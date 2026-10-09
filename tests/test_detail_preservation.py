import hashlib, tempfile, unittest
from pathlib import Path
from PIL import Image

from src.production.detail import _enhance, _metrics, _profile
from src.visual_assets.extraction import _write_source_bytes

class DetailPreservationTests(unittest.TestCase):
    def test_byte_exact_png_and_alpha_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/"input.png";Image.new("RGBA",(12,8),(1,2,3,100)).save(source);data=source.read_bytes()
            record=_write_source_bytes(root,data,"doc.pdf",1,1,".png")
            saved=root/Path(record["filename"]).name
            self.assertEqual(saved.read_bytes(),data);self.assertTrue(record["byte_preserving"]);self.assertEqual(record["extraction_fidelity"],"byte_exact")
            with Image.open(saved) as image:self.assertEqual(image.mode,"RGBA")

    def test_already_sharp_source_is_not_sharpened(self):
        profile=_profile("exterior",{"sharpness":1000})
        self.assertEqual(profile["action"],"unchanged")

    def test_conservative_enhancement_preserves_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/"s.png";dest=root/"d.png";Image.effect_noise((100,80),32).convert("RGB").save(source)
            profile=_profile("floorplan",_metrics(source));_enhance(source,dest,profile)
            self.assertEqual(Image.open(source).size,Image.open(dest).size)
            self.assertLessEqual(profile["parameters"]["local_contrast"],1.08)

if __name__=="__main__":unittest.main()
