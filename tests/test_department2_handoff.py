from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.department1.pipeline import Department1Config, Department1Pipeline, project_storage_key
from src.knowledge.handoff import (
    Department2HandoffError,
    load_department2_handoff,
)


class FakeResponses:
    def create(self, **kwargs):
        stage = next(
            candidate
            for candidate in ("UNDERSTAND", "ANALYZE", "CLASSIFY", "EXTRACT")
            if candidate in kwargs.get("instructions", "")
        )
        user_text = kwargs["input"][0]["content"][0]["text"]
        project = next(
            line.split(":", 1)[1].strip()
            for line in user_text.splitlines()
            if line.startswith("ACTIVE PROJECT:")
        )
        payload = {
            "project": project,
            "stage": stage,
            "summary": f"{stage} complete",
            "data": {"ok": True},
            "unknowns": [],
            "warnings": [],
        }

        class Response:
            output_text = json.dumps(payload)

        return Response()


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


class Department2HandoffTests(unittest.TestCase):
    def _build(self, base: Path):
        project = base / "input" / "Project A"
        project.mkdir(parents=True)
        notes = project / "notes.txt"
        notes.write_text("Project A\nLine two", encoding="utf-8")
        out = base / "output" / "department1"
        handoff = Department1Pipeline(
            project,
            output_root=out,
            config=Department1Config(allow_external_ai=True),
            client=FakeClient(),
        ).run()
        path = out / project_storage_key("Project A") / "department2-handoff.json"
        return project, notes, handoff, path

    def test_loader_preserves_text_line_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            project, _, _, path = self._build(Path(td))
            loaded = load_department2_handoff(
                path, expected_project="Project A", project_root=project
            )
            self.assertEqual(len(loaded.sources), 1)
            blocks = loaded.sources[0].blocks
            self.assertEqual(blocks[0]["provenance"]["locator"]["type"], "line")
            self.assertEqual(blocks[0]["provenance"]["locator"]["start"], 1)
            self.assertEqual(blocks[0]["provenance"]["project"], "Project A")
            self.assertIn("## Lines 1-1", loaded.sources[0].markdown())

    def test_tampered_handoff_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            project, _, _, path = self._build(Path(td))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["project"] = "Project B"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(Department2HandoffError):
                load_department2_handoff(
                    path, expected_project="Project A", project_root=project
                )

    def test_source_change_invalidates_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            project, notes, _, path = self._build(Path(td))
            notes.write_text("Project A\nCHANGED", encoding="utf-8")
            with self.assertRaises(Department2HandoffError):
                load_department2_handoff(
                    path, expected_project="Project A", project_root=project
                )

    def test_cross_project_evidence_fails_closed_even_with_recomputed_hash(self):
        with tempfile.TemporaryDirectory() as td:
            project, _, _, path = self._build(Path(td))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["sources"][0]["project"] = "Project B"
            payload.pop("handoff_sha256")
            import hashlib
            payload["handoff_sha256"] = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(Department2HandoffError):
                load_department2_handoff(
                    path, expected_project="Project A", project_root=project
                )

    def test_explicit_source_paths_prevent_neighbor_project_ingestion(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "input"
            root.mkdir()
            a = root / "a.txt"
            b = root / "b.txt"
            a.write_text("A", encoding="utf-8")
            b.write_text("B", encoding="utf-8")
            pipe = Department1Pipeline(
                root,
                project_name="Project A",
                output_root=base / "out",
                source_paths=[a],
                config=Department1Config(allow_external_ai=True),
                client=FakeClient(),
            )
            manifest = pipe.input_stage()
            self.assertEqual([f["relative_path"] for f in manifest["files"]], ["a.txt"])


if __name__ == "__main__":
    unittest.main()
