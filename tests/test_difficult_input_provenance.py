from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from src.core.text_document_reader import extract_text_document, save_extracted_text
from src.knowledge.commercial import extract_document_intelligence, resolve_project_intelligence
from src.knowledge.document_classifier import DocumentType
from src.knowledge.fusion import fuse_knowledge
from src.knowledge.schema import ProjectKnowledge
from src.knowledge.consumer import canonical_verified_facts


DOCX_PREFIX = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>'''
DOCX_SUFFIX = '''</w:body></w:document>'''


def make_docx(path: Path, body: str) -> None:
    with zipfile.ZipFile(path,"w") as archive:
        archive.writestr("word/document.xml",DOCX_PREFIX+body+DOCX_SUFFIX)


class DifficultInputProvenanceTests(unittest.TestCase):
    def test_regular_docx_table_preserves_exact_rows_and_headers(self):
        body = '''
        <w:p><w:r><w:t>Official unit pricing</w:t></w:r></w:p>
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>Unit</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Area</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Starting Price</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>A101</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>120 sqm</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 150,000</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>B202</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>180 sqm</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 220,000</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>'''
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"pricing.docx";make_docx(source,body)
            blocks=extract_text_document(source,"P")
        self.assertEqual(blocks[0].location,"paragraph 1")
        rows=[x for x in blocks if x.block_type=="table_row"]
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0].location,"table 1 row 2")
        self.assertEqual(rows[0].headers,("Unit","Area","Starting Price"))
        self.assertIn("Unit: A101",rows[0].text)
        self.assertIn("Starting Price: USD 150,000",rows[0].text)
        self.assertEqual(rows[0].structure_status,"regular")

    def test_table_rows_do_not_cross_join_unit_prices(self):
        body = '''
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>Unit</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Area</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Unit Price</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>A101</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>120 sqm</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 150,000</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>B202</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>180 sqm</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 220,000</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>'''
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"pricing.docx";make_docx(source,body)
            blocks=extract_text_document(source,"P")
            markdown,_=save_extracted_text(root/"out",source,"P",blocks)
            doc=extract_document_intelligence(
                markdown.read_text(encoding="utf-8"),
                project="P",source_file="pricing.docx",document_type=DocumentType.PRICE_LIST,
                source_id="src_docx",source_sha256="abc",
            )
            result=resolve_project_intelligence([doc],"P")
        prices=[x for x in result["pricing"]["facts"] if x["fact_type"]=="total_unit_price"]
        self.assertEqual(len(prices),2)
        self.assertEqual({x["relationship_context"]["unit_id"] for x in prices},{"A101","B202"})
        by_unit={x["relationship_context"]["unit_id"]:x for x in prices}
        self.assertEqual(by_unit["A101"]["value"],150000)
        self.assertEqual(by_unit["B202"]["value"],220000)
        self.assertEqual(by_unit["A101"]["evidence"][0]["table_index"],1)
        self.assertEqual(by_unit["A101"]["evidence"][0]["row_index"],2)

    def test_merged_table_row_is_ambiguous_and_not_extracted_as_price(self):
        body = '''
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>Unit</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Unit Price</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr>
            <w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>A101 USD 150,000</w:t></w:r></w:p></w:tc>
          </w:tr>
        </w:tbl>'''
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"merged.docx";make_docx(source,body)
            blocks=extract_text_document(source,"P")
            merged=next(x for x in blocks if x.row_index==2)
            self.assertEqual(merged.structure_status,"ambiguous")
            self.assertIn("horizontal_merge",merged.structure_warnings)
            markdown,_=save_extracted_text(root/"out",source,"P",blocks)
            doc=extract_document_intelligence(
                markdown.read_text(encoding="utf-8"),
                project="P",source_file="merged.docx",document_type=DocumentType.PRICE_LIST,
            )
        self.assertEqual(doc["facts"],[])

    def test_repeated_header_is_preserved_but_not_treated_as_data(self):
        body = '''
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>Unit</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Starting Price</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>A101</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 150,000</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>Unit</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Starting Price</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>B202</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 220,000</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>'''
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"repeat.docx";make_docx(source,body)
            blocks=extract_text_document(source,"P")
        repeated=next(x for x in blocks if x.row_index==3)
        self.assertEqual(repeated.block_type,"table_repeated_header")
        self.assertIn("repeated_header",repeated.structure_warnings)

    def test_irregular_row_count_is_ambiguous(self):
        body = '''
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>Unit</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Area</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Starting Price</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>A101</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 150,000</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>'''
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"irregular.docx";make_docx(source,body)
            row=next(x for x in extract_text_document(source,"P") if x.row_index==2)
        self.assertEqual(row.structure_status,"ambiguous")
        self.assertIn("irregular_column_count",row.structure_warnings)


    def test_headerless_table_is_not_treated_as_relational_schema(self):
        body = '''
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>A101</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 150,000</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>B202</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 220,000</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>'''
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"headerless.docx";make_docx(source,body)
            blocks=extract_text_document(source,"P")
        self.assertTrue(blocks)
        self.assertTrue(all(x.structure_status=="ambiguous" for x in blocks))
        self.assertTrue(any("ambiguous_or_missing_headers" in x.structure_warnings for x in blocks))

    def test_nested_table_cell_is_ambiguous(self):
        body = '''
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>Unit</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Starting Price</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr>
            <w:tc><w:p><w:r><w:t>A101</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>USD 150,000</w:t></w:r></w:p>
              <w:tbl><w:tr><w:tc><w:p><w:r><w:t>nested note</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
            </w:tc>
          </w:tr>
        </w:tbl>'''
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"nested.docx";make_docx(source,body)
            row=next(x for x in extract_text_document(source,"P") if x.row_index==2)
        self.assertEqual(row.structure_status,"ambiguous")
        self.assertIn("nested_table",row.structure_warnings)

    def test_table_row_provenance_survives_to_canonical_consumer(self):
        body = '''
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>Unit</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Unit Price</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>A101</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 150,000</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>'''
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"canonical.docx";make_docx(source,body)
            blocks=extract_text_document(source,"P")
            markdown,_=save_extracted_text(root/"out",source,"P",blocks)
            doc=extract_document_intelligence(
                markdown.read_text(encoding="utf-8"),
                project="P",source_file="canonical.docx",document_type=DocumentType.PRICE_LIST,
                source_id="src_table",source_sha256="hash_table",
            )
            knowledge=ProjectKnowledge.from_dict({
                "project":{"name":"P","developer":"","location":"","description":""},
                "project_identity":{"project_name":"P","developer_name":"","project_type":"","location":""},
            })
            # Fusion consumes intermediate per-document commercial evidence and
            # resolves it into the authoritative project contract.
            knowledge.commercial_intelligence=doc
            merged,_=fuse_knowledge(
                [(knowledge,DocumentType.PRICE_LIST,Path("canonical.docx"))],
                project_namespace="P",
            )
            consumer=canonical_verified_facts(merged.to_dict(),"P",include_commercial=True)
        price=next(x for x in consumer.values() if x.canonical_path=="commercial.total_unit_price")
        self.assertEqual(price.value,150000)
        self.assertEqual(price.evidence[0]["table_index"],1)
        self.assertEqual(price.evidence[0]["row_index"],2)
        self.assertEqual(price.evidence[0]["source_id"],"src_table")
        self.assertEqual(price.evidence[0]["source_sha256"],"hash_table")

    def test_sidecar_contains_machine_readable_table_coordinates(self):
        body = '''
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>Unit</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Starting Price</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>A101</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>USD 150,000</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>'''
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"sidecar.docx";make_docx(source,body)
            _,sidecar=save_extracted_text(root/"out",source,"P",extract_text_document(source,"P"))
            payload=json.loads(sidecar.read_text(encoding="utf-8"))
        row=next(x for x in payload["blocks"] if x["row_index"]==2)
        self.assertEqual(row["table_index"],1)
        self.assertEqual(row["row_index"],2)
        self.assertEqual(row["headers"],["Unit","Starting Price"])
        self.assertEqual(row["structure_status"],"regular")


if __name__=="__main__":
    unittest.main()
