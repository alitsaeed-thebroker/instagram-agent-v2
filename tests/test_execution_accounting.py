"""Exact, exclusive runtime stage and API-call accounting."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
from src.execution.stages import StageCache


class ExecutionAccountingTests(unittest.TestCase):
    def test_mixed_outcomes_are_exclusive_and_manifest_records_are_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/"out.json";output.write_text("{}")
            with patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY",root/"manifests"),patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY",root/"cache"):
                cache=StageCache("P",[]);cache.reset_runtime_accounting(requested_mode="stage",requested_stage="content-planner",stage_forced=False)
                cache.begin("content-planner");cache.complete("content-planner",[output],cache.expected("content-planner",[]))
                cache.skip("creative-director",True);cache.reuse_prerequisite("campaign-planner",output);cache.not_requested("scene-planner")
                cache.fail("shot-planner","failed");cache.block("brand-composer","blocked")
                summary=cache.accounting_summary()
                self.assertEqual(summary["stages_executed"],1);self.assertEqual(summary["stages_skipped_cached"],1);self.assertEqual(summary["prerequisites_reused"],1)
                self.assertEqual(summary["stages_not_requested"],1);self.assertEqual(summary["stages_failed"],1);self.assertEqual(summary["stages_blocked"],1)
                self.assertEqual(len(cache.runtime_records),6);self.assertEqual(len({r["stage_name"] for r in cache.runtime_records.values()}),6)
                record=cache.runtime_records["creative-director"];self.assertEqual(record["execution_state"],"skipped_cached");self.assertTrue(record["cache_hit"]);self.assertFalse(record["executed"])
                saved=json.loads(cache.manifest_path.read_text());self.assertEqual(len(saved["stage_records"]),6);self.assertIn("duration_ms",saved["stage_records"][0])

    def test_api_calls_executed_avoided_failed_and_non_ai_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/"o.json";output.write_text("{}")
            with patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY",root/"m"),patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY",root/"c"):
                cache=StageCache("P",[]);cache.reset_runtime_accounting(requested_mode="from_stage",requested_stage="content-planner",stage_forced=False)
                cache.begin("content-planner");cache.complete("content-planner",[output],cache.expected("content-planner",[]));cache.skip("creative-director",True);cache.fail("scene-planner","api failed")
                cache.begin("branded-image-qa");cache.complete("branded-image-qa",[output],cache.expected("branded-image-qa",[]))
                summary=cache.accounting_summary();self.assertEqual(summary["api_calls_executed"],1);self.assertEqual(summary["api_calls_avoided_by_cache"],1);self.assertEqual(summary["api_calls_failed"],1);self.assertEqual(summary["api_calls_retried"],0)

    def test_prerequisite_state_cannot_be_double_counted_as_not_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);artifact=root/"plan.json";artifact.write_text("{}")
            with patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY",root/"m"),patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY",root/"c"):
                cache=StageCache("P",[]);cache.reset_runtime_accounting(requested_mode="force_stage",requested_stage="branded-image-qa",stage_forced=True);cache.reuse_prerequisite("brand-composer",artifact)
                if "brand-composer" not in cache.runtime_records:cache.not_requested("brand-composer")
                self.assertEqual(cache.accounting_summary()["prerequisites_reused"],1);self.assertEqual(cache.accounting_summary()["stages_not_requested"],0)

    def test_health_check_is_utility_not_stage_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);report=root/"health.json";report.write_text(json.dumps({"status":"HEALTHY","projects":[]}))
            with patch.object(app,"PROJECT_ROOT",root),patch.object(app,"run_health_check",return_value=report):
                self.assertEqual(app.main(["--health-check"]),0);self.assertEqual(app._RUN_ACCOUNTING,[])


if __name__=="__main__":unittest.main()
