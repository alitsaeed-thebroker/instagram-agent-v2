"""Adversarial regression coverage for nested Department 2 knowledge fusion."""

from pathlib import Path
import unittest

from src.knowledge.document_classifier import DocumentType
from src.knowledge.fusion import KnowledgeFusionError, _merge_value, fuse_knowledge
from src.knowledge.schema import ProjectDetails, ProjectIdentity, ProjectKnowledge


def merge_raw(target: dict, candidate: dict) -> tuple[dict, list[str]]:
    conflicts: list[str] = []
    _merge_value(target, candidate, (), DocumentType.CATALOGUE, {}, conflicts, "Catalogue.json")
    return target, conflicts


class NestedFusionRegressionTests(unittest.TestCase):
    def test_empty_target_accepts_nested_dictionary(self) -> None:
        target, _ = merge_raw({}, {"project_identity": {"project_name": "Beverly Hills"}})
        self.assertEqual(target, {"project_identity": {"project_name": "Beverly Hills"}})

    def test_multiple_levels_of_nesting(self) -> None:
        target, _ = merge_raw({}, {"one": {"two": {"three": "value"}}})
        self.assertEqual(target["one"]["two"]["three"], "value")

    def test_documents_contribute_under_same_nested_parent(self) -> None:
        target, conflicts = merge_raw({}, {"parent": {"left": "a"}})
        _merge_value(target, {"parent": {"right": "b"}}, (), DocumentType.CATALOGUE, {}, conflicts, "Second.json")
        self.assertEqual(target["parent"], {"left": "a", "right": "b"})

    def test_nested_conflict_uses_existing_authority_rules(self) -> None:
        target: dict = {}
        priorities: dict[str, int] = {}
        conflicts: list[str] = []
        _merge_value(target, {"pricing": {"starting_price": 100}}, (), DocumentType.CATALOGUE, priorities, conflicts, "Catalogue.json")
        _merge_value(target, {"pricing": {"starting_price": 125}}, (), DocumentType.PRICE_LIST, priorities, conflicts, "Price List.json")
        self.assertEqual(target["pricing"]["starting_price"], 125)
        self.assertEqual(len(conflicts), 1)

    def test_scalar_then_dictionary_collision_fails_closed(self) -> None:
        target, _ = merge_raw({}, {"field": "scalar"})
        with self.assertRaisesRegex(KnowledgeFusionError, "field.*str.*object"):
            merge_raw(target, {"field": {"nested": "value"}})
        self.assertEqual(target["field"], "scalar")

    def test_dictionary_then_scalar_collision_fails_closed(self) -> None:
        target, _ = merge_raw({}, {"field": {"nested": "value"}})
        with self.assertRaisesRegex(KnowledgeFusionError, "field.*object.*str"):
            merge_raw(target, {"field": "scalar"})
        self.assertEqual(target["field"], {"nested": "value"})

    def test_missing_empty_and_null_nested_values_are_ignored(self) -> None:
        target, _ = merge_raw({}, {"outer": {"none": None, "empty": "  "}})
        self.assertEqual(target, {"outer": {}})

    def test_flat_field_fusion_is_unchanged(self) -> None:
        low = ProjectKnowledge(project=ProjectDetails(name="P", location="Old"))
        high = ProjectKnowledge(project=ProjectDetails(name="P", location="New"))
        merged, conflicts = fuse_knowledge([
            (low, DocumentType.PRESENTATION, Path("Presentation.json")),
            (high, DocumentType.CATALOGUE, Path("Catalogue.json")),
        ])
        self.assertEqual(merged.project.location, "New")
        self.assertTrue(any(conflict.get("fact_key") == "project.location" for conflict in conflicts))
        conflict = next(x for x in conflicts if x.get("fact_key") == "project.location")
        self.assertEqual(conflict["status"], "RESOLVED")
        self.assertEqual(conflict["resolution_reason"], "higher_field_authority")
        self.assertEqual(len(conflict["candidates"]), 2)

    def test_literal_dotted_provenance_keys_remain_valid(self) -> None:
        knowledge = ProjectKnowledge(
            project=ProjectDetails(name="Beverly Hills", location="Erbil"),
            project_identity=ProjectIdentity(project_name="Beverly Hills", location="Erbil"),
            fact_provenance={"project_identity.project_name": [{"source_document": "Catalogue.pdf"}]},
        )
        merged, _ = fuse_knowledge([(knowledge, DocumentType.CATALOGUE, Path("Catalogue.json"))])
        self.assertEqual(merged.fact_provenance["project_identity.project_name"][0]["source_document"], "Catalogue.pdf")
        self.assertEqual(merged.project_identity.project_name, "Beverly Hills")

    def test_commercial_intelligence_nested_contract_remains_valid(self) -> None:
        knowledge = ProjectKnowledge(
            project=ProjectDetails(name="P", location="L"),
            project_identity=ProjectIdentity(project_name="P", location="L"),
            commercial_intelligence={
                "project": "P", "source_file": "Price.pdf", "authority": 90,
                "facts": [], "marketing_claims": [],
            },
        )
        merged, _ = fuse_knowledge([(knowledge, DocumentType.PRICE_LIST, Path("Price.pdf"))])
        self.assertEqual(merged.commercial_intelligence["contract_role"], "authoritative_project_intelligence")
        self.assertEqual(merged.commercial_intelligence["pricing"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
