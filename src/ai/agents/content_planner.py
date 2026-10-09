"""OpenAI-backed generation of grounded, production-ready content plans."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.content.schema import ContentPlan
from src.content.storage import save_content_plan
from src.core.logger import get_logger
from src.knowledge.schema import ProjectKnowledge
from src.strategy.schema import MarketingStrategy
from src.utils.config import REPORTS_OUTPUT_DIRECTORY

DEFAULT_MODEL = "gpt-4o-mini"


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_IDEA_SCHEMA = _object({
    "unique_id": {"type": "string"}, "title": {"type": "string"}, "story": {"type": "string"},
    "purpose": {"type": "string"}, "target_audience": {"type": "string"}, "emotion": {"type": "string"},
    "marketing_goal": {"type": "string"}, "recommended_platform": {"type": "string"},
    "recommended_format": {"type": "string"},
    "image_orientation": {"type": "string", "enum": ["Square", "Portrait", "Landscape"]},
    "priority": {"type": "string"}, "main_subject": {"type": "string"},
    "supporting_subjects": {"type": "array", "items": {"type": "string"}},
    "environment": {"type": "string"}, "time_of_day": {"type": "string"}, "weather": {"type": "string"},
    "mood": {"type": "string"}, "color_palette": {"type": "string"}, "camera_style": {"type": "string"},
    "recommended_lens": {"type": "string"}, "composition": {"type": "string"},
    "visual_keywords": {"type": "array", "items": {"type": "string"}},
    "future_asset_type": {"type": "string", "enum": [
        "Hero Image", "Instagram Carousel", "Instagram Reel", "Facebook Post",
        "Website Banner", "YouTube Thumbnail", "LinkedIn Graphic",
    ]},
    "required_source_asset_ids": {"type": "array", "items": {"type": "string"}},
    "available_source_asset_ids": {"type": "array", "items": {"type": "string"}},
    "selected_source_asset_ids": {"type": "array", "items": {"type": "string"}},
    "source_support_status": {"type": "string", "enum": ["fully_supported", "partially_supported", "text_only", "unavailable"]},
    "visual_evidence": {"type": "array", "items": {"type": "string"}},
    "text_evidence": {"type": "array", "items": {"type": "string"}},
    "feasible_platforms": {"type": "array", "items": {"type": "string"}},
    "feasible_formats": {"type": "array", "items": {"type": "string"}},
})
CONTENT_PLAN_JSON_SCHEMA = _object({
    "pillars": {"type": "array", "items": _object({
        "name": {"type": "string"},
        "content_ideas": {"type": "array", "items": _IDEA_SCHEMA},
    })},
})


class ContentPlanner:
    """Create visual story decisions from validated knowledge and strategy artifacts."""

    def __init__(self, model: str | None = None) -> None:
        self.logger = get_logger(__name__)
        self.model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

    def run(self, knowledge_path: Path, strategy_path: Path, visual_inventory_path: Path | None = None,
            performance_learning_path: Path | None = None) -> Path | None:
        """Read inputs, generate a validated content plan, and persist it."""
        self.logger.info("Reading knowledge and strategy...")
        try:
            knowledge = ProjectKnowledge.from_json(knowledge_path.read_text(encoding="utf-8"))
            errors = knowledge.validate()
            if errors:
                raise ValueError("; ".join(errors))
            strategy = MarketingStrategy.from_json(strategy_path.read_text(encoding="utf-8"))
            visual_inventory = (
                json.loads(visual_inventory_path.read_text(encoding="utf-8"))
                if visual_inventory_path else None
            )
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            self.logger.error("Could not read valid Content Planner input: %s", error)
            return None

        api_key = self._load_api_key()
        if not api_key:
            return None
        self.logger.info("Generating content plan...")
        try:
            learning=None
            if performance_learning_path and performance_learning_path.is_file():
                from src.performance.integration import content_planner_context
                learning=content_planner_context(json.loads(performance_learning_path.read_text(encoding="utf-8")))
            response_text = self._request_plan(knowledge.to_dict(), strategy.to_dict(), api_key, visual_inventory, learning)
            plan = ContentPlan.from_json(response_text)
            if visual_inventory is not None:
                _rank_and_assign_semantic_assets(plan, visual_inventory)
                _repair_inventory_grounding(plan, visual_inventory)
                _validate_inventory_grounding(plan, visual_inventory)
                plan, availability = _remove_unavailable_ideas(plan)
                _save_availability_report(availability, knowledge_path.stem)
        except Exception as error:
            self.logger.error("Content Planner API request or response validation failed: %s", error)
            return None
        try:
            output_path = save_content_plan(plan, f"{knowledge_path.stem}-content-plan")
        except (OSError, ValueError) as error:
            self.logger.error("Could not save content plan JSON: %s", error)
            return None
        self.logger.info("Content plan saved.")
        return output_path

    def _load_api_key(self) -> str | None:
        try:
            from dotenv import load_dotenv
        except ImportError:
            self.logger.error("Missing dependency: install packages with 'python -m pip install -r requirements.txt'.")
            return None
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self.logger.error("OPENAI_API_KEY is not set. Add it to the local .env file.")
            return None
        return api_key

    def _request_plan(self, knowledge: dict[str, Any], strategy: dict[str, Any], api_key: str, visual_inventory: dict[str, Any] | None = None,
                      performance_learning: dict[str, Any] | None = None) -> str:
        from openai import OpenAI

        request_input = json.dumps({"knowledge": knowledge, "marketing_strategy": strategy, "visual_inventory": visual_inventory, "performance_learning": performance_learning}, ensure_ascii=False)
        response = OpenAI(api_key=api_key).responses.create(
            model=self.model,
            instructions="""You are simultaneously a creative director, luxury brand strategist, real-estate marketing director, and social media content director.

Create a production-ready content plan using only supplied knowledge, strategy, and authentic visual_inventory. The source material defines the maximum available content. Create ideas only when existing approved asset IDs and factual text can produce them. Never request or imagine a missing project visual, person, lifestyle situation, viewpoint, room, amenity, or feature.

Copy authentic asset IDs exactly into required_source_asset_ids, available_source_asset_ids, and selected_source_asset_ids. Every ID must occur in this project's visual_inventory; never copy an asset from another project. Explain visual_evidence and text_evidence. Set feasible platforms and formats only when the approved assets can support them. Prefer fully_supported. Use partially_supported only when existing assets plus factual text overlays are sufficient. text_only may use approved logos, templates, maps, diagrams, masterplans, floorplans, and factual source text. Mark impossible ideas unavailable; they will be skipped and must not continue to production.

Use semantic asset descriptions as hard visual boundaries. Never claim an asset shows a person, interior, amenity, interview, testimonial, statistic, or feature unless its semantic record visibly confirms it. Do not use unknown or review-required assets as proof. Do not propose video when only still images are available. Python will make the final deterministic asset selection; never invent an ID. Optional performance_learning is advisory and account-specific; use confident format or CTA associations only as tie-breakers. It cannot add facts, override evidence, or mandate repetition.

Create only relevant content pillars, with multiple detailed ideas per pillar. Each story must be a cinematic visual narrative that could open a luxury commercial, not a generic instruction. Describe WHAT visual story should be created. Do not write image prompts, captions, images, videos, hashtags, calls to action, or text outside the required JSON. Return valid JSON only, exactly matching the supplied schema.""",
            input=request_input,
            text={"format": {"type": "json_schema", "name": "content_plan", "strict": True, "schema": CONTENT_PLAN_JSON_SCHEMA}},
        )
        if not response.output_text:
            raise ValueError("The API returned no JSON output")
        return response.output_text


def _inventory_asset_ids(inventory: dict[str, Any]) -> set[str]:
    return set(inventory.get("all_source_asset_ids", []))


def _validate_inventory_grounding(plan: ContentPlan, inventory: dict[str, Any]) -> None:
    allowed = _inventory_asset_ids(inventory)
    for pillar in plan.pillars:
        for idea in pillar.content_ideas:
            referenced = set(idea.required_source_asset_ids) | set(idea.available_source_asset_ids) | set(idea.selected_source_asset_ids)
            unknown = sorted(referenced - allowed)
            if unknown:
                raise ValueError(f"Content idea {idea.unique_id} references unknown source asset IDs: {', '.join(unknown)}")
            if idea.source_support_status in {"fully_supported", "partially_supported"} and not idea.available_source_asset_ids:
                raise ValueError(f"Content idea {idea.unique_id} lacks approved visual support")


def _repair_inventory_grounding(plan: ContentPlan, inventory: dict[str, Any]) -> dict[str, Any]:
    """Remove cross-project/hallucinated IDs before strict validation."""
    allowed = _inventory_asset_ids(inventory)
    removed: dict[str, list[str]] = {}
    for pillar in plan.pillars:
        for idea in pillar.content_ideas:
            rejected: list[str] = []
            for field_name in (
                "required_source_asset_ids", "available_source_asset_ids", "selected_source_asset_ids",
            ):
                original = getattr(idea, field_name)
                valid = list(dict.fromkeys(asset_id for asset_id in original if asset_id in allowed))
                rejected.extend(asset_id for asset_id in original if asset_id not in allowed)
                setattr(idea, field_name, valid)
            if rejected:
                removed[idea.unique_id] = list(dict.fromkeys(rejected))
            has_visual = bool(idea.available_source_asset_ids or idea.selected_source_asset_ids)
            if not has_visual and idea.source_support_status in {"fully_supported", "partially_supported"}:
                idea.source_support_status = "text_only" if idea.text_evidence else "unavailable"
    return {"removed_asset_ids": removed}


def _rank_and_assign_semantic_assets(plan: ContentPlan, inventory: dict[str, Any]) -> None:
    """Select current-project assets by visible semantic compatibility, never filenames."""
    if inventory.get("inventory_type") != "semantic":
        return
    assets = _semantic_assets(inventory)
    for pillar in plan.pillars:
        for idea in pillar.content_ideas:
            text = " ".join([idea.title, idea.story, idea.main_subject, idea.environment, *idea.supporting_subjects, *idea.visual_keywords]).casefold()
            required_types, requires_people, unsupported_format = _visual_requirements(text, idea.recommended_format, idea.future_asset_type)
            candidates = []
            for asset in assets:
                if required_types and asset.get("asset_type") not in required_types:
                    continue
                if requires_people and not asset.get("contains_people", False):
                    continue
                candidates.append((_semantic_score(asset, idea, text), asset))
            candidates.sort(key=lambda item: (-item[0], item[1]["asset_id"]))
            selected = [asset for _, asset in candidates[:3]]
            if unsupported_format:
                idea.recommended_format = "Carousel"
                idea.future_asset_type = "Instagram Carousel"
                idea.feasible_formats = [item for item in idea.feasible_formats if "reel" not in item.casefold() and "video" not in item.casefold()]
            if selected:
                ids = [asset["asset_id"] for asset in selected]
                idea.required_source_asset_ids = ids
                idea.available_source_asset_ids = ids
                idea.selected_source_asset_ids = ids
                idea.source_support_status = "fully_supported" if len(selected) >= 2 else "partially_supported"
                idea.visual_evidence = [
                    f"{asset['asset_id']}: semantic match ({asset.get('asset_type')}, confidence {asset.get('confidence', 0):.2f})"
                    for asset in selected
                ]
            else:
                idea.required_source_asset_ids = []
                idea.available_source_asset_ids = []
                idea.selected_source_asset_ids = []
                inappropriate_text_story = requires_people or bool(required_types & {"interior", "swimming_pool", "lifestyle"})
                idea.source_support_status = "unavailable" if inappropriate_text_story or not idea.text_evidence else "text_only"


def _semantic_assets(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    assets: dict[str, dict[str, Any]] = {}
    for field, values in inventory.items():
        if not field.startswith("available_") or field == "available_text_facts" or not isinstance(values, list):
            continue
        for asset in values:
            if not isinstance(asset, dict) or not asset.get("asset_id"):
                continue
            if asset.get("analysis_status") in {"failed", "review_required", "unsuitable"} or asset.get("asset_type") in {"unknown", "unsuitable"}:
                continue
            if asset.get("marketing_suitability") in {"review_required", "unsuitable"}:
                continue
            assets[asset["asset_id"]] = asset
    return list(assets.values())


def _visual_requirements(text: str, recommended_format: str, future_asset_type: str) -> tuple[set[str], bool, bool]:
    mapping = (
        (("interior", "living room", "bedroom", "kitchen", "bathroom"), {"interior", "residential_space", "commercial_space"}),
        (("pool", "swimming"), {"swimming_pool"}), (("clubhouse",), {"clubhouse", "amenity"}),
        (("garden", "landscape"), {"garden_landscape", "amenity"}), (("floor plan", "floorplan"), {"floorplan"}),
        (("masterplan", "master plan"), {"masterplan", "site_plan"}), (("location map",), {"location_map"}),
        (("diagram", "infographic", "chart"), {"diagram", "infographic"}), (("construction",), {"construction_progress"}),
        (("exterior", "facade", "façade", "villa", "architecture"), {"exterior", "aerial_view", "architectural_detail", "residential_space"}),
    )
    required = next((types for terms, types in mapping if any(term in text for term in terms)), set())
    people = any(term in text for term in ("family", "people", "resident", "testimonial", "interview", "dining", "lifestyle"))
    if people and not required:
        required = {"lifestyle"}
    format_text = f"{recommended_format} {future_asset_type}".casefold()
    video = "video" in format_text or "reel" in format_text
    return required, people, video


def _semantic_score(asset: dict[str, Any], idea: Any, text: str) -> int:
    suitability = {"hero_ready": 50, "feed_ready": 42, "carousel_ready": 40, "story_ready": 38, "banner_ready": 38, "information_graphic_ready": 40, "usable_after_enhancement": 25, "limited_use": 10}
    quality = int(asset.get("image_quality", {}).get("score", asset.get("quality_score", 0)))
    score = suitability.get(asset.get("marketing_suitability"), 0) + quality + int(float(asset.get("confidence", 0)) * 30)
    features = " ".join(asset.get("visible_project_features", [])).casefold()
    score += sum(5 for token in set(text.split()) if len(token) > 4 and token in features)
    if idea.recommended_platform in asset.get("recommended_platforms", []): score += 15
    orientation = str(asset.get("orientation", "")).casefold()
    if idea.image_orientation.casefold() == orientation: score += 10
    crop = asset.get("safe_crop_assessment", {}).get("level")
    score += {"flexible": 10, "moderately_flexible": 6, "limited": 2}.get(crop, 0)
    return score


def _remove_unavailable_ideas(plan: ContentPlan) -> tuple[ContentPlan, dict[str, Any]]:
    counts = {"fully_supported": 0, "partially_supported": 0, "text_only": 0, "skipped_unavailable": 0}
    skipped = []
    for pillar in plan.pillars:
        feasible = []
        for idea in pillar.content_ideas:
            if idea.source_support_status == "unavailable":
                counts["skipped_unavailable"] += 1
                skipped.append({"content_idea_id": idea.unique_id, "missing_visual_requirement": idea.main_subject})
            else:
                counts[idea.source_support_status] += 1
                feasible.append(idea)
        pillar.content_ideas = feasible
    plan.pillars = [pillar for pillar in plan.pillars if pillar.content_ideas]
    return plan, {"summary": counts, "skipped_items": skipped}


def _save_availability_report(report: dict[str, Any], project_name: str) -> Path:
    REPORTS_OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = REPORTS_OUTPUT_DIRECTORY / f"{project_name}-content-availability.json"
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination
