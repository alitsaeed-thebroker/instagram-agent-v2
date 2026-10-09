"""Unit tests for Scene Planner behavior without API calls."""

from __future__ import annotations

from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ai.agents.scene_planner import SCENE_PLANNER_BATCH_SIZE, ScenePlanner, _repair_scene_counts, _sanitize_scene_output, _validate_plan_coverage
from src.content.schema import ContentIdea, ContentPillar, ContentPlan
from src.creative.schema import (
    CreativeDirection,
    CreativeDirectionPlan,
    EmotionalDirection,
    StorytellingDirection,
    VisualIdentity,
)
from src.knowledge.schema import Architecture, ProjectDetails, ProjectKnowledge
from src.scenes.schema import Scene, ScenePlan, ScenePlanCollection


def _content_plan() -> ContentPlan:
    return ContentPlan(pillars=[ContentPillar(name="Architecture", content_ideas=[ContentIdea(
        unique_id="architecture_01", title="Material Legacy",
        story="Move from recognition of natural stone to confidence in enduring quality.",
        purpose="Build confidence in documented quality.", target_audience="Discerning family buyers",
        emotion="Assurance", marketing_goal="Increase consideration", recommended_platform="Instagram",
        recommended_format="Carousel", image_orientation="Portrait", priority="High",
        main_subject="Documented villa architecture", supporting_subjects=["Natural stone"],
        environment="Project exterior", time_of_day="Late afternoon", weather="Not specified",
        mood="Quietly assured", color_palette="Warm mineral neutrals", camera_style="Legacy value to ignore",
        recommended_lens="Legacy value to ignore", composition="Legacy value to ignore",
        visual_keywords=["authentic", "restrained"], future_asset_type="Instagram Carousel",
    )])])


def _creative_directions() -> CreativeDirectionPlan:
    return CreativeDirectionPlan(creative_directions=[CreativeDirection(
        creative_direction_id="cd_architecture_01", content_idea_id="architecture_01",
        campaign_concept="Material as Legacy",
        visual_identity=VisualIdentity(
            factual_project_elements=["Natural stone"],
            creative_interpretation="Material permanence symbolizes continuity.",
            palette_intent=["Warm mineral neutrals"], texture_language=["Natural texture"],
        ),
        emotional_direction=EmotionalDirection(
            primary_emotion="Assurance", supporting_emotions=["Pride"],
            desired_response="Perceive credible lasting quality.",
        ),
        storytelling_direction=StorytellingDirection(
            premise="Material integrity expresses endurance.", narrative_arc=["Recognition", "Trust"],
            story_boundaries=["Do not introduce undocumented spaces"],
        ),
        brand_constraints=["Preserve architectural authenticity"],
        luxury_level="Understated premium luxury", realism_level="Photorealistic and credible",
        audience_perception="A credible home of lasting quality",
        artistic_vision="Restrained material authenticity.", reference_asset_ids=[],
        consistency_approval_criteria=["Every scene reinforces material integrity"],
    )])


def _scene_collection() -> ScenePlanCollection:
    common_restrictions = [
        "No undocumented architecture", "No invented amenities", "No fantasy elements",
        "No exaggerated luxury cliches", "Preserve realistic human behavior",
        "Preserve architectural authenticity",
    ]
    return ScenePlanCollection(scene_plans=[ScenePlan(
        scene_plan_id="sp_architecture_01", creative_direction_id="cd_architecture_01",
        content_idea_id="architecture_01",
        overall_story_summary="Authentic material detail moves the viewer from recognition to trust.",
        scene_count=2,
        scenes=[
            Scene(
                scene_id="sc_architecture_01_01", sequence=1, scene_name="Recognition",
                story_purpose="Establish documented material character.",
                scene_summary="The villa exterior and its natural stone establish credible quality.",
                main_subject="Documented natural-stone exterior", supporting_subjects=[],
                environment="Documented project exterior", factual_basis=["Natural stone is a documented material"],
                creative_interpretation="The material is experienced with quiet attention.",
                time_of_day="Late afternoon", weather="Not specified", mood="Assured",
                lighting_direction="Warm natural light reveals authentic texture without exaggeration.",
                scene_dependencies=[], reusable_asset_ids=[],
                continuity_notes=["Maintain the same documented material identity"],
                restrictions=common_restrictions,
                transition_to_next_scene="Move from broad recognition toward tactile material appreciation.",
            ),
            Scene(
                scene_id="sc_architecture_01_02", sequence=2, scene_name="Trust",
                story_purpose="Turn material recognition into confidence in lasting quality.",
                scene_summary="Human attention to the same authentic material makes quality personally meaningful.",
                main_subject="Natural-stone material", supporting_subjects=["Realistic family interaction"],
                environment="The same documented project exterior", factual_basis=["Natural stone is a documented material"],
                creative_interpretation="A family pauses naturally to appreciate the home's material character.",
                time_of_day="Late afternoon", weather="Not specified", mood="Trusting",
                lighting_direction="Consistent warm natural light preserves continuity.",
                scene_dependencies=["sc_architecture_01_01"], reusable_asset_ids=[],
                continuity_notes=["Retain the same environment and material appearance"],
                restrictions=common_restrictions,
                transition_to_next_scene="End of sequence on a feeling of credible permanence.",
            ),
        ],
    )])


def _two_creative_directions() -> CreativeDirectionPlan:
    directions = _creative_directions()
    second = deepcopy(directions.creative_directions[0])
    second.creative_direction_id = "cd_architecture_02"
    second.content_idea_id = "architecture_02"
    directions.creative_directions.append(second)
    return directions


def _two_scene_collection() -> ScenePlanCollection:
    collection = _scene_collection()
    second = deepcopy(collection.scene_plans[0])
    second.scene_plan_id = "sp_architecture_02"
    second.creative_direction_id = "cd_architecture_02"
    second.content_idea_id = "architecture_02"
    for scene in second.scenes:
        old_id = scene.scene_id
        scene.scene_id = old_id.replace("architecture_01", "architecture_02")
        scene.scene_dependencies = [
            dependency.replace("architecture_01", "architecture_02")
            for dependency in scene.scene_dependencies
        ]
    collection.scene_plans.append(second)
    return collection


class ScenePlannerTests(unittest.TestCase):
    def test_run_reads_inputs_and_saves_linked_scene_plans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge_path, content_path, directions_path = _write_inputs(root)
            destination = root / "scene-plans"
            planner = ScenePlanner(model="test-model")
            with (
                patch.object(planner, "_load_api_key", return_value="test-key"),
                patch.object(planner, "_request_scene_plans", return_value=_scene_collection().to_json()) as request,
                patch("src.ai.agents.scene_planner.save_scene_plans") as save,
            ):
                save.side_effect = lambda collection, filename: _save(collection, filename, destination)
                path = planner.run(knowledge_path, content_path, directions_path)
            self.assertIsNotNone(path)
            self.assertEqual(path.name, "palm-gardens-scene-plans.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["scene_plans"][0]["scene_count"], 2)
            self.assertEqual(payload["scene_plans"][0]["creative_direction_id"], "cd_architecture_01")
            planning_input = request.call_args.args[1][0]["content_idea"]
            self.assertNotIn("recommended_lens", planning_input)
            self.assertNotIn("composition", planning_input)
            self.assertNotIn("camera_style", planning_input)

    def test_run_batches_directions_without_losing_order_or_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge_path, content_path, directions_path = _write_inputs(root)
            content = ContentPlan.from_json(content_path.read_text(encoding="utf-8"))
            directions = CreativeDirectionPlan.from_json(directions_path.read_text(encoding="utf-8"))
            base_idea = content.pillars[0].content_ideas[0]
            base_direction = directions.creative_directions[0]
            for index in range(1, SCENE_PLANNER_BATCH_SIZE + 2):
                idea = deepcopy(base_idea); idea.unique_id = f"architecture_{index + 1:02d}"
                direction = deepcopy(base_direction); direction.content_idea_id = idea.unique_id; direction.creative_direction_id = f"cd_{idea.unique_id}"
                content.pillars[0].content_ideas.append(idea); directions.creative_directions.append(direction)
            content_path.write_text(content.to_json(), encoding="utf-8")
            directions_path.write_text(directions.to_json(), encoding="utf-8")
            planner = ScenePlanner()

            def response(_knowledge, batch, _key):
                plans = []
                for item in batch:
                    plan = deepcopy(_scene_collection().scene_plans[0])
                    plan.creative_direction_id = item["creative_direction"]["creative_direction_id"]
                    plan.content_idea_id = item["creative_direction"]["content_idea_id"]
                    plan.scene_plan_id = f"sp_{plan.creative_direction_id}"
                    plans.append(plan)
                return ScenePlanCollection(scene_plans=plans).to_json()

            with patch.object(planner, "_load_api_key", return_value="test-key"), patch.object(planner, "_request_scene_plans", side_effect=response) as request:
                path = planner.run(knowledge_path, content_path, directions_path)
            self.assertIsNotNone(path)
            saved = ScenePlanCollection.from_json(path.read_text(encoding="utf-8"))
            self.assertEqual(request.call_count, 2)
            self.assertEqual([x.creative_direction_id for x in saved.scene_plans], [x.creative_direction_id for x in directions.creative_directions])
            self.assertEqual(len({x.scene_plan_id for x in saved.scene_plans}), len(saved.scene_plans))

    def test_sanitizer_canonicalizes_scene_plan_id_from_direction_id(self) -> None:
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scene_plan_id"] = "model_generated_duplicate"
        _sanitize_scene_output(payload)
        self.assertEqual(payload["scene_plans"][0]["scene_plan_id"], "cd_architecture_01-PLAN")

    def test_run_recovers_only_a_missing_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_inputs(Path(directory))
            planner = ScenePlanner()
            responses = [ScenePlanCollection().to_json(), _scene_collection().to_json()]
            with patch.object(planner, "_load_api_key", return_value="test-key"), patch.object(planner, "_request_scene_plans", side_effect=responses) as request:
                path = planner.run(*paths)
            self.assertIsNotNone(path)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args_list[1].args[1][0]["creative_direction"]["creative_direction_id"], "cd_architecture_01")

    def test_run_targeted_semantic_recovery_replaces_only_invalid_plan(self) -> None:
        invalid = _scene_collection().to_dict()
        invalid["scene_plans"][0]["scenes"][0]["scene_summary"] = "Use tight framing around the entrance."
        valid = _scene_collection().to_json()
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_inputs(Path(directory))
            planner = ScenePlanner()
            with patch.object(planner, "_load_api_key", return_value="test-key"), patch.object(planner, "_request_scene_plans", side_effect=[json.dumps(invalid), valid]) as request:
                path = planner.run(*paths)
            self.assertIsNotNone(path)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args_list[1].args[1][0]["creative_direction"]["creative_direction_id"], "cd_architecture_01")
            self.assertIn("framing", request.call_args_list[1].kwargs["recovery_feedback"]["cd_architecture_01"])
            saved = ScenePlanCollection.from_json(path.read_text(encoding="utf-8"))
            self.assertEqual(saved.scene_plans[0].creative_direction_id, "cd_architecture_01")

    def test_run_fails_after_two_invalid_semantic_recoveries(self) -> None:
        invalid = _scene_collection().to_dict()
        invalid["scene_plans"][0]["scenes"][0]["scene_summary"] = "Use a camera angle chosen for impact."
        with tempfile.TemporaryDirectory() as directory:
            planner = ScenePlanner()
            paths = _write_inputs(Path(directory))
            with patch.object(planner, "_load_api_key", return_value="test-key"), patch.object(planner, "_request_scene_plans", return_value=json.dumps(invalid)) as request:
                self.assertIsNone(planner.run(*paths))
            self.assertEqual(request.call_count, 3)

    def test_schema_rejects_shot_planning_fields(self) -> None:
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scenes"][0]["camera_angle"] = "low angle"
        with self.assertRaisesRegex(ValueError, "unexpected or missing scene fields"):
            ScenePlanCollection.from_dict(payload)

    def test_semantic_boundary_rejects_production_decisions(self) -> None:
        cases = (
            "Use tight framing around the entrance.",
            "Choose a low camera angle.",
            "Use a 35mm lens and focal length.",
            "Build a three-point lighting setup.",
            "Add slow camera movement.",
            "Apply centered composition.",
        )
        for text in cases:
            with self.subTest(text=text):
                payload = _scene_collection().to_dict()
                payload["scene_plans"][0]["scenes"][0]["scene_summary"] = text
                with self.assertRaisesRegex(ValueError, "downstream production decision"):
                    ScenePlanCollection.from_dict(payload)

    def test_semantic_boundary_accepts_narrative_intent(self) -> None:
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scenes"][0]["scene_summary"] = "The entrance welcomes residents and establishes a calm arrival experience."
        ScenePlanCollection.from_dict(payload)

    def test_sanitizer_does_not_strip_forbidden_words_from_text(self) -> None:
        payload = _scene_collection().to_dict()
        text = "Use tight framing around the entrance."
        payload["scene_plans"][0]["scenes"][0]["scene_summary"] = text
        _sanitize_scene_output(payload)
        self.assertEqual(payload["scene_plans"][0]["scenes"][0]["scene_summary"], text)
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scenes"][0]["scene_summary"] = "Use a wide-angle lens."
        with self.assertRaisesRegex(ValueError, "downstream production decision"):
            ScenePlanCollection.from_dict(payload)

    def test_schema_rejects_bad_count_sequence_and_dependencies(self) -> None:
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scene_count"] = 3
        payload["scene_plans"][0]["scenes"][1]["sequence"] = 3
        payload["scene_plans"][0]["scenes"][1]["scene_dependencies"] = ["unknown_scene"]
        with self.assertRaisesRegex(ValueError, "scene_count|consecutive|unknown scene"):
            ScenePlanCollection.from_dict(payload)

    def test_run_rejects_incorrect_creative_direction_coverage(self) -> None:
        collection = _scene_collection()
        collection.scene_plans[0].creative_direction_id = "unknown_direction"
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_inputs(Path(directory))
            planner = ScenePlanner()
            with (
                patch.object(planner, "_load_api_key", return_value="test-key"),
                patch.object(planner, "_request_scene_plans", return_value=collection.to_json()),
            ):
                self.assertIsNone(planner.run(*paths))

    def test_run_removes_unapproved_reusable_assets(self) -> None:
        collection = _scene_collection()
        collection.scene_plans[0].scenes[0].reusable_asset_ids = ["invented_asset"]
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_inputs(Path(directory))
            planner = ScenePlanner()
            with (
                patch.object(planner, "_load_api_key", return_value="test-key"),
                patch.object(planner, "_request_scene_plans", return_value=collection.to_json()),
            ):
                path = planner.run(*paths)
            self.assertIsNotNone(path)
            saved = ScenePlanCollection.from_json(path.read_text(encoding="utf-8"))
            self.assertEqual(saved.scene_plans[0].scenes[0].reusable_asset_ids, [])

    def test_run_handles_api_failure_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_inputs(Path(directory))
            planner = ScenePlanner()
            with (
                patch.object(planner, "_load_api_key", return_value="test-key"),
                patch.object(planner, "_request_scene_plans", side_effect=RuntimeError("service unavailable")),
            ):
                self.assertIsNone(planner.run(*paths))


class ScenePlanMappingTests(unittest.TestCase):
    def test_correct_one_to_one_mapping(self) -> None:
        collection = _two_scene_collection()
        _validate_plan_coverage(collection, _two_creative_directions())
        self.assertEqual(
            [plan.creative_direction_id for plan in collection.scene_plans],
            ["cd_architecture_01", "cd_architecture_02"],
        )


class SceneCountRepairTests(unittest.TestCase):
    def test_correct_scene_count_is_unchanged(self) -> None:
        payload = _scene_collection().to_dict()
        self.assertEqual(_repair_scene_counts(payload), [])
        self.assertEqual(payload["scene_plans"][0]["scene_count"], 2)
        ScenePlanCollection.from_dict(payload)

    def test_scene_count_too_low_is_recalculated(self) -> None:
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scene_count"] = 1
        repairs = _repair_scene_counts(payload)
        self.assertEqual(payload["scene_plans"][0]["scene_count"], 2)
        self.assertRegex(repairs[0], r"index 0.*creative_direction_id=cd_architecture_01.*declared scene_count=1.*actual scenes=2")
        ScenePlanCollection.from_dict(payload)

    def test_scene_count_too_high_is_recalculated(self) -> None:
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scene_count"] = 7
        repairs = _repair_scene_counts(payload)
        self.assertEqual(payload["scene_plans"][0]["scene_count"], 2)
        self.assertIn("declared scene_count=7, actual scenes=2", repairs[0])
        ScenePlanCollection.from_dict(payload)

    def test_missing_scene_count_is_added(self) -> None:
        payload = _scene_collection().to_dict()
        del payload["scene_plans"][0]["scene_count"]
        repairs = _repair_scene_counts(payload)
        self.assertEqual(payload["scene_plans"][0]["scene_count"], 2)
        self.assertIn("declared scene_count=<missing>, actual scenes=2", repairs[0])
        ScenePlanCollection.from_dict(payload)

    def test_empty_scenes_remains_invalid_after_count_repair(self) -> None:
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scenes"] = []
        _repair_scene_counts(payload)
        self.assertEqual(payload["scene_plans"][0]["scene_count"], 0)
        with self.assertRaisesRegex(ValueError, "scenes must be a non-empty list"):
            ScenePlanCollection.from_dict(payload)


class SceneOutputSanitizationTests(unittest.TestCase):
    def test_forbidden_framing_field_is_removed_with_indexed_warning(self) -> None:
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scenes"][0]["framing"] = "centered"
        warnings = _sanitize_scene_output(payload)
        self.assertNotIn("framing", payload["scene_plans"][0]["scenes"][0])
        self.assertRegex(warnings[0], r"plan index 0.*creative_direction_id=cd_architecture_01.*scene index 0.*framing")
        ScenePlanCollection.from_dict(payload)

    def test_forbidden_camera_field_is_removed(self) -> None:
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scenes"][0]["camera_angle"] = "low"
        _sanitize_scene_output(payload)
        self.assertNotIn("camera_angle", payload["scene_plans"][0]["scenes"][0])

    def test_duplicate_empty_and_malformed_ai_ids_are_regenerated(self) -> None:
        for original_ids in (["duplicate", "duplicate"], ["", ""], ["bad/id", "not-an-id"]):
            with self.subTest(original_ids=original_ids):
                payload = _scene_collection().to_dict()
                for scene, scene_id in zip(payload["scene_plans"][0]["scenes"], original_ids):
                    scene["scene_id"] = scene_id
                _sanitize_scene_output(payload)
                self.assertEqual(
                    [scene["scene_id"] for scene in payload["scene_plans"][0]["scenes"]],
                    ["cd_architecture_01-SC1", "cd_architecture_01-SC2"],
                )
                ScenePlanCollection.from_dict(payload)

    def test_duplicate_generated_id_has_detailed_error(self) -> None:
        payload = _two_scene_collection().to_dict()
        payload["scene_plans"][1]["creative_direction_id"] = "cd_architecture_01"
        with self.assertRaisesRegex(ValueError, r"plan index 1.*scene index 0.*duplicate generated ID cd_architecture_01-SC1"):
            _sanitize_scene_output(payload)

    def test_duplicate_and_missing_sequences_are_repaired_from_array_order(self) -> None:
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scenes"][0]["sequence"] = 1
        payload["scene_plans"][0]["scenes"][1]["sequence"] = 1
        warnings = _sanitize_scene_output(payload)
        self.assertEqual([scene["sequence"] for scene in payload["scene_plans"][0]["scenes"]], [1, 2])
        self.assertTrue(any("invalid sequence value 1; repaired to 2" in warning for warning in warnings))
        payload = _scene_collection().to_dict()
        del payload["scene_plans"][0]["scenes"][1]["sequence"]
        warnings = _sanitize_scene_output(payload)
        self.assertTrue(any("invalid sequence value <missing>; repaired to 2" in warning for warning in warnings))

    def test_scene_count_is_recalculated_with_deterministic_ids(self) -> None:
        payload = _scene_collection().to_dict()
        payload["scene_plans"][0]["scene_count"] = 99
        _sanitize_scene_output(payload)
        self.assertEqual(payload["scene_plans"][0]["scene_count"], 2)
        ScenePlanCollection.from_dict(payload)

    def test_valid_output_with_skipped_unavailable_ideas_remains_valid(self) -> None:
        payload = _scene_collection().to_dict()
        payload["skipped_content_ideas"] = [{
            "content_idea_id": "unsupported_02", "status": "skipped_unavailable",
            "reason": "No approved source asset supports this idea.",
        }]
        payload["summary"]["skipped_unavailable"] = 1
        _sanitize_scene_output(payload)
        collection = ScenePlanCollection.from_dict(payload)
        self.assertEqual(collection.skipped_content_ideas[0].content_idea_id, "unsupported_02")



class ScenePlanMappingErrorTests(unittest.TestCase):
    def test_missing_plan_identifies_creative_direction_id(self) -> None:
        collection = _two_scene_collection()
        collection.scene_plans.pop()
        with self.assertRaisesRegex(ValueError, "missing creative_direction_id: cd_architecture_02"):
            _validate_plan_coverage(collection, _two_creative_directions())

    def test_duplicate_plan_identifies_creative_direction_id(self) -> None:
        collection = _two_scene_collection()
        duplicate = deepcopy(collection.scene_plans[0])
        duplicate.scene_plan_id = "sp_duplicate"
        collection.scene_plans.append(duplicate)
        with self.assertRaisesRegex(ValueError, "duplicate creative_direction_id: cd_architecture_01"):
            _validate_plan_coverage(collection, _two_creative_directions())

    def test_extra_plan_identifies_unexpected_creative_direction_id(self) -> None:
        collection = _two_scene_collection()
        extra = deepcopy(collection.scene_plans[0])
        extra.scene_plan_id = "sp_unexpected"
        extra.creative_direction_id = "cd_unexpected"
        extra.content_idea_id = "idea_unexpected"
        collection.scene_plans.append(extra)
        with self.assertRaisesRegex(ValueError, "unexpected creative_direction_id: cd_unexpected"):
            _validate_plan_coverage(collection, _two_creative_directions())

    def test_mismatched_content_idea_is_identified(self) -> None:
        collection = _two_scene_collection()
        collection.scene_plans[1].content_idea_id = "wrong_idea"
        with self.assertRaisesRegex(
            ValueError,
            "mismatched content_idea_id for creative_direction_id cd_architecture_02: expected architecture_02, received wrong_idea",
        ):
            _validate_plan_coverage(collection, _two_creative_directions())

    def test_reordered_valid_plans_are_restored_to_input_order(self) -> None:
        collection = _two_scene_collection()
        collection.scene_plans.reverse()
        _validate_plan_coverage(collection, _two_creative_directions())
        self.assertEqual(
            [plan.creative_direction_id for plan in collection.scene_plans],
            ["cd_architecture_01", "cd_architecture_02"],
        )


def _write_inputs(root: Path) -> tuple[Path, Path, Path]:
    knowledge_path = root / "palm-gardens.json"
    content_path = root / "palm-gardens-content-plan.json"
    directions_path = root / "palm-gardens-creative-directions.json"
    knowledge_path.write_text(ProjectKnowledge(
        project=ProjectDetails(name="Palm Gardens", location="Baghdad"),
        architecture=Architecture(materials=["Natural stone"]),
    ).to_json(), encoding="utf-8")
    content_path.write_text(_content_plan().to_json(), encoding="utf-8")
    directions_path.write_text(_creative_directions().to_json(), encoding="utf-8")
    return knowledge_path, content_path, directions_path


def _save(collection: ScenePlanCollection, filename: str, directory: Path) -> Path:
    directory.mkdir()
    path = directory / f"{filename}.json"
    path.write_text(collection.to_json(), encoding="utf-8")
    return path
