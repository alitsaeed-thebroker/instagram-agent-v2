"""Validated JSON contract for source-only image-processing instructions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any


ALLOWED_OPERATIONS = {
    "exposure_adjustment", "brightness_adjustment", "contrast_adjustment",
    "white_balance_correction", "denoising", "deblocking", "moderate_sharpening",
    "super_resolution", "compression_cleanup", "pdf_margin_removal", "perspective_correction",
}
FORBIDDEN_FIELDS = {
    "image_prompt", "negative_prompt", "provider", "model", "seed", "generation_count",
    "camera_angle", "lens", "new_viewpoint", "inpainting_request", "synthetic_background",
    "content_generation_instruction", "invented_subject", "invented_architecture",
}


@dataclass
class SourceAssetOperation:
    source_asset_id: str
    source_path: str
    source_width: int
    source_height: int
    source_format: str
    source_hash: str
    orientation: str
    crop: dict[str, float]
    resize: dict[str, Any]
    technical_enhancements: list[dict[str, Any]]
    output_preparation: dict[str, Any]


@dataclass
class ExportVariant:
    platform: str
    width: int
    height: int
    aspect_ratio: str
    output_format: str
    compression_quality: int


@dataclass
class ImageProcessingPlan:
    processing_plan_id: str
    project: str
    shot_plan_id: str
    scene_plan_id: str
    creative_direction_id: str
    content_idea_id: str
    scene_id: str
    framing_plan_id: str
    source_support_status: str
    source_asset_ids: list[str]
    source_asset_operations: list[SourceAssetOperation]
    export_variants: list[ExportVariant]
    text_layout_preparation: dict[str, Any] | None
    provenance: dict[str, Any]


@dataclass
class ProcessingSummary:
    processing_plans_created: int = 0
    text_only_plans_created: int = 0
    skipped_unavailable: int = 0
    invalid_asset_references_removed: int = 0
    fallback_plans_created: int = 0


@dataclass
class ImageProcessingPlanCollection:
    image_processing_plans: list[ImageProcessingPlan] = field(default_factory=list)
    skipped_items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: ProcessingSummary = field(default_factory=ProcessingSummary)

    def validate(self) -> list[str]:
        errors: list[str] = []
        ids: set[str] = set()
        framing_ids: set[str] = set()
        for index, plan in enumerate(self.image_processing_plans):
            prefix = f"image_processing_plans[{index}]"
            if plan.processing_plan_id in ids:
                errors.append(f"{prefix} has duplicate processing_plan_id: {plan.processing_plan_id}")
            ids.add(plan.processing_plan_id)
            if plan.framing_plan_id in framing_ids:
                errors.append(f"{prefix} has duplicate framing_plan_id: {plan.framing_plan_id}")
            framing_ids.add(plan.framing_plan_id)
            if plan.processing_plan_id != f"{plan.framing_plan_id}-IP1":
                errors.append(f"{prefix}.processing_plan_id is not deterministic")
            if plan.source_support_status not in {"fully_supported", "partially_supported", "text_only"}:
                errors.append(f"{prefix}.source_support_status is invalid")
            if plan.source_asset_ids != [item.source_asset_id for item in plan.source_asset_operations]:
                errors.append(f"{prefix}.source_asset_ids must match source_asset_operations")
            for operation_index, operation in enumerate(plan.source_asset_operations):
                op_prefix = f"{prefix}.source_asset_operations[{operation_index}]"
                errors.extend(_validate_crop(operation.crop, op_prefix))
                if operation.source_width <= 0 or operation.source_height <= 0:
                    errors.append(f"{op_prefix} source dimensions must be positive")
                for enhancement in operation.technical_enhancements:
                    if enhancement.get("operation") not in ALLOWED_OPERATIONS:
                        errors.append(f"{op_prefix} contains unsupported operation {enhancement.get('operation')}")
            for variant_index, variant in enumerate(plan.export_variants):
                if variant.width <= 0 or variant.height <= 0:
                    errors.append(f"{prefix}.export_variants[{variant_index}] dimensions must be positive")
            forbidden = _find_forbidden(asdict(plan))
            if forbidden:
                errors.append(f"{prefix} contains forbidden fields: {', '.join(sorted(forbidden))}")
        if self.summary.processing_plans_created != len(self.image_processing_plans):
            errors.append("summary.processing_plans_created must match image_processing_plans")
        if self.summary.text_only_plans_created != sum(plan.source_support_status == "text_only" for plan in self.image_processing_plans):
            errors.append("summary.text_only_plans_created does not match plans")
        if self.summary.skipped_unavailable != len(self.skipped_items):
            errors.append("summary.skipped_unavailable must match skipped_items")
        if self.summary.fallback_plans_created != len(self.image_processing_plans):
            errors.append("summary.fallback_plans_created must match deterministic fallback plans")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageProcessingPlanCollection":
        if not isinstance(data, dict) or set(data) != {"image_processing_plans", "skipped_items", "warnings", "summary"}:
            raise ValueError("Image processing plan JSON has unexpected or missing collection fields")
        try:
            plans = []
            for raw in data["image_processing_plans"]:
                operations = [SourceAssetOperation(**item) for item in raw["source_asset_operations"]]
                variants = [ExportVariant(**item) for item in raw["export_variants"]]
                plans.append(ImageProcessingPlan(
                    **{key: value for key, value in raw.items() if key not in {"source_asset_operations", "export_variants"}},
                    source_asset_operations=operations, export_variants=variants,
                ))
            collection = cls(plans, data["skipped_items"], data["warnings"], ProcessingSummary(**data["summary"]))
        except (KeyError, TypeError) as error:
            raise ValueError("Image processing plan JSON has an invalid structure") from error
        errors = collection.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return collection

    @classmethod
    def from_json(cls, payload: str) -> "ImageProcessingPlanCollection":
        try:
            return cls.from_dict(json.loads(payload))
        except json.JSONDecodeError as error:
            raise ValueError("Image processing plan JSON is invalid") from error


def _validate_crop(crop: dict[str, Any], prefix: str) -> list[str]:
    if not isinstance(crop, dict) or set(crop) != {"x", "y", "width", "height"}:
        return [f"{prefix}.crop must contain normalized x, y, width, and height"]
    values = crop.values()
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in values):
        return [f"{prefix}.crop values must be numeric"]
    if crop["x"] < 0 or crop["y"] < 0 or crop["width"] <= 0 or crop["height"] <= 0 or crop["x"] + crop["width"] > 1 or crop["y"] + crop["height"] > 1:
        return [f"{prefix}.crop must remain within normalized bounds"]
    return []


def _find_forbidden(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_FIELDS:
                found.add(key)
            found.update(_find_forbidden(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_forbidden(item))
    return found
