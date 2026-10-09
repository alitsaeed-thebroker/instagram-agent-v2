"""Unit tests for campaign planning without API calls."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ai.agents.campaign_planner import CampaignPlanner
from src.campaign.schema import Campaign, CampaignPlan, CampaignPost
from src.strategy.schema import MarketingStrategy


def campaign_payload() -> str:
    return CampaignPlan(campaigns=[Campaign(
        campaign_name="Luxury Lifestyle", objective="Showcase refined living", target_audience="Luxury buyers",
        marketing_message="A distinctive residential lifestyle", emotional_trigger="Prestige", priority="High",
        recommended_number_of_posts=1, posts=[CampaignPost(
            post_number=1, title="A life of distinction", content_goal="Introduce the lifestyle proposition",
            visual_concept="Hero exterior and landscaped setting", image_orientation="Portrait",
            suggested_platform="Instagram Feed", priority="High",
        )],
    )]).to_json()


class CampaignPlannerTests(unittest.TestCase):
    def test_run_saves_valid_campaign_plan(self) -> None:
        strategy = MarketingStrategy(project_summary="A residential project")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "palm-gardens-strategy.json"
            source.write_text(strategy.to_json(), encoding="utf-8")
            destination = Path(directory) / "campaigns"
            planner = CampaignPlanner(model="test-model")
            with (
                patch.object(planner, "_load_api_key", return_value="test-key"),
                patch.object(planner, "_request_plan", return_value=campaign_payload()),
                patch("src.ai.agents.campaign_planner.save_campaign_plan") as save,
            ):
                save.side_effect = lambda plan, filename: _save(plan, filename, destination)
                path = planner.run(source)
            self.assertEqual(path.name, "palm-gardens-campaigns.json")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["campaigns"][0]["campaign_name"], "Luxury Lifestyle")

    def test_run_rejects_invalid_campaign_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "palm-gardens-strategy.json"
            source.write_text(MarketingStrategy().to_json(), encoding="utf-8")
            planner = CampaignPlanner()
            with (
                patch.object(planner, "_load_api_key", return_value="test-key"),
                patch.object(planner, "_request_plan", return_value='{"campaigns": [{"campaign_name": "missing fields"}]}'),
            ):
                self.assertIsNone(planner.run(source))

    def test_campaign_plan_rejects_unsupported_post_format(self) -> None:
        payload = json.loads(campaign_payload())
        payload["campaigns"][0]["posts"][0]["image_orientation"] = "Vertical"
        with self.assertRaisesRegex(ValueError, "image_orientation"):
            CampaignPlan.from_dict(payload)

    def test_campaign_plan_requires_post_count_to_match_posts(self) -> None:
        payload = json.loads(campaign_payload())
        payload["campaigns"][0]["recommended_number_of_posts"] = 2
        with self.assertRaisesRegex(ValueError, "recommended_number_of_posts"):
            CampaignPlan.from_dict(payload)

    def test_run_handles_api_failure_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "palm-gardens-strategy.json"
            source.write_text(MarketingStrategy().to_json(), encoding="utf-8")
            planner = CampaignPlanner()
            with (
                patch.object(planner, "_load_api_key", return_value="test-key"),
                patch.object(planner, "_request_plan", side_effect=RuntimeError("service unavailable")),
            ):
                self.assertIsNone(planner.run(source))


def _save(plan: CampaignPlan, filename: str, directory: Path) -> Path:
    directory.mkdir()
    path = directory / f"{filename}.json"
    path.write_text(plan.to_json(), encoding="utf-8")
    return path
