"""Fail-safe selection of approved source visuals for content ideas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.content.schema import ContentPlan
from src.utils.config import ASSET_SELECTIONS_OUTPUT_DIRECTORY, REPORTS_OUTPUT_DIRECTORY, PROJECT_ROOT
from src.content.visual_purpose import load_visual_reviews, validate_overview_slides
from src.project_sequence import role

SELECTION_VERSION="2.0.1"


def plan_asset_selection(
    content_plan_path: Path,
    analysis_path: Path,
    output_root: Path = ASSET_SELECTIONS_OUTPUT_DIRECTORY,
    review_root: Path = PROJECT_ROOT,
) -> Path:
    """Select only approved usable assets; block ideas when none exist."""
    raw_content=json.loads(content_plan_path.read_text(encoding="utf-8"))
    content = ContentPlan.from_dict(raw_content)
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    usable = _usable_assets(analysis)
    project=str(raw_content.get("project_id") or analysis.get("project_id") or analysis.get("project") or content_plan_path.stem.removesuffix("-content-plan"))
    raw_ideas={i.get("content_idea_id"):i for i in raw_content.get("content_ideas",[])}
    all_assets={a["asset_id"]:a for values in analysis.values() if isinstance(values,list) for a in values if isinstance(a,dict) and a.get("asset_id") and a.get("project_id",a.get("project"))==project}
    reviewed={a["asset_id"]:a for a in load_visual_reviews(review_root,list(all_assets.values()))}
    selections = []
    for pillar in content.pillars:
        for idea in pillar.content_ideas:
            allowed_ids = set(idea.available_source_asset_ids)
            ranked = sorted((asset for asset in usable if asset["asset_id"] in allowed_ids and asset.get("project_id",asset.get("project",project))==project), key=lambda asset: _score(asset, idea), reverse=True)
            selected = ranked[:3]
            purpose=role(raw_ideas.get(idea.unique_id,{}).get("content_category"))
            canonical_ids=list(idea.selected_source_asset_ids)
            if canonical_ids:
                candidates=reviewed if purpose=="project_overview" else {a["asset_id"]:a for a in usable if a.get("project_id",a.get("project",project))==project}
                if len(set(canonical_ids))!=len(canonical_ids) or any(a not in candidates or a not in allowed_ids for a in canonical_ids):
                    raise ValueError("Canonical source selection contains unavailable or duplicate source assets")
                selected=[candidates[a] for a in canonical_ids]
                if purpose=="project_overview":
                    errors=validate_overview_slides(selected,project)
                    if errors:raise ValueError(str(errors))
            supported = idea.source_support_status != "unavailable" and (
                bool(selected) or idea.source_support_status == "text_only"
            )
            selections.append({
                "content_idea_id": idea.unique_id,
                "canonical_ordered_selection":bool(canonical_ids),
                "publication_role":purpose,
                "publication_type":idea.selected_format,
                "source_image_available": bool(selected),
                "selected_asset_ids": [asset["asset_id"] for asset in selected],
                "selection_reason": "Approved source assets already assigned by inventory-grounded content planning" if selected else "Source-supported text-only treatment" if supported else "No usable approved source image was found",
                "supported_project_features": [feature for asset in selected for feature in asset.get("visible_project_features", [])],
                "recommended_platforms": sorted({platform for asset in selected for platform in asset.get("recommended_platforms", [])}),
                "recommended_layout": "Use the source composition without reconstructing project content" if selected else "approved text graphic" if supported else "skipped",
                "safe_crop": "Crop only within source bounds; preserve all important visible project features" if selected else None,
                "text_safe_zone": [asset.get("text_safe_area_assessment", "") for asset in selected if asset.get("text_safe_area_assessment")],
                "logo_safe_zone": [],
                "reason": None if supported else "No approved visual can support this content item",
                "required_missing_asset": None if supported else idea.main_subject,
                "status": "ready" if supported else "skipped_unavailable",
            })
    output_root.mkdir(parents=True, exist_ok=True)
    project = content_plan_path.stem.removesuffix("-content-plan")
    destination = output_root / f"{project}-asset-selections.json"
    summary = {
        "fully_supported": sum(idea.source_support_status == "fully_supported" for pillar in content.pillars for idea in pillar.content_ideas),
        "partially_supported": sum(idea.source_support_status == "partially_supported" for pillar in content.pillars for idea in pillar.content_ideas),
        "text_only": sum(idea.source_support_status == "text_only" for pillar in content.pillars for idea in pillar.content_ideas),
        "skipped_unavailable": sum(item["status"] == "skipped_unavailable" for item in selections),
    }
    payload = {
        "project": project, "visual_mode": "source_only", "selection_version":SELECTION_VERSION,"selections": selections,
        "workflow_status": "ready", "content_production_summary": summary,
    }
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REPORTS_OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_OUTPUT_DIRECTORY / f"{project}-content-availability.json"
    report_path.write_text(json.dumps({"summary": summary, "skipped_items": [item for item in selections if item["status"] == "skipped_unavailable"]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


def assert_selection_ready(selection_path: Path) -> None:
    data = json.loads(selection_path.read_text(encoding="utf-8"))
    if data.get("visual_mode") != "source_only" or data.get("workflow_status") != "ready":
        raise ValueError("Asset selection artifact is invalid for source-only processing")


def _score(asset: dict[str, Any], idea: Any) -> int:
    terms = " ".join([idea.title, idea.story, idea.main_subject, *idea.supporting_subjects]).casefold()
    type_score = 30 if asset["asset_type"].casefold().replace("_", " ") in terms else 0
    return int(asset.get("quality_score", asset.get("image_quality", {}).get("score", 0))) + type_score + int(float(asset.get("confidence", 0)) * 20)


def _usable_assets(data: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(data.get("assets"), list):
        return [asset for asset in data["assets"] if asset["asset_type"] not in {"Low Quality", "Text Page", "Logo", "Developer Graphic", "Unknown"} and asset["marketing_suitability"] == "suitable"]
    excluded = {"unknown_assets", "unsuitable_assets", "failed_analyses"}
    assets: dict[str, dict[str, Any]] = {}
    for field, values in data.items():
        if not field.startswith("available_") or field == "available_text_facts" or field in excluded or not isinstance(values, list):
            continue
        for raw in values:
            if not isinstance(raw, dict) or not raw.get("asset_id") or raw.get("analysis_status") in {"failed", "unsuitable", "review_required"}:
                continue
            if raw.get("marketing_suitability") in {"review_required", "unsuitable"}:
                continue
            asset = dict(raw)
            asset["quality_score"] = raw.get("quality_score", raw.get("image_quality", {}).get("score", 0))
            assets[asset["asset_id"]] = asset
    return list(assets.values())
