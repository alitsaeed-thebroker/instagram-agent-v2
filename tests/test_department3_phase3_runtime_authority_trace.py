import tempfile
import unittest
from pathlib import Path

from tools.department3_phase3_runtime_authority_trace import (
    RuntimeAuthorityTracer,
    aggregate_calls,
    classify_runtime_authority,
)


class Department3Phase3RuntimeTraceTests(unittest.TestCase):
    def test_category_marks_canonical_and_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracer = RuntimeAuthorityTracer(root)
            self.assertEqual(
                tracer.category("src/creative/visual_art_director.py"),
                "CANONICAL_D3",
            )
            self.assertEqual(
                tracer.category("src/ai/agents/content_planner.py"),
                "LEGACY_CANDIDATE",
            )

    def test_nonexecuted_legacy_is_not_called_a_defect(self):
        summary = {"per_file": {}, "edges": []}
        io = {"authoritative_write_events": [], "writers": {}, "readers": {}}
        result = classify_runtime_authority(summary, io)
        self.assertEqual(
            result["src/ai/agents/content_planner.py"]["status"],
            "NOT_EXECUTED_IN_TRACED_SUITE",
        )
        self.assertEqual(
            result["src/ai/agents/content_planner.py"]["severity"],
            "INFO",
        )


if __name__ == "__main__":
    unittest.main()
