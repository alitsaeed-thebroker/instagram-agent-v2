"""Unit tests for Content Planner behavior without API calls."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ai.agents.content_planner import ContentPlanner
from src.content.schema import ContentIdea, ContentPillar, ContentPlan
from src.knowledge.schema import ProjectDetails, ProjectKnowledge
from src.strategy.schema import MarketingStrategy


def content_payload() -> str:
    idea = ContentIdea(
        unique_id="luxury-001", title="Morning light at Beverly Hills",
        story="Morning light moves across floor-to-ceiling windows as a family shares breakfast in an open-plan living space.",
        purpose="Introduce the refined residential experience.", target_audience="Luxury family homebuyers",
        emotion="Belonging", marketing_goal="Build lifestyle consideration", recommended_platform="Instagram",
        recommended_format="Carousel", image_orientation="Portrait", priority="High",
        main_subject="Floor-to-ceiling windows and open-plan living", supporting_subjects=["Family", "Breakfast setting"],
        environment="A supported villa living space", time_of_day="Morning", weather="Soft clear daylight",
        mood="Quietly aspirational", color_palette="Warm neutrals and natural stone", camera_style="Cinematic editorial photography",
        recommended_lens="35mm", composition="Wide interior framing with layered foreground", 
        visual_keywords=["cinematic", "natural light", "premium lifestyle"], future_asset_type="Instagram Carousel",
    )
    return ContentPlan(pillars=[ContentPillar(name="Luxury Lifestyle", content_ideas=[idea])]).to_json()


class ContentPlannerTests(unittest.TestCase):
    def test_run_saves_plan_from_both_inputs(self) -> None:
        knowledge = ProjectKnowledge(project=ProjectDetails(name="Palm Gardens", location="Baghdad"))
        strategy = MarketingStrategy(project_summary="A residential project")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge_path = root / "palm-gardens.json"
            strategy_path = root / "palm-gardens-strategy.json"
            knowledge_path.write_text(knowledge.to_json(), encoding="utf-8")
            strategy_path.write_text(strategy.to_json(), encoding="utf-8")
            planner = ContentPlanner(model="test-model")
            destination = root / "content"
            with (
                patch.object(planner, "_load_api_key", return_value="test-key"),
                patch.object(planner, "_request_plan", return_value=content_payload()) as request,
                patch("src.ai.agents.content_planner.save_content_plan") as save,
            ):
                save.side_effect = lambda plan, filename: _save(plan, filename, destination)
                path = planner.run(knowledge_path, strategy_path)
            self.assertEqual(path.name, "palm-gardens-content-plan.json")
            request.assert_called_once()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["pillars"][0]["content_ideas"][0]["unique_id"], "luxury-001")

    def test_rejects_duplicate_ids_and_unsupported_asset_type(self) -> None:
        payload = json.loads(content_payload())
        duplicate = payload["pillars"][0]["content_ideas"][0].copy()
        duplicate["future_asset_type"] = "TikTok"
        payload["pillars"].append({"name": "Architecture", "content_ideas": [duplicate]})
        with self.assertRaisesRegex(ValueError, "unique_id|future_asset_type"):
            ContentPlan.from_dict(payload)

    def test_run_handles_api_failure_gracefully(self) -> None:
        knowledge = ProjectKnowledge(project=ProjectDetails(name="Palm Gardens", location="Baghdad"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge_path = root / "palm-gardens.json"
            strategy_path = root / "palm-gardens-strategy.json"
            knowledge_path.write_text(knowledge.to_json(), encoding="utf-8")
            strategy_path.write_text(MarketingStrategy().to_json(), encoding="utf-8")
            planner = ContentPlanner()
            with (
                patch.object(planner, "_load_api_key", return_value="test-key"),
                patch.object(planner, "_request_plan", side_effect=RuntimeError("service unavailable")),
            ):
                self.assertIsNone(planner.run(knowledge_path, strategy_path))


def _save(plan: ContentPlan, filename: str, directory: Path) -> Path:
    directory.mkdir()
    path = directory / f"{filename}.json"
    path.write_text(plan.to_json(), encoding="utf-8")
    return path
