"""Semantic, source-grounded validation and image-production routing."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib, json, re
from pathlib import Path
from typing import Any

from src.core.logger import get_logger
from src.content.inventory import VISUAL_TYPES
from src.production.eligibility import WARNING_SCHEMA_VERSION, warning_for_message
from src.utils.config import IMAGE_PROMPTS_OUTPUT_DIRECTORY, PROJECT_ROOT, PROJECT_VISUAL_MODE

MODULE_VERSION = "2.2.0"
PROMPT_TEMPLATE_VERSION = "2.2.0"
MODEL_POLICY = "deterministic-source-only"
logger = get_logger(__name__)

_UNSUITABLE = {"unsuitable", "rejected", "invalid", "do_not_use", "not_suitable"}
_DETERMINISTIC = {"crop", "resize", "contain", "contain_letterbox", "letterbox", "padding",
    "format_conversion", "compression", "moderate_sharpening", "mild_sharpening", "denoising",
    "exposure_adjustment", "brightness_adjustment", "white_balance_correction", "pdf_margin_removal",
    "compression_cleanup", "deblocking", "contrast_adjustment", "super_resolution"}
_TYPE_MAP = {"floorplan":"floorplan_presentation", "masterplan":"masterplan_presentation",
    "site_plan":"site_plan_presentation", "location_map":"location_map_presentation", "map":"location_map_presentation",
    "infographic":"infographic_presentation", "logo":"text_supported_graphic"}
_PRESERVE = {
    "exterior": ["architecture", "facade", "roofline", "doors", "windows", "landscaping", "visible vehicles and people"],
    "interior": ["room geometry", "furniture", "finishes", "lighting fixtures", "openings", "visible decor"],
    "lifestyle": ["visible people", "poses", "activity", "environment", "sports equipment", "landscaping"],
    "floorplan": ["geometry", "walls", "dimensions", "room labels", "doors", "windows", "circulation", "scale"],
    "masterplan": ["footprints", "roads", "plots", "amenities", "landscaping", "boundaries", "labels", "orientation"],
    "site_plan": ["footprints", "roads", "plots", "amenities", "landscaping", "boundaries", "labels", "orientation"],
    "location_map": ["roads", "location markers", "boundaries", "labels", "orientation", "relative scale"],
    "logo": ["logo geometry", "letterforms", "colors", "spacing", "project identity"],
}
_FORBIDDEN = {
    "exterior": ["invented architecture", "redesigned facade", "changed floors", "changed roofline, doors, or windows", "invented landscaping", "invented people or vehicles", "new viewpoint"],
    "interior": ["changed room geometry", "replaced furniture or finishes", "changed openings", "invented decor or people", "new viewpoint"],
    "lifestyle": ["invented people", "changed poses or activity", "invented sports equipment", "changed environment or landscaping", "new viewpoint"],
    "floorplan": ["changed geometry, walls, dimensions, labels, doors, or windows", "added or removed rooms", "invented furniture layout"],
    "masterplan": ["changed footprints, roads, plots, amenities, boundaries, labels, orientation, or scale", "invented 3D architecture"],
    "site_plan": ["changed footprints, roads, plots, amenities, boundaries, labels, orientation, or scale", "invented 3D architecture"],
    "location_map": ["changed roads, markers, boundaries, labels, orientation, or scale", "invented location claims"],
    "logo": ["redesigned logo", "changed letterforms, colors, or spacing", "synthetic project imagery"],
}

class ImagePromptGenerator:
    def run(self, *, project: str, processing_path: Path, asset_intelligence_path: Path,
            visual_inventory_path: Path, knowledge_path: Path | None = None, content_path: Path | None = None,
            campaign_path: Path | None = None, creative_path: Path | None = None, scene_path: Path | None = None,
            shot_path: Path | None = None, opportunities_path: Path | None = None,
            strategy_path: Path | None = None, source_manifest_path: Path | None = None) -> tuple[Path, Path]:
        if PROJECT_VISUAL_MODE != "source_only": raise ValueError("Image Prompt Generator requires PROJECT_VISUAL_MODE=source_only")
        logger.info("Reading validated source assets and production plans...")
        processing, intelligence, inventory = map(_read, (processing_path, asset_intelligence_path, visual_inventory_path))
        for value in (processing, intelligence, inventory):
            if value.get("project", value.get("project_id")) not in {None, project}: raise ValueError("Prompt inputs belong to another project")
        optional={"knowledge":knowledge_path,"content":content_path,"campaign":campaign_path,"creative":creative_path,
            "scene":scene_path,"shot":shot_path,"visual_opportunities":opportunities_path,"strategy":strategy_path}
        contexts={name:_read(path) for name,path in optional.items() if path and path.is_file()}
        if source_manifest_path and source_manifest_path.is_file():contexts["source_manifest"]=_read(source_manifest_path)
        missing=[f"Optional context missing: {name}" for name,path in optional.items() if not path or not path.is_file()]
        logger.info("Building source-grounded production prompts...")
        prompts, stats = _build(project, processing, intelligence, inventory, contexts, missing)
        logger.info("Validating prompt provenance and preservation rules...")
        out=IMAGE_PROMPTS_OUTPUT_DIRECTORY; out.mkdir(parents=True,exist_ok=True)
        canonical=out/f"{project}-image-prompts.json"; manifest=out/f"{project}-prompt-manifest.json"
        canonical.write_text(json.dumps({"project_id":project,"visual_mode":"source_only","prompts":prompts,"warnings":missing,
            "module_version":MODULE_VERSION,"prompt_template_version":PROMPT_TEMPLATE_VERSION},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        scores=[p["confidence"]["quality_score"] for p in prompts]
        payload={"project_id":project,"total_processing_plans":len(processing.get("image_processing_plans",[])),
            "total_export_variants":stats["variants"],"prompts_created":len(prompts),
            "deterministic_processing_routes":sum(p["execution_route"]=="deterministic_processor" for p in prompts),
            "ai_editing_routes":sum(p["execution_route"]=="ai_image_editor" for p in prompts),
            "production_ready":sum(p["confidence"]["status"]=="production_ready" for p in prompts),
            "production_ready_with_warnings":sum(p["confidence"]["status"]=="production_ready_with_warnings" for p in prompts),
            "review_required":sum(p["confidence"]["status"]=="review_required" for p in prompts),
            "blocked":stats["blocked"],"blocked_reason_distribution":stats["blocked_reasons"],"semantic_mismatches_repaired":stats["repaired"],
            "asset_resolution_diagnostics":stats["diagnostics"],
            "variant_authorization_diagnostics":stats["authorization_diagnostics"],
            "unauthorized_variants_removed":stats["unauthorized"],"invalid_asset_references":stats["invalid"],
            "average_quality_score":round(sum(scores)/len(scores),1) if scores else 0,
            "prompt_generator_version":MODULE_VERSION,"created_at":datetime.now(timezone.utc).isoformat()}
        manifest.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        logger.info("Image prompts saved:\n%s",_console_safe(_display(canonical)))
        logger.info("Image Prompt Generator completed:\n- Prompts created: %d\n- Deterministic processing routes: %d\n- AI editing routes: %d\n- Production ready: %d\n- Ready with warnings: %d\n- Review required: %d\n- Blocked: %d\n- Semantic mismatches repaired: %d\n- Unauthorized variants removed: %d\n- Average quality: %s/100",
            payload["prompts_created"],payload["deterministic_processing_routes"],payload["ai_editing_routes"],payload["production_ready"],payload["production_ready_with_warnings"],payload["review_required"],payload["blocked"],payload["semantic_mismatches_repaired"],payload["unauthorized_variants_removed"],payload["average_quality_score"])
        return canonical,manifest

def _read(path: Path) -> dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise ValueError(f"Expected JSON object: {path}")
    return value

def _build(project:str, processing:dict[str,Any], intel:dict[str,Any], inventory:dict[str,Any], contexts:dict[str,Any], missing:list[str]):
    assets={a.get("asset_id"):a for a in intel.get("assets",[])}; allowed=set(inventory.get("all_source_asset_ids",[]))
    source_records={a.get("asset_id"):a for a in contexts.get("source_manifest",{}).get("assets",[])}
    content=_index(contexts.get("content",{}),"content_idea_id"); opportunities=_index(contexts.get("visual_opportunities",{}),"opportunity_id")
    campaigns=_index(contexts.get("campaign",{}),"campaign_id"); fact_ids=_fact_ids(contexts.get("knowledge",{}))
    prompts=[]; used=set(); stats={"variants":0,"blocked":0,"blocked_reasons":{},"diagnostics":[],"authorization_diagnostics":[],"invalid":0,"repaired":0,"unauthorized":0}
    def block(reason: str, count: int) -> None:
        stats["blocked"] += count
        stats["blocked_reasons"][reason] = stats["blocked_reasons"].get(reason, 0) + count
    for plan in processing.get("image_processing_plans",[]):
        idea=content.get(str(plan.get("content_idea_id")),{}); campaign=campaigns.get(str(idea.get("campaign_id")),{})
        opportunity=opportunities.get(str(idea.get("selected_opportunity_id")),{})
        expected=_expected_type(idea,opportunity); approved=set(idea.get("selected_source_asset_ids",[])); ops={o.get("source_asset_id"):o for o in plan.get("source_asset_operations",[])}
        valid=[]; mismatched=[]; warnings=list(missing)
        for aid in plan.get("source_asset_ids",[]):
            asset=assets.get(aid); op=ops.get(aid); error=_asset_error(project,aid,asset,op,allowed,source_records or None)
            if error: stats["invalid"]+=1; warnings.append(error); continue
            if approved and aid not in approved: mismatched.append((asset,op,"asset is not approved for the content item")); continue
            if not _compatible(expected,asset): mismatched.append((asset,op,f"{asset.get('asset_type')} does not match {expected}")); continue
            valid.append((asset,op))
        if mismatched:
            replacements=[(assets[aid],ops[aid]) for aid in approved if aid in assets and aid in ops and _compatible(expected,assets[aid]) and not _asset_error(project,aid,assets[aid],ops[aid],allowed,source_records or None)]
            if replacements: valid=replacements; stats["repaired"]+=1; warnings.append("Semantic asset mismatch repaired using approved content-plan assets")
        variants=plan.get("export_variants",[]); stats["variants"]+=len(variants)
        diagnostic={"candidate_id":plan.get("processing_plan_id"),"content_idea_id":plan.get("content_idea_id"),
            "required_asset_type":expected,"requested_asset_ids":list(plan.get("source_asset_ids",[])),
            "resolved_asset_ids":[a[0]["asset_id"] for a in valid],"resolution_status":"resolved" if valid else "blocked",
            "block_reason":None if valid else "no_valid_authentic_source_asset"}
        stats["diagnostics"].append(diagnostic)
        if not valid: block("no_valid_authentic_source_asset",max(1,len(variants))); continue
        requested=list(idea.get("selected_fact_refs",idea.get("verified_fact_refs",[])) or []); unsupported=[x for x in requested if fact_ids and x not in fact_ids]
        if unsupported: block("unsupported_fact_reference",len(variants)); continue
        for variant in variants:
            authorized,reason=_authorization(variant,idea,campaign);stats["authorization_diagnostics"].append({"candidate_id":plan.get("processing_plan_id"),"content_idea_id":plan.get("content_idea_id"),"source_asset_ids":[a[0]["asset_id"] for a in valid],"platform":variant.get("platform"),"format":variant.get("output_format"),"width":variant.get("width"),"height":variant.get("height"),"execution_route":"deterministic_processor","authorized":authorized,"reason":reason})
            if not authorized: stats["unauthorized"]+=1; continue
            pid=f"{plan.get('processing_plan_id')}-PR{len([x for x in used if x.startswith(str(plan.get('processing_plan_id'))+'-PR')])+1}"
            if pid in used: raise ValueError(f"Duplicate deterministic prompt ID: {pid}")
            used.add(pid); prompts.append(_prompt(project,pid,plan,variant,valid,idea,expected,requested,warnings,bool(mismatched and not valid)))
    return prompts,stats

def _asset_error(project,aid,asset,op,allowed,source_records=None):
    if not asset:return f"Invalid asset {aid}: missing from Asset Intelligence"
    if asset.get("project_id",asset.get("project"))!=project:return f"Invalid asset {aid}: belongs to another project"
    if allowed and aid not in allowed:return f"Invalid asset {aid}: absent from visual inventory"
    source_record=source_records.get(aid) if source_records is not None else None
    if source_records is not None and not source_record:return f"Invalid asset {aid}: absent from authoritative source manifest"
    if str(asset.get("marketing_suitability","")).casefold() in _UNSUITABLE or str(asset.get("analysis_status","")).casefold() in _UNSUITABLE:return f"Invalid asset {aid}: unsuitable"
    raw=asset.get("source_path") or (op or {}).get("source_path"); path=Path(raw) if raw else None
    if path and not path.is_absolute():path=PROJECT_ROOT/path
    if not path or not path.is_file():return f"Invalid asset {aid}: source file missing"
    expected=asset.get("source_hash") or (op or {}).get("source_hash")
    if not expected or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:return f"Invalid asset {aid}: source hash mismatch"
    if source_record is not None and source_record.get("sha256")!=expected:return f"Invalid asset {aid}: source manifest hash mismatch"
    if not op or op.get("source_hash")!=expected:return f"Invalid asset {aid}: processing provenance hash mismatch"
    return None

def _prompt(project,pid,plan,variant,valid,idea,expected,facts,warnings,semantic_mismatch):
    asset_ids=[a[0]["asset_id"] for a in valid]; types=[_asset_type(a[0]) for a in valid]; primary=expected or types[0]
    paths=[a[0].get("source_path") or a[1].get("source_path") for a in valid]; hashes=[a[0].get("source_hash") for a in valid]
    operations=[]
    for _,op in valid:
        operations += [e.get("operation") for e in op.get("technical_enhancements",[]) if e.get("enabled")]
        operations += ["crop",op.get("resize",{}).get("mode","resize"),"resize"]
    operations=list(dict.fromkeys(x for x in operations if x)); nondeterministic=[x for x in operations if x not in _DETERMINISTIC]
    route="ai_image_editor" if nondeterministic else "deterministic_processor"; ai_required=route=="ai_image_editor"
    preservation=_PRESERVE.get(primary,["source geometry","visible content","project identity"]); forbidden=_FORBIDDEN.get(primary,["invented content","new viewpoint","synthetic project replacement"])
    objective=str(idea.get("content_objective") or idea.get("title") or "Prepare the approved authentic source.")
    factual_needed=bool(facts) or _factual_objective(objective); factual=15 if facts else 0 if factual_needed else None
    semantic_confidence=min(float(a[0].get("confidence",1.0) or 0) for a in valid)
    semantic=0 if semantic_mismatch else round(20*semantic_confidence); platform=10; clarity=5
    if facts:
        factual=round(15*float(idea.get("factual_confidence",1.0) or 0))
    breakdown={"source_integrity":20,"semantic_asset_content_match":semantic,"factual_evidence":factual if factual is not None else "not_applicable",
        "platform_authorization":platform,"processing_plan_compliance":10,"asset_specific_preservation":10,"provenance_completeness":10,"prompt_clarity":clarity}
    numeric=20+semantic+(factual or 0)+platform+10+10+10+clarity; denominator=85 if factual is None else 100
    score=round(numeric/denominator*100) if factual is None else numeric
    if semantic_mismatch:score=min(score,69)
    status="production_ready" if score>=90 and not warnings else "production_ready_with_warnings" if score>=80 else "review_required" if score>=70 else "blocked"
    if not ai_required:
        production=f"Use authentic source asset(s) {', '.join(asset_ids)}. Apply only {', '.join(operations)} for {variant.get('width')} x {variant.get('height')} {variant.get('output_format','JPEG')} output. Preserve {', '.join(preservation)}. Do not add, remove, redesign, reinterpret, or generate project elements."
    else:
        production=f"Use the supplied authentic source asset(s) {', '.join(asset_ids)} as the sole visual truth. Objective: {objective} Apply only the validated operations: {', '.join(operations)}. Preserve {', '.join(preservation)}. Prohibit {', '.join(forbidden)}. Keep the original viewpoint and output {variant.get('width')} x {variant.get('height')} pixels."
    ptype=_TYPE_MAP.get(primary,"approved_multi_asset_composition" if len(valid)>1 else "source_image_enhancement")
    all_warnings=warnings+(["Factual objective has no verified fact references"] if factual_needed and not facts else [])
    return {"prompt_id":pid,"project_id":project,"campaign_id":idea.get("campaign_id",""),"content_idea_id":plan.get("content_idea_id",""),"creative_direction_id":plan.get("creative_direction_id",""),"scene_plan_id":plan.get("scene_plan_id",""),"scene_id":plan.get("scene_id",""),"shot_plan_id":plan.get("shot_plan_id",""),"framing_plan_id":plan.get("framing_plan_id",""),"processing_plan_id":plan.get("processing_plan_id",""),"prompt_type":ptype,"execution_route":route,"ai_prompt_required":ai_required,"source_asset_ids":asset_ids,"source_asset_paths":paths,"source_hashes":hashes,"verified_fact_refs":facts,"visual_evidence_refs":asset_ids,"target_platform":variant.get("platform",""),"publication_type":(idea.get("planned_publication") or {}).get("publication_type") or idea.get("selected_format"),"target_format":variant.get("output_format",""),"target_aspect_ratio":variant.get("aspect_ratio",""),"target_width":variant.get("width",0),"target_height":variant.get("height",0),"production_prompt":production,"negative_prompt":", ".join("no "+x for x in forbidden),"preservation_rules":preservation,"allowed_operations":operations,"forbidden_operations":forbidden,"confidence":{"quality_score":score,"status":status,"breakdown":breakdown,"factual_alignment_basis":"verified_refs" if facts else "missing_required_facts" if factual_needed else "not_applicable_redistributed"},"provenance":{"source_only":True,"processing_plan_id":plan.get("processing_plan_id"),"source_hashes":hashes,"module_version":MODULE_VERSION,"prompt_template_version":PROMPT_TEMPLATE_VERSION,"warning_schema_version":WARNING_SCHEMA_VERSION,"model_policy":MODEL_POLICY},"warnings":all_warnings,"warning_details":[warning_for_message(x) for x in all_warnings]}

def _expected_type(idea,opportunity):
    raw=str(opportunity.get("opportunity_type","")).casefold().replace(" ","_")
    if raw=="carousel":raw=str(opportunity.get("subcategory","")).casefold().replace(" ","_")
    if raw:return raw
    text=" ".join(str(idea.get(x,"")) for x in ("title","content_objective","concept_summary")).casefold()
    for kind,words in {"interior":["interior","living room","kitchen"],"exterior":["exterior","villa architecture"],"floorplan":["floorplan","floor plan"],"masterplan":["masterplan"],"site_plan":["site plan","site layout"],"lifestyle":["lifestyle"],"logo":["logo","project introduction"],"location_map":["location","map"]}.items():
        if any(w in text for w in words):return kind
    return ""

def _asset_type(asset):
    kind=str(asset.get("asset_type","")).casefold().replace(" ","_")
    if asset.get("contains_floorplan"):return "floorplan"
    if asset.get("contains_masterplan"):return "masterplan"
    return kind

def _compatible(expected,asset):
    actual=_asset_type(asset)
    if not expected:return True
    aliases={"map":"location_map","siteplan":"site_plan","floor_plan":"floorplan","unit_plan":"floorplan","architecture":"exterior"}
    actual=aliases.get(actual,actual);expected=aliases.get(expected,expected)
    allowed=VISUAL_TYPES.get(expected)
    return actual in {aliases.get(value,value) for value in allowed} if allowed else actual==expected

def _authorization(variant,idea,campaign):
    platform=str(variant.get("platform","")).casefold(); formats=[str(x).casefold() for x in idea.get("feasible_formats",[])]
    formats += [str(x).casefold() for x in campaign.get("supported_formats",campaign.get("formats",[]))]
    platforms=[str(x).casefold() for x in idea.get("feasible_platforms",[])]+[str(x).casefold() for x in campaign.get("supported_platforms",campaign.get("platforms",[]))]
    aliases={"instagram feed":["instagram single image","instagram post","single_feed_post"],"instagram carousel":["instagram carousel","carousel"],"instagram story":["instagram story graphic","instagram story","story"],"facebook":["facebook post","facebook carousel","single_feed_post","carousel"],"website banner":["website banner"],"linkedin":["linkedin graphic"]}
    format_ok=any(a in formats for a in aliases.get(platform,[platform]));family=platform.split()[0]
    destinations={str(x).casefold() for x in idea.get("planned_destinations",[]) or []};platform_ok=family in destinations if destinations else any(family in x or x in {"social media","web","website"} and family in {"instagram","facebook","website"} for x in platforms)
    if not platform_ok:return False,"platform_not_in_authoritative_planned_destinations"
    selected=(idea.get("planned_publication") or {}).get("publication_type") or idea.get("selected_format")
    if selected:
        from src.publication import normalize_publication_type
        intended=normalize_publication_type(selected)
        variant_kind="story" if "story" in platform else "reel" if "reel" in platform else "carousel" if "carousel" in platform else "single_post"
        if intended!=variant_kind:return False,"variant_not_selected_for_production"
    if not format_ok:return False,"variant_not_supported_by_canonical_feasible_format"
    if not isinstance(variant.get("width"),int) or not isinstance(variant.get("height"),int) or variant["width"]<=0 or variant["height"]<=0:return False,"invalid_output_dimensions"
    if str(variant.get("output_format","")).upper() not in {"JPEG","JPG","PNG","WEBP"}:return False,"unsupported_output_format"
    return True,"authorized"

def _authorized(variant,idea,campaign):return _authorization(variant,idea,campaign)[0]

def _factual_objective(text):
    return bool(re.search(r"\b(verified|fact|explain|education|location|distance|amenit|masterplan|site layout|floorplan|price|size|completion|roi)\b",text.casefold()))

def _index(value,key):
    out={}
    def walk(v):
        if isinstance(v,dict):
            if v.get(key):out[str(v[key])]=v
            for x in v.values():walk(x)
        elif isinstance(v,list):
            for x in v:walk(x)
    walk(value);return out

def _fact_ids(value):
    found=set()
    def walk(v,path=""):
        if isinstance(v,dict):
            for key,item in v.items():
                new=f"{path}.{key}" if path else key
                if key in {"fact_id","verified_fact_id","reference_id","claim_id"} and isinstance(item,str):found.add(item)
                if not isinstance(item,(dict,list)) and item is not None and item != "":found.add(new)
                walk(item,new)
        elif isinstance(v,list):
            for i,item in enumerate(v):
                new=f"{path}[{i}]"; found.add(new); walk(item,new)
    walk(value);return found

def _display(path):
    try:return path.relative_to(PROJECT_ROOT)
    except ValueError:return path

def _console_safe(value):
    """Keep Windows legacy consoles from failing on valid Unicode project names."""
    return str(value).encode("ascii","backslashreplace").decode("ascii")
