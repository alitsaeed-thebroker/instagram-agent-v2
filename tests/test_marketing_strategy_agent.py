"""Unit tests for marketing strategy generation without API calls."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ai.agents.marketing_strategy_agent import (
    MAX_FACTS,
    MAX_OPPORTUNITIES,
    MAX_STRATEGY_INPUT_CHARS,
    MarketingStrategyAgent,
    build_strategy_context,
)
from src.knowledge.schema import ProjectDetails, ProjectIdentity, ProjectKnowledge
from src.strategy.schema import MarketingStrategy


def strategy_payload() -> str:
    return MarketingStrategy(
        project_summary="Palm Gardens is a residential project in Baghdad.",
        target_audience=["Families"],
        primary_marketing_angle="Garden-led family living",
        recommended_visual_style="Warm, contemporary photography",
        brand_tone_of_voice="Confident and welcoming",
        recommended_posting_frequency="Three posts per week",
    ).to_json()


class MarketingStrategyAgentTests(unittest.TestCase):
    def test_run_saves_valid_strategy_response(self) -> None:
        knowledge = ProjectKnowledge(project=ProjectDetails(name="Palm Gardens", location="Baghdad"))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "palm-gardens.json"
            source.write_text(knowledge.to_json(), encoding="utf-8")
            destination = Path(directory) / "strategy"
            agent = MarketingStrategyAgent(model="test-model")
            with (
                patch.object(agent, "_load_api_key", return_value="test-key"),
                patch.object(agent, "_request_strategy", return_value=strategy_payload()),
                patch("src.ai.agents.marketing_strategy_agent.save_marketing_strategy") as save,
            ):
                save.side_effect = lambda strategy, filename: _save(strategy, filename, destination)
                path = agent.run(source)
            self.assertEqual(path.name, "palm-gardens-strategy.json")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["primary_marketing_angle"], "Garden-led family living")

    def test_run_rejects_invalid_strategy_response(self) -> None:
        knowledge = ProjectKnowledge(project=ProjectDetails(name="Palm Gardens", location="Baghdad"))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "palm-gardens.json"
            source.write_text(knowledge.to_json(), encoding="utf-8")
            agent = MarketingStrategyAgent()
            with (
                patch.object(agent, "_load_api_key", return_value="test-key"),
                patch.object(agent, "_request_strategy", return_value='{"project_summary": "only one field"}'),
            ):
                self.assertIsNone(agent.run(source))

    def test_large_canonical_inputs_are_bounded_without_raw_provenance(self) -> None:
        knowledge = ProjectKnowledge(
            project=ProjectDetails(name="Beverly Hills", location="Erbil"),
            project_identity=ProjectIdentity(
                project_name="Beverly Hills", location="Erbil"
            ),
        )
        facts = [
            {
                "fact_id": f"fact_{index:04d}",
                "category": "unit" if index % 5 == 0 else "architecture",
                "text": "Verified source detail " + ("x" * 4_000),
                "truth_layer": "VERIFIED_FACT",
                "confidence": 0.95,
                "authority": "SOURCE_PROVENANCE",
                "freshness": "CURRENT_OR_NOT_TIME_SENSITIVE",
                "relationship_status": "VERIFIED",
                "claim_risk": "MEDIUM",
                "eligible": True,
                "provenance": [{"source": "catalogue.pdf", "page": index + 1}],
            }
            for index in range(500)
        ]
        opportunities = [
            {
                "opportunity_id": f"op_{index:03d}",
                "category": "unit" if index % 5 == 0 else "architecture",
                "title": "Opportunity " + ("y" * 1_000),
                "objective": "Explain verified evidence " + ("z" * 2_000),
                "supporting_fact_ids": [f"fact_{index:04d}"],
                "evidence_strength": 90,
                "visual_strength": 85,
                "score": 88,
                "status": "STRONG",
                "priority": "STRONG",
                "restrictions": [],
                "blocked_claims": [],
            }
            for index in range(200)
        ]
        reci = {
            "contract_role": "canonical_creative_opportunity_map",
            "project_id": "Beverly Hills",
            "facts": facts,
            "opportunities": opportunities,
            "audience_hypotheses": [],
        }
        campaign = {
            "contract_role": "canonical_campaign_decision_contract",
            "project_id": "Beverly Hills",
            "strategic_queue": [],
            "conditional_candidates": [],
        }
        context = build_strategy_context(knowledge, reci, campaign)
        encoded = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        self.assertLessEqual(len(encoded), MAX_STRATEGY_INPUT_CHARS)
        self.assertEqual(len(context["verified_fact_brief"]), MAX_FACTS)
        self.assertEqual(len(context["creative_opportunities"]), MAX_OPPORTUNITIES)
        self.assertTrue(
            all("provenance" not in fact for fact in context["verified_fact_brief"])
        )

    def test_referenced_unit_fact_and_plan_restriction_are_preserved(self) -> None:
        knowledge = ProjectKnowledge(
            project=ProjectDetails(name="Beverly Hills"),
            project_identity=ProjectIdentity(project_name="Beverly Hills"),
        )
        facts = [
            {
                "fact_id": f"fact_{index:03d}",
                "category": "educational",
                "text": f"Fact {index}",
                "authority": "SOURCE_PROVENANCE",
                "freshness": "CURRENT_OR_NOT_TIME_SENSITIVE",
                "relationship_status": "VERIFIED",
                "eligible": True,
                "provenance": [{"page": index + 1}],
            }
            for index in range(MAX_FACTS + 5)
        ]
        facts.append(
            {
                "fact_id": "fact_unit_dimensions",
                "category": "unit",
                "text": "Room dimensions are visible on the authentic plan.",
                "authority": "SOURCE_PROVENANCE",
                "freshness": "CURRENT_OR_NOT_TIME_SENSITIVE",
                "relationship_status": "VERIFIED",
                "eligible": True,
                "provenance": [{"page": 44}],
            }
        )
        reci = {
            "contract_role": "canonical_creative_opportunity_map",
            "project_id": "Beverly Hills",
            "facts": facts,
            "opportunities": [
                {
                    "opportunity_id": "unit_plan",
                    "category": "unit",
                    "supporting_fact_ids": ["fact_unit_dimensions"],
                    "status": "REVIEW_REQUIRED",
                    "layout_sensitive": True,
                    "restrictions": ["Exact unit relationship must remain verified."],
                    "blocked_claims": ["Do not infer missing dimensions."],
                }
            ],
        }
        context = build_strategy_context(knowledge, reci, None)
        fact_ids = {fact["fact_id"] for fact in context["verified_fact_brief"]}
        self.assertIn("fact_unit_dimensions", fact_ids)
        unit = context["creative_opportunities"][0]
        self.assertTrue(unit["layout_sensitive"])
        self.assertIn("Do not infer missing dimensions.", unit["blocked_claims"])
        self.assertEqual(
            context["source_truth_policy"]["campaign_sequence"][3], "unit_plans"
        )

    def test_cross_project_context_is_rejected(self) -> None:
        knowledge = ProjectKnowledge(
            project=ProjectDetails(name="Beverly Hills"),
            project_identity=ProjectIdentity(project_name="Beverly Hills"),
        )
        reci = {
            "contract_role": "canonical_creative_opportunity_map",
            "project_id": "Another Project",
        }
        with self.assertRaisesRegex(ValueError, "another project"):
            build_strategy_context(knowledge, reci, None)


def _save(strategy: MarketingStrategy, filename: str, directory: Path) -> Path:
    directory.mkdir()
    path = directory / f"{filename}.json"
    path.write_text(strategy.to_json(), encoding="utf-8")
    return path
