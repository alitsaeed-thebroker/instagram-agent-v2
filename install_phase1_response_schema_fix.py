"""Install the Phase 1.0.2 Department 1 strict-schema repair.

Run from the root of ``instagram-agent V2``. The installer backs up the live
Department 1 pipeline, applies an idempotent compatibility patch, installs a
focused regression test, compiles both files, and runs the Department 1 tests.
It makes no API calls and never reads or prints credential values.
"""

from __future__ import annotations

import argparse
import codecs
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path


SENTINEL = "data field returned invalid encoded JSON"
BACKUP_NAME = "pipeline.py.phase1_response_schema_backup"

OLD_PROMPT = '''                                "Never import knowledge from another project.\\n\\n"
                                f"EVIDENCE:\\n{evidence_json}"
'''

NEW_PROMPT = '''                                "Never import knowledge from another project.\\n\\n"
                                "OUTPUT CONTRACT: The data field must be a "
                                "JSON-encoded string whose decoded value is a "
                                "JSON object. Preserve unknown or unsupported "
                                "information as unknown; never invent values.\\n\\n"
                                f"EVIDENCE:\\n{evidence_json}"
'''

OLD_PARSE_BOUNDARY = '''        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise Department1Error(f"{stage} returned invalid JSON: {exc}") from exc

        if parsed.get("project") != self.project_name:
'''

NEW_PARSE_BOUNDARY = '''        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise Department1Error(f"{stage} returned invalid JSON: {exc}") from exc

        # Strict Structured Outputs requires every schema object to declare
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
'''

OLD_SCHEMA = '''    def _stage_schema(self, stage: str) -> dict[str, Any]:
        # Kept deliberately stable and permissive inside `data` so Department 1
        # can evolve its real-estate ontology without breaking the stage contract.
        return {
'''

NEW_SCHEMA = '''    def _stage_schema(self, stage: str) -> dict[str, Any]:
        # OpenAI strict schemas require additionalProperties=false for every
        # object. Keep a closed, stable envelope and carry the evolving
        # real-estate ontology as encoded JSON, decoded at the trust boundary.
        return {
'''

OLD_DATA_SCHEMA = '''                "data": {
                    "type": "object",
                    "additionalProperties": True,
                },
'''

NEW_DATA_SCHEMA = '''                "data": {"type": "string"},
'''

TEST_SOURCE = '''from __future__ import annotations

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


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} marker, found {count}.")
    return source.replace(old, new, 1)


def install(project_root: Path) -> int:
    root = project_root.resolve()
    pipeline_path = root / "src" / "department1" / "pipeline.py"
    test_path = root / "tests" / "test_department1_response_schema_phase102.py"
    backup_path = pipeline_path.with_name(BACKUP_NAME)

    if not pipeline_path.is_file():
        print(f"ERROR: Department 1 pipeline was not found: {pipeline_path}")
        return 1
    if test_path.exists() and test_path.read_text(encoding="utf-8-sig") != TEST_SOURCE:
        print(f"ERROR: Refusing to overwrite a different test file: {test_path}")
        return 1

    raw_source = pipeline_path.read_bytes()
    has_utf8_bom = raw_source.startswith(codecs.BOM_UTF8)
    decoded = raw_source.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in decoded else "\n"
    normalized = decoded.replace("\r\n", "\n")

    if SENTINEL not in normalized:
        try:
            updated = _replace_once(normalized, OLD_PROMPT, NEW_PROMPT, "prompt")
            updated = _replace_once(
                updated, OLD_PARSE_BOUNDARY, NEW_PARSE_BOUNDARY, "parse-boundary"
            )
            updated = _replace_once(updated, OLD_SCHEMA, NEW_SCHEMA, "schema-comment")
            updated = _replace_once(
                updated, OLD_DATA_SCHEMA, NEW_DATA_SCHEMA, "data-schema"
            )
        except RuntimeError as error:
            print(f"ERROR: {error}")
            print("The live pipeline differs from the certified Phase 1 baseline.")
            return 1

        compile(updated, str(pipeline_path), "exec")
        if not backup_path.exists():
            shutil.copy2(pipeline_path, backup_path)
            print(f"Backup created: {backup_path.name}")
        else:
            print(f"Existing backup preserved: {backup_path.name}")

        output_text = updated.replace("\n", newline)
        output_bytes = output_text.encode("utf-8")
        if has_utf8_bom:
            output_bytes = codecs.BOM_UTF8 + output_bytes
        pipeline_path.write_bytes(output_bytes)
        print("Department 1 strict-schema repair installed.")
    else:
        print("Department 1 strict-schema repair is already installed.")

    if not test_path.exists():
        test_path.write_text(TEST_SOURCE, encoding="utf-8")
        print(f"Regression test installed: {test_path.name}")

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
        description="Install the Phase 1.0.2 Department 1 schema repair."
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
