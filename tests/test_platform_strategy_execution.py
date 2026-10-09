from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from src.execution import (EARLIEST_PLATFORM_DEPENDENT_STAGE, PLATFORM_DEPENDENT_STAGES,
                           PLATFORM_INDEPENDENT_STAGES, STAGE_ORDER, StageCache)


class PlatformStrategyExecutionTests(unittest.TestCase):
    def test_dependency_boundary_is_canonical(self):
        self.assertEqual(EARLIEST_PLATFORM_DEPENDENT_STAGE,"campaign-planner")
        for stage in ("discover","document-analysis","text-extraction","knowledge-extraction","visual-extraction","asset-intelligence","visual-inventory","marketing-strategy","visual-opportunities"):
            self.assertIn(stage,PLATFORM_INDEPENDENT_STAGES)
        self.assertIn("content-planner",PLATFORM_DEPENDENT_STAGES)

    def test_default_applies_only_when_cli_absent(self):
        self.assertIsNone(app._parse_args([]).platform_strategy)
        self.assertEqual(app._resolve_platform_strategy(None),("both_platform_optimized","default"))
        self.assertEqual(app._resolve_platform_strategy("facebook_only"),("facebook_only","cli"))

    def test_malformed_strategy_is_rejected(self):
        with self.assertRaises(SystemExit):app._parse_args(["--platform-strategy",r"both\_platform\_optimized"])

    def test_cache_identity_changes_only_when_config_is_attached(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/"source";source.write_text("stable")
            with patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY",root/"manifests"),patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY",root/"cache"):
                cache=StageCache("project",[source])
                upstream_a=cache.expected("knowledge-extraction",[source]);upstream_b=cache.expected("knowledge-extraction",[source])
                downstream_a=cache.expected("content-planner",[source],config={"platform_strategy":"instagram_only"})
                downstream_b=cache.expected("content-planner",[source],config={"platform_strategy":"facebook_only"})
            self.assertEqual(upstream_a["cache_key"],upstream_b["cache_key"]);self.assertNotEqual(downstream_a["cache_key"],downstream_b["cache_key"])

    def test_strategy_only_command_uses_staged_runner(self):
        project=type("Project",(),{"name":"P"})()
        with patch.object(app,"find_project_inputs",return_value=[project]),patch.object(app,"_process_staged_planning",return_value=True) as staged,patch.object(app,"_process_default_cached") as monolithic:
            self.assertEqual(app.main(["--project","P","--platform-strategy","instagram_only"]),0)
        staged.assert_called_once();monolithic.assert_not_called()
        self.assertEqual(staged.call_args.args[1].from_stage,"campaign-planner")

if __name__=="__main__":unittest.main()
