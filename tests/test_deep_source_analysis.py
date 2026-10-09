from __future__ import annotations

import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from src.knowledge.deep_source import analyze_deep_source


class _Page:
    def __init__(self,text):self.text=text
    def extract_text(self):return self.text
class _Reader:
    def __init__(self,_):self.pages=[_Page("Exclusive Villas\nVilla Type A 1020M2\nGround Floor 434 m2\n• Private garden\n• Smart home automation"),_Page("Amenities & Facilities\n• Swimming pool\n• Tennis court\nContact: +964 750 123 4567\nsales@example.com\nwww.example.com\nالعربية کوردی")]


class DeepSourceAnalysisTests(unittest.TestCase):
    def test_every_page_structure_linking_entities_coverage_and_source_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project="Project";pdf=root/"input/catalogue.pdf";pdf.parent.mkdir();pdf.write_bytes(b"source-pdf");before=hashlib.sha256(pdf.read_bytes()).hexdigest();source=root/"output/source-images"/project;source.mkdir(parents=True);assets=[{"asset_id":"site","source_document":"catalogue.pdf","source_page":1,"filename":"originals/site.jpg","sha256":"a","width":1000,"height":700},{"asset_id":"dev","source_document":"catalogue.pdf","source_page":2,"filename":"originals/dev.png","sha256":"b","width":400,"height":200}];(source/"manifest.json").write_text(json.dumps({"assets":assets}));intel=root/"output/asset-intelligence";intel.mkdir();(intel/f"{project}-asset-intelligence.json").write_text(json.dumps({"assets":[{"asset_id":"site","asset_type":"masterplan","confidence":.95,"dominant_subject":"community masterplan"},{"asset_id":"dev","asset_type":"logo","asset_subtype":"developer_logo","confidence":.9,"dominant_subject":"developer logo"}]}))
            with patch("src.knowledge.deep_source.PdfReader",_Reader):knowledge,coverage,payload=analyze_deep_source(root,project,[pdf])
            self.assertTrue(knowledge.is_file());self.assertTrue(coverage.is_file());self.assertEqual(len(list((root/"output/knowledge/Project/pages").glob("page-*.json"))),2);self.assertEqual(payload["source_sections"],["exclusive_villas","amenities_facilities"]);self.assertEqual(payload["source_visuals"][0]["image_type"],"masterplan");self.assertEqual(payload["source_visuals"][1]["image_type"],"developer_logo");self.assertEqual(payload["villa_types"][0]["type"],"A");self.assertIn("1020M2",payload["villa_types"][0]["areas"]);self.assertEqual(len(payload["amenities"]),2);self.assertEqual(len(payload["contact_information"]),3);self.assertIn("ar",json.loads((root/"output/knowledge/Project/pages/page-002.json").read_text())["languages"]);self.assertEqual(before,hashlib.sha256(pdf.read_bytes()).hexdigest());self.assertEqual(payload["api_calls"],{"ai":0,"image_generation":0,"meta":0})
            report=json.loads(coverage.read_text());self.assertEqual(report["pages_total"],2);self.assertEqual(report["pages_analyzed"],2);self.assertEqual(report["images_semantically_classified"],2)

    def test_duplicate_fact_sources_merge_and_blank_page_is_partial(self):
        class Reader:
            def __init__(self,_):self.pages=[_Page("Project Overview\nSame verified fact."),_Page("Project Overview\nSame verified fact."),_Page("")]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project="P";pdf=root/"x.pdf";pdf.write_bytes(b"x");source=root/"output/source-images/P";source.mkdir(parents=True);(source/"manifest.json").write_text('{"assets":[]}')
            with patch("src.knowledge.deep_source.PdfReader",Reader):_,coverage,payload=analyze_deep_source(root,project,[pdf])
            fact=next(x for x in payload["canonical_facts"] if x["value"]=="Same verified fact.");self.assertEqual(len(fact["sources"]),2);self.assertEqual(payload["knowledge_status"],"partial");self.assertEqual(len(payload["unresolved_pages"]),1);self.assertFalse(payload["quality_gates"]["passed"]);self.assertEqual(json.loads(coverage.read_text())["unresolved_page_count"],1)

    def test_multiple_documents_merge_generic_unit_types_with_provenance(self):
        class Reader:
            def __init__(self,path):
                name=Path(path).name;self.pages=[_Page("Apartments\n2BR Apartment 145 m2\nLiving Room 35 m2") if name=="catalogue.pdf" else _Page("Unit Plans\nOffice Unit 210 m2\nFirst Floor")]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);pdfs=[root/"catalogue.pdf",root/"technical.pdf"]
            for pdf in pdfs:pdf.write_bytes(b"x")
            source=root/"output/source-images/Mixed Project";source.mkdir(parents=True);(source/"manifest.json").write_text('{"assets":[]}')
            with patch("src.knowledge.deep_source.PdfReader",Reader):_,_,payload=analyze_deep_source(root,"Mixed Project",pdfs)
            self.assertEqual(len(payload["source_documents"]),2);self.assertEqual({x["category"] for x in payload["unit_types"]},{"apartment","office"});self.assertEqual(payload["property_types"],payload["unit_types"])
            self.assertEqual({x["source_pages"][0]["document"] for x in payload["unit_types"]},{"catalogue.pdf","technical.pdf"})


if __name__=="__main__":unittest.main()
