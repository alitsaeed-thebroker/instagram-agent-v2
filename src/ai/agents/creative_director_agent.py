"""OpenAI-backed generation of grounded creative direction JSON."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from src.content.schema import ContentPlan
from src.creative.schema import CreativeDirectionPlan
from src.creative.storage import save_creative_directions
from src.core.logger import get_logger
from src.knowledge.schema import ProjectKnowledge
from src.ai.agents.creative_context import creative_knowledge_context
from src.strategy.schema import MarketingStrategy
from src.utils.config import PROJECT_ROOT

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BATCH_SIZE = 5
MAX_RECOVERY_ATTEMPTS = 2


class CreativeDirectorCompletenessError(ValueError):
    def __init__(self, expected: list[str], returned: list[str], *, recovery_attempts: int = 0) -> None:
        duplicates=sorted({item for item in returned if returned.count(item)>1})
        missing=sorted(set(expected)-set(returned));unexpected=sorted(set(returned)-set(expected))
        self.expected,self.returned,self.missing,self.unexpected,self.duplicates,self.recovery_attempts=expected,returned,missing,unexpected,duplicates,recovery_attempts
        super().__init__(f"CreativeDirectorCompletenessError expected={len(expected)} returned={len(returned)} missing={missing} unexpected={unexpected} duplicates={duplicates} recovery_attempts={recovery_attempts}")


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_VISUAL_IDENTITY_SCHEMA = _object({
    "factual_project_elements": {"type": "array", "items": {"type": "string"}},
    "creative_interpretation": {"type": "string"},
    "palette_intent": {"type": "array", "items": {"type": "string"}},
    "texture_language": {"type": "array", "items": {"type": "string"}},
})
_EMOTIONAL_DIRECTION_SCHEMA = _object({
    "primary_emotion": {"type": "string"},
    "supporting_emotions": {"type": "array", "items": {"type": "string"}},
    "desired_response": {"type": "string"},
})
_STORYTELLING_DIRECTION_SCHEMA = _object({
    "premise": {"type": "string"},
    "narrative_arc": {"type": "array", "items": {"type": "string"}},
    "story_boundaries": {"type": "array", "items": {"type": "string"}},
})
_CREATIVE_DIRECTION_SCHEMA = _object({
    "creative_direction_id": {"type": "string"},
    "content_idea_id": {"type": "string"},
    "campaign_concept": {"type": "string"},
    "visual_identity": _VISUAL_IDENTITY_SCHEMA,
    "emotional_direction": _EMOTIONAL_DIRECTION_SCHEMA,
    "storytelling_direction": _STORYTELLING_DIRECTION_SCHEMA,
    "brand_constraints": {"type": "array", "items": {"type": "string"}},
    "luxury_level": {"type": "string"},
    "realism_level": {"type": "string"},
    "audience_perception": {"type": "string"},
    "artistic_vision": {"type": "string"},
    "reference_asset_ids": {"type": "array", "items": {"type": "string"}},
    "consistency_approval_criteria": {"type": "array", "items": {"type": "string"}},
})
CREATIVE_DIRECTION_JSON_SCHEMA = _object({
    "creative_directions": {"type": "array", "items": _CREATIVE_DIRECTION_SCHEMA},
})


class CreativeDirectorAgent:
    """Create senior creative direction without making production decisions."""

    def __init__(self, model: str | None = None) -> None:
        self.logger = get_logger(__name__)
        self.model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self.batch_size = max(1,int(os.getenv("CREATIVE_DIRECTOR_BATCH_SIZE",DEFAULT_BATCH_SIZE)))
        self.last_run_diagnostics: dict[str,Any] = {}

    def run(
        self,
        knowledge_path: Path,
        strategy_path: Path,
        content_plan_path: Path,
        selected_content_idea_ids: Iterable[str] | None = None,
    ) -> Path | None:
        """Generate and save one creative direction per selected content idea."""
        self.logger.info("Reading knowledge, strategy, and content plan...")
        try:
            knowledge = ProjectKnowledge.from_json(knowledge_path.read_text(encoding="utf-8"))
            knowledge_errors = knowledge.validate()
            if knowledge_errors:
                raise ValueError("; ".join(knowledge_errors))
            strategy = MarketingStrategy.from_json(strategy_path.read_text(encoding="utf-8"))
            content_plan = ContentPlan.from_json(content_plan_path.read_text(encoding="utf-8"))
            selected_ideas = _select_content_ideas(content_plan, selected_content_idea_ids)
            expected_ids=[idea["unique_id"] for idea in selected_ideas]
            if len(expected_ids)!=len(set(expected_ids)):raise ValueError("Authoritative content idea IDs must be unique")
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            self.logger.error("Could not read valid Creative Director input: %s", error)
            return None

        api_key = self._load_api_key()
        if not api_key:
            return None

        self.logger.info("Generating creative directions for %d authoritative content ideas in deterministic batches of %d...",len(expected_ids),self.batch_size)
        try:
            directions=[];initial_ids=[];recovery_attempts=0
            for batch in _batches(selected_ideas,self.batch_size):
                batch_ids=[idea["unique_id"] for idea in batch]
                response_text=self._request_directions(knowledge.to_dict(),strategy.to_dict(),batch,api_key)
                plan,returned=_parse_exact_response(response_text,batch_ids)
                initial_ids.extend(returned);directions.extend(plan.creative_directions)
                missing=[item for item in batch_ids if item not in returned]
                batch_recovery_attempts=0
                while missing and batch_recovery_attempts<MAX_RECOVERY_ATTEMPTS:
                    batch_recovery_attempts+=1;recovery_attempts+=1;recovery=[idea for idea in batch if idea["unique_id"] in set(missing)]
                    recovered_text=self._request_directions(knowledge.to_dict(),strategy.to_dict(),recovery,api_key)
                    recovered_plan,recovered_ids=_parse_exact_response(recovered_text,missing)
                    directions.extend(recovered_plan.creative_directions);returned.extend(recovered_ids)
                    missing=[item for item in batch_ids if item not in returned]
                if missing:raise CreativeDirectorCompletenessError(batch_ids,returned,recovery_attempts=recovery_attempts)
            order={identity:index for index,identity in enumerate(expected_ids)}
            unexpected=[item.content_idea_id for item in directions if item.content_idea_id not in order]
            if unexpected:raise ValueError("Creative Director returned identities absent from the authoritative content plan: "+", ".join(sorted(set(unexpected))))
            directions.sort(key=lambda item:order[item.content_idea_id])
            plan=CreativeDirectionPlan(directions)
            plan_errors=plan.validate()
            if plan_errors:raise ValueError("; ".join(plan_errors))
            _validate_idea_coverage(plan,expected_ids,recovery_attempts=recovery_attempts)
            self.last_run_diagnostics={"expected_count":len(expected_ids),"initial_returned_count":len(initial_ids),"initial_missing_ids":sorted(set(expected_ids)-set(initial_ids)),"recovery_attempts":recovery_attempts,"final_count":len(directions)}
            self.logger.info("Creative Director completeness: expected=%d initial_returned=%d initial_missing=%d recovery_attempts=%d final=%d",len(expected_ids),len(initial_ids),len(self.last_run_diagnostics["initial_missing_ids"]),recovery_attempts,len(directions))
        except Exception as error:
            self.logger.error("Creative Director API request failed: %s", error)
            return None

        self.logger.info("Validating creative direction JSON...")
        try:
            _validate_reference_assets(plan, selected_ideas)
        except (TypeError, ValueError) as error:
            self.logger.error("OpenAI returned invalid creative direction JSON: %s", error)
            return None

        try:
            output_path = save_creative_directions(plan, _output_filename(content_plan_path.stem))
        except (OSError, ValueError) as error:
            self.logger.error("Could not save creative direction JSON: %s", error)
            return None
        try:
            display_path = output_path.relative_to(PROJECT_ROOT)
        except ValueError:
            display_path = output_path
        self.logger.info("Creative directions saved:")
        self.logger.info("%s", display_path)
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

    def _request_directions(
        self,
        knowledge: dict[str, Any],
        strategy: dict[str, Any],
        selected_ideas: list[dict[str, Any]],
        api_key: str,
    ) -> str:
        from openai import OpenAI

        required_ids=[idea["unique_id"] for idea in selected_ideas]
        required_direction_ids=[_direction_id(item) for item in required_ids]
        request_input = json.dumps({
            "required_content_idea_ids":required_ids,
            "project_knowledge": creative_knowledge_context(knowledge),
            "marketing_strategy": strategy,
            "selected_content_ideas": selected_ideas,
            "available_reference_asset_ids": sorted({
                asset_id for idea in selected_ideas for asset_id in idea.get("available_source_asset_ids", [])
            }),
        }, ensure_ascii=False)
        schema=deepcopy(CREATIVE_DIRECTION_JSON_SCHEMA)
        directions_schema=schema["properties"]["creative_directions"]
        directions_schema["minItems"]=len(required_ids);directions_schema["maxItems"]=len(required_ids)
        directions_schema["items"]["properties"]["content_idea_id"]={"type":"string","enum":required_ids}
        directions_schema["items"]["properties"]["creative_direction_id"]={"type":"string","enum":required_direction_ids}
        response = OpenAI(api_key=api_key).responses.create(
            model=self.model,
            instructions="""You are the senior Creative Director of a world-class luxury real-estate advertising agency.

Create exactly one creative direction for every supplied content idea and every required_content_idea_id. Preserve each content_idea_id exactly, invent none, and omit none. For each content ID content_SUFFIX, use the corresponding creative_direction_id direction_SUFFIX. Decide only the campaign concept, visual identity, emotional direction, storytelling direction, brand constraints, luxury level, realism level, intended audience perception, overall artistic vision, and measurable creative-consistency approval criteria.

Use project_knowledge only for factual project elements, marketing_strategy for marketing direction, and each feasible selected content idea for its intended story and approved assets. Copy only that idea's available_source_asset_ids into reference_asset_ids. Design around what is visibly available. Never describe undocumented interiors, exteriors, amenities, people, lifestyle situations, viewpoints, materials, or reference assets. Clearly separate supported facts from creative interpretation and preserve architectural authenticity.

The direction must be premium, project-specific, emotionally coherent, restrained, realistic, reusable by a later Scene Planner, and free from generic luxury advertising clichés. Storytelling direction defines the premise and emotional arc, not individual scenes.

Never decide or mention camera angle, camera height, lens, shot type, composition, framing, aspect ratio, prompt wording, provider syntax, image-generation parameters, captions, branding layouts, or publishing. These belong to later modules. Return valid JSON only, exactly matching the supplied schema, with no commentary.""",
            input=request_input,
            text={"format": {"type": "json_schema", "name": "creative_directions", "strict": True, "schema": schema}},
        )
        if not response.output_text:
            raise ValueError("The API returned no JSON output")
        return response.output_text


def _select_content_ideas(
    plan: ContentPlan,
    selected_content_idea_ids: Iterable[str] | None,
) -> list[dict[str, Any]]:
    all_ideas = [
        idea
        for pillar in plan.to_dict()["pillars"]
        for idea in pillar["content_ideas"]
    ]
    if selected_content_idea_ids is None:
        if not all_ideas:
            raise ValueError("Content plan contains no content ideas")
        return all_ideas
    selected_ids = list(selected_content_idea_ids)
    if not selected_ids:
        raise ValueError("At least one content idea must be selected")
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("Selected content idea IDs must be unique")
    ideas_by_id = {idea["unique_id"]: idea for idea in all_ideas}
    missing = [idea_id for idea_id in selected_ids if idea_id not in ideas_by_id]
    if missing:
        raise ValueError("Unknown selected content idea IDs: " + ", ".join(missing))
    return [ideas_by_id[idea_id] for idea_id in selected_ids]


def _validate_idea_coverage(plan: CreativeDirectionPlan, expected_ids: list[str], *, recovery_attempts:int=0) -> None:
    actual_ids = [direction.content_idea_id for direction in plan.creative_directions]
    if len(actual_ids) != len(expected_ids) or set(actual_ids) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(actual_ids))
        extra = sorted(set(actual_ids) - set(expected_ids))
        details = []
        if missing:
            details.append("missing content idea IDs: " + ", ".join(missing))
        if extra:
            details.append("unexpected content idea IDs: " + ", ".join(extra))
        raise CreativeDirectorCompletenessError(expected_ids,actual_ids,recovery_attempts=recovery_attempts)


def _parse_exact_response(payload:str,expected_ids:list[str])->tuple[CreativeDirectionPlan,list[str]]:
    try:data=json.loads(payload);rows=data.get("creative_directions",[]) if isinstance(data,dict) else []
    except json.JSONDecodeError as error:raise ValueError("Creative direction JSON is invalid") from error
    returned=[str(row.get("content_idea_id")) for row in rows if isinstance(row,dict) and row.get("content_idea_id")]
    duplicates={item for item in returned if returned.count(item)>1};unexpected=set(returned)-set(expected_ids)
    if duplicates or unexpected:raise CreativeDirectorCompletenessError(expected_ids,returned)
    plan=CreativeDirectionPlan.from_dict(data)
    return plan,returned


def _batches(items:list[dict[str,Any]],size:int)->list[list[dict[str,Any]]]:
    return [items[index:index+size] for index in range(0,len(items),size)]


def _direction_id(content_id:str)->str:
    return "direction_"+(content_id.removeprefix("content_") or content_id)


def _validate_reference_assets(plan: CreativeDirectionPlan, ideas: list[dict[str, Any]]) -> None:
    ideas_by_id = {idea["unique_id"]: idea for idea in ideas}
    for direction in plan.creative_directions:
        idea = ideas_by_id[direction.content_idea_id]
        allowed = set(idea.get("available_source_asset_ids", []))
        unknown = sorted(set(direction.reference_asset_ids) - allowed)
        if unknown:
            raise ValueError(
                f"Creative direction {direction.creative_direction_id} references unavailable source assets: {', '.join(unknown)}"
            )
        if idea.get("source_support_status") in {"fully_supported", "partially_supported"} and not direction.reference_asset_ids:
            raise ValueError(f"Creative direction {direction.creative_direction_id} must reference an approved source asset")


def _output_filename(content_plan_stem: str) -> str:
    return f"{content_plan_stem.removesuffix('-content-plan')}-creative-directions"
