from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import tests.test_brand_composer as brand_fixture
from src.branding import BrandComposer
from src.execution.stages import STAGE_ORDER, select_stages
from src.hardening import HardeningPipeline, run_health_check


class FoundationHardeningRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture=brand_fixture.BrandComposerTests();self.fixture.setUp();self.root=self.fixture.root;self.project=self.fixture.project
        visual=self.root/f"output/visual-inventory/{self.project}-visual-inventory.json"
        visual.write_text(json.dumps({"project_id":self.project,"assets":[{"asset_id":"asset-1","source_document":"fixture.pdf","source_page":1,"source_hash":"abc"}]}))
        self.fixture._write(f"output/asset-intelligence/{self.project}-asset-intelligence.json",{"project_id":self.project,"assets":[{"asset_id":"asset-1"}]})
        composer=BrandComposer(self.project,self.root);composer.compose();composer.output_qa(force=True);composer.qa(force=True);self.pipeline=HardeningPipeline(self.project,self.root)
    def tearDown(self) -> None:self.fixture.tearDown()

    def test_balanced_creative_quality_and_oversized_branding_detection(self) -> None:
        result=json.loads(self.pipeline.creative_qa(force=True).read_text())["items"][0]
        self.assertGreaterEqual(result["creative_score"],85);self.assertIn(result["status"],{"exceptional","production_ready","good_minor_improvements"})
        composer=BrandComposer(self.project,self.root);payload=json.loads(composer.plan_path.read_text());plan=payload["plans"][0];plan["logo_position"][2]=round(plan["width"]*.3);plan["typography"]["font_sizes"]["headline"]=round(plan["height"]*.1);plan["overlay_regions"]=[[0,0,plan["width"],round(plan["height"]*.6)]];composer.plan_path.write_text(json.dumps(payload))
        weak=json.loads(self.pipeline.creative_qa(force=True).read_text())["items"][0]
        self.assertLess(weak["creative_score"],85);self.assertEqual(weak["responsible_stage"],"visual-art-director");self.assertTrue(weak["recommended_corrections"])

    def test_self_correction_is_item_scoped_and_retry_bounded(self) -> None:
        composer=BrandComposer(self.project,self.root);payload=json.loads(composer.plan_path.read_text());plan=payload["plans"][0];plan["logo_position"][2]=round(plan["width"]*.3);plan["overlay_regions"]=[[0,0,plan["width"],round(plan["height"]*.6)]];composer.plan_path.write_text(json.dumps(payload));self.pipeline.creative_qa(force=True)
        log=json.loads(self.pipeline.self_correct(force=True).read_text());self.assertLessEqual(len(log["records"]),2);self.assertEqual(log["records"][0]["responsible_stage"],"visual-art-director")
        self.pipeline.self_correct(force=True);self.pipeline.self_correct(force=True);log=json.loads(self.pipeline.corrections_path.read_text());self.assertLessEqual(sum(r["branded_item_id"]==plan["branded_item_id"] for r in log["records"]),2)

    def test_complete_provenance_quality_and_sequential_immutable_releases(self) -> None:
        self.pipeline.creative_qa(force=True);self.pipeline.self_correct(force=True);audit=json.loads(self.pipeline.provenance_audit(force=True).read_text())
        self.assertEqual(audit["items"][0]["integrity_status"],"complete");self.assertEqual(audit["items"][0]["source_pages"],[1]);self.assertTrue(audit["items"][0]["brand_refs"]["logo_hash"])
        quality=json.loads(self.pipeline.quality_report(force=True).read_text());self.assertLess(quality["overall_quality_score"],100);self.assertIn(quality["production_readiness"],{"exceptional","production_ready","production_ready_with_warnings","revision_recommended"})
        first=self.pipeline.release();before=first.read_bytes();second=self.pipeline.release(force=True)
        self.assertEqual(first.parent.name,"release-001");self.assertEqual(second.parent.name,"release-002");self.assertEqual(first.read_bytes(),before)
        pointer=json.loads((self.root/f"output/runs/{self.project}/current.json").read_text());self.assertTrue(pointer["run_id"])

    def test_health_report_detects_invalid_release_and_force_semantics_remain_exact(self) -> None:
        self.pipeline.creative_qa(force=True);self.pipeline.self_correct();self.pipeline.provenance_audit();self.pipeline.quality_report();self.pipeline.release()
        report=json.loads(run_health_check(self.root,self.project).read_text());self.assertIn(report["status"],{"HEALTHY","HEALTHY_WITH_WARNINGS"})
        (self.root/f"output/releases/{self.project}/release-001/manifest.json").write_text("{broken")
        degraded=json.loads(run_health_check(self.root,self.project).read_text());self.assertEqual(degraded["status"],"CRITICAL")
        for stage in ("creative-visual-qa","self-correction","provenance-audit","release-manager"):
            selection=select_stages(force_stage=stage);self.assertEqual(selection.requested,(stage,));self.assertEqual(selection.forced,frozenset({stage}))
        self.assertEqual(select_stages(force_all=True).requested,STAGE_ORDER)


if __name__=="__main__":unittest.main()
