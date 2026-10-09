from __future__ import annotations

import hashlib,json,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from src.brand_kit.project_identity import extract_project_brand_identity


class ProjectBrandIdentityTests(unittest.TestCase):
    def test_wordmark_manifest_provenance_and_source_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project="Project";source=root/"output/source-images"/project/"originals";source.mkdir(parents=True);cover=source/"cover.png";image=Image.new("RGBA",(1600,1200),(35,10,25,255));draw=ImageDraw.Draw(image);draw.rectangle((310,980,860,1060),fill=(245,245,245,255));image.save(cover);before=hashlib.sha256(cover.read_bytes()).hexdigest()
            manifest={"assets":[{"asset_id":"cover","filename":"originals/cover.png","source_document":"catalogue.pdf","source_page":1,"sha256":before}]};(source.parent/"manifest.json").write_text(json.dumps(manifest));knowledge=root/"output/knowledge";knowledge.mkdir(parents=True);(knowledge/f"{project}.json").write_text(json.dumps({"project_identity":{"project_name":"Verified Project"}}))
            path,payload=extract_project_brand_identity(root,project);self.assertTrue(path.is_file());self.assertTrue(payload["project_wordmark"]["available"]);self.assertEqual(payload["project_wordmark"]["source_page"],1);self.assertEqual(payload["project_wordmark"]["source_document"],"catalogue.pdf");self.assertEqual(payload["preferred_project_name_rendering"],"wordmark");self.assertFalse(payload["project_font"]["available"]);self.assertEqual(before,hashlib.sha256(cover.read_bytes()).hexdigest())

    def test_missing_identity_candidate_records_safe_fallback_without_font_guess(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project="Project";source=root/"output/source-images"/project/"originals";source.mkdir(parents=True);plain=source/"plain.png";Image.new("RGB",(800,600),(80,80,80)).save(plain);(source.parent/"manifest.json").write_text(json.dumps({"assets":[{"filename":"originals/plain.png","source_document":"catalogue.pdf","source_page":1}]}));knowledge=root/"output/knowledge";knowledge.mkdir(parents=True);(knowledge/f"{project}.json").write_text(json.dumps({"project_identity":{"project_name":"Verified Project"}}))
            _,payload=extract_project_brand_identity(root,project);self.assertTrue(payload["fallback_required"]);self.assertTrue(payload["project_brand_identity_unavailable"]);self.assertFalse(payload["project_font"]["available"]);self.assertFalse(payload["developer_identity"]["available"]);self.assertEqual(payload["api_calls"],{"ai":0,"image_generation":0,"meta":0})

    def test_compound_identity_is_partitioned_with_source_colors_and_no_background_texture(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project="Project";source=root/"output/source-images"/project/"originals";source.mkdir(parents=True);cover=source/"cover.png";image=Image.new("RGB",(1200,1000),(62,8,42));draw=ImageDraw.Draw(image)
            # Large project treatment, then separated developer and project suffix clusters.
            draw.rectangle((180,650,1010,760),fill=(244,237,218));draw.rectangle((190,800,590,860),fill=(244,237,218));draw.rectangle((790,800,1030,860),fill=(244,237,218));image.save(cover);before=hashlib.sha256(cover.read_bytes()).hexdigest();(source.parent/"manifest.json").write_text(json.dumps({"assets":[{"filename":"originals/cover.png","source_document":"catalogue.pdf","source_page":1}]}));knowledge=root/"output/knowledge";knowledge.mkdir(parents=True);(knowledge/f"{project}.json").write_text(json.dumps({"project_identity":{"project_name":"Verified Project","developer_name":"Verified Developer"}}))
            _,payload=extract_project_brand_identity(root,project);self.assertTrue(payload["project_wordmark"]["transparent_background"]);self.assertFalse(payload["background_included"]);self.assertTrue(payload["developer_identity"]["available"]);self.assertTrue(payload["developer_identity"]["wordmark_path"]);self.assertGreaterEqual(len(payload["brand_colors"]),2);self.assertEqual(before,hashlib.sha256(cover.read_bytes()).hexdigest())
            with Image.open(root/payload["project_wordmark"]["path"]) as mark:self.assertEqual(mark.mode,"RGBA");self.assertLess(mark.getchannel("A").getextrema()[0],255)


if __name__=="__main__":unittest.main()
