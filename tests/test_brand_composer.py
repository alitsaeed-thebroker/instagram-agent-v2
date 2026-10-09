"""Phase 20B locked branding, layout, preservation, cache, and QA tests."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from src.brand_kit.defaults import DEFAULT_BRAND_CONFIG
from src.brand_kit.identity import approved_config_hash, migrate_config, typography_system
from src.branding.composer import BrandComposer, _outside_equal, _safe_headline
from src.creative.visual_art_director import VisualArtDirectorWorkflow
from src.execution.lineage import attach_lineage, canonical_graph_fingerprint


def _sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_knowledge(namespace:str, display_name:str, location:str)->dict:
    evidence={
        "evidence_id":"ev_fixture_identity",
        "source_project":namespace,
        "source_file":"fixture.pdf",
        "source_document":"fixture.pdf",
        "source_id":"src_fixture_identity",
        "source_sha256":"hash_fixture_identity",
        "source_page":1,
        "page":1,
        "source_text":f"{display_name} is located in {location}.",
        "extraction_method":"test_authoritative_fixture",
        "support_status":"direct",
    }
    return {
        "project":{"name":display_name,"location":location},
        "project_identity":{"project_name":display_name,"developer_name":"","project_type":"","location":location},
        "canonical_intelligence":{
            "project_namespace":namespace,
            "schema_version":"2.0.0",
            "contract_role":"authoritative_department2_relational_intelligence",
            "entities":[{
                "entity_id":"project_fixture",
                "entity_type":"project",
                "project_namespace":namespace,
                "label":display_name,
                "parent_entity_id":None,
                "attributes":{},
            }],
            "facts":[
                {
                    "fact_id":"fact_fixture_name","entity_id":"project_fixture","fact_type":"project.project_name",
                    "value":display_name,"unit":None,"currency":None,"state":"VERIFIED","confidence":1.0,
                    "authority":90,"marketing_eligible":True,"provenance":[dict(evidence,fact_value=display_name)],
                    "relationship_context":{"project_namespace":namespace},"effective_date":None,"conflicts":[],
                },
                {
                    "fact_id":"fact_fixture_location","entity_id":"project_fixture","fact_type":"project.location",
                    "value":location,"unit":None,"currency":None,"state":"VERIFIED","confidence":1.0,
                    "authority":90,"marketing_eligible":True,"provenance":[dict(evidence,fact_value=location)],
                    "relationship_context":{"project_namespace":namespace},"effective_date":None,"conflicts":[],
                },
            ],
            "conflicts":[],"unknowns":[],"metadata":{},
        },
    }


class BrandComposerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.project = "Test Project"; self._fixture()
    def tearDown(self) -> None: self.temp.cleanup()
    def _write(self, relative: str, value: dict) -> Path:
        path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding="utf-8");return path

    def _fixture(self) -> None:
        logo=self.root/"input"/"brand"/"logos"/"official.png";logo.parent.mkdir(parents=True,exist_ok=True);Image.new("RGBA",(600,200),(120,24,16,255)).save(logo)
        config=copy.deepcopy(DEFAULT_BRAND_CONFIG);config["company"].update(official_name="Domus Erbil",display_name="Domus Erbil");config,_=migrate_config(config)
        config["visual_identity"]["logo_policy"].update(status="available",preferred_logo_id="official-1")
        config["visual_identity"]["colors"].update(status="logo_derived",primary={"value":"#781810","status":"logo_derived","source":"preferred_logo","confidence":.99})
        config["approval"].update(status="approved",locked=True,approved_by="tester",approved_at="2026-01-01T00:00:00Z",approved_logo_hash=_sha(logo),approved_config_hash=None)
        config["approval"]["approved_config_hash"]=approved_config_hash(config);self._write("input/brand/brand-config.json",config)
        self._write("output/brand-analysis/domus-erbil-logo-inventory.json",{"brand_id":"domus-erbil","preferred_logo_id":"official-1","logos":[{"logo_id":"official-1","path":str(logo),"sha256":_sha(logo),"suitability":"preferred","width":600,"height":200,"aspect_ratio":3.0}]})
        typography=typography_system();self._write("output/brand-analysis/domus-erbil-brand-identity.json",{"brand_id":"domus-erbil","preferred_logo":{"logo_id":"official-1","path":str(logo),"sha256":_sha(logo),"valid":True,"hash_verified":True},"palette":{"primary":{"hex":"#781810"},"neutrals":[{"hex":"#FFFFFF"},{"hex":"#000000"}]},"contrast_recommendations":[{"contrast_ratio":8}],"typography_system":typography,"language_typography_rules":typography["language_rules"],"provenance":{"test":True}})
        self._write("output/brand-analysis/domus-erbil-brand-readiness.json",{})
        source=self.root/"output"/"produced-images"/self.project/"image.png";source.parent.mkdir(parents=True,exist_ok=True);image=Image.new("RGB",(1080,1350),(210,210,210));image.paste((30,30,30),(540,0,1080,1350));image.save(source)
        item={"production_item_id":"item:1","project_id":self.project,"prompt_id":"prompt-1","campaign_id":"campaign-1","content_idea_id":"idea-1","source_asset_ids":["asset-1"],"output_path":str(source),"output_hash":_sha(source),"processing_status":"produced","target_platform":"Instagram Feed","prompt_type":"source_image_enhancement"}
        self._write(f"output/production-manifests/{self.project}-production-manifest.json",{"project_id":self.project,"items":[item]});self._write(f"output/qa/{self.project}-image-qa.json",{"project_id":self.project,"items":[{"production_item_id":"item:1","status":"passed"}]})
        knowledge_payload=_canonical_knowledge(self.project,"Verified Residences","Erbil")
        self._write(f"output/knowledge/{self.project}.json",knowledge_payload);self._write(f"output/campaigns/{self.project}-campaign-plan.json",{"campaigns":[]})
        content_payload=attach_lineage({"project_id":self.project,"content_ideas":[{"content_idea_id":"idea-1","title":"Verified Residences"}]},stage="department3-content-plan",canonical_fingerprint=canonical_graph_fingerprint(knowledge_payload))
        self._write(f"output/content/{self.project}-content-plan.json",content_payload);self._write(f"output/creative-directions/{self.project}-creative-directions.json",{"creative_directions":[]});self._write(f"output/visual-inventory/{self.project}-visual-inventory.json",{"project_id":self.project,"assets":[{"asset_id":"asset-1","project_id":self.project,"asset_type":"exterior","quality_score":95,"text_safe_regions":[[0,0,420,1350]],"protected_regions":[[540,0,1080,1350]]}]})
        self._write(f"output/image-prompts/{self.project}-image-prompts.json",{"project_id":self.project,"prompts":[{"prompt_id":"prompt-1","project_id":self.project,"campaign_id":"campaign-1","content_idea_id":"idea-1","source_asset_ids":["asset-1"],"source_asset_paths":[str(source)],"target_width":1080,"target_height":1350,"target_platform":"Instagram Feed","confidence":{"status":"production_ready"}}]})
        VisualArtDirectorWorkflow(self.project,self.root).run()

    def test_locked_brand_project_name_palette_website_and_missing_contacts(self) -> None:
        plan=json.loads(BrandComposer(self.project,self.root).compose().read_text())["plans"][0]
        self.assertEqual(plan["logo_path"],str(self.root/"input/brand/logos/official.png"));self.assertEqual(plan["verified_project_name"],"Verified Residences");self.assertEqual(plan["website"],"domuserbil.com")
        self.assertEqual(plan["palette"]["primary"],"#781810");self.assertIsNone(plan["palette"]["secondary"]);self.assertIsNone(plan["palette"]["accent"]);self.assertEqual(plan["typography"]["primary_font"],"Segoe UI")
        self.assertNotIn("phone",plan);self.assertNotIn("email",plan)

    def test_unlocked_modified_config_or_logo_blocks(self) -> None:
        config_path=self.root/"input"/"brand"/"brand-config.json";config=json.loads(config_path.read_text());config["approval"]["locked"]=False;config_path.write_text(json.dumps(config))
        with self.assertRaises(ValueError):BrandComposer(self.project,self.root).compose()
        self._fixture();logo=self.root/"input"/"brand"/"logos"/"official.png";Image.new("RGBA",(600,200),(2,3,4,255)).save(logo)
        with self.assertRaises(ValueError):BrandComposer(self.project,self.root).compose()

    def test_layout_preserves_logo_ratio_color_and_safe_margin(self) -> None:
        plan=json.loads(BrandComposer(self.project,self.root).compose().read_text())["plans"][0];x,y,w,h=plan["logo_position"]
        self.assertAlmostEqual(w/h,3.0,places=1);self.assertGreaterEqual(w,120);self.assertGreaterEqual(x,plan["safe_margin"]);self.assertGreaterEqual(y,plan["safe_margin"])
        with Image.open(plan["branded_image_path"]) as branded:self.assertIn((120,24,16,255),set(branded.convert("RGBA").getdata()))

    def test_floorplan_busy_layout_and_headline_policy(self) -> None:
        prompts=self.root/f"output/image-prompts/{self.project}-image-prompts.json";data=json.loads(prompts.read_text());source=Path(data["prompts"][0]["source_asset_paths"][0]);Image.effect_noise((1080,1350),100).convert("RGB").save(source);prompts.write_text(json.dumps(data));inventory=self.root/f"output/visual-inventory/{self.project}-visual-inventory.json";assets=json.loads(inventory.read_text());assets["assets"][0]["asset_type"]="floor_plan";inventory.write_text(json.dumps(assets));VisualArtDirectorWorkflow(self.project,self.root).run()
        plan=json.loads(BrandComposer(self.project,self.root).compose(force=True).read_text())["plans"][0]
        self.assertEqual(plan["layout_type"],"bottom_information_zone");self.assertEqual(plan["verified_project_name"],"Verified Residences");self.assertLessEqual(plan["rendered_headline_lines"],2)

    def test_pixel_preservation_qa_manifest_gallery_and_decisions(self) -> None:
        composer=BrandComposer(self.project,self.root);plan=json.loads(composer.compose().read_text())["plans"][0]
        with Image.open(plan["source_image_path"]) as before,Image.open(plan["branded_image_path"]) as after:self.assertTrue(_outside_equal(before.convert("RGBA"),after.convert("RGBA"),tuple(plan["overlay_regions"][0])))
        qa=json.loads(composer.qa().read_text());self.assertEqual(qa["items"][0]["status"],"exceptional");self.assertEqual(qa["items"][0]["score"],100)
        self.assertEqual(qa["assessment_scope"],"visual_brand_only")
        self.assertEqual(qa["factual_readiness"],"not_assessed")
        self.assertEqual(qa["publishing_readiness"],"not_assessed")
        self.assertTrue(composer.manifest_path.is_file());self.assertTrue(composer.gallery_path.is_file());self.assertTrue(composer.decisions_path.is_file())

    def test_cache_reuse_and_source_change_invalidation(self) -> None:
        composer=BrandComposer(self.project,self.root);composer.compose();mtime=composer.plan_path.stat().st_mtime_ns;composer.compose();self.assertEqual(mtime,composer.plan_path.stat().st_mtime_ns)
        prompts=self.root/f"output/image-prompts/{self.project}-image-prompts.json";data=json.loads(prompts.read_text());source=Path(data["prompts"][0]["source_asset_paths"][0]);Image.new("RGB",(1080,1350),(1,2,3)).save(source)
        with self.assertRaisesRegex(ValueError,"stale source"):composer.compose(force=True)
        VisualArtDirectorWorkflow(self.project,self.root).run();composer.compose(force=True);self.assertNotEqual(mtime,composer.plan_path.stat().st_mtime_ns)

    def test_semantic_rerun_preserves_business_ids_and_qa_manifest_links(self) -> None:
        composer=BrandComposer(self.project,self.root);first=json.loads(composer.compose(force=True).read_text())["plans"][0];composer.qa(force=True)
        payload=json.loads(composer.plan_path.read_text());payload["created_at"]="2099-01-01T00:00:00Z";composer.plan_path.write_text(json.dumps(payload));second=json.loads(composer.compose(force=True).read_text())["plans"][0];composer.qa()
        manifest=json.loads(composer.manifest_path.read_text())["items"][0];qa=json.loads(composer.qa_path.read_text())["items"][0]
        self.assertEqual(first["production_item_id"],second["production_item_id"]);self.assertEqual(first["branded_item_id"],second["branded_item_id"]);self.assertEqual({second["branded_item_id"]},{manifest["branded_item_id"],qa["branded_item_id"]})

    def test_safe_editorial_headlines_block_claims(self) -> None:
        self.assertNotIn("ROI",_safe_headline("exterior","Guaranteed ROI"));self.assertEqual(_safe_headline("masterplan","Guaranteed ROI"),"Explore the Masterplan")

    def test_arabic_and_kurdish_rtl_with_fallbacks(self) -> None:
        content=self.root/f"output/content/{self.project}-content-plan.json"
        for language,code in (("Arabic","ar"),("Kurdish Sorani","ckb")):
            content.write_text(json.dumps({"project_id":self.project,"content_ideas":[{"content_idea_id":"idea-1","title":"Verified Residences","language":language}]}));VisualArtDirectorWorkflow(self.project,self.root).run();plan=json.loads(BrandComposer(self.project,self.root).compose(force=True).read_text())["plans"][0]
            self.assertEqual(plan["text_direction"],"rtl");self.assertEqual(plan["language"],language)

    def test_qa_critical_failures(self) -> None:
        composer=BrandComposer(self.project,self.root);payload=json.loads(composer.compose().read_text());payload["plans"][0]["website"]="wrong.example";payload["plans"][0]["logo_position"][2]*=2;composer.plan_path.write_text(json.dumps(payload))
        result=json.loads(composer.qa(force=True).read_text())["items"][0];self.assertEqual(result["status"],"failed");self.assertTrue(any("website" in error for error in result["errors"]));self.assertTrue(any("distorted" in error for error in result["errors"]))

    def test_ambiguous_project_name_omitted_and_cross_project_skipped(self) -> None:
        knowledge=self.root/f"output/knowledge/{self.project}.json";knowledge.write_text(json.dumps({"project":{"name":"One"},"project_identity":{"project_name":"Two"}}));directions=json.loads(VisualArtDirectorWorkflow(self.project,self.root).run().read_text());self.assertEqual(directions["summary"]["approved"],0)
        with self.assertRaisesRegex(ValueError,"require redirection"):BrandComposer(self.project,self.root).compose(force=True)
        self._fixture();prompts=self.root/f"output/image-prompts/{self.project}-image-prompts.json";data=json.loads(prompts.read_text());data["project_id"]="Other";prompts.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"cross-project"):VisualArtDirectorWorkflow(self.project,self.root).run()


if __name__ == "__main__": unittest.main()
