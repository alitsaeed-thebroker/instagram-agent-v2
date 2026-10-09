from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import unittest

import tests.regression.test_foundation_hardening as foundation_fixture
from src.hardening import HardeningPipeline
from src.post_package import PostPackagePipeline
from src.publishing import PublishingFoundation
from src.social_review import SocialContentReview
from src.execution.lineage import attach_lineage


class PublishingFoundationTests(unittest.TestCase):
    def setUp(self)->None:
        self.fixture=foundation_fixture.FoundationHardeningRegressionTests();self.fixture.setUp();self.root=self.fixture.root;self.project=self.fixture.project
        self.fixture.fixture._write(f"output/strategy/{self.project}-strategy.json",{"project_id":self.project});self.fixture.fixture._write(f"output/visual-opportunities/{self.project}-visual-opportunities.json",{"project_id":self.project,"opportunities":[]})
        config={"schema_version":"1.0.0","timezone":"Asia/Baghdad","default_mode":"manual","minimum_spacing_minutes":60,"max_posts_per_day":3,"allow_same_package_multi_platform":True,"allow_duplicate_package_same_platform":False,"retry_policy":{"max_attempts":3,"initial_delay_minutes":5,"backoff_multiplier":2}}
        self.fixture.fixture._write("input/publishing/publishing-config.json",config)
        hard=HardeningPipeline(self.project,self.root);hard.creative_qa(force=True);hard.self_correct();hard.provenance_audit();hard.quality_report();hard.release()
        manifest=json.loads((self.root/f"output/production-manifests/{self.project}-branded-production-manifest.json").read_text());item=manifest["items"][0];self.fixture.fixture._write(f"output/asset-intelligence/{self.project}-asset-intelligence.json",{"project_id":self.project,"assets":[{"asset_id":item["source_asset_ids"][0],"project_id":self.project,"asset_type":"exterior","source_path":item["source_image_path"],"source_hash":item["source_image_hash"]}]})
        # This fixture represents the project's first overview publication.
        content_path=self.root/f"output/content/{self.project}-content-plan.json"
        content=json.loads(content_path.read_text());lineage=content["lineage"]
        for idea in content.get("content_ideas",[]):idea["content_category"]="project_overview"
        content=attach_lineage(content,stage="department3-content-plan",canonical_fingerprint=lineage["canonical_department2_fingerprint"],parents=lineage["parent_artifact_fingerprints"])
        content_path.write_text(json.dumps(content))
        # Source-bound, human-reviewed synthetic overview fixture for publishing safety tests.
        asset_path=self.root/f"output/asset-intelligence/{self.project}-asset-intelligence.json"
        assets=json.loads(asset_path.read_text());asset=assets["assets"][0]
        asset.update(source_document_hash="fixture-pdf-hash",source_page=1)
        asset_path.write_text(json.dumps(assets))
        review={k:asset.get(k) for k in ("asset_id","project_id","source_hash","source_document_hash","source_page")}
        review.update(purpose="project_overview",scope="whole_development",status="APPROVED",reviewer="synthetic_test_fixture")
        self.fixture.fixture._write("input/visual-review/project-overview-reviews.json",{"reviews":[review]})
        pipeline=PostPackagePipeline(self.project,self.root);pipeline.groups();pipeline.captions();pipeline.hashtags();pipeline.alt_text();pipeline.build();pipeline.qa();SocialContentReview(self.project,self.root).render();self.pub=PublishingFoundation(self.project,self.root)
    def tearDown(self)->None:self.fixture.tearDown()

    def test_queue_is_persistent_deterministic_and_manual_schedule_does_not_guess(self)->None:
        first=json.loads(self.pub.queue().read_text());second=json.loads(self.pub.queue().read_text());self.assertEqual(len(second["items"]),1);self.assertEqual(first["items"][0]["idempotency_key"],second["items"][0]["idempotency_key"]);self.assertEqual(first["items"][0]["priority"],100)
        schedule=json.loads(self.pub.schedule().read_text());self.assertIsNone(schedule["items"][0]["scheduled_at_local"]);self.assertEqual(schedule["items"][0]["status"],"queued")

    def test_exact_schedule_timezone_preflight_and_media_tamper_block(self)->None:
        queue=json.loads(self.pub.queue().read_text());config=json.loads(self.pub.config_path.read_text());config["manual_schedule"]={queue["items"][0]["queue_item_id"]:(datetime.now(timezone.utc)+timedelta(days=1)).replace(tzinfo=None).isoformat()};self.pub.config_path.write_text(json.dumps(config));schedule=json.loads(self.pub.schedule().read_text());self.assertIn("+03:00",schedule["items"][0]["scheduled_at_local"]);self.assertTrue(schedule["items"][0]["scheduled_at_utc"].endswith("+00:00"));self.assertEqual(json.loads(self.pub.preflight().read_text())["items"][0]["status"],"ready")
        packages=self.root/f"output/post-packages/{self.project}-post-packages.json";value=json.loads(packages.read_text());value["packages"][0]["image"]["image_hash"]="tampered";packages.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,"artifact fingerprint mismatch"):self.pub.preflight()

    def test_mock_payload_receipt_history_and_idempotency_reuse(self)->None:
        self.pub.queue();self.pub.schedule();self.pub.preflight();manifest=json.loads(self.pub.mock_publish().read_text());self.assertEqual(len(manifest["mock_receipts"]),1);self.assertTrue(manifest["mock_receipts"][0]["dry_run"]);payloads=list(self.pub.payload_dir.glob("*.json"));self.assertEqual(len(payloads),1);payload=json.loads(payloads[0].read_text());self.assertEqual(payload["slide_order"],[1]);self.assertTrue(payload["dry_run"])
        again=json.loads(self.pub.mock_publish().read_text());self.assertEqual(len(again["mock_receipts"]),1);self.assertTrue(any(x["status"]=="simulated_success_already_recorded" for x in again["publication_history"]));final=json.loads(self.pub.manifest().read_text());self.assertEqual(final["mock_receipts"][0]["payload_hash"],manifest["mock_receipts"][0]["payload_hash"])

    def test_transient_retry_backoff_and_permanent_failure(self)->None:
        self.pub.queue();self.pub.schedule();self.pub.preflight();self.pub.mock_publish("network");queue=json.loads(self.pub.queue_path.read_text())["items"][0];self.assertEqual(queue["status"],"retry_wait");self.assertEqual(queue["attempt_count"],1);self.assertTrue(queue["next_retry_at"])
        # A clean fixture would permanently fail immediately; reset retry state here.
        self.pub.mock_publish("validation");queue=json.loads(self.pub.queue_path.read_text())["items"][0];self.assertEqual(queue["status"],"failed");self.assertIsNone(queue["next_retry_at"])

    def test_unexpected_empty_package_state_preserves_active_queue(self)->None:
        before=json.loads(self.pub.queue().read_text());path=self.root/f"output/post-packages/{self.project}-post-packages.json";payload=json.loads(path.read_text());payload.update(status="no_content_unexpected",semantic_manifest_valid=False,packages=[]);lineage=payload["lineage"];payload=attach_lineage(payload,stage="post-package-manifest",canonical_fingerprint=lineage["canonical_department2_fingerprint"],parents=lineage["parent_artifact_fingerprints"]);path.write_text(json.dumps(payload));PostPackagePipeline(self.project,self.root).qa();SocialContentReview(self.project,self.root).render()
        after=json.loads(self.pub.queue().read_text());self.assertEqual(after["reconciliation_status"],"blocked_invalid_upstream_package_state");self.assertEqual([x["idempotency_key"] for x in before["items"]],[x["idempotency_key"] for x in after["items"]]);self.assertNotIn("superseded",{x["status"] for x in after["items"]})

    def test_socially_blocked_queue_item_cannot_be_promoted_by_preflight(self)->None:
        queue=json.loads(self.pub.queue().read_text());queue["items"][0]["status"]="blocked";queue["items"][0]["errors"]=["social review is not ready"];lineage=queue["lineage"];queue=attach_lineage(queue,stage="publishing-queue",canonical_fingerprint=lineage["canonical_department2_fingerprint"],parents=lineage["parent_artifact_fingerprints"]);self.pub.queue_path.write_text(json.dumps(queue))
        result=json.loads(self.pub.preflight().read_text())["items"][0];self.assertEqual(result["status"],"blocked");self.assertIn("social review is not ready",result["blockers"])
        after=json.loads(self.pub.queue_path.read_text())["items"][0];self.assertEqual(after["status"],"blocked")


if __name__=="__main__":unittest.main()
