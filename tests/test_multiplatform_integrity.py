from __future__ import annotations
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from src.execution import ancestors
from src.publishing.foundation import PublishingFoundation, QUEUE_VERSION, QUEUE_RECONCILIATION_VERSION, _adapter_eligibility, _queue_summary
from src.social_review.dashboard import _independent_caption_warnings
from src.planning.engine import _platform_allocation
from src.platforms import CampaignPlatformStrategy
from src.core.console import has_mojibake
from src.execution.stages import _semantic_file_hash
from src.branding.composer import _cache_signature

def package(identity,platform,master="master",kind="single_post",caption="Same useful caption for buyers"):
    return {"package_id":identity,"package_type":kind,"platform":platform,"destination":platform,"master_concept_id":master,"caption":{"full_caption":caption}}

class MultiPlatformIntegrityTests(unittest.TestCase):
    def test_upstream_count_comes_from_dependency_graph(self):
        required=ancestors("campaign-planner")
        self.assertIn("discover",required);self.assertIn("visual-opportunities",required);self.assertEqual(len(required),len(set(required)))
    def test_cross_platform_variants_are_not_duplicates(self):
        self.assertEqual(_independent_caption_warnings([package("ig","instagram"),package("fb","facebook")]),[])
    def test_same_platform_duplicate_has_diagnostic_reason(self):
        warnings=_independent_caption_warnings([package("a","instagram","a"),package("b","instagram","b")])
        self.assertEqual(len(warnings),1);self.assertFalse(warnings[0]["intentional_variant"]);self.assertTrue(warnings[0]["reason"])
    def test_distinct_ideas_and_assets_with_semantic_similarity_are_diagnostic_only(self):
        a=package("a","instagram","m1");b=package("b","instagram","m2");a.update(content_idea_id="i1",slides=[{"source_asset_ids":["asset1"]}]);b.update(content_idea_id="i2",slides=[{"source_asset_ids":["asset2"]}])
        warnings,analysis=__import__("src.social_review.dashboard",fromlist=["_duplicate_analysis"])._duplicate_analysis([a,b])
        self.assertEqual(warnings,[]);self.assertEqual(analysis["counts"]["semantic_similarity_only"],1);self.assertEqual(analysis["genuine_warnings"],0)
    def test_carousel_shared_caption_is_not_independent_duplicate(self):
        self.assertEqual(_independent_caption_warnings([package("a","instagram",kind="carousel"),package("b","instagram",kind="carousel")]),[])
    def test_superseded_is_historical_not_active(self):
        summary=_queue_summary([{"status":"queued"},{"status":"superseded"}])
        self.assertEqual(summary["active_total"],1);self.assertEqual(summary["superseded"],1)
    def test_blocked_preflight_is_never_adapter_eligible(self):
        item={"status":"blocked","idempotency_key":"key"};eligible,reason=_adapter_eligibility(item,{"status":"blocked"},{})
        self.assertFalse(eligible);self.assertEqual(reason,"preflight_blocked")
    def test_carousel_is_one_job_and_platform_variants_are_two(self):
        self.assertEqual(_queue_summary([{"status":"queued","package_type":"carousel"}])["platform_publication_jobs"],1)
        self.assertEqual(_queue_summary([{"status":"queued","platform":"instagram"},{"status":"queued","platform":"facebook"}])["platform_publication_jobs"],2)
    def test_platform_allocation_and_zero_target_diagnostic(self):
        shared=[{"planned_destinations":["instagram","facebook"],"platform_rationale":"asset fit"}]
        value=_platform_allocation(shared,CampaignPlatformStrategy.BOTH_PLATFORM_OPTIMIZED);self.assertEqual(value["shared_concepts"],1);self.assertFalse(value["warnings"])
        biased=[{"planned_destinations":["instagram"],"platform_rationale":"asset fit"} for _ in range(2)]
        self.assertEqual(_platform_allocation(biased,CampaignPlatformStrategy.BOTH_PLATFORM_OPTIMIZED)["warnings"][0]["warning_type"],"platform_allocation_warning")
        for item in biased:item["platform_rationale"]="Explicit asymmetric campaign rule"
        self.assertFalse(_platform_allocation(biased,CampaignPlatformStrategy.BOTH_PLATFORM_OPTIMIZED)["warnings"])
    def test_unicode_console_text_has_no_mojibake(self):
        value="Project — مشروع عقاري — پڕۆژەی خانووبەرە"
        self.assertFalse(has_mojibake(value));self.assertTrue(has_mojibake("Project Ã¢â‚¬â€ broken"))
    def test_missing_and_old_queue_versions_trigger_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);foundation=PublishingFoundation("P",root);foundation.queue_path.parent.mkdir(parents=True)
            context={"packages":{"packages":[]}}
            with patch.object(foundation,"_inputs",return_value=context):
                foundation.queue_path.write_text(json.dumps({"project_id":"P","items":[]}));self.assertEqual(foundation.queue_reconciliation_reason(),"outdated queue schema")
                foundation.queue_path.write_text(json.dumps({"project_id":"P","queue_schema_version":QUEUE_VERSION,"queue_reconciliation_version":"old","items":[]}));self.assertEqual(foundation.queue_reconciliation_reason(),"reconciliation policy changed")
                foundation.queue_path.write_text(json.dumps({"project_id":"P","queue_schema_version":QUEUE_VERSION,"queue_reconciliation_version":QUEUE_RECONCILIATION_VERSION,"items":[]}));self.assertIsNone(foundation.queue_reconciliation_reason())
    def test_semantic_json_cache_ignores_timestamps_but_not_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"input.json";path.write_text(json.dumps({"created_at":"one","value":1}));first=_semantic_file_hash(path)
            path.write_text(json.dumps({"created_at":"two","value":1}));self.assertEqual(first,_semantic_file_hash(path))
            path.write_text(json.dumps({"created_at":"two","value":2}));self.assertNotEqual(first,_semantic_file_hash(path))
    def test_brand_signature_changes_for_logo_brand_source_and_context(self):
        with tempfile.TemporaryDirectory() as directory:
            context=Path(directory)/"context.json";context.write_text(json.dumps({"created_at":"one","fact":"x"}))
            config={"approval":{"approved_config_hash":"brand-a"}};items=[{"production_item_id":"p","output_hash":"source-a","target_platform":"instagram","language":"en"}]
            first=_cache_signature(config,items,{"sha256":"logo-a"},[context])
            context.write_text(json.dumps({"created_at":"two","fact":"x"}));self.assertEqual(first,_cache_signature(config,items,{"sha256":"logo-a"},[context]))
            self.assertNotEqual(first,_cache_signature(config,items,{"sha256":"logo-b"},[context]))
            self.assertNotEqual(first,_cache_signature({"approval":{"approved_config_hash":"brand-b"}},items,{"sha256":"logo-a"},[context]))
            self.assertNotEqual(first,_cache_signature(config,[{**items[0],"output_hash":"source-b"}],{"sha256":"logo-a"},[context]))

if __name__=="__main__":unittest.main()
