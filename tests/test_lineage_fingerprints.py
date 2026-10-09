from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.execution.lineage import (
    artifact_fingerprint,
    attach_lineage,
    canonical_graph_fingerprint,
    require_lineage,
    validate_lineage,
)
from src.execution.stages import StageCache


def knowledge(project: str="P", value: str="Project P") -> dict:
    return {
        "canonical_intelligence":{
            "project_namespace":project,
            "schema_version":"2.0.0",
            "contract_role":"authoritative_department2_relational_intelligence",
            "entities":[{"entity_id":"project_p","entity_type":"project","project_namespace":project,"label":value,"parent_entity_id":None,"attributes":{}}],
            "facts":[{"fact_id":"fact_name","entity_id":"project_p","fact_type":"project.project_name","value":value,"unit":None,"currency":None,
                      "state":"VERIFIED","confidence":1.0,"authority":90,"marketing_eligible":True,
                      "provenance":[{"evidence_id":"ev1","source_project":project,"source_file":"a.pdf","source_document":"a.pdf","page":1,"source_text":value,"extraction_method":"test"}],
                      "relationship_context":{"project_namespace":project},"effective_date":None,"conflicts":[]}],
            "conflicts":[],"unknowns":[],"metadata":{},
        }
    }


class LineageFingerprintTests(unittest.TestCase):
    def test_canonical_fingerprint_changes_when_fact_changes(self):
        first=canonical_graph_fingerprint(knowledge(value="Alpha"))
        second=canonical_graph_fingerprint(knowledge(value="Beta"))
        self.assertNotEqual(first,second)

    def test_volatile_timestamps_do_not_change_artifact_fingerprint(self):
        a={"project_id":"P","value":1,"created_at":"2026-01-01T00:00:00Z"}
        b={"project_id":"P","value":1,"created_at":"2030-01-01T00:00:00Z"}
        self.assertEqual(artifact_fingerprint(a),artifact_fingerprint(b))

    def test_raw_artifact_mutation_is_detected(self):
        d2=canonical_graph_fingerprint(knowledge())
        payload=attach_lineage({"project_id":"P","items":[1]},stage="x",canonical_fingerprint=d2)
        payload["items"].append(2)
        valid,reason=validate_lineage(payload,expected_stage="x",canonical_fingerprint=d2)
        self.assertFalse(valid);self.assertEqual(reason,"artifact fingerprint mismatch")

    def test_stale_canonical_ancestry_is_rejected_even_if_artifact_is_untouched(self):
        old=canonical_graph_fingerprint(knowledge(value="Old"))
        current=canonical_graph_fingerprint(knowledge(value="Current"))
        payload=attach_lineage({"project_id":"P"},stage="x",canonical_fingerprint=old)
        with self.assertRaisesRegex(ValueError,"canonical Department 2 fingerprint changed"):
            require_lineage(payload,expected_stage="x",canonical_fingerprint=current)

    def test_parent_replacement_is_detected(self):
        d2=canonical_graph_fingerprint(knowledge())
        parent1=attach_lineage({"value":"A"},stage="parent",canonical_fingerprint=d2)
        child=attach_lineage({"value":"child"},stage="child",canonical_fingerprint=d2,
                             parents={"parent":parent1["artifact_fingerprint"]})
        parent2=attach_lineage({"value":"B"},stage="parent",canonical_fingerprint=d2)
        with self.assertRaisesRegex(ValueError,"parent artifact fingerprint changed"):
            require_lineage(child,expected_stage="child",canonical_fingerprint=d2,
                            parents={"parent":parent2["artifact_fingerprint"]})

    def test_stage_cache_key_can_bind_to_canonical_d2_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/"source.txt";source.write_text("x",encoding="utf-8")
            cache=StageCache("P",[source])
            a=cache.expected("knowledge-extraction",[source],canonical_department2_fingerprint="aaa")
            b=cache.expected("knowledge-extraction",[source],canonical_department2_fingerprint="bbb")
            self.assertNotEqual(a["cache_key"],b["cache_key"])
            self.assertEqual(a["canonical_department2_fingerprint"],"aaa")


if __name__=="__main__":
    unittest.main()
