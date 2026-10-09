"""Validated contract for deterministic source-asset framing plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any


ASPECT_RATIOS = {"1:1", "4:5", "9:16", "16:9", "3:2"}
FUTURE_PLATFORMS = {
    "Instagram Feed", "Instagram Carousel", "Instagram Story", "Instagram Reel",
    "Facebook", "LinkedIn", "Website Banner", "YouTube Thumbnail",
}


@dataclass
class FramingPlan:
    framing_plan_id: str
    sequence: int
    layout_type: str
    crop_strategy: str
    safe_zoom: str
    aspect_ratios: list[str]
    text_safe_area: str
    logo_safe_area: str
    enhancement_notes: list[str]
    platforms: list[str]


@dataclass
class SceneFramingGroup:
    scene_id: str
    scene_name: str
    source_support_status: str
    source_asset_ids: list[str]
    framing_plans: list[FramingPlan] = field(default_factory=list)


@dataclass
class ShotPlan:
    shot_plan_id: str
    scene_plan_id: str
    creative_direction_id: str
    content_idea_id: str
    scene_framing_groups: list[SceneFramingGroup] = field(default_factory=list)


@dataclass
class SkippedScene:
    scene_id: str
    content_idea_id: str
    status: str = "skipped_unavailable"
    reason: str = "No approved source asset supports this scene."


@dataclass
class ShotPlanSummary:
    scene_plans_processed: int = 0
    scenes_processed: int = 0
    fallback_plans_created: int = 0
    text_only_plans_created: int = 0
    skipped_unavailable: int = 0
    invalid_asset_references_removed: int = 0


@dataclass
class ShotPlanCollection:
    shot_plans: list[ShotPlan] = field(default_factory=list)
    skipped_scenes: list[SkippedScene] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: ShotPlanSummary = field(default_factory=ShotPlanSummary)

    def validate(self) -> list[str]:
        errors: list[str] = []
        plan_ids: set[str] = set()
        scene_plan_ids: set[str] = set()
        scene_ids: set[str] = set()
        framing_ids: set[str] = set()
        for plan_index, plan in enumerate(self.shot_plans):
            prefix = f"shot_plans[{plan_index}]"
            if not isinstance(plan, ShotPlan):
                errors.append(f"{prefix} must be an object")
                continue
            for name in ("shot_plan_id", "scene_plan_id", "creative_direction_id", "content_idea_id"):
                value = getattr(plan, name)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{prefix}.{name} must be a non-empty string")
            if plan.shot_plan_id in plan_ids:
                errors.append(f"{prefix} has duplicate shot_plan_id: {plan.shot_plan_id}")
            if plan.scene_plan_id in scene_plan_ids:
                errors.append(f"{prefix} has duplicate scene_plan_id: {plan.scene_plan_id}")
            plan_ids.add(plan.shot_plan_id); scene_plan_ids.add(plan.scene_plan_id)
            for group_index, group in enumerate(plan.scene_framing_groups):
                group_prefix = f"{prefix}.scene_framing_groups[{group_index}]"
                if not isinstance(group, SceneFramingGroup):
                    errors.append(f"{group_prefix} must be an object")
                    continue
                if group.scene_id in scene_ids:
                    errors.append(f"{group_prefix} has duplicate scene_id: {group.scene_id}")
                scene_ids.add(group.scene_id)
                if group.source_support_status not in {"fully_supported", "partially_supported", "text_only"}:
                    errors.append(f"{group_prefix}.source_support_status is invalid")
                if len(group.framing_plans) != 1:
                    errors.append(f"{group_prefix} must contain exactly one framing plan")
                for framing in group.framing_plans:
                    errors.extend(_validate_framing(framing, group_prefix, framing_ids))
        if not isinstance(self.warnings, list) or not all(isinstance(item, str) for item in self.warnings):
            errors.append("warnings must contain only strings")
        if not isinstance(self.summary, ShotPlanSummary) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in asdict(self.summary).values()
        ):
            errors.append("summary counts must be non-negative integers")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ShotPlanCollection":
        if not isinstance(data, dict) or set(data) != {"shot_plans", "skipped_scenes", "warnings", "summary"}:
            raise ValueError("Shot plan JSON has unexpected or missing collection fields")
        try:
            plans = []
            for raw_plan in data["shot_plans"]:
                if set(raw_plan) != set(ShotPlan.__dataclass_fields__):
                    raise ValueError("Shot plan JSON has unexpected or missing plan fields")
                groups = []
                for raw_group in raw_plan["scene_framing_groups"]:
                    if set(raw_group) != set(SceneFramingGroup.__dataclass_fields__):
                        raise ValueError("Shot plan JSON has unexpected or missing scene framing fields")
                    framings = [FramingPlan(**item) for item in raw_group["framing_plans"]]
                    groups.append(SceneFramingGroup(**{key: value for key, value in raw_group.items() if key != "framing_plans"}, framing_plans=framings))
                plans.append(ShotPlan(**{key: value for key, value in raw_plan.items() if key != "scene_framing_groups"}, scene_framing_groups=groups))
            collection = cls(
                shot_plans=plans,
                skipped_scenes=[SkippedScene(**item) for item in data["skipped_scenes"]],
                warnings=data["warnings"], summary=ShotPlanSummary(**data["summary"]),
            )
        except (KeyError, TypeError) as error:
            raise ValueError("Shot plan JSON has an invalid structure") from error
        errors = collection.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return collection

    @classmethod
    def from_json(cls, payload: str) -> "ShotPlanCollection":
        try:
            return cls.from_dict(json.loads(payload))
        except json.JSONDecodeError as error:
            raise ValueError("Shot plan JSON is invalid") from error


def _validate_framing(framing: FramingPlan, prefix: str, ids: set[str]) -> list[str]:
    errors: list[str] = []
    if framing.framing_plan_id in ids:
        errors.append(f"{prefix} has duplicate framing_plan_id: {framing.framing_plan_id}")
    ids.add(framing.framing_plan_id)
    if framing.sequence != 1:
        errors.append(f"{prefix}.framing plan sequence must be 1")
    for name in ("framing_plan_id", "layout_type", "crop_strategy", "safe_zoom", "text_safe_area", "logo_safe_area"):
        value = getattr(framing, name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{prefix}.{name} must be a non-empty string")
    if not framing.aspect_ratios or not set(framing.aspect_ratios).issubset(ASPECT_RATIOS):
        errors.append(f"{prefix}.aspect_ratios contains unsupported values")
    if not set(framing.platforms).issubset(FUTURE_PLATFORMS):
        errors.append(f"{prefix}.platforms contains unsupported values")
    if not isinstance(framing.enhancement_notes, list) or not all(isinstance(item, str) for item in framing.enhancement_notes):
        errors.append(f"{prefix}.enhancement_notes must contain strings")
    return errors


# Compatibility aliases for imports; the legacy cinematography contract is no longer produced.
Shot = FramingPlan
SceneShotGroup = SceneFramingGroup
SHOT_TYPES: set[str] = set()
