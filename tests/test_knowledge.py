"""Tests for the knowledge model and its JSON storage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.knowledge.schema import (
    Architecture,
    Branding,
    Investment,
    Marketing,
    Pricing,
    ProjectDetails,
    ProjectKnowledge,
    Unit,
)
from src.knowledge.storage import load_project_knowledge, save_project_knowledge


def sample_knowledge() -> ProjectKnowledge:
    return ProjectKnowledge(
        project=ProjectDetails(name="Palm Gardens", developer="Example Developments", location="Baghdad"),
        branding=Branding(tagline="Live in bloom", key_messages=["Private gardens"]),
        pricing=Pricing(currency="USD", starting_price=125000),
        units=[Unit(name="Two-bedroom apartment", bedrooms=2, area_sqm=108.5)],
        amenities=["Pool", "Gym"],
        architecture=Architecture(style="Contemporary"),
        investment=Investment(highlights=["Growing district"]),
        marketing=Marketing(target_audience=["Families"]),
    )


class ProjectKnowledgeTests(unittest.TestCase):
    def test_serialization(self) -> None:
        data = sample_knowledge().to_dict()

        self.assertEqual(data["project"]["name"], "Palm Gardens")
        self.assertEqual(data["units"][0]["area_sqm"], 108.5)

    def test_deserialization(self) -> None:
        restored = ProjectKnowledge.from_json(sample_knowledge().to_json())

        self.assertEqual(restored, sample_knowledge())

    def test_validation_reports_missing_required_fields(self) -> None:
        errors = ProjectKnowledge().validate()

        self.assertIn("project.name is required", errors)
        self.assertNotIn("project.location is required", errors)

    def test_save_and_load(self) -> None:
        knowledge = sample_knowledge()
        with tempfile.TemporaryDirectory() as directory:
            path = save_project_knowledge(knowledge, "palm-gardens", Path(directory))
            restored = load_project_knowledge("palm-gardens.json", Path(directory))

        self.assertEqual(path.name, "palm-gardens.json")
        self.assertEqual(restored, knowledge)


if __name__ == "__main__":
    unittest.main()
