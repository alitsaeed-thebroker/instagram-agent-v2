from __future__ import annotations

import json
import unittest

import tests.regression.test_foundation_hardening as foundation_fixture
from src.hardening import HardeningPipeline
from src.post_package import PostPackagePipeline
from src.social_review import SocialContentReview
from src.execution.lineage import attach_lineage


class SocialContentReviewTests(unittest.TestCase):
    def setUp(self)->None:
        self.fixture=foundation_fixture.FoundationHardeningRegressionTests();self.fixture.setUp();self.root=self.fixture.root;self.project=self.fixture.project
        self.fixture.fixture._write(f"output/strategy/{self.project}-strategy.json",{"project_id":self.project})
        self.fixture.fixture._write(f"output/visual-opportunities/{self.project}-visual-opportunities.json",{"project_id":self.project,"opportunities":[]})
        hard=HardeningPipeline(self.project,self.root);hard.creative_qa(force=True);hard.self_correct();hard.provenance_audit();hard.quality_report();hard.release()
        manifest=json.loads((self.root/f"output/production-manifests/{self.project}-branded-production-manifest.json").read_text());item=manifest["items"][0]
        intelligence={"project_id":self.project,"assets":[{"asset_id":item["source_asset_ids"][0],"project_id":self.project,"asset_type":"floorplan","asset_subtype":"technical_plan","source_path":item["source_image_path"],"source_hash":item["source_image_hash"]}]}
        self.fixture.fixture._write(f"output/asset-intelligence/{self.project}-asset-intelligence.json",intelligence)
        pipeline=PostPackagePipeline(self.project,self.root);pipeline.groups();pipeline.captions();pipeline.hashtags();pipeline.alt_text();pipeline.build();pipeline.qa()
    def tearDown(self)->None:self.fixture.tearDown()

    def test_offline_dashboard_contains_navigation_copy_zoom_source_and_unicode(self)->None:
        dashboard=SocialContentReview(self.project+" د ک",self.root)
        # Keep project isolation strict by using the fixture's actual ID for rendering.
        dashboard=SocialContentReview(self.project,self.root);html_path,json_path=dashboard.render();page=html_path.read_text(encoding="utf-8");data=json.loads(json_path.read_text(encoding="utf-8"))
        self.assertIn("Next →",page);self.assertIn("data-slide",page);self.assertIn("Copy Hashtags",page);self.assertIn('data-zoom="2"',page);self.assertIn("Side by side",page);self.assertNotIn("cdn.",page.casefold());self.assertNotIn("http://",page.casefold());self.assertEqual(data["package_count"],1);self.assertEqual(data["source_comparisons_available"],1);self.assertEqual(data["provenance_completeness"],{"complete":1,"total":1});self.assertTrue(data["packages"][0]["slides"][0]["technical_visual"])

    def test_project_isolation_and_semantic_warning_are_diagnostic_only(self)->None:
        package_path=self.root/f"output/post-packages/{self.project}-post-packages.json";payload=json.loads(package_path.read_text());payload["packages"][0]["alt_text"]="Branded site plan showing visible plots and roads without marketing language.";lineage=payload["lineage"];payload=attach_lineage(payload,stage="post-package-manifest",canonical_fingerprint=lineage["canonical_department2_fingerprint"],parents=lineage["parent_artifact_fingerprints"]);package_path.write_text(json.dumps(payload));PostPackagePipeline(self.project,self.root).qa();before_render=package_path.read_bytes();data=json.loads(SocialContentReview(self.project,self.root).render()[1].read_text());self.assertEqual(package_path.read_bytes(),before_render);self.assertTrue(data["semantic_warnings"])
        provenance_path=self.root/f"output/provenance/{self.project}-provenance-audit.json";provenance=json.loads(provenance_path.read_text());provenance["project_id"]="another-project";provenance_path.write_text(json.dumps(provenance));
        with self.assertRaises(ValueError):SocialContentReview(self.project,self.root).render()

    def test_zero_packages_are_never_publishing_ready(self)->None:
        path=self.root/f"output/post-packages/{self.project}-post-packages.json";payload=json.loads(path.read_text());payload["packages"]=[];lineage=payload["lineage"];payload=attach_lineage(payload,stage="post-package-manifest",canonical_fingerprint=lineage["canonical_department2_fingerprint"],parents=lineage["parent_artifact_fingerprints"]);path.write_text(json.dumps(payload))
        PostPackagePipeline(self.project,self.root).qa()
        data=json.loads(SocialContentReview(self.project,self.root).render()[1].read_text());self.assertEqual(data["package_count"],0);self.assertEqual(data["overall_readiness"],"NO_PUBLISHABLE_CONTENT")


if __name__=="__main__":unittest.main()
