"""OpenAI-backed generation of validated marketing strategy JSON."""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

from src.core.logger import get_logger
from src.knowledge.schema import ProjectKnowledge
from src.strategy.schema import MarketingStrategy
from src.strategy.storage import save_marketing_strategy

DEFAULT_MODEL = "gpt-4o-mini"
STRATEGY_CONTEXT_VERSION = "1.3.0"
MAX_STRATEGY_INPUT_CHARS = 90_000
MAX_FACTS = 60
MAX_OPPORTUNITIES = 20
MAX_CAMPAIGN_DECISIONS = 10
_CATEGORY_ORDER = {
    "project": 0,
    "architecture": 1,
    "interior": 2,
    "unit": 3,
    "amenity": 4,
    "lifestyle": 5,
    "location": 6,
    "commercial": 7,
    "investment": 8,
    "educational": 9,
    "conversion": 10,
}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


MARKETING_STRATEGY_JSON_SCHEMA = _object({
    "project_summary": {"type": "string"},
    "target_audience": {"type": "array", "items": {"type": "string"}},
    "buyer_personas": {"type": "array", "items": _object({
        "name": {"type": "string"}, "description": {"type": "string"},
        "motivations": {"type": "array", "items": {"type": "string"}},
        "concerns": {"type": "array", "items": {"type": "string"}},
    })},
    "primary_marketing_angle": {"type": "string"},
    "secondary_marketing_angles": {"type": "array", "items": {"type": "string"}},
    "emotional_triggers": {"type": "array", "items": {"type": "string"}},
    "key_selling_points": {"type": "array", "items": {"type": "string"}},
    "recommended_campaign_themes": {"type": "array", "items": {"type": "string"}},
    "recommended_visual_style": {"type": "string"},
    "brand_tone_of_voice": {"type": "string"},
    "recommended_content_pillars": {"type": "array", "items": {"type": "string"}},
    "recommended_social_media_platforms": {"type": "array", "items": {"type": "string"}},
    "recommended_posting_frequency": {"type": "string"},
    "calls_to_action": {"type": "array", "items": {"type": "string"}},
})


def _bounded_text(value: Any, limit: int = 600) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _bounded_strings(value: Any, *, count: int = 12, chars: int = 240) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_bounded_text(item, chars) for item in value[:count] if str(item or "").strip()]


def _compact_fact(fact: dict[str, Any]) -> dict[str, Any]:
    provenance = fact.get("provenance")
    source_supported = bool(provenance) or fact.get("authority") == "SOURCE_PROVENANCE"
    freshness = str(fact.get("freshness") or "UNKNOWN").upper()
    relationship = str(fact.get("relationship_status") or "UNKNOWN").upper()
    truth_layer = str(fact.get("truth_layer") or "UNKNOWN")
    claim_eligible = bool(fact.get("eligible")) and source_supported and freshness not in {
        "STALE", "EXPIRED"
    } and relationship not in {"CONFLICTED", "AMBIGUOUS", "UNVERIFIED"}
    return {
        "fact_id": str(fact.get("fact_id") or ""),
        "category": str(fact.get("category") or "educational"),
        "text": _bounded_text(fact.get("text") or fact.get("value"), 600),
        "truth_layer": truth_layer,
        "confidence": fact.get("confidence"),
        "authority": str(fact.get("authority") or "UNKNOWN"),
        "freshness": freshness,
        "relationship_status": relationship,
        "claim_risk": str(fact.get("claim_risk") or "UNKNOWN"),
        "source_supported": source_supported,
        "claim_eligible": claim_eligible,
    }


def _compact_opportunity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "opportunity_id": str(item.get("opportunity_id") or ""),
        "category": str(item.get("category") or "educational"),
        "title": _bounded_text(item.get("title"), 180),
        "objective": _bounded_text(item.get("objective"), 320),
        "buyer_value": _bounded_strings(item.get("buyer_value"), count=8),
        "recommended_message": _bounded_text(item.get("recommended_message"), 360),
        "supporting_fact_ids": _bounded_strings(
            item.get("supporting_fact_ids"), count=16, chars=120
        ),
        "evidence_strength": item.get("evidence_strength"),
        "visual_strength": item.get("visual_strength"),
        "score": item.get("score"),
        "status": str(item.get("status") or "UNKNOWN"),
        "priority": str(item.get("priority") or "UNKNOWN"),
        "layout_sensitive": bool(item.get("layout_sensitive")),
        "recommended_formats": _bounded_strings(
            item.get("recommended_formats"), count=6, chars=100
        ),
        "recommended_platforms": _bounded_strings(
            item.get("recommended_platforms"), count=4, chars=80
        ),
        "restrictions": _bounded_strings(item.get("restrictions"), count=12),
        "blocked_claims": _bounded_strings(item.get("blocked_claims"), count=12),
    }


def _compact_audience(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "hypothesis_id": str(item.get("hypothesis_id") or ""),
        "truth_layer": str(item.get("truth_layer") or "AUDIENCE_HYPOTHESIS"),
        "audience_type": _bounded_text(item.get("audience_type"), 120),
        "reason": _bounded_text(item.get("reason"), 320),
        "supporting_fact_ids": _bounded_strings(
            item.get("supporting_facts"), count=10, chars=120
        ),
        "confidence": item.get("confidence"),
        "status": str(item.get("status") or "HYPOTHESIS"),
    }


def _compact_decision(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    audience = item.get("audience") if isinstance(item.get("audience"), dict) else {}
    return {
        "decision_id": str(item.get("decision_id") or ""),
        "campaign_role": str(item.get("campaign_role") or ""),
        "objective": _bounded_text(item.get("objective"), 300),
        "reason": _bounded_text(item.get("reason"), 420),
        "why_now": _bounded_text(item.get("why_now"), 300),
        "reci_opportunity_id": str(item.get("reci_opportunity_id") or ""),
        "supporting_fact_ids": _bounded_strings(
            item.get("supporting_fact_ids"), count=16, chars=120
        ),
        "candidate_asset_ids": _bounded_strings(
            item.get("candidate_asset_ids"), count=12, chars=120
        ),
        "platform": _bounded_text(item.get("platform"), 80),
        "format": _bounded_text(item.get("format"), 80),
        "audience": {
            "truth_layer": str(audience.get("truth_layer") or "AUDIENCE_HYPOTHESIS"),
            "value": _bounded_text(audience.get("value"), 180),
            "confidence": audience.get("confidence"),
        },
        "content_angle": _bounded_text(item.get("content_angle"), 300),
        "claim_policy": str(item.get("claim_policy") or "NONE"),
        "cta_intent": str(item.get("cta_intent") or "NONE"),
        "priority": item.get("priority"),
        "confidence": item.get("confidence"),
        "status": str(item.get("status") or "UNKNOWN"),
        "restrictions": _bounded_strings(item.get("restrictions"), count=12),
        "blocked_claims": _bounded_strings(item.get("blocked_claims"), count=12),
    }


def build_strategy_context(
    knowledge: ProjectKnowledge,
    creative_map: dict[str, Any] | None = None,
    campaign_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded, source-controlled advisory payload."""
    creative_map = creative_map or {}
    campaign_contract = campaign_contract or {}
    identity = knowledge.to_dict().get("project_identity", {})
    project_name = str(identity.get("project_name") or knowledge.project.name)
    map_project = str(creative_map.get("project_id") or project_name)
    campaign_project = str(campaign_contract.get("project_id") or project_name)
    if map_project and project_name and map_project.casefold() != project_name.casefold():
        raise ValueError("Creative Opportunity Map belongs to another project")
    if campaign_project and project_name and campaign_project.casefold() != project_name.casefold():
        raise ValueError("Campaign Decision Contract belongs to another project")

    raw_opportunities = [
        item for item in (creative_map.get("opportunities") or []) if isinstance(item, dict)
    ]
    raw_decisions = [
        item
        for key in ("strategic_queue", "conditional_candidates")
        for item in (campaign_contract.get(key) or [])
        if isinstance(item, dict)
    ]
    referenced_fact_ids = {
        str(fact_id)
        for item in [*raw_opportunities, *raw_decisions]
        for fact_id in item.get("supporting_fact_ids", [])
    }
    raw_facts = [item for item in (creative_map.get("facts") or []) if isinstance(item, dict)]
    raw_facts.sort(
        key=lambda item: (
            0 if str(item.get("fact_id")) in referenced_fact_ids else 1,
            _CATEGORY_ORDER.get(str(item.get("category") or "educational"), 99),
            str(item.get("fact_id") or ""),
        )
    )
    facts = [_compact_fact(item) for item in raw_facts[:MAX_FACTS]]
    raw_opportunities.sort(
        key=lambda item: (
            _CATEGORY_ORDER.get(str(item.get("category") or "educational"), 99),
            1 if item.get("status") in {"BLOCKED", "REVIEW_REQUIRED"} else 0,
            -int(item.get("score") or 0),
            str(item.get("opportunity_id") or ""),
        )
    )
    opportunities = [
        _compact_opportunity(item) for item in raw_opportunities[:MAX_OPPORTUNITIES]
    ]
    audiences = [
        _compact_audience(item)
        for item in (creative_map.get("audience_hypotheses") or [])[:10]
        if isinstance(item, dict)
    ]

    def decisions(key: str) -> list[dict[str, Any]]:
        values = []
        for item in (campaign_contract.get(key) or [])[:MAX_CAMPAIGN_DECISIONS]:
            compact = _compact_decision(item)
            if compact is not None:
                values.append(compact)
        return values

    next_best = _compact_decision(campaign_contract.get("next_best_content"))
    payload = {
        "contract_role": "legacy_marketing_strategy_advisory_input",
        "context_version": STRATEGY_CONTEXT_VERSION,
        "project_id": project_name,
        "project_identity": {
            key: _bounded_text(value, 240)
            for key, value in identity.items()
            if str(value or "").strip()
        },
        "source_truth_policy": {
            "facts_without_claim_eligible_true_must_not_be_public_claims": True,
            "audiences_are_hypotheses": True,
            "blocked_and_review_required_items_are_binding": True,
            "missing_information_must_remain_missing": True,
            "campaign_sequence": [
                "project_masterplan",
                "exterior_architecture",
                "interior_design",
                "unit_plans",
                "landscaping_community_lifestyle",
            ],
            "unit_plan_rule": (
                "Use only exact source-visible unit numbers, labels, areas and dimensions; "
                "never infer, redraw or repair missing details."
            ),
        },
        "verified_fact_brief": facts,
        "audience_hypotheses": audiences,
        "creative_opportunities": opportunities,
        "global_weaknesses": _bounded_strings(
            creative_map.get("weaknesses"), count=20, chars=320
        ),
        "global_restrictions": _bounded_strings(
            creative_map.get("restrictions"), count=20, chars=320
        ),
        "campaign_decision_brief": {
            "campaign_stage": str(campaign_contract.get("campaign_stage") or "UNKNOWN"),
            "next_best_content": next_best,
            "strategic_queue": decisions("strategic_queue"),
            "conditional_candidates": decisions("conditional_candidates"),
            "contract_hash": str(campaign_contract.get("contract_hash") or ""),
        },
        "compaction": {
            "full_provenance_retained_upstream": True,
            "facts_available": len(raw_facts),
            "facts_included": len(facts),
            "opportunities_available": len(raw_opportunities),
            "opportunities_included": len(opportunities),
            "omitted_information_is_not_authorized_for_inference": True,
        },
    }
    size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    if size > MAX_STRATEGY_INPUT_CHARS:
        raise ValueError(
            f"Compacted marketing-strategy input is still too large: {size} characters"
        )
    payload["compaction"]["input_characters"] = size
    payload["compaction"]["maximum_characters"] = MAX_STRATEGY_INPUT_CHARS
    return payload


class MarketingStrategyAgent:
    """Transform a validated knowledge artifact into a marketing strategy artifact."""

    def __init__(self, model: str | None = None) -> None:
        self.logger = get_logger(__name__)
        self.model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

    def run(self, knowledge_path: Path, creative_intelligence_path: Path | None = None,
            campaign_intelligence_path: Path | None = None) -> Path | None:
        """Read knowledge JSON, generate validated strategy JSON, and save it."""
        self.logger.info("Reading knowledge JSON: %s", knowledge_path.name)
        try:
            knowledge = ProjectKnowledge.from_json(knowledge_path.read_text(encoding="utf-8"))
            errors = knowledge.validate()
            if errors:
                raise ValueError("; ".join(errors))
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            self.logger.error("Could not read valid knowledge JSON: %s", error)
            return None

        api_key = self._load_api_key()
        if not api_key:
            return None
        self.logger.info("Generating marketing strategy with %s...", self.model)
        try:
            creative_map: dict[str, Any] | None = None
            campaign_contract: dict[str, Any] | None = None
            if creative_intelligence_path is not None:
                creative_map=json.loads(creative_intelligence_path.read_text(encoding="utf-8"))
                if creative_map.get("contract_role")!="canonical_creative_opportunity_map":raise ValueError("Invalid Creative Opportunity Map")
            if campaign_intelligence_path is not None:
                campaign_contract=json.loads(campaign_intelligence_path.read_text(encoding="utf-8"))
                if campaign_contract.get("contract_role")!="canonical_campaign_decision_contract":raise ValueError("Invalid Campaign Decision Contract")
                if creative_map is not None and campaign_contract.get("project_id")!=creative_map.get("project_id"):raise ValueError("Campaign Decision Contract project mismatch")
            request_payload = build_strategy_context(
                knowledge, creative_map, campaign_contract
            )
            response_text = self._request_strategy(
                json.dumps(request_payload, ensure_ascii=False, separators=(",", ":")),
                api_key,
            )
        except Exception as error:
            self.logger.error("OpenAI API request failed while generating strategy: %s", error)
            return None

        self.logger.info("Validating returned marketing strategy JSON...")
        try:
            strategy = MarketingStrategy.from_json(response_text)
        except (TypeError, ValueError) as error:
            self.logger.error("OpenAI returned invalid marketing strategy: %s", error)
            return None

        try:
            output_path = save_marketing_strategy(strategy, f"{knowledge_path.stem}-strategy")
        except (OSError, ValueError) as error:
            self.logger.error("Could not save marketing strategy JSON: %s", error)
            return None
        self.logger.info("Marketing strategy complete. Saved: %s", output_path)
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

    def _request_strategy(self, strategy_context_json: str, api_key: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=self.model,
            instructions="""You are a senior real-estate marketing strategist. Create one actionable,
structured marketing strategy using only the supplied compact, source-controlled
strategy context. Full provenance remains upstream and is referenced through
fact IDs; omitted information is not permission to infer it.

Do not invent project facts, prices, locations, features, performance claims, or
unsupported buyer attributes. You may make strategic recommendations (angles,
themes, content pillars, visual style, platforms, cadence, and calls to action)
based on the supplied evidence. Where evidence is insufficient, use an empty
string or empty list rather than asserting a fact. Do not generate captions,
image prompts, images, or prose outside the required JSON object.

Treat Creative Opportunity Map restrictions, BLOCKED, and REVIEW_REQUIRED items
as binding. Audience entries marked HYPOTHESIS remain hypotheses, not facts.
Only facts with claim_eligible=true may become project-specific selling points.
Follow the supplied five-stage real-estate campaign sequence. Treat unit plans
as technical evidence and never infer dimensions, areas, labels, relationships,
or unit numbers that are not explicitly authorized in the context.
Treat the optional Campaign Decision Contract as the campaign-level authority for
WHAT and WHY to prioritize. Do not contradict its restrictions or activate its
conditional/blocked candidates. It does not authorize scheduling or publishing.

Return valid JSON only, matching the supplied schema exactly.""",
            input=strategy_context_json,
            text={"format": {"type": "json_schema", "name": "marketing_strategy", "strict": True, "schema": MARKETING_STRATEGY_JSON_SCHEMA}},
        )
        if not response.output_text:
            raise ValueError("The API returned no JSON output")
        return response.output_text
