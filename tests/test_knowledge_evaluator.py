"""Tests for offline knowledge quality evaluation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.knowledge.evaluator import EVALUATOR_VERSION, KnowledgeEvaluator


def complete_data() -> dict:
    return {
        "project": {"name": "Example", "developer": "Builder", "location": "City", "description": "A project"},
        "pricing": {"currency": "USD", "starting_price": 100000, "payment_plan": "Installments"},
        "units": [{"name": "Villa", "bedrooms": 3, "bathrooms": 3, "area_sqm": 200}],
        "amenities": ["Pool", "Gym", "Park"],
        "architecture": {"style": "Modern", "materials": ["Stone", "Glass"], "design_features": ["Windows", "Open plan"]},
        "marketing": {"target_audience": ["Families", "Investors"], "selling_points": ["Space", "Location"]},
    }


class KnowledgeEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = KnowledgeEvaluator()

    def test_complete_json_scores_full(self) -> None:
        evaluation = self.evaluator.evaluate_data(complete_data())

        self.assertEqual(evaluation.json_validity["score"], 10)
        self.assertEqual(evaluation.evaluator_version, EVALUATOR_VERSION)
        self.assertEqual(evaluation.to_dict()["evaluator_version"], EVALUATOR_VERSION)
        self.assertEqual(evaluation.overall_score, 100.0)
        self.assertEqual(evaluation.completeness_percentage, 100.0)

    def test_report_includes_evaluator_version(self) -> None:
        evaluation = self.evaluator.evaluate_data(complete_data())

        report = self.evaluator.format_report(evaluation)

        self.assertIn(EVALUATOR_VERSION, report)

    def test_incomplete_json_reports_missing_fields(self) -> None:
        data = complete_data()
        data["pricing"]["payment_plan"] = ""
        data["amenities"] = []
        evaluation = self.evaluator.evaluate_data(data)

        self.assertNotIn("pricing.payment_plan", evaluation.missing_fields)
        self.assertIn("amenities", evaluation.missing_fields)
        self.assertLess(evaluation.overall_score, 100)

    def test_invalid_json_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("{not valid json", encoding="utf-8")
            evaluation = self.evaluator.evaluate_file(path)

        self.assertFalse(evaluation.json_validity["valid"])
        self.assertEqual(evaluation.overall_score, 0.0)

    def test_missing_fields_are_counted(self) -> None:
        evaluation = self.evaluator.evaluate_data({"project": {"name": "Example"}})

        self.assertIn("project.developer", evaluation.missing_fields)
        self.assertIn("pricing.currency", evaluation.missing_fields)

    def test_placeholders_and_whitespace_do_not_receive_credit(self) -> None:
        data = complete_data()
        data["project"]["developer"] = "  Unknown  "
        data["pricing"]["starting_price"] = 0
        data["architecture"]["materials"] = [" ", "N/A"]
        evaluation = self.evaluator.evaluate_data(data)

        self.assertIn("project.developer", evaluation.missing_fields)
        self.assertIn("pricing.starting_price", evaluation.missing_fields)
        self.assertIn("architecture.materials", evaluation.missing_fields)
        self.assertLess(evaluation.category_scores["architecture"], 100)

    def test_lists_require_meaningful_entries(self) -> None:
        data = complete_data()
        data["amenities"] = [" ", "unknown", None]
        data["marketing"]["target_audience"] = ["Families", "N/A"]
        evaluation = self.evaluator.evaluate_data(data)

        self.assertIn("amenities", evaluation.missing_fields)
        self.assertLess(evaluation.category_scores["marketing"], 100)
