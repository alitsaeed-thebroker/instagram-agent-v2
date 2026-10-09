"""Source-based, isolated unit-plan certification. Never creates live jobs."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from PIL import Image, ImageOps
from src.brand_kit import approved_config_hash
from src.branding.composer import BrandComposer
from src.creative.visual_direction import VisualArtDirector, contract_id, contract_integrity_hash, validate_visual_direction_contract
from src.creative_intelligence import RealEstateCreativeIntelligence
from src.plan_integrity import UNIT_TYPES, make_plan_record, validate_package_layouts, write_plan_inventory
from src.production.workflow import ProductionWorkflow, ValidationError
from src.publishing.foundation import _json_hash, _preflight_checks
from src.unit_plan_catalogue import extract_catalogue_leaves
from src.visual_assets.extraction import extract_visual_assets, verify_source_integrity
from src.ai.agents.asset_intelligence_agent import _with_provenance, _semantic_inventory
from src.knowledge.schema import ProjectKnowledge

PROJECT = "Beverly Hills"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def package_for(record, brand, logo, config_path):
    identity = record["unit_identity"]
    with Image.open(record["source_path"]) as image:
        width, height = image.size
    with Image.open(logo) as image:
        logo_ratio = image.width/image.height
    return {"project_id": PROJECT, "plan_intelligence": record,
        "content_brief": {"content_id": "unit-plan-cert-"+record["asset_id"], "project_id": PROJECT,
            "content_objective": "explain verified villa layout", "campaign_role": "CONSIDER",
            "post_type": "static", "carousel_position": 1,
            "marketing_angle": "source-backed floor plan", "primary_message": identity.get("unit_type") or "Villa layout",
            "secondary_message": identity.get("floor") or "", "allowed_claims": [],
            "required_identification": ["project"], "optional_identification": [],
            "prohibited_claims": ["guaranteed ROI"], "cta_requirement": "none", "language": "en",
            "platform": "Instagram Feed", "publication_type": "carousel",
            "target_dimensions": {"width":1080,"height":1350}},
        "source_asset": {"asset_id": record["asset_id"], "project_id": PROJECT, "original_filename": Path(record["source_path"]).name,
            "source_document": record["source_document"], "source_page": record["source_page"], "asset_type":"villa_layout",
            "width":width,"height":height,"orientation":"square","quality_score":100,"content_group":"unit-plan",
            "source_provenance":"deterministic linked catalogue floors", "path":record["source_path"]},
        "visual_intelligence": {"protected_regions":[[0,0,width,height]],"text_safe_regions":[]},
        "project_identity": {"project_name":PROJECT,"canonical_project_name":PROJECT,"project_type":"standalone villas",
            "location":None,"developer_name":None,"developer_identity_status":"unverified",
            "project_logo_if_verified":None,"project_identity_source":record["source_document_path"]},
        "brand_identity": {"brand_name":brand["company"]["display_name"],
            "approved_logo_assets":[{"path":str(logo),"variant":"original"}],"approved_logo_variants":["original"],
            "brand_fonts":[brand["visual_identity"]["typography"]["primary_font"]],
            "brand_colors":[brand["visual_identity"]["colors"]["primary"]["value"]],
            "minimum_logo_size":120,"maximum_logo_size":180,"logo_clear_space":12,"logo_aspect_ratio":logo_ratio,
            "prohibited_logo_modifications":["stretch","recolor","crop","rotate"],
            "brand_tone":"premium","brand_visual_character":"restrained"}}


def processor_check(record):
    prompt={"project_id":PROJECT,"prompt_type":"floorplan_presentation","target_width":1080,"target_height":1350,
        "source_asset_ids":[record["asset_id"]],"source_asset_paths":[record["source_path"]],
        "source_hashes":[record["source_hash"]]}
    plan={"operations":[{"source_asset_id":record["asset_id"],"crop":{"x":0,"y":0,"width":1,"height":1}}]}
    try:
        ProductionWorkflow(PROJECT)._validate(prompt,plan,{record["asset_id"]},{record["asset_id"]:record})
        return {"status":"PASSED","blockers":[]}
    except ValidationError as error:
        return {"status":"BLOCKED","blockers":[str(error)]}


def render_unit(records, brand, logo, config_path, root):
    contracts=[];slides=[];qa=[];provenance=[]
    for index,record in enumerate(records,1):
        direct=VisualArtDirector().direct(package_for(record,brand,logo,config_path))
        if not direct.contract:
            return {"status":"BLOCKED","blockers":list(direct.blockers)}, None
        contract=direct.contract
        contract["provenance"].update(source_image_hash=sha(record["source_path"]),logo_hash=sha(logo),
                                      brand_config_hash=approved_config_hash(brand))
        contract["contract_id"]=contract_id(contract)
        contract["contract_hash"]=contract_integrity_hash(contract)
        errors=validate_visual_direction_contract(contract)
        if errors:
            return {"status":"BLOCKED","blockers":errors},None
        output=root/"renders"/f"{record['unit_identity']['unit_type'].replace(' ','-')}-{index}.png"
        BrandComposer(PROJECT,root).execute_visual_direction(contract,destination=output)
        # Pixel-for-pixel equality with the compositor's prescribed proportional
        # source containment demonstrates no regenerated or obstructed geometry.
        with Image.open(record["source_path"]) as source:
            contained=ImageOps.contain(source.convert("RGBA"),tuple(contract["source_image"]["placement"][2:]))
        px,py,pw,ph=contract["source_image"]["placement"]
        reference=Image.new("RGBA",(contract["canvas"]["width"],contract["canvas"]["height"]),"white")
        reference.alpha_composite(contained,(px+(pw-contained.width)//2,py+(ph-contained.height)//2))
        with Image.open(output) as actual:
            geometry_equal=reference.crop((px,py,px+pw,py+ph)).tobytes()==actual.convert("RGBA").crop((px,py,px+pw,py+ph)).tobytes()
        if not geometry_equal:
            raise ValueError("Rendered technical geometry differs from prescribed source containment")
        scope=record["unit_plan_relationship"]["catalogue_relationship"]
        rect=scope["source_region"];scale=min(pw/(rect[2]-rect[0]),ph/(rect[3]-rect[1]))
        sizes=[size for row in scope["protected_source_rows"] for size in row["font_sizes"]]
        qa.append({"asset_id":record["asset_id"],"source_page":record["source_page"],
            "floor":record["unit_identity"]["floor"],"source_geometry_preserved":geometry_equal,
            "complete_plan_and_legend_visible":True,"uniform_source_scale":scale,
            "minimum_main_label_font_px":min(size for size in sizes if size>=7)*scale,
            "minimum_superscript_font_px":min(size for size in sizes if size<7)*scale if any(size<7 for size in sizes) else None,
            "output":str(output),"output_sha256":sha(output),"contract_validation_errors":errors})
        branded_id=contract["contract_id"]
        slides.append({"slide_number":index,"source_asset_ids":[record["asset_id"]],"image_path":str(output),
            "image_hash":sha(output),"branded_item_id":branded_id,"final_output_hash":sha(output),
            "alt_text":f"{record['unit_identity']['unit_type']} villa layout, {record['unit_identity']['floor']}, original numbered room legend."})
        provenance.append({"branded_item_id":branded_id,"integrity_status":"complete","final_output_hash":sha(output),
                           "source_asset_ids":[record["asset_id"]],"source_document_hash":record["source_document_hash"],
                           "relationship_id":record["unit_plan_relationship"]["relationship_id"]})
        contracts.append(contract)
    identity=records[0]["unit_identity"]
    package={"package_id":"cert-"+identity["unit_type"].replace(" ","-"),"project_id":PROJECT,
        "package_type":"carousel","status":"ready","platform":"instagram","release_id":"isolated-unit-plan-certification",
        "brand_config_hash":approved_config_hash(brand),"slides":slides,"hashtags":[],
        "master_caption":{"full_caption":f"Beverly Hills — {identity['unit_type']} villa layout.\n{identity['bedrooms']}-bedroom villa with {identity['area_sqm']:g} sqm built-up area. Ground floor and first floor shown."}}
    return {"status":"PASSED","render_qa":qa,"provenance":provenance,"contracts":contracts},package


def preflight(package, inventory, brand, provenance):
    ctx={"plan_intelligence":inventory,"packages":{"project_id":PROJECT},
         "release":{"release_id":"isolated-unit-plan-certification"},"brand":brand,
         "provenance":{"items":provenance}}
    item={"package_hash":_json_hash(package),"idempotency_key":"cert-"+package["package_id"],"status":"preflight_ready"}
    checks,blockers,warnings=_preflight_checks(item,package,ctx,set())
    return {"status":"BLOCKED" if blockers else "PASSED","checks":checks,"blockers":blockers,"warnings":warnings}


def install_working_inventories(repository, root, manifest):
    """Persist proven sources and structural semantics without another model call."""
    live_sources=repository/"output/source-images"/PROJECT
    live_sources.mkdir(parents=True,exist_ok=True)
    targets={
        "source-manifest":live_sources/"manifest.json",
        "asset-intelligence":repository/"output/asset-intelligence"/f"{PROJECT}-asset-intelligence.json",
        "visual-inventory":repository/"output/visual-inventory"/f"{PROJECT}-visual-inventory.json",
        "plan-inventory":repository/"output/plan-intelligence"/f"{PROJECT}-plan-intelligence.json",
    }
    for label,path in targets.items():
        snapshot=root/f"previous-{label}.json"
        if path.is_file() and not snapshot.is_file():
            write(snapshot,read(path))
    stage_sources=root/"source-images"/PROJECT
    for asset in manifest["assets"]:
        relative=Path(asset["filename"])
        destination=(live_sources/relative).resolve()
        if not destination.is_relative_to(live_sources.resolve()):
            raise ValueError("Source manifest path escapes the project source directory")
        original=stage_sources/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        if not destination.is_file() or sha(destination)!=asset["sha256"]:
            shutil.copy2(original,destination)
        if asset.get("source_kind")=="pdf_villa_plan_leaf":
            asset["source_path"]=str(destination)
    write(targets["source-manifest"],manifest)
    if verify_source_integrity(targets["source-manifest"]):
        raise ValueError("Installed working source manifest failed integrity")
    leaves=[asset for asset in manifest["assets"] if asset.get("source_kind")=="pdf_villa_plan_leaf"]
    previous=read(targets["asset-intelligence"]) if targets["asset-intelligence"].is_file() else {"assets":[]}
    analyses=[]
    for analysis in previous["assets"]:
        if analysis.get("source_kind")=="pdf_villa_plan_leaf":
            continue
        rebuilt=make_plan_record(analysis)
        if rebuilt:
            analysis.update({key:value for key,value in rebuilt.items() if key!="confidence"})
            if analysis.get("asset_type") in UNIT_TYPES and not analysis.get("marketing_eligible"):
                analysis.update(analysis_status="review_required",marketing_suitability="review_required")
        analyses.append(analysis)
    for leaf in leaves:
        semantic={"asset_type":"villa_layout","confidence":1.0,"unit_identity":{},"evidence":{},
            "analysis_status":"analyzed","marketing_suitability":"information_graphic_ready",
            "dominant_subject":"complete original villa floor plan and numbered room legend",
            "contains_floorplan":True,"contains_text":True,"contains_diagram":True,
            "restrictions":["Complete canonical floor set required; no plan geometry or label edits."],
            "recommended_formats":["carousel"],"recommended_platforms":["instagram"],
            "visible_project_features":[]}
        analyzed=_with_provenance(semantic,leaf,Path(leaf["source_path"]),PROJECT,
                                  "deterministic-catalogue:"+leaf["asset_id"],"analyzed")
        analyzed["model_policy"]="no LLM; source catalogue adapter and exact render proof"
        analyses.append(analyzed)
    previous["assets"]=analyses
    previous["unit_plan_migration"]={"authority":"deterministic_catalogue_villa_relationship",
                                    "certification_report":str(root/"certification-report.json")}
    write(targets["asset-intelligence"],previous)
    knowledge=ProjectKnowledge.from_json((repository/"output/knowledge"/f"{PROJECT}.json").read_text(encoding="utf-8"))
    write(targets["visual-inventory"],_semantic_inventory(PROJECT,analyses,knowledge))
    write_plan_inventory(PROJECT,repository,analyses)
    return {"source_assets":len(manifest["assets"]),"deterministic_plan_leaves":len(leaves),
            "verified_plan_leaves":sum(analysis.get("source_kind")=="pdf_villa_plan_leaf" and analysis.get("marketing_eligible",False)
                                      for analysis in analyses),
            "updated_files":{label:str(path) for label,path in targets.items()}}


def run(repository, brand_root, *, reuse_extraction=False):
    root=repository/"output/verification/unit-plans/Beverly-Hills"
    root.mkdir(parents=True,exist_ok=True)
    pdf=repository/"input"/PROJECT/"Beverly Hills Catalogue.pdf"
    manifest_path=root/"source-images"/PROJECT/"manifest.json"
    if not reuse_extraction or not manifest_path.is_file():
        manifest_path=extract_visual_assets(PROJECT,[pdf],output_root=root/"source-images")
    manifest=read(manifest_path)
    if any(asset.get("source_document_sha256")!=sha(pdf) for asset in manifest["assets"]):
        raise ValueError("Reused extraction does not belong to current source document")
    if verify_source_integrity(manifest_path):
        raise ValueError("Re-extracted source integrity failed")
    leaf_assets,candidates=extract_catalogue_leaves(PROJECT,pdf,manifest_path.parent/"plans/unit-layouts")
    non_leaves=[asset for asset in manifest["assets"] if asset.get("source_kind")!="pdf_villa_plan_leaf"]
    for leaf in leaf_assets:
        leaf["filename"]=Path(leaf["source_path"]).relative_to(manifest_path.parent).as_posix()
    manifest["assets"]=non_leaves+leaf_assets
    manifest["extraction_summary"]["extracted_images"]=len(manifest["assets"])
    manifest["extraction_summary"]["complete_plan_leaves"]=len(leaf_assets)
    write(manifest_path,manifest)
    if verify_source_integrity(manifest_path):
        raise ValueError("Plan leaf extraction integrity failed")
    records=[make_plan_record(asset) for asset in leaf_assets]
    inventory={"project_id":PROJECT,"assets":records}
    write(root/"canonical-plan-inventory.json",inventory)
    write(root/"catalogue-candidates.json",candidates)
    source_config=brand_root/"brand-config.json";source_logo=brand_root/"logos/domus logo.png"
    brand=read(source_config)
    approval=brand.get("approval") or {}
    if approval.get("status")!="approved" or not approval.get("locked") or approved_config_hash(brand)!=approval.get("approved_config_hash"):
        raise ValueError("Available brand configuration is not approved and locked")
    if sha(source_logo)!=approval.get("approved_logo_hash"):
        raise ValueError("Available logo does not match its recorded approval")
    local_brand=root/"input/brand";(local_brand/"logos").mkdir(parents=True,exist_ok=True)
    shutil.copy2(source_config,local_brand/"brand-config.json")
    shutil.copy2(source_logo,local_brand/"logos/domus logo.png")
    logo=local_brand/"logos/domus logo.png"
    config_path=local_brand/"brand-config.json"
    verified=[];blocked=[];packages=[]
    for candidate in candidates:
        candidate_records=[record for record in records
                           if record["source_page"] in [member["source_page"] for member in candidate["members"]]]
        is_verified=bool(candidate_records) and all(record["marketing_eligible"] for record in candidate_records)
        if is_verified:
            result,package=render_unit(candidate_records,brand,logo,config_path,root)
            if package:
                package_errors=validate_package_layouts(package,inventory,expected_project=PROJECT)
                publishing=preflight(package,inventory,brand,result["provenance"])
                partial=deepcopy(package);partial["slides"]=partial["slides"][:1]
                partial_errors=validate_package_layouts(partial,inventory,expected_project=PROJECT)
                partial_publish=preflight(partial,inventory,brand,result["provenance"])
                result.update(package_plan_errors=package_errors,publishing_preflight=publishing,
                    processor_checks=[processor_check(record) for record in candidate_records],
                    partial_set_errors=partial_errors,partial_set_publishing_preflight=partial_publish)
                if package_errors or publishing["status"]!="PASSED" or not partial_errors or partial_publish["status"]!="BLOCKED":
                    result["status"]="FAILED"
                write(root/"packages"/f"{candidate['unit_type'].replace(' ','-')}.json",package)
                packages.append(package)
            write(root/"contracts"/f"{candidate['unit_type'].replace(' ','-')}.json",result.pop("contracts",[]))
            verified.append({"unit_type":candidate["unit_type"],"bedrooms":candidate["bedrooms"],
                "built_up_area_sqm":candidate["area_sqm"],"source_pages":[member["source_page"] for member in candidate["members"]],
                **result})
        else:
            first=candidate_records[0]
            direction=VisualArtDirector().direct(package_for(first,brand,logo,config_path))
            unsafe_package={"package_id":"cert-blocked-"+candidate["unit_type"],"project_id":PROJECT,
                "status":"ready","release_id":"isolated-unit-plan-certification","slides":[{"source_asset_ids":[record["asset_id"]]} for record in candidate_records],
                "master_caption":{"full_caption":f"{candidate['unit_type']} villa layout"}}
            plan_errors=validate_package_layouts(unsafe_package,inventory,expected_project=PROJECT)
            publishing=preflight(unsafe_package,inventory,brand,[])
            knowledge={"project_id":PROJECT,"project":{"name":PROJECT},"plan_intelligence":{"layout":{"unit_type":candidate["unit_type"]}}}
            opportunity=next(op for op in RealEstateCreativeIntelligence().build(
                knowledge,plans={"project_id":PROJECT,"assets":candidate_records},
                inventory={"project_id":PROJECT,"assets":candidate_records},project_hint=PROJECT).opportunities if op.category=="unit")
            blocked.append({"unit_type":candidate["unit_type"],"source_reasons":candidate["reasons"],
                "planning_status":opportunity.status,"director_status":direction.status,
                "director_blockers":list(direction.blockers),"processor":processor_check(first),
                "package_plan_errors":plan_errors,"publishing_preflight":publishing})
    all_pass=bool(verified) and all(item["status"]=="PASSED" for item in verified) and all(
        item["planning_status"] in {"BLOCKED","REVIEW_REQUIRED"} and item["director_status"]=="REQUIRES_REDIRECTION"
        and item["processor"]["status"]=="BLOCKED" and item["package_plan_errors"]
        and item["publishing_preflight"]["checks"]["plan_integrity"]=="failed" for item in blocked)
    report={"project_id":PROJECT,"status":"PASSED" if all_pass else "FAILED","created_at":datetime.now(timezone.utc).isoformat(),
        "source_document":{"path":str(pdf),"sha256":sha(pdf)},"extraction":manifest["extraction_summary"],
        "source_asset_hash_failures":verify_source_integrity(manifest_path),"verified_units":verified,"blocked_units":blocked,
        "brand_snapshot":{"source":str(source_config),"approved_config_hash":approved_config_hash(brand),"logo_sha256":sha(logo)},
        "external_requests":0,"live_publication_jobs_created":0,
        "scope":"actual source relationships, actual 1080x1350 VAD/compositor outputs, processor gate, package plan gate and publishing preflight; isolated certification"}
    write(root/"certification-report.json",report)
    if all_pass:
        live_inventory=repository/"output/plan-intelligence"/f"{PROJECT}-plan-intelligence.json"
        previous=read(live_inventory) if live_inventory.is_file() else {"assets":[]}
        if not (root/"previous-plan-inventory.json").is_file():
            write(root/"previous-plan-inventory.json",previous)
        report["working_inventory_migration"]=install_working_inventories(repository,root,manifest)
        write(root/"certification-report.json",report)
    return root/"certification-report.json"


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--brand-root",type=Path,required=True)
    parser.add_argument("--reuse-extraction",action="store_true")
    args=parser.parse_args()
    result=run(REPOSITORY,args.brand_root.resolve(),reuse_extraction=args.reuse_extraction)
    report=read(result)
    print(json.dumps({"status":report["status"],"verified_units":[{"unit_type":item["unit_type"],"status":item["status"]} for item in report["verified_units"]],
                      "blocked_units":[item["unit_type"] for item in report["blocked_units"]],"report":str(result)},indent=2))
    raise SystemExit(0 if report["status"]=="PASSED" else 1)
