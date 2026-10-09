from __future__ import annotations

import json
from pathlib import Path
import unittest

from PIL import Image

from src.branding.composer import BrandComposer
from src.creative.visual_art_director import VisualArtDirectorWorkflow
from src.creative.visual_direction import contract_integrity_hash
import tests.test_brand_composer as brand_fixture


class ContractAwareBrandedQATests(unittest.TestCase):
    def setUp(self):
        self.fixture=brand_fixture.BrandComposerTests();self.fixture.setUp();self.root=self.fixture.root;self.project=self.fixture.project
    def tearDown(self):self.fixture.tearDown()

    def _compose_qa(self):
        composer=BrandComposer(self.project,self.root);plans=json.loads(composer.compose(force=True).read_text())["plans"];report=json.loads(composer.qa(force=True).read_text());return composer,plans,report

    def test_pure_overlay_and_authorized_geometry_pass(self):
        _,plans,report=self._compose_qa();item=report["items"][0]
        self.assertIn(item["status"],{"production_ready","exceptional"});self.assertTrue(item["checks"]["contract_authorized_render_exact"])
        # A different canvas requires deterministic contract-authorized scaling/cropping.
        prompts=self.root/f"output/image-prompts/{self.project}-image-prompts.json";value=json.loads(prompts.read_text());value["prompts"][0].update(target_width=900,target_height=900);prompts.write_text(json.dumps(value));VisualArtDirectorWorkflow(self.project,self.root).run()
        _,plans,report=self._compose_qa();self.assertEqual((plans[0]["width"],plans[0]["height"]),(900,900));self.assertNotEqual(report["items"][0]["status"],"failed")

    def test_tamper_wrong_dimensions_and_source_substitution_fail(self):
        composer,plans,_=self._compose_qa();output=Path(plans[0]["branded_image_path"])
        with Image.open(output) as image:changed=image.convert("RGBA");old=changed.getpixel((700,700));changed.putpixel((700,700),tuple(255-x for x in old[:3])+(255,));changed.save(output)
        result=json.loads(composer.qa(force=True).read_text())["items"][0];self.assertIn("rendered pixels differ from signed Visual Direction Contract",result["errors"]);self.assertIn("branded image hash mismatch",result["errors"])
        Image.new("RGBA",(100,100),(0,0,0,255)).save(output);result=json.loads(composer.qa(force=True).read_text())["items"][0];self.assertIn("output dimensions are incorrect",result["errors"])
        source=Path(plans[0]["source_image_path"]);Image.new("RGB",(1080,1350),(9,9,9)).save(source);result=json.loads(composer.qa(force=True).read_text())["items"][0];self.assertIn("source image hash mismatch",result["errors"])

    def test_pr1_pr2_have_independent_identity_hash_dimensions_and_files(self):
        prompts=self.root/f"output/image-prompts/{self.project}-image-prompts.json";value=json.loads(prompts.read_text());second={**value["prompts"][0],"prompt_id":"prompt-1-PR2","target_width":1080,"target_height":1080};value["prompts"].append(second);prompts.write_text(json.dumps(value));VisualArtDirectorWorkflow(self.project,self.root).run()
        _,plans,report=self._compose_qa();self.assertEqual(len(plans),2)
        for field in ("composition_id","production_item_id","branded_item_id","branded_image_path","branded_image_hash"):self.assertEqual(len({x[field] for x in plans}),2,field)
        self.assertTrue(all(x["status"] in {"production_ready","exceptional"} for x in report["items"]))

    def test_unauthorized_contract_crop_and_plan_damage_fail_closed(self):
        composer,plans,_=self._compose_qa();directions=self.root/f"output/visual-directions/{self.project}-visual-direction-contracts.json";value=json.loads(directions.read_text());contract=value["contracts"][0];contract["source_image"]["asset_type"]="unit_layout";contract["plan_integrity"]={"preservation":{"complete_plan_required":True}};contract["source_image"]["crop_mode"]="controlled_crop";contract["contract_hash"]=contract_integrity_hash(contract);directions.write_text(json.dumps(value))
        result=json.loads(composer.qa(force=True).read_text())["items"][0];self.assertEqual(result["status"],"failed");self.assertTrue(any("plan" in error for error in result["errors"]))


if __name__=="__main__":unittest.main()
