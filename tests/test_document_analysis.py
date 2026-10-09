"""Tests for content-derived document inventory records."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.core.document_analysis import analyze_document
from src.knowledge.document_classifier import ClassificationResult, DocumentType


class DocumentAnalysisTests(unittest.TestCase):
    def test_mixed_language_and_structure_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "misleading-price-list.png"
            Image.new("RGB", (8, 8)).save(path)
            result = ClassificationResult(DocumentType.BROCHURE, 0.9, "content", "Content evidence", ("project overview",), ("Contains marketing text",))
            record = analyze_document(path, "# Project Overview\nمشروع سكني residential project\nA | B | C", result, "Content Project")
        self.assertEqual(record["document_language"], "mixed_arabic_latin")
        self.assertEqual(record["image_count"], 1)
        self.assertEqual(record["classification"], "Brochure")
        self.assertGreaterEqual(record["tables_detected"], 1)

    def test_missing_extracted_content_is_retained_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Catalogue.webp"
            Image.new("RGB", (8, 8)).save(path)
            result = ClassificationResult(DocumentType.UNKNOWN, 0.0, "content", "Insufficient evidence")
            record = analyze_document(path, "", result, "project-candidate-001")
        self.assertEqual(record["text_quality"], "empty")
        self.assertEqual(record["classification"], "Unknown")
        self.assertTrue(record["warnings"])
