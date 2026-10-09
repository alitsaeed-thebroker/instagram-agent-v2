from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from src.visual_assets.ranking import rank_source_images


class SourceImageRankingTests(unittest.TestCase):
    def _image(self,path:Path,size=(1400,1000),seed=0)->str:
        path.parent.mkdir(parents=True,exist_ok=True);image=Image.new("RGB",size,(30+seed,70,110));draw=ImageDraw.Draw(image)
        for x in range(0,size[0],40):draw.line((x,0,size[0]-x,size[1]),fill=(180,140+seed%80,80),width=5)
        image.save(path,quality=94);return hashlib.sha256(path.read_bytes()).hexdigest()

    def _fixture(self,root:Path,project="Alpha",count=3):
        folder=root/"source"/project;assets=[];intel=[]
        for index in range(count):
            path=folder/"originals"/f"image-{index}.jpg";digest=self._image(path,size=(1400+index*7,1000+index*5),seed=index);identity=f"a{index}"
            assets.append({"asset_id":identity,"filename":f"originals/{path.name}","sha256":digest})
            intel.append({"asset_id":identity,"asset_type":"exterior","confidence":.95,"contains_text":False,"marketing_suitability":"hero_ready","safe_crop_assessment":{"level":"flexible"}})
        (folder/"manifest.json").write_text(json.dumps({"project":project,"assets":assets}),encoding="utf-8")
        intelligence=root/f"{project}-intelligence.json";intelligence.write_text(json.dumps({"assets":intel}),encoding="utf-8")
        return folder,intelligence

    def test_discovery_schema_copy_limit_and_original_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder,intelligence=self._fixture(root,count=12);before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (folder/"originals").glob("*")}
            _,_,payload=rank_source_images(root/"source",root/"inventory",root/"selected",project="Alpha",max_selected=4,intelligence_path=intelligence)
            self.assertEqual(payload["summary"]["images_discovered"],12);self.assertEqual(payload["summary"]["images_selected"],4)
            required={"path","width","height","aspect_ratio","source_image_type","visual_quality_score","marketing_value_score","brand_content_suitability_score","social_media_suitability_score","overall_score","text_heavy","likely_duplicate","duplicate_group","recommended_use","selection_priority","rejection_reason"}
            self.assertTrue(required<=set(payload["images"][0]));self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (folder/"originals").glob("*")})
            self.assertEqual(len(list((root/"selected"/"Alpha").glob("*"))),4)

    def test_low_resolution_floorplan_duplicate_and_corrupt_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder,intelligence=self._fixture(root,count=2);data=json.loads(intelligence.read_text());data["assets"][1]["asset_type"]="floorplan";intelligence.write_text(json.dumps(data))
            low=folder/"originals"/"low.png";self._image(low,(120,90));duplicate=folder/"originals"/"duplicate.jpg";duplicate.write_bytes((folder/"originals"/"image-0.jpg").read_bytes());bad=folder/"originals"/"bad.jpg";bad.write_bytes(b"not an image")
            _,_,payload=rank_source_images(root/"source",root/"inventory",root/"selected",project="Alpha",intelligence_path=intelligence);by_name={Path(x["path"]).name:x for x in payload["images"]}
            self.assertEqual(by_name["image-1.jpg"]["source_image_type"],"floor_plan");self.assertEqual(by_name["image-1.jpg"]["selection_priority"],"LOW");self.assertEqual(by_name["low.png"]["selection_priority"],"REJECT")
            self.assertEqual(by_name["duplicate.jpg"]["duplicate_group"],by_name["image-0.jpg"]["duplicate_group"]);self.assertTrue(by_name["duplicate.jpg"]["likely_duplicate"] or by_name["image-0.jpg"]["likely_duplicate"]);self.assertEqual(by_name["bad.jpg"]["rejection_reason"],"corrupted or unreadable image")

    def test_projects_remain_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,a=self._fixture(root,"Alpha",1);_,b=self._fixture(root,"Beta",1);combined=root/"all-intelligence.json";combined.write_text(json.dumps({"assets":[*json.loads(a.read_text())["assets"],*json.loads(b.read_text())["assets"]]}))
            rank_source_images(root/"source",root/"inventory",root/"selected",max_selected=1,intelligence_path=combined)
            self.assertTrue((root/"selected"/"Alpha").is_dir());self.assertTrue((root/"selected"/"Beta").is_dir())

    def test_editorial_sequence_and_semantic_carousel(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder,intelligence=self._fixture(root,count=5);data=json.loads(intelligence.read_text());types=["site_plan","exterior","exterior","interior","amenity"]
            for item,kind in zip(data["assets"],types):item["asset_type"]=kind;item["visual_category"]=kind;item["dominant_subject"]="complete development layout" if kind=="site_plan" else "residential villa" if kind=="exterior" else "villa interior" if kind=="interior" else kind
            intelligence.write_text(json.dumps(data));_,_,payload=rank_source_images(root/"source",root/"inventory",root/"selected",project="Alpha",intelligence_path=intelligence)
            selected=sorted((x for x in payload["images"] if x["selected"]),key=lambda x:x["selection_rank"])
            self.assertEqual(selected[0]["source_image_type"],"full_project_site_plan");self.assertNotEqual(selected[0]["source_image_type"],"floor_plan")
            self.assertEqual([x["content_priority"] for x in selected[:5]],[1,2,2,3,4]);self.assertGreater(selected[1]["overall_score"],0)
            self.assertIn(selected[1]["asset_id"],selected[0]["carousel_compatibility"])
            plan=(root/"inventory/visual-editorial-inventory-Alpha.md").read_text(encoding="utf-8");self.assertIn("NON-AUTHORITATIVE VISUAL EDITORIAL INVENTORY",plan);self.assertIn("exterior_overview",plan)
            machine=json.loads((root/"inventory/visual-editorial-inventory-Alpha.json").read_text(encoding="utf-8"));self.assertFalse(machine["authoritative_strategy"]);self.assertTrue(machine["may_not_drive_branded_content"]);first=machine["projects"][0]["visual_groups"][0]
            self.assertEqual(first["editorial_visual_role"],"project_overview");self.assertEqual(first["visual_format_suggestion"],"single");self.assertEqual([x["visual_story_role"] for x in first["visual_assets"]],["project_overview"])
            second=machine["projects"][0]["visual_groups"][1];self.assertEqual(second["editorial_visual_role"],"villas");self.assertEqual(second["visual_format_suggestion"],"carousel");self.assertEqual([x["visual_story_role"] for x in second["visual_assets"]],["exterior_overview","exterior_detail","interior_experience"])

    def test_unusable_masterplan_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder,intelligence=self._fixture(root,count=1);path=folder/"originals/image-0.jpg";self._image(path,(120,90));manifest=json.loads((folder/"manifest.json").read_text());manifest["assets"][0]["sha256"]=hashlib.sha256(path.read_bytes()).hexdigest();(folder/"manifest.json").write_text(json.dumps(manifest));data=json.loads(intelligence.read_text());data["assets"][0]["asset_type"]="masterplan";intelligence.write_text(json.dumps(data))
            _,_,payload=rank_source_images(root/"source",root/"inventory",root/"selected",project="Alpha",intelligence_path=intelligence);item=payload["images"][0]
            self.assertEqual(item["source_image_type"],"masterplan");self.assertEqual(item["selection_priority"],"REJECT")

    def test_ambiguous_site_plan_is_conservatively_a_unit_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,intelligence=self._fixture(root,count=1);data=json.loads(intelligence.read_text());data["assets"][0].update(asset_type="site_plan",visual_category="site_plan",dominant_subject="site plan",asset_subtype="site_plan");intelligence.write_text(json.dumps(data))
            _,_,payload=rank_source_images(root/"source",root/"inventory",root/"selected",project="Alpha",intelligence_path=intelligence)
            self.assertEqual(payload["images"][0]["source_image_type"],"unit_plan");self.assertNotEqual(payload["images"][0]["content_priority"],1)

    def test_deep_knowledge_expands_plan_and_writes_content_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,intelligence=self._fixture(root,"Beta",2);data=json.loads(intelligence.read_text());data["assets"][0].update(asset_type="site_plan",dominant_subject="complete development layout");data["assets"][1].update(asset_type="exterior",dominant_subject="apartment tower exterior");intelligence.write_text(json.dumps(data))
            knowledge=root/"beta-knowledge.json";knowledge.write_text(json.dumps({"project_overview":{"facts":[{"value":"Mixed-use community","sources":[{"document":"brochure.pdf","page":1}]}]},"location":{"facts":[{"value":"Near the central district","sources":[{"document":"brochure.pdf","page":2}]}]},"features":[{"name":"Smart access","sources":[{"document":"technical.pdf","page":3}]}],"unit_types":[{"source_name":"2BR","category":"apartment","source_pages":[{"document":"plans.pdf","page":4}]}],"plans_and_layouts":[]}))
            rank_source_images(root/"source",root/"output/inventory",root/"output/selected",project="Beta",intelligence_path=intelligence,knowledge_path=knowledge)
            plan=json.loads((root/"output/inventory/visual-editorial-inventory-Beta.json").read_text());posts=plan["projects"][0]["visual_groups"];topics=[x["editorial_visual_role"] for x in posts]
            self.assertIn("location",topics);self.assertIn("features",topics);self.assertIn("property_types",topics);self.assertTrue(posts[0]["render_ready"]);self.assertFalse(next(x for x in posts if x["editorial_visual_role"]=="location")["render_ready"])
            coverage=json.loads((root/"output/reports/content-coverage-Beta.json").read_text());self.assertEqual(coverage["projects"][0]["topics_unused"],0);self.assertTrue((root/"output/reports/content-coverage-Beta.md").is_file())

    def test_villa_post_rebuilds_from_full_deep_inventory_not_global_shortlist(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder,intelligence=self._fixture(root,"Alpha",7);data=json.loads(intelligence.read_text());types=["site_plan","exterior","exterior","exterior","interior","exterior","exterior"]
            for index,(item,kind) in enumerate(zip(data["assets"],types)):
                item.update(asset_type=kind,visual_category=kind,dominant_subject="complete development layout" if index==0 else "villa")
            intelligence.write_text(json.dumps(data));manifest=json.loads((folder/"manifest.json").read_text())
            visuals=[{"asset_id":x["asset_id"],"page_number":i+1,"section":"project_overview" if i==0 else "villa_types","image_type":"masterplan" if i==0 else "villa_interior" if i==4 else "villa_exterior","related_villa_type":None if i==0 else "Type A","marketing_topic":"project_overview" if i==0 else "villas"} for i,x in enumerate(manifest["assets"])]
            knowledge=root/"knowledge.json";knowledge.write_text(json.dumps({"source_visuals":visuals}))
            rank_source_images(root/"source",root/"inventory",root/"selected",project="Alpha",max_selected=2,intelligence_path=intelligence,knowledge_path=knowledge)
            plan=json.loads((root/"inventory/visual-editorial-inventory-Alpha.json").read_text());first,second=plan["projects"][0]["visual_groups"][:2]
            self.assertEqual(first["visual_assets"][0]["asset_id"],"a0");self.assertEqual(second["editorial_visual_role"],"villas");self.assertEqual(second["visual_format_suggestion"],"carousel");self.assertEqual(len(second["visual_assets"]),6)
            self.assertGreater(sum(slide["selected_path"] is None for slide in second["visual_assets"]),0);self.assertEqual([x["visual_story_role"] for x in second["visual_assets"]],["exterior_overview","exterior_detail","exterior_detail","exterior_detail","exterior_detail","interior_experience"])
            self.assertTrue(all(x["source_page"] and x["source_section"] and x["ranking_score"] and x["selection_rationale"] for x in second["visual_assets"]))


if __name__=="__main__":unittest.main()
