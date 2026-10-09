\
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.department1.pipeline import Department1Config, Department1Pipeline


class FakeResponses:
    def create(self, **kwargs):
        stage = "UNKNOWN"
        instructions = kwargs.get("instructions", "")
        for candidate in ("UNDERSTAND", "ANALYZE", "CLASSIFY", "EXTRACT"):
            if candidate in instructions:
                stage = candidate
                break

        user_text = kwargs["input"][0]["content"][0]["text"]
        project_line = next(
            line for line in user_text.splitlines()
            if line.startswith("ACTIVE PROJECT:")
        )
        project = project_line.split(":", 1)[1].strip()

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


class Department1PipelineTests(unittest.TestCase):
    def test_full_cognitive_chain_and_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            project = base / "input" / "Avenue Square"
            project.mkdir(parents=True)
            (project / "notes.txt").write_text(
                "Avenue Square\nPremium office buildings\nErbil Avenue",
                encoding="utf-8",
            )

            out = base / "output" / "department1"
            pipe = Department1Pipeline(
                project,
                output_root=out,
                config=Department1Config(allow_external_ai=True),
                client=FakeClient(),
            )
            handoff = pipe.run()

            self.assertEqual(handoff["project"], "Avenue Square")
            self.assertEqual(
                handoff["pipeline_completed"],
                ["INPUT", "READ", "UNDERSTAND", "ANALYZE", "CLASSIFY", "EXTRACT"],
            )
            self.assertTrue(
                (pipe.output_dir / "department2-handoff.json").exists()
            )

    def test_project_folder_is_authoritative_namespace(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            project = base / "input" / "Avenue Square"
            project.mkdir(parents=True)
            (project / "bad-title.txt").write_text(
                "2 3\nThis text must never replace the project namespace.",
                encoding="utf-8",
            )

            pipe = Department1Pipeline(
                project,
                output_root=base / "out",
                config=Department1Config(allow_external_ai=True),
                client=FakeClient(),
            )
            manifest = pipe.input_stage()
            self.assertEqual(manifest["project"], "Avenue Square")

    def test_global_brand_subfolder_is_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            project = base / "input" / "Project A"
            project.mkdir(parents=True)
            (project / "project.txt").write_text("Project A", encoding="utf-8")
            brand = project / "brand"
            brand.mkdir()
            (brand / "logo.png").write_bytes(b"not-a-real-image")

            pipe = Department1Pipeline(
                project,
                output_root=base / "out",
                config=Department1Config(allow_external_ai=True),
                client=FakeClient(),
            )
            manifest = pipe.input_stage()
            paths = [f["relative_path"] for f in manifest["files"]]
            self.assertEqual(paths, ["project.txt"])


if __name__ == "__main__":
    unittest.main()
