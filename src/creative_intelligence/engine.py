"""Deterministic, fail-closed Real Estate Creative Intelligence engine."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from src.creative_intelligence.schema import CreativeOpportunityMap, Opportunity, TruthLayer
from src.plan_integrity import PLAN_TYPES, UNIT_TYPES
from src.unit_plan_relationship import relationship_errors
from src.utils.config import CREATIVE_INTELLIGENCE_OUTPUT_DIRECTORY
from src.utils.config import PROJECT_ROOT, CACHE_METADATA_OUTPUT_DIRECTORY
from src.creative_library import CreativeIntelligenceLibrary, PatternRetriever, RetrievalContext

RECI_VERSION = "1.0"
HIGH_RISK = {"pricing", "payment_plan", "availability", "investment", "roi", "rental_yield", "handover", "discount", "scarcity"}
COMPARATIVES = {"best", "largest", "highest", "most luxurious", "most profitable", "number one", "only project", "unique"}
CATEGORY_TYPES = {
    "project": "project_overview", "location": "location_advantage", "architecture": "architecture_hero",
    "interior": "interior_hero", "unit": "unit_features", "amenity": "amenity_overview",
    "lifestyle": "convenience", "commercial": "commercial_breakdown", "investment": "investment_positioning",
    "educational": "project_faq", "conversion": "request_availability",
}


class RealEstateCreativeIntelligence:
    """Convert authoritative facts into bounded, auditable content opportunities."""

    def run(self, knowledge_path: Path, evaluation_path: Path | None = None,
            inventory_path: Path | None = None, plan_path: Path | None = None,
            performance_learning_path: Path | None = None,
            output_directory: Path | None = None) -> Path:
        knowledge = _read(knowledge_path)
        evaluation = _read(evaluation_path)
        inventory = _read(inventory_path)
        plans = _read(plan_path)
        performance_learning = _read(performance_learning_path)
        result = self.build(knowledge, evaluation=evaluation, inventory=inventory, plans=plans,
                            performance_learning=performance_learning,
                            project_hint=knowledge_path.stem,
                            input_paths=[p for p in (knowledge_path, evaluation_path, inventory_path, plan_path, performance_learning_path) if p])
        destination = (output_directory or CREATIVE_INTELLIGENCE_OUTPUT_DIRECTORY) / f"{result.project_id}-creative-opportunity-map.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return destination

    def build(self, knowledge: dict[str, Any], *, evaluation: dict[str, Any] | None = None,
              inventory: dict[str, Any] | None = None, plans: dict[str, Any] | None = None,
              performance_learning: dict[str, Any] | None = None,
              project_hint: str = "Project", input_paths: list[Path] | None = None) -> CreativeOpportunityMap:
        evaluation, inventory, plans = evaluation or {}, inventory or {}, plans or {}
        project = _project_id(knowledge, project_hint)
        _assert_project(project, inventory, plans)
        facts = _collect_facts(knowledge, project)
        assets = _assets(inventory, project)
        interpretations = [_interpret(f) for f in facts]
        hypotheses = _audiences(facts)
        opportunities = _opportunities(facts, assets, plans, hypotheses, evaluation, project)
        performance_context = _apply_performance_advice(opportunities, performance_learning or {}, project)
        library=CreativeIntelligenceLibrary.default(PROJECT_ROOT);library_payload=library.initialize()
        retriever=PatternRetriever(library,CACHE_METADATA_OUTPUT_DIRECTORY/"creative-retrieval")
        _enrich_patterns(opportunities,assets,hypotheses,retriever,project)
        weaknesses = _weaknesses(facts, assets, plans)
        restrictions = sorted({r for item in opportunities for r in item.restrictions})
        metrics = _metrics(opportunities, hypotheses)
        profile = _profile(facts, assets, opportunities)
        fingerprint = _fingerprint(knowledge, evaluation, inventory, plans,{"creative_library_version":library_payload["library_version"]})
        critique = {
            "evidence_backed": all(x.supporting_fact_ids or (x.status in {"BLOCKED","LIMITED"} and x.restrictions) for x in opportunities),
            "duplicate_opportunities": False,
            "unsupported_investment_language": False,
            "layout_relationships_protected": all(not x.layout_sensitive or x.status in {"BLOCKED", "REVIEW_REQUIRED"} or x.evidence_strength >= 80 for x in opportunities),
            "opportunity_count_justified_by_source_depth": len(opportunities) <= max(5, len(facts)),
        }
        return CreativeOpportunityMap(project, RECI_VERSION, datetime.now(timezone.utc).isoformat(),
            "canonical_creative_opportunity_map", fingerprint, str(knowledge.get("knowledge_version") or knowledge.get("schema_version") or "unknown"),
            profile, facts, interpretations, hypotheses, opportunities, weaknesses, restrictions, critique, metrics,
            {"input_paths": [str(p) for p in input_paths or []], "fact_ids": [f["fact_id"] for f in facts], "reci_version": RECI_VERSION,"creative_library_path":str(library.path)},library_payload["library_version"],
            str((performance_learning or {}).get("learning_version") or "unavailable"), performance_context)


def _apply_performance_advice(opportunities: list[Opportunity], learning: dict[str, Any], project: str) -> dict[str, Any]:
    """Apply a bounded tie-breaker only after evidence and buyer relevance."""
    if not learning or learning.get("status") == "COLD_START":
        return {"status": "COLD_START", "advisory_only": True, "score_adjustment_limit": 0}
    project_data = (learning.get("project_effectiveness") or {}).get(project, {})
    categories = project_data.get("category_performance") or (learning.get("account_effectiveness") or {}).get("category_performance", [])
    signals = {str(x.get("content_category")): x for x in categories if x.get("performance_confidence") in {"MODERATE_CONFIDENCE", "STRONG_SIGNAL"}}
    applied = []
    for opportunity in opportunities:
        signal = signals.get(opportunity.category)
        if not signal or opportunity.status in {"BLOCKED", "REVIEW_REQUIRED"} or opportunity.evidence_strength < 60:
            continue
        adjustment = max(-5, min(5, round((float(signal.get("average_performance_score", 50)) - 50) / 10)))
        opportunity.score = max(0, min(100, opportunity.score + adjustment))
        opportunity.explanation += f" Historical account performance supplied an advisory {adjustment:+d} tie-breaker; association only."
        applied.append({"opportunity_id": opportunity.opportunity_id, "adjustment": adjustment})
    return {"status": "APPLIED" if applied else "NO_CONFIDENT_MATCH", "advisory_only": True,
            "score_adjustment_limit": 5, "safety_precedence": "evidence_before_performance", "applied": applied}


def _read(path: Path | None) -> dict[str, Any]:
    if not path or not path.is_file(): return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _norm(value: Any) -> str: return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
def _stable(prefix: str, *values: Any) -> str:
    return f"{prefix}_{hashlib.sha256('|'.join(_norm(x) for x in values).encode()).hexdigest()[:12]}"
def _project_id(k: dict[str, Any], fallback: str) -> str:
    return str(k.get("project_id") or k.get("project_identity", {}).get("project_name") or k.get("project", {}).get("name") or fallback)
def _same(a: Any, b: Any) -> bool: return bool(a) and _norm(a) == _norm(b)


def _assert_project(project: str, inventory: dict[str, Any], plans: dict[str, Any]) -> None:
    for artifact, label in ((inventory, "visual inventory"), (plans, "plan intelligence")):
        owner = artifact.get("project_id") or artifact.get("project")
        if owner and not _same(owner, project): raise ValueError(f"RECI blocked cross-project {label}: {owner!r}")


def _collect_facts(k: dict[str, Any], project: str) -> list[dict[str, Any]]:
    provenance = k.get("fact_provenance") if isinstance(k.get("fact_provenance"), dict) else {}
    raw: list[tuple[str, Any, str]] = []
    identity = k.get("project_identity", {}); legacy = k.get("project", {})
    for field in ("project_name", "project_type", "location", "developer_name"):
        value = identity.get(field) or legacy.get({"project_name":"name", "developer_name":"developer"}.get(field, field))
        if value: raw.append((f"project_identity.{field}", value, "project" if field != "location" else "location"))
    for i, value in enumerate(k.get("amenities", []) or []): raw.append((f"amenities[{i}]", value, "amenity"))
    for i, value in enumerate(k.get("units", []) or []): raw.append((f"units[{i}]", value, "unit"))
    for field, value in (k.get("architecture", {}) or {}).items():
        for i, item in enumerate(value if isinstance(value, list) else [value] if value else []): raw.append((f"architecture.{field}[{i}]", item, "architecture"))
    for field, category in (("pricing","commercial"),("commercial_intelligence","commercial"),("investment","investment"),("location_intelligence","location"),("plan_intelligence","unit"),("interiors","interior"),("services","lifestyle")):
        value=k.get(field)
        if isinstance(value, dict):
            for key,item in value.items():
                if item not in (None,"",[],{}): raw.append((f"{field}.{key}",item,category))
    for i, fact in enumerate(k.get("canonical_facts", []) or []):
        if isinstance(fact, dict): raw.append((str(fact.get("fact_id") or f"canonical_facts[{i}]"), fact.get("value"), str(fact.get("category") or "educational")))
    for i, fact in enumerate(k.get("recovered_atomic_facts", []) or []):
        if isinstance(fact, dict): raw.append((str(fact.get("fact_id") or f"recovered_atomic_facts[{i}]"), fact, str(fact.get("category") or "educational")))
    facts=[];seen=set()
    for path,value,category in raw:
        display=value.get("value") or value.get("text") if isinstance(value,dict) else value
        text=json.dumps(display,ensure_ascii=False,sort_keys=True) if isinstance(display,(dict,list)) else str(display)
        category=_category(category,text)
        if not text.strip() or (_norm(text),category) in seen: continue
        seen.add((_norm(text),category)); records=provenance.get(path, [])
        if not records and "[" in path: records=provenance.get(path.split("[")[0], [])
        embedded = value.get("sources", []) if isinstance(value,dict) else []
        if isinstance(value,dict) and isinstance(value.get("provenance"),dict): embedded=[value["provenance"]]
        sources = records or embedded
        risk = _risk(path, text)
        fact_id = path if path.startswith("fact_") else _stable("fact", project, path, text)
        layer=str(value.get("fact_type") if isinstance(value,dict) and value.get("fact_type") else TruthLayer.VERIFIED_FACT.value)
        facts.append({"fact_id":fact_id,"path":path,"value":display,"text":text,"category":category,
            "truth_layer":layer,"confidence":_confidence(value),"authority":_authority(value,sources),
            "freshness":_freshness(value),"relationship_status":_relationship(value),"provenance":sources,
            "claim_risk":risk,"eligible":bool(sources) or risk=="LOW"})
    return facts


def _confidence(v: Any) -> float:
    if isinstance(v,dict):
        try:return max(0,min(1,float(v.get("confidence",v.get("scores",{}).get("factual_confidence",1)))))
        except (TypeError,ValueError):pass
    return 1.0
def _authority(v: Any, sources: list[Any]) -> str:
    return str(v.get("authority") if isinstance(v,dict) and v.get("authority") else "SOURCE_PROVENANCE" if sources else "STRUCTURED_KNOWLEDGE")
def _freshness(v: Any) -> str: return str(v.get("freshness") if isinstance(v,dict) and v.get("freshness") else "CURRENT_OR_NOT_TIME_SENSITIVE").upper()
def _relationship(v: Any) -> str: return str(v.get("relationship_status") if isinstance(v,dict) and v.get("relationship_status") else "VERIFIED").upper()
def _risk(path: str, text: str) -> str:
    hay=_norm(path+" "+text)
    return "HIGH" if any(_norm(x) in hay for x in HIGH_RISK) else "MEDIUM" if any(x in hay for x in ("developer","area","layout","bedroom","bathroom")) else "LOW"
def _category(category:str,text:str)->str:
    value=_norm(category);hay=_norm(text)
    if value in {"identity","project_identity"}:return "project"
    if value in {"services","service"}:return "lifestyle"
    if value in {"architecture_interior","architecture interior"}:
        return "architecture" if any(x in hay for x in ("architecture","window","facade","exterior","design")) else "interior"
    if value in {"units","unit_information","unit intelligence","plan","plan_intelligence"}:return "unit"
    if value in CATEGORY_TYPES:return value
    return "educational"


def _assets(inv: dict[str, Any], project: str) -> list[dict[str, Any]]:
    values=list(inv.get("assets",[]) or [])+list(inv.get("images",[]) or [])
    for key,items in inv.items():
        if key.startswith("available_") and isinstance(items,list): values.extend(x for x in items if isinstance(x,dict))
    found={}
    for asset in values:
        aid=str(asset.get("asset_id") or ""); owner=asset.get("project_id") or asset.get("source_project") or asset.get("project") or project
        if aid and _same(owner,project):found[aid]=asset
    return list(found.values())


def _interpret(f: dict[str, Any]) -> dict[str, Any]:
    category=f["category"]; mapping={"location":"Connectivity and convenience may matter to buyers.","unit":"Space and practical usability can support the sales conversation.","amenity":"A verified amenity can make the project experience concrete.","architecture":"Design quality can differentiate the project visually.","interior":"Interior evidence can explain finish and living-space character.","commercial":"Authoritative commercial detail can reduce inquiry friction.","investment":"Verified investment information can support an investor conversation.","project":"Project identity builds understanding and trust."}
    return {"interpretation_id":_stable("interp",f["fact_id"]),"truth_layer":TruthLayer.COMMERCIAL_INTERPRETATION.value,
            "supporting_fact_ids":[f["fact_id"]],"buyer_meaning":mapping.get(category,"This verified detail can answer a buyer question."),
            "buyer_desires":_desires(category),"confidence":round(f["confidence"]*.9,2)}
def _desires(category: str) -> list[str]:
    return {"location":["LOCATION","CONVENIENCE"],"unit":["SPACE","FLEXIBILITY"],"amenity":["AMENITIES","LIFESTYLE"],"architecture":["DESIGN_QUALITY","PRESTIGE"],"interior":["DESIGN_QUALITY","LIFESTYLE"],"commercial":["VALUE"],"investment":["INVESTMENT"],"project":["STATUS"]}.get(category,["PROJECT_UNDERSTANDING"])


def _audiences(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    joined=" ".join(f["text"] for f in facts).casefold(); result=[]
    rules=(("investor",("investment","rental","commercial")),("family_buyer",("bedroom","family","school","playground")),("business_owner",("office","retail","business")),("luxury_buyer",("luxury","premium","prestige")),("end_user",("residential","apartment","villa")))
    for audience,tokens in rules:
        support=[f["fact_id"] for f in facts if any(t in f["text"].casefold() for t in tokens)]
        if support: result.append({"hypothesis_id":_stable("aud",audience,*support),"truth_layer":TruthLayer.AUDIENCE_HYPOTHESIS.value,"audience_type":audience,"reason":f"Verified project evidence mentions {', '.join(t for t in tokens if t in joined)}.","supporting_facts":support[:8],"confidence":round(min(.9,.45+.08*len(support)),2),"status":"HYPOTHESIS"})
    return result


def _opportunities(facts:list[dict[str,Any]],assets:list[dict[str,Any]],plans:dict[str,Any],hypotheses:list[dict[str,Any]],evaluation:dict[str,Any],project:str)->list[Opportunity]:
    bycat={c:[f for f in facts if f["category"]==c] for c in CATEGORY_TYPES}; result=[]
    for category,otype in CATEGORY_TYPES.items():
        group=bycat[category];relevant=_matching_assets(category,assets)
        if not group and category not in {"commercial","investment"} and not (category=="unit" and relevant):continue
        blocked=[];restrictions=[]
        eligible=[f for f in group if f["eligible"] and f["freshness"] not in {"STALE","EXPIRED"} and f["relationship_status"] not in {"CONFLICTED","AMBIGUOUS","UNVERIFIED"}]
        if category in {"commercial","investment"}:
            if not group: restrictions.append(f"No authoritative {category} evidence; do not create current {category} claims.")
            for f in group:
                if not f["provenance"]: blocked.append(f["fact_id"]);restrictions.append("High-risk commercial claims require provenance.")
                if f["freshness"] in {"STALE","EXPIRED"}:blocked.append(f["fact_id"]);restrictions.append("Stale commercial facts cannot be presented as current.")
                if any(x in _norm(f["text"]) for x in COMPARATIVES):blocked.append(f["fact_id"]);restrictions.append("Unsupported comparative claims are prohibited.")
        layout=category=="unit" and any("layout" in _norm(f["path"]+f["text"]) for f in group)
        layout=layout or (category=="unit" and any(_asset_type(a) in {"floorplan","floor_plan","unit_layout"} for a in relevant))
        if layout:
            records=[p for p in plans.get("assets",[]) if p.get("asset_type") in UNIT_TYPES]
            verified=[p for p in records if p.get("marketing_eligible") and not relationship_errors(p, expected_project=project)]
            verified_ids={p["asset_id"] for p in verified}
            relevant=[a for a in relevant if a.get("asset_id") in verified_ids]
            if not verified: restrictions.append("Exact unit layout relationship is not VERIFIED.");blocked.extend(f["fact_id"] for f in group)
        evidence=round(100*sum(f["confidence"] for f in eligible)/max(1,len(group)))
        if group and any(not f["provenance"] for f in group): evidence=min(evidence,70)
        visual=_visual_strength(relevant); buyer=min(95,55+8*len(eligible));commercial=min(95,45+10*len(eligible));content=min(95,45+8*len(eligible)+visual//10);diff=min(90,40+8*len(eligible));lead=80 if category in {"commercial","conversion","unit"} else 65
        score=round(.25*evidence+.15*buyer+.15*visual+.15*commercial+.10*content+.10*diff+.10*lead)
        if restrictions and (category in {"commercial","investment"} or layout):
            status="LIMITED" if not group and category in {"commercial","investment"} else "BLOCKED" if not eligible or blocked else "REVIEW_REQUIRED"
        elif score>=80:status="STRONG"
        elif score>=70:status="GOOD"
        elif score>=60:status="LIMITED"
        else:status="LIMITED"
        priority="BLOCKED" if status=="BLOCKED" else "ELITE" if score>=90 else "STRONG" if score>=80 else "GOOD" if score>=70 else "LIMITED" if score>=60 else "LOW"
        ids=[f["fact_id"] for f in eligible][:12]; asset_ids=[str(a["asset_id"]) for a in relevant][:12]
        result.append(Opportunity(_stable("op",project,category,otype),otype,category,otype.replace("_"," ").title(),
            f"Communicate verified {category} value without extending beyond the evidence.",_desires(category),
            f"Answers a buyer's {category} question.",f"Explain the verified {category} evidence and why it may matter.",ids,asset_ids,evidence,buyer,visual,commercial,content,diff,lead,score,status,priority,
            _formats(otype),["instagram","facebook"],sorted(set(restrictions)),sorted(set(blocked)),[h["hypothesis_id"] for h in hypotheses if set(h["supporting_facts"])&set(ids)],
            [category,"informational_graphic"],asset_ids,{aid:visual for aid in asset_ids},[f"{len(asset_ids)} authentic candidate asset(s) matched." if asset_ids else "No authentic visual support; keep informational or limited."],round(evidence/100,2),
            f"{len(ids)} eligible verified fact(s) + visual strength {visual} + commercial relevance {commercial} = score {score}.",
            [*[{"truth_layer":layer,"ids":[f["fact_id"] for f in eligible if f["truth_layer"]==layer]} for layer in sorted({f["truth_layer"] for f in eligible})],{"truth_layer":TruthLayer.CONTENT_OPPORTUNITY.value,"statement":otype},{"truth_layer":TruthLayer.RESTRICTION.value,"statements":sorted(set(restrictions))}],layout))
    return _dedupe(result)


def _matching_assets(category:str, assets:list[dict[str,Any]])->list[dict[str,Any]]:
    aliases={"project":{"exterior","exterior_render","logo","aerial_view","masterplan"},"location":{"location_map","map","aerial_view"},"architecture":{"exterior","exterior_render","architectural_detail"},"interior":{"interior","interior_render","residential_space","commercial_space"},"unit":{"floorplan","floor_plan","unit_layout"},"amenity":{"amenity","landscape"},"lifestyle":{"lifestyle","landscape"},"commercial":{"diagram","logo","exterior","exterior_render"},"investment":{"diagram","exterior","exterior_render"},"educational":{"diagram","floorplan","floor_plan","location_map","masterplan"},"conversion":{"logo","exterior","exterior_render"}}
    wanted=aliases.get(category,set());return [a for a in assets if _asset_type(a) in wanted]
def _asset_type(a:dict[str,Any])->str:
    return _norm(a.get("asset_type") or a.get("visual_category") or a.get("source_image_type") or a.get("deep_image_type")).replace(" ","_")
def _visual_strength(assets:list[dict[str,Any]])->int:
    if not assets:return 0
    scores=[]
    for a in assets:
        value=a.get("quality_score",a.get("visual_quality_score",a.get("image_quality",{}).get("score",0)))
        try:scores.append(float(value or 0))
        except (TypeError,ValueError):scores.append(0)
    return round(min(100,sum(scores)/len(scores)+min(20,5*len(assets))))
def _formats(otype:str)->list[str]:
    if "layout" in otype or "comparison" in otype or "location" in otype or "commercial" in otype:return ["instagram_carousel","instagram_story"]
    return ["instagram_feed","instagram_carousel"]
def _dedupe(items:list[Opportunity])->list[Opportunity]:
    found={}
    for item in items:
        key=(item.category,_norm(item.opportunity_type))
        if key not in found or item.score>found[key].score:found[key]=item
    return list(found.values())

def _enrich_patterns(opportunities,assets,hypotheses,retriever,project):
    by_id={str(a.get("asset_id")):a for a in assets}
    audience=str(hypotheses[0]["audience_type"]) if hypotheses else ""
    for op in opportunities:
        candidates=[by_id[x] for x in op.supporting_asset_ids if x in by_id]
        preferred={"project":{"exterior","exterior_render","architecture_hero"},"architecture":{"exterior","exterior_render","architectural_detail"}}
        first=next((a for a in candidates if _asset_type(a) in preferred.get(op.category,set())),candidates[0] if candidates else {})
        asset_type=_asset_type(first) if first else "text_only"
        opportunity_type="unit_layout" if op.layout_sensitive else "project_hero" if op.category=="project" else op.opportunity_type
        relationship="UNVERIFIED" if op.layout_sensitive and op.status in {"BLOCKED","REVIEW_REQUIRED"} else "VERIFIED"
        result=retriever.retrieve(RetrievalContext(project,opportunity_type,asset_type=asset_type,platform=(op.recommended_platforms or ["instagram_feed"])[0],audience_hypothesis=audience,information_density="technical" if op.layout_sensitive else "",visual_strength=op.visual_strength,commercial_strength=op.commercial_strength,evidence_strength=op.evidence_strength,relationship_status=relationship),limit=3)
        op.recommended_patterns=result["top_relevant_patterns"];op.relevant_anti_patterns=result["relevant_anti_patterns"]
        op.pattern_usage={"library_version":result["library_version"],"pattern_influence":"advisory","pattern_ids_considered":result["pattern_ids_considered"],"pattern_ids_selected":result["pattern_ids_selected"],"pattern_ids_rejected":result["pattern_ids_rejected"],"reason":"contextual retrieval; patterns contributed no project facts"}


def _weaknesses(facts,assets,plans)->list[str]:
    categories={f["category"] for f in facts};result=[]
    if "commercial" not in categories:result.append("missing commercial evidence")
    if "investment" not in categories:result.append("no verified investment claims")
    if not _matching_assets("amenity",assets):result.append("no authentic amenity visuals")
    if not any(p.get("marketing_eligible") and not relationship_errors(p) for p in plans.get("assets",[])):result.append("poor layout coverage")
    if len({f["category"] for f in facts})<4:result.append("limited content diversity")
    return result
def _profile(facts,assets,opps)->dict[str,int]:
    cat=Counter(f["category"] for f in facts);strong=[o for o in opps if o.status in {"STRONG","GOOD"}]
    base=lambda name:min(100,cat[name]*18)
    return {"knowledge_strength":round(100*sum(f["confidence"] for f in facts)/max(1,len(facts))),"visual_strength":_visual_strength(assets),"commercial_strength":base("commercial"),"location_strength":base("location"),"unit_content_strength":base("unit"),"lifestyle_strength":base("lifestyle"),"amenity_strength":base("amenity"),"investment_content_strength":base("investment"),"educational_content_strength":base("educational"),"lead_generation_strength":round(sum(o.lead_generation_potential for o in opps)/max(1,len(opps))),"carousel_potential":min(100,len(strong)*15),"story_potential":min(100,len(opps)*12),"overall_content_potential":round(sum(o.score for o in opps)/max(1,len(opps)))}
def _metrics(opps,hypotheses)->dict[str,Any]:
    counts=Counter(o.category for o in opps);categories=("project","location","architecture","interior","unit","amenity","lifestyle","commercial","investment","educational","conversion")
    return {"total_opportunities":len(opps),"elite_opportunities":sum(o.priority=="ELITE" for o in opps),"strong_opportunities":sum(o.status=="STRONG" for o in opps),"good_opportunities":sum(o.status=="GOOD" for o in opps),"limited_opportunities":sum(o.status=="LIMITED" for o in opps),"blocked_opportunities":sum(o.status=="BLOCKED" for o in opps),"review_required":sum(o.status=="REVIEW_REQUIRED" for o in opps),"average_evidence_strength":round(sum(o.evidence_strength for o in opps)/max(1,len(opps)),1),"average_visual_strength":round(sum(o.visual_strength for o in opps)/max(1,len(opps)),1),"category_distribution":{x:counts[x] for x in categories},"audience_hypotheses_count":len(hypotheses),"commercial_opportunities":sum(o.category=="commercial" for o in opps),"layout_sensitive_opportunities":sum(o.layout_sensitive for o in opps)}
def _fingerprint(*values:dict[str,Any])->str:
    return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
