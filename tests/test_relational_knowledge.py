from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.knowledge.commercial import extract_document_intelligence, resolve_project_intelligence
from src.knowledge.document_classifier import DocumentType
from src.knowledge.fusion import fuse_knowledge
from src.knowledge.relational import CanonicalIntelligence
from src.knowledge.schema import ProjectKnowledge
from src.knowledge.storage import (
    load_authoritative_department2_intelligence,
    save_project_knowledge,
)


class RelationalKnowledgeTests(unittest.TestCase):
    def test_two_units_with_same_fact_type_do_not_conflict_or_merge(self):
        text = """## Page 1
Unit A101 | 2 bedrooms | 120 sqm | Unit price: USD 150,000
Unit B202 | 3 bedrooms | 180 sqm | Unit price: USD 220,000
"""
        doc = extract_document_intelligence(
            text,
            project="Project A",
            source_file="price-list.pdf",
            document_type=DocumentType.PRICE_LIST,
        )
        result = resolve_project_intelligence([doc], "Project A")
        prices = [
            f for f in result["pricing"]["facts"]
            if f["fact_type"] == "total_unit_price"
        ]
        self.assertEqual(len(prices), 2)
        by_unit = {f["relationship_context"]["unit_id"]: f["value"] for f in prices}
        self.assertEqual(by_unit["A101"], 150000)
        self.assertEqual(by_unit["B202"], 220000)
        self.assertFalse([
            c for c in result["conflicts"]
            if c.get("fact_type") == "total_unit_price"
        ])

    def test_payment_plan_text_does_not_enter_relational_intelligence(self):
        text = """## Page 1
Plan A: 20% down payment. Plan A: 80% at handover.
Plan B: 10% down payment. Plan B: 90% at handover.
"""
        doc = extract_document_intelligence(
            text,
            project="Project A",
            source_file="payment-plan.pdf",
            document_type=DocumentType.PAYMENT_PLAN,
        )
        self.assertEqual(doc["facts"], [])
        result = resolve_project_intelligence([doc], "Project A")
        self.assertEqual(result["payment_plans"], [])
        self.assertEqual(result["payment_plan"]["status"], "not_supported")

    def test_canonical_graph_keeps_legacy_units_as_separate_entities(self):
        left = ProjectKnowledge.from_dict({
            "project": {"name": "Project A", "developer": "", "location": "", "description": ""},
            "units": [
                {"name": "A", "bedrooms": 2, "bathrooms": 2, "area_sqm": 120,
                 "starting_price": 150000, "features": []},
                {"name": "B", "bedrooms": 3, "bathrooms": 3, "area_sqm": 180,
                 "starting_price": 220000, "features": []},
            ],
            "fact_provenance": {
                "units[0]": [{"source_file": "units.pdf", "source_project": "Project A"}],
                "units[1]": [{"source_file": "units.pdf", "source_project": "Project A"}],
            },
        })
        merged, _ = fuse_knowledge(
            [(left, DocumentType.FLOOR_PLANS, Path("units.pdf"))],
            project_namespace="Project A",
        )
        graph = CanonicalIntelligence.from_dict(merged.canonical_intelligence)
        unit_entities = [e for e in graph.entities if e.entity_type == "unit_type"]
        self.assertEqual(len(unit_entities), 2)
        entity_values = {}
        for entity in unit_entities:
            entity_values[entity.label] = {
                f.fact_type: f.value for f in graph.facts if f.entity_id == entity.entity_id
            }
        self.assertEqual(entity_values["A"]["unit.area_sqm"], 120)
        self.assertEqual(entity_values["A"]["unit.starting_price"], 150000)
        self.assertEqual(entity_values["B"]["unit.area_sqm"], 180)
        self.assertEqual(entity_values["B"]["unit.starting_price"], 220000)

    def test_sparse_project_without_location_is_valid(self):
        knowledge = ProjectKnowledge.from_dict({
            "project": {"name": "Sparse Project", "developer": "", "location": "", "description": ""}
        })
        self.assertEqual(knowledge.validate(), [])

    def test_authoritative_loader_rejects_legacy_only_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            knowledge = ProjectKnowledge.from_dict({
                "project": {"name": "Legacy", "developer": "", "location": "", "description": ""}
            })
            save_project_knowledge(knowledge, "legacy.json", root)
            with self.assertRaisesRegex(ValueError, "relational intelligence is unavailable"):
                load_authoritative_department2_intelligence("legacy.json", root)

    def test_verified_relational_fact_requires_provenance(self):
        data = {
            "project_namespace": "Project A",
            "contract_role": "authoritative_department2_relational_intelligence",
            "schema_version": "2.0.0",
            "entities": [{
                "entity_id": "project_x", "entity_type": "project",
                "project_namespace": "Project A", "label": "Project A",
                "parent_entity_id": None, "attributes": {},
            }],
            "facts": [{
                "fact_id": "fact_x", "entity_id": "project_x",
                "fact_type": "project.location", "value": "Somewhere",
                "unit": None, "currency": None, "state": "VERIFIED",
                "confidence": 1.0, "authority": 90,
                "marketing_eligible": True, "provenance": [],
                "relationship_context": {}, "effective_date": None, "conflicts": [],
            }],
            "conflicts": [], "unknowns": [], "metadata": {},
        }
        with self.assertRaisesRegex(ValueError, "has no provenance"):
            CanonicalIntelligence.from_dict(data)


if __name__ == "__main__":
    unittest.main()
