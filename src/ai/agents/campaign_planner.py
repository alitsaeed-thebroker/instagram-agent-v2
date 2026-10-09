"""OpenAI-backed generation of validated campaign planning JSON."""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

from src.campaign.schema import CampaignPlan
from src.campaign.storage import save_campaign_plan
from src.core.logger import get_logger
from src.strategy.schema import MarketingStrategy

DEFAULT_MODEL = "gpt-4o-mini"


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_POST_SCHEMA = _object({
    "post_number": {"type": "integer", "minimum": 1}, "title": {"type": "string"},
    "content_goal": {"type": "string"}, "visual_concept": {"type": "string"},
    "image_orientation": {"type": "string", "enum": ["Square", "Portrait", "Landscape"]},
    "suggested_platform": {"type": "string", "enum": ["Instagram Feed", "Instagram Carousel", "Instagram Story", "Facebook", "LinkedIn", "Website"]},
    "priority": {"type": "string"},
})
CAMPAIGN_PLAN_JSON_SCHEMA = _object({
    "campaigns": {"type": "array", "items": _object({
        "campaign_name": {"type": "string"}, "objective": {"type": "string"},
        "target_audience": {"type": "string"}, "marketing_message": {"type": "string"},
        "emotional_trigger": {"type": "string"}, "priority": {"type": "string"},
        "recommended_number_of_posts": {"type": "integer", "minimum": 0},
        "posts": {"type": "array", "items": _POST_SCHEMA},
    })},
})


class CampaignPlanner:
    """Transform a validated marketing strategy into a reusable campaign plan."""

    def __init__(self, model: str | None = None) -> None:
        self.logger = get_logger(__name__)
        self.model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

    def run(self, strategy_path: Path, performance_learning_path: Path | None = None) -> Path | None:
        """Read strategy JSON, generate a validated campaign plan, and save it."""
        self.logger.info("Reading strategy...")
        try:
            strategy = MarketingStrategy.from_json(strategy_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            self.logger.error("Could not read valid strategy JSON: %s", error)
            return None
        api_key = self._load_api_key()
        if not api_key:
            return None
        self.logger.info("Generating campaign plan...")
        try:
            request_input = strategy.to_json()
            if performance_learning_path and performance_learning_path.is_file():
                from src.performance.integration import campaign_planner_context
                learning=campaign_planner_context(json.loads(performance_learning_path.read_text(encoding="utf-8")))
                request_input=json.dumps({"marketing_strategy":strategy.to_dict(),"performance_learning":learning},ensure_ascii=False)
            plan = CampaignPlan.from_json(self._request_plan(request_input, api_key))
        except Exception as error:
            self.logger.error("Campaign Planner API request or response validation failed: %s", error)
            return None
        try:
            output_path = save_campaign_plan(plan, _campaign_filename(strategy_path.stem))
        except (OSError, ValueError) as error:
            self.logger.error("Could not save campaign plan JSON: %s", error)
            return None
        self.logger.info("Campaign plan saved.")
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

    def _request_plan(self, strategy_json: str, api_key: str) -> str:
        from openai import OpenAI

        response = OpenAI(api_key=api_key).responses.create(
            model=self.model,
            instructions="""You are a senior real-estate campaign planner. Create a complete, reusable content plan using only the supplied marketing strategy JSON.

Build campaigns with clear, distinct purposes from the strategy's themes, pillars, audiences, selling points, and emotional triggers. Optional performance_learning is account-specific, confidence-aware, advisory context: use it for category/format balance and fatigue awareness only. Never let it introduce or alter facts, suppress required campaign roles, or cause repetitive overfitting. Create only decisions about WHAT content should exist. Do not generate image prompts, captions, images, hashtags, calls to action, or prose outside the required JSON object. Do not invent project facts. The number of posts must exactly equal the number of post objects in every campaign. Return valid JSON only, matching the supplied schema exactly.""",
            input=strategy_json,
            text={"format": {"type": "json_schema", "name": "campaign_plan", "strict": True, "schema": CAMPAIGN_PLAN_JSON_SCHEMA}},
        )
        if not response.output_text:
            raise ValueError("The API returned no JSON output")
        return response.output_text


def _campaign_filename(strategy_stem: str) -> str:
    return f"{strategy_stem.removesuffix('-strategy')}-campaigns"
