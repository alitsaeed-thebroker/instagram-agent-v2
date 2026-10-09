"""Tests for deterministic source-asset framing assembly."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.ai.agents.shot_planner import ShotPlanner, _assemble_shot_plans, _parse_recommendations
from src.knowledge.schema import Architecture, ProjectDetails, ProjectKnowledge
from src.shots.schema import ShotPlanCollection
from tests.test_scene_planner import _creative_directions, _scene_collection


def _recommendation() -> dict[str, object]:
    return {
        "layout_type": "single_source_image", "crop_strategy": "preserve_full_subject",
        "safe_zoom": "none", "aspect_ratios": ["4:5", "1:1"],
        "text_safe_area": "Natural empty space only", "logo_safe_area": "Bottom corner",
        "enhancement_notes": ["Non-destructive correction only"],
        "platforms": ["Instagram Feed"],
    }


def _supported_scenes(asset_ids: list[str] | None = None):
    scenes = _scene_collection()
    for scene in scenes.scene_plans[0].scenes:
        scene.reusable_asset_ids = list(asset_ids or ["asset_a"])
    return scenes


class DeterministicAssemblyTests(unittest.TestCase):
    def test_ai_omits_one_scene_and_fallback_completes_coverage(self) -> None:
        collection = _assemble_shot_plans(_supported_scenes(), {}, {"asset_a"}, [_recommendation()])
        groups = collection.shot_plans[0].scene_framing_groups
        self.assertEqual(len(groups), 2)
        self.assertEqual(collection.summary.fallback_plans_created, 1)

    def test_ai_omits_every_scene(self) -> None:
        collection = _assemble_shot_plans(_supported_scenes(), {}, {"asset_a"}, [])
        self.assertEqual(collection.summary.scenes_processed, 2)
        self.assertEqual(collection.summary.fallback_plans_created, 2)

    def test_unknown_ai_asset_and_forbidden_fields_are_ignored(self) -> None:
        raw = {**_recommendation(), "source_asset_ids": ["hallucinated"], "camera_angle": "low"}
        recommendations, warnings = _parse_recommendations(json.dumps({"recommendations": [raw]}))
        self.assertNotIn("source_asset_ids", recommendations[0])
        self.assertNotIn("camera_angle", recommendations[0])
        self.assertTrue(warnings)

    def test_foreign_project_asset_is_removed(self) -> None:
        collection = _assemble_shot_plans(
            _supported_scenes(["320_asset", "vision_asset"]), {}, {"320_asset"}, [],
        )
        self.assertEqual(collection.shot_plans[0].scene_framing_groups[0].source_asset_ids, ["320_asset"])
        self.assertEqual(collection.summary.invalid_asset_references_removed, 2)

    def test_mixed_valid_and_invalid_assets_preserve_valid_only(self) -> None:
        collection = _assemble_shot_plans(_supported_scenes(["valid", "invalid"]), {}, {"valid"}, [])
        self.assertTrue(all(group.source_asset_ids == ["valid"] for group in collection.shot_plans[0].scene_framing_groups))

    def test_fully_supported_scene(self) -> None:
        statuses = {"architecture_01": {"status": "fully_supported", "text_evidence": []}}
        collection = _assemble_shot_plans(_supported_scenes(), statuses, {"asset_a"}, [_recommendation(), _recommendation()])
        self.assertTrue(all(group.source_support_status == "fully_supported" for group in collection.shot_plans[0].scene_framing_groups))

    def test_partially_supported_scene(self) -> None:
        statuses = {"architecture_01": {"status": "partially_supported", "text_evidence": []}}
        collection = _assemble_shot_plans(_supported_scenes(), statuses, {"asset_a"}, [])
        self.assertEqual(collection.shot_plans[0].scene_framing_groups[0].source_support_status, "partially_supported")

    def test_text_only_scene_needs_no_source_image(self) -> None:
        statuses = {"architecture_01": {"status": "text_only", "text_evidence": ["project.location"]}}
        collection = _assemble_shot_plans(_scene_collection(), statuses, set(), [])
        group = collection.shot_plans[0].scene_framing_groups[0]
        self.assertEqual(group.source_asset_ids, [])
        self.assertEqual(group.framing_plans[0].layout_type, "source_supported_text_graphic")
        self.assertEqual(collection.summary.text_only_plans_created, 2)

    def test_unavailable_scene_is_skipped(self) -> None:
        statuses = {"architecture_01": {"status": "unavailable", "text_evidence": []}}
        collection = _assemble_shot_plans(_supported_scenes(), statuses, {"asset_a"}, [])
        self.assertEqual(collection.shot_plans[0].scene_framing_groups, [])
        self.assertEqual(collection.summary.skipped_unavailable, 2)

    def test_fallback_is_deterministic_and_ids_are_globally_unique(self) -> None:
        collection = _assemble_shot_plans(_supported_scenes(), {}, {"asset_a"}, [])
        plan = collection.shot_plans[0]
        self.assertEqual(plan.shot_plan_id, f"{plan.scene_plan_id}-FP")
        ids = [group.framing_plans[0].framing_plan_id for group in plan.scene_framing_groups]
        self.assertEqual(ids, [f"{group.scene_id}-FP1" for group in plan.scene_framing_groups])
        self.assertEqual(len(ids), len(set(ids)))

    def test_complete_scene_coverage_preserves_order(self) -> None:
        source = _supported_scenes()
        collection = _assemble_shot_plans(source, {}, {"asset_a"}, [])
        self.assertEqual(
            [group.scene_id for group in collection.shot_plans[0].scene_framing_groups],
            [scene.scene_id for scene in source.scene_plans[0].scenes],
        )
        self.assertEqual(collection.validate(), [])

    def test_two_projects_remain_isolated(self) -> None:
        first = _assemble_shot_plans(_supported_scenes(["project_a", "project_b"]), {}, {"project_a"}, [])
        second = _assemble_shot_plans(_supported_scenes(["project_a", "project_b"]), {}, {"project_b"}, [])
        self.assertEqual(first.shot_plans[0].scene_framing_groups[0].source_asset_ids, ["project_a"])
        self.assertEqual(second.shot_plans[0].scene_framing_groups[0].source_asset_ids, ["project_b"])


class ShotPlannerRunTests(unittest.TestCase):
    def test_successful_completion_with_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge, creative, scenes = _write_inputs(root)
            planner = ShotPlanner(model="test-model")
            destination = root / "shot-plans"
            with (
                patch.object(planner, "_load_api_key", return_value="test-key"),
                patch.object(planner, "_request_shot_plans", return_value='{"recommendations": []}'),
                patch("src.ai.agents.shot_planner.save_shot_plans") as save,
            ):
                save.side_effect = lambda collection, filename: _save(collection, filename, destination)
                result = planner.run(knowledge, creative, scenes)
            self.assertIsNotNone(result)
            payload = ShotPlanCollection.from_json(result.read_text(encoding="utf-8"))
            self.assertEqual(payload.summary.fallback_plans_created, 2)
            self.assertTrue(payload.warnings)

    def test_api_failure_uses_fallback_instead_of_failing_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            planner = ShotPlanner()
            destination = Path(directory) / "out"
            with (
                patch.object(planner, "_load_api_key", return_value="test-key"),
                patch.object(planner, "_request_shot_plans", side_effect=RuntimeError("service unavailable")),
                patch("src.ai.agents.shot_planner.save_shot_plans") as save,
            ):
                save.side_effect = lambda collection, filename: _save(collection, filename, destination)
                result = planner.run(*_write_inputs(Path(directory)))
            self.assertIsNotNone(result)


def _write_inputs(root: Path) -> tuple[Path, Path, Path]:
    knowledge = root / "palm-gardens.json"
    creative = root / "palm-gardens-creative-directions.json"
    scenes = root / "palm-gardens-scene-plans.json"
    knowledge.write_text(ProjectKnowledge(
        project=ProjectDetails(name="Palm Gardens", location="Baghdad"),
        architecture=Architecture(materials=["Natural stone"]),
    ).to_json(), encoding="utf-8")
    creative.write_text(_creative_directions().to_json(), encoding="utf-8")
    scenes.write_text(_scene_collection().to_json(), encoding="utf-8")
    return knowledge, creative, scenes


def _save(collection: ShotPlanCollection, filename: str, directory: Path) -> Path:
    directory.mkdir(exist_ok=True)
    path = directory / f"{filename}.json"
    path.write_text(collection.to_json(), encoding="utf-8")
    return path
