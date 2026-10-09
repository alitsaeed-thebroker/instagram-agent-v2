from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from PIL import Image

from src.content.schema import ContentPlan
from src.creative.visual_direction import VisualArtDirector, validate_visual_direction_contract
from src.image_processing.planner import _export_variants
from src.image_prompts.generator import _authorization
from src.publication import normalize_publication_type, public_copy, validate_public_copy
from src.publishing.eligibility import publication_surface
from src.publishing.meta import MetaInstagramAdapter


class InstagramStoryContractTests(unittest.TestCase):
    def test_normalization_is_canonical_and_story_is_not_reel(self):
        for value in ("story","Instagram Story","instagram_story"):
            self.assertEqual(normalize_publication_type(value),"story")
        self.assertEqual(normalize_publication_type("Instagram Reel"),"reel")
        with self.assertRaises(ValueError): normalize_publication_type("vertical")

    def test_feasible_story_does_not_imply_selected_story(self):
        data={"content_ideas":[{"content_idea_id":"c","title":"Exterior","concept_summary":"Visible architecture","content_objective":"Show architecture","target_persona":"Buyers","funnel_stage":"awareness","selected_source_asset_ids":["a"],"source_support_status":"fully_supported","feasible_platforms":["Instagram"],"feasible_formats":["story","single_feed_post"],"orientation":"portrait"}]}
        idea=ContentPlan.from_dict(data).pillars[0].content_ideas[0]
        self.assertIsNone(idea.selected_format);self.assertIsNone(idea.planned_publication)

    def test_story_selection_authorizes_story_only(self):
        idea={"feasible_formats":["story","single_feed_post"],"planned_destinations":["instagram"],"selected_format":"story","planned_publication":{"publication_type":"story"}}
        story={"platform":"Instagram Story","width":1080,"height":1920,"output_format":"JPEG"}
        feed={"platform":"Instagram Feed","width":1080,"height":1350,"output_format":"JPEG"}
        self.assertEqual(_authorization(story,idea,{})[1],"authorized")
        self.assertEqual(_authorization(feed,idea,{})[1],"variant_not_selected_for_production")

    def test_story_and_reel_exports_remain_distinct(self):
        variants=_export_variants(["Instagram Story","Instagram Reel"],["9:16"])
        self.assertEqual({x.platform for x in variants},{"Instagram Story","Instagram Reel"})
        self.assertTrue(all((x.width,x.height,x.aspect_ratio)==(1080,1920,"9:16") for x in variants))

    def test_public_copy_allowlist_and_metadata_leak_detector(self):
        value=public_copy({"public_copy":{"project_name":"Beverly Hills","headline":"Explore the Interior","subheadline":None,"cta":None,"website":"domuserbil.com"},"concept_summary":"Present 1 approved interior asset(s) as a single_feed_post"})
        self.assertNotIn("concept_summary",value);self.assertFalse(validate_public_copy(value))
        self.assertTrue(validate_public_copy({**value,"headline":"Present 1 approved interior asset(s) as a single_feed_post"}))

    def test_story_vdc_requires_target_dimensions_and_safe_zones(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/"source.jpg";logo=root/"logo.png"
            image=Image.new("RGB",(1400,2100),(230,230,230));image.paste(Image.effect_noise((460,2100),100).convert("RGB"),(0,0));image.save(source);Image.new("RGBA",(300,100),(120,24,16,255)).save(logo)
            package={"project_id":"P","content_brief":{"content_id":"c","project_id":"P","content_objective":"awareness","campaign_role":"standalone","post_type":"static","carousel_position":1,"marketing_angle":"architecture","primary_message":"Beverly Hills","secondary_message":"","allowed_claims":[],"required_identification":["project"],"optional_identification":[],"prohibited_claims":["guaranteed ROI"],"cta_requirement":"none","language":"en","platform":"Instagram Story","publication_type":"story","public_copy":{"project_name":"Beverly Hills","headline":"Beverly Hills","subheadline":None,"cta":None,"website":None},"target_dimensions":{"width":1080,"height":1920}},"source_asset":{"asset_id":"a","original_filename":"source.jpg","source_document":"catalogue.pdf","source_page":1,"asset_type":"exterior","width":1400,"height":2100,"orientation":"portrait","quality_score":95,"content_group":"project","source_provenance":"verified","path":str(source)},"visual_intelligence":{},"project_identity":{"project_name":"Beverly Hills","canonical_project_name":"Beverly Hills","project_type":"residential","location":"Erbil","developer_name":None,"developer_identity_status":"unverified","project_logo_if_verified":None,"project_identity_source":"knowledge"},"brand_identity":{"brand_name":"Domus Erbil","approved_logo_assets":[{"path":str(logo),"variant":"original"}],"approved_logo_variants":["original"],"brand_fonts":["Arial"],"brand_colors":["#781810"],"minimum_logo_size":120,"maximum_logo_size":180,"logo_clear_space":12,"logo_aspect_ratio":3,"prohibited_logo_modifications":["stretch"],"brand_tone":"premium","brand_visual_character":"restrained"}}
            contract=VisualArtDirector().direct(package).contract
            self.assertIsNotNone(contract,VisualArtDirector().direct(package).blockers);self.assertFalse(validate_visual_direction_contract(contract))
            wrong=deepcopy(contract);wrong["canvas"].update(width=1080,height=1350,aspect_ratio="1080:1350")
            self.assertTrue(any("Story canvas" in x for x in validate_visual_direction_contract(wrong)))

    def test_story_surface_and_meta_container_semantics(self):
        self.assertEqual(publication_surface("story","instagram"),"story")
        self.assertEqual(publication_surface("single_post","instagram"),"feed")


if __name__=="__main__":unittest.main()
