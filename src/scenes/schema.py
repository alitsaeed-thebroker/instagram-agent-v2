"""Validated JSON contract for grounded cinematic scene plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any


@dataclass
class Scene:
    """One story unit, containing no cinematography or prompt decisions."""

    scene_id: str
    sequence: int
    scene_name: str
    story_purpose: str
    scene_summary: str
    main_subject: str
    supporting_subjects: list[str]
    environment: str
    factual_basis: list[str]
    creative_interpretation: str
    time_of_day: str
    weather: str
    mood: str
    lighting_direction: str
    scene_dependencies: list[str]
    reusable_asset_ids: list[str]
    continuity_notes: list[str]
    restrictions: list[str]
    transition_to_next_scene: str


@dataclass
class ScenePlan:
    """Ordered scenes for exactly one approved creative direction."""

    scene_plan_id: str
    creative_direction_id: str
    content_idea_id: str
    overall_story_summary: str
    scene_count: int
    scenes: list[Scene] = field(default_factory=list)


@dataclass
class SkippedContentIdea:
    content_idea_id: str
    status: str = "skipped_unavailable"
    reason: str = "No approved source asset supports this idea."


@dataclass
class ScenePlanSummary:
    fully_supported_processed: int = 0
    partially_supported_processed: int = 0
    text_only_processed: int = 0
    skipped_unavailable: int = 0


@dataclass
class ScenePlanCollection:
    """Complete collection of scene plans produced in one workflow stage."""

    scene_plans: list[ScenePlan] = field(default_factory=list)
    skipped_content_ideas: list[SkippedContentIdea] = field(default_factory=list)
    summary: ScenePlanSummary = field(default_factory=ScenePlanSummary)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.scene_plans, list):
            return ["scene_plans must be a list of objects"]
        if not isinstance(self.skipped_content_ideas, list):
            errors.append("skipped_content_ideas must be a list of objects")
        else:
            for index, item in enumerate(self.skipped_content_ideas):
                if not isinstance(item, SkippedContentIdea) or not isinstance(item.content_idea_id, str) or not item.content_idea_id.strip():
                    errors.append(f"skipped_content_ideas[{index}] is invalid")
                elif item.status != "skipped_unavailable":
                    errors.append(f"skipped_content_ideas[{index}].status must be skipped_unavailable")
        if not isinstance(self.summary, ScenePlanSummary):
            errors.append("summary must be an object")
        elif any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in asdict(self.summary).values()):
            errors.append("summary counts must be non-negative integers")
        plan_ids: set[str] = set()
        direction_ids: set[str] = set()
        idea_ids: set[str] = set()
        all_scene_ids: set[str] = set()
        for plan_index, plan in enumerate(self.scene_plans):
            prefix = f"scene_plans[{plan_index}]"
            if not isinstance(plan, ScenePlan):
                errors.append(f"{prefix} must be an object")
                continue
            for name in _PLAN_STRING_FIELDS:
                value = getattr(plan, name)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{prefix}.{name} must be a non-empty string")
            if plan.scene_plan_id in plan_ids:
                errors.append(f"{prefix}.scene_plan_id must be unique")
            plan_ids.add(plan.scene_plan_id)
            if plan.creative_direction_id in direction_ids:
                errors.append(f"{prefix} has duplicate creative_direction_id: {plan.creative_direction_id}")
            direction_ids.add(plan.creative_direction_id)
            if plan.content_idea_id in idea_ids:
                errors.append(f"{prefix}.content_idea_id must be unique")
            idea_ids.add(plan.content_idea_id)
            if not isinstance(plan.scenes, list) or not plan.scenes:
                errors.append(f"{prefix}.scenes must be a non-empty list of objects")
                continue
            if not isinstance(plan.scene_count, int) or isinstance(plan.scene_count, bool):
                errors.append(
                    f"{prefix} (creative_direction_id={plan.creative_direction_id}) has invalid "
                    f"declared scene_count={plan.scene_count}; actual scenes={len(plan.scenes)}"
                )
            elif plan.scene_count != len(plan.scenes):
                errors.append(
                    f"{prefix} (creative_direction_id={plan.creative_direction_id}) scene_count mismatch: "
                    f"declared scene_count={plan.scene_count}, actual scenes={len(plan.scenes)}"
                )
            expected_sequences = list(range(1, len(plan.scenes) + 1))
            actual_sequences = [scene.sequence for scene in plan.scenes if isinstance(scene, Scene)]
            if len(actual_sequences) == len(plan.scenes) and actual_sequences != expected_sequences:
                errors.append(f"{prefix}.scenes must have consecutive sequence values starting at 1")
            local_ids = {scene.scene_id for scene in plan.scenes if isinstance(scene, Scene) and isinstance(scene.scene_id, str)}
            normalized_names = [scene.scene_name.strip().casefold() for scene in plan.scenes if isinstance(scene, Scene) and isinstance(scene.scene_name, str)]
            if len(normalized_names) != len(set(normalized_names)):
                errors.append(f"{prefix}.scenes must have distinct scene names")
            normalized_summaries = [scene.scene_summary.strip().casefold() for scene in plan.scenes if isinstance(scene, Scene) and isinstance(scene.scene_summary, str)]
            if len(normalized_summaries) != len(set(normalized_summaries)):
                errors.append(f"{prefix}.scenes must have distinct scene summaries")
            sequence_by_id = {
                scene.scene_id: scene.sequence for scene in plan.scenes
                if isinstance(scene, Scene) and isinstance(scene.scene_id, str) and isinstance(scene.sequence, int)
            }
            for scene_index, scene in enumerate(plan.scenes):
                scene_prefix = f"{prefix}.scenes[{scene_index}]"
                if not isinstance(scene, Scene):
                    errors.append(f"{scene_prefix} must be an object")
                    continue
                errors.extend(_validate_scene(scene, scene_prefix))
                if scene.scene_id in all_scene_ids:
                    errors.append(f"{scene_prefix}.scene_id must be globally unique")
                all_scene_ids.add(scene.scene_id)
                for dependency in scene.scene_dependencies:
                    if dependency not in local_ids:
                        errors.append(f"{scene_prefix}.scene_dependencies contains unknown scene ID {dependency}")
                    elif dependency == scene.scene_id:
                        errors.append(f"{scene_prefix}.scene_dependencies must not reference itself")
                    elif sequence_by_id.get(dependency, scene.sequence) >= scene.sequence:
                        errors.append(f"{scene_prefix}.scene_dependencies must reference an earlier scene")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScenePlanCollection":
        allowed_fields = {"scene_plans", "skipped_content_ideas", "summary"}
        if not isinstance(data, dict) or "scene_plans" not in data or not set(data).issubset(allowed_fields):
            raise ValueError("Scene plan JSON contains unexpected or missing collection fields")
        raw_plans = data["scene_plans"]
        if not isinstance(raw_plans, list):
            raise ValueError("scene_plans must be a list of objects")
        plans: list[ScenePlan] = []
        try:
            for raw_plan in raw_plans:
                if not isinstance(raw_plan, dict) or set(raw_plan) != set(_PLAN_FIELDS):
                    raise ValueError("Scene plan JSON has unexpected or missing plan fields")
                raw_scenes = raw_plan["scenes"]
                if not isinstance(raw_scenes, list) or any(
                    not isinstance(raw_scene, dict) or set(raw_scene) != set(_SCENE_FIELDS)
                    for raw_scene in raw_scenes
                ):
                    raise ValueError("Scene plan JSON has unexpected or missing scene fields")
                plans.append(ScenePlan(
                    **{name: raw_plan[name] for name in _PLAN_FIELDS if name != "scenes"},
                    scenes=[Scene(**raw_scene) for raw_scene in raw_scenes],
                ))
        except (KeyError, TypeError) as error:
            raise ValueError("Scene plan JSON has an invalid structure") from error
        try:
            skipped = [SkippedContentIdea(**item) for item in data.get("skipped_content_ideas", [])]
            summary = ScenePlanSummary(**data.get("summary", {}))
        except (TypeError, KeyError) as error:
            raise ValueError("Scene plan summary or skipped content is invalid") from error
        collection = cls(scene_plans=plans, skipped_content_ideas=skipped, summary=summary)
        errors = collection.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return collection

    @classmethod
    def from_json(cls, payload: str) -> "ScenePlanCollection":
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("Scene plan JSON is invalid") from error
        return cls.from_dict(data)


def _validate_scene(scene: Scene, prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(scene.sequence, int) or isinstance(scene.sequence, bool) or scene.sequence < 1:
        errors.append(f"{prefix}.sequence must be a positive integer")
    for name in _SCENE_STRING_FIELDS:
        value = getattr(scene, name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{prefix}.{name} must be a non-empty string")
    for name in _SCENE_LIST_FIELDS:
        value = getattr(scene, name)
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            errors.append(f"{prefix}.{name} must contain only non-empty strings")
    if not scene.factual_basis:
        errors.append(f"{prefix}.factual_basis must contain at least one supported fact")
    if not scene.restrictions:
        errors.append(f"{prefix}.restrictions must not be empty")
    serialized_text = json.dumps(asdict(scene), ensure_ascii=False).casefold()
    for term in _FORBIDDEN_PRODUCTION_TERMS:
        if term in serialized_text:
            errors.append(f"{prefix} must not contain downstream production decision '{term}'")
    return errors


_PLAN_FIELDS = tuple(ScenePlan.__dataclass_fields__)
_SCENE_FIELDS = tuple(Scene.__dataclass_fields__)
_PLAN_STRING_FIELDS = ("scene_plan_id", "creative_direction_id", "content_idea_id", "overall_story_summary")
_SCENE_STRING_FIELDS = (
    "scene_id", "scene_name", "story_purpose", "scene_summary", "main_subject", "environment",
    "creative_interpretation", "time_of_day", "weather", "mood", "lighting_direction",
    "transition_to_next_scene",
)
_SCENE_LIST_FIELDS = (
    "supporting_subjects", "factual_basis", "scene_dependencies", "reusable_asset_ids",
    "continuity_notes", "restrictions",
)
_FORBIDDEN_PRODUCTION_TERMS = (
    "camera angle", "camera height", "camera movement", "lens", "focal length",
    "shot type", "shot size", "framing", "composition", "depth of field",
    "camera motion", "aperture", "shutter speed", "lighting setup", "aspect ratio",
    "prompt wording", "image generation parameter", "rendering setting", "vfx",
)
