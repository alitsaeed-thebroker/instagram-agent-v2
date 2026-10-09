from __future__ import annotations

import hashlib,json,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from src.branding.source_content import generate_branded_content,_render,_is_project_overview,_overview_copy,_identity_background,PROJECT_OVERVIEW_LAYOUT
from src.branding.design_system import TOKENS, LAYOUT_FAMILIES, layout_family
from src.branding.visual_regression import baseline_from_manifest,compare_baseline,image_difference_ratio,update_baseline,validate_baseline


class BrandedContentTests(unittest.TestCase):
    def _setup(self,root:Path,*,rejected=False,missing=False):
        project="Project One";slug="Project-One";selected=root/"output/selected-images"/slug;selected.mkdir(parents=True);images=[]
        kinds=["full_project_site_plan","exterior_render","exterior_render","interior_render"];roles=["project_overview","exterior_overview","exterior_detail","interior_experience"]
        for index in range(4):
            path=selected/f"image-{index}.jpg";image=Image.new("RGB",(1600+index*10,900),(35+index*10,90,130));ImageDraw.Draw(image).rectangle((300,180,1250,760),fill=(190,170,130));image.save(path,quality=94);digest=hashlib.sha256(path.read_bytes()).hexdigest()
            images.append({"project":project,"path":f"{project}/originals/image-{index}.jpg","sha256":digest,"selected":True,"selected_path":f"{slug}/{path.name}","selection_rank":index+1,"overall_score":50 if index==0 else 99-index,"source_image_type":kinds[index],"story_role":roles[index],"selection_priority":"REJECT" if rejected and index==0 else "HIGH","rejection_reason":"test rejection" if rejected and index==0 else None})
        inventory=root/"output/inventory";inventory.mkdir(parents=True);(inventory/f"source-image-ranking-{slug}.json").write_text(json.dumps({"images":images}))
        def slide(index):return {"slide_number":index+1,"source_image":images[index]["path"],"source_image_type":kinds[index],"story_role":roles[index],"selection_priority":images[index]["selection_priority"],"rejection_reason":images[index]["rejection_reason"]}
        posts=[{"post_number":1,"post_id":"post-001","post_group_id":"post-001-project_overview","title":"Project Overview","story":"project_overview","content_topic":"project_overview","post_format":"single","slide_count":1,"slides":[slide(0)]},{"post_number":2,"post_id":"post-002","post_group_id":"post-002-villas","title":"Villas","story":"villas","content_topic":"villas","post_format":"carousel","slide_count":3,"slides":[slide(1),slide(2),slide(3)]}]
        if missing:posts[1]["slides"][1]["source_image"]="Project One/originals/missing.jpg"
        canonical=root/"output/content-inventory"/f"{project}-content-opportunity-inventory.json";canonical.parent.mkdir(parents=True);canonical.write_text(json.dumps({"project_id":project,"inventory_version":"1.0.0","contract_role":"authoritative_content_opportunity_inventory"}))
        plan_path=root/"output/content"/f"{project}-content-plan.json";plan_path.parent.mkdir(parents=True);plan_path.write_text(json.dumps({"contract_role":"compatibility_content_plan","derived_from_canonical_inventory":True,"canonical_inventory_path":str(canonical),"canonical_inventory_version":"1.0.0","canonical_inventory_sha256":hashlib.sha256(canonical.read_bytes()).hexdigest(),"projects":[{"project":project,"posts":posts}]}))
        logo_dir=root/"input/brand/logos";logo_dir.mkdir(parents=True);logo=logo_dir/"logo.png";mark=Image.new("RGBA",(600,180),(0,0,0,0));ImageDraw.Draw(mark).rectangle((10,20,590,160),fill=(120,24,16,255));mark.save(logo);logo_hash=hashlib.sha256(logo.read_bytes()).hexdigest()
        (root/"input/brand/brand-config.json").write_text(json.dumps({"visual_identity":{"logo_policy":{"status":"available"}},"approval":{"status":"approved","locked":True,"approved_logo_hash":logo_hash}}))
        knowledge=root/"output/knowledge";knowledge.mkdir(parents=True);(knowledge/f"{project}.json").write_text(json.dumps({"project_identity":{"project_name":"Verified Project","location":"Erbil, along the 120m Road near Rashkin Park"},"fact_provenance":{"project_identity.location":[{"source_document":"catalogue.pdf","source_page":4}]}}))
        return project,images,logo

    def test_post_boundaries_formats_paths_quality_and_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,logo=self._setup(root);before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/"output/selected-images/Project-One").glob("*")};manifest,payload=generate_branded_content(root,project)
            self.assertEqual(manifest.name,"branded-content-Project-One.json");self.assertEqual([(x["content_topic"],x["post_format"]) for x in payload["posts"]],[("project_overview","single"),("villas","carousel")])
            self.assertEqual([Path(x["output_path"]).as_posix().split("/")[-2:] for x in payload["items"]],[["post-001","post.jpg"],["post-002","slide-01.jpg"],["post-002","slide-02.jpg"],["post-002","slide-03.jpg"]])
            self.assertEqual([x["story_role"] for x in payload["items"]],["project_overview","exterior_overview","exterior_detail","interior_experience"]);self.assertEqual(payload["posts"][1]["slide_count"],3);self.assertFalse((root/"output/branded-content/Project-One/carousel-001").exists())
            with Image.open(logo) as im:logo_ratio=im.width/im.height
            for item in payload["items"]:
                with Image.open(root/item["output_path"]) as out:self.assertEqual(out.size,(1080,1350))
                self.assertAlmostEqual(item["source_aspect_ratio"],item["rendered_source_aspect_ratio"],places=2);self.assertAlmostEqual(item["logo_aspect_ratio"],logo_ratio,places=3)
            self.assertTrue(payload["items"][0]["full_source_visible"]);self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/"output/selected-images/Project-One").glob("*")});self.assertEqual(payload["api_calls"],{"ai":0,"image_generation":0,"meta":0})

    def test_visual_editorial_inventory_is_rejected_as_strategy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,_=self._setup(root);plan=root/"output/content/Project One-content-plan.json"
            plan.write_text(json.dumps({"role":"visual_intelligence","authoritative_strategy":False,"pre_strategy":True,"may_not_drive_branded_content":True}))
            with self.assertRaisesRegex(ValueError,"derived from canonical"):generate_branded_content(root,project)

    def test_score_does_not_merge_or_reorder_posts_and_rerun_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,_=self._setup(root);_,first=generate_branded_content(root,project);_,second=generate_branded_content(root,project)
            self.assertEqual([x["output_sha256"] for x in first["items"]],[x["output_sha256"] for x in second["items"]]);self.assertEqual(Path(second["items"][0]["source_image"]).name,"image-0.jpg")

    def test_rejected_and_missing_assets_are_not_substituted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,_=self._setup(root,rejected=True);_,payload=generate_branded_content(root,project);self.assertEqual(payload["outputs_created"],3);self.assertTrue(payload["omissions"])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,_=self._setup(root,missing=True);_,payload=generate_branded_content(root,project);self.assertEqual(payload["outputs_created"],3);self.assertTrue(payload["omissions"])

    def test_site_plan_must_be_standalone(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,_=self._setup(root);path=root/"output/content/Project One-content-plan.json";plan=json.loads(path.read_text());plan["projects"][0]["posts"][0]["post_format"]="carousel";path.write_text(json.dumps(plan))
            _,payload=generate_branded_content(root,project);self.assertEqual(payload["posts"][0]["render_status"],"planned_not_renderable");self.assertEqual(payload["posts"][0]["reason"],"no_approved_renderer")

    def test_authentic_wordmark_replaces_generic_project_name_without_distortion(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,logo=self._setup(root);mark_dir=root/"output/project-brand/Project-One";mark_dir.mkdir(parents=True);mark=mark_dir/"project-wordmark.png";Image.new("RGBA",(600,120),(65,15,45,255)).save(mark);digest=hashlib.sha256(mark.read_bytes()).hexdigest();manifest={"project_wordmark":{"available":True,"path":"output/project-brand/Project-One/project-wordmark.png","output_sha256":digest},"preferred_project_name_rendering":"wordmark"};(root/"output/inventory/project-brand-Project-One.json").write_text(json.dumps(manifest));logo_before=hashlib.sha256(logo.read_bytes()).hexdigest()
            source=root/"output/selected-images/Project-One/image-0.jpg";support={"text":"120m Road, Erbil","sources":[]};_,baseline=_render(source,logo,"Verified Project",support,1,"full_project_site_plan",{"available":False});_,authentic=_render(source,logo,"Verified Project",support,1,"full_project_site_plan",{"available":True,"path":mark,"sha256":digest})
            for field in ("layout_strategy","logo_box","panel_box","source_render_box","supporting_font_size"):self.assertEqual(baseline[field],authentic[field])
            _,payload=generate_branded_content(root,project);self.assertTrue(all(x["project_name_rendering"]=="wordmark" for x in payload["items"]));self.assertTrue(all(x["project_identity_aspect_ratio"]==5.0 for x in payload["items"]));self.assertTrue(all(not x["project_brand_identity_unavailable"] for x in payload["items"]));self.assertEqual(logo_before,hashlib.sha256(logo.read_bytes()).hexdigest())

    def test_overview_layout_is_semantic_light_and_aspect_safe_while_villa_geometry_is_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,logo=self._setup(root);source=root/"output/selected-images/Project-One/image-0.jpg";before=hashlib.sha256(source.read_bytes()).hexdigest();support={"text":"Verified location","sources":[]}
            self.assertTrue(_is_project_overview("full_project_site_plan"));self.assertTrue(_is_project_overview("masterplan"));self.assertFalse(_is_project_overview("exterior_render","villas","exterior_overview"))
            overview,decision=_render(source,logo,"Verified Project",support,1,"masterplan",{"available":False},content_topic="project_overview",story_role="project_overview",headline="Verified Overview",website="example.test")
            self.assertEqual(decision["layout_strategy"],PROJECT_OVERVIEW_LAYOUT);self.assertTrue(decision["full_source_visible"]);self.assertAlmostEqual(decision["source_aspect_ratio"],decision["rendered_source_aspect_ratio"],places=2);self.assertEqual(decision["editorial_background"],"#FFFFFF");self.assertEqual(decision["accent_color"],"#781810");self.assertEqual(overview.getpixel((1000,100)),(255,255,255));self.assertEqual(overview.getpixel((58,100)),(120,24,16));self.assertTrue(decision["project_identity_overlaps_header_image"]);self.assertLess(decision["footer_box"][3]-decision["footer_box"][1],250);self.assertGreater(decision["source_render_box"][3]-decision["source_render_box"][1],decision["panel_box"][3]-decision["panel_box"][1]);self.assertTrue(decision["location_rendered"]);self.assertTrue(decision["website_rendered"])
            mark=root/"mark.png";developer=root/"developer.png";Image.new("RGBA",(600,120),(241,228,217,255)).save(mark);Image.new("RGBA",(500,100),(241,228,217,255)).save(developer);_,branded=_render(source,logo,"Verified Project",support,1,"masterplan",{"available":True,"path":mark,"colors":["#F1E4D9","#1E071D"],"developer_wordmark_path":developer},content_topic="project_overview",story_role="project_overview",headline="Verified Overview",kicker="Project Overview",website="example.test");self.assertEqual(branded["project_name_rendering"],"wordmark");self.assertTrue(branded["developer_identity_used"]);self.assertIn(branded["project_identity_card_placement"],{"upper_left","upper_right"})
            realistic=root/"overview.jpg";Image.new("RGB",(1529,1000),(90,110,80)).save(realistic);_,refined=_render(realistic,logo,"Verified Project",support,1,"full_project_site_plan",{"available":False},content_topic="project_overview",story_role="project_overview",headline="Verified Overview",kicker="Project Overview",website="example.test");self.assertLess(refined["panel_box"][3],430);self.assertLess(refined["footer_box"][3]-refined["footer_box"][1],214);self.assertGreater((refined["source_render_box"][2]-refined["source_render_box"][0])*(refined["source_render_box"][3]-refined["source_render_box"][1]),1080*706);copy=_overview_copy("Project Overview",{"project_name":"Verified Project"},{"canonical_facts":[{"value":"The Vision of Verified Project","sources":[{"source_page":3}]},{"value":"architecture meets timeless luxury.","category":"marketing_claim"}]});self.assertEqual(copy["headline"],"The Vision of Verified Project");self.assertEqual(copy["supporting_line"],"Architecture meets timeless luxury.")
            square=root/"square.jpg";Image.new("RGB",(1000,1000),(80,110,140)).save(square);_,villa=_render(square,logo,"Verified Project",None,1,"exterior_render",{"available":False},content_topic="villas",story_role="exterior_overview");self.assertEqual(villa["layout_strategy"],"PROPERTY_SHOWCASE");self.assertEqual(villa["source_render_box"],[0,0,1080,960]);self.assertEqual(villa["design_tokens"]["panel_height"],TOKENS.panel_height);self.assertEqual(before,hashlib.sha256(source.read_bytes()).hexdigest())

    def test_villa_identity_card_is_contrast_aware_authentic_and_consistent(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,logo=self._setup(root);brand_dir=root/"output/project-brand/Project-One";brand_dir.mkdir(parents=True);mark=brand_dir/"project-wordmark.png";developer=brand_dir/"developer-wordmark.png"
            Image.new("RGBA",(600,120),(241,228,217,255)).save(mark);Image.new("RGBA",(500,100),(241,228,217,255)).save(developer);mark_hash=hashlib.sha256(mark.read_bytes()).hexdigest();developer_hash=hashlib.sha256(developer.read_bytes()).hexdigest();logo_hash=hashlib.sha256(logo.read_bytes()).hexdigest()
            manifest={"project_wordmark":{"available":True,"path":"output/project-brand/Project-One/project-wordmark.png","output_sha256":mark_hash},"developer_identity":{"available":True,"wordmark_path":"output/project-brand/Project-One/developer-wordmark.png","wordmark_sha256":developer_hash},"brand_colors":["#F1E4D9","#1E071D"]};(root/"output/inventory/project-brand-Project-One.json").write_text(json.dumps(manifest))
            _,payload=generate_branded_content(root,project);villas=payload["posts"][1]["outputs"];treatments=[x["project_identity_rendering"] for x in villas]
            self.assertTrue(all(x==treatments[0] for x in treatments));self.assertEqual(treatments[0]["background_mode"],"solid_brand_color");self.assertEqual(treatments[0]["background_color"],"#1E071D");self.assertEqual(treatments[0]["contrast_status"],"pass");self.assertFalse(treatments[0]["wordmark_recolored"]);self.assertFalse(treatments[0]["texture_used"])
            self.assertTrue(all(x["project_identity_box"][3]-x["project_identity_box"][1]>=40 for x in villas));self.assertTrue(all((x["developer_identity_box"][2]-x["developer_identity_box"][0])<(x["project_identity_box"][2]-x["project_identity_box"][0]) for x in villas));self.assertTrue(all(x["project_identity_aspect_ratio"]==5.0 for x in villas));self.assertEqual(mark_hash,hashlib.sha256(mark.read_bytes()).hexdigest());self.assertEqual(logo_hash,hashlib.sha256(logo.read_bytes()).hexdigest())
            dark=Image.new("RGBA",(300,80),(20,20,20,255));self.assertEqual(_identity_background(dark,["#F8F8F8"])["manifest"]["background_color"],"#F8F8F8");self.assertEqual(_identity_background(dark,[])["manifest"]["background_mode"],"solid_neutral")

    def test_complete_plan_is_evaluated_dynamically_and_outputs_are_safely_synchronized(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,_=self._setup(root);plan_path=root/"output/content/Project One-content-plan.json";plan=json.loads(plan_path.read_text());posts=plan["projects"][0]["posts"]
            _,baseline=generate_branded_content(root,project);baseline_hashes=[x["output_sha256"] for x in baseline["items"]]
            architecture={**posts[1],"post_number":4,"post_id":"post-004","post_group_id":"post-004-architecture","title":"Architecture","content_topic":"architecture","post_format":"single","slide_count":1,"slides":[posts[1]["slides"][0]]}
            interiors={**posts[1],"post_number":7,"post_id":"post-007","post_group_id":"post-007-interiors","title":"Interiors","content_topic":"interiors","post_format":"carousel","slide_count":2,"slides":posts[1]["slides"][1:]}
            empty={"post_number":9,"post_id":"post-009","post_group_id":"post-009-location","title":"Location","content_topic":"location","post_format":"single","slide_count":0,"slides":[]}
            unsupported={"post_number":12,"post_id":"post-012","post_group_id":"post-012-technical","title":"Technical","content_topic":"technical","post_format":"single","slide_count":1,"slides":[{**posts[1]["slides"][0],"source_image_type":"floor_plan"}]}
            plan["projects"][0]["posts"]=[*posts,architecture,interiors,empty,unsupported];plan_path.write_text(json.dumps(plan))
            stale=root/"output/branded-content/Project-One/post-999";stale.mkdir(parents=True);(stale/"post.jpg").write_bytes(b"stale");other=root/"output/branded-content/Other/post-999";other.mkdir(parents=True);(other/"post.jpg").write_bytes(b"keep");legacy=root/"output/branded-images/Project-One";legacy.mkdir(parents=True);(legacy/"keep.png").write_bytes(b"keep")
            _,payload=generate_branded_content(root,project);self.assertEqual(payload["summary"],{"planned_posts":6,"renderable_posts":4,"rendered_posts":4,"deferred_posts":2,"rendered_assets":7});self.assertEqual([x["post_number"] for x in payload["posts"]],[1,2,4,7,9,12]);self.assertEqual([x["render_status"] for x in payload["posts"]],["rendered","rendered","rendered","rendered","planned_not_renderable","planned_not_renderable"]);self.assertEqual(payload["posts"][4]["reason"],"no_approved_source_visual");self.assertEqual(payload["posts"][5]["reason"],"no_approved_renderer")
            self.assertTrue((root/"output/branded-content/Project-One/post-004/post.jpg").is_file());self.assertEqual(len(list((root/"output/branded-content/Project-One/post-007").glob("slide-*.jpg"))),2);self.assertFalse(stale.exists());self.assertTrue((other/"post.jpg").is_file());self.assertTrue((legacy/"keep.png").is_file());self.assertEqual(baseline_hashes,[x["output_sha256"] for x in payload["items"][:4]]);self.assertEqual(payload["api_calls"],{"ai":0,"image_generation":0,"meta":0});self.assertEqual(payload["publishing_writes"],0)

    def test_shared_design_tokens_layout_families_and_project_neutrality(self):
        self.assertEqual(layout_family("villas"),"PROPERTY_SHOWCASE")
        self.assertEqual(layout_family("architecture"),"ARCHITECTURE_SHOWCASE")
        self.assertEqual(layout_family("interiors"),"INTERIOR_SHOWCASE")
        self.assertEqual(layout_family("amenities"),"AMENITY_SHOWCASE")
        self.assertEqual(TOKENS.canvas_width,1080);self.assertEqual(TOKENS.canvas_height,1350)
        module=(Path(__file__).parents[1]/"src/branding/design_system.py").read_text(encoding="utf-8")
        self.assertNotIn("Beverly Hills",module);self.assertNotIn("NorthLight",module)
        self.assertEqual(len(set(LAYOUT_FAMILIES.values())),8)

    def test_second_project_uses_its_own_data_driven_identity_and_safe_fit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,_=self._setup(root);brand_dir=root/"output/project-brand/Project-One";brand_dir.mkdir(parents=True)
            mark=brand_dir/"project-wordmark.png";Image.new("RGBA",(320,160),(15,80,120,255)).save(mark);digest=hashlib.sha256(mark.read_bytes()).hexdigest()
            (root/"output/inventory/project-brand-Project-One.json").write_text(json.dumps({"project_wordmark":{"available":True,"path":"output/project-brand/Project-One/project-wordmark.png","output_sha256":digest},"brand_colors":["#0F5078"]}))
            _,payload=generate_branded_content(root,project);self.assertEqual(payload["project"],"Project One");self.assertTrue(all(x["project_identity_aspect_ratio"]==2.0 for x in payload["items"]));self.assertTrue(all(x["project_identity_rendering"]["contrast_checked"] for x in payload["items"]));self.assertTrue(all("Beverly" not in str(x) and "NorthLight" not in str(x) for x in payload["items"]))

    def test_visual_regression_baseline_records_required_provenance_and_detects_pixel_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,_=self._setup(root);_,payload=generate_branded_content(root,project);baseline=baseline_from_manifest(payload)
            self.assertEqual(baseline["renderer_version"],payload["module_version"]);self.assertEqual(baseline["project_fixture"],project);self.assertFalse(compare_baseline(baseline,baseline))
            first=baseline["items"][0];self.assertTrue({"status","project_fixture","post_number","slide_number","content_topic","layout_family","renderer_version","schema_version","source_asset_hash","output_hash","width","height","aspect_ratio","approval_timestamp","baseline_reference_path"}.issubset(first))
            changed=json.loads(json.dumps(baseline));changed["items"][0]["output_hash"]="changed";self.assertIn("output_hash",compare_baseline(baseline,changed)[0])
            image=root/first["baseline_reference_path"];self.assertEqual(image_difference_ratio(image,image),0.0)

    def test_visual_baseline_update_is_explicit_read_only_validation_detects_one_pixel(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,_,_=self._setup(root);manifest_path,payload=generate_branded_content(root,project);baseline_path=root/"tests/visual_baselines/canonical/manifest.json"
            with self.assertRaises(PermissionError):update_baseline(manifest_path,baseline_path,root=root)
            baseline=update_baseline(manifest_path,baseline_path,root=root,explicit=True,approval_timestamp="2026-08-09T00:00:00+00:00");before=baseline_path.read_bytes();self.assertFalse(validate_baseline(root,baseline))
            output=root/baseline["items"][0]["baseline_reference_path"]
            with Image.open(output) as raw:image=raw.convert("RGB")
            old=image.getpixel((0,0));image.putpixel((0,0),((old[0]+1)%256,old[1],old[2]));image.save(output,"JPEG",quality=95,subsampling=0)
            failures=validate_baseline(root,baseline);self.assertTrue(any("expected_hash=" in x and "actual_hash=" in x and "baseline_path=" in x and "newly_rendered_path=" in x for x in failures));self.assertEqual(before,baseline_path.read_bytes())


if __name__=="__main__":unittest.main()
