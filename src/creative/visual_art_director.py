"""Pipeline integration for the canonical Department 4 Visual Art Director."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image

from src.creative.visual_direction import VISUAL_DIRECTION_VERSION, VisualArtDirector, contract_id, contract_integrity_hash
from src.creative.visual_history import VisualDirectionHistory
from src.creative.editorial_profile import load_editorial_profile
from src.knowledge.consumer import require_canonical_graph
from src.execution.lineage import canonical_graph_fingerprint,require_lineage,require_content_plan_lineage
from src.brand_kit import approved_config_hash
from src.performance.integration import visual_art_director_context
from src.publication import normalize_publication_type, public_copy, INTERNAL_COPY_PATTERNS
from src.plan_integrity import UNIT_TYPES, normalize_plan_type, make_plan_record


class VisualArtDirectorWorkflow:
    """Build one canonical contract collection from existing project artifacts."""

    def __init__(self, project: str, root: Path, *, minimum_creative_score: int = 80) -> None:
        self.project, self.root = project, root
        self.director = VisualArtDirector(minimum_creative_score=minimum_creative_score)
        self.output_path = root/"output"/"visual-directions"/f"{project}-visual-direction-contracts.json"

    def run(self) -> Path:
        paths = self._paths(); payloads = {name:_read(path) for name,path in paths.items() if name != "brand_config"}
        brand_config = _read(paths["brand_config"]); production = payloads["prompts"]
        _assert_project(self.project, production, payloads["visual_inventory"], payloads["content"])
        content = _index(payloads["content"], "content_idea_id")
        assets = _index(payloads["visual_inventory"], "asset_id")
        plans=_index(payloads.get("plan_intelligence",{}),"asset_id")
        history = VisualDirectionHistory(self.project,self.root).recent_context()
        learning_path=self.root/"data"/"performance-learning"/"creative-learning-profile.json"
        performance_context=visual_art_director_context(_read(learning_path)) if learning_path.is_file() else visual_art_director_context({})
        logo = _approved_logo(payloads["logo_inventory"], brand_config, self.root)
        identity = _project_identity(payloads["knowledge"])
        profile=load_editorial_profile(self.root,self.project)
        if profile:
            require_canonical_graph(payloads["knowledge"],expected_project=self.project)
            require_content_plan_lineage(payloads["content"],payloads["knowledge"],self.root,self.project)
        exclusions={x["asset_id"]:x for x in (profile or {}).get("excluded_source_assets",[])}
        contracts: list[dict[str, Any]]=[]; redirected=[];style_exclusions=[]
        for item in production.get("prompts", production.get("items", [])):
            item_id=str(item.get("prompt_id", "")); idea=content.get(str(item.get("content_idea_id", "")), {})
            asset_ids=[str(x) for x in item.get("source_asset_ids", [])]; asset=assets.get(asset_ids[0], {}) if len(asset_ids)==1 else {}
            if profile:
                if idea.get("content_idea_id") is None or not set(asset_ids)<=set(idea.get("selected_source_asset_ids",[])):raise ValueError("Editorial source is outside its canonical content selection")
                if asset.get("project_id")!=self.project:raise ValueError("Editorial source belongs to another project")
                if len(asset_ids)==1 and asset_ids[0] in exclusions:
                    excluded=exclusions[asset_ids[0]]
                    if excluded.get("source_hash")!=asset.get("source_hash"):raise ValueError("Creative source exclusion has stale provenance")
                    style_exclusions.append({"production_item_id":item_id,"asset_id":asset_ids[0],"reason":excluded["reason"],"status":"excluded_by_project_design_profile"});continue
            raw_plan_type,_=normalize_plan_type(asset.get("asset_type") or asset.get("visual_category"))
            plan_record=plans.get(asset_ids[0]) if asset_ids else None
            if plan_record:
                plan_record = make_plan_record(plan_record)
            if raw_plan_type in UNIT_TYPES and not plan_record:
                redirected.append({"production_item_id":item_id,"status":"REQUIRES_REDIRECTION","blockers":["unit plan is missing its exact plan-intelligence record"]})
                continue
            if plan_record and plan_record.get("asset_type") in UNIT_TYPES and not plan_record.get("marketing_eligible"):
                redirected.append({"production_item_id":item_id,"status":"REQUIRES_REDIRECTION","blockers":["unit plan is REVIEW_REQUIRED and cannot enter production"]})
                continue
            if plan_record:asset={**asset,"plan_intelligence":plan_record,"asset_type":plan_record["asset_type"]}
            package = _package(self.project, item, idea, asset, identity, brand_config, logo, self.root)
            package["performance_context"]=performance_context
            if profile:
                package["editorial_profile"]=profile
                package["content_brief"].update(primary_message="",secondary_message="",cta_requirement="none")
                package["content_brief"]["public_copy"]={"project_name":identity["canonical_project_name"],"headline":None,"subheadline":None,"cta":None,"website":None}
            if item.get("confidence",{}).get("status") not in {None,"production_ready","production_ready_with_warnings"}:result_reason=["source planning artifact is not production eligible"]
            else:
                result=self.director.direct(package,recent_contracts=history+contracts)
                if result.contract is not None:
                    result.contract["production_item_id"]=item_id
                    result.contract["campaign_id"]=item.get("campaign_id")
                    result.contract["content_idea_id"]=item.get("content_idea_id")
                    result.contract["contract_id"]=contract_id(result.contract)
                    result.contract["provenance"].update(
                        content_brief_hash=_hash_json(package["content_brief"]), source_image_hash=_hash_file(Path(package["source_asset"]["path"])),
                        logo_hash=logo["sha256"], brand_config_hash=approved_config_hash(brand_config),brand_identity_source=str(paths["brand_config"]), developer_identity_source=identity.get("developer_identity_source"),
                        generated_at=_now(),editorial_profile_hash=_hash_json(profile) if profile else None)
                    result.contract["contract_hash"]=contract_integrity_hash(result.contract)
                    contracts.append(result.contract);continue
                result_reason=list(result.blockers)
            redirected.append({"production_item_id":item_id,"status":"REQUIRES_REDIRECTION","blockers":result_reason})
        output={"project_id":self.project,"contract_version":VISUAL_DIRECTION_VERSION,"authority":"visual-art-director",
                "contracts":contracts,"redirected":redirected,"style_exclusions":style_exclusions,"editorial_profile":profile,"summary":{"approved":len(contracts),"requires_redirection":len(redirected)},"created_at":_now()}
        self.output_path.parent.mkdir(parents=True,exist_ok=True)
        self.output_path.write_text(json.dumps(output,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        return self.output_path

    def _paths(self) -> dict[str, Path]:
        output=self.root/"output"; paths={
            "prompts":output/"image-prompts"/f"{self.project}-image-prompts.json",
            "content":output/"content"/f"{self.project}-content-plan.json",
            "knowledge":output/"knowledge"/f"{self.project}.json",
            "visual_inventory":output/"visual-inventory"/f"{self.project}-visual-inventory.json",
            "logo_inventory":output/"brand-analysis"/"domus-erbil-logo-inventory.json",
            "brand_config":self.root/"input"/"brand"/"brand-config.json",
        }
        missing=[str(path) for path in paths.values() if not path.is_file()]
        if missing: raise ValueError("Visual Art Director missing inputs: "+", ".join(missing))
        history=VisualDirectionHistory(self.project,self.root).path
        if history.is_file():paths["history"]=history
        plan_intelligence=output/"plan-intelligence"/f"{self.project}-plan-intelligence.json"
        if plan_intelligence.is_file():paths["plan_intelligence"]=plan_intelligence
        return paths


def _package(project: str, item: dict[str, Any], idea: dict[str, Any], asset: dict[str, Any], identity: dict[str, Any],
             config: dict[str, Any], logo: dict[str, Any], root: Path) -> dict[str, Any]:
    source=_resolve(root,str((item.get("source_asset_paths") or [item.get("source_path") or ""])[0]))
    with Image.open(source) as image: width,height=image.size
    target_width=int(item.get("target_width") or width)
    target_height=int(item.get("target_height") or height)
    explicit={"public_copy":idea.get("public_copy") or {"project_name":identity.get("canonical_project_name"),"headline":idea.get("title"),"subheadline":None,"cta":None,"website":None}}
    if INTERNAL_COPY_PATTERNS.search(str(explicit["public_copy"].get("headline") or "")):
        explicit["public_copy"]={**explicit["public_copy"],"headline":"Discover the Design"}
    copy=public_copy(explicit);title=str(copy.get("headline") or copy.get("project_name") or identity.get("canonical_project_name") or "");secondary=str(copy.get("subheadline") or "")
    visual=config.get("visual_identity",{}); policy=visual.get("logo_policy",{}); typography=visual.get("typography",{}); colors=visual.get("colors",{})
    language=str(idea.get("language") or idea.get("text_language") or config.get("content_rules",{}).get("default_language","English"))
    asset_type=str(asset.get("asset_type") or item.get("prompt_type") or "unknown").casefold().replace(" ","_")
    publication=normalize_publication_type(item.get("publication_type") or (idea.get("planned_publication") or {}).get("publication_type") or idea.get("selected_format") or "single_post")
    return {"project_id":project,"content_brief":{
        "content_id":str(item.get("content_idea_id") or item.get("production_item_id")),"project_id":project,
        "content_objective":str(idea.get("content_objective") or idea.get("purpose") or "project identification"),
        "campaign_role":str(idea.get("carousel_role") or idea.get("campaign_role") or "standalone"),"post_type":"static",
        "carousel_position":idea.get("carousel_position",1),"marketing_angle":str(idea.get("marketing_angle") or idea.get("concept_summary") or "verified project presentation"),
        "primary_message":title,"secondary_message":secondary,"allowed_claims":list(idea.get("allowed_claims") or idea.get("verified_fact_refs") or []),
        "required_identification":["project","broker"],"optional_identification":["location","developer"],
        "prohibited_claims":list(idea.get("prohibited_claims") or config.get("brand_voice",{}).get("avoid",[])),
        "cta_requirement":copy.get("cta") or "none","language":language,"platform":str(item.get("target_platform") or "Instagram Feed"),"publication_type":publication,"public_copy":copy,
        "target_dimensions":{"width":target_width,"height":target_height},
        "creative_pattern_references":list(idea.get("creative_pattern_references") or [])[:3],"creative_anti_patterns":list(idea.get("creative_anti_patterns") or []),
        "pattern_factual_authority":"NONE","pattern_influence":"advisory"},
        "source_asset":{"asset_id":str(asset.get("asset_id") or (item.get("source_asset_ids") or [""])[0]),
            "original_filename":str(asset.get("original_filename") or source.name),"source_document":str(asset.get("source_document") or asset.get("document_path") or "production-manifest"),
            "source_page":asset.get("source_page",asset.get("page_number",0)),"asset_type":asset_type,"width":width,"height":height,
            "orientation":"landscape" if width>height else "portrait" if height>width else "square","quality_score":asset.get("quality_score",100),
            "content_group":str(asset.get("content_group") or "project"),"source_provenance":str(asset.get("source_provenance") or "verified production manifest"),"path":str(source)},
        "visual_intelligence":_visual_intelligence(asset),"plan_intelligence":asset.get("plan_intelligence"),"project_identity":identity,
        "brand_identity":{"brand_name":str(config.get("company",{}).get("display_name") or config.get("brand_id")),
            "approved_logo_assets":[{"path":str(logo["resolved_path"]),"variant":"original"}],"approved_logo_variants":["original"],
            "brand_fonts":[str(typography.get("primary_font") or "Arial")],"brand_colors":[str(colors.get("primary",{}).get("value") or colors.get("primary") or "#111111")],
            "minimum_logo_size":int(policy.get("minimum_width_px") or 120),"maximum_logo_size":max(int(policy.get("minimum_width_px") or 120),round(target_width*.18)),
            "logo_clear_space":max(8,round(target_width*float(policy.get("minimum_clear_space_ratio",.1))*.12)),"logo_aspect_ratio":float(logo.get("aspect_ratio") or 1),
            "prohibited_logo_modifications":[name for name,key in (("recolor","allow_recoloring"),("distort","allow_distortion"),("crop","allow_cropping"),("rotate","allow_rotation"),("effects","allow_effects")) if not policy.get(key,False)],
            "brand_tone":config.get("brand_voice",{}).get("tone",[]),"brand_visual_character":str(visual.get("layout_style",{}).get("style") or "premium_minimal")}}


def _visual_intelligence(asset: dict[str, Any]) -> dict[str, Any]:
    aliases={"safe_text_areas":"text_safe_regions","focal_region":"primary_focal_region"}; result={}
    for name in ("primary_focal_region","secondary_focal_regions","architecture_regions","protected_regions","text_safe_regions","negative_space_regions",
                 "high_contrast_regions","low_contrast_regions","bright_regions","dark_regions","busy_regions","existing_text_regions","horizon_position",
                 "dominant_visual_weight","perspective_direction","leading_lines","symmetry","subject_density","crop_tolerance","edge_safety"):
        value=asset.get(name)
        if value is None:
            source=next((key for key,target in aliases.items() if target==name),None);value=asset.get(source) if source else None
        if value is not None:result[name]=value
    return result


def _project_identity(knowledge: dict[str, Any]) -> dict[str, Any]:
    project=knowledge.get("project",{}) if isinstance(knowledge.get("project"),dict) else {}
    explicit=knowledge.get("project_identity",{}) if isinstance(knowledge.get("project_identity"),dict) else {}
    names={str(x).strip() for x in (project.get("name"),explicit.get("project_name")) if str(x or "").strip()}
    canonical=next(iter(names)) if len(names)==1 else ""
    developer=project.get("developer") or explicit.get("developer_name")
    verified=bool(developer and (explicit.get("developer_verified") is True or explicit.get("developer_identity_status") in {"verified","confirmed"}))
    return {"project_name":canonical,"canonical_project_name":canonical,"project_type":project.get("type") or explicit.get("project_type") or "unknown",
            "location":project.get("location") or explicit.get("location"),"developer_name":developer if verified else None,
            "developer_identity_status":"verified" if verified else "unverified","project_logo_if_verified":explicit.get("project_logo_if_verified"),
            "project_identity_source":"knowledge fusion" if canonical else "","developer_identity_source":"knowledge fusion" if verified else None}


def _approved_logo(inventory: dict[str, Any], config: dict[str, Any], root: Path) -> dict[str, Any]:
    preferred=config.get("visual_identity",{}).get("logo_policy",{}).get("preferred_logo_id") or inventory.get("preferred_logo_id")
    logo=next((x for x in inventory.get("logos",[]) if x.get("logo_id")==preferred),None)
    if not logo: raise ValueError("Visual Art Director requires the approved preferred logo")
    path=_resolve(root,str(logo.get("path","")))
    if not path.is_file(): raise ValueError("Visual Art Director approved logo is missing")
    result=dict(logo);result["resolved_path"]=path;result["sha256"]=_hash_file(path);return result


def _assert_project(project: str, *payloads: dict[str, Any]) -> None:
    for payload in payloads:
        actual=payload.get("project_id",payload.get("project"))
        if isinstance(actual,str) and actual and actual!=project: raise ValueError(f"Visual Art Director blocked cross-project input: {actual}")


def _history(payload: dict[str, Any], project: str) -> list[dict[str, Any]]:
    return list(payload.get("contracts",[])) if payload.get("project_id")==project else []


def _index(value: Any, key: str) -> dict[str, dict[str, Any]]:
    result={}
    def walk(item: Any) -> None:
        if isinstance(item,dict):
            if item.get(key):
                result[str(item[key])]=item
                return  # Nested provenance/evidence repeats asset_id; it is not an asset record.
            for nested in item.values():walk(nested)
        elif isinstance(item,list):
            for nested in item:walk(nested)
    walk(value);return result


def _resolve(root: Path, value: str) -> Path:
    path=Path(value);return path if path.is_absolute() else root/path
def _read(path: Path) -> dict[str, Any]:return json.loads(path.read_text(encoding="utf-8"))
def _hash_file(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda:source.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()
def _hash_json(value: Any) -> str:return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def _now() -> str:return datetime.now(timezone.utc).isoformat()
