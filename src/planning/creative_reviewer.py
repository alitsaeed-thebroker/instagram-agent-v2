"""Senior real-estate creative portfolio gate for Department 3."""
from __future__ import annotations
from datetime import datetime,timezone
from difflib import SequenceMatcher
import hashlib,json,re
from pathlib import Path
from typing import Any

REVIEWER_VERSION="1.1.2"
DECISIONS={"approve","revise","hold","reject"}

class RealEstateCreativeReviewer:
    """Select a coherent, evidence-safe portfolio before creative production."""
    def __init__(self,root:Path)->None:self.root=root
    def review(self,project:str,content_path:Path,knowledge_path:Path,strategy_path:Path,inventory_path:Path)->tuple[Path,Path]:
        content=_read(content_path);knowledge=_read(knowledge_path);strategy=_read(strategy_path);inventory=_read(inventory_path)
        for value in (content,inventory):
            if value.get("project_id",value.get("project")) not in {None,project}:raise ValueError("Creative review input belongs to another project")
        assets=_index_assets(inventory);decisions=[];approved=[];signatures=[]
        for idea in content.get("content_ideas",[]):
            decision=_decision(project,idea,assets,knowledge,strategy,signatures);decisions.append(decision)
            if decision["decision"] in {"approve","revise"}:
                approved.append({**idea,"creative_review":{k:decision[k] for k in ("decision","priority","portfolio_role","review_id")}});signatures.append(_signature(idea))
        reviewed={**content,"content_ideas":approved,"creative_reviewer_version":REVIEWER_VERSION,"creative_review_status":"approved_portfolio" if approved else "no_approved_content","original_idea_count":len(content.get("content_ideas",[])),"approved_idea_count":len(approved)}
        if content.get("lineage"):
            from src.execution.lineage import attach_lineage,require_lineage,canonical_graph_fingerprint
            fingerprint=canonical_graph_fingerprint(knowledge)
            require_lineage(content,expected_stage="department3-content-plan",canonical_fingerprint=fingerprint)
            reviewed=attach_lineage(reviewed,stage="creative-reviewed-content-plan",canonical_fingerprint=fingerprint,parents={"canonical_content_plan":content["artifact_fingerprint"]})
        report_path=self.root/"output"/"creative-reviews"/f"{project}-creative-review.json";report_path.parent.mkdir(parents=True,exist_ok=True)
        reviewed_path=report_path.parent/"approved"/f"{project}-content-plan.json"
        reviewed_path.parent.mkdir(parents=True,exist_ok=True)
        reviewed_path.write_text(json.dumps(reviewed,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        report={"project_id":project,"reviewer_version":REVIEWER_VERSION,"status":"completed","decisions":decisions,"summary":{d:sum(x["decision"]==d for x in decisions) for d in sorted(DECISIONS)},"approved_portfolio_ids":[x.get("content_idea_id") for x in approved],"created_at":datetime.now(timezone.utc).isoformat()};report_path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        return reviewed_path,report_path

def _index_assets(value:Any)->dict[str,dict[str,Any]]:
    """Index canonical inventory assets regardless of their category bucket."""
    indexed:dict[str,dict[str,Any]]={}
    def visit(node:Any)->None:
        if isinstance(node,dict):
            asset_id=node.get("asset_id")
            if isinstance(asset_id,str) and asset_id:
                previous=indexed.get(asset_id)
                if previous is not None and previous!=node:
                    raise ValueError(f"Conflicting visual inventory records for asset_id {asset_id!r}")
                indexed[asset_id]=node
                return
            for child in node.values():visit(child)
        elif isinstance(node,list):
            for child in node:visit(child)
    visit(value)
    return indexed

def _decision(project:str,idea:dict[str,Any],assets:dict[str,dict[str,Any]],knowledge:dict[str,Any],strategy:dict[str,Any],signatures:list[str])->dict[str,Any]:
    iid=str(idea.get("content_idea_id") or "");ids=list(dict.fromkeys(idea.get("selected_source_asset_ids") or []));resolved=[assets[x] for x in ids if x in assets];reasons=[];risks=[]
    usable=[x for x in resolved if x.get("analysis_status") not in {"failed","review_required","unsuitable"} and x.get("asset_type") not in {"unknown","unsuitable"}]
    visual=35 if usable and len(usable)==len(ids) else 12 if usable else 0
    if not usable:reasons.append("No production-eligible authentic visual is attached.")
    if len(usable)!=len(ids):risks.append("One or more selected assets are unresolved or unsafe.")
    factual=20 if idea.get("selected_fact_refs") or idea.get("factual_evidence") else 12 if idea.get("source_support_status") in {"partially_supported","visual_only"} else 5
    market=15 if idea.get("target_persona") and idea.get("funnel_stage") else 8
    format_score=15 if idea.get("planned_destinations") and idea.get("feasible_formats") else 5
    sig=_signature(idea);duplicate=max((SequenceMatcher(None,sig,x).ratio() for x in signatures),default=0);distinct=15 if duplicate<.72 else 5 if duplicate<.88 else 0
    if duplicate>=.88:reasons.append("Concept substantially duplicates an already selected portfolio item.")
    score=visual+factual+market+format_score+distinct
    decision="reject" if not usable or duplicate>=.92 else "hold" if score<55 else "revise" if score<75 or risks else "approve"
    subject=str(idea.get("title") or idea.get("content_objective") or "Project story");kind=str(usable[0].get("asset_type") if usable else "unresolved")
    return {"review_id":"review_"+hashlib.sha256(f"{project}|{iid}|{REVIEWER_VERSION}".encode()).hexdigest()[:18],"content_idea_id":iid,"decision":decision,"score":score,"priority":"high" if score>=85 else "medium" if score>=70 else "low","portfolio_role":_role(kind,idea),"recommended_platforms":idea.get("planned_destinations") or idea.get("feasible_platforms") or [],"recommended_formats":idea.get("feasible_formats") or [],"approved_source_asset_ids":[x.get("asset_id") for x in usable],"verified_fact_refs":idea.get("selected_fact_refs") or [],"design_brief":f"Build a clear {kind.replace('_',' ')}-led composition around {subject}; preserve the authentic source as visual truth and use restrained Domus Erbil hierarchy.","allowed_claims":idea.get("factual_evidence") or [],"forbidden_claims":idea.get("forbidden_claims") or ["unsupported project or commercial claims"],"reasons":reasons or ["Strong enough to contribute a distinct, producible role to the portfolio."],"risks":risks,"bounded_revision":"Repair copy, format, or source selection only; do not invent facts or imagery." if decision=="revise" else None}

def _role(kind:str,idea:dict[str,Any])->str:
    if kind in {"masterplan","site_plan","location_map"}:return "project_context"
    if kind=="floorplan":return "layout_education"
    if kind in {"amenity","lifestyle","garden_landscape"}:return "experience_story"
    if kind in {"exterior","aerial_view"}:return "architecture_hero"
    if kind in {"interior","commercial_space"}:return "space_experience"
    return "supporting_story"
def _signature(idea:dict[str,Any])->str:return re.sub(r"\W+"," "," ".join(str(idea.get(x) or "") for x in ("title","content_objective","concept_summary")).casefold()).strip()
def _read(path:Path)->dict[str,Any]:return json.loads(path.read_text(encoding="utf-8"))
