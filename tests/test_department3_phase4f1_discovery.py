from src.department3.phase4f_certification import (
    _artifact_matches_project,
    _text_mentions_project,
)
import json


def test_project_can_be_identified_from_json_content(tmp_path):
    path = tmp_path / "generic-inventory.json"
    path.write_text(
        json.dumps({
            "project_id": "Beverly Hills",
            "assets": [{"id": "a1"}],
        }),
        encoding="utf-8",
    )
    matched, mode = _artifact_matches_project(path, "Beverly Hills")
    assert matched is True
    assert mode == "content"


def test_nested_project_identity_is_detected():
    doc = {
        "metadata": {
            "source_project": "Beverly Hills",
        }
    }
    assert _text_mentions_project(doc, "Beverly Hills") is True
