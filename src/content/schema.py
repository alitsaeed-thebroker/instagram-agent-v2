"""Validated JSON contract for detailed, production-ready content plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any
from src.publication import normalize_publication_type


IMAGE_ORIENTATIONS = {"Square", "Portrait", "Landscape"}
FUTURE_ASSET_TYPES = {
    "Hero Image", "Instagram Carousel", "Instagram Story", "Instagram Reel", "Facebook Post",
    "Website Banner", "YouTube Thumbnail", "LinkedIn Graphic",
}
SOURCE_SUPPORT_STATUSES = {"fully_supported", "partially_supported", "text_only", "unavailable", "skipped_unavailable"}


@dataclass
class ContentIdea:
    unique_id: str
    title: str
    story: str
    purpose: str
    target_audience: str
    emotion: str
    marketing_goal: str
    recommended_platform: str
    recommended_format: str
    image_orientation: str
    priority: str
    main_subject: str
    supporting_subjects: list[str]
    environment: str
    time_of_day: str
    weather: str
    mood: str
    color_palette: str
    camera_style: str
    recommended_lens: str
    composition: str
    visual_keywords: list[str]
    future_asset_type: str
    required_source_asset_ids: list[str] = field(default_factory=list)
    available_source_asset_ids: list[str] = field(default_factory=list)
    selected_source_asset_ids: list[str] = field(default_factory=list)
    source_support_status: str = "text_only"
    visual_evidence: list[str] = field(default_factory=list)
    text_evidence: list[str] = field(default_factory=list)
    feasible_platforms: list[str] = field(default_factory=list)
    feasible_formats: list[str] = field(default_factory=list)
    selected_format: str | None = None
    planned_publication: dict[str, Any] | None = None
    public_copy: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentPillar:
    name: str
    content_ideas: list[ContentIdea] = field(default_factory=list)


@dataclass
class ContentPlan:
    """A content production plan grounded in project knowledge and strategy."""

    pillars: list[ContentPillar] = field(default_factory=list)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.pillars, list):
            return ["pillars must be a list of objects"]
        ids: set[str] = set()
        for pillar_index, pillar in enumerate(self.pillars):
            prefix = f"pillars[{pillar_index}]"
            if not isinstance(pillar, ContentPillar):
                errors.append(f"{prefix} must be an object")
                continue
            if not isinstance(pillar.name, str) or not pillar.name.strip():
                errors.append(f"{prefix}.name must be a non-empty string")
            if not isinstance(pillar.content_ideas, list):
                errors.append(f"{prefix}.content_ideas must be a list of objects")
                continue
            for idea_index, idea in enumerate(pillar.content_ideas):
                idea_prefix = f"{prefix}.content_ideas[{idea_index}]"
                if not isinstance(idea, ContentIdea):
                    errors.append(f"{idea_prefix} must be an object")
                    continue
                if not all(isinstance(getattr(idea, name), str) for name in _IDEA_STRING_FIELDS):
                    errors.append(f"{idea_prefix} text fields must be strings")
                elif not all(getattr(idea, name).strip() for name in _IDEA_STRING_FIELDS):
                    errors.append(f"{idea_prefix} text fields must not be empty")
                if not isinstance(idea.supporting_subjects, list) or not all(isinstance(item, str) and item.strip() for item in idea.supporting_subjects):
                    errors.append(f"{idea_prefix}.supporting_subjects must contain only non-empty strings")
                if not isinstance(idea.visual_keywords, list) or not idea.visual_keywords or not all(isinstance(item, str) and item.strip() for item in idea.visual_keywords):
                    errors.append(f"{idea_prefix}.visual_keywords must contain non-empty strings")
                if isinstance(idea.unique_id, str):
                    if idea.unique_id in ids:
                        errors.append(f"{idea_prefix}.unique_id must be unique")
                    ids.add(idea.unique_id)
                if idea.image_orientation not in IMAGE_ORIENTATIONS:
                    errors.append(f"{idea_prefix}.image_orientation must be Square, Portrait, or Landscape")
                if idea.future_asset_type not in FUTURE_ASSET_TYPES:
                    errors.append(f"{idea_prefix}.future_asset_type is not supported")
                if idea.source_support_status not in SOURCE_SUPPORT_STATUSES:
                    errors.append(f"{idea_prefix}.source_support_status is not supported")
                for name in _SOURCE_LIST_FIELDS:
                    value = getattr(idea, name)
                    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                        errors.append(f"{idea_prefix}.{name} must contain only non-empty strings")
                if idea.source_support_status in {"fully_supported", "partially_supported"} and not idea.available_source_asset_ids:
                    errors.append(f"{idea_prefix}.available_source_asset_ids is required for visually supported ideas")
                if idea.selected_format is not None:
                    try:selected=normalize_publication_type(idea.selected_format)
                    except ValueError as error:errors.append(f"{idea_prefix}.selected_format: {error}");selected=None
                    intent=idea.planned_publication or {}
                    if intent.get("publication_type")!=selected:errors.append(f"{idea_prefix}.planned_publication does not match selected_format")
                    if selected=="story" and not any(str(x).casefold() in {"story","instagram story","instagram_story"} for x in idea.feasible_formats):errors.append(f"{idea_prefix}.Story was selected but is not feasible")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContentPlan":
        if isinstance(data, dict) and isinstance(data.get("content_ideas"), list):
            return cls._from_asset_first(data)
        if not isinstance(data, dict) or set(data) != {"pillars"}:
            raise ValueError("Content plan JSON must contain only a pillars field")
        raw_pillars = data["pillars"]
        if not isinstance(raw_pillars, list):
            raise ValueError("pillars must be a list of objects")
        try:
            pillars = []
            for pillar in raw_pillars:
                if not isinstance(pillar, dict) or set(pillar) != set(_PILLAR_FIELDS):
                    raise ValueError("Content plan JSON has unexpected or missing pillar fields")
                ideas = pillar["content_ideas"]
                if not isinstance(ideas, list) or any(not isinstance(idea, dict) for idea in ideas):
                    raise ValueError("Content plan JSON has unexpected or missing content idea fields")
                normalized_ideas = []
                for idea in ideas:
                    normalized = dict(idea)
                    for name, default in _SOURCE_FIELD_DEFAULTS.items():
                        normalized.setdefault(name, list(default) if isinstance(default, list) else default)
                    if set(normalized) != set(_IDEA_FIELDS):
                        raise ValueError("Content plan JSON has unexpected or missing content idea fields")
                    normalized_ideas.append(ContentIdea(**normalized))
                pillars.append(ContentPillar(name=pillar["name"], content_ideas=normalized_ideas))
            plan = cls(pillars=pillars)
        except (KeyError, TypeError) as error:
            raise ValueError("Content plan JSON has an invalid structure") from error
        errors = plan.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return plan

    @classmethod
    def _from_asset_first(cls, data: dict[str, Any]) -> "ContentPlan":
        """Adapt Phase 9.1 output for downstream modules without weakening its file contract."""
        grouped: dict[str, list[ContentIdea]] = {}
        for raw in data["content_ideas"]:
            if not isinstance(raw, dict):
                raise ValueError("content_ideas must contain objects")
            formats = raw.get("feasible_formats", [])
            selected = raw.get("selected_source_asset_ids", [])
            status = raw.get("source_support_status", "unavailable")
            idea = ContentIdea(
                unique_id=str(raw.get("content_idea_id", "")), title=str(raw.get("title", "")),
                story=str(raw.get("concept_summary", "")), purpose=str(raw.get("content_objective", "")),
                target_audience=str(raw.get("target_persona", "")), emotion="Evidence-led confidence",
                marketing_goal=str(raw.get("funnel_stage", "")), recommended_platform=str((raw.get("feasible_platforms") or ["Instagram"])[0]),
                recommended_format=str(formats[0] if formats else "Instagram Single Image"),
                image_orientation=str(raw.get("orientation", "Square")).title(), priority="High" if float(raw.get("overall_confidence", 0)) >= .85 else "Medium",
                main_subject=str(raw.get("title", "")), supporting_subjects=list(raw.get("message_hierarchy", [])),
                environment="Approved source asset", time_of_day="As visible in source", weather="As visible in source",
                mood="Source-authentic", color_palette="Preserve authentic source", camera_style="Deferred to Shot Planner",
                recommended_lens="Deferred to Shot Planner", composition="Deferred to Shot Planner",
                visual_keywords=[str(raw.get("selected_opportunity_id", "authentic source"))],
                future_asset_type=_legacy_asset_type(formats), required_source_asset_ids=list(selected),
                available_source_asset_ids=list(selected), selected_source_asset_ids=list(selected), source_support_status=status,
                visual_evidence=list(raw.get("visual_evidence", [])), text_evidence=list(raw.get("factual_evidence", [])),
                feasible_platforms=list(raw.get("feasible_platforms", [])), feasible_formats=list(formats),
                selected_format=raw.get("selected_format"), planned_publication=raw.get("planned_publication"), public_copy=dict(raw.get("public_copy") or {}),
            )
            grouped.setdefault(str(raw.get("pillar_id", "Asset-First")), []).append(idea)
        plan = cls([ContentPillar(name=name, content_ideas=ideas) for name, ideas in grouped.items()])
        errors = plan.validate()
        if errors: raise ValueError("; ".join(errors))
        return plan

    @classmethod
    def from_json(cls, payload: str) -> "ContentPlan":
        try:
            return cls.from_dict(json.loads(payload))
        except json.JSONDecodeError as error:
            raise ValueError("Content plan JSON is invalid") from error


_PILLAR_FIELDS = tuple(ContentPillar.__dataclass_fields__)
_IDEA_FIELDS = tuple(ContentIdea.__dataclass_fields__)
_IDEA_STRING_FIELDS = (
    "unique_id", "title", "story", "purpose", "target_audience", "emotion",
    "marketing_goal", "recommended_platform", "recommended_format", "image_orientation",
    "priority", "main_subject", "environment", "time_of_day", "weather", "mood",
    "color_palette", "camera_style", "recommended_lens", "composition", "future_asset_type",
)
_SOURCE_LIST_FIELDS = (
    "required_source_asset_ids", "available_source_asset_ids", "selected_source_asset_ids", "visual_evidence",
    "text_evidence", "feasible_platforms", "feasible_formats",
)
_SOURCE_FIELD_DEFAULTS = {name: [] for name in _SOURCE_LIST_FIELDS} | {"source_support_status": "text_only", "selected_format": None, "planned_publication": None, "public_copy": {}}


def _legacy_asset_type(formats: list[str]) -> str:
    text = " ".join(formats).casefold()
    if "story" in text: return "Instagram Story"
    if "carousel" in text: return "Instagram Carousel"
    if "website" in text or "banner" in text: return "Website Banner"
    if "linkedin" in text: return "LinkedIn Graphic"
    if "facebook" in text: return "Facebook Post"
    return "Hero Image"
