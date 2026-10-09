"""OpenAI-backed conversion of approved creative directions into scene plans."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.content.schema import ContentPlan
from src.creative.schema import CreativeDirectionPlan
from src.core.logger import get_logger
from src.knowledge.schema import ProjectKnowledge
from src.ai.agents.creative_context import creative_knowledge_context
from src.scenes.schema import ScenePlanCollection, ScenePlanSummary, SkippedContentIdea
from src.scenes.storage import save_scene_plans
from src.utils.config import PROJECT_ROOT

DEFAULT_MODEL = "gpt-4o-mini"
SCENE_PLANNER_BATCH_SIZE = 5
SCENE_PLANNER_MAX_RECOVERY_ATTEMPTS = 2


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _narrative_string(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description + " Describe narrative intent and supported subjects or context only; exclude camera, framing, composition, lighting-setup, rendering, and production-execution instructions."}


_SCENE_SCHEMA = _object({
    "scene_id": {"type": "string"},
    "sequence": {"type": "integer", "minimum": 1},
    "scene_name": _narrative_string("A concise name for this narrative story unit."),
    "story_purpose": _narrative_string("What this scene contributes to the story progression."),
    "scene_summary": _narrative_string("What happens and which supported subject and environment are present."),
    "main_subject": {"type": "string"},
    "supporting_subjects": {"type": "array", "items": {"type": "string"}},
    "environment": {"type": "string"},
    "factual_basis": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    "creative_interpretation": _narrative_string("The evidence-preserving emotional or narrative meaning."),
    "time_of_day": {"type": "string"},
    "weather": {"type": "string"},
    "mood": {"type": "string"},
    "lighting_direction": _narrative_string("The supported natural light condition or narrative light intent, never a lighting setup."),
    "scene_dependencies": {"type": "array", "items": {"type": "string"}},
    "reusable_asset_ids": {"type": "array", "items": {"type": "string"}},
    "continuity_notes": {"type": "array", "items": {"type": "string"}},
    "restrictions": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    "transition_to_next_scene": _narrative_string("The narrative progression into the next scene or the end of the sequence."),
})
_SCENE_PLAN_SCHEMA = _object({
    "scene_plan_id": {"type": "string"},
    "creative_direction_id": {"type": "string"},
    "content_idea_id": {"type": "string"},
    "overall_story_summary": _narrative_string("The complete narrative progression for this creative direction."),
    "scene_count": {"type": "integer", "minimum": 1},
    "scenes": {"type": "array", "items": _SCENE_SCHEMA, "minItems": 1},
})
SCENE_PLAN_JSON_SCHEMA = _object({
    "scene_plans": {"type": "array", "items": _SCENE_PLAN_SCHEMA},
})


class ScenePlanner:
    """Plan story scenes while leaving all cinematography to Shot Planner."""

    def __init__(self, model: str | None = None) -> None:
        self.logger = get_logger(__name__)
        self.model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

    def run(
        self,
        knowledge_path: Path,
        content_plan_path: Path,
        creative_directions_path: Path,
        asset_selections_path: Path | None = None,
        visual_inventory_path: Path | None = None,
    ) -> Path | None:
        """Read upstream artifacts, generate validated scene plans, and save them."""
        self.logger.info("Reading knowledge, content plan, and creative directions...")
        try:
            knowledge = ProjectKnowledge.from_json(knowledge_path.read_text(encoding="utf-8"))
            knowledge_errors = knowledge.validate()
            if knowledge_errors:
                raise ValueError("; ".join(knowledge_errors))
            content_plan = ContentPlan.from_json(content_plan_path.read_text(encoding="utf-8"))
            creative_directions = CreativeDirectionPlan.from_json(
                creative_directions_path.read_text(encoding="utf-8")
            )
            selections = _read_asset_selections(asset_selections_path, visual_inventory_path) if asset_selections_path else None
            inputs, eligible_direction_ids, skipped, summary = _build_planning_inputs(content_plan, creative_directions, selections)
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            self.logger.error("Could not read valid Scene Planner input: %s", error)
            return None

        if inputs:
            api_key = self._load_api_key()
            if not api_key:
                return None
            self.logger.info("Generating scene plans...")
            try:
                raw_plans: list[dict[str, Any]] = []
                initial_returned = 0
                initial_semantic_violations = 0
                semantic_recovery_attempts = 0
                for offset in range(0, len(inputs), SCENE_PLANNER_BATCH_SIZE):
                    batch = inputs[offset:offset + SCENE_PLANNER_BATCH_SIZE]
                    expected = {item["creative_direction"]["creative_direction_id"]: item for item in batch}
                    accepted: dict[str, dict[str, Any]] = {}
                    pending = batch
                    recovery_feedback: dict[str, str] = {}
                    for attempt in range(SCENE_PLANNER_MAX_RECOVERY_ATTEMPTS + 1):
                        if recovery_feedback:
                            semantic_recovery_attempts += 1
                            response_text = self._request_scene_plans(
                                knowledge.to_dict(), pending, api_key,
                                recovery_feedback=recovery_feedback,
                            )
                        else:
                            response_text = self._request_scene_plans(knowledge.to_dict(), pending, api_key)
                        batch_output = json.loads(response_text)
                        for repair_message in _sanitize_scene_output(batch_output):
                            self.logger.warning("Scene Planner sanitized output: %s", repair_message)
                        returned_plans = batch_output.get("scene_plans") if isinstance(batch_output, dict) else None
                        if not isinstance(returned_plans, list):
                            raise ValueError("scene_plans must be a list of objects")
                        if attempt == 0:
                            initial_returned += len(returned_plans)
                        violations: dict[str, str] = {}
                        for plan in returned_plans:
                            if not isinstance(plan, dict):
                                raise ValueError("scene plan must be an object")
                            direction_id = plan["creative_direction_id"]
                            if direction_id not in expected:
                                raise ValueError(f"unexpected creative_direction_id: {direction_id}")
                            expected_idea_id = expected[direction_id]["creative_direction"]["content_idea_id"]
                            if plan["content_idea_id"] != expected_idea_id:
                                raise ValueError(f"mismatched content_idea_id for creative_direction_id {direction_id}")
                            if direction_id in accepted:
                                raise ValueError(f"duplicate creative_direction_id: {direction_id}")
                            try:
                                validated = ScenePlanCollection.from_dict({"scene_plans": [plan]})
                            except ValueError as error:
                                if "downstream production decision" not in str(error):
                                    raise
                                violations[direction_id] = str(error)
                                if attempt == 0:
                                    initial_semantic_violations += 1
                                continue
                            selection=expected[direction_id].get("approved_source_asset_selection")
                            source_errors=_ordered_source_errors(validated.scene_plans[0],selection)
                            if source_errors:
                                violations[direction_id]="; ".join(source_errors)
                                if attempt==0:initial_semantic_violations+=1
                                continue
                            accepted[direction_id] = validated.to_dict()["scene_plans"][0]
                        missing = [direction_id for direction_id in expected if direction_id not in accepted]
                        if not missing:
                            break
                        if attempt == SCENE_PLANNER_MAX_RECOVERY_ATTEMPTS:
                            raise ValueError("missing creative_direction_id: " + ", ".join(missing))
                        pending = [expected[direction_id] for direction_id in missing]
                        recovery_feedback = {
                            direction_id: violations.get(direction_id, "The required scene plan was missing.")
                            for direction_id in missing
                        }
                        self.logger.warning("Scene Planner recovery attempt %d for %d missing direction(s)", attempt + 1, len(pending))
                    raw_plans.extend(accepted[direction_id] for direction_id in expected)
                self.logger.info(
                    "Scene Planner completeness: expected=%d initial_returned=%d initial_semantic_violations=%d semantic_recovery_attempts=%d final=%d",
                    len(inputs), initial_returned, initial_semantic_violations,
                    semantic_recovery_attempts, len(raw_plans),
                )
            except Exception as error:
                self.logger.error("Scene Planner API request failed: %s", error)
                return None
            self.logger.info("Validating scene plan JSON...")
            try:
                raw_output = {"scene_plans": raw_plans}
                collection = ScenePlanCollection.from_dict(raw_output)
                _validate_plan_coverage(collection, creative_directions, eligible_direction_ids)
                _repair_and_validate_reusable_assets(collection, selections)
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                self.logger.error("OpenAI returned invalid scene plan JSON: %s", error)
                return None
        else:
            self.logger.warning("No source-supported content ideas remain; saving an empty scene plan.")
            collection = ScenePlanCollection()
        collection.skipped_content_ideas = skipped
        collection.summary = summary

        try:
            output_path = save_scene_plans(collection, _output_filename(creative_directions_path.stem))
        except (OSError, ValueError) as error:
            self.logger.error("Could not save scene plan JSON: %s", error)
            return None
        try:
            display_path = output_path.relative_to(PROJECT_ROOT)
        except ValueError:
            display_path = output_path
        self.logger.info("Scene plans saved:")
        self.logger.info("%s", display_path)
        self.logger.info(
            "Scene Planner completed:\n- Scene plans created: %d\n- Partially supported: %d\n- Text-only: %d\n- Skipped unavailable: %d",
            len(collection.scene_plans), summary.partially_supported_processed,
            summary.text_only_processed, summary.skipped_unavailable,
        )
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

    def _request_scene_plans(
        self,
        knowledge: dict[str, Any],
        planning_inputs: list[dict[str, Any]],
        api_key: str,
        *,
        recovery_feedback: dict[str, str] | None = None,
    ) -> str:
        from openai import OpenAI

        request_input = json.dumps({
            "project_knowledge": creative_knowledge_context(knowledge),
            "approved_creative_directions_and_content_ideas": planning_inputs,
            **({"targeted_recovery_feedback": recovery_feedback} if recovery_feedback else {}),
        }, ensure_ascii=False)
        schema = deepcopy(SCENE_PLAN_JSON_SCHEMA)
        plan_properties = schema["properties"]["scene_plans"]["items"]["properties"]
        plan_properties["creative_direction_id"] = {
            "type": "string",
            "enum": [item["creative_direction"]["creative_direction_id"] for item in planning_inputs],
        }
        plan_properties["content_idea_id"] = {
            "type": "string",
            "enum": [item["creative_direction"]["content_idea_id"] for item in planning_inputs],
        }
        recovery_instruction = ""
        if recovery_feedback:
            recovery_instruction = "\nThis is a targeted replacement request. Replace each complete scene plan from scratch for the exact IDs supplied. The prior plan violated the semantic boundary described in targeted_recovery_feedback. Do not reuse any invalid scene text."
        response = OpenAI(api_key=api_key).responses.create(
            model=self.model,
            instructions="""You are the Scene Planner. Convert every supplied approved creative direction into a practical, structured sequence of narrative story scenes. You own what happens, supported subjects and actions, environment and context, evidence relationships, scene purpose, emotional story intent, continuity, and narrative transitions. You do not own how a scene is photographed, laid out, lit, rendered, or produced.

For each creative direction in the input, return exactly one scene plan. Copy creative_direction_id and content_idea_id exactly as provided. Do not rename, normalize, shorten, or generate new IDs. Return scene plans in the same order as the creative directions in the input. Do not omit a direction, duplicate a plan, or add an unlinked plan.

For every scene plan, scene_count must exactly equal len(scenes). Count the final scenes array before returning JSON.

In source-only mode, a scene is an ordered use of approved authentic material, not an invented view. For fully_supported ideas, use only supplied approved source_asset_ids. For partially_supported ideas, create only scenes supported by those assets and factual text. For text_only ideas, create a text, map, floor plan, masterplan, diagram, or branded information layout and do not invent an image reference. Never request a view, subject, environment, time, weather, lighting condition, or event that is not supported. Use metadata truthfully and mark unknown details as unknown.
For canonical_ordered_selection carousels, create exactly one scene per selected_asset_ids entry in that exact order. Each scene's reusable_asset_ids must contain exactly that entry. Do not repeat a source, substitute another source, or invent a new view of it.

Ground every factual_basis entry in project_knowledge or the supplied content idea. Use approved creative interpretation only for atmosphere, human behavior, and narrative meaning; it cannot create a new project fact. If information is missing, design around known details. Never invent architecture, interiors, views, amenities, materials, rooms, private spaces, community spaces, location claims, services, or project status. An interiors-only direction must remain indoors. A community-life direction must not introduce unsupported private spaces. reusable_asset_ids may contain only IDs listed by that creative direction.

Preserve the creative direction's emotional direction, storytelling direction, visual identity, luxury level, realism level, brand constraints, and story boundaries. Every scene must include specific factual_basis, continuity notes as applicable, and restrictions protecting against undocumented architecture, invented amenities, fantasy elements, exaggerated luxury cliches, unrealistic human behavior, and loss of architectural authenticity. Use "Not specified" for unknown weather rather than asserting it. The last transition_to_next_scene should clearly state that the sequence ends.

Do not include framing or cropping. Do not specify shot size or shot type. Do not specify camera angle or camera height. Do not specify a lens, focal length, aperture, exposure, depth of field, shutter setting, or camera motion. Do not specify composition, layout, aspect ratio, or safe zones. Do not specify lighting equipment, placement, or setup. Do not specify renderer, VFX, prompt wording, provider syntax, image-generation parameters, or post-production execution. Express the narrative subject and intended meaning instead, and leave every implementation decision to Shot Planner and Production. Ignore any legacy cinematography fields in upstream content. Return valid JSON only, exactly matching the supplied schema, with no commentary.""" + recovery_instruction,
            input=request_input,
            text={"format": {"type": "json_schema", "name": "scene_plans", "strict": True, "schema": schema}},
        )
        if not response.output_text:
            raise ValueError("The API returned no JSON output")
        return response.output_text


def _build_planning_inputs(
    content_plan: ContentPlan,
    creative_directions: CreativeDirectionPlan,
    selections: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[SkippedContentIdea], ScenePlanSummary]:
    ideas = {
        idea["unique_id"]: _story_context(idea)
        for pillar in content_plan.to_dict()["pillars"]
        for idea in pillar["content_ideas"]
    }
    if not creative_directions.creative_directions:
        raise ValueError("Creative direction artifact contains no directions")
    inputs: list[dict[str, Any]] = []
    eligible_direction_ids: list[str] = []
    skipped: list[SkippedContentIdea] = []
    summary = ScenePlanSummary()
    for direction in creative_directions.to_dict()["creative_directions"]:
        content_idea_id = direction["content_idea_id"]
        if content_idea_id not in ideas:
            raise ValueError(f"Creative direction references unknown content idea ID: {content_idea_id}")
        idea = ideas[content_idea_id]
        status = idea["source_support_status"]
        selection = selections.get(content_idea_id) if selections is not None else None
        selected_ids = list(selection.get("selected_asset_ids", [])) if selection else []
        if status in {"unavailable", "skipped_unavailable"}:
            skipped.append(SkippedContentIdea(content_idea_id))
            summary.skipped_unavailable += 1
            continue
        if status in {"fully_supported", "partially_supported"} and not selected_ids:
            status = "text_only" if idea.get("text_evidence") else "skipped_unavailable"
        if selection is not None and selection.get("status") != "ready" and status != "text_only":
            status = "text_only" if idea.get("text_evidence") else "skipped_unavailable"
        if status == "skipped_unavailable":
            skipped.append(SkippedContentIdea(content_idea_id))
            summary.skipped_unavailable += 1
            continue
        idea["source_support_status"] = status
        item = {"creative_direction": direction, "content_idea": idea}
        if selections is not None:
            item["approved_source_asset_selection"] = selection or {"selected_asset_ids": [], "status": "ready"}
        inputs.append(item)
        eligible_direction_ids.append(direction["creative_direction_id"])
        setattr(summary, f"{status}_processed", getattr(summary, f"{status}_processed") + 1)
    return inputs, eligible_direction_ids, skipped, summary


def _repair_scene_counts(data: Any) -> list[str]:
    """Repair only scene_count values from untouched scenes arrays."""
    if not isinstance(data, dict):
        return []
    raw_plans = data.get("scene_plans")
    if not isinstance(raw_plans, list):
        return []
    repairs: list[str] = []
    for index, raw_plan in enumerate(raw_plans):
        if not isinstance(raw_plan, dict):
            continue
        scenes = raw_plan.get("scenes")
        if not isinstance(scenes, list):
            continue
        declared = raw_plan.get("scene_count", "<missing>")
        actual = len(scenes)
        if not isinstance(declared, int) or isinstance(declared, bool) or declared != actual:
            direction_id = raw_plan.get("creative_direction_id", "<missing>")
            repairs.append(
                f"scene plan index {index}, creative_direction_id={direction_id}, "
                f"declared scene_count={declared}, actual scenes={actual}"
            )
            raw_plan["scene_count"] = actual
    return repairs


_FORBIDDEN_SCENE_FIELDS = {
    "framing", "crop", "crop_coordinates", "camera_angle", "camera_height", "lens",
    "composition", "depth_of_field", "camera_motion", "aspect_ratio", "text_safe_zone",
    "logo_safe_zone", "zoom", "shot_type",
}


def _sanitize_scene_output(data: Any) -> list[str]:
    """Remove downstream fields and canonicalize scene identity before strict validation."""
    if not isinstance(data, dict) or not isinstance(data.get("scene_plans"), list):
        return []
    warnings: list[str] = []
    generated_ids: set[str] = set()
    for plan_index, plan in enumerate(data["scene_plans"]):
        if not isinstance(plan, dict) or not isinstance(plan.get("scenes"), list):
            continue
        direction_id = plan.get("creative_direction_id", "<missing>")
        plan["scene_plan_id"] = f"{direction_id}-PLAN"
        old_to_new: dict[str, str] = {}
        scenes = plan["scenes"]
        for scene_index, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            for field_name in sorted(_FORBIDDEN_SCENE_FIELDS & set(scene)):
                scene.pop(field_name)
                warnings.append(
                    f"scene plan index {plan_index}, creative_direction_id={direction_id}, "
                    f"scene index {scene_index}: removed forbidden field {field_name}"
                )
            expected_sequence = scene_index + 1
            declared_sequence = scene.get("sequence", "<missing>")
            if not isinstance(declared_sequence, int) or isinstance(declared_sequence, bool) or declared_sequence != expected_sequence:
                warnings.append(
                    f"scene plan index {plan_index}, creative_direction_id={direction_id}, "
                    f"scene index {scene_index}: invalid sequence value {declared_sequence}; repaired to {expected_sequence}"
                )
            scene["sequence"] = expected_sequence
            generated_id = f"{direction_id}-SC{expected_sequence}"
            if generated_id in generated_ids:
                raise ValueError(
                    f"scene plan index {plan_index}, creative_direction_id={direction_id}, "
                    f"scene index {scene_index}: duplicate generated ID {generated_id}"
                )
            old_id = scene.get("scene_id")
            if isinstance(old_id, str) and old_id and old_id not in old_to_new:
                old_to_new[old_id] = generated_id
            scene["scene_id"] = generated_id
            generated_ids.add(generated_id)
        for scene_index, scene in enumerate(scenes):
            if not isinstance(scene, dict) or not isinstance(scene.get("scene_dependencies"), list):
                continue
            current_sequence = scene_index + 1
            remapped: list[str] = []
            for dependency in scene["scene_dependencies"]:
                mapped = old_to_new.get(dependency, dependency if dependency in generated_ids else None)
                if mapped and mapped in generated_ids:
                    try:
                        dependency_sequence = int(mapped.rsplit("-SC", 1)[1])
                    except (IndexError, ValueError):
                        continue
                    if dependency_sequence < current_sequence and mapped not in remapped:
                        remapped.append(mapped)
            scene["scene_dependencies"] = remapped
        declared_count = plan.get("scene_count", "<missing>")
        actual_count = len(scenes)
        if not isinstance(declared_count, int) or isinstance(declared_count, bool) or declared_count != actual_count:
            warnings.append(
                f"scene plan index {plan_index}, creative_direction_id={direction_id}, "
                f"declared scene_count={declared_count}, actual scenes={actual_count}"
            )
        plan["scene_count"] = actual_count
    return warnings


def _story_context(idea: dict[str, Any]) -> dict[str, Any]:
    """Exclude completed-plan cinematography fields from Scene Planner input."""
    names = (
        "unique_id", "title", "story", "purpose", "target_audience", "emotion",
        "marketing_goal", "main_subject", "supporting_subjects", "environment",
        "time_of_day", "weather", "mood", "color_palette", "visual_keywords",
        "source_support_status", "text_evidence",
    )
    return {name: idea[name] for name in names}


def _validate_plan_coverage(
    collection: ScenePlanCollection,
    creative_directions: CreativeDirectionPlan,
    eligible_direction_ids: list[str] | None = None,
) -> None:
    allowed_expected = set(eligible_direction_ids) if eligible_direction_ids is not None else None
    expected_order = [direction.creative_direction_id for direction in creative_directions.creative_directions if allowed_expected is None or direction.creative_direction_id in allowed_expected]
    expected_ideas = {
        direction.creative_direction_id: direction.content_idea_id
        for direction in creative_directions.creative_directions
    }
    plans_by_id: dict[str, list[Any]] = {}
    for plan in collection.scene_plans:
        plans_by_id.setdefault(plan.creative_direction_id, []).append(plan)

    errors: list[str] = []
    for direction_id in expected_order:
        matches = plans_by_id.get(direction_id, [])
        if not matches:
            errors.append(f"missing creative_direction_id: {direction_id}")
        elif len(matches) > 1:
            errors.append(f"duplicate creative_direction_id: {direction_id}")

    for direction_id in plans_by_id:
        if direction_id not in expected_ideas:
            errors.append(f"unexpected creative_direction_id: {direction_id}")

    for direction_id in expected_order:
        matches = plans_by_id.get(direction_id, [])
        if len(matches) == 1:
            actual_idea_id = matches[0].content_idea_id
            expected_idea_id = expected_ideas[direction_id]
            if actual_idea_id != expected_idea_id:
                errors.append(
                    f"mismatched content_idea_id for creative_direction_id {direction_id}: "
                    f"expected {expected_idea_id}, received {actual_idea_id}"
                )

    if errors:
        raise ValueError("Invalid scene plan mapping: " + "; ".join(errors))

    # Valid plans may arrive in a different order. Canonicalize them to the exact
    # Creative Director input order before asset validation and persistence.
    collection.scene_plans[:] = [plans_by_id[direction_id][0] for direction_id in expected_order]


def _repair_and_validate_reusable_assets(
    collection: ScenePlanCollection,
    selections: dict[str, dict[str, Any]] | None = None,
) -> None:
    for plan in collection.scene_plans:
        selection = selections.get(plan.content_idea_id) if selections is not None else None
        errors=_ordered_source_errors(plan,selection)
        if errors:raise ValueError("; ".join(errors))
        if selection and selection.get("canonical_ordered_selection") and selection.get("publication_type")=="carousel":
            continue # Exact source order was validated, never silently replaced.
        allowed = set(selection.get("selected_asset_ids", [])) if selection else set()
        for scene in plan.scenes:
            scene.reusable_asset_ids = [asset_id for asset_id in scene.reusable_asset_ids if asset_id in allowed]
            if allowed and not scene.reusable_asset_ids:
                scene.reusable_asset_ids = [sorted(allowed)[0]]


def _ordered_source_errors(plan,selection):
    if not selection or not selection.get("canonical_ordered_selection") or selection.get("publication_type")!="carousel":return []
    ordered=selection.get("selected_asset_ids",[])
    scenes=sorted(plan.scenes,key=lambda s:s.sequence)
    if len(scenes)!=len(ordered) or any(s.reusable_asset_ids!=[aid] for s,aid in zip(scenes,ordered)):
        return ["Canonical carousel requires exactly one scene per source in selected_asset_ids order: "+", ".join(ordered)]
    return []


def _read_asset_selections(path: Path, visual_inventory_path: Path | None = None) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("visual_mode") != "source_only" or data.get("workflow_status") != "ready":
        raise ValueError("Asset selection artifact is not ready in source-only mode")
    allowed: set[str] | None = None
    if visual_inventory_path is not None:
        inventory = json.loads(visual_inventory_path.read_text(encoding="utf-8"))
        if inventory.get("project") != data.get("project"):
            raise ValueError("Asset selection and visual inventory belong to different projects")
        allowed = set(inventory.get("all_source_asset_ids", []))
    selections: dict[str, dict[str, Any]] = {}
    for raw_item in data.get("selections", []):
        item = dict(raw_item)
        if allowed is not None:
            if item.get("canonical_ordered_selection") and any(asset_id not in allowed for asset_id in item.get("selected_asset_ids", [])):
                raise ValueError("Canonical source selection is absent from the current project inventory")
            item["selected_asset_ids"] = [asset_id for asset_id in item.get("selected_asset_ids", []) if asset_id in allowed]
        selections[item["content_idea_id"]] = item
    return selections


def _output_filename(creative_directions_stem: str) -> str:
    return f"{creative_directions_stem.removesuffix('-creative-directions')}-scene-plans"
