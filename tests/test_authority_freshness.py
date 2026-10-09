from __future__ import annotations

from pathlib import Path
import unittest

from src.knowledge.authority import explicit_freshness, compare_candidates, source_authority
from src.knowledge.commercial import (
    document_date,
    extract_document_intelligence,
    resolve_project_intelligence,
)
from src.knowledge.document_classifier import DocumentType
from src.knowledge.fusion import fuse_knowledge
from src.knowledge.schema import ProjectDetails, ProjectKnowledge


class AuthorityFreshnessTests(unittest.TestCase):
    def test_completion_date_is_not_document_freshness(self):
        text = """## Page 1
Project completion date: 2028-12-31
Starting from USD 150,000
"""
        self.assertIsNone(document_date("price-list.pdf", text))
        freshness = explicit_freshness("price-list.pdf", text)
        self.assertFalse(freshness.comparable)

    def test_explicit_effective_date_is_freshness(self):
        text = """## Page 1
Effective Date: 2026-08-01
Starting from USD 150,000
"""
        freshness = explicit_freshness("price-list.pdf", text)
        self.assertEqual(freshness.effective_date, "2026-08-01")
        self.assertEqual(freshness.basis, "explicit_document_date")

    def test_newer_equal_authority_commercial_source_supersedes_older(self):
        older = extract_document_intelligence(
            "## Page 1\nEffective Date: 2026-07-01\nStarting from USD 150,000",
            project="P", source_file="prices-old.pdf",
            document_type=DocumentType.PRICE_LIST,
        )
        newer = extract_document_intelligence(
            "## Page 1\nEffective Date: 2026-08-01\nStarting from USD 160,000",
            project="P", source_file="prices-new.pdf",
            document_type=DocumentType.PRICE_LIST,
        )
        result = resolve_project_intelligence([older, newer], "P")
        fact = next(f for f in result["pricing"]["facts"] if f["fact_type"] == "starting_price")
        self.assertEqual(fact["value"], 160000)
        resolution = next(c for c in result["conflicts"] if c["fact_type"] == "starting_price")
        self.assertEqual(resolution["status"], "RESOLVED")
        self.assertEqual(resolution["resolution_reason"], "newer_explicit_freshness")
        self.assertEqual(len(resolution["supersession"]), 1)

    def test_dated_source_does_not_automatically_beat_undated_equal_authority(self):
        dated = extract_document_intelligence(
            "## Page 1\nEffective Date: 2026-08-01\nStarting from USD 160,000",
            project="P", source_file="dated.pdf",
            document_type=DocumentType.PRICE_LIST,
        )
        undated = extract_document_intelligence(
            "## Page 1\nStarting from USD 150,000",
            project="P", source_file="undated.pdf",
            document_type=DocumentType.PRICE_LIST,
        )
        result = resolve_project_intelligence([dated, undated], "P")
        self.assertEqual(result["pricing"]["status"], "conflicting")
        self.assertEqual(result["pricing"]["facts"], [])
        resolution = next(c for c in result["conflicts"] if c["fact_type"] == "starting_price")
        self.assertEqual(resolution["status"], "CONFLICTING")
        self.assertEqual(
            resolution["resolution_reason"],
            "equal_authority_without_comparable_explicit_freshness",
        )

    def test_higher_authority_beats_newer_lower_authority(self):
        official = extract_document_intelligence(
            "## Page 1\nEffective Date: 2026-07-01\nStarting from USD 150,000",
            project="P", source_file="official-price-list.pdf",
            document_type=DocumentType.PRICE_LIST,
        )
        note = extract_document_intelligence(
            "## Lines 1-1\nEffective Date: 2026-08-01\nStarting from USD 175,000",
            project="P", source_file="project-notes.txt",
            document_type=DocumentType.PROJECT_NOTES,
        )
        result = resolve_project_intelligence([official, note], "P")
        fact = next(f for f in result["pricing"]["facts"] if f["fact_type"] == "starting_price")
        self.assertEqual(fact["value"], 150000)
        resolution = next(c for c in result["conflicts"] if c["fact_type"] == "starting_price")
        self.assertEqual(resolution["resolution_reason"], "higher_source_authority")

    def test_filename_revision_does_not_change_authority(self):
        self.assertEqual(
            source_authority(DocumentType.PRICE_LIST, "prices-v9.pdf"),
            source_authority(DocumentType.PRICE_LIST, "prices-v1.pdf"),
        )

    def test_generic_equal_authority_conflict_fails_closed_and_preserves_candidates(self):
        a = ProjectKnowledge(project=ProjectDetails(name="P", location="Alpha"))
        b = ProjectKnowledge(project=ProjectDetails(name="P", location="Beta"))
        merged, conflicts = fuse_knowledge([
            (a, DocumentType.CATALOGUE, Path("A.pdf")),
            (b, DocumentType.CATALOGUE, Path("B.pdf")),
        ], project_namespace="P")
        self.assertEqual(merged.project.location, "")
        conflict = next(x for x in conflicts if x.get("fact_key") == "project.location")
        self.assertEqual(conflict["status"], "CONFLICTING")
        self.assertEqual(len(conflict["candidates"]), 2)
        self.assertIsNone(conflict["selected_candidate_id"])

    def test_resolution_comparison_requires_comparable_freshness(self):
        left = {"authority": 90, "freshness": {"effective_date": "2026-08-01", "basis": "explicit_document_date"}}
        right = {"authority": 90, "freshness": {"basis": "unknown"}}
        result, reason = compare_candidates(left, right)
        self.assertEqual(result, 0)
        self.assertEqual(reason, "equal_authority_without_comparable_explicit_freshness")


if __name__ == "__main__":
    unittest.main()
