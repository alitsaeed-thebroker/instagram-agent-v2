"""Prepare source-backed unit carousel drafts without creating publication jobs."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from tools.certify_beverly_unit_plans import PROJECT, read, write, sha, render_unit, preflight
from src.brand_kit import approved_config_hash
from src.content.schema import ContentIdea, ContentPillar, ContentPlan
from src.plan_integrity import validate_package_layouts
from src.unit_plan_relationship import relationship_errors


def content_idea(records):
    identity = records[0]["unit_identity"]
    scope = records[0]["unit_plan_relationship"]["catalogue_relationship"]
    ids = [r["asset_id"] for r in records]
    name = identity["unit_type"]
    caption = (f"Beverly Hills — {name} villa layout.\n"
               f"{identity['bedrooms']}-bedroom villa with {identity['area_sqm']:g} m² built-up area.\n"
               "Swipe through the ground-floor and first-floor plans.\n"
               "Source: Beverly Hills Catalogue. Figures reflect the brochure.")
    return ContentIdea(
        unique_id="unit-" + scope["unit_scope_id"], title=f"{name}: two floors, one complete layout",
        story="Present the complete ground-floor plan first, followed by the complete first-floor plan, retaining both numbered room legends.",
        purpose="Explain a source-verified villa layout", target_audience="Prospective villa buyers",
        emotion="Clarity", marketing_goal="Support informed comparison of villa layouts",
        recommended_platform="Instagram", recommended_format="Carousel", image_orientation="Portrait",
        priority="High", main_subject=f"{name} villa plans", supporting_subjects=["Ground Floor", "First Floor"],
        environment="Original technical drawings", time_of_day="Not applicable to technical plans",
        weather="Not applicable to technical plans", mood="Clear and restrained",
        color_palette="Preserve original source drawing colors", camera_style="Full source plan presentation",
        recommended_lens="Not applicable to technical plans", composition="Uniform containment; complete plan and legend; branding outside drawing",
        visual_keywords=["complete villa layout", "source-backed facts"], future_asset_type="Instagram Carousel",
        required_source_asset_ids=ids, available_source_asset_ids=ids, selected_source_asset_ids=ids,
        source_support_status="fully_supported", visual_evidence=[r["unit_plan_relationship"]["relationship_id"] for r in records],
        text_evidence=[f"PDF pages {', '.join(str(r['source_page']) for r in records)}; numbered bedroom legends and reconciled built-up area tables"],
        feasible_platforms=["Instagram"], feasible_formats=["Carousel"], selected_format="carousel",
        planned_publication={"publication_type":"carousel"}, public_copy={"caption":caption})


def run(repository=REPOSITORY):
    inventory_path=repository/"output/plan-intelligence"/f"{PROJECT}-plan-intelligence.json"
    inventory=read(inventory_path)
    certification_root=repository/"output/verification/unit-plans/Beverly-Hills"
    certified=read(certification_root/"certification-report.json")
    if certified["status"] != "PASSED":
        raise ValueError("Source certification must pass before preparing drafts")
    config=certification_root/"input/brand/brand-config.json"
    logo=certification_root/"input/brand/logos/domus logo.png"
    brand=read(config)
    if approved_config_hash(brand)!=certified["brand_snapshot"]["approved_config_hash"] or sha(logo)!=certified["brand_snapshot"]["logo_sha256"]:
        raise ValueError("Approved brand snapshot has changed")
    root=repository/"output/production/unit-plans/Beverly-Hills"
    groups={}
    for record in inventory["assets"]:
        proof=record.get("unit_plan_relationship") or {}
        if proof.get("status")!="VERIFIED" or not record.get("marketing_eligible"):
            continue
        scope=proof.get("catalogue_relationship")
        if not scope:
            continue
        errors=relationship_errors(record,expected_project=PROJECT,asset_id=record["asset_id"],source_path=record["source_path"])
        if errors:
            raise ValueError("Stale verified source: "+"; ".join(errors))
        groups.setdefault(scope["unit_scope_id"],[]).append(record)
    ideas=[]; results=[]; previews=[]
    for scope_id,records in sorted(groups.items()):
        records.sort(key=lambda r:r["source_page"])
        scope=records[0]["unit_plan_relationship"]["catalogue_relationship"]
        if set(r["asset_id"] for r in records)!=set(scope["required_plan_asset_ids"]):
            raise ValueError("Complete canonical floor set is required")
        if any(r["unit_identity"][key]!=records[0]["unit_identity"][key] for r in records for key in ("unit_type","bedrooms","area_sqm")):
            raise ValueError("Conflicting canonical unit facts")
        idea=content_idea(records)
        plan=ContentPlan([ContentPillar("Verified villa layouts",[idea])])
        if plan.validate():
            raise ValueError("; ".join(plan.validate()))
        rendered,package=render_unit(records,brand,logo,config,root)
        if rendered["status"]!="PASSED" or not package:
            raise ValueError("Rendering failed: "+str(rendered))
        package["master_caption"]["full_caption"]=idea.public_copy["caption"]
        gate=validate_package_layouts(package,inventory,expected_project=PROJECT)
        checks=preflight(package,inventory,brand,rendered["provenance"])
        partial=deepcopy(package); partial["slides"]=partial["slides"][:1]
        partial_errors=validate_package_layouts(partial,inventory,expected_project=PROJECT)
        if gate or checks["status"]!="PASSED" or not partial_errors:
            raise ValueError("Draft validation failed: "+str((gate,checks,partial_errors)))
        package.update(package_id="draft-"+scope_id, status="draft", release_id=None,
                       publication_authorized=False,content_id=idea.unique_id)
        slug=records[0]["unit_identity"]["unit_type"].replace(" ","-")
        write(root/"packages"/f"{slug}.json",package)
        write(root/"contracts"/f"{slug}.json",rendered["contracts"])
        write(root/"provenance"/f"{slug}.json",rendered["provenance"])
        ideas.append(idea)
        results.append({"unit_type":records[0]["unit_identity"]["unit_type"],"status":"DRAFT_VALIDATED",
                        "render_qa":rendered["render_qa"],"package_plan_errors":gate,
                        "isolated_preflight":checks,"missing_floor_errors":partial_errors})
        images="".join(f'<img src="renders/{slug}-{i}.png" alt="{escape(s["alt_text"])}">' for i,s in enumerate(package["slides"],1))
        previews.append(f'<section><h2>{escape(idea.title)}</h2><p>{escape(idea.public_copy["caption"]).replace(chr(10),"<br>")}</p><div>{images}</div></section>')
    if not ideas:
        raise ValueError("No complete verified villa relationship is available")
    write(root/"content-plan.json",ContentPlan([ContentPillar("Verified villa layouts",ideas)]).to_dict())
    blocked=[{"unit_type":r["unit_type"],"status":"REVIEW_REQUIRED","reasons":r["source_reasons"]} for r in certified["blocked_units"]]
    write(root/"draft-readiness-report.json",{"project_id":PROJECT,"status":"DRAFTS_VALIDATED",
        "created_at":datetime.now(timezone.utc).isoformat(),"source_inventory":str(inventory_path),
        "source_inventory_sha256":sha(inventory_path),"drafts":results,"blocked_units":blocked,
        "external_requests":0,"publication_jobs_created":0,
        "scope":"Focused source-backed drafts with fresh render and canonical checks. Isolated preflight is evidence, not a live release or schedule."})
    root.mkdir(parents=True,exist_ok=True)
    (root/"review.html").write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Beverly Hills verified villa drafts</title><style>body{font:16px system-ui;background:#f5f4f1;color:#252525;margin:32px auto;max-width:1200px;padding:0 20px}section{margin:32px 0;padding:24px;background:white;border-radius:12px}div{display:flex;gap:20px;flex-wrap:wrap}img{width:min(100%,520px);height:auto;border:1px solid #ddd}p{line-height:1.6}</style><h1>Beverly Hills — verified villa drafts</h1><p>Drafts for review. Both floors are included. Types A, B and C remain blocked. No publication has been scheduled.</p>'+"".join(previews)+'</html>',encoding="utf-8")
    return root/"draft-readiness-report.json"


if __name__=="__main__":
    print(run())
