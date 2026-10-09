"""Scene Planner behavior for source-supported and unavailable ideas."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.ai.agents.scene_planner import ScenePlanner, _build_planning_inputs, _read_asset_selections, _repair_and_validate_reusable_assets
from src.scenes.schema import ScenePlanCollection
from tests.test_scene_planner import _content_plan, _creative_directions, _save, _write_inputs, _scene_collection


class SceneSourceSupportTests(unittest.TestCase):
    def test_canonical_carousel_rejects_repeated_reversed_and_missing_sources(self):
        selection={"architecture_01":{"canonical_ordered_selection":True,"publication_type":"carousel","selected_asset_ids":["cover","entrance"]}}
        collection=_scene_collection()
        for scene,aid in zip(collection.scene_plans[0].scenes,["cover","entrance"]):scene.reusable_asset_ids=[aid]
        _repair_and_validate_reusable_assets(collection,selection)
        for ids in (["entrance","entrance"],["entrance","cover"],["cover"]):
            with self.subTest(ids=ids):
                broken=deepcopy(collection);broken.scene_plans[0].scenes=broken.scene_plans[0].scenes[:len(ids)]
                for scene,aid in zip(broken.scene_plans[0].scenes,ids):scene.reusable_asset_ids=[aid]
                with self.assertRaisesRegex(ValueError,"Canonical carousel"):_repair_and_validate_reusable_assets(broken,selection)
                self.assertEqual([s.reusable_asset_ids[0] for s in broken.scene_plans[0].scenes],ids)

    def test_canonical_missing_inventory_source_is_rejected_without_silent_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);selection=root/"selection.json";inventory=root/"inventory.json"
            selection.write_text(json.dumps({"project":"Beverly Hills","visual_mode":"source_only","workflow_status":"ready","selections":[{"content_idea_id":"overview","canonical_ordered_selection":True,"selected_asset_ids":["cover","entrance"]}]}))
            inventory.write_text(json.dumps({"project":"Beverly Hills","all_source_asset_ids":["entrance"]}))
            with self.assertRaisesRegex(ValueError,"Canonical source selection"):_read_asset_selections(selection,inventory)

    def _build(self, status: str, selected: list[str] | None = None, text: bool = False):
        content = _content_plan()
        idea = content.pillars[0].content_ideas[0]
        idea.source_support_status = status
        idea.text_evidence = ["project.location"] if text else []
        selections = {idea.unique_id: {
            "content_idea_id": idea.unique_id, "status": "ready" if selected or status == "text_only" else "skipped_unavailable",
            "selected_asset_ids": selected or [],
        }}
        return _build_planning_inputs(content, _creative_directions(), selections)

    def test_fully_supported_idea_uses_approved_asset(self) -> None:
        inputs, _, _, summary = self._build("fully_supported", ["asset_a"])
        self.assertEqual(inputs[0]["approved_source_asset_selection"]["selected_asset_ids"], ["asset_a"])
        self.assertEqual(summary.fully_supported_processed, 1)

    def test_partially_supported_idea_is_processed(self) -> None:
        inputs, _, _, summary = self._build("partially_supported", ["asset_a"])
        self.assertEqual(len(inputs), 1)
        self.assertEqual(summary.partially_supported_processed, 1)

    def test_text_only_idea_is_processed_without_image(self) -> None:
        inputs, _, _, summary = self._build("text_only", [], True)
        self.assertEqual(inputs[0]["content_idea"]["source_support_status"], "text_only")
        self.assertEqual(summary.text_only_processed, 1)

    def test_unavailable_and_skipped_unavailable_are_skipped(self) -> None:
        for status in ("unavailable", "skipped_unavailable"):
            with self.subTest(status=status):
                inputs, _, skipped, summary = self._build(status)
                self.assertEqual(inputs, [])
                self.assertEqual(skipped[0].status, "skipped_unavailable")
                self.assertEqual(summary.skipped_unavailable, 1)

    def test_empty_inventory_downgrades_visual_idea_to_text_only(self) -> None:
        inputs, _, _, summary = self._build("fully_supported", [], True)
        self.assertEqual(inputs[0]["content_idea"]["source_support_status"], "text_only")
        self.assertEqual(summary.text_only_processed, 1)

    def test_unknown_and_foreign_assets_are_removed_by_current_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selection = root / "selection.json"
            inventory = root / "inventory.json"
            selection.write_text(json.dumps({
                "project": "320M2", "visual_mode": "source_only", "workflow_status": "ready",
                "selections": [{"content_idea_id": "architecture_01", "status": "ready", "selected_asset_ids": ["320_asset", "vision_asset"]}],
            }), encoding="utf-8")
            inventory.write_text(json.dumps({"project": "320M2", "all_source_asset_ids": ["320_asset"]}), encoding="utf-8")
            selections = _read_asset_selections(selection, inventory)
        self.assertEqual(selections["architecture_01"]["selected_asset_ids"], ["320_asset"])

    def test_project_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selection = root / "selection.json"; inventory = root / "inventory.json"
            selection.write_text(json.dumps({"project": "The Vision of Beverly Hills06د", "visual_mode": "source_only", "workflow_status": "ready", "selections": []}), encoding="utf-8")
            inventory.write_text(json.dumps({"project": "320M2", "all_source_asset_ids": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different projects"):
                _read_asset_selections(selection, inventory)

    def test_mixed_valid_and_unavailable_ideas_continue(self) -> None:
        content = _content_plan(); directions = _creative_directions()
        second_idea = deepcopy(content.pillars[0].content_ideas[0]); second_idea.unique_id = "unavailable_02"; second_idea.source_support_status = "unavailable"
        content.pillars[0].content_ideas.append(second_idea)
        second_direction = deepcopy(directions.creative_directions[0]); second_direction.creative_direction_id = "cd_unavailable_02"; second_direction.content_idea_id = "unavailable_02"
        directions.creative_directions.append(second_direction)
        first_id = content.pillars[0].content_ideas[0].unique_id
        content.pillars[0].content_ideas[0].source_support_status = "partially_supported"
        inputs, _, skipped, summary = _build_planning_inputs(content, directions, {first_id: {"status": "ready", "selected_asset_ids": ["valid"]}})
        self.assertEqual(len(inputs), 1)
        self.assertEqual(skipped[0].content_idea_id, "unavailable_02")
        self.assertEqual(summary.skipped_unavailable, 1)

    def test_all_unavailable_saves_empty_successful_result_without_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge, content_path, directions = _write_inputs(root)
            content = _content_plan(); content.pillars[0].content_ideas[0].source_support_status = "unavailable"
            content_path.write_text(content.to_json(), encoding="utf-8")
            selection = root / "selections.json"
            selection.write_text(json.dumps({"project": "palm-gardens", "visual_mode": "source_only", "workflow_status": "ready", "selections": []}), encoding="utf-8")
            planner = ScenePlanner()
            destination = root / "scene-output"
            with (
                patch.object(planner, "_load_api_key", side_effect=AssertionError("API must not be called")),
                patch("src.ai.agents.scene_planner.save_scene_plans") as save,
            ):
                save.side_effect = lambda collection, filename: _save(collection, filename, destination)
                result = planner.run(knowledge, content_path, directions, selection)
            payload = ScenePlanCollection.from_json(result.read_text(encoding="utf-8"))
            self.assertEqual(payload.scene_plans, [])
            self.assertEqual(payload.summary.skipped_unavailable, 1)
            self.assertEqual(payload.skipped_content_ideas[0].reason, "No approved source asset supports this idea.")
