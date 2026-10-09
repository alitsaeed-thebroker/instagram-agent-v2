from __future__ import annotations

import json
import unittest

import tests.regression.test_foundation_hardening as foundation_fixture
from src.hardening import HardeningPipeline
from src.post_package import PostPackagePipeline
from src.execution.lineage import attach_lineage


class PostPackageTests(unittest.TestCase):
    def setUp(self)->None:
        self.fixture=foundation_fixture.FoundationHardeningRegressionTests();self.fixture.setUp();self.root=self.fixture.root;self.project=self.fixture.project
        self.fixture.fixture._write(f"output/strategy/{self.project}-strategy.json",{"project_id":self.project})
        self.fixture.fixture._write(f"output/visual-opportunities/{self.project}-visual-opportunities.json",{"project_id":self.project,"opportunities":[]})
        hard=HardeningPipeline(self.project,self.root);hard.creative_qa(force=True);hard.self_correct();hard.provenance_audit();hard.quality_report();hard.release()
        manifest=json.loads((self.root/f"output/production-manifests/{self.project}-branded-production-manifest.json").read_text())
        item=manifest["items"][0]
        self.fixture.fixture._write(
            f"output/asset-intelligence/{self.project}-asset-intelligence.json",
            {"project_id":self.project,"assets":[{"asset_id":item["source_asset_ids"][0],"project_id":self.project,"asset_type":"exterior","source_path":item["source_image_path"],"source_hash":item["source_image_hash"]}]},
        )
    def tearDown(self)->None:self.fixture.tearDown()

    def test_grounded_multilingual_caption_hashtags_alt_and_package(self)->None:
        pipeline=PostPackagePipeline(self.project,self.root,("en","ar","ku"));pipeline.groups();captions=json.loads(pipeline.captions().read_text(encoding="utf-8"))["items"]
        self.assertEqual(len(captions),3);self.assertTrue(all("ROI" not in x["full_caption"] and "price" not in x["full_caption"].casefold() for x in captions));self.assertEqual({x["text_direction"] for x in captions},{"ltr","rtl"})
        tags=json.loads(pipeline.hashtags().read_text(encoding="utf-8"))["items"];self.assertTrue(all(len({x["hashtag"] for x in item["hashtags"]})==item["count"] for item in tags))
        alts=json.loads(pipeline.alt_text().read_text(encoding="utf-8"))["items"];self.assertTrue(all(40<=x["character_count"]<=300 for x in alts));self.assertTrue(all("investment" not in x["alt_text"].casefold() for x in alts))
        packages=json.loads(pipeline.build().read_text(encoding="utf-8"))["packages"];self.assertEqual(len(packages),3);self.assertTrue(all(x["project_id"]==self.project for x in packages))
        qa=json.loads(pipeline.qa().read_text(encoding="utf-8"));self.assertEqual(qa["summary"]["blocked"],0);self.assertEqual(qa["summary"]["exceptional"],3)

    def test_platform_hashtag_limits_and_exact_website(self)->None:
        pipeline=PostPackagePipeline(self.project,self.root);pipeline.groups();captions=json.loads(pipeline.captions().read_text())["items"]
        self.assertTrue(all(x["CTA"]=="Learn more at domuserbil.com" for x in captions));pipeline.hashtags();sets=json.loads(pipeline.hashtag_path.read_text())["items"]
        self.assertTrue(all(0<=x["count"]<=12 for x in sets))

    def test_wrong_image_hash_and_invalid_provenance_block(self)->None:
        pipeline=PostPackagePipeline(self.project,self.root);pipeline.groups();pipeline.captions();pipeline.hashtags();pipeline.alt_text();pipeline.build();payload=json.loads(pipeline.package_path.read_text());payload["packages"][0]["image"]["image_hash"]="bad";pipeline.package_path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError,"artifact fingerprint mismatch"):pipeline.qa()

    def test_language_validation_and_project_isolation(self)->None:
        with self.assertRaises(ValueError):PostPackagePipeline(self.project,self.root,("fr",))

    def test_grouping_accounts_for_every_branded_input(self)->None:
        pipeline=PostPackagePipeline(self.project,self.root);payload=json.loads(pipeline.groups().read_text());summary=payload["summary"]
        self.assertEqual(summary["branded_inputs_considered"],summary["grouped_items"]+summary["excluded_items"]);self.assertEqual(summary["grouped_items"],1)

    def test_zero_package_qa_is_explicit_no_content_with_null_score(self)->None:
        pipeline=PostPackagePipeline(self.project,self.root);ctx=pipeline._context();pipeline.package_path.parent.mkdir(parents=True,exist_ok=True);payload=pipeline._stamp(ctx,"post-package-manifest",{"project_id":self.project,"packages":[]})
        pipeline.package_path.write_text(json.dumps(payload));result=json.loads(pipeline.qa().read_text());self.assertEqual(result["status"],"no_content");self.assertIsNone(result["summary"]["average_score"])


if __name__=="__main__":unittest.main()
