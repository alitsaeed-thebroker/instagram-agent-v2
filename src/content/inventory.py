"""Canonical, knowledge-first Content Strategy opportunity inventory.

Visuals and renderer support are optional attachments.  This module owns what
is worth communicating; downstream departments own production and publication.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from src.content.visual_purpose import assess_visual_purpose, select_purpose_assets, load_visual_reviews
from src.knowledge.consumer import (
    canonical_project_identity,
    canonical_verified_facts,
    require_canonical_graph,
)
from src.utils.config import CONTENT_INVENTORY_OUTPUT_DIRECTORY
from src.execution.lineage import attach_lineage, artifact_fingerprint, canonical_graph_fingerprint

INVENTORY_VERSION = "1.0.0"
HIGH_CATEGORIES = {"introduction", "location", "masterplan", "exterior", "interior", "amenity", "layout", "commercial"}
VISUAL_TYPES = {
    "masterplan": {"masterplan", "site_plan"}, "exterior": {"exterior", "aerial_view", "architectural_detail"},
    "interior": {"interior", "residential_space", "commercial_space"},
    "amenity": {"amenity", "clubhouse", "swimming_pool", "garden_landscape"},
    "layout": {"floorplan", "unit_plan", "unit_layout", "apartment_layout", "office_layout", "villa_layout", "commercial_unit_layout", "floor_plan", "typical_floor_plan", "master_floor_plan"}, "location": {"location_map", "map", "site_plan"},
    "introduction": {"logo", "exterior", "aerial_view", "masterplan", "site_plan"},
}
SAFE_CTAS = (
    ("contact", "Contact us for details"), ("units", "Ask about available units"),
    ("layouts", "Request the floor plans"), ("pricing", "Ask about current pricing"),
    ("consultation", "Schedule a consultation"),
)


@dataclass
class EvidenceReference:
    fact_id: str
    value: str
    knowledge_path: str
    source_file: str | None = None
    source_document: str | None = None
    page: int | None = None
    line_range: str | None = None
    paragraph: int | None = None
    project: str | None = None
    status: str = "supported"
    authority: int | None = None
    evidence_origin: str = "source_package_fact"
    source_url: str | None = None
    domain: str | None = None
    retrieval_timestamp: str | None = None
    source_type: str | None = None
    authority_level: int | None = None
    project_match: bool | None = None
    extracted_claim: str | None = None
    freshness: str | None = None
    conflict_state: str | None = None
    evidence_id: str | None = None
    source_id: str | None = None
    source_sha256: str | None = None
    extraction_method: str | None = None
    table_index: int | None = None
    row_index: int | None = None


@dataclass
class ContentOpportunity:
    opportunity_id: str
    category: str
    subcategory: str
    title: str
    purpose: str
    supporting_fact_ids: list[str]
    supporting_facts: list[str]
    provenance: list[EvidenceReference]
    related_visual_asset_ids: list[str]
    recommended_formats: list[str]
    priority: str
    confidence: float
    readiness: str
    renderer_readiness: str
    blocked_reason: str | None = None
    limitations: list[str] = field(default_factory=list)
    forbidden_claims: list[str] = field(default_factory=list)
    carousel_compatible_with: list[str] = field(default_factory=list)
    evidence_mode: str = "fact_supported"
    cta_type: str | None = None


@dataclass
class StoryFrame:
    order: int
    role: str
    topic: str
    supporting_fact_ids: list[str]
    visual_asset_ids: list[str]
    suggested_purpose: str
    provenance: list[EvidenceReference] = field(default_factory=list)


@dataclass
class StorySequence:
    sequence_id: str
    title: str
    purpose: str
    priority: str
    frames: list[StoryFrame]


@dataclass
class ContentOpportunityInventory:
    project_id: str
    inventory_version: str
    generated_at: str
    contract_role: str
    source_package_references: list[dict[str, Any]]
    opportunities: list[ContentOpportunity]
    story_sequences: list[StorySequence]
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]: return asdict(self)
    def to_json(self) -> str: return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContentOpportunityInventory":
        if data.get("contract_role") != "authoritative_content_opportunity_inventory":
            raise ValueError("Content inventory is not authoritative")
        if str(data.get("inventory_version")) != INVENTORY_VERSION:
            raise ValueError("Unsupported content inventory version")
        opportunities=[]
        for raw in data.get("opportunities", []):
            item=dict(raw);item["provenance"]=[EvidenceReference(**x) for x in item.get("provenance",[])]
            opportunities.append(ContentOpportunity(**item))
        sequences=[]
        for raw in data.get("story_sequences", []):
            item=dict(raw);frames=[]
            for frame in item.get("frames",[]):
                value=dict(frame);value["provenance"]=[EvidenceReference(**x) for x in value.get("provenance",[])]
                frames.append(StoryFrame(**value))
            item["frames"]=frames
            sequences.append(StorySequence(**item))
        return cls(project_id=str(data["project_id"]),inventory_version=str(data["inventory_version"]),generated_at=str(data["generated_at"]),contract_role=str(data["contract_role"]),source_package_references=list(data.get("source_package_references",[])),opportunities=opportunities,story_sequences=sequences,diagnostics=dict(data.get("diagnostics",{})))


class ContentOpportunityInventoryEngine:
    """Discover source-grounded opportunities before attaching optional visuals."""

    def run(self, knowledge_path: Path, visual_inventory_path: Path, strategy_path: Path | None = None, output_directory: Path | None = None, project_id: str | None = None) -> Path:
        knowledge=_read(knowledge_path);visuals=_read(visual_inventory_path);strategy=_read(strategy_path)
        graph=require_canonical_graph(knowledge,expected_project=project_id) if project_id else require_canonical_graph(knowledge)
        identity=canonical_project_identity(knowledge,expected_project=graph.project_namespace)
        knowledge_project=str(graph.project_namespace)
        visual_project=str(visuals.get("project_id") or visuals.get("project") or knowledge_project)
        project=str(project_id or knowledge_project)
        if _norm(visual_project) != _norm(project):
            raise ValueError(f"Visual inventory project '{visual_project}' does not match orchestration project '{project}'")
        if _norm(project) != _norm(knowledge_project) and not _knowledge_owned_by_project(knowledge,project):
            raise ValueError(f"Visual inventory project '{visual_project}' does not match authoritative project '{knowledge_project}'")
        root=Path(knowledge_path).resolve().parents[2]
        for key,items in list(visuals.items()):
            if key.startswith("available_") and key!="available_text_facts" and isinstance(items,list):
                visuals[key]=load_visual_reviews(root,items)
        facts=_facts(knowledge,project);assets=_assets(visuals,project);opportunities=[]
        opportunities.extend(_introduction(facts,assets,project))
        opportunities.extend(_locations(facts,assets,project))
        opportunities.extend(_visual_categories(facts,assets,project))
        opportunities.extend(_commercial(knowledge,assets,project))
        opportunities=_dedupe(opportunities)
        opportunities.extend(_ctas(opportunities,facts,project))
        opportunities.extend(_carousels(opportunities,project))
        opportunities=_dedupe(opportunities)
        sequences=_story_sequences(opportunities,project)
        for sequence in sequences:
            opportunities.append(_story_opportunity(sequence,project))
        opportunities.sort(key=lambda x: ({"HIGH":0,"MEDIUM":1,"LOW":2}.get(x.priority,3),x.category,x.subcategory,x.opportunity_id))
        sources=_sources(knowledge_path,knowledge,visual_inventory_path)
        counts={category:sum(x.category==category for x in opportunities) for category in sorted({x.category for x in opportunities})}
        content_subjects=sum(x.category not in {"cta","carousel","story_sequence"} for x in opportunities)
        ctas=[x for x in opportunities if x.category=="cta"]
        result=ContentOpportunityInventory(project,INVENTORY_VERSION,datetime.now(timezone.utc).isoformat(),"authoritative_content_opportunity_inventory",sources,opportunities,sequences,{"opportunity_count":len(opportunities),"category_counts":counts,"content_subjects":content_subjects,"cta_opportunities":len(ctas),"policy_cta_opportunities":sum(x.cta_type=="policy_cta" for x in ctas),"contextual_cta_opportunities":sum(x.cta_type=="contextual_cta" for x in ctas),"carousel_opportunities":counts.get("carousel",0),"story_sequences":len(sequences),"total_strategy_objects":len(opportunities),"text_only_count":sum(not x.related_visual_asset_ids for x in opportunities),"blocked_count":sum(x.readiness=="blocked" for x in opportunities),"legacy_outputs_are_compatibility_only":True,"opening_visual_decisions":[assess_visual_purpose(a,purpose,project) for purpose in ("project_overview","project_site_plan") for a in assets]})
        payload=attach_lineage(
            result.to_dict(),
            stage="department3-content-opportunity-inventory",
            canonical_fingerprint=canonical_graph_fingerprint(knowledge),
            inputs={"visual_inventory":artifact_fingerprint(visuals) if isinstance(visuals,dict) else ""},
        )
        destination=(output_directory or CONTENT_INVENTORY_OUTPUT_DIRECTORY)/f"{project}-content-opportunity-inventory.json";destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");return destination


def _knowledge_owned_by_project(knowledge:dict[str,Any],project:str)->bool:
    """Canonical namespace is the only production ownership authority."""
    try:
        graph=require_canonical_graph(knowledge,expected_project=project)
    except ValueError:
        return False
    return _norm(graph.project_namespace)==_norm(project)


def load_content_opportunity_inventory(path: Path) -> ContentOpportunityInventory:
    return ContentOpportunityInventory.from_dict(json.loads(path.read_text(encoding="utf-8")))


def legacy_visual_opportunities(inventory: ContentOpportunityInventory, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Temporary adapter for PlanningEngine; canonical inventory remains authority."""
    by_id={str(a.get("asset_id")):a for a in assets if _belongs(a.get("project_id") or a.get("source_project") or a.get("project"),inventory.project_id)}
    groups=[]
    for item in inventory.opportunities:
        if item.category in {"story_sequence"}: continue
        selected=[by_id[x] for x in item.related_visual_asset_ids if x in by_id]
        platforms=sorted({p for a in selected for p in a.get("recommended_platforms",[])})
        groups.append({"opportunity_id":item.opportunity_id,"title":item.title,"opportunity_type":item.category,
            "supported_asset_ids":item.related_visual_asset_ids,"supporting_fact_refs":item.supporting_fact_ids,
            "supported_personas":[],"supported_funnel_stages":["awareness","consideration"] if item.category in {"introduction","location"} else ["consideration","education","conversion"],
            "supported_platforms":platforms,"supported_formats":item.recommended_formats,"visual_strength":round(100*max([float(a.get("confidence",0)) for a in selected],default=.5)),
            "factual_strength":round(item.confidence*100),"overall_confidence":item.confidence,"asset_diversity_score":len(selected),
            "reuse_capacity":max(1,len(selected)*2),"limitations":item.limitations,"forbidden_claims":item.forbidden_claims,
            "recommended_priority":item.priority.casefold(),"canonical_category":item.category,"canonical_subcategory":item.subcategory,
            "readiness":item.readiness,"renderer_readiness":item.renderer_readiness,"derived_from_canonical_inventory":True,
            "canonical_inventory_version":inventory.inventory_version})
    return groups


def _canonical_facts(canonical: dict[str, Any], project: str) -> list[EvidenceReference]:
    """Consume only VERIFIED, marketing-eligible canonical Department 2 facts."""
    if _norm(canonical.get("project_namespace")) != _norm(project):
        return []
    result: list[EvidenceReference] = []
    for fact in canonical.get("facts", []) or []:
        if not isinstance(fact, dict):
            continue
        if fact.get("state") != "VERIFIED" or fact.get("marketing_eligible") is not True:
            continue
        fact_type = str(fact.get("fact_type") or "")
        if fact_type.startswith("commercial."):
            continue
        value = _value(fact.get("value"))
        if not value:
            continue
        for source in fact.get("provenance", []) or []:
            if not isinstance(source, dict):
                continue
            if not _belongs(source.get("source_project"), project):
                continue
            if not source.get("evidence_id"):
                continue
            if not (source.get("source_file") or source.get("source_document")):
                continue
            if not source.get("source_text"):
                continue
            locator_present = (
                any(
                    source.get(key) is not None
                    for key in ("page", "source_page", "line_range", "paragraph")
                )
                or (source.get("table_index") is not None and source.get("row_index") is not None)
            )
            if not locator_present:
                continue
            result.append(EvidenceReference(
                fact_id=str(fact.get("fact_id") or ""),
                value=value,
                knowledge_path=fact_type,
                source_file=source.get("source_file") or source.get("source_document"),
                source_document=source.get("source_document") or source.get("source_file"),
                page=source.get("page") or source.get("source_page"),
                line_range=source.get("line_range"),
                paragraph=source.get("paragraph"),
                project=source.get("source_project"),
                status="verified",
                authority=fact.get("authority"),
                evidence_origin=source.get("evidence_origin", "department1_source_evidence"),
                extracted_claim=source.get("source_text") or value,
                conflict_state="none",
                evidence_id=source.get("evidence_id"),
                source_id=source.get("source_id"),
                source_sha256=source.get("source_sha256"),
                extraction_method=source.get("extraction_method"),
                table_index=source.get("table_index"),
                row_index=source.get("row_index"),
            ))
    return result


def _facts(k:dict[str,Any],project:str)->list[EvidenceReference]:
    result=[]
    for fact in canonical_verified_facts(k,project,include_commercial=False).values():
        text=_value(fact.value)
        if not text:continue
        for source in fact.evidence:
            result.append(EvidenceReference(
                fact.fact_id,
                text,
                fact.path,
                source.get("source_file") or source.get("source_document"),
                source.get("source_document") or source.get("source_file"),
                source.get("page") if source.get("page") is not None else source.get("source_page"),
                source.get("line_range"),
                source.get("paragraph"),
                source.get("source_project") or project,
                "verified",
                fact.authority,
                source.get("evidence_origin","department1_source_evidence"),
                source.get("source_url"),
                source.get("domain"),
                source.get("retrieval_timestamp"),
                source.get("source_type"),
                source.get("authority_level"),
                source.get("project_match"),
                source.get("source_text") or text,
                source.get("freshness"),
                "none",
                source.get("evidence_id"),
                source.get("source_id"),
                source.get("source_sha256"),
                source.get("extraction_method"),
                source.get("table_index"),
                source.get("row_index"),
            ))
    return result


def _introduction(facts,assets,project):
    selected=[f for f in facts if f.knowledge_path in {"project_identity.project_name","project_identity.project_type"}]
    if not selected:return []
    return [_op(project,"introduction","project_overview","Project Introduction","Introduce the verified project identity and offering.",selected,_match_assets(assets,"introduction"),["single_feed_post","carousel","story","story_sequence"],"HIGH")]


def _locations(facts,assets,project):
    location=[f for f in facts if "location" in f.knowledge_path or _location_text(f.value)]
    buckets={"overview":[],"landmarks":[],"connectivity":[],"destinations":[],"accessibility":[],"advantages":[]}
    for fact in location:
        text=fact.value.casefold();matched=[]
        if re.search(r"minutes?|\bkm\b|destination|دقيقة|دقائق|كيلومتر|خولەک|کیلۆمەتر",text):matched.append("destinations")
        if re.search(r"road|route|connect|highway|street|شارع|طريق|ڕێگا|شەقام",text):matched.append("connectivity")
        if re.search(r"\bnear\b|landmark|park|mall|school|hospital|citadel|بالقرب|قريب|منتزه|مول|نزیك|نزیک|پارک",text):matched.append("landmarks")
        if re.search(r"access|reachable|وصول|سهولة الوصول|دەستگەیشتن",text):matched.append("accessibility")
        if re.search(r"strategic|central|prime location|استراتيجي|مركزي|ستراتیژی|ناوەندی",text):matched.append("advantages")
        for bucket in matched or ["overview"]:buckets[bucket].append(fact)
    titles={"overview":"Project Location Overview","landmarks":"Nearby Landmarks","connectivity":"Road Connectivity","destinations":"Important Destinations","accessibility":"Project Accessibility","advantages":"Strategic Location Advantages"}
    return [_op(project,"location",key,titles[key],f"Communicate only verified {key.replace('_',' ')} information.",items,_match_assets(assets,"location"),["single_feed_post","carousel","story","informational_graphic"],"HIGH",forbidden=["Invented distances, travel times, landmarks, access routes, or location advantages"]) for key,items in buckets.items() if items]


def _visual_categories(facts,assets,project):
    result=[];titles={"masterplan":"Masterplan Overview","exterior":"Exterior Architecture","interior":"Interior Design","amenity":"Amenity","layout":"Unit Layout"}
    for category in ("masterplan","exterior","interior","amenity","layout"):
        matches=_match_assets(assets,category);by_subject={}
        for asset in matches:
            subject=str(asset.get("dominant_subject") or asset.get("asset_subtype") or asset.get("asset_type") or category).strip();by_subject.setdefault(_norm(subject),[]).append(asset)
        related=[f for f in facts if category in f.knowledge_path or (category=="amenity" and "amenit" in f.knowledge_path) or (category=="layout" and f.knowledge_path.startswith("unit.")) or (category in {"exterior","interior"} and "architecture" in f.knowledge_path)]
        if not by_subject and related:by_subject={category:[]}
        for subject,items in by_subject.items():
            label=_display(subject) if subject and subject!=category else titles[category]
            evidence=_semantic_facts(related,label,category)
            item=_op(project,category,subject or category,label,f"Explain the source-supported {category} subject.",evidence,[str(x.get("asset_id")) for x in items if x.get("asset_id")],["single_feed_post","carousel","story","informational_graphic"],"HIGH",confidence=.9 if items and evidence else .72 if items else .95)
            if items and not evidence:
                item.evidence_mode="visual_only";item.provenance=_visual_evidence(items,project);item.limitations.append("Visual-only subject: do not infer factual attributes from appearance.")
            result.append(item)
    return result


def _commercial(k,assets,project):
    result=[]
    facts=[
        fact for fact in canonical_verified_facts(k,project,include_commercial=True).values()
        if fact.commercial
    ]
    for fact in facts:
        # Canonical value formatting is deliberately conservative and keeps
        # only the unit/currency carried by the authoritative fact itself.
        if isinstance(fact.value,(int,float)):
            numeric=f"{fact.value:g}" if isinstance(fact.value,float) else str(fact.value)
            if fact.canonical_path=="commercial.price_per_sqm":
                value=" ".join(x for x in (fact.currency,numeric,"per sqm") if x)
            else:
                value=" ".join(x for x in (fact.currency,numeric) if x)
        else:
            value=_value(fact.value)
        evid=[]
        for e in fact.evidence:
            evid.append(EvidenceReference(
                fact.fact_id,
                value,
                fact.path,
                e.get("source_file") or e.get("source_document"),
                e.get("source_document") or e.get("source_file"),
                e.get("page") if e.get("page") is not None else e.get("source_page"),
                e.get("line_range"),
                e.get("paragraph"),
                e.get("source_project") or project,
                "verified",
                fact.authority,
                e.get("evidence_origin","department1_source_evidence"),
                e.get("source_url"),
                e.get("domain"),
                e.get("retrieval_timestamp"),
                e.get("source_type"),
                e.get("authority_level"),
                e.get("project_match"),
                e.get("source_text") or value,
                e.get("freshness"),
                "none",
                e.get("evidence_id"),
                e.get("source_id"),
                e.get("source_sha256"),
                e.get("extraction_method"),
                e.get("table_index"),
                e.get("row_index"),
            ))
        if not evid:continue
        kind=fact.canonical_path.removeprefix("commercial.")
        result.append(_op(
            project,"commercial",kind,_display(kind),
            "Explain only this verified price fact without adding payment terms, returns, scarcity, or urgency claims.",
            evid,[],["informational_graphic","carousel","story"],"HIGH",
            forbidden=["Payment plans, installments, ROI, rental yield, guaranteed return, appreciation, scarcity, or urgency"],
        ))
    return result


def _ctas(opportunities,facts,project):
    result=[];has_layout=any(x.category=="layout" for x in opportunities);has_payment=any(x.category=="commercial" for x in opportunities)
    for key,title in SAFE_CTAS:
        if key=="layouts" and not has_layout:continue
        if key=="payment" and not has_payment:continue
        evidence=[]
        item=_op(project,"cta",key,title if key!="units" else "Ask about current unit availability","Offer a safe next step without unsupported urgency.",evidence,[],["single_feed_post","story","story_sequence"],"MEDIUM",confidence=.8,forbidden=["Last units remaining","Selling fast","Limited-time offer","Guaranteed return","Highest ROI","Guaranteed appreciation"])
        item.evidence_mode="policy_generated";item.cta_type="contextual_cta" if key in {"layouts","payment"} else "policy_cta"
        result.append(item)
    return result


def _carousels(opportunities,project):
    result=[]
    for category in ("location","amenity","layout","commercial"):
        members=[x for x in opportunities if x.category==category]
        if len(members)<2:continue
        factual=[e for x in members for e in x.provenance if e.status!="visual_only"]
        visual=[e for x in members for e in x.provenance if e.status=="visual_only"]
        assets=list(dict.fromkeys(a for x in members for a in x.related_visual_asset_ids))
        modes={x.evidence_mode for x in members}
        mode="visual_only" if modes=={"visual_only"} else "fact_supported" if modes=={"fact_supported"} else "mixed"
        # A grouping wrapper must never be more certain than its weakest member.
        item=_op(project,"carousel",category,f"{_display(category)} Carousel",f"Combine {category} opportunities into a coherent evidence-backed sequence.",factual,assets,["carousel"],"MEDIUM",confidence=min(x.confidence for x in members))
        item.evidence_mode=mode;item.provenance=_unique_evidence([*factual,*visual])
        if mode=="visual_only":item.supporting_fact_ids=[];item.supporting_facts=[]
        elif mode=="mixed":
            item.supporting_fact_ids=list(dict.fromkeys(x.fact_id for x in factual));item.supporting_facts=list(dict.fromkeys(x.value for x in factual))
        item.carousel_compatible_with=[x.opportunity_id for x in members];result.append(item)
    return result


def _story_sequences(opportunities,project):
    sequences=[];intro=next((x for x in opportunities if x.category=="introduction"),None);location=next((x for x in opportunities if x.category=="location"),None);feature=next((x for x in opportunities if x.category in {"masterplan","exterior","amenity"}),None);cta=next((x for x in opportunities if x.category=="cta"),None)
    chosen=[x for x in (intro,location,feature,cta) if x]
    if len(chosen)>=2:sequences.append(_sequence(project,"project_introduction","Project Introduction Sequence","Introduce the project through verified identity, place, features, and a safe next step.",chosen))
    amenities=[x for x in opportunities if x.category=="amenity"]
    if amenities:
        chosen=[*amenities[:4],*([cta] if cta else [])];sequences.append(_sequence(project,"amenities","Amenities Sequence","Present distinct verified amenities and a safe next step.",chosen))
    return sequences


def _sequence(project,key,title,purpose,items):
    frames=[]
    for i,item in enumerate(items,1):frames.append(StoryFrame(i,"cta" if item.category=="cta" else "opening" if i==1 else "evidence",item.title,item.supporting_fact_ids,item.related_visual_asset_ids,item.purpose,list(item.provenance)))
    return StorySequence(_id("sequence",project,key,*[x.opportunity_id for x in items]),title,purpose,"MEDIUM",frames)


def _story_opportunity(sequence,project):
    fact_ids=list(dict.fromkeys(x for f in sequence.frames for x in f.supporting_fact_ids));assets=list(dict.fromkeys(x for f in sequence.frames for x in f.visual_asset_ids))
    evidence=_unique_evidence([x for frame in sequence.frames for x in frame.provenance]);values=list(dict.fromkeys(x.value for x in evidence))
    return ContentOpportunity(_id("opp",project,"story_sequence",sequence.sequence_id),"story_sequence",sequence.sequence_id,sequence.title,sequence.purpose,fact_ids,values,evidence,assets,["story_sequence"],"MEDIUM",.85,"strategy_ready","not_assessed",None,[],["Unsupported facts, urgency, scarcity, or guarantees"],[],"derived_sequence")


def _op(project,category,subcategory,title,purpose,evidence,assets,formats,priority,confidence=None,forbidden=None):
    evidence=_unique_evidence(evidence);fact_ids=list(dict.fromkeys(x.fact_id for x in evidence));values=list(dict.fromkeys(x.value for x in evidence));asset_ids=[str(x.get("asset_id")) for x in assets if isinstance(x,dict) and x.get("asset_id")] if assets and isinstance(assets[0],dict) else list(dict.fromkeys(assets or []))
    conf=confidence if confidence is not None else (.95 if evidence else .75 if asset_ids else .4);readiness="strategy_ready" if evidence or asset_ids or category=="cta" else "blocked"
    mode="mixed" if evidence and asset_ids else "fact_supported" if evidence else "visual_only" if asset_ids else "policy_generated" if category=="cta" else "fact_supported"
    return ContentOpportunity(_id("opp",project,category,subcategory,*fact_ids),category,subcategory,title,purpose,fact_ids,values,evidence,asset_ids,list(dict.fromkeys(formats)),priority,round(conf,3),readiness,"not_assessed",None if readiness!="blocked" else "insufficient authoritative evidence",["Visual attachment optional; preserve source-supported claims only."],["Unsupported facts, urgency, scarcity, ROI, guarantees, or invented project details",*(forbidden or [])],[],mode)


def _dedupe(items):
    result={}
    for item in items:
        key=(item.category,_norm(item.subcategory),tuple(sorted(item.supporting_fact_ids)))
        if key not in result:result[key]=item
        else:
            old=result[key];old.related_visual_asset_ids=list(dict.fromkeys([*old.related_visual_asset_ids,*item.related_visual_asset_ids]));old.provenance=_unique_evidence([*old.provenance,*item.provenance])
    return list(result.values())


def _assets(inventory,project):
    found={}
    for key,values in inventory.items():
        if key.startswith("available_") and key!="available_text_facts" and isinstance(values,list):
            for item in values:
                owner=item.get("project_id") or item.get("source_project") or item.get("project") if isinstance(item,dict) else None
                if isinstance(item,dict) and _belongs(owner,project) and item.get("asset_id") and (assess_visual_purpose(item,"project_overview",project,allow_support=True)["status"]=="MATCH" or (item.get("analysis_status") not in {"failed","review_required","unsuitable"} and item.get("marketing_suitability") not in {"review_required","unsuitable"})):found[str(item["asset_id"])]=item
    return list(found.values())


def _match_assets(assets,category):
    if category in {"introduction","masterplan"}:
        return select_purpose_assets(assets,category)[0]
    return [a for a in assets if str(a.get("asset_type","")).casefold() in VISUAL_TYPES.get(category,set())]
def _semantic_facts(facts,label,category):
    subject=_norm(label).replace("bedroom","bedroom")
    words={x for x in subject.split() if len(x)>2 and x not in {"layout","unit","apartment","project"}}
    result=[]
    for fact in facts:
        value=_norm(fact.value)
        if category=="interior" and not re.search(r"interior|living|bedroom|kitchen|lounge|natural light",value):continue
        if category=="exterior" and not re.search(r"exterior|facade|façade|tower|architecture",value):continue
        if category=="layout":
            label_type="office" if "office" in subject else next((x for x in subject.split() if x.isdigit()),None)
            value_type="office" if "office" in value else next((x for x in value.split() if x.isdigit()),None)
            if label_type is None or label_type!=value_type:continue
        elif words and not any(word in value for word in words):continue
        result.append(fact)
    return result[:6]

def _visual_evidence(items,project):
    result=[]
    for asset in items:
        source=asset.get("source_file") or asset.get("source_document") or asset.get("path")
        result.append(EvidenceReference(str(asset.get("asset_id")),str(asset.get("dominant_subject") or asset.get("asset_type")),"visual_inventory",source,asset.get("source_document") or source,asset.get("source_page") or asset.get("page"),None,None,project,"visual_only",None))
    return _unique_evidence(result)
def _location_text(text):return bool(re.search(r"\b(?:located|location|district|neighbou?rhood|road|street|near|minutes?|km|airport|landmark|access|connectivity)\b",str(text),re.I))
def _commercial_value(f):
    if f.get("minimum") is not None:return f"{f.get('currency') or ''} {f.get('minimum')}–{f.get('maximum')}".strip()
    if f.get("percentage") is not None:return f"{f.get('percentage')}% {str(f.get('fact_type','')).replace('_',' ')}"
    return f"{f.get('currency') or ''} {f.get('value')} {f.get('unit') or ''}".strip()
def _value(v):
    if isinstance(v,dict):return str(v.get("name") or v.get("value") or v.get("type") or v.get("description") or "").strip()
    return str(v or "").strip()
def _unique_evidence(items):
    result={}
    for x in items:
        locator = tuple(x.line_range) if isinstance(x.line_range, list) else x.line_range
        result[(x.fact_id,x.source_file,x.page,locator,x.paragraph)]=x
    return list(result.values())
def _sources(kpath,k,vpath):
    graph=require_canonical_graph(k)
    source_paths=[]
    for fact in graph.facts:
        for evidence in fact.provenance:
            path=evidence.get("source_file") or evidence.get("source_document")
            if path and path not in source_paths:source_paths.append(path)
    return [
        {"path":str(kpath),"role":"authoritative_department2_relational_intelligence"},
        {"path":str(vpath),"role":"optional_visual_inventory"},
        *[{"path":str(path),"role":"source_document"} for path in source_paths],
    ]
def _read(path):
    try:return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else {}
    except (OSError,ValueError):return {}
def _id(prefix,*parts):return f"{prefix}_{hashlib.sha256('|'.join(_norm(x) for x in parts).encode()).hexdigest()[:12]}"
def _norm(v):return re.sub(r"\s+"," ",re.sub(r"[^\w]+"," ",str(v).casefold())).strip()
def _display(v):return str(v).replace("_"," ").strip().title()
def _belongs(owner,project):return bool(owner) and _norm(owner)==_norm(project)
def _approved_external(source,status):
    allowed={"official_developer","official_project","government","municipality","infrastructure_authority","mapping_authority","approved_authoritative_external"}
    return bool(str(status).casefold()=="verified" and source.get("project_match") is True and str(source.get("source_type","")).casefold() in allowed and str(source.get("conflict_state") or "resolved").casefold()=="resolved" and source.get("retrieval_timestamp") and source.get("domain"))
