"""Tests for dependency-aware selection, cache validation, and resume state."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.execution.stages import STAGE_ORDER, StageCache, select_stages


class StageExecutionTests(unittest.TestCase):
    def test_stage_only_and_from_stage(self) -> None:
        self.assertEqual(select_stages(stage="content-planner").requested, ("content-planner",))
        selected = select_stages(from_stage="visual-opportunities").requested
        self.assertIn("visual-opportunities", selected); self.assertIn("image-processing-planner", selected)
        self.assertNotIn("asset-intelligence", selected)
        downstream = select_stages(from_stage="brand-composer").requested
        self.assertIn("brand-composer", downstream); self.assertIn("branded-image-qa", downstream)

    def test_force_stage_selects_and_forces_exactly_one_stage(self) -> None:
        for stage in ("content-planner", "image-output-qa", "brand-composer", "branded-image-qa"):
            selected = select_stages(force_stage=stage)
            self.assertEqual(selected.requested, (stage,)); self.assertEqual(selected.forced, frozenset({stage}))

    def test_force_all_and_unknown_stage(self) -> None:
        selected = select_stages(force_all=True)
        self.assertEqual(selected.requested, STAGE_ORDER); self.assertEqual(len(selected.forced), len(STAGE_ORDER))
        with self.assertRaisesRegex(ValueError, "Unknown stage"): select_stages(from_stage="made-up")

    def test_valid_cache_and_corruption_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/"source.pdf"; source.write_bytes(b"pdf")
            inp = root/"input.json"; inp.write_text('{"ok": true}', encoding="utf-8")
            out = root/"output.json"; out.write_text('{"ok": true}', encoding="utf-8")
            with patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY", root/"manifests"), patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY", root/"cache"):
                cache = StageCache("p", [source]); expected = cache.expected("content-planner", [inp], module_version="9")
                cache.complete("content-planner", [out], expected)
                self.assertTrue(cache.valid("content-planner", [out], expected)[0])
                out.write_text("{broken", encoding="utf-8")
                self.assertFalse(cache.valid("content-planner", [out], expected)[0])

    def test_source_and_prompt_changes_make_cache_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/"s.pdf"; source.write_bytes(b"one"); inp=root/"i.json"; inp.write_text("{}", encoding="utf-8"); out=root/"o.json"; out.write_text("{}", encoding="utf-8")
            with patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY", root/"m"), patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY", root/"c"):
                first=StageCache("p", [source]); expected=first.expected("content-planner", [inp], prompt_version="1"); first.complete("content-planner", [out], expected)
                changed_prompt=first.expected("content-planner", [inp], prompt_version="2")
                self.assertFalse(first.valid("content-planner", [out], changed_prompt)[0])
                source.write_bytes(b"two"); second=StageCache("p", [source]); changed_source=second.expected("content-planner", [inp], prompt_version="1")
                self.assertFalse(second.valid("content-planner", [out], changed_source)[0])

    def test_branded_content_mode_invalidates_legacy_cache_and_status_is_current(self) -> None:
        import app
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inp=root/"content-plan.json";inp.write_text("{}",encoding="utf-8");out=root/"slide.jpg";out.write_bytes(b"slide")
            with patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY",root/"m"),patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY",root/"c"):
                cache=StageCache("p",[]);legacy=cache.expected("branded-content",[inp],module_version="1.0.0",config={"limit":3,"format":"instagram_feed_4_5"});cache.complete("branded-content",[out],legacy)
                current=cache.expected("branded-content",[inp],module_version="3.1.0",config={"mode":app.BRANDED_CONTENT_CACHE_MODE,"carousel_limit":10,"format":"instagram_feed_4_5"})
                self.assertFalse(cache.valid("branded-content",[out],current)[0])
                self.assertIn("consuming complete content plan",app.BRANDED_CONTENT_RUN_DESCRIPTION);self.assertNotIn("posts 001-002",app.BRANDED_CONTENT_RUN_DESCRIPTION);self.assertNotIn("top 3 selected originals",app.BRANDED_CONTENT_RUN_DESCRIPTION)

    def test_forced_changed_output_marks_only_downstream_stale_without_running_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/"content.json";out.write_text('{"v":1}',encoding="utf-8")
            with patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY",root/"m"),patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY",root/"c"):
                cache=StageCache("p",[]);expected=cache.expected("content-planner",[]);cache.complete("content-planner",[out],expected)
                out.write_text('{"v":2}',encoding="utf-8");cache.forced_stage="content-planner";cache.begin("content-planner");cache.complete("content-planner",[out],expected)
                self.assertEqual(cache.manifest["stages_actually_executed"],["content-planner"])
                self.assertEqual(cache.manifest["stage_statuses"]["content-planner"],"completed")
                self.assertEqual(cache.manifest["stage_statuses"]["creative-director"],"stale")
                self.assertNotIn("campaign-planner",cache.manifest["downstream_marked_stale"])

    def test_failure_manifest_can_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY", root/"m"), patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY", root/"c"):
                cache=StageCache("p", []); cache.manifest["stage_statuses"]={s:"completed" for s in STAGE_ORDER}; cache.fail("scene-planner", "stopped")
                resumed=StageCache("p", [])
                self.assertEqual(resumed.first_incomplete(), "scene-planner")
                data=json.loads(resumed.manifest_path.read_text(encoding="utf-8")); self.assertEqual(data["failed_stage"], "scene-planner")

    def test_forced_prerequisite_missing_and_corruption_are_explicit(self) -> None:
        import app
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);plan=root/"output"/"qa"/"P-image-qa.json"
            with patch.object(app,"PROJECT_ROOT",root),patch.object(app,"IMAGE_QA_OUTPUT_DIRECTORY",root/"output/qa"),patch("src.execution.stages.MANIFESTS_OUTPUT_DIRECTORY",root/"manifests"),patch("src.execution.stages.CACHE_METADATA_OUTPUT_DIRECTORY",root/"cache"):
                cache=StageCache("P",[])
                valid,error=app._validate_forced_prerequisites("branded-image-qa","P",cache)
                self.assertFalse(valid);self.assertIn("image-output-qa",error);self.assertIn("missing",error)
                plan.parent.mkdir(parents=True);plan.write_text("{broken",encoding="utf-8")
                valid,error=app._validate_forced_prerequisites("branded-image-qa","P",cache)
                self.assertFalse(valid);self.assertIn("corrupted",error)


if __name__ == "__main__": unittest.main()
