import unittest,tempfile,hashlib,io
from pathlib import Path
import fitz
from PIL import Image
from src.visual_assets.extraction import extract_visual_assets
import json
class EmbeddedProvenanceTests(unittest.TestCase):
 def test_embedded_image_retains_exact_document_path_and_hash(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);pdf=root/'document.pdf';buf=io.BytesIO();Image.new('RGB',(20,20),'red').save(buf,format='PNG')
   doc=fitz.open();page=doc.new_page(width=100,height=100);page.insert_image(fitz.Rect(5,5,95,95),stream=buf.getvalue());doc.save(pdf);doc.close()
   manifest=extract_visual_assets('Fixture',[pdf],output_root=root/'sources');assets=json.loads(manifest.read_text(encoding='utf-8'))['assets']
   embedded=[a for a in assets if a['source_kind']=='pdf_embedded_image'];self.assertTrue(embedded)
   for asset in embedded:
    self.assertEqual(asset['source_document_path'],str(pdf.resolve()))
    self.assertEqual(asset['source_document_sha256'],hashlib.sha256(pdf.read_bytes()).hexdigest())
