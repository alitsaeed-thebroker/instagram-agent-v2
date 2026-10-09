"""Validated JSON contract for the marketing strategy artifact."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any


@dataclass
class BuyerPersona:
    """A concise, evidence-grounded buyer segment."""

    name: str = ""
    description: str = ""
    motivations: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)


@dataclass
class MarketingStrategy:
    """The complete structured marketing recommendation for one project."""

    project_summary: str = ""
    target_audience: list[str] = field(default_factory=list)
    buyer_personas: list[BuyerPersona] = field(default_factory=list)
    primary_marketing_angle: str = ""
    secondary_marketing_angles: list[str] = field(default_factory=list)
    emotional_triggers: list[str] = field(default_factory=list)
    key_selling_points: list[str] = field(default_factory=list)
    recommended_campaign_themes: list[str] = field(default_factory=list)
    recommended_visual_style: str = ""
    brand_tone_of_voice: str = ""
    recommended_content_pillars: list[str] = field(default_factory=list)
    recommended_social_media_platforms: list[str] = field(default_factory=list)
    recommended_posting_frequency: str = ""
    calls_to_action: list[str] = field(default_factory=list)

    def validate(self) -> list[str]:
        """Return contract errors; empty recommendations are permitted when unsupported."""
        errors: list[str] = []
        for field_name in _STRING_FIELDS:
            if not isinstance(getattr(self, field_name), str):
                errors.append(f"{field_name} must be a string")
        for field_name in _STRING_LIST_FIELDS:
            value = getattr(self, field_name)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                errors.append(f"{field_name} must contain only strings")
        if not isinstance(self.buyer_personas, list):
            errors.append("buyer_personas must be a list of objects")
            return errors
        for index, persona in enumerate(self.buyer_personas):
            if not isinstance(persona, BuyerPersona):
                errors.append(f"buyer_personas[{index}] must be an object")
                continue
            if not all(isinstance(value, str) for value in (persona.name, persona.description)):
                errors.append(f"buyer_personas[{index}] name and description must be strings")
            if (
                not isinstance(persona.motivations, list)
                or not isinstance(persona.concerns, list)
                or not all(isinstance(item, str) for item in persona.motivations + persona.concerns)
            ):
                errors.append(f"buyer_personas[{index}] motivations and concerns must contain only strings")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MarketingStrategy":
        if not isinstance(data, dict):
            raise ValueError("Strategy JSON must be an object")
        expected = set(cls.__dataclass_fields__)
        if set(data) != expected:
            missing = sorted(expected - set(data))
            extra = sorted(set(data) - expected)
            details = []
            if missing:
                details.append("missing fields: " + ", ".join(missing))
            if extra:
                details.append("unexpected fields: " + ", ".join(extra))
            raise ValueError("Strategy JSON has " + "; ".join(details))
        personas = data["buyer_personas"]
        if not isinstance(personas, list) or not all(isinstance(item, dict) for item in personas):
            raise ValueError("buyer_personas must be a list of objects")
        try:
            strategy = cls(
                **{name: data[name] for name in expected - {"buyer_personas"}},
                buyer_personas=[BuyerPersona(**persona) for persona in personas],
            )
        except TypeError as error:
            raise ValueError("Strategy JSON has an invalid structure") from error
        errors = strategy.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return strategy

    @classmethod
    def from_json(cls, payload: str) -> "MarketingStrategy":
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("Strategy JSON is invalid") from error
        return cls.from_dict(data)


_STRING_FIELDS = (
    "project_summary", "primary_marketing_angle", "recommended_visual_style",
    "brand_tone_of_voice", "recommended_posting_frequency",
)

_STRING_LIST_FIELDS = (
    "target_audience", "secondary_marketing_angles", "emotional_triggers",
    "key_selling_points", "recommended_campaign_themes",
    "recommended_content_pillars", "recommended_social_media_platforms", "calls_to_action",
)
