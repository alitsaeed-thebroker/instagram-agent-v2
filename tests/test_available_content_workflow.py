"""Tests for inventory-grounded content planning and per-item skipping."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.ai.agents.content_planner import _rank_and_assign_semantic_assets, _remove_unavailable_ideas, _repair_inventory_grounding, _validate_inventory_grounding
from src.knowledge.schema import Architecture, ProjectDetails, ProjectKnowledge
from src.visual_assets.analysis import analyze_visual_assets
from src.visual_assets.extraction import extract_visual_assets
from src.visual_assets.inventory import create_available_content_inventory
from tests.test_authentic_visual_workflow import _image
from tests.test_scene_planner import _content_plan


class AvailableContentWorkflowTests(unittest.TestCase):
    def test_inventory_contains_text_facts_and_source_asset_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge_path = root / "Project.json"
            knowledge_path.write_text(ProjectKnowledge(
                project=ProjectDetails(name="Project", location="Erbil"),
                architecture=Architecture(materials=["Natural stone"]),
            ).to_json(), encoding="utf-8")
            manifest = extract_visual_assets("Project", [], [_image(root / "Exterior.jpg")], root / "source")
            analysis = analyze_visual_assets(manifest, root / "analysis")
            inventory_path = create_available_content_inventory(knowledge_path, manifest, analysis, root / "inventory")
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            self.assertTrue(inventory["available_text_facts"])
            self.assertEqual(inventory["available_exterior_images"][0]["source_document"], "Exterior.jpg")
            self.assertEqual(inventory["available_exterior_images"][0]["source_page"], None)
            self.assertIn(inventory["available_exterior_images"][0]["asset_id"], inventory["all_source_asset_ids"])

    def test_unknown_asset_ids_are_removed_before_validation(self) -> None:
        plan = _content_plan()
        idea = plan.pillars[0].content_ideas[0]
        idea.source_support_status = "fully_supported"
        idea.available_source_asset_ids = ["invented_asset"]
        _repair_inventory_grounding(plan, {"project": "Current", "all_source_asset_ids": ["approved_asset"]})
        _validate_inventory_grounding(plan, {"project": "Current", "all_source_asset_ids": ["approved_asset"]})
        self.assertEqual(idea.available_source_asset_ids, [])
        self.assertEqual(idea.source_support_status, "unavailable")

    def test_valid_asset_ids_are_preserved(self) -> None:
        plan = _content_plan()
        idea = plan.pillars[0].content_ideas[0]
        idea.source_support_status = "fully_supported"
        idea.required_source_asset_ids = ["current_asset"]
        idea.available_source_asset_ids = ["current_asset"]
        idea.selected_source_asset_ids = ["current_asset"]
        _repair_inventory_grounding(plan, {"project": "Current", "all_source_asset_ids": ["current_asset"]})
        _validate_inventory_grounding(plan, {"project": "Current", "all_source_asset_ids": ["current_asset"]})
        self.assertEqual(idea.selected_source_asset_ids, ["current_asset"])

    def test_mixed_valid_and_invalid_ids_are_filtered(self) -> None:
        plan = _content_plan()
        idea = plan.pillars[0].content_ideas[0]
        idea.available_source_asset_ids = ["valid", "hallucinated", "valid"]
        idea.required_source_asset_ids = ["other_project", "valid"]
        _repair_inventory_grounding(plan, {"project": "Current", "all_source_asset_ids": ["valid"]})
        self.assertEqual(idea.available_source_asset_ids, ["valid"])
        self.assertEqual(idea.required_source_asset_ids, ["valid"])

    def test_empty_inventory_downgrades_to_text_only_when_text_exists(self) -> None:
        plan = _content_plan()
        idea = plan.pillars[0].content_ideas[0]
        idea.source_support_status = "fully_supported"
        idea.available_source_asset_ids = ["missing"]
        idea.text_evidence = ["project.location"]
        _repair_inventory_grounding(plan, {"project": "Current", "all_source_asset_ids": []})
        self.assertEqual(idea.source_support_status, "text_only")

    def test_project_isolation_removes_foreign_asset(self) -> None:
        plan = _content_plan()
        idea = plan.pillars[0].content_ideas[0]
        idea.available_source_asset_ids = ["project_b_asset"]
        _repair_inventory_grounding(plan, {"project": "Project A", "all_source_asset_ids": ["project_a_asset"]})
        self.assertEqual(idea.available_source_asset_ids, [])

    def test_unavailable_idea_is_skipped_while_feasible_idea_continues(self) -> None:
        plan = _content_plan()
        unavailable = plan.pillars[0].content_ideas[0]
        unavailable.source_support_status = "unavailable"
        feasible = type(unavailable)(**{
            **unavailable.__dict__, "unique_id": "text_01", "title": "Verified facts",
            "source_support_status": "text_only", "text_evidence": ["project.location"],
        })
        plan.pillars[0].content_ideas.append(feasible)
        filtered, report = _remove_unavailable_ideas(plan)
        self.assertEqual([item.unique_id for item in filtered.pillars[0].content_ideas], ["text_01"])
        self.assertEqual(report["summary"]["text_only"], 1)
        self.assertEqual(report["summary"]["skipped_unavailable"], 1)

    def test_content_planner_selects_semantically_matching_asset(self) -> None:
        plan = _content_plan()
        inventory = _semantic_inventory([
            _semantic_asset("exterior_1", "exterior", ["villa exterior"]),
            _semantic_asset("interior_1", "interior", ["living room"]),
        ])
        _rank_and_assign_semantic_assets(plan, inventory)
        idea = plan.pillars[0].content_ideas[0]
        self.assertEqual(idea.available_source_asset_ids, ["exterior_1"])
        self.assertNotIn("invented_asset", idea.available_source_asset_ids)
        self.assertNotEqual(idea.source_support_status, "text_only")

    def test_content_planner_avoids_unsupported_lifestyle_story(self) -> None:
        plan = _content_plan()
        idea = plan.pillars[0].content_ideas[0]
        idea.title = "Families enjoying the project"
        idea.story = "A resident family shares dinner beside the pool"
        idea.main_subject = "Resident family"
        _rank_and_assign_semantic_assets(plan, _semantic_inventory([
            _semantic_asset("exterior_1", "exterior", ["villa exterior"], contains_people=False),
        ]))
        self.assertEqual(idea.source_support_status, "unavailable")
        self.assertEqual(idea.available_source_asset_ids, [])


def _semantic_asset(asset_id: str, asset_type: str, features: list[str], contains_people: bool = False) -> dict:
    return {
        "asset_id": asset_id, "asset_type": asset_type, "asset_subtype": "", "confidence": 0.9,
        "analysis_status": "analyzed", "marketing_suitability": "feed_ready",
        "image_quality": {"score": 80}, "visible_project_features": features,
        "contains_people": contains_people, "recommended_platforms": ["Instagram Feed"],
        "orientation": "portrait", "safe_crop_assessment": {"level": "flexible"},
    }


def _semantic_inventory(assets: list[dict]) -> dict:
    inventory = {"project": "Current", "inventory_type": "semantic", "all_source_asset_ids": [item["asset_id"] for item in assets]}
    for asset in assets:
        field = "available_exterior_images" if asset["asset_type"] == "exterior" else "available_interior_images"
        inventory.setdefault(field, []).append(asset)
    return inventory
