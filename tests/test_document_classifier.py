"""Tests for deterministic, confidence-ranked document classification."""

from __future__ import annotations

import unittest

from src.knowledge.document_classifier import DOCUMENT_TYPE_REGISTRY, DocumentClassifier, DocumentType, ClassificationResult


class DocumentClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = DocumentClassifier(ai_classifier=lambda *_: None)

    def test_every_registered_type_can_be_detected_from_content(self) -> None:
        for definition in DOCUMENT_TYPE_REGISTRY:
            with self.subTest(document_type=definition.document_type):
                phrase = definition.content_phrases[0]
                result = self.classifier.classify("random-7f2a.pdf", f"{phrase}\n{phrase}\nSupporting project information")
                self.assertEqual(result.document_type, definition.document_type)
                self.assertGreaterEqual(result.confidence, 0.70)
                self.assertEqual(result.classification_method, "content")

    def test_title_match_has_second_priority(self) -> None:
        result = self.classifier.classify("document.pdf", "# Extracted text: document.pdf\n\n## Page 1\n\nPayment Plan\n\nTerms")
        self.assertEqual(result.document_type, DocumentType.PAYMENT_PLAN)
        self.assertGreaterEqual(result.confidence, 0.70)
        self.assertEqual(result.classification_method, "content")

    def test_keyword_match_has_third_priority(self) -> None:
        result = self.classifier.classify("document.pdf", "This document describes the site layout and surrounding plots.")
        self.assertEqual(result.document_type, DocumentType.MASTER_PLAN)
        self.assertGreaterEqual(result.confidence, 0.70)
        self.assertEqual(result.classification_method, "content")

    def test_ai_is_not_called_after_deterministic_match(self) -> None:
        calls = []
        classifier = DocumentClassifier(ai_classifier=lambda *_: calls.append(True))
        result = classifier.classify("Catalogue.pdf", "Payment Plan\nDown payment and installment schedule")
        self.assertEqual(result.document_type, DocumentType.PAYMENT_PLAN)
        self.assertEqual(calls, [])

    def test_ai_is_only_fallback_below_seventy_percent(self) -> None:
        ai_result = ClassificationResult(DocumentType.PRESENTATION, 0.82, "ai", "AI fallback classification")
        classifier = DocumentClassifier(ai_classifier=lambda *_: ai_result)
        result = classifier.classify("untitled.pdf", "unclassified source text")
        self.assertEqual(result, ai_result)

    def test_metadata_contains_required_fields(self) -> None:
        metadata = self.classifier.classify("FAQ.pdf", "Frequently asked questions\nQuestions and answers").to_dict()
        self.assertEqual(metadata["document_type"], "FAQ")
        self.assertGreaterEqual(metadata["confidence"], 0.70)
        self.assertIn("evidence", metadata)

    def test_misleading_and_random_filenames_do_not_change_result(self) -> None:
        content = "Price List\nUnit price, total price and currency for every residence"
        a = self.classifier.classify("Payment Plan.pdf", content)
        b = self.classifier.classify("8dd3f0.bin.pdf", content)
        self.assertEqual(a, b)
        self.assertEqual(a.document_type, DocumentType.PRICE_LIST)

    def test_empty_content_is_unknown_even_with_descriptive_filename(self) -> None:
        self.assertEqual(self.classifier.classify("Master Plan.pdf", "").document_type, DocumentType.UNKNOWN)
