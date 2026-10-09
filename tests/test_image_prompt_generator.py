"""Focused semantic quality checks for source-grounded prompts."""
import unittest

from src.image_prompts.generator import _asset_error, _authorized, _build, _compatible, _factual_objective, _prompt


class ImagePromptSemanticTests(unittest.TestCase):
    def test_exterior_is_not_interior_and_valid_interior_matches(self):
        self.assertFalse(_compatible("interior", {"asset_type":"exterior"}))
        self.assertTrue(_compatible("interior", {"asset_type":"interior"}))

    def test_canonical_content_categories_accept_only_safe_visual_types(self):
        accepted=(("masterplan","masterplan"),("masterplan","site_plan"),("exterior","exterior"),("exterior","aerial_view"),("interior","interior"),("amenity","amenity"),("amenity","garden_landscape"),("layout","floorplan"))
        for expected,actual in accepted:self.assertTrue(_compatible(expected,{"asset_type":actual}),(expected,actual))
        self.assertFalse(_compatible("exterior",{"asset_type":"interior"}))
        self.assertFalse(_compatible("interior",{"asset_type":"floorplan"}))

    def test_platform_requires_upstream_format_and_platform(self):
        variant={"platform":"Instagram Feed","width":1080,"height":1350,"output_format":"JPEG"}
        self.assertFalse(_authorized(variant,{"feasible_formats":["Website Banner"],"feasible_platforms":["website"]},{}))
        self.assertTrue(_authorized(variant,{"feasible_formats":["Instagram Single Image"],"feasible_platforms":["Instagram"]},{}))
        self.assertTrue(_authorized(variant,{"feasible_formats":["single_feed_post"],"feasible_platforms":["social media"]},{}))
        self.assertTrue(_authorized(variant,{"feasible_formats":["single_feed_post"],"feasible_platforms":["print"],"planned_destinations":["instagram"]},{}))
        self.assertFalse(_authorized({**variant,"platform":"YouTube Thumbnail"},{"feasible_formats":["single_feed_post"],"planned_destinations":["instagram"]},{}))

    def test_asset_resolution_fails_closed_for_wrong_project_unknown_manifest_and_rejection(self):
        asset={"asset_id":"a","project_id":"P","asset_type":"exterior","marketing_suitability":"feed_ready","analysis_status":"analyzed","source_path":"unused","source_hash":"h"}
        self.assertIn("another project",_asset_error("Q","a",asset,None,{"a"},{"a":{}}))
        self.assertIn("source manifest",_asset_error("P","a",asset,None,{"a"},{}))
        rejected={**asset,"marketing_suitability":"rejected"}
        self.assertIn("unsuitable",_asset_error("P","a",rejected,None,{"a"},{"a":{"sha256":"h"}}))

    def test_factual_objective_detection(self):
        self.assertTrue(_factual_objective("Explain the verified project amenities"))
        self.assertFalse(_factual_objective("Present the authentic exterior image"))

    def test_asset_specific_preservation_and_deterministic_route(self):
        asset={"asset_id":"a","asset_type":"lifestyle","source_path":"a.jpg","source_hash":"h"}
        op={"source_path":"a.jpg","source_hash":"h","technical_enhancements":[],"resize":{"mode":"contain_letterbox"}}
        plan={"processing_plan_id":"ip","content_idea_id":"c","source_asset_operations":[op]}
        variant={"platform":"Instagram Feed","width":1080,"height":1350,"output_format":"JPEG","aspect_ratio":"4:5"}
        result=_prompt("p","ip-PR1",plan,variant,[(asset,op)],{"content_objective":"Present the image"},"lifestyle",[],[],False)
        self.assertEqual(result["execution_route"],"deterministic_processor")
        self.assertFalse(result["ai_prompt_required"])
        self.assertIn("poses",result["preservation_rules"])
        self.assertNotIn("no a new viewpoint",result["negative_prompt"])
        self.assertLess(result["confidence"]["quality_score"],101)

    def test_floorplan_preservation_and_missing_facts_score(self):
        asset={"asset_id":"a","asset_type":"floorplan","source_path":"a.png","source_hash":"h"}
        op={"source_path":"a.png","source_hash":"h","technical_enhancements":[],"resize":{"mode":"contain_letterbox"}}
        result=_prompt("p","ip-PR1",{"processing_plan_id":"ip"},{"platform":"Instagram Carousel","width":1080,"height":1350},[(asset,op)],{"content_objective":"Explain verified floorplan facts"},"floorplan",[],[],False)
        self.assertIn("room labels",result["preservation_rules"])
        self.assertEqual(result["confidence"]["breakdown"]["factual_evidence"],0)
        self.assertLess(result["confidence"]["quality_score"],90)

    def test_ai_editing_route_for_nondeterministic_validated_operation(self):
        asset={"asset_id":"a","asset_type":"interior","source_path":"a.jpg","source_hash":"h"}
        op={"source_path":"a.jpg","source_hash":"h","technical_enhancements":[{"operation":"validated_local_retouch","enabled":True}],"resize":{"mode":"contain_letterbox"}}
        result=_prompt("p","ip-PR1",{"processing_plan_id":"ip"},{"platform":"Instagram Feed","width":1080,"height":1350},[(asset,op)],{"content_objective":"Present interior"},"interior",[],[],False)
        self.assertEqual(result["execution_route"],"ai_image_editor")
        self.assertTrue(result["ai_prompt_required"])

    def test_block_reason_distribution_accounts_for_every_blocked_variant(self):
        processing={"image_processing_plans":[{"content_idea_id":"c","source_asset_ids":["missing"],"source_asset_operations":[],"export_variants":[{},{}]}]}
        prompts,stats=_build("P",processing,{"assets":[]},{"all_source_asset_ids":[]},{},[])
        self.assertEqual(prompts,[])
        self.assertEqual(stats["blocked"],2)
        self.assertEqual(stats["blocked_reasons"],{"no_valid_authentic_source_asset":2})
        self.assertEqual(sum(stats["blocked_reasons"].values()),stats["blocked"])


if __name__ == "__main__": unittest.main()
