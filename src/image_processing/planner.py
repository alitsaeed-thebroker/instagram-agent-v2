"""Plan conservative processing of authentic project assets without transforming them."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from src.core.logger import get_logger
from src.image_processing.schema import (
    ExportVariant, ImageProcessingPlan, ImageProcessingPlanCollection, SourceAssetOperation,
)
from src.image_processing.storage import save_image_processing_plans
from src.shots.schema import ShotPlanCollection
from src.utils.config import PROJECT_ROOT, PROJECT_VISUAL_MODE, SOURCE_IMAGES_OUTPUT_DIRECTORY

MODULE_VERSION = "1.2.0"
logger = get_logger(__name__)

_EXPORTS = {
    "Instagram Feed": (1080, 1350, "4:5"),
    "Instagram Carousel": (1080, 1350, "4:5"),
    "Instagram Story": (1080, 1920, "9:16"),
    "Instagram Reel": (1080, 1920, "9:16"),
    "Facebook": (1200, 1500, "4:5"),
    "LinkedIn": (1200, 1200, "1:1"),
    "Website Banner": (1920, 1080, "16:9"),
    "YouTube Thumbnail": (1280, 720, "16:9"),
}


class ImageProcessingPlanner:
    """Create instructions only; never execute transformations or generate imagery."""

    def run(
        self, visual_inventory_path: Path, shot_plans_path: Path,
        source_manifest_path: Path | None = None,
        content_plan_path: Path | None = None, knowledge_path: Path | None = None,
    ) -> Path | None:
        logger.info("Starting Image Processing Planner...")
        logger.info("Reading visual inventory and framing plans...")
        try:
            if PROJECT_VISUAL_MODE != "source_only":
                raise ValueError("Image Processing Planner requires PROJECT_VISUAL_MODE=source_only")
            inventory = json.loads(visual_inventory_path.read_text(encoding="utf-8"))
            framing = ShotPlanCollection.from_json(shot_plans_path.read_text(encoding="utf-8"))
            project = inventory["project"]
            manifest_path = source_manifest_path or SOURCE_IMAGES_OUTPUT_DIRECTORY / project / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("project") != project:
                raise ValueError("Visual inventory and source manifest belong to different projects")
        except (OSError, UnicodeError, KeyError, TypeError, ValueError) as error:
            logger.error("Could not read valid Image Processing Planner input: %s", error)
            return None

        logger.info("Validating authentic source assets...")
        collection = _build_processing_plans(project, inventory, manifest, manifest_path.parent, framing)
        if content_plan_path is not None:
            try:
                if knowledge_path is None:raise ValueError("Canonical knowledge is required for publication export alignment")
                from src.image_processing.canonical_exports import align_canonical_exports
                collection=align_canonical_exports(collection,json.loads(content_plan_path.read_text(encoding="utf-8")),json.loads(knowledge_path.read_text(encoding="utf-8")),project)
            except (OSError,TypeError,ValueError) as error:
                logger.error("Canonical export handoff failed: %s",error);return None
        logger.info("Generating processing plans...")
        logger.info("Validating image processing plans...")
        errors = collection.validate()
        errors.extend(_validate_coverage(collection, framing))
        if errors:
            logger.error("Image processing plan validation failed: %s", "; ".join(errors))
            return None
        try:
            output_path = save_image_processing_plans(collection, project)
        except (OSError, ValueError) as error:
            logger.error("Could not save image processing plans: %s", error)
            return None
        try:
            display_path = output_path.relative_to(PROJECT_ROOT)
        except ValueError:
            display_path = output_path
        logger.info("Image processing plans saved:\n%s", display_path)
        summary = collection.summary
        logger.info(
            "Image Processing Planner completed:\n- Processing plans created: %d\n- Text-only plans: %d\n- Fallback plans: %d\n- Skipped unavailable: %d\n- Invalid asset references removed: %d",
            summary.processing_plans_created, summary.text_only_plans_created,
            summary.fallback_plans_created, summary.skipped_unavailable,
            summary.invalid_asset_references_removed,
        )
        return output_path


def _build_processing_plans(
    project: str, inventory: dict[str, Any], manifest: dict[str, Any], source_root: Path,
    framing: ShotPlanCollection,
) -> ImageProcessingPlanCollection:
    output = ImageProcessingPlanCollection()
    allowed_ids = set(inventory.get("all_source_asset_ids", []))
    manifest_assets = {item["asset_id"]: item for item in manifest.get("assets", [])}
    for skipped in framing.skipped_scenes:
        output.skipped_items.append({
            "scene_id": skipped.scene_id, "content_idea_id": skipped.content_idea_id,
            "status": "skipped_unavailable", "reason": skipped.reason,
        })
        output.summary.skipped_unavailable += 1
    for shot_plan in framing.shot_plans:
        for group in shot_plan.scene_framing_groups:
            for framing_plan in group.framing_plans:
                valid_assets: list[dict[str, Any]] = []
                for asset_id in group.source_asset_ids:
                    asset, warning = _validated_asset(asset_id, allowed_ids, manifest_assets, source_root)
                    if asset is None:
                        output.summary.invalid_asset_references_removed += 1
                        output.warnings.append(f"Scene {group.scene_id}: {warning}")
                    else:
                        valid_assets.append(asset)
                status = group.source_support_status
                if status in {"fully_supported", "partially_supported"} and not valid_assets:
                    output.skipped_items.append({
                        "scene_id": group.scene_id, "content_idea_id": shot_plan.content_idea_id,
                        "status": "skipped_unavailable", "reason": "No valid authentic source file remains for processing.",
                    })
                    output.summary.skipped_unavailable += 1
                    continue
                variants = _export_variants(framing_plan.platforms, framing_plan.aspect_ratios)
                operations = [_source_operation(asset, source_root, variants, output.warnings) for asset in valid_assets]
                text_layout = _text_layout(framing_plan, valid_assets) if status == "text_only" else None
                created = datetime.now(timezone.utc).isoformat()
                plan = ImageProcessingPlan(
                    processing_plan_id=f"{framing_plan.framing_plan_id}-IP1", project=project,
                    shot_plan_id=shot_plan.shot_plan_id, scene_plan_id=shot_plan.scene_plan_id,
                    creative_direction_id=shot_plan.creative_direction_id,
                    content_idea_id=shot_plan.content_idea_id, scene_id=group.scene_id,
                    framing_plan_id=framing_plan.framing_plan_id, source_support_status=status,
                    source_asset_ids=[asset["asset_id"] for asset in valid_assets],
                    source_asset_operations=operations, export_variants=variants,
                    text_layout_preparation=text_layout,
                    provenance={
                        "source_asset_ids": [asset["asset_id"] for asset in valid_assets],
                        "source_documents": [asset.get("source_document") for asset in valid_assets],
                        "source_pages": [asset.get("source_page") for asset in valid_assets],
                        "source_hashes": [asset["sha256"] for asset in valid_assets],
                        "crop_coordinates": [operation.crop for operation in operations],
                        "resize_dimensions": [{"width": item.width, "height": item.height} for item in variants],
                        "planned_enhancements": [operation.technical_enhancements for operation in operations],
                        "output_formats": sorted({item.output_format for item in variants}),
                        "module_version": MODULE_VERSION, "creation_timestamp": created,
                        "source_only": True, "transformations_executed": False,
                    },
                )
                output.image_processing_plans.append(plan)
                output.summary.fallback_plans_created += 1
                if status == "text_only":
                    output.summary.text_only_plans_created += 1
    output.summary.processing_plans_created = len(output.image_processing_plans)
    return output


def _validated_asset(asset_id: str, allowed_ids: set[str], assets: dict[str, dict[str, Any]], root: Path) -> tuple[dict[str, Any] | None, str | None]:
    if asset_id not in allowed_ids:
        return None, f"asset {asset_id} is not in the current project visual inventory"
    asset = assets.get(asset_id)
    if asset is None:
        return None, f"asset {asset_id} is missing from the current project source manifest"
    path = root / asset.get("filename", "")
    if not path.is_file():
        return None, f"source file for asset {asset_id} is missing"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != asset.get("sha256"):
        return None, f"source hash mismatch for asset {asset_id}"
    return asset, None


def _export_variants(platforms: list[str], ratios: list[str]) -> list[ExportVariant]:
    variants: list[ExportVariant] = []
    seen: set[tuple[str, int, int]] = set()
    for platform in platforms:
        if platform not in _EXPORTS:
            continue
        width, height, ratio = _EXPORTS[platform]
        if ratios and ratio not in ratios:
            continue
        key = (platform, width, height)
        if key not in seen:
            variants.append(ExportVariant(platform, width, height, ratio, "JPEG", 90))
            seen.add(key)
    if not variants:
        for ratio in ratios:
            dimensions = {"4:5": (1080, 1350), "1:1": (1080, 1080), "9:16": (1080, 1920), "16:9": (1920, 1080), "3:2": (1500, 1000)}.get(ratio)
            if dimensions:
                variants.append(ExportVariant("Generic approved layout", *dimensions, ratio, "JPEG", 90))
    return variants


def _source_operation(asset: dict[str, Any], root: Path, variants: list[ExportVariant], warnings: list[str]) -> SourceAssetOperation:
    width, height = int(asset.get("width", 0)), int(asset.get("height", 0))
    max_scale = max((max(item.width / max(width, 1), item.height / max(height, 1)) for item in variants), default=1.0)
    needs_super_resolution = max_scale > 1.0
    if needs_super_resolution:
        warnings.append(f"Low-resolution source {asset['asset_id']} requires conservative super-resolution; generated detail must not be represented as original")
    enhancements = []
    for operation in (
        "exposure_adjustment", "brightness_adjustment", "contrast_adjustment", "white_balance_correction",
        "denoising", "deblocking", "moderate_sharpening", "super_resolution",
        "compression_cleanup", "pdf_margin_removal", "perspective_correction",
    ):
        enabled = operation == "super_resolution" and needs_super_resolution
        enhancements.append({
            "operation": operation, "enabled": enabled,
            "strength": f"{math.ceil(max_scale)}x" if enabled else "disabled",
            "reason": "Required to meet target export dimensions" if enabled else "No reliable automated evidence justifies adjustment",
            "preservation_constraint": "Preserve source geometry, texture identity, architecture, proportions, materials, colors, and visible project features; do not invent detail",
        })
    path = root / asset["filename"]
    try:
        source_path = str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        source_path = str(path)
    return SourceAssetOperation(
        source_asset_id=asset["asset_id"], source_path=source_path,
        source_width=width, source_height=height,
        source_format=asset.get("format") or Path(asset["filename"]).suffix.lstrip(".").upper(),
        source_hash=asset["sha256"], orientation=asset.get("orientation", "unknown"),
        crop={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
        resize={"mode": "contain_letterbox", "target_dimensions": [{"width": item.width, "height": item.height} for item in variants], "preserve_geometry": True},
        technical_enhancements=enhancements,
        output_preparation={"output_format": "JPEG", "compression_quality": 90, "preserve_metadata_provenance": True},
    )


def _text_layout(framing: Any, assets: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "layout_type": framing.layout_type,
        "approved_source_refs": [asset["asset_id"] for asset in assets],
        "required_text_refs": [],
        "recommended_background_policy": "Use only a future approved neutral template; do not create a synthetic project background",
        "text_safe_area": framing.text_safe_area, "logo_safe_area": framing.logo_safe_area,
    }


def _validate_coverage(collection: ImageProcessingPlanCollection, framing: ShotPlanCollection) -> list[str]:
    """Ensure every framing input is represented exactly once as processed or skipped."""
    errors: list[str] = []
    plans_by_framing: dict[str, list[ImageProcessingPlan]] = {}
    for plan in collection.image_processing_plans:
        plans_by_framing.setdefault(plan.framing_plan_id, []).append(plan)
    skipped_scene_ids = {item.get("scene_id") for item in collection.skipped_items}
    expected_ids: set[str] = set()
    for shot_plan in framing.shot_plans:
        for group in shot_plan.scene_framing_groups:
            for framing_plan in group.framing_plans:
                expected_ids.add(framing_plan.framing_plan_id)
                matches = plans_by_framing.get(framing_plan.framing_plan_id, [])
                if len(matches) == 1:
                    plan = matches[0]
                    if (
                        plan.shot_plan_id != shot_plan.shot_plan_id
                        or plan.scene_plan_id != shot_plan.scene_plan_id
                        or plan.creative_direction_id != shot_plan.creative_direction_id
                        or plan.content_idea_id != shot_plan.content_idea_id
                        or plan.scene_id != group.scene_id
                    ):
                        errors.append(f"processing plan {plan.processing_plan_id} does not preserve upstream links")
                elif len(matches) > 1:
                    errors.append(f"duplicate processing plans for framing_plan_id {framing_plan.framing_plan_id}")
                elif group.scene_id not in skipped_scene_ids:
                    errors.append(f"missing processing or skip record for framing_plan_id {framing_plan.framing_plan_id}")
    unexpected = set(plans_by_framing) - expected_ids
    if unexpected:
        errors.append(f"unexpected framing plan IDs: {', '.join(sorted(unexpected))}")
    return errors
