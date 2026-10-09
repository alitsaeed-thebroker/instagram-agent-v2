"""Install the Phase 1.0.3 Department 1 dynamic-JSON repair.

Run from the root of ``instagram-agent V2`` after the Phase 1.0.2 schema
repair. The installer backs up the affected files, replaces the brittle
encoded-JSON payload with direct JSON-object mode, enforces the complete stage
contract in Python, and runs focused tests. It makes no API calls.
"""

from __future__ import annotations

import argparse
import codecs
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path


SENTINEL = 'text={"format": {"type": "json_object"}}'
PIPELINE_BACKUP = "pipeline.py.phase1_dynamic_json_backup"
TEST_BACKUP = "test_department1_response_schema_phase102.py.phase102_backup"

OLD_PROMPT = '''                                "OUTPUT CONTRACT: The data field must be a "
                                "JSON-encoded string whose decoded value is a "
                                "JSON object. Preserve unknown or unsupported "
                                "information as unknown; never invent values.\\n\\n"
'''

NEW_PROMPT = '''                                "OUTPUT CONTRACT: Return exactly one JSON object "
                                "with these keys: project, stage, summary, data, "
                                "unknowns, warnings. The data field must be a JSON "
                                "object, not a string. unknowns and warnings must "
                                "be arrays of strings. Preserve unsupported "
                                "information as unknown; never invent values.\\n\\n"
'''

OLD_FORMAT = '''            text={
                "format": {
                    "type": "json_schema",
                    "name": f"department1_{stage.lower()}",
                    "strict": True,
                    "schema": self._stage_schema(stage),
                }
            },
'''

NEW_FORMAT = '''            text={"format": {"type": "json_object"}},
'''

OLD_BOUNDARY = '''        # Strict Structured Outputs requires every schema object to declare
        # additionalProperties=false. Department 1's ontology intentionally
        # evolves, so the strict envelope carries its dynamic data as JSON text
        # and this boundary restores the original dictionary contract.
        data_value = parsed.get("data")
        if isinstance(data_value, str):
            try:
                decoded_data = json.loads(data_value)
            except json.JSONDecodeError as exc:
                raise Department1Error(
                    f"{stage} data field returned invalid encoded JSON: {exc}"
                ) from exc
            if not isinstance(decoded_data, dict):
                raise Department1Error(
                    f"{stage} data field must decode to a JSON object."
                )
            parsed["data"] = decoded_data
        elif not isinstance(data_value, dict):
            # Retain compatibility with injected test/legacy clients that
            # already return a dictionary, while the live strict schema below
            # only permits the encoded-string representation.
            raise Department1Error(f"{stage} data field must be a JSON object.")

        if parsed.get("project") != self.project_name:
            raise Department1Error(
                f"{stage} project identity mismatch: {parsed.get('project')!r}"
            )
        return parsed

    def _stage_schema(self, stage: str) -> dict[str, Any]:
        # OpenAI strict schemas require additionalProperties=false for every
        # object. Keep a closed, stable envelope and carry the evolving
        # real-estate ontology as encoded JSON, decoded at the trust boundary.
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "project": {"type": "string"},
                "stage": {"type": "string", "enum": [stage]},
                "summary": {"type": "string"},
                "data": {"type": "string"},
                "unknowns": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "project", "stage", "summary", "data", "unknowns", "warnings"
            ],
        }
'''

NEW_BOUNDARY = '''        self._validate_stage_payload(stage, parsed)
        return parsed

    def _validate_stage_payload(self, stage: str, parsed: Any) -> None:
        if not isinstance(parsed, dict):
            raise Department1Error(f"{stage} output must be a JSON object.")

        required = {"project", "stage", "summary", "data", "unknowns", "warnings"}
        actual = set(parsed)
        if actual != required:
            missing = sorted(required - actual)
            unexpected = sorted(actual - required)
            raise Department1Error(
                f"{stage} output contract mismatch; missing={missing}, "
                f"unexpected={unexpected}."
            )
        if parsed["project"] != self.project_name:
            raise Department1Error(
                f"{stage} project identity mismatch: {parsed['project']!r}"
            )
        if parsed["stage"] != stage:
            raise Department1Error(
                f"{stage} stage identity mismatch: {parsed['stage']!r}"
            )
        if not isinstance(parsed["summary"], str):
            raise Department1Error(f"{stage} summary must be a string.")
        if not isinstance(parsed["data"], dict):
            raise Department1Error(f"{stage} data field must be a JSON object.")
        for field in ("unknowns", "warnings"):
            value = parsed[field]
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                raise Department1Error(
                    f"{stage} {field} field must be an array of strings."
                )
'''

OLD_TEST_SOURCE = '''from __future__ import annotations

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
        stage = kwargs["text"]["format"]["name"].removeprefix("department1_").upper()
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


class Department1ResponseSchemaPhase102Tests(unittest.TestCase):
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

    def test_live_schema_has_no_open_nested_object(self):
        with tempfile.TemporaryDirectory() as td:
            pipeline, _ = self._pipeline(Path(td), json.dumps({"facts": []}))
            schema = pipeline._stage_schema("UNDERSTAND")
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(schema["properties"]["data"], {"type": "string"})

    def test_encoded_data_is_restored_to_dictionary(self):
        with tempfile.TemporaryDirectory() as td:
            pipeline, client = self._pipeline(
                Path(td), json.dumps({"facts": [{"name": "project"}]})
            )
            result = pipeline._ai_json(
                stage="UNDERSTAND", instructions="UNDERSTAND", evidence={}
            )
            self.assertEqual(result["data"]["facts"][0]["name"], "project")
            self.assertTrue(client.responses.last_kwargs["text"]["format"]["strict"])

    def test_invalid_encoded_data_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            pipeline, _ = self._pipeline(Path(td), "not-json")
            with self.assertRaises(Department1Error):
                pipeline._ai_json(
                    stage="UNDERSTAND", instructions="UNDERSTAND", evidence={}
                )


if __name__ == "__main__":
    unittest.main()
'''

NEW_TEST_SOURCE = '''from __future__ import annotations

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
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} marker, found {count}.")
    return source.replace(old, new, 1)


def install(project_root: Path) -> int:
    root = project_root.resolve()
    pipeline_path = root / "src" / "department1" / "pipeline.py"
    test_path = root / "tests" / "test_department1_response_schema_phase102.py"
    pipeline_backup = pipeline_path.with_name(PIPELINE_BACKUP)
    test_backup = test_path.with_name(TEST_BACKUP)

    if not pipeline_path.is_file():
        print(f"ERROR: Department 1 pipeline was not found: {pipeline_path}")
        return 1
    if not test_path.is_file():
        print("ERROR: Phase 1.0.2 regression test was not found. Install 1.0.2 first.")
        return 1

    test_normalized = test_path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    if test_normalized not in (OLD_TEST_SOURCE, NEW_TEST_SOURCE):
        print(f"ERROR: Refusing to overwrite a modified test file: {test_path}")
        return 1

    raw_source = pipeline_path.read_bytes()
    has_utf8_bom = raw_source.startswith(codecs.BOM_UTF8)
    decoded = raw_source.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in decoded else "\n"
    normalized = decoded.replace("\r\n", "\n")

    if SENTINEL not in normalized:
        try:
            updated = _replace_once(normalized, OLD_PROMPT, NEW_PROMPT, "prompt")
            updated = _replace_once(updated, OLD_FORMAT, NEW_FORMAT, "format")
            updated = _replace_once(
                updated, OLD_BOUNDARY, NEW_BOUNDARY, "validation-boundary"
            )
        except RuntimeError as error:
            print(f"ERROR: {error}")
            print("The live pipeline differs from the certified Phase 1.0.2 baseline.")
            return 1

        compile(updated, str(pipeline_path), "exec")
        if not pipeline_backup.exists():
            shutil.copy2(pipeline_path, pipeline_backup)
            print(f"Pipeline backup created: {pipeline_backup.name}")
        else:
            print(f"Existing pipeline backup preserved: {pipeline_backup.name}")

        output_text = updated.replace("\n", newline)
        output_bytes = output_text.encode("utf-8")
        if has_utf8_bom:
            output_bytes = codecs.BOM_UTF8 + output_bytes
        pipeline_path.write_bytes(output_bytes)
        print("Department 1 dynamic-JSON repair installed.")
    else:
        print("Department 1 dynamic-JSON repair is already installed.")

    if test_normalized != NEW_TEST_SOURCE:
        if not test_backup.exists():
            shutil.copy2(test_path, test_backup)
            print(f"Test backup created: {test_backup.name}")
        test_path.write_text(NEW_TEST_SOURCE, encoding="utf-8")
        print("Department 1 response-format regression test updated.")

    py_compile.compile(str(pipeline_path), doraise=True)
    py_compile.compile(str(test_path), doraise=True)
    print("Python syntax verification: PASS")

    command = [
        sys.executable,
        "-m",
        "unittest",
        "tests.test_department1_response_schema_phase102",
        "tests.test_department1_pipeline",
    ]
    completed = subprocess.run(command, cwd=root, check=False)
    if completed.returncode != 0:
        print("ERROR: Focused Department 1 verification failed.")
        return completed.returncode

    print("Focused Department 1 verification: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the Phase 1.0.3 Department 1 dynamic-JSON repair."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Instagram-agent root; defaults to the current directory.",
    )
    return install(parser.parse_args().project_root)


if __name__ == "__main__":
    raise SystemExit(main())
