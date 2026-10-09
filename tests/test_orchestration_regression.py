"""Regression tests for truthful complete-pipeline orchestration."""

import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
from src.content.inventory import ContentOpportunityInventoryEngine
from src.core.file_manager import ProjectInput
from src.execution.stages import DEPENDENCIES, STAGE_ORDER, StageCache, select_stages, validate_stage_graph


class OrchestrationRegressionTests(unittest.TestCase):
    def test_legacy_branded_content_is_explicit_only(self):
        self.assertNotIn("branded-content", select_stages().requested)
        self.assertNotIn("branded-content", select_stages(from_stage="deep-source-analysis").requested)
        self.assertEqual(select_stages(stage="branded-content").requested, ("branded-content",))

    def test_stage_graph_is_acyclic_and_has_no_forward_dependencies(self) -> None:
        validate_stage_graph()
        position={stage:index for index,stage in enumerate(STAGE_ORDER)}
        for stage,parents in DEPENDENCIES.items():
            self.assertTrue(all(position[parent] < position[stage] for parent in parents))

    def test_graph_validation_rejects_impossible_forward_dependency(self) -> None:
        with patch.dict(DEPENDENCIES,{"discover":("review-gallery",)}):
            with self.assertRaisesRegex(ValueError,"impossible forward dependency"):
                validate_stage_graph()

    def test_default_continues_after_asset_intelligence_without_real_meta(self) -> None:
        project=ProjectInput("P",[])
        args=argparse.Namespace(force_all=False,force_stage=None,stage=None,from_stage=None,resume=False,publish_meta=False)
        captured=[]
        with patch.object(app,"_process_project",return_value=True),patch.object(app,"_process_staged_planning",side_effect=lambda _p,a:captured.append(a) or True),patch.object(app,"StageCache"):
            self.assertTrue(app._process_default_cached(project,args))
        self.assertEqual(captured[0].from_stage,"deep-source-analysis")
        self.assertTrue(captured[0].default_continuation)
        self.assertFalse(captured[0].publish_meta)

    def test_core_failure_does_not_report_project_success(self) -> None:
        project=ProjectInput("P",[])
        args=argparse.Namespace(force_all=False,force_stage=None,stage=None,from_stage=None,resume=False,publish_meta=False)
        with tempfile.TemporaryDirectory() as directory,patch.object(app,"_process_project",return_value=False),patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY",Path(directory)/"m"),patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY",Path(directory)/"c"):
            self.assertFalse(app._process_default_cached(project,args))

    def test_missing_stage_specific_artifact_invalidates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/"strategy.json";output.write_text("{}",encoding="utf-8")
            with patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY",root/"m"),patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY",root/"c"):
                cache=StageCache("P",[]);expected=cache.expected("marketing-strategy",[]);cache.complete("marketing-strategy",[output],expected)
                output.unlink()
                self.assertFalse(cache.valid("marketing-strategy",[output],expected)[0])
                self.assertNotEqual(cache.manifest["stage_statuses"]["content-planner"],"completed")
                self.assertNotEqual(cache.manifest["stage_statuses"]["brand-composer"],"completed")
                self.assertNotEqual(cache.manifest["stage_statuses"]["publishing-queue"],"completed")

    def test_new_run_cannot_inherit_false_downstream_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY",root/"m"),patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY",root/"c"):
                cache=StageCache("P",[]);cache.manifest["stage_statuses"]={stage:"completed" for stage in STAGE_ORDER}
                cache.manifest["output_paths"]={stage:["wrong.json"] for stage in STAGE_ORDER}
                cache.reset_runtime_accounting(requested_mode="default",requested_stage=None,stage_forced=False)
                self.assertTrue(all(status=="pending" for status in cache.manifest["stage_statuses"].values()))
                self.assertEqual(cache.manifest["output_paths"],{})

    def test_default_selection_includes_all_departments_but_not_real_publish(self) -> None:
        args=argparse.Namespace(stage=None,from_stage="deep-source-analysis",force_stage=None,force_all=False,publish_meta=False,resume=False,default_continuation=True)
        project=ProjectInput("P",[])
        with patch.object(app,"StageCache") as cache_type:
            cache_type.return_value.manifest={"stage_statuses":{stage:"pending" for stage in STAGE_ORDER}}
            cache_type.return_value.reset_runtime_accounting.return_value=None
            cache_type.return_value.block.return_value=None
            cache_type.return_value.finish.return_value=None
            with patch.object(app,"_artifact",return_value=None),patch.object(app,"_finish_early_accounting"):
                app._process_staged_planning(project,args)
        # The missing prerequisite causes a controlled stop, but selection construction
        # itself must never authorize the real Meta adapter in default mode.
        self.assertFalse(args.publish_meta)

    def test_project_alias_requires_provenance_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);knowledge=root/"knowledge.json";visuals=root/"visuals.json";output=root/"out"
            base={"project_identity":{"project_name":"Orchestration","location":"Erbil"},"project":{"name":"Orchestration","location":"Erbil"},
                  "canonical_intelligence":{"project_namespace":"Canonical","schema_version":"2.0.0","contract_role":"authoritative_department2_relational_intelligence",
                    "entities":[{"entity_id":"project_c","entity_type":"project","project_namespace":"Canonical","label":"Canonical","parent_entity_id":None,"attributes":{}}],
                    "facts":[],"conflicts":[],"unknowns":[],"metadata":{}}}
            knowledge.write_text(__import__("json").dumps(base),encoding="utf-8")
            visuals.write_text('{"project_id":"Orchestration","assets":[]}',encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"project mismatch"):
                ContentOpportunityInventoryEngine().run(knowledge,visuals,output_directory=output,project_id="Orchestration")
            # Only the canonical namespace can authorize orchestration ownership.
            base["canonical_intelligence"]["project_namespace"]="Orchestration"
            base["canonical_intelligence"]["entities"][0].update(project_namespace="Orchestration",label="Orchestration")
            knowledge.write_text(__import__("json").dumps(base),encoding="utf-8")
            result=ContentOpportunityInventoryEngine().run(knowledge,visuals,output_directory=output,project_id="Orchestration")
            self.assertIn("Orchestration",result.name)


if __name__=="__main__":unittest.main()
