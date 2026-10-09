from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.department1.pipeline import (
    Department1Config,
    Department1Error,
    Department1Pipeline,
)


class _Responses:
    def __init__(self, data):
        self.data = data
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        stage_line = next(
            line
            for line in kwargs["input"][0]["content"][0]["text"].splitlines()
            if line.startswith("DEPARTMENT 1 STAGE:")
        )
        stage = stage_line.split(":", 1)[1].strip()
        project_line = next(
            line
            for line in kwargs["input"][0]["content"][0]["text"].splitlines()
            if line.startswith("ACTIVE PROJECT:")
        )
        project = project_line.split(":", 1)[1].strip()
        payload = {
            "project": project,
            "stage": stage,
            "summary": "complete",
            "data": self.data,
            "unknowns": [],
            "warnings": [],
        }

        class Response:
            output_text = json.dumps(payload)

        return Response()


class _Client:
    def __init__(self, data):
        self.responses = _Responses(data)


class Department1ResponseSchemaPhase103Tests(unittest.TestCase):
    def _pipeline(self, root: Path, data):
        project = root / "input" / "Beverly Hills"
        project.mkdir(parents=True)
        (project / "notes.txt").write_text("Beverly Hills", encoding="utf-8")
        client = _Client(data)
        pipeline = Department1Pipeline(
            project,
            output_root=root / "output",
            config=Department1Config(allow_external_ai=True),
            client=client,
        )
        return pipeline, client

    def test_live_request_uses_json_object_mode(self):
        with tempfile.TemporaryDirectory() as td:
            pipeline, client = self._pipeline(Path(td), {"facts": []})
            pipeline._ai_json(
                stage="UNDERSTAND", instructions="UNDERSTAND", evidence={}
            )
            self.assertEqual(
                client.responses.last_kwargs["text"]["format"],
                {"type": "json_object"},
            )

    def test_dynamic_data_remains_a_dictionary(self):
        with tempfile.TemporaryDirectory() as td:
            pipeline, _ = self._pipeline(
                Path(td), {"facts": [{"name": "project"}]}
            )
            result = pipeline._ai_json(
                stage="UNDERSTAND", instructions="UNDERSTAND", evidence={}
            )
            self.assertEqual(result["data"]["facts"][0]["name"], "project")

    def test_non_object_data_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            pipeline, _ = self._pipeline(Path(td), "not-an-object")
            with self.assertRaises(Department1Error):
                pipeline._ai_json(
                    stage="UNDERSTAND", instructions="UNDERSTAND", evidence={}
                )


if __name__ == "__main__":
    unittest.main()
