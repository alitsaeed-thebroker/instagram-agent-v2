"""Deterministic source-asset framing planner with optional AI recommendations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.content.schema import ContentPlan
from src.creative.schema import CreativeDirectionPlan
from src.core.logger import get_logger
from src.knowledge.schema import ProjectKnowledge
from src.ai.agents.creative_context import creative_knowledge_context
from src.scenes.schema import ScenePlanCollection
from src.shots.schema import ASPECT_RATIOS, FUTURE_PLATFORMS, FramingPlan, SceneFramingGroup, ShotPlan, ShotPlanCollection, ShotPlanSummary, SkippedScene
from src.shots.storage import save_shot_plans
from src.utils.config import PROJECT_ROOT

DEFAULT_MODEL = "gpt-4o-mini"
_RECOMMENDATION_FIELDS = {
    "layout_type", "crop_strategy", "safe_zoom", "aspect_ratios", "text_safe_area",
    "logo_safe_area", "enhancement_notes", "platforms",
}
_FORBIDDEN_AI_FIELDS = {
    "camera_angle", "camera_height", "lens", "camera_motion", "shot_type", "new_viewpoint",
    "depth_of_field", "generated_scene_description", "invented_project_subject", "ai_image_prompt",
    "negative_prompt", "provider_name", "generation_parameters", "source_asset_ids",
    "shot_plan_id", "scene_plan_id", "creative_direction_id", "content_idea_id", "scene_id",
    "shot_id", "framing_plan_id", "sequence", "total_count",
}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_AI_RECOMMENDATION_SCHEMA = _object({
    "layout_type": {"type": "string"}, "crop_strategy": {"type": "string"},
    "safe_zoom": {"type": "string"},
    "aspect_ratios": {"type": "array", "items": {"type": "string", "enum": ["1:1", "4:5", "9:16", "16:9", "3:2"]}},
    "text_safe_area": {"type": "string"}, "logo_safe_area": {"type": "string"},
    "enhancement_notes": {"type": "array", "items": {"type": "string"}},
    "platforms": {"type": "array", "items": {"type": "string", "enum": ["Instagram Feed", "Instagram Carousel", "Instagram Story", "Instagram Reel", "Facebook", "LinkedIn", "Website Banner", "YouTube Thumbnail"]}},
})
SHOT_PLAN_JSON_SCHEMA = _object({"recommendations": {"type": "array", "items": _AI_RECOMMENDATION_SCHEMA}})


class ShotPlanner:
    """Create one deterministic framing plan for every feasible source-only scene."""

    def __init__(self, model: str | None = None) -> None:
        self.logger = get_logger(__name__)
        self.model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

    def run(
        self, knowledge_path: Path, creative_directions_path: Path, scene_plans_path: Path,
        visual_inventory_path: Path | None = None, content_plan_path: Path | None = None,
    ) -> Path | None:
        self.logger.info("Reading knowledge, creative directions, and scene plans...")
        try:
            knowledge = ProjectKnowledge.from_json(knowledge_path.read_text(encoding="utf-8"))
            if knowledge.validate():
                raise ValueError("; ".join(knowledge.validate()))
            creative = CreativeDirectionPlan.from_json(creative_directions_path.read_text(encoding="utf-8"))
            scenes = ScenePlanCollection.from_json(scene_plans_path.read_text(encoding="utf-8"))
            statuses = _content_statuses(content_plan_path)
            inventory_ids = _inventory_ids(visual_inventory_path)
            planning_inputs = _build_planning_inputs(creative, scenes, statuses, inventory_ids)
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            self.logger.error("Could not read valid Shot Planner input: %s", error)
            return None

        recommendations: list[dict[str, Any]] = []
        warnings: list[str] = []
        feasible_count = sum(len(item["scenes"]) for item in planning_inputs)
        if feasible_count:
            api_key = self._load_api_key()
            if api_key:
                try:
                    recommendations, ai_warnings = _parse_recommendations(
                        self._request_shot_plans(knowledge.to_dict(), planning_inputs, api_key)
                    )
                    warnings.extend(ai_warnings)
                except Exception as error:
                    warnings.append(f"AI framing recommendations unavailable: {type(error).__name__}: {error}")
            else:
                warnings.append("AI framing recommendations unavailable; deterministic fallbacks used")

        collection = _assemble_shot_plans(scenes, statuses, inventory_ids, recommendations, warnings)
        errors = collection.validate()
        errors.extend(_validate_against_source(collection, scenes, statuses, inventory_ids))
        if errors:
            self.logger.error("Deterministic Shot Planner validation failed: %s", "; ".join(errors))
            return None
        try:
            output_path = save_shot_plans(collection, _output_filename(scene_plans_path.stem))
        except (OSError, ValueError) as error:
            self.logger.error("Could not save shot plan JSON: %s", error)
            return None
        try:
            display_path = output_path.relative_to(PROJECT_ROOT)
        except ValueError:
            display_path = output_path
        self.logger.info("Shot plans saved:\n%s", display_path)
        self.logger.info(
            "Shot Planner completed:\n- Scene plans processed: %d\n- Scenes processed: %d\n- Fallback plans: %d\n- Text-only plans: %d\n- Skipped unavailable: %d\n- Invalid asset references removed: %d",
            *collection.summary.__dict__.values(),
        )
        return output_path

    def _load_api_key(self) -> str | None:
        try:
            from dotenv import load_dotenv
        except ImportError:
            return None
        load_dotenv()
        return os.getenv("OPENAI_API_KEY")

    def _request_shot_plans(self, knowledge: dict[str, Any], planning_inputs: list[dict[str, Any]], api_key: str) -> str:
        from openai import OpenAI
        response = OpenAI(api_key=api_key).responses.create(
            model=self.model,
            instructions="""You are an Existing Asset Framing Planner. Return framing recommendations only, in the supplied scene order. Decide crop recommendation, safe zoom, framing adaptation, aspect-ratio options, text-safe area, logo-safe area, layout type, image enhancement notes, and platform suitability. Do not return IDs, sequence values, counts, source asset IDs, camera decisions, new viewpoints, scene descriptions, project subjects, prompts, providers, or generation parameters. Never invent architecture, interiors, amenities, people, scenery, or source assets. Return valid JSON only.""",
            input=json.dumps({"project_knowledge": creative_knowledge_context(knowledge), "source_supported_scenes": planning_inputs}, ensure_ascii=False),
            text={"format": {"type": "json_schema", "name": "framing_recommendations", "strict": True, "schema": SHOT_PLAN_JSON_SCHEMA}},
        )
        if not response.output_text:
            raise ValueError("The API returned no JSON output")
        return response.output_text


def _content_statuses(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    content = ContentPlan.from_json(path.read_text(encoding="utf-8"))
    return {idea.unique_id: {"status": idea.source_support_status, "text_evidence": idea.text_evidence,
            "selected_format":idea.selected_format,"planned_publication":idea.planned_publication} for pillar in content.pillars for idea in pillar.content_ideas}


def _inventory_ids(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    return set(json.loads(path.read_text(encoding="utf-8")).get("all_source_asset_ids", []))


def _status_for(content_idea_id: str, scene_assets: list[str], statuses: dict[str, dict[str, Any]]) -> tuple[str, bool]:
    item = statuses.get(content_idea_id)
    if item:
        return item["status"], bool(item.get("text_evidence"))
    return ("fully_supported", False) if scene_assets else ("text_only", True)


def _build_planning_inputs(creative: CreativeDirectionPlan, scenes: ScenePlanCollection, statuses: dict[str, dict[str, Any]] | None = None, inventory_ids: set[str] | None = None) -> list[dict[str, Any]]:
    direction_ids = {item.creative_direction_id for item in creative.creative_directions}
    statuses = statuses or {}
    inputs: list[dict[str, Any]] = []
    for plan in scenes.scene_plans:
        if plan.creative_direction_id not in direction_ids:
            raise ValueError(f"Scene plan references unknown creative_direction_id: {plan.creative_direction_id}")
        scene_inputs = []
        for scene in plan.scenes:
            valid = [asset_id for asset_id in scene.reusable_asset_ids if inventory_ids is None or asset_id in inventory_ids]
            status, has_text = _status_for(plan.content_idea_id, valid, statuses)
            if status in {"fully_supported", "partially_supported"} and not valid:
                status = "text_only" if has_text else "skipped_unavailable"
            if status not in {"unavailable", "skipped_unavailable"}:
                scene_inputs.append({"scene_name": scene.scene_name, "source_support_status": status, "source_asset_count": len(valid)})
        inputs.append({"scene_plan_context": plan.overall_story_summary, "scenes": scene_inputs})
    return inputs


def _parse_recommendations(payload: str) -> tuple[list[dict[str, Any]], list[str]]:
    data = json.loads(payload)
    raw = data.get("recommendations", []) if isinstance(data, dict) else []
    if not isinstance(raw, list):
        return [], ["AI recommendations were not an array; all scenes use fallbacks"]
    clean: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            warnings.append(f"AI recommendation index {index} was invalid and ignored")
            continue
        forbidden = sorted(set(item) & _FORBIDDEN_AI_FIELDS)
        unknown = sorted(set(item) - _RECOMMENDATION_FIELDS - _FORBIDDEN_AI_FIELDS)
        if forbidden or unknown:
            warnings.append(f"AI recommendation index {index} removed fields: {', '.join(forbidden + unknown)}")
        clean.append({key: item[key] for key in _RECOMMENDATION_FIELDS if key in item})
    return clean, warnings


def _assemble_shot_plans(
    scenes: ScenePlanCollection, statuses: dict[str, dict[str, Any]] | None,
    inventory_ids: set[str] | None, recommendations: list[dict[str, Any]], warnings: list[str] | None = None,
) -> ShotPlanCollection:
    statuses = statuses or {}
    output = ShotPlanCollection(warnings=list(warnings or []))
    recommendation_index = 0
    for source_plan in scenes.scene_plans:
        groups: list[SceneFramingGroup] = []
        for scene in source_plan.scenes:
            original_assets = list(dict.fromkeys(scene.reusable_asset_ids))
            valid_assets = [asset_id for asset_id in original_assets if inventory_ids is None or asset_id in inventory_ids]
            output.summary.invalid_asset_references_removed += len(original_assets) - len(valid_assets)
            status, has_text = _status_for(source_plan.content_idea_id, valid_assets, statuses)
            if status in {"fully_supported", "partially_supported"} and not valid_assets:
                status = "text_only" if has_text else "skipped_unavailable"
                output.warnings.append(f"Scene {scene.scene_id} downgraded because no valid current-project asset remained")
            if status in {"unavailable", "skipped_unavailable"}:
                output.skipped_scenes.append(SkippedScene(scene.scene_id, source_plan.content_idea_id))
                output.summary.skipped_unavailable += 1
                continue
            recommendation = recommendations[recommendation_index] if recommendation_index < len(recommendations) else None
            recommendation_index += 1
            if recommendation is None or not _valid_recommendation(recommendation):
                recommendation = _fallback(status == "text_only")
                output.summary.fallback_plans_created += 1
                output.warnings.append(f"Deterministic fallback created for scene {scene.scene_id}")
            elif status != "text_only":
                # Compatibility artifact only. Static crop, layout, and brand
                # safe-area authority belongs exclusively to Visual Art Director.
                recommendation={**recommendation,"layout_type":"visual_art_director_deferred","crop_strategy":"preserve_full_source_for_visual_art_director",
                                "safe_zoom":"none","text_safe_area":"Resolved by Visual Direction Contract","logo_safe_area":"Resolved by Visual Direction Contract"}
            intent=statuses.get(source_plan.content_idea_id,{}).get("planned_publication") or {}
            if intent.get("publication_type")=="story":
                recommendation={**recommendation,"platforms":["Instagram Story"],"aspect_ratios":["9:16"],
                    "crop_strategy":"contain_letterbox_or_safe_portrait_crop","safe_zoom":"none",
                    "text_safe_area":"Story central safe zone: y=250..1600","logo_safe_area":"Story central safe zone: y=250..1600"}
            framing = FramingPlan(framing_plan_id=f"{scene.scene_id}-FP1", sequence=1, **recommendation)
            groups.append(SceneFramingGroup(scene.scene_id, scene.scene_name, status, valid_assets, [framing]))
            output.summary.scenes_processed += 1
            if status == "text_only":
                output.summary.text_only_plans_created += 1
        output.shot_plans.append(ShotPlan(
            shot_plan_id=f"{source_plan.scene_plan_id}-FP", scene_plan_id=source_plan.scene_plan_id,
            creative_direction_id=source_plan.creative_direction_id, content_idea_id=source_plan.content_idea_id,
            scene_framing_groups=groups,
        ))
    output.summary.scene_plans_processed = len(output.shot_plans)
    if recommendation_index < len(recommendations):
        output.warnings.append(f"Ignored {len(recommendations) - recommendation_index} unexpected AI recommendation(s)")
    return output


def _valid_recommendation(item: dict[str, Any]) -> bool:
    return (
        set(item) == _RECOMMENDATION_FIELDS
        and all(isinstance(item.get(name), str) and item[name].strip() for name in ("layout_type", "crop_strategy", "safe_zoom", "text_safe_area", "logo_safe_area"))
        and isinstance(item.get("aspect_ratios"), list) and bool(item["aspect_ratios"])
        and set(item["aspect_ratios"]).issubset(ASPECT_RATIOS)
        and isinstance(item.get("platforms"), list) and set(item["platforms"]).issubset(FUTURE_PLATFORMS)
        and isinstance(item.get("enhancement_notes"), list)
        and all(isinstance(note, str) for note in item["enhancement_notes"])
    )


def _validate_against_source(
    collection: ShotPlanCollection, scenes: ScenePlanCollection,
    statuses: dict[str, dict[str, Any]] | None, inventory_ids: set[str] | None,
) -> list[str]:
    """Verify deterministic coverage, IDs, and project-local asset provenance."""
    statuses = statuses or {}
    errors: list[str] = []
    plans_by_source = {plan.scene_plan_id: plan for plan in collection.shot_plans}
    if len(collection.shot_plans) != len(scenes.scene_plans):
        errors.append("exactly one shot plan is required per scene plan")
    skipped_ids = {item.scene_id for item in collection.skipped_scenes}
    seen_scene_ids: set[str] = set()
    seen_framing_ids: set[str] = set()
    for source_plan in scenes.scene_plans:
        output_plan = plans_by_source.get(source_plan.scene_plan_id)
        if output_plan is None:
            errors.append(f"missing scene_plan_id: {source_plan.scene_plan_id}")
            continue
        if output_plan.shot_plan_id != f"{source_plan.scene_plan_id}-FP":
            errors.append(f"invalid deterministic shot_plan_id for {source_plan.scene_plan_id}")
        groups = {group.scene_id: group for group in output_plan.scene_framing_groups}
        for source_scene in source_plan.scenes:
            valid_assets = [asset_id for asset_id in source_scene.reusable_asset_ids if inventory_ids is None or asset_id in inventory_ids]
            status, has_text = _status_for(source_plan.content_idea_id, valid_assets, statuses)
            if status in {"fully_supported", "partially_supported"} and not valid_assets:
                status = "text_only" if has_text else "skipped_unavailable"
            if status in {"unavailable", "skipped_unavailable"}:
                if source_scene.scene_id not in skipped_ids:
                    errors.append(f"unavailable scene was not recorded as skipped: {source_scene.scene_id}")
                continue
            group = groups.get(source_scene.scene_id)
            if group is None:
                errors.append(f"missing feasible scene_id: {source_scene.scene_id}")
                continue
            if group.scene_id in seen_scene_ids:
                errors.append(f"duplicate scene_id: {group.scene_id}")
            seen_scene_ids.add(group.scene_id)
            allowed = set(source_scene.reusable_asset_ids)
            if inventory_ids is not None:
                allowed &= inventory_ids
            if not set(group.source_asset_ids).issubset(allowed):
                errors.append(f"scene {group.scene_id} contains a non-project source asset")
            framing_id = group.framing_plans[0].framing_plan_id
            if framing_id != f"{group.scene_id}-FP1" or framing_id in seen_framing_ids:
                errors.append(f"invalid or duplicate framing_plan_id: {framing_id}")
            seen_framing_ids.add(framing_id)
        unexpected = set(groups) - {scene.scene_id for scene in source_plan.scenes}
        if unexpected:
            errors.append(f"unexpected scene IDs: {', '.join(sorted(unexpected))}")
    return errors


def _fallback(text_only: bool) -> dict[str, Any]:
    if text_only:
        return {"layout_type": "source_supported_text_graphic", "crop_strategy": "not_applicable", "safe_zoom": "not_applicable", "aspect_ratios": ["4:5", "1:1", "9:16"], "text_safe_area": "Template-defined", "logo_safe_area": "Template-defined", "enhancement_notes": [], "platforms": ["Instagram Feed", "Instagram Story", "Instagram Carousel"]}
    return {"layout_type": "visual_art_director_deferred", "crop_strategy": "preserve_full_source_for_visual_art_director", "safe_zoom": "none", "aspect_ratios": ["4:5", "1:1"], "text_safe_area": "Resolved by Visual Direction Contract", "logo_safe_area": "Resolved by Visual Direction Contract", "enhancement_notes": ["Apply only non-destructive technical correction"], "platforms": ["Instagram Feed", "Instagram Carousel"]}


def _output_filename(scene_plans_stem: str) -> str:
    return f"{scene_plans_stem.removesuffix('-scene-plans')}-shot-plans"
