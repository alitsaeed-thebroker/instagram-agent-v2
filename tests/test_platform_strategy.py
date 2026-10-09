from __future__ import annotations
import unittest
from src.platforms import CampaignPlatformStrategy, DestinationOverride, Platform, PlatformIntent, apply_destination_override, build_variants, capability_for

class PlatformStrategyTests(unittest.TestCase):
    def test_all_strategies_validate(self):
        cases={"instagram_only":("instagram",),"facebook_only":("facebook",),"both_mirrored":("instagram","facebook"),"both_platform_optimized":("instagram","facebook")}
        for raw,destinations in cases.items():
            intent=PlatformIntent("idea","master",CampaignPlatformStrategy.parse(raw),tuple(Platform.parse(x) for x in destinations),"grounded rationale","platform_specific" if raw=="both_platform_optimized" else "shared")
            self.assertEqual(intent.strategy.value,raw)
    def test_unknown_values_fail_safely(self):
        with self.assertRaisesRegex(ValueError,"Unknown CampaignPlatformStrategy"):CampaignPlatformStrategy.parse("tiktok")
    def test_override_preserves_planned_input(self):
        planned=(Platform.INSTAGRAM,Platform.FACEBOOK)
        self.assertEqual(apply_destination_override(planned,"instagram"),(Platform.INSTAGRAM,));self.assertEqual(apply_destination_override(planned,"use_planned"),planned);self.assertEqual(apply_destination_override((Platform.INSTAGRAM,),DestinationOverride.BOTH),tuple(Platform))
    def test_variants_preserve_master_facts_and_provenance(self):
        intent=PlatformIntent("idea","master",CampaignPlatformStrategy.BOTH_PLATFORM_OPTIMIZED,tuple(Platform),"format suitability","platform_specific",("fact-1",))
        variants=build_variants({"content_id":"master","content_version":"2","verified_facts":["fact"],"source_references":["doc:1"],"caption":"copy"},intent)
        self.assertEqual(len(variants),2);self.assertEqual({x.factual_claims for x in variants},{("fact",)});self.assertEqual({x.source_references for x in variants},{("doc:1",)})
    def test_capabilities_are_central_and_limits_are_not_guessed(self):
        self.assertTrue(capability_for("instagram").carousel);self.assertTrue(capability_for("facebook").feed_image);self.assertIsNone(capability_for("facebook").media_count["maximum"])

if __name__=="__main__":unittest.main()
