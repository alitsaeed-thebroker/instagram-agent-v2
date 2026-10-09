"""TXT/DOCX extraction must preserve content and block provenance."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import zipfile

from src.core.text_document_reader import extract_text_document, save_extracted_text


class TextDocumentReaderTests(unittest.TestCase):
    def test_txt_blocks_retain_filename_project_and_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "project-notes.txt"
            source.write_text("Pool and gym\nOpen daily\n\nNear the park\n", encoding="utf-8")
            blocks = extract_text_document(source, "Project A")
            markdown, provenance = save_extracted_text(root / "out", source, "Project A", blocks)
            payload = json.loads(provenance.read_text(encoding="utf-8"))
            markdown_text = markdown.read_text(encoding="utf-8")
        self.assertEqual([block.location for block in blocks], ["lines 1-2", "line 4"])
        self.assertIn("Pool and gym", markdown_text)
        self.assertEqual(payload["blocks"][0]["original_filename"], "project-notes.txt")
        self.assertEqual(payload["blocks"][0]["project"], "Project A")

    def test_docx_paragraphs_are_extracted_with_provenance(self) -> None:
        xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body><w:p><w:r><w:t>Starting price: $250,000</w:t></w:r></w:p>
          <w:p><w:r><w:t>Payment plan available</w:t></w:r></w:p></w:body>
        </w:document>'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pricing.docx"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("word/document.xml", xml)
            blocks = extract_text_document(source, "Project B")
        self.assertEqual([block.text for block in blocks], ["Starting price: $250,000", "Payment plan available"])
        self.assertEqual([block.location for block in blocks], ["paragraph 1", "paragraph 2"])
        self.assertTrue(all(block.original_filename == "pricing.docx" for block in blocks))
        self.assertTrue(all(block.project == "Project B" for block in blocks))


if __name__ == "__main__":
    unittest.main()
