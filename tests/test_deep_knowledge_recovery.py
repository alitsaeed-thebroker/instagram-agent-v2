from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src.knowledge.evaluator import KnowledgeEvaluator


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeepKnowledgeRecoveryTests(unittest.TestCase):
    def setup_project(self, name="Recovery Project", source_text=""):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        knowledge = root / "output/knowledge" / f"{name}.json"
        knowledge.parent.mkdir(parents=True)
        knowledge.write_text(json.dumps({"project": {"name": name}}), encoding="utf-8")

        source = root / "input" / name / "catalogue.txt"
        source.parent.mkdir(parents=True)
        source.write_text(source_text, encoding="utf-8")

        manifest = root / "output/manifests" / f"{name}-run-manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({
            "project_id": name,
            "source_file_hashes": {str(source): sha256(source)},
        }), encoding="utf-8")
        return temp, root, knowledge, source

    def test_evaluator_is_strictly_read_only(self):
        temp, _, knowledge, _ = self.setup_project(
            source_text="Located on 100 Meter Road near Erbil Airport."
        )
        try:
            before = knowledge.read_bytes()
            before_hash = sha256(knowledge)
            KnowledgeEvaluator().evaluate_file(knowledge)
            KnowledgeEvaluator().evaluate_file(knowledge)
            self.assertEqual(before, knowledge.read_bytes())
            self.assertEqual(before_hash, sha256(knowledge))
        finally:
            temp.cleanup()

    def test_rich_source_empty_canonical_does_not_score_100(self):
        temp, _, knowledge, _ = self.setup_project(
            source_text=(
                "Located on 100 Meter Road near Erbil Airport.\n"
                "Starting price USD 125000 with payment plan.\n"
                "Villa Type A 220 m2 3 bedrooms.\n"
                "Pool gym garden security parking.\n"
            )
        )
        try:
            result = KnowledgeEvaluator().evaluate_file(knowledge)
            self.assertLess(result.source_utilization_score, 100.0)
            self.assertLess(result.project_completeness_score, 100.0)
            self.assertEqual(result.information_density["facts_recovered_by_evaluator"], 0)
        finally:
            temp.cleanup()

    def test_pattern_match_is_candidate_not_recovered_or_verified_side_channel(self):
        temp, _, knowledge, _ = self.setup_project(
            source_text="Starting price USD 125000 with payment plan."
        )
        try:
            result = KnowledgeEvaluator().evaluate_file(knowledge)
            self.assertEqual(result.recovered_atomic_facts, [])
            self.assertTrue(result.recovery_requests)
            self.assertTrue(all(
                item["status"] in {"CANDIDATE", "REVIEW_REQUIRED"}
                for item in result.recovery_requests
            ))
            self.assertTrue(all(
                item["requires_authoritative_pipeline"]
                for item in result.recovery_requests
            ))
        finally:
            temp.cleanup()

    def test_completeness_is_canonical_coverage_not_source_verification(self):
        temp, _, knowledge, _ = self.setup_project(
            source_text=(
                "Located on 100 Meter Road near Erbil Airport.\n"
                "Pool gym spa garden clubhouse security parking.\n"
            )
        )
        try:
            result = KnowledgeEvaluator().evaluate_file(knowledge)
            applicable = result.source_coverage["applicable_categories"]
            scores = result.source_coverage["category_scores"]
            self.assertTrue(applicable)
            self.assertTrue(any(scores[name] == 0.0 for name in applicable))
            self.assertLess(result.project_completeness_score, 100.0)
        finally:
            temp.cleanup()

    def test_generated_outputs_are_not_part_of_recovery_corpus(self):
        temp, root, knowledge, _ = self.setup_project(
            source_text="Recovery Project is a residential development."
        )
        try:
            generated = root / "output/reports/Recovery Project-danger.txt"
            generated.parent.mkdir(parents=True)
            generated.write_text("Starting price USD 999999", encoding="utf-8")
            result = KnowledgeEvaluator().evaluate_file(knowledge)
            docs = {
                fact["provenance"]["original_filename"]
                for fact in result.source_coverage.get("page_coverage", [])
                if "provenance" in fact
            }
            atomic_docs = {
                req["source_document"] for req in result.recovery_requests
            }
            self.assertNotIn(generated.name, atomic_docs)
            self.assertFalse(any("999999" in str(req) for req in result.recovery_requests))
        finally:
            temp.cleanup()

    def test_overlapping_project_name_cannot_cross_contaminate_manifest(self):
        temp, root, knowledge, _ = self.setup_project(
            name="Beverly Hills",
            source_text="Beverly Hills is a residential development."
        )
        try:
            other = root / "input/Beverly Hills Residences/catalogue.txt"
            other.parent.mkdir(parents=True)
            other.write_text("Starting price USD 777777", encoding="utf-8")
            result = KnowledgeEvaluator().evaluate_file(knowledge)
            self.assertFalse(any("777777" in str(req) for req in result.recovery_requests))
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
