"""Canonical, deterministic Department 5 publication eligibility policy."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from typing import Any
from src.project_sequence import sequence_error


class DecisionType(str, Enum):
    ELIGIBLE="ELIGIBLE"
    DEFERRED_NOT_BEFORE="DEFERRED_NOT_BEFORE"
    DEFERRED_GLOBAL_COOLDOWN="DEFERRED_GLOBAL_COOLDOWN"
    DEFERRED_PROJECT_COOLDOWN="DEFERRED_PROJECT_COOLDOWN"
    DEFERRED_SURFACE_COOLDOWN="DEFERRED_SURFACE_COOLDOWN"
    DEFERRED_CROSS_SURFACE_REUSE="DEFERRED_CROSS_SURFACE_REUSE"
    BLOCKED_DUPLICATE="BLOCKED_DUPLICATE"
    BLOCKED_INVALID_CONTRACT="BLOCKED_INVALID_CONTRACT"
    BLOCKED_UNCERTAIN_PUBLICATION="BLOCKED_UNCERTAIN_PUBLICATION"
    BLOCKED_PROJECT_SEQUENCE="BLOCKED_PROJECT_SEQUENCE"
    NO_ELIGIBLE_PUBLICATION="NO_ELIGIBLE_PUBLICATION"


@dataclass(frozen=True)
class EligibilityDecision:
    queue_item_id: str | None
    decision: str
    surface: str | None
    format: str | None
    reason: str
    conflicting_queue_item_id: str | None = None
    conflicting_receipt_id: str | None = None
    next_eligible_at: str | None = None

    def to_dict(self)->dict[str,Any]:return asdict(self)


DEFAULT_POLICY={
    "minimum_global_interval_minutes":60,
    "minimum_feed_interval_minutes":720,
    "minimum_story_interval_minutes":120,
    "minimum_project_interval_minutes":180,
    "cross_surface_reuse_cooldown_minutes":1440,
    "same_story_reuse_cooldown_minutes":10080,
    "allow_same_surface_recycling":False,
    "simultaneous_cross_surface_allowed":False,
}


def publication_surface(package_type:str|None,platform:str|None)->str:
    return "story" if str(package_type).casefold()=="story" or "story" in str(platform).casefold() else "feed"


def publication_format(package_type:str|None,surface:str)->str:
    return "story_sequence" if surface=="story" else "carousel" if package_type=="carousel" else "single_image"


def semantic_creative_identity(project:str,media_hashes:list[str],package_type:str|None)->str:
    value={"project_id":project,"media_hashes":list(media_hashes),"composition":"carousel" if package_type=="carousel" else "single"}
    return "creative_"+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:24]


def select_next_eligible_publication(queue:dict[str,Any],receipts:list[dict[str,Any]],*,now:datetime,config:dict[str,Any])->dict[str,Any]:
    if now.tzinfo is None or now.utcoffset() is None:raise ValueError("Authoritative scheduling requires a timezone-aware clock")
    now=now.astimezone(timezone.utc);policy={**DEFAULT_POLICY,**config.get("scheduling_policy",{})};decisions=[];eligible=[]
    successful=[x for x in receipts if x.get("status") in {"published","published_with_warnings"}]
    for item in queue.get("items",[]):
        decision=_evaluate(item,successful,now,policy);decisions.append(decision.to_dict())
        if decision.decision==DecisionType.ELIGIBLE.value:eligible.append(item)
    eligible.sort(key=lambda x:(int((x.get("project_sequence") or {}).get("preferred_order",5)),-int(x.get("priority",0)),str(x.get("scheduled_at_utc") or x.get("created_at") or ""),str(x.get("queue_item_id") or "")))
    if not eligible:return {"decision":DecisionType.NO_ELIGIBLE_PUBLICATION.value,"selected_queue_item_id":None,"reason":"No queued publication is currently safe.","evaluated":decisions,"evaluated_at":now.isoformat()}
    selected=eligible[0];return {"decision":DecisionType.ELIGIBLE.value,"selected_queue_item_id":selected.get("queue_item_id"),"reason":"Highest-priority currently eligible publication selected with deterministic tie-breaking.","evaluated":decisions,"evaluated_at":now.isoformat()}


def _evaluate(item:dict[str,Any],receipts:list[dict[str,Any]],now:datetime,policy:dict[str,Any])->EligibilityDecision:
    qid=str(item.get("queue_item_id") or "");surface=str(item.get("surface") or publication_surface(item.get("package_type"),item.get("platform")));fmt=str(item.get("format") or publication_format(item.get("package_type"),surface));status=item.get("status")
    if status=="publishing_uncertain":return EligibilityDecision(qid,DecisionType.BLOCKED_UNCERTAIN_PUBLICATION.value,surface,fmt,"Remote publication outcome is uncertain.")
    if status not in {"queued","scheduled","preflight_ready","retry_wait"}:return EligibilityDecision(qid,DecisionType.BLOCKED_INVALID_CONTRACT.value,surface,fmt,f"Queue state {status!r} is not eligible.")
    if policy.get("require_explicit_schedule") and not item.get("scheduled_at_utc"):
        return EligibilityDecision(qid,DecisionType.DEFERRED_NOT_BEFORE.value,surface,fmt,"Automatic publishing requires an explicit saved schedule.")
    sequence_block=sequence_error(item,receipts)
    if sequence_block:return EligibilityDecision(qid,DecisionType.BLOCKED_PROJECT_SEQUENCE.value,surface,fmt,sequence_block)
    due=_parse(item.get("next_retry_at") or item.get("scheduled_at_utc"))
    if due and due>now:return EligibilityDecision(qid,DecisionType.DEFERRED_NOT_BEFORE.value,surface,fmt,"Publication not-before time has not arrived.",next_eligible_at=due.isoformat())
    identity=item.get("semantic_creative_identity") or semantic_creative_identity(str(item.get("project_id")),list(item.get("image_hashes",[])),item.get("package_type"));media=set(item.get("image_hashes",[]));published=sorted(receipts,key=lambda x:_parse(x.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),reverse=True)
    for receipt in published:
        if receipt.get("project_id")!=item.get("project_id"):continue
        prior_surface=str(receipt.get("surface") or publication_surface(receipt.get("format"),receipt.get("platform")));prior_identity=receipt.get("semantic_creative_identity");prior_media=set(receipt.get("media_hashes",[]));same=identity==prior_identity or (bool(media) and media==prior_media and fmt==receipt.get("format"))
        if prior_surface==surface and same and not policy["allow_same_surface_recycling"]:return EligibilityDecision(qid,DecisionType.BLOCKED_DUPLICATE.value,surface,fmt,"The semantic creative was already published on this surface.",conflicting_receipt_id=receipt.get("receipt_id"))
    latest=_latest(published)
    decision=_cooldown(qid,surface,fmt,latest,now,int(policy["minimum_global_interval_minutes"]),DecisionType.DEFERRED_GLOBAL_COOLDOWN,"Global publication spacing")
    if decision:return decision
    project_latest=_latest([x for x in published if x.get("project_id")==item.get("project_id")])
    decision=_cooldown(qid,surface,fmt,project_latest,now,int(policy["minimum_project_interval_minutes"]),DecisionType.DEFERRED_PROJECT_COOLDOWN,"Project publication spacing")
    if decision:return decision
    surface_latest=_latest([x for x in published if (x.get("surface") or publication_surface(x.get("format"),x.get("platform")))==surface])
    minutes=int(policy["minimum_story_interval_minutes"] if surface=="story" else policy["minimum_feed_interval_minutes"]);decision=_cooldown(qid,surface,fmt,surface_latest,now,minutes,DecisionType.DEFERRED_SURFACE_COOLDOWN,f"{surface.title()} publication spacing")
    if decision:return decision
    for receipt in published:
        if receipt.get("project_id")!=item.get("project_id"):continue
        prior_surface=str(receipt.get("surface") or publication_surface(receipt.get("format"),receipt.get("platform")));overlap=media & set(receipt.get("media_hashes",[]))
        if prior_surface!=surface and overlap:
            at=_parse(receipt.get("published_at"));until=at+timedelta(minutes=int(policy["cross_surface_reuse_cooldown_minutes"])) if at else None
            if until and now<until and not policy["simultaneous_cross_surface_allowed"]:return EligibilityDecision(qid,DecisionType.DEFERRED_CROSS_SURFACE_REUSE.value,surface,fmt,"Approved cross-surface reuse is inside its cooldown.",conflicting_receipt_id=receipt.get("receipt_id"),next_eligible_at=until.isoformat())
    return EligibilityDecision(qid,DecisionType.ELIGIBLE.value,surface,fmt,"All publication safety and cooldown policies pass.")


def _latest(values:list[dict[str,Any]])->dict[str,Any]|None:return max(values,key=lambda x:_parse(x.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),default=None)
def _cooldown(qid,surface,fmt,receipt,now,minutes,kind,label):
    at=_parse(receipt.get("published_at")) if receipt else None;until=at+timedelta(minutes=minutes) if at else None
    return EligibilityDecision(qid,kind.value,surface,fmt,f"{label} is active.",conflicting_receipt_id=receipt.get("receipt_id"),next_eligible_at=until.isoformat()) if until and now<until else None
def _parse(value:Any)->datetime|None:
    if not value:return None
    parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:raise ValueError("Authoritative publication timestamps must include timezone offsets")
    return parsed.astimezone(timezone.utc)
