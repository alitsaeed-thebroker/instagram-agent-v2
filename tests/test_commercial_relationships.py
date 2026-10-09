from __future__ import annotations

import unittest

from src.knowledge.commercial import (
    extract_document_intelligence,
    resolve_project_intelligence,
    verified_fact,
)
from src.knowledge.document_classifier import DocumentType
from src.knowledge.fusion import fuse_knowledge
from src.knowledge.relational import CanonicalIntelligence
from src.knowledge.schema import ProjectKnowledge


def extract(text: str, kind: DocumentType = DocumentType.PRICE_LIST) -> dict:
    return extract_document_intelligence(
        f"## Page 1\n{text}",
        project="P",
        source_file="official.pdf",
        document_type=kind,
        classification_confidence=.99,
        source_id="src_1",
        source_sha256="abc",
    )


class CommercialRelationshipHardeningTests(unittest.TestCase):
    def test_unscoped_exact_unit_price_is_not_marketing_verified(self):
        doc = extract("Unit price: USD 150,000")
        fact = next(x for x in doc["facts"] if x["fact_type"] == "total_unit_price")
        self.assertEqual(fact["relationship_status"], "ambiguous")
        self.assertFalse(verified_fact(fact, "P"))

        result = resolve_project_intelligence([doc], "P")
        self.assertEqual(result["pricing"]["status"], "uncertain")
        self.assertIn(
            "ambiguous_unit_scoped_commercial_fact",
            result["relationship_diagnostics"]["warnings"],
        )

    def test_unit_price_with_unit_id_and_area_is_relationship_safe(self):
        doc = extract("Unit A101 | 120 sqm | Unit price: USD 150,000")
        fact = next(x for x in doc["facts"] if x["fact_type"] == "total_unit_price")
        self.assertEqual(fact["relationship_status"], "scoped")
        self.assertEqual(fact["relationship_context"]["unit_id"], "A101")
        self.assertEqual(fact["relationship_context"]["area_sqm"], 120.0)
        self.assertTrue(verified_fact(fact, "P"))

    def test_same_unit_different_price_facts_conflict_inside_same_scope(self):
        a = extract_document_intelligence(
            "## Page 1\nUnit A101 | 120 sqm | Unit price: USD 150,000",
            project="P", source_file="A.pdf", document_type=DocumentType.PRICE_LIST,
            source_id="a", source_sha256="a",
        )
        b = extract_document_intelligence(
            "## Page 1\nUnit A101 | 120 sqm | Unit price: USD 160,000",
            project="P", source_file="B.pdf", document_type=DocumentType.PRICE_LIST,
            source_id="b", source_sha256="b",
        )
        result = resolve_project_intelligence([a, b], "P")
        self.assertEqual(result["pricing"]["status"], "conflicting")
        conflict = next(c for c in result["conflicts"] if c["fact_type"] == "total_unit_price")
        self.assertEqual(conflict["status"], "CONFLICTING")

    def test_different_units_never_conflict(self):
        a = extract_document_intelligence(
            "## Page 1\nUnit A101 | 120 sqm | Unit price: USD 150,000",
            project="P", source_file="A.pdf", document_type=DocumentType.PRICE_LIST,
            source_id="a", source_sha256="a",
        )
        b = extract_document_intelligence(
            "## Page 1\nUnit B202 | 180 sqm | Unit price: USD 160,000",
            project="P", source_file="B.pdf", document_type=DocumentType.PRICE_LIST,
            source_id="b", source_sha256="b",
        )
        result = resolve_project_intelligence([a, b], "P")
        prices = [x for x in result["pricing"]["facts"] if x["fact_type"] == "total_unit_price"]
        self.assertEqual({x["relationship_context"]["unit_id"] for x in prices}, {"A101", "B202"})
        self.assertFalse([c for c in result["conflicts"] if c["fact_type"] == "total_unit_price"])

    def test_payment_plan_percentages_are_not_extracted(self):
        doc = extract_document_intelligence(
            """## Page 1
Plan A: 50% first installment. Plan A: 50% first installment.""",
            project="P", source_file="plan.pdf", document_type=DocumentType.PAYMENT_PLAN,
            source_id="p", source_sha256="p",
        )
        self.assertEqual(doc["facts"], [])
        result = resolve_project_intelligence([doc], "P")
        self.assertEqual(result["payment_plan"]["status"], "not_supported")
        self.assertEqual(result["payment_plans"], [])


    def test_invalid_payment_percentages_are_ignored_not_modeled(self):
        doc = extract_document_intelligence(
            """## Page 1
Plan A: 120% down payment.""",
            project="P", source_file="plan.pdf", document_type=DocumentType.PAYMENT_PLAN,
            source_id="p", source_sha256="p",
        )
        self.assertEqual(doc["facts"], [])
        result = resolve_project_intelligence([doc], "P")
        self.assertEqual(result["payment_plan"]["status"], "not_supported")


    def test_named_and_unscoped_payment_terms_are_both_ignored(self):
        doc = extract_document_intelligence(
            """## Page 1
Plan A: 20% down payment.
80% at handover.""",
            project="P", source_file="plan.pdf", document_type=DocumentType.PAYMENT_PLAN,
            source_id="p", source_sha256="p",
        )
        self.assertEqual(doc["facts"], [])
        self.assertEqual(resolve_project_intelligence([doc], "P")["payment_plans"], [])


    def test_multiple_named_payment_plans_are_not_extracted(self):
        doc = extract_document_intelligence(
            """## Page 1
Plan A: 20% down payment. Plan A: 80% at handover.
Plan B: 10% down payment. Plan B: 90% at handover.""",
            project="P", source_file="plan.pdf", document_type=DocumentType.PAYMENT_PLAN,
            source_id="p", source_sha256="p",
        )
        self.assertEqual(doc["facts"], [])
        result = resolve_project_intelligence([doc], "P")
        self.assertEqual(result["payment_plans"], [])
        self.assertEqual(result["commercial_terms"], [])


    def test_relational_graph_contains_no_payment_plan_entities(self):
        knowledge = ProjectKnowledge.from_dict({
            "project": {"name": "P", "developer": "", "location": "", "description": ""},
            "project_identity": {
                "project_name": "P", "developer_name": "", "project_type": "", "location": ""
            },
        })
        commercial_doc = extract_document_intelligence(
            """## Page 1
Plan A: 20% down payment. Plan A: 80% at handover.""",
            project="P", source_file="plan.pdf", document_type=DocumentType.PAYMENT_PLAN,
            source_id="p", source_sha256="p",
        )
        knowledge.commercial_intelligence = commercial_doc
        merged, _ = fuse_knowledge(
            [(knowledge, DocumentType.PAYMENT_PLAN, __import__("pathlib").Path("plan.pdf"))],
            project_namespace="P",
        )
        graph = CanonicalIntelligence.from_dict(merged.canonical_intelligence)
        self.assertFalse([e for e in graph.entities if e.entity_type == "payment_plan"])
        self.assertFalse([f for f in graph.facts if "payment" in f.fact_type or "installment" in f.fact_type])


    def test_pricing_relationship_groups_do_not_mix_unit_scopes(self):
        doc = extract("""Unit A101 | 120 sqm | Unit price: USD 150,000
Unit B202 | 180 sqm | Unit price: USD 220,000""")
        result = resolve_project_intelligence([doc], "P")
        groups = result["pricing"]["relationship_groups"]
        unit_groups = [g for g in groups if g["relationship_context"].get("unit_id")]
        self.assertEqual(len(unit_groups), 2)
        self.assertEqual(
            {g["relationship_context"]["unit_id"] for g in unit_groups},
            {"A101", "B202"},
        )


if __name__ == "__main__":
    unittest.main()
