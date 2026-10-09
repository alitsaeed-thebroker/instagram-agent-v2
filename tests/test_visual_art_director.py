from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import json
import tempfile
import unittest

from PIL import Image

from src.creative.visual_direction import VisualArtDirector, _merge_intelligence, contract_id, contract_integrity_hash, validate_visual_direction_contract, visual_direction_cache_key
from src.creative.visual_art_director import VisualArtDirectorWorkflow
from src.creative.visual_history import VisualDirectionHistory
from src.branding.composer import BrandComposer
from src.execution.stages import STAGE_ORDER
import tests.test_brand_composer as brand_fixture


class VisualArtDirectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.image = self.root/"source.png"; Image.new("RGB", (1200, 900), "white").save(self.image)
        self.logo = self.root/"logo.png"; Image.new("RGBA", (300, 100), "black").save(self.logo)

    def tearDown(self): self.tmp.cleanup()

    def package(self, asset_type="exterior"):
        return {"project_id":"p1", "content_brief": {
            "content_id":"c1", "project_id":"p1", "content_objective":"awareness", "campaign_role":"hero",
            "post_type":"static", "carousel_position":1, "marketing_angle":"architecture", "primary_message":"Avenue Square",
            "secondary_message":"Premium offices", "allowed_claims":[], "required_identification":["project"],
            "optional_identification":[], "prohibited_claims":["guaranteed ROI"], "cta_requirement":"none", "language":"en",
            "platform":"Instagram", "target_dimensions":{"width":1080,"height":1350}},
            "source_asset":{"asset_id":"a1", "original_filename":"source.png", "source_document":"brochure.pdf", "source_page":2,
             "asset_type":asset_type, "width":1200, "height":900, "orientation":"landscape", "quality_score":95,
             "content_group":"project", "source_provenance":"verified", "path":str(self.image)},
            "visual_intelligence":{"primary_focal_region":"center_right", "protected_regions":[[500,0,1200,900]],
                                   "text_safe_regions":[[0,0,400,900]], "bright_regions":["left"]},
            "project_identity":{"project_name":"Avenue Square", "canonical_project_name":"Avenue Square", "project_type":"office",
             "location":"Erbil", "developer_name":None, "developer_identity_status":"unverified", "project_logo_if_verified":None,
             "project_identity_source":"knowledge"},
            "brand_identity":{"brand_name":"Domus", "approved_logo_assets":[{"path":str(self.logo),"variant":"dark"}],
             "approved_logo_variants":["dark","white"], "brand_fonts":["Arial"], "brand_colors":["#000000"],
             "minimum_logo_size":80, "maximum_logo_size":180, "logo_clear_space":20, "logo_aspect_ratio":3,
             "prohibited_logo_modifications":["stretch"], "brand_tone":"premium", "brand_visual_character":"restrained"}}

    def test_source_geometry_drives_safe_placement(self):
        result = VisualArtDirector().direct(self.package())
        self.assertEqual(result.status, "APPROVED"); self.assertFalse(validate_visual_direction_contract(result.contract))
        self.assertLess(result.contract["brand_logo"]["x"], 500)

    def test_masterplan_uses_fit_and_information_rail(self):
        result = VisualArtDirector().direct(self.package("masterplan"))
        self.assertEqual(result.contract["source_image"]["crop_mode"], "fit")
        self.assertEqual(result.contract["composition"]["strategy"], "side_information_rail")

    def test_square_logo_and_plan_copy_fit_beside_each_other_without_reducing_geometry(self):
        Image.new("RGBA",(300,300),"black").save(self.logo)
        package=self.package("floor_plan")
        package["brand_identity"].update(logo_aspect_ratio=1,minimum_logo_size=120,logo_clear_space=12)
        result=VisualArtDirector().direct(package)
        self.assertEqual(result.status,"APPROVED")
        contract=result.contract
        self.assertEqual(contract["source_image"]["placement"],[0,0,1080,1053])
        self.assertEqual(contract["source_image"]["crop_mode"],"fit")
        for name in ("project_identity","location","headline","supporting_copy"):
            box=contract[name]
            self.assertLessEqual(box["x"]+box["width"],contract["brand_logo"]["x"]-contract["brand_logo"]["clear_space"])
        self.assertEqual(validate_visual_direction_contract(contract),[])

    def test_missing_identity_fails_closed(self):
        package=self.package();package["project_identity"]["canonical_project_name"]=""
        result=VisualArtDirector().direct(package);self.assertEqual(result.status,"REQUIRES_REDIRECTION");self.assertIsNone(result.contract)

    def test_campaign_repetition_introduces_controlled_variation(self):
        history=[{"composition":{"strategy":"negative_space_overlay"}}]*2
        result=VisualArtDirector().direct(self.package(),recent_contracts=history)
        self.assertEqual(result.contract["composition"]["strategy"],"editorial_corner")

    def test_revision_changes_named_decision(self):
        contract=VisualArtDirector().direct(self.package()).contract; before=contract["project_identity"].copy()
        result=VisualArtDirector().revise(contract,{"status":"FAIL","issues":[{"type":"logo_contrast"}]})
        self.assertEqual(result.contract["project_identity"],before);self.assertNotEqual(result.contract["brand_logo"]["variant"],contract["brand_logo"]["variant"])

    def test_opposite_negative_space_changes_composition_geometry(self):
        left=self.root/"left.png";right=self.root/"right.png"
        noisy=Image.effect_noise((600,900),100).convert("RGB")
        for path,box in ((left,(600,0)),(right,(0,0))):
            image=Image.new("RGB",(1200,900),"white");image.paste(noisy,box);image.save(path)
        results=[]
        for path in (left,right):
            package=self.package();package["source_asset"]["path"]=str(path);package["visual_intelligence"]={}
            results.append(VisualArtDirector().direct(package).contract)
        self.assertNotEqual(results[0]["brand_logo"]["x"],results[1]["brand_logo"]["x"])

    def test_no_overlay_area_creates_dedicated_zone(self):
        package=self.package();package["visual_intelligence"].update(text_safe_regions=[],negative_space_regions=[],protected_regions=[[0,0,1200,900]])
        result=VisualArtDirector().direct(package)
        self.assertEqual(result.status,"APPROVED");self.assertEqual(result.contract["composition"]["strategy"],"bottom_information_zone")
        self.assertEqual(result.contract["source_image"]["placement"][3],result.contract["graphics"]["overlay_geometry"][1])

    def test_interior_protected_region_is_not_covered(self):
        package=self.package("interior");package["visual_intelligence"].update(protected_regions=[[400,0,1200,900]],text_safe_regions=[[0,0,350,900]])
        contract=VisualArtDirector().direct(package).contract
        self.assertFalse(validate_visual_direction_contract(contract,brand_identity=package["brand_identity"]))

    def test_logo_variant_is_approved_and_identity_types_are_distinct(self):
        package=self.package();contract=VisualArtDirector().direct(package).contract
        self.assertIn(contract["brand_logo"]["variant"],package["brand_identity"]["approved_logo_variants"])
        self.assertEqual({contract["project_identity"]["identity_type"],contract["developer_identity"]["identity_type"],contract["brand_logo"]["identity_type"]},{"project","developer","broker_marketing_brand"})

    def test_logo_distortion_and_out_of_bounds_geometry_fail(self):
        package=self.package();contract=VisualArtDirector().direct(package).contract
        distorted=deepcopy(contract);distorted["brand_logo"]["height"]*=2
        outside=deepcopy(contract);outside["headline"]["x"]=-1
        self.assertTrue(any("distort" in x for x in validate_visual_direction_contract(distorted,brand_identity=package["brand_identity"])))
        self.assertTrue(any("outside" in x for x in validate_visual_direction_contract(outside,brand_identity=package["brand_identity"])))

    def test_missing_source_fails_closed(self):
        package=self.package();package["source_asset"]["path"]=str(self.root/"missing.png")
        result=VisualArtDirector().direct(package);self.assertEqual(result.status,"REQUIRES_REDIRECTION");self.assertIn("source image is missing",result.blockers)

    def test_floor_plan_uses_dedicated_information_zone(self):
        package=self.package("floor_plan");package["visual_intelligence"].update(protected_regions=[[0,0,1200,900]],text_safe_regions=[])
        contract=VisualArtDirector().direct(package).contract
        self.assertEqual(contract["source_image"]["crop_mode"],"fit");self.assertLessEqual(contract["source_image"]["placement"][3],contract["graphics"]["overlay_geometry"][1])

    def test_individual_unit_plan_requires_cleared_plan_intelligence(self):
        package=self.package("unit_layout")
        missing=VisualArtDirector().direct(package)
        self.assertEqual(missing.status,"REQUIRES_REDIRECTION")
        self.assertTrue(any("plan-intelligence" in blocker for blocker in missing.blockers))
        package["plan_intelligence"]={"asset_type":"unit_layout","marketing_eligible":False}
        review=VisualArtDirector().direct(package)
        self.assertEqual(review.status,"REQUIRES_REDIRECTION")
        self.assertTrue(any("REVIEW_REQUIRED" in blocker for blocker in review.blockers))

    def test_cache_key_invalidates_source_logo_brief_and_history(self):
        package=self.package();base=visual_direction_cache_key(package)
        changed=deepcopy(package);changed["content_brief"]["primary_message"]="Changed";self.assertNotEqual(base,visual_direction_cache_key(changed))
        Image.new("RGB",(1200,900),"black").save(self.image);self.assertNotEqual(base,visual_direction_cache_key(package))
        source_changed=visual_direction_cache_key(package);Image.new("RGBA",(300,100),"white").save(self.logo);self.assertNotEqual(source_changed,visual_direction_cache_key(package))
        self.assertNotEqual(visual_direction_cache_key(package),visual_direction_cache_key(package,[{"composition":{"strategy":"minimal_identity"}}]))

    def test_canonical_unit_plan_reaches_director_and_rejects_substitution(self):
        from tests.unit_plan_fixtures import source_plan
        from src.plan_integrity import make_plan_record
        from src.creative.visual_art_director import _index
        record=make_plan_record(source_plan(project="p1"))
        self.assertEqual(_index({"assets":[record]}, "asset_id")[record["asset_id"]], record)
        package=self.package("unit_layout")
        package["plan_intelligence"]=record
        with Image.open(record["source_path"]) as image:
            width,height=image.size
        package["source_asset"].update(asset_id=record["asset_id"],path=record["source_path"],width=width,height=height)
        package["visual_intelligence"].update(protected_regions=[[0,0,width,height]],text_safe_regions=[])
        result=VisualArtDirector().direct(package)
        self.assertEqual(result.status,"APPROVED",result.blockers)
        self.assertEqual(validate_visual_direction_contract(result.contract),[])
        package["source_asset"]["path"]=str(self.image)
        self.assertEqual(VisualArtDirector().direct(package).status,"REQUIRES_REDIRECTION")

    def test_cross_project_source_is_rejected(self):
        package=self.package();package["source_asset"]["project_id"]="p2"
        self.assertEqual(VisualArtDirector().direct(package).status,"REQUIRES_REDIRECTION")

    def test_signed_contract_rejects_autonomous_layout_override(self):
        contract=VisualArtDirector().direct(self.package()).contract;contract["contract_hash"]=contract_integrity_hash(contract)
        contract["brand_logo"]["x"]+=10
        self.assertIn("Visual Direction Contract integrity hash mismatch",validate_visual_direction_contract(contract))

    def test_canonical_pipeline_order_is_direction_render_output_qa(self):
        self.assertLess(STAGE_ORDER.index("visual-art-director"),STAGE_ORDER.index("brand-composer"))
        self.assertLess(STAGE_ORDER.index("brand-composer"),STAGE_ORDER.index("image-output-qa"))

    def test_pre_direction_analysis_is_non_destructive(self):
        before=self.image.read_bytes();intelligence=_merge_intelligence(Image.open(self.image).convert("RGB"),{})
        self.assertEqual(before,self.image.read_bytes());self.assertIn("deterministic_metrics",intelligence)
        self.assertFalse(any(self.root.glob("*production*")))

    def test_composer_without_contract_fails_and_has_no_layout_planner(self):
        with self.assertRaisesRegex(ValueError,"requires a signed Visual Direction Contract"):BrandComposer("p1",self.root).compose()
        self.assertFalse(hasattr(BrandComposer,"_plan"))

    def test_durable_history_is_project_isolated_and_drives_safe_variation(self):
        contracts=[]
        for index in range(2):
            contract=VisualArtDirector().direct(self.package()).contract;contract["content_id"]=f"c{index}";contract["contract_id"]=contract_id(contract);contract["contract_hash"]=contract_integrity_hash(contract);contracts.append(contract)
        history=VisualDirectionHistory("p1",self.root);history.record_released(contracts,{x["contract_id"] for x in contracts},release_id="release-001")
        context=history.recent_context();self.assertEqual(len(context),2);self.assertFalse(VisualDirectionHistory("p2",self.root).recent_context())
        varied=VisualArtDirector().direct(self.package(),recent_contracts=context).contract
        self.assertEqual(varied["composition"]["strategy"],"editorial_corner")
        constrained=self.package();constrained["visual_intelligence"].update(text_safe_regions=[],negative_space_regions=[],protected_regions=[[0,0,1200,900]])
        safe=VisualArtDirector().direct(constrained,recent_contracts=context).contract
        self.assertEqual(safe["composition"]["strategy"],"bottom_information_zone")


class VisualArtDirectorPipelineFixtureTests(unittest.TestCase):
    def test_two_source_project_fixture_contracts_and_renders_without_publishing(self):
        fixture=brand_fixture.BrandComposerTests();fixture.setUp()
        try:
            root,project=fixture.root,fixture.project
            prompts_path=root/f"output/image-prompts/{project}-image-prompts.json";prompts=json.loads(prompts_path.read_text())
            first=Path(prompts["prompts"][0]["source_asset_paths"][0]);second=first.with_name("image-2.png")
            image=Image.new("RGB",(1080,1350),(30,30,30));image.paste((220,220,220),(540,0,1080,1350));image.save(second)
            item=deepcopy(prompts["prompts"][0]);item.update(prompt_id="prompt-2",content_idea_id="idea-2",source_asset_ids=["asset-2"],source_asset_paths=[str(second)]);prompts["prompts"].append(item);prompts_path.write_text(json.dumps(prompts))
            content=root/f"output/content/{project}-content-plan.json";content.write_text(json.dumps({"project_id":project,"content_ideas":[{"content_idea_id":"idea-1","title":"Verified Residences"},{"content_idea_id":"idea-2","title":"Project Detail"}]}))
            inventory=root/f"output/visual-inventory/{project}-visual-inventory.json";inventory.write_text(json.dumps({"project_id":project,"assets":[
                {"asset_id":"asset-1","project_id":project,"asset_type":"exterior","text_safe_regions":[[0,0,400,1350]],"protected_regions":[[500,0,1080,1350]],"quality_score":95},
                {"asset_id":"asset-2","project_id":project,"asset_type":"exterior","text_safe_regions":[[680,0,1080,1350]],"protected_regions":[[0,0,580,1350]],"quality_score":95}] }))
            directions=json.loads(VisualArtDirectorWorkflow(project,root).run().read_text());self.assertEqual(directions["summary"],{"approved":2,"requires_redirection":0})
            self.assertNotEqual(directions["contracts"][0]["brand_logo"]["x"],directions["contracts"][1]["brand_logo"]["x"])
            plans=json.loads(BrandComposer(project,root).compose().read_text());self.assertEqual(plans["creative_authority"],"visual-art-director");self.assertEqual(plans["summary"]["branded_images"],2)
            output_qa=json.loads(BrandComposer(project,root).output_qa().read_text());self.assertEqual(output_qa["summary"],{"passed":2,"failed":0});self.assertTrue(all(x["checked_after_contract"] for x in output_qa["items"]))
            contracts=directions["contracts"];VisualDirectionHistory(project,root).record_released(contracts,{x["contract_id"] for x in contracts},release_id="fixture-release")
            second_run=json.loads(VisualArtDirectorWorkflow(project,root).run().read_text());self.assertEqual(second_run["summary"]["approved"],2);self.assertEqual(len(VisualDirectionHistory(project,root).recent_context()),2)
            self.assertFalse((root/"output/publishing").exists())
        finally:fixture.tearDown()


if __name__ == "__main__": unittest.main()
