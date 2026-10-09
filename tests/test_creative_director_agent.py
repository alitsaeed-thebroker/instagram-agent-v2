"""Unit tests for Creative Director behavior without API calls."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ai.agents.creative_director_agent import CreativeDirectorAgent, CreativeDirectorCompletenessError, _parse_exact_response
from src.content.schema import ContentIdea, ContentPillar, ContentPlan
from src.creative.schema import (
    CreativeDirection,
    CreativeDirectionPlan,
    EmotionalDirection,
    StorytellingDirection,
    VisualIdentity,
)
from src.knowledge.schema import Architecture, ProjectDetails, ProjectKnowledge
from src.strategy.schema import MarketingStrategy


def _content_plan() -> ContentPlan:
    idea = ContentIdea(
        unique_id="architecture_01", title="Material Legacy",
        story="Reveal the documented natural-stone architecture as an expression of enduring family value.",
        purpose="Build confidence in project quality.", target_audience="Discerning family buyers",
        emotion="Assurance", marketing_goal="Increase consideration", recommended_platform="Instagram",
        recommended_format="Carousel", image_orientation="Portrait", priority="High",
        main_subject="Documented villa architecture", supporting_subjects=["Natural stone"],
        environment="Project exterior", time_of_day="Late afternoon", weather="Not specified",
        mood="Quietly assured", color_palette="Warm mineral neutrals", camera_style="Editorial",
        recommended_lens="35mm", composition="Not used by Creative Director",
        visual_keywords=["authentic", "restrained", "enduring"], future_asset_type="Instagram Carousel",
    )
    return ContentPlan(pillars=[ContentPillar(name="Architecture", content_ideas=[idea])])


def _creative_plan(content_idea_id: str = "architecture_01") -> CreativeDirectionPlan:
    return CreativeDirectionPlan(creative_directions=[CreativeDirection(
        creative_direction_id="cd_architecture_01",
        content_idea_id=content_idea_id,
        campaign_concept="Material as Legacy",
        visual_identity=VisualIdentity(
            factual_project_elements=["Natural stone is a documented project material"],
            creative_interpretation="Treat material permanence as a restrained symbol of family continuity.",
            palette_intent=["Warm mineral neutrals"], texture_language=["Honest natural texture"],
        ),
        emotional_direction=EmotionalDirection(
            primary_emotion="Assurance", supporting_emotions=["Pride", "Belonging"],
            desired_response="The buyer perceives lasting quality without ostentation.",
        ),
        storytelling_direction=StorytellingDirection(
            premise="Material integrity expresses a home intended to endure.",
            narrative_arc=["Recognition", "Trust", "Belonging"],
            story_boundaries=["Do not introduce undocumented architectural features"],
        ),
        brand_constraints=["Preserve architectural authenticity", "Avoid generic status symbolism"],
        luxury_level="Understated premium luxury",
        realism_level="Photorealistic and architecturally credible",
        audience_perception="A credible residence shaped by lasting quality",
        artistic_vision="A restrained study of authentic materiality and family permanence.",
        reference_asset_ids=[],
        consistency_approval_criteria=["Every interpretation remains traceable to documented materials"],
    )])


class CreativeDirectorAgentTests(unittest.TestCase):
    def test_run_reads_all_inputs_and_saves_one_direction_per_idea(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge_path = root / "palm-gardens.json"
            strategy_path = root / "palm-gardens-strategy.json"
            content_path = root / "palm-gardens-content-plan.json"
            knowledge_path.write_text(ProjectKnowledge(
                project=ProjectDetails(name="Palm Gardens", location="Baghdad"),
                architecture=Architecture(materials=["Natural stone"]),
            ).to_json(), encoding="utf-8")
            strategy_path.write_text(MarketingStrategy(
                project_summary="A residential project grounded in material quality",
                target_audience=["Discerning family buyers"],
            ).to_json(), encoding="utf-8")
            content_path.write_text(_content_plan().to_json(), encoding="utf-8")
            destination = root / "creative-directions"
            agent = CreativeDirectorAgent(model="test-model")
            with (
                patch.object(agent, "_load_api_key", return_value="test-key"),
                patch.object(agent, "_request_directions", return_value=_creative_plan().to_json()) as request,
                patch("src.ai.agents.creative_director_agent.save_creative_directions") as save,
            ):
                save.side_effect = lambda plan, filename: _save(plan, filename, destination)
                path = agent.run(knowledge_path, strategy_path, content_path)
            self.assertIsNotNone(path)
            self.assertEqual(path.name, "palm-gardens-creative-directions.json")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["creative_directions"][0]["content_idea_id"], "architecture_01")
            request.assert_called_once()
            selected_ideas = request.call_args.args[2]
            self.assertEqual([idea["unique_id"] for idea in selected_ideas], ["architecture_01"])

    def test_schema_rejects_production_decisions(self) -> None:
        payload = _creative_plan().to_dict()
        payload["creative_directions"][0]["camera_angle"] = "low angle"
        with self.assertRaisesRegex(ValueError, "unexpected or missing fields"):
            CreativeDirectionPlan.from_dict(payload)

    def test_run_rejects_missing_or_unexpected_content_idea_directions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge_path, strategy_path, content_path = _write_inputs(root)
            agent = CreativeDirectorAgent()
            with (
                patch.object(agent, "_load_api_key", return_value="test-key"),
                patch.object(agent, "_request_directions", return_value=_creative_plan("unknown_idea").to_json()),
            ):
                self.assertIsNone(agent.run(knowledge_path, strategy_path, content_path))

    def test_selected_content_ideas_are_respected(self) -> None:
        plan = _content_plan()
        second = ContentIdea(**{**plan.to_dict()["pillars"][0]["content_ideas"][0], "unique_id": "architecture_02", "title": "Second idea"})
        plan.pillars[0].content_ideas.append(second)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge_path, strategy_path, content_path = _write_inputs(root, plan)
            agent = CreativeDirectorAgent()
            with (
                patch.object(agent, "_load_api_key", return_value="test-key"),
                patch.object(agent, "_request_directions", return_value=_creative_plan("architecture_02").to_json()) as request,
                patch("src.ai.agents.creative_director_agent.save_creative_directions") as save,
            ):
                save.side_effect = lambda value, filename: _save(value, filename, root / "creative")
                self.assertIsNotNone(agent.run(
                    knowledge_path, strategy_path, content_path,
                    selected_content_idea_ids=["architecture_02"],
                ))
            self.assertEqual(request.call_args.args[2][0]["unique_id"], "architecture_02")

    def test_run_handles_api_failure_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            knowledge_path, strategy_path, content_path = _write_inputs(Path(directory))
            agent = CreativeDirectorAgent()
            with (
                patch.object(agent, "_load_api_key", return_value="test-key"),
                patch.object(agent, "_request_directions", side_effect=RuntimeError("service unavailable")),
            ):
                self.assertIsNone(agent.run(knowledge_path, strategy_path, content_path))

    def test_missing_ids_are_recovered_and_merged_in_authoritative_order(self) -> None:
        plan=_plan_with_ids("idea_1","idea_2","idea_3")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);knowledge,strategy,content=_write_inputs(root,plan);agent=CreativeDirectorAgent();agent.batch_size=10
            responses=[_creative_for_ids("idea_1").to_json(),_creative_for_ids("idea_2","idea_3").to_json()]
            with patch.object(agent,"_load_api_key",return_value="key"),patch.object(agent,"_request_directions",side_effect=responses) as request,patch("src.ai.agents.creative_director_agent.save_creative_directions") as save:
                save.side_effect=lambda value,filename:_save(value,filename,root/"creative")
                output=agent.run(knowledge,strategy,content)
            self.assertIsNotNone(output);self.assertEqual(request.call_count,2)
            self.assertEqual([x["unique_id"] for x in request.call_args_list[1].args[2]],["idea_2","idea_3"])
            self.assertEqual([x["content_idea_id"] for x in json.loads(output.read_text())["creative_directions"]],["idea_1","idea_2","idea_3"])
            self.assertEqual(agent.last_run_diagnostics["initial_returned_count"],1);self.assertEqual(agent.last_run_diagnostics["recovery_attempts"],1)

    def test_recovery_that_remains_incomplete_fails_without_saving(self) -> None:
        plan=_plan_with_ids("idea_1","idea_2")
        with tempfile.TemporaryDirectory() as directory:
            knowledge,strategy,content=_write_inputs(Path(directory),plan);agent=CreativeDirectorAgent();agent.batch_size=10
            responses=[_creative_for_ids("idea_1").to_json(),CreativeDirectionPlan().to_json(),CreativeDirectionPlan().to_json()]
            with patch.object(agent,"_load_api_key",return_value="key"),patch.object(agent,"_request_directions",side_effect=responses) as request,patch("src.ai.agents.creative_director_agent.save_creative_directions") as save:
                self.assertIsNone(agent.run(knowledge,strategy,content))
            self.assertEqual(request.call_count,3);save.assert_not_called()

    def test_unexpected_and_duplicate_ids_fail_closed(self) -> None:
        with self.assertRaises(CreativeDirectorCompletenessError):_parse_exact_response(_creative_for_ids("unexpected").to_json(),["idea_1"])
        duplicate=_creative_for_ids("idea_1","idea_1").to_dict()
        with self.assertRaises(CreativeDirectorCompletenessError):_parse_exact_response(json.dumps(duplicate),["idea_1"])

    def test_large_set_batches_every_id_exactly_once(self) -> None:
        ids=[f"idea_{index}" for index in range(13)];plan=_plan_with_ids(*ids)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);knowledge,strategy,content=_write_inputs(root,plan);agent=CreativeDirectorAgent();agent.batch_size=5
            def respond(_k,_s,ideas,_key):return _creative_for_ids(*(x["unique_id"] for x in ideas)).to_json()
            with patch.object(agent,"_load_api_key",return_value="key"),patch.object(agent,"_request_directions",side_effect=respond) as request,patch("src.ai.agents.creative_director_agent.save_creative_directions") as save:
                save.side_effect=lambda value,filename:_save(value,filename,root/"creative");output=agent.run(knowledge,strategy,content)
            sent=[x["unique_id"] for call in request.call_args_list for x in call.args[2]]
            self.assertEqual(sent,ids);self.assertEqual(len(sent),len(set(sent)));self.assertIsNotNone(output)


def _write_inputs(root: Path, content_plan: ContentPlan | None = None) -> tuple[Path, Path, Path]:
    knowledge_path = root / "palm-gardens.json"
    strategy_path = root / "palm-gardens-strategy.json"
    content_path = root / "palm-gardens-content-plan.json"
    knowledge_path.write_text(ProjectKnowledge(
        project=ProjectDetails(name="Palm Gardens", location="Baghdad"),
    ).to_json(), encoding="utf-8")
    strategy_path.write_text(MarketingStrategy().to_json(), encoding="utf-8")
    content_path.write_text((content_plan or _content_plan()).to_json(), encoding="utf-8")
    return knowledge_path, strategy_path, content_path


def _save(plan: CreativeDirectionPlan, filename: str, directory: Path) -> Path:
    directory.mkdir()
    path = directory / f"{filename}.json"
    path.write_text(plan.to_json(), encoding="utf-8")
    return path


def _plan_with_ids(*ids:str)->ContentPlan:
    base=_content_plan().to_dict()["pillars"][0]["content_ideas"][0]
    return ContentPlan(pillars=[ContentPillar(name="P",content_ideas=[ContentIdea(**{**base,"unique_id":item,"title":item}) for item in ids])])


def _creative_for_ids(*ids:str)->CreativeDirectionPlan:
    directions=[]
    for item in ids:
        value=_creative_plan(item).creative_directions[0];value.creative_direction_id="cd_"+item;directions.append(value)
    return CreativeDirectionPlan(directions)
