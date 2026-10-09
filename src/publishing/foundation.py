"""Persistent queue, scheduling, preflight, and dry-run publication adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from src.content.visual_purpose import assess_visual_purpose, load_visual_reviews, validate_overview_slides
from src.project_sequence import role
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image

from src.brand_kit import approved_config_hash
from src.creative.production_contract import CONTRACT_VERSION, validate_publication_package
from src.platforms import DestinationOverride, Platform, apply_destination_override
from src.publishing.eligibility import publication_format, publication_surface, semantic_creative_identity
from src.publishing.ledger import PublicationLedger
from src.plan_integrity import validate_package_layouts
from src.knowledge.consumer import require_canonical_graph
from src.execution.lineage import attach_lineage, artifact_fingerprint, canonical_graph_fingerprint, require_lineage

QUEUE_VERSION="3.1.0";QUEUE_RECONCILIATION_VERSION="3.1.0";SCHEDULE_VERSION="1.1.0";PREFLIGHT_VERSION="1.3.0";ADAPTER_VERSION="1.1.0";MANIFEST_VERSION="2.0.0"
QUEUE_STATUSES={"queued","scheduled","reserved","publishing","publishing_uncertain","published","published_with_warnings","retry_wait","failed","blocked","cancelled","superseded"}
INTERNAL=re.compile(r"without adding unverified claims|based on approved source material|this image has been validated|no unsupported room claims|according to the source file|verified asset|source-supported visual",re.I)


class PlatformAdapter(ABC):
    adapter_name="abstract";platform="platform-neutral";supports_single_image=True;supports_carousel=True;supports_story=True;supports_alt_text=True;supports_scheduling=False;max_caption_length=2200;max_hashtags=30;supported_image_formats=("JPEG","PNG","WEBP");supported_aspect_ratios=("1:1","4:5","9:16","1.91:1")
    def validate_credentials(self)->dict[str,Any]:return {"valid":True,"required":False}
    @abstractmethod
    def validate_package(self,package:dict[str,Any])->list[str]:...
    @abstractmethod
    def prepare_payload(self,package:dict[str,Any],item:dict[str,Any])->dict[str,Any]:...
    @abstractmethod
    def publish(self,payload:dict[str,Any],item:dict[str,Any])->dict[str,Any]:...
    def get_status(self,receipt:dict[str,Any])->str:return str(receipt.get("status","unknown"))
    def normalize_error(self,error:Exception)->dict[str,Any]:return {"classification":"transient" if isinstance(error,(TimeoutError,ConnectionError)) else "permanent","message":str(error)}
    def build_receipt(self,**values:Any)->dict[str,Any]:return values


class MockPlatformAdapter(PlatformAdapter):
    adapter_name="mock";platform="platform-neutral";supports_scheduling=True
    def __init__(self,fail_as:str|None=None)->None:self.fail_as=fail_as
    def validate_package(self,package:dict[str,Any])->list[str]:
        errors=[];kind=package.get("package_type")
        if kind=="carousel" and not self.supports_carousel:errors.append("unsupported carousel")
        if kind=="single_post" and not self.supports_single_image:errors.append("unsupported single image")
        if kind=="story" and (not self.supports_story or len(_slides(package))!=1):errors.append("unsupported or invalid V1 Story")
        return errors
    def prepare_payload(self,package:dict[str,Any],item:dict[str,Any])->dict[str,Any]:
        caption=package.get("master_caption") or package.get("caption") or {};slides=package.get("slides") or [{**package.get("image",{}),"alt_text":package.get("alt_text"),"provenance_id":package.get("provenance_id"),"slide_number":1}]
        return {"dry_run":True,"adapter":"mock","platform":package.get("platform"),"package_type":package.get("package_type"),"package_id":package.get("package_id"),"media_paths":[x.get("image_path") for x in slides],"slide_order":[x.get("slide_number") for x in slides],"caption":caption.get("full_caption"),"hashtags":[x.get("hashtag") for x in package.get("hashtags",[])],"alt_text":[x.get("alt_text") for x in slides],"scheduled_at_local":item.get("scheduled_at_local"),"scheduled_at_utc":item.get("scheduled_at_utc"),"idempotency_key":item["idempotency_key"],"package_hash":item["package_hash"],"provenance_refs":[x.get("provenance_id") for x in slides]}
    def publish(self,payload:dict[str,Any],item:dict[str,Any])->dict[str,Any]:
        if self.fail_as:raise InjectedAdapterFailure(self.fail_as)
        payload_hash=_json_hash(payload);now=_now()
        return self.build_receipt(receipt_id=_stable("receipt",item["idempotency_key"],payload_hash),queue_item_id=item["queue_item_id"],adapter="mock",dry_run=True,status="simulated_success",platform=item["platform"],package_id=item["package_id"],idempotency_key=item["idempotency_key"],payload_hash=payload_hash,simulated_remote_id=_stable("mock-remote",item["idempotency_key"]),created_at=now)


class InjectedAdapterFailure(RuntimeError):
    def __init__(self,classification:str)->None:self.classification=classification;super().__init__(f"injected {classification} adapter failure")


class PublishingFoundation:
    def __init__(self,project:str,root:Path,*,publish_target:str="use_planned")->None:
        self.project,self.root=project,root;self.publish_target=DestinationOverride.parse(publish_target);self.output=root/"output";self.directory=self.output/"publishing";self.config_path=root/"input"/"publishing"/"publishing-config.json";self.queue_path=self.directory/f"{project}-publishing-queue.json";self.schedule_path=self.directory/f"{project}-schedule.json";self.preflight_path=self.directory/f"{project}-preflight.json";self.manifest_path=self.directory/f"{project}-publication-manifest.json";self.payload_dir=self.directory/"mock-payloads"/project;self.lock_path=self.directory/f".{_slug(project)}.lock"
    def _read_project_artifact(self, path: Path)->dict[str,Any]:
        value=_read(path)
        if value.get("project_id") != self.project:
            raise ValueError("Publishing blocked: missing or cross-project persisted artifact ownership")
        if path == self.queue_path and any(item.get("project_id") != self.project for item in value.get("items", [])):
            raise ValueError("Publishing blocked: cross-project queue item ownership")
        return value

    def _config(self)->dict[str,Any]:
        if not self.config_path.is_file():raise ValueError("Publishing config missing")
        value=_read(self.config_path);_timezone(value.get("timezone",""));return value
    def _inputs(self)->dict[str,Any]:
        paths={"packages":self.output/"post-packages"/f"{self.project}-post-packages.json","qa":self.output/"qa"/f"{self.project}-post-package-qa.json","review":self.output/"social-review"/f"{self.project}-social-review.json","provenance":self.output/"provenance"/f"{self.project}-provenance-audit.json","brand":self.root/"input"/"brand"/"brand-config.json","knowledge":self.output/"knowledge"/f"{self.project}.json"}
        missing=[str(x) for x in paths.values() if not x.is_file()]
        if missing:raise ValueError("Publishing inputs missing: "+", ".join(missing))
        data={k:_read(v) for k,v in paths.items()};plan_path=self.output/"plan-intelligence"/f"{self.project}-plan-intelligence.json";data["plan_intelligence"]=_read(plan_path) if plan_path.is_file() else {"project_id":self.project,"assets":[]}
        asset_path=self.output/"asset-intelligence"/f"{self.project}-asset-intelligence.json"
        data["visual_assets"]=load_visual_reviews(self.root,_read(asset_path).get("assets",[]) if asset_path.is_file() else [])
        require_canonical_graph(data["knowledge"], expected_project=self.project)
        if any(data[k].get("project_id") != self.project for k in
               ("packages", "qa", "review", "provenance", "plan_intelligence")):
            raise ValueError("Publishing blocked: missing or cross-project input ownership")
        if any(asset.get("project_id", asset.get("project")) != self.project
               for asset in data["visual_assets"]):
            raise ValueError("Publishing blocked: cross-project visual asset")
        d2_fingerprint=canonical_graph_fingerprint(data["knowledge"])
        package_fp=str(data["packages"].get("artifact_fingerprint") or artifact_fingerprint(data["packages"]))
        qa_fp=str(data["qa"].get("artifact_fingerprint") or artifact_fingerprint(data["qa"]))
        require_lineage(data["packages"],expected_stage="post-package-manifest",canonical_fingerprint=d2_fingerprint)
        require_lineage(data["qa"],expected_stage="post-package-qa",canonical_fingerprint=d2_fingerprint,parents={"post_packages":package_fp})
        require_lineage(data["review"],expected_stage="social-review",canonical_fingerprint=d2_fingerprint,parents={"post_packages":package_fp,"post_package_qa":qa_fp})
        data["d2_fingerprint"]=d2_fingerprint;data["package_fingerprint"]=package_fp;data["qa_fingerprint"]=qa_fp;data["review_fingerprint"]=str(data["review"].get("artifact_fingerprint") or artifact_fingerprint(data["review"]))
        releases=sorted((self.output/"releases"/self.project).glob("release-*/manifest.json"));
        if not releases:raise ValueError("Publishing requires a valid release")
        package_release_ids={x.get("release_id") for x in data["packages"].get("packages",[]) if x.get("release_id")}
        selected=next((path for path in reversed(releases) if _read(path).get("status") in {"completed","completed_with_warnings"} and (not package_release_ids or _read(path).get("release_id") in package_release_ids)),None)
        if selected is None:raise ValueError("Publishing requires a successful release matching the current package manifest")
        from src.project_sequence import campaign_scope
        data["campaign_scope"]=campaign_scope(self.root,self.project)
        data["release"]=_read(selected)
        if data["release"].get("project_id") != self.project:
            raise ValueError("Publishing blocked: missing or cross-project release ownership")
        data["release_path"]=selected;return data
    def queue_reconciliation_reason(self)->str|None:
        if not self.queue_path.is_file():return "queue artifact missing"
        try:queue=self._read_project_artifact(self.queue_path);ctx=self._inputs()
        except (OSError,ValueError):return "queue artifact unreadable"
        if queue.get("queue_schema_version")!=QUEUE_VERSION:return "outdated queue schema"
        if queue.get("queue_reconciliation_version")!=QUEUE_RECONCILIATION_VERSION:return "reconciliation policy changed"
        # Only current-version queues are expected to carry Phase 8 lineage.
        if all(key in ctx for key in ("d2_fingerprint","package_fingerprint","review_fingerprint")):
            try:
                require_lineage(queue,expected_stage="publishing-queue",canonical_fingerprint=ctx["d2_fingerprint"],parents={"post_packages":ctx["package_fingerprint"],"social_review":ctx["review_fingerprint"]})
            except ValueError as error:
                return str(error)
        current=set()
        for package in ctx["packages"].get("packages",[]):
            planned=_planned_destinations(package);requested=apply_destination_override(planned,self.publish_target)
            for destination in requested:current.add(_publication_identity(self.project,package,destination.value))
        represented={x.get("idempotency_key") for x in queue.get("items",[]) if x.get("status") not in {"superseded","cancelled"}}
        if represented!=current:return "current package jobs differ from queue state"
        return None
    def queue(self)->Path:
        config=self._config();ctx=self._inputs();qa={x.get("package_id"):x for x in ctx["qa"].get("items",[])};review={x.get("package_id"):x for x in ctx["review"].get("packages",[])};now=_now()
        with _lock(self.lock_path):
            new_authority=not self.queue_path.is_file()
            existing=self._read_project_artifact(self.queue_path) if not new_authority else {"project_id":self.project,"items":[],"history":[],"created_at":now};by_key={x.get("publication_identity") or x.get("idempotency_key"):x for x in existing.get("items",[])};items=[]
            if new_authority and not self.manifest_path.exists():_atomic_json(self.manifest_path,_empty_manifest(self.project,ctx["release"].get("release_id")))
            manifest=self._read_project_artifact(self.manifest_path) if self.manifest_path.is_file() else {};real_receipts=manifest.get("real_receipts",[]) if isinstance(manifest,dict) else [];ledger=PublicationLedger(self.root);ledger.initialize(fresh=new_authority and not real_receipts,confirmed_receipts=real_receipts)
            package_state=ctx["packages"].get("status");manifest_valid=ctx["packages"].get("semantic_manifest_valid") is True
            if not manifest_valid or package_state in {"failed","blocked","no_content_unexpected"}:
                value={**existing,"project_id":self.project,"queue_version":QUEUE_VERSION,"queue_schema_version":QUEUE_VERSION,"queue_reconciliation_version":QUEUE_RECONCILIATION_VERSION,"reconciliation_status":"blocked_invalid_upstream_package_state","reconciliation_reason":f"package generation state is {package_state or 'unknown'}; existing current jobs preserved","updated_at":now,"summary":_queue_summary(existing.get("items",[]))};value=attach_lineage(value,stage="publishing-queue",canonical_fingerprint=ctx["d2_fingerprint"],parents={"post_packages":ctx["package_fingerprint"],"social_review":ctx["review_fingerprint"]});_atomic_json(self.queue_path,value);return self.queue_path
            for package in ctx["packages"].get("packages",[]):
              planned=_planned_destinations(package);requested=apply_destination_override(planned,self.publish_target)
              for destination in requested:
                package_hash=_json_hash(package);key=_publication_identity(self.project,package,destination.value);old=by_key.get(key);errors=_queue_blockers(package,qa.get(package.get("package_id"),{}),review.get(package.get("package_id"),{}),ctx)
                surface=publication_surface(package.get("package_type"),package.get("platform"));fmt=publication_format(package.get("package_type"),surface);image_hashes=_image_hashes(package);creative_identity=semantic_creative_identity(self.project,image_hashes,package.get("package_type"))
                if old:item={**old,"release_id":package.get("release_id"),"package_id":package.get("package_id"),"package_hash":package_hash,"surface":surface,"format":fmt,"semantic_creative_identity":creative_identity,"image_hashes":image_hashes,"updated_at":now};item["warnings"]=list(dict.fromkeys(item.get("warnings",[])));item["errors"]=errors;item["status"]="blocked" if errors and item.get("status") not in {"published","published_with_warnings","publishing_uncertain"} else item.get("status","queued")
                else:item={"queue_item_id":_stable("queue",key),"project_id":self.project,"release_id":package.get("release_id"),"package_id":package.get("package_id"),"package_type":package.get("package_type"),"production_contract_version":package.get("creative_production_contract_version"),"platform":destination.value,"surface":surface,"format":fmt,"semantic_creative_identity":creative_identity,"planned_destinations":[x.value for x in planned],"actual_requested_destinations":[x.value for x in requested],"destination_override":self.publish_target.value,"content_version":package.get("content_version",package_hash[:12]),"language":package.get("language"),"scheduled_at":None,"scheduled_at_local":None,"scheduled_at_utc":None,"timezone":config["timezone"],"priority":100,"status":"blocked" if errors else "queued","attempt_count":0,"max_attempts":config["retry_policy"]["max_attempts"],"next_retry_at":None,"publication_identity":key,"idempotency_key":key,"package_hash":package_hash,"image_hashes":image_hashes,"caption_hash":_json_hash(package.get("master_caption") or package.get("caption") or {}),"adapter_name":"mock","created_at":now,"updated_at":now,"warnings":[],"errors":errors}
                item["project_sequence"]=package.get("project_sequence")
                item["campaign_scope"]=package.get("campaign_scope")
                items.append(item)
            current_keys={x["idempotency_key"] for x in items}
            for old in existing.get("items",[]):
                if old.get("idempotency_key") not in current_keys and old.get("status") not in {"cancelled","superseded"}:
                    history=list(old.get("status_history",[]));history.append({"from":old.get("status"),"to":"superseded","at":now,"reason":"queue reconciliation"});items.append({**old,"previous_status":old.get("status"),"status_history":history,"status":"superseded","updated_at":now})
            value={**existing,"project_id":self.project,"queue_version":QUEUE_VERSION,"queue_schema_version":QUEUE_VERSION,"queue_reconciliation_version":QUEUE_RECONCILIATION_VERSION,"items":items,"updated_at":now};value=ledger.reconcile_queue(value);value["summary"]=_queue_summary(value["items"]);value=attach_lineage(value,stage="publishing-queue",canonical_fingerprint=ctx["d2_fingerprint"],parents={"post_packages":ctx["package_fingerprint"],"social_review":ctx["review_fingerprint"]});_atomic_json(self.queue_path,value)
        return self.queue_path
    def schedule(self)->Path:
        config=self._config();queue=self._read_project_artifact(self.queue_path);mode=config.get("default_mode","manual");tz=_timezone(config["timezone"]);items=[];used=[]
        manual=config.get("manual_schedule",{});start=config.get("sequential_start_at")
        active=sorted((x for x in queue.get("items",[]) if _is_active_job(x)),key=lambda x:(-int(x.get("priority",0)),x.get("created_at","")))
        for position,item in enumerate(active):
            local_text=manual.get(item["queue_item_id"])
            if mode=="sequential" and start:local_text=(datetime.fromisoformat(start)+timedelta(minutes=position*int(config["minimum_spacing_minutes"]))).isoformat()
            warnings=[];blockers=[];local=utc=None
            if local_text:
                try:
                    parsed=datetime.fromisoformat(local_text);parsed=parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz);local=parsed.isoformat();utc=parsed.astimezone(timezone.utc).isoformat()
                    if parsed<datetime.now(tz):blockers.append("scheduled timestamp is in the past")
                    if any(abs((parsed-x).total_seconds())<int(config["minimum_spacing_minutes"])*60 for x in used):blockers.append("minimum spacing violated")
                    if sum(x.date()==parsed.date() for x in used)>=int(config["max_posts_per_day"]):blockers.append("maximum posts per day exceeded")
                    if not blockers:used.append(parsed)
                except ValueError:blockers.append("invalid scheduled timestamp")
            status="blocked" if blockers else "scheduled" if local else item["status"]
            if item["status"] in {"blocked","cancelled","superseded"}:status=item["status"]
            items.append({"queue_item_id":item["queue_item_id"],"mode":mode,"timezone":config["timezone"],"scheduled_at_local":local,"scheduled_at_utc":utc,"status":status,"warnings":warnings,"blockers":blockers})
        ignored=queue.get("items",[]);value={"project_id":self.project,"schedule_version":SCHEDULE_VERSION,"mode":mode,"timezone":config["timezone"],"items":items,"summary":{"scheduler_active_input":len(active),"scheduled_active":sum(bool(x.get("scheduled_at_utc")) for x in items),"unscheduled_active":sum(not x.get("scheduled_at_utc") for x in items),"superseded_ignored":sum(x.get("status")=="superseded" for x in ignored),"cancelled_ignored":sum(x.get("status")=="cancelled" for x in ignored),"published_ignored":sum(x.get("status") in {"published","published_with_warnings"} for x in ignored)},"created_at":_now()};_atomic_json(self.schedule_path,value);self._merge_schedule(items);return self.schedule_path
    def _merge_schedule(self,schedule:list[dict[str,Any]])->None:
        by_id={x["queue_item_id"]:x for x in schedule}
        with _lock(self.lock_path):
            queue=self._read_project_artifact(self.queue_path)
            for item in queue.get("items",[]):
                value=by_id.get(item["queue_item_id"],{});item.update(scheduled_at=value.get("scheduled_at_utc"),scheduled_at_local=value.get("scheduled_at_local"),scheduled_at_utc=value.get("scheduled_at_utc"),timezone=value.get("timezone",item.get("timezone")));item["status"]=value.get("status",item["status"]);item["updated_at"]=_now()
            queue["summary"]=_queue_summary(queue["items"]);queue["updated_at"]=_now()
            ctx=self._inputs()
            queue=attach_lineage(queue,stage="publishing-queue",canonical_fingerprint=ctx["d2_fingerprint"],parents={"post_packages":ctx["package_fingerprint"],"social_review":ctx["review_fingerprint"]})
            _atomic_json(self.queue_path,queue)
    def preflight(self)->Path:
        ctx=self._inputs();queue=self._read_project_artifact(self.queue_path);require_lineage(queue,expected_stage="publishing-queue",canonical_fingerprint=ctx["d2_fingerprint"],parents={"post_packages":ctx["package_fingerprint"],"social_review":ctx["review_fingerprint"]});packages={x.get("package_id"):x for x in ctx["packages"].get("packages",[])};manifest=self._read_project_artifact(self.manifest_path) if self.manifest_path.is_file() else {};success={x.get("idempotency_key") for x in manifest.get("mock_receipts",[]) if x.get("status")=="simulated_success"};results=[]
        for item in queue.get("items",[]):
            skip=_preflight_skip_status(item)
            if skip:
                blocked=skip=="blocked";results.append({"queue_item_id":item["queue_item_id"],"status":skip,"score":0 if blocked else None,"checks":{"queue_admission":"failed"} if blocked else {},"blockers":list(item.get("errors") or ["queue admission blocked"]) if blocked else [],"warnings":[],"validated_at":_now()});continue
            package=packages.get(item.get("package_id"));checks,blockers,warnings=_preflight_checks(item,package,ctx,success);score=sum(weight for name,weight in (("package_integrity",20),("media_integrity",20),("content_integrity",15),("provenance",15),("brand_integrity",10),("schedule_integrity",10),("idempotency",10)) if checks.get(name)=="passed");status="blocked" if blockers else "ready_with_warnings" if warnings else "ready";simulation_warning=item.get("idempotency_key") in success;results.append({"queue_item_id":item["queue_item_id"],"status":status,"ready_with_warnings_due_to_existing_simulation":simulation_warning,"score":min(score,79) if blockers else score,"checks":checks,"blockers":blockers,"warnings":warnings,"validated_at":_now()})
        value={"project_id":self.project,"preflight_version":PREFLIGHT_VERSION,"items":results,"summary":{"preflight_considered":sum(x["status"] in {"ready","ready_with_warnings","blocked"} for x in results),"ready":sum(x["status"]=="ready" for x in results),"ready_with_warnings":sum(x["status"]=="ready_with_warnings" for x in results),"blocked":sum(x["status"]=="blocked" for x in results),"superseded_skipped":sum(x["status"]=="superseded_skipped" for x in results),"cancelled_skipped":sum(x["status"]=="cancelled_skipped" for x in results),"already_published_skipped":sum(x["status"]=="already_published_skipped" for x in results)},"created_at":_now()};value=attach_lineage(value,stage="publishing-preflight",canonical_fingerprint=ctx["d2_fingerprint"],parents={"publishing_queue":str(queue.get("artifact_fingerprint") or artifact_fingerprint(queue)),"post_packages":ctx["package_fingerprint"],"social_review":ctx["review_fingerprint"]});_atomic_json(self.preflight_path,value);self._merge_preflight(results);return self.preflight_path
    def _merge_preflight(self,results:list[dict[str,Any]])->None:
        states={x["queue_item_id"]:x for x in results}
        with _lock(self.lock_path):
            queue=self._read_project_artifact(self.queue_path)
            for item in queue["items"]:
                result=states.get(item["queue_item_id"],{})
                if result.get("status") in {"ready","ready_with_warnings"}:item["status"]="preflight_ready"
                elif result.get("blockers")==["duplicate publication or actively publishing"]:item["status"]="preflight_ready";item["warnings"]=list(dict.fromkeys([*item.get("warnings",[]),"dry-run success already recorded; adapter will not run again"]))
                elif result.get("status")=="blocked":item["status"]="blocked"
                item["updated_at"]=_now()
            queue["summary"]=_queue_summary(queue["items"]);queue["updated_at"]=_now()
            ctx=self._inputs()
            queue=attach_lineage(queue,stage="publishing-queue",canonical_fingerprint=ctx["d2_fingerprint"],parents={"post_packages":ctx["package_fingerprint"],"social_review":ctx["review_fingerprint"]})
            _atomic_json(self.queue_path,queue)
    def mock_publish(self,fail_as:str|None=None)->Path:
        adapter=MockPlatformAdapter(fail_as);queue=self._read_project_artifact(self.queue_path);preflight={x["queue_item_id"]:x for x in self._read_project_artifact(self.preflight_path).get("items",[])};ctx=self._inputs();require_lineage(queue,expected_stage="publishing-queue",canonical_fingerprint=ctx["d2_fingerprint"],parents={"post_packages":ctx["package_fingerprint"],"social_review":ctx["review_fingerprint"]});packages={x["package_id"]:x for x in ctx["packages"].get("packages",[])};manifest=self._read_project_artifact(self.manifest_path) if self.manifest_path.is_file() else _empty_manifest(self.project,ctx["release"].get("release_id"));receipts=manifest.get("mock_receipts",[]);successful={x.get("idempotency_key"):x for x in receipts if x.get("status")=="simulated_success"};history=manifest.get("publication_history",[]);attempted=generated=skipped=0;skip_categories={"superseded_skipped":0,"existing_successful_simulation_reused":0,"preflight_blocked_active":0,"other_skipped":0}
        for item in queue.get("items",[]):
            eligible,reason=_adapter_eligibility(item,preflight.get(item["queue_item_id"],{}),successful)
            if not eligible:
                item["adapter_skipped"]=True;item["skip_reason"]=reason;skipped+=1
                category="superseded_skipped" if item.get("status")=="superseded" else "existing_successful_simulation_reused" if reason=="already_published_duplicate" else "preflight_blocked_active" if reason=="preflight_blocked" and _is_active_job(item) else "other_skipped";skip_categories[category]+=1
                if reason=="already_published_duplicate":history=_append_history(history,item,"simulated_success_already_recorded","mock",successful[item["idempotency_key"]].get("receipt_id"),successful[item["idempotency_key"]].get("payload_hash"))
                continue
            if item["idempotency_key"] in successful:
                history=_append_history(history,item,"simulated_success_already_recorded","mock",successful[item["idempotency_key"]].get("receipt_id"),successful[item["idempotency_key"]].get("payload_hash"));continue
            package=packages[item["package_id"]];errors=validate_package_layouts(package,ctx.get("plan_intelligence",{}),expected_project=self.project)+adapter.validate_package(package)
            if errors:self._fail_item(item,"validation","; ".join(errors),False);history=_append_history(history,item,"failed","mock",None,None,"; ".join(errors));continue
            payload=adapter.prepare_payload(package,item);payload_path=self.payload_dir/f"{item['queue_item_id']}.json";_atomic_json(payload_path,payload)
            try:
                attempted+=1;receipt=adapter.publish(payload,item);receipts.append(receipt);generated+=1;history=_append_history(history,item,"simulated_success","mock",receipt["receipt_id"],receipt["payload_hash"])
            except Exception as error:
                classification=getattr(error,"classification",adapter.normalize_error(error)["classification"]);transient=classification in {"rate_limit","network","transient"};self._fail_item(item,classification,str(error),transient);history=_append_history(history,item,"failed","mock",None,_json_hash(payload),str(error))
        eligible_count=sum(preflight.get(x["queue_item_id"],{}).get("status") in {"ready","ready_with_warnings"} and _is_active_job(x) for x in queue.get("items",[]));manifest.update(mock_receipts=_dedupe(receipts,"receipt_id"),publication_history=_dedupe(history,"history_id"),last_adapter_run={"preflight_eligible":eligible_count,"adapter_attempted":attempted,"adapter_skipped":skipped,"skip_categories":skip_categories,"receipts_generated":generated,"external_requests":0},updated_at=_now());_atomic_json(self.manifest_path,manifest);self._write_queue_items(queue,item_by_id={x["queue_item_id"]:x for x in queue["items"]});return self.manifest_path
    def _fail_item(self,item:dict[str,Any],classification:str,message:str,transient:bool)->None:
        item["attempt_count"]+=1;item["errors"].append({"classification":classification,"message":message,"at":_now()});can_retry=transient and item["attempt_count"]<item["max_attempts"]
        if can_retry:
            policy=self._config()["retry_policy"];delay=float(policy["initial_delay_minutes"])*(float(policy["backoff_multiplier"])**(item["attempt_count"]-1));item["status"]="retry_wait";item["next_retry_at"]=(datetime.now(timezone.utc)+timedelta(minutes=delay)).isoformat()
        else:item["status"]="failed";item["next_retry_at"]=None
    def _write_queue_items(self,queue:dict[str,Any],item_by_id:dict[str,dict[str,Any]])->None:
        with _lock(self.lock_path):
            current=self._read_project_artifact(self.queue_path);current["items"]=[item_by_id.get(x["queue_item_id"],x) for x in current["items"]];current["summary"]=_queue_summary(current["items"]);current["updated_at"]=_now();ctx=self._inputs();current=attach_lineage(current,stage="publishing-queue",canonical_fingerprint=ctx["d2_fingerprint"],parents={"post_packages":ctx["package_fingerprint"],"social_review":ctx["review_fingerprint"]});_atomic_json(self.queue_path,current)
    def manifest(self)->Path:
        ctx=self._inputs();queue=self._read_project_artifact(self.queue_path);schedule=self._read_project_artifact(self.schedule_path) if self.schedule_path.is_file() else {};preflight=self._read_project_artifact(self.preflight_path) if self.preflight_path.is_file() else {};existing=self._read_project_artifact(self.manifest_path) if self.manifest_path.is_file() else _empty_manifest(self.project,ctx["release"].get("release_id"));run=existing.get("last_adapter_run",{});items=queue.get("items",[]);receipts=[*existing.get("mock_receipts",[]),*existing.get("real_receipts",[])];categories=run.get("skip_categories",{});existing.update(project_id=self.project,release_id=ctx["release"].get("release_id"),manifest_version=MANIFEST_VERSION,queue_items=items,scheduled_items=schedule.get("items",[]),preflight_results=preflight.get("items",[]),real_receipts=existing.get("real_receipts",[]),historical_totals={"total_queue_records":len(items),"total_receipts":len(receipts),"total_history_entries":len(existing.get("publication_history",[]))},current_state={"active_jobs":sum(_is_active_job(x) for x in items),"superseded_jobs":sum(x.get("status")=="superseded" for x in items)},current_run={"preflight_eligible":run.get("preflight_eligible",0),"existing_successful_simulations_reused":categories.get("existing_successful_simulation_reused",0),"adapter_attempts":run.get("adapter_attempted",0),"adapter_skips":run.get("adapter_skipped",0),"skip_categories":categories,"new_receipts_generated":run.get("receipts_generated",0)},retries=[x for x in items if x.get("attempt_count",0)],failures=[x for x in items if x.get("status")=="failed"],updated_at=_now());_atomic_json(self.manifest_path,existing);return self.manifest_path
    def show_queue(self)->str:
        queue=self._read_project_artifact(self.queue_path);lines=[f"Publishing Queue - {self.project}",f"Items: {len(queue.get('items',[]))}"]
        lines += [f"- {x['queue_item_id']}: {x['status']} | {x['platform']} | {x['language']} | scheduled={x.get('scheduled_at_local') or 'not scheduled'} | attempts={x['attempt_count']}/{x['max_attempts']}" for x in queue.get("items",[])];return "\n".join(lines)


def _queue_blockers(package:dict[str,Any],qa:dict[str,Any],review:dict[str,Any],ctx:dict[str,Any])->list[str]:
    errors=validate_publication_package(package,expected_project=str(ctx["packages"].get("project_id")))
    errors.extend(validate_package_layouts(package,ctx.get("plan_intelligence",{}),expected_project=str(ctx["packages"].get("project_id"))))
    if package.get("creative_production_contract_version")!=CONTRACT_VERSION:errors.append("creative production contract is missing or stale")
    if package.get("status") not in {"ready","ready_with_warnings"}:errors.append("package status is not ready")
    if qa.get("status") not in {"ready","ready_with_warnings","exceptional"}:errors.append("package QA is not publishable")
    if review.get("readiness")!="READY FOR PUBLISHING LAYER":errors.append("social review is not ready")
    if package.get("release_id")!=ctx["release"].get("release_id") or ctx["release"].get("status")!="completed":errors.append("release is invalid or superseded")
    brand=ctx["brand"];approval=brand.get("approval",{})
    if not approval.get("locked") or approval.get("status")!="approved" or approved_config_hash(brand)!=approval.get("approved_config_hash"):errors.append("brand lock is invalid")
    for slide in _slides(package):
        path=Path(str(slide.get("image_path","")))
        if not path.is_file() or _sha(path)!=slide.get("image_hash"):errors.append(f"image missing or hash mismatch: {slide.get('branded_item_id')}")
        if not slide.get("provenance_id"):errors.append(f"provenance incomplete: {slide.get('branded_item_id')}")
    return list(dict.fromkeys(errors))
def _planned_destinations(package:dict[str,Any])->tuple[Platform,...]:
    raw=package.get("planned_destinations")
    if raw:return tuple(Platform.parse(x) for x in raw)
    legacy=str(package.get("platform") or "instagram").casefold()
    if "facebook" in legacy and "instagram" in legacy:return tuple(Platform)
    return (Platform.FACEBOOK,) if "facebook" in legacy else (Platform.INSTAGRAM,)
def _preflight_checks(item:dict[str,Any],package:dict[str,Any]|None,ctx:dict[str,Any],successful:set[str])->tuple[dict[str,str],list[str],list[str]]:
    blockers=[];warnings=[];checks={};
    layout_errors=validate_package_layouts(package or {},ctx.get("plan_intelligence",{}),expected_project=str(ctx["packages"].get("project_id")))
    if layout_errors:blockers.extend(layout_errors);checks["plan_integrity"]="failed"
    else:checks["plan_integrity"]="passed"
    if not package or _json_hash(package)!=item.get("package_hash") or package.get("release_id")!=ctx["release"].get("release_id") or package.get("status") not in {"ready","ready_with_warnings"}:blockers.append("package integrity failure");checks["package_integrity"]="failed"
    else:checks["package_integrity"]="passed"
    slides=_slides(package or {});media_ok=bool(slides)
    if [x.get("slide_number") for x in slides]!=list(range(1,len(slides)+1)):blockers.append("invalid slide order");media_ok=False
    for slide in slides:
        path=Path(str(slide.get("image_path","")))
        if not path.is_file() or _sha(path)!=slide.get("image_hash"):blockers.append("missing media or wrong media hash");media_ok=False;continue
        try:
            with Image.open(path) as image:
                if image.format not in MockPlatformAdapter.supported_image_formats:blockers.append("unsupported image format");media_ok=False
        except OSError:blockers.append("invalid media");media_ok=False
    checks["media_integrity"]="passed" if media_ok else "failed"
    caption=(package or {}).get("master_caption") or (package or {}).get("caption") or {};text=str(caption.get("full_caption") or "");tags=[x.get("hashtag","") for x in (package or {}).get("hashtags",[])];story=(package or {}).get("package_type")=="story";content_ok=(story or bool(text)) and not INTERNAL.search(text) and len(text)<=MockPlatformAdapter.max_caption_length and len({x.casefold() for x in tags})==len(tags) and all(re.fullmatch(r"#[A-Za-z0-9]+",x) for x in tags) and all(x.get("alt_text") for x in slides)
    websites=re.findall(r"(?:https?://)?(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}",text.casefold())
    if websites and any("domuserbil.com" not in value for value in websites):blockers.append("wrong website");content_ok=False
    if not content_ok:blockers.append("content integrity failure")
    checks["content_integrity"]="passed" if content_ok else "failed"
    prov={x.get("branded_item_id"):x for x in ctx["provenance"].get("items",[])};prov_ok=all(x.get("branded_item_id") in prov and prov[x["branded_item_id"]].get("integrity_status") in {"complete","complete_with_warnings"} and x.get("final_output_hash")==prov[x["branded_item_id"]].get("final_output_hash") for x in slides)
    if not prov_ok:blockers.append("invalid provenance");checks["provenance"]="failed"
    else:checks["provenance"]="passed"
    brand=ctx["brand"];approval=brand.get("approval",{});brand_ok=approval.get("locked") and approved_config_hash(brand)==approval.get("approved_config_hash") and (package or {}).get("brand_config_hash")==approval.get("approved_config_hash");checks["brand_integrity"]="passed" if brand_ok else "failed"
    if not brand_ok:blockers.append("invalid brand lock")
    schedule_ok=True
    if item.get("scheduled_at_utc"):
        try:schedule_ok=datetime.fromisoformat(item["scheduled_at_utc"])>=datetime.now(timezone.utc)
        except ValueError:schedule_ok=False
    if not schedule_ok:blockers.append("invalid or past schedule")
    checks["schedule_integrity"]="passed" if schedule_ok else "failed"
    if item.get("idempotency_key") in successful:
        idem_ok=True;warnings.append("simulated success already recorded; mock adapter will reuse the receipt")
    else:idem_ok=item.get("status")!="publishing"
    checks["idempotency"]="passed" if idem_ok else "failed"
    if not idem_ok:blockers.append("duplicate publication or actively publishing")
    return checks,list(dict.fromkeys(blockers)),warnings
def _adapter_eligibility(item:dict[str,Any],preflight:dict[str,Any],successful:dict[str,Any]|set[str])->tuple[bool,str|None]:
    if preflight.get("status") not in {"ready","ready_with_warnings"}:return False,"preflight_blocked"
    if item.get("status") in {"blocked","failed","cancelled","superseded","published","published_with_warnings"}:return False,"queue_state_"+str(item.get("status"))
    if item.get("idempotency_key") in successful:return False,"already_published_duplicate"
    return True,None

def final_publish_errors(item:dict[str,Any],package:dict[str,Any],ctx:dict[str,Any])->list[str]:
    """Revalidate current production authority at execution, allowing due schedules."""
    qa=next((x for x in ctx.get("qa",{}).get("items",[]) if x.get("package_id")==package.get("package_id")),{})
    review=next((x for x in ctx.get("review",{}).get("packages",[]) if x.get("package_id")==package.get("package_id")),{})
    errors=_queue_blockers(package,qa,review,ctx)
    current=next((x for x in ctx["packages"].get("packages",[]) if x.get("package_id")==package.get("package_id")),None)
    if current is None or _json_hash(current)!=_json_hash(package):errors.append("current package changed during publishing preparation")
    if not package.get("project_sequence") or item.get("project_sequence")!=package.get("project_sequence"):
        errors.append("missing or altered project publication sequence")
    if item.get("campaign_scope")!=package.get("campaign_scope"):errors.append("altered campaign scope")
    if package.get("campaign_scope"):
        from src.project_sequence import campaign_scope
        if package["campaign_scope"]!=ctx.get("campaign_scope"):errors.append("campaign scope is stale or unapproved")
    purpose=(package.get("project_sequence") or {}).get("role")
    if purpose in {"project_overview","project_site_plan"}:
        source_ids={a for slide in _slides(package) for a in slide.get("source_asset_ids",package.get("source_asset_ids",[]))}
        assets=[a for a in ctx.get("visual_assets",[]) if a.get("asset_id") in source_ids]
        if not source_ids or {a.get("asset_id") for a in assets}!=source_ids:
            errors.append("opening post source-purpose evidence is missing")
        elif purpose=="project_overview":
            by_id={a["asset_id"]:a for a in assets}
            ordered=[by_id[a] for slide in _slides(package) for a in slide.get("source_asset_ids",package.get("source_asset_ids",[]))]
            errors.extend(validate_overview_slides(ordered,package.get("project_id")))
        elif any(assess_visual_purpose(a,purpose,package.get("project_id"))["status"]!="MATCH" for a in assets):
            errors.append("opening post visual purpose is unsuitable or requires review")
    if purpose=="project_site_plan":
        caption=package.get("master_caption") or package.get("caption") or {}
        text=str(caption.get("full_caption") or "")
        for asset in assets:
            decision=assess_visual_purpose(asset,purpose,package.get("project_id"))
            disclosure=decision.get("required_disclosure")
            if disclosure and disclosure not in text:
                errors.append("illustrated project layout disclosure is missing")
    expected_identity=_publication_identity(str(item.get("project_id")),package,str(item.get("platform")))
    if item.get("publication_identity")!=expected_identity or item.get("idempotency_key")!=expected_identity:
        errors.append("publication identity does not match the current package")
    if item.get("image_hashes")!=_image_hashes(package):errors.append("queue media hashes do not match the current package")
    # Execution eligibility owns not-before timestamps; preflight's future-only
    # schedule rule is for planning, not an already due publication.
    checks,blockers,_=_preflight_checks({**item,"scheduled_at_utc":None},package,ctx,set())
    errors.extend(blockers)
    if item.get("project_id")!=ctx["packages"].get("project_id") or package.get("project_id")!=item.get("project_id"):
        errors.append("publication project identity mismatch")
    return list(dict.fromkeys(errors))
def publishing_health(project:str,root:Path)->dict[str,Any]:
    foundation=PublishingFoundation(project,root);checks={};errors=[]
    try:
        config=foundation._config();checks["schedule_config"]="valid"
        queue=_read(foundation.queue_path);keys=[x.get("idempotency_key") for x in queue.get("items",[])];checks["queue"]="valid" if len(keys)==len(set(keys)) else "duplicate_keys"
        if checks["queue"]!="valid":errors.append("duplicate idempotency keys")
        packages_path=foundation.output/"post-packages"/f"{project}-post-packages.json";packages={x.get("package_id"):x for x in _read(packages_path).get("packages",[])};stale=[x["queue_item_id"] for x in queue.get("items",[]) if x.get("package_id") not in packages or x.get("package_hash")!=_json_hash(packages[x["package_id"]])]
        checks["package_hashes"]="current" if not stale else "stale";
        if stale:errors.append("stale queued package hashes")
        manifest=_read(foundation.manifest_path) if foundation.manifest_path.is_file() else {};checks["manifest"]="valid" if isinstance(manifest,dict) and manifest.get("project_id")==project else "invalid";receipts=manifest.get("mock_receipts",[]);checks["receipts"]="valid" if all(x.get("dry_run") is True and x.get("payload_hash") for x in receipts) else "invalid"
        latest=sorted((foundation.output/"releases"/project).glob("release-*/manifest.json"));latest_id=_read(latest[-1]).get("release_id") if latest else None;checks["release_refs"]="valid" if latest_id and all(x.get("release_id")==latest_id for x in queue.get("items",[])) else "invalid"
        if checks["release_refs"]!="valid":errors.append("invalid publishing release references")
        successful={x.get("idempotency_key") for x in receipts if x.get("status")=="simulated_success"};real_requeued=[x["queue_item_id"] for x in queue.get("items",[]) if x.get("idempotency_key") in successful and x.get("status") in {"queued","scheduled","publishing"}]
        if real_requeued:errors.append("successful dry-run item returned to an active queue state")
        payloads={x.get("queue_item_id") for x in receipts};missing=[x for x in payloads if not (foundation.payload_dir/f"{x}.json").is_file()]
        if missing:errors.append("missing mock payload files")
        schedule=_read(foundation.schedule_path) if foundation.schedule_path.is_file() else {"items":[]};superseded_ids={x.get("queue_item_id") for x in queue.get("items",[]) if x.get("status")=="superseded"}
        if any(x.get("queue_item_id") in superseded_ids for x in schedule.get("items",[])):errors.append("superseded jobs entered scheduler")
        preflight=_read(foundation.preflight_path) if foundation.preflight_path.is_file() else {"items":[]}
        if any(x.get("queue_item_id") in superseded_ids and x.get("status")=="blocked" for x in preflight.get("items",[])):errors.append("superseded jobs counted as blocked preflight")
        historical=manifest.get("historical_totals",{});current=manifest.get("current_run",{});run=manifest.get("last_adapter_run",{})
        if historical and historical.get("total_queue_records")!=len(queue.get("items",[])):errors.append("manifest historical queue counter mismatch")
        if current and (current.get("adapter_attempts",0)>current.get("preflight_eligible",0) or current.get("new_receipts_generated",0)>current.get("adapter_attempts",0)):errors.append("manifest current-run publishing invariant failed")
        try:
            from src.core.console import has_mojibake
            if has_mojibake(foundation.show_queue()):errors.append("malformed console encoding configuration")
        except (OSError,ValueError):pass
    except Exception as error:errors.append(str(error))
    return {"status":"HEALTHY" if not errors else "CRITICAL","checks":checks,"errors":errors}
def _slides(package:dict[str,Any])->list[dict[str,Any]]:
    if package.get("slides"):return package["slides"]
    image=package.get("image",{});return [{**image,"slide_number":1,"branded_item_id":package.get("branded_item_id"),"alt_text":package.get("alt_text"),"provenance_id":package.get("provenance_id"),"final_output_hash":package.get("final_output_hash")}] if image else []
def _image_hashes(package:dict[str,Any])->list[str]:return [str(x.get("image_hash")) for x in _slides(package)]
def _queue_summary(items:list[dict[str,Any]])->dict[str,Any]:
    historical={"superseded","cancelled"};active=[x for x in items if x.get("status") not in historical]
    return {"total":len(items),"active_total":len(active),"platform_publication_jobs":len(active),**{status:sum(x.get("status")==status for x in items) for status in QUEUE_STATUSES}}
def _is_active_job(item:dict[str,Any])->bool:return item.get("status") not in {"superseded","cancelled","failed","published","published_with_warnings","publishing","publishing_uncertain"}
def _preflight_skip_status(item:dict[str,Any])->str|None:
    status=item.get("status")
    if status=="superseded":return "superseded_skipped"
    if status=="cancelled":return "cancelled_skipped"
    if status in {"published","published_with_warnings"}:return "already_published_skipped"
    if status=="failed":return "failed_skipped"
    if status=="blocked":return "blocked"
    return None
def _empty_manifest(project:str,release_id:str|None)->dict[str,Any]:
    now=_now();return {"project_id":project,"release_id":release_id,"manifest_version":MANIFEST_VERSION,"queue_items":[],"scheduled_items":[],"preflight_results":[],"mock_receipts":[],"real_receipts":[],"retries":[],"failures":[],"publication_history":[],"created_at":now,"updated_at":now}
def _append_history(history:list[dict[str,Any]],item:dict[str,Any],status:str,adapter:str,receipt_id:str|None,payload_hash:str|None,error:str|None=None)->list[dict[str,Any]]:
    identity=_stable("history",item["queue_item_id"],status,receipt_id or "",payload_hash or "")
    return [*history,{"history_id":identity,"queue_item_id":item["queue_item_id"],"package_id":item["package_id"],"platform":item["platform"],"action":"dry_run_publish","status":status,"adapter":adapter,"timestamp":_now(),"receipt_id":receipt_id,"error":error,"payload_hash":payload_hash}]
def _dedupe(items:list[dict[str,Any]],key:str)->list[dict[str,Any]]:return list({x.get(key):x for x in items}.values())
def _timezone(name:str)->Any:
    try:return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        # Windows Python installations may not ship the IANA database. Baghdad
        # has observed UTC+03:00 without DST since 2008, so this local fallback
        # preserves the configured publishing decision without a network install.
        if name=="Asia/Baghdad":return timezone(timedelta(hours=3),name)
        raise ValueError(f"Invalid publishing timezone: {name}") from error
@contextmanager
def _lock(path:Path,timeout:float=5)->Iterator[None]:
    # The OS releases this lock on process death. Keep the inode/file in place:
    # deleting it would permit a second process to lock a different file.
    path.parent.mkdir(parents=True,exist_ok=True);started=time.monotonic()
    with path.open("a+b") as handle:
        if path.stat().st_size==0:handle.write(b"0");handle.flush()
        def acquire():
            handle.seek(0)
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            try:acquire();break
            except OSError as error:
                if error.errno not in {11,13,35,36}:raise
                if time.monotonic()-started>=timeout:raise TimeoutError(f"Publishing queue lock unavailable: {path}") from error
                time.sleep(.05)
        try:yield
        finally:
            handle.seek(0)
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
def _atomic_json(path:Path,value:Any)->None:
    path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w",encoding="utf-8",newline="\n") as target:json.dump(value,target,indent=2,ensure_ascii=False);target.write("\n");target.flush();os.fsync(target.fileno())
    os.replace(temporary,path)
def _json_hash(value:Any)->str:return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def _publication_identity(project:str,package:dict[str,Any],platform:str)->str:
    slides=_slides(package);caption=package.get("master_caption") or package.get("caption") or {}
    surface=publication_surface(package.get("package_type"),package.get("platform"));semantic={"project_id":project,"platform":str(platform).casefold(),"surface":surface,"format":publication_format(package.get("package_type"),surface),"content_idea_id":package.get("content_idea_id"),"master_concept_id":package.get("master_concept_id"),"language_code":package.get("language_code"),"media":[{"branded_item_id":x.get("branded_item_id"),"image_hash":x.get("image_hash"),"source_asset_ids":x.get("source_asset_ids",[]),"slide_number":x.get("slide_number")} for x in slides],"caption":caption.get("full_caption"),"hashtags":[x.get("hashtag") for x in package.get("hashtags",[])],"CTA":package.get("CTA"),"production_contract_version":package.get("creative_production_contract_version")}
    return _stable("publication",_json_hash(semantic))
def _sha(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda:source.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()
def _stable(prefix:str,*values:Any)->str:return prefix+"_"+hashlib.sha256("|".join(str(x) for x in values).encode()).hexdigest()[:24]
def _slug(value:str)->str:return re.sub(r"[^a-z0-9]+","-",value.casefold()).strip("-") or "project"
def _read(path:Path)->dict[str,Any]:return json.loads(path.read_text(encoding="utf-8"))
def _now()->str:return datetime.now(timezone.utc).isoformat()
