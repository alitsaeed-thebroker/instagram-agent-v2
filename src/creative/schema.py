"""Validated JSON contract for project-grounded creative directions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any


@dataclass
class VisualIdentity:
    """Separate source-supported visual elements from creative interpretation."""

    factual_project_elements: list[str] = field(default_factory=list)
    creative_interpretation: str = ""
    palette_intent: list[str] = field(default_factory=list)
    texture_language: list[str] = field(default_factory=list)


@dataclass
class EmotionalDirection:
    primary_emotion: str = ""
    supporting_emotions: list[str] = field(default_factory=list)
    desired_response: str = ""


@dataclass
class StorytellingDirection:
    premise: str = ""
    narrative_arc: list[str] = field(default_factory=list)
    story_boundaries: list[str] = field(default_factory=list)


@dataclass
class CreativeDirection:
    """Senior creative decisions for exactly one content idea."""

    creative_direction_id: str
    content_idea_id: str
    campaign_concept: str
    visual_identity: VisualIdentity
    emotional_direction: EmotionalDirection
    storytelling_direction: StorytellingDirection
    brand_constraints: list[str]
    luxury_level: str
    realism_level: str
    audience_perception: str
    artistic_vision: str
    reference_asset_ids: list[str]
    consistency_approval_criteria: list[str]


@dataclass
class CreativeDirectionPlan:
    """Complete collection of creative directions for selected content ideas."""

    creative_directions: list[CreativeDirection] = field(default_factory=list)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.creative_directions, list):
            return ["creative_directions must be a list of objects"]
        direction_ids: set[str] = set()
        idea_ids: set[str] = set()
        for index, direction in enumerate(self.creative_directions):
            prefix = f"creative_directions[{index}]"
            if not isinstance(direction, CreativeDirection):
                errors.append(f"{prefix} must be an object")
                continue
            for name in _DIRECTION_STRING_FIELDS:
                value = getattr(direction, name)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{prefix}.{name} must be a non-empty string")
            for name in _DIRECTION_LIST_FIELDS:
                value = getattr(direction, name)
                if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                    errors.append(f"{prefix}.{name} must contain only non-empty strings")
            if direction.creative_direction_id in direction_ids:
                errors.append(f"{prefix}.creative_direction_id must be unique")
            direction_ids.add(direction.creative_direction_id)
            if direction.content_idea_id in idea_ids:
                errors.append(f"{prefix}.content_idea_id must be unique")
            idea_ids.add(direction.content_idea_id)
            errors.extend(_validate_visual_identity(direction.visual_identity, prefix))
            errors.extend(_validate_emotional_direction(direction.emotional_direction, prefix))
            errors.extend(_validate_storytelling_direction(direction.storytelling_direction, prefix))
            if not direction.consistency_approval_criteria:
                errors.append(f"{prefix}.consistency_approval_criteria must not be empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CreativeDirectionPlan":
        if not isinstance(data, dict) or set(data) != {"creative_directions"}:
            raise ValueError("Creative direction JSON must contain only a creative_directions field")
        raw_directions = data["creative_directions"]
        if not isinstance(raw_directions, list):
            raise ValueError("creative_directions must be a list of objects")
        directions: list[CreativeDirection] = []
        try:
            for raw in raw_directions:
                if not isinstance(raw, dict) or set(raw) != set(_DIRECTION_FIELDS):
                    raise ValueError("Creative direction JSON has unexpected or missing fields")
                visual = raw["visual_identity"]
                emotional = raw["emotional_direction"]
                storytelling = raw["storytelling_direction"]
                if not isinstance(visual, dict) or set(visual) != set(VisualIdentity.__dataclass_fields__):
                    raise ValueError("visual_identity has unexpected or missing fields")
                if not isinstance(emotional, dict) or set(emotional) != set(EmotionalDirection.__dataclass_fields__):
                    raise ValueError("emotional_direction has unexpected or missing fields")
                if not isinstance(storytelling, dict) or set(storytelling) != set(StorytellingDirection.__dataclass_fields__):
                    raise ValueError("storytelling_direction has unexpected or missing fields")
                directions.append(CreativeDirection(
                    **{name: raw[name] for name in _DIRECTION_FIELDS if name not in _NESTED_FIELDS},
                    visual_identity=VisualIdentity(**visual),
                    emotional_direction=EmotionalDirection(**emotional),
                    storytelling_direction=StorytellingDirection(**storytelling),
                ))
        except (KeyError, TypeError) as error:
            raise ValueError("Creative direction JSON has an invalid structure") from error
        plan = cls(creative_directions=directions)
        errors = plan.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return plan

    @classmethod
    def from_json(cls, payload: str) -> "CreativeDirectionPlan":
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("Creative direction JSON is invalid") from error
        return cls.from_dict(data)


def _validate_visual_identity(value: object, prefix: str) -> list[str]:
    if not isinstance(value, VisualIdentity):
        return [f"{prefix}.visual_identity must be an object"]
    errors = _validate_string_lists(value, ("factual_project_elements", "palette_intent", "texture_language"), f"{prefix}.visual_identity")
    if not isinstance(value.creative_interpretation, str) or not value.creative_interpretation.strip():
        errors.append(f"{prefix}.visual_identity.creative_interpretation must be a non-empty string")
    return errors


def _validate_emotional_direction(value: object, prefix: str) -> list[str]:
    if not isinstance(value, EmotionalDirection):
        return [f"{prefix}.emotional_direction must be an object"]
    errors = _validate_string_lists(value, ("supporting_emotions",), f"{prefix}.emotional_direction")
    for name in ("primary_emotion", "desired_response"):
        item = getattr(value, name)
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{prefix}.emotional_direction.{name} must be a non-empty string")
    return errors


def _validate_storytelling_direction(value: object, prefix: str) -> list[str]:
    if not isinstance(value, StorytellingDirection):
        return [f"{prefix}.storytelling_direction must be an object"]
    errors = _validate_string_lists(value, ("narrative_arc", "story_boundaries"), f"{prefix}.storytelling_direction")
    if not isinstance(value.premise, str) or not value.premise.strip():
        errors.append(f"{prefix}.storytelling_direction.premise must be a non-empty string")
    return errors


def _validate_string_lists(value: object, names: tuple[str, ...], prefix: str) -> list[str]:
    errors: list[str] = []
    for name in names:
        items = getattr(value, name)
        if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
            errors.append(f"{prefix}.{name} must contain only non-empty strings")
    return errors


_DIRECTION_FIELDS = tuple(CreativeDirection.__dataclass_fields__)
_NESTED_FIELDS = {"visual_identity", "emotional_direction", "storytelling_direction"}
_DIRECTION_STRING_FIELDS = (
    "creative_direction_id", "content_idea_id", "campaign_concept", "luxury_level",
    "realism_level", "audience_perception", "artistic_vision",
)
_DIRECTION_LIST_FIELDS = ("brand_constraints", "reference_asset_ids", "consistency_approval_criteria")
