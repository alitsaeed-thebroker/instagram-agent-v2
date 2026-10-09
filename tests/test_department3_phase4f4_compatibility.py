from pathlib import Path
import json

from src.department3.phase4f_certification import (
    _artifact_matches_project,
    _is_forbidden_source,
    _opportunities_from_inventory,
    _score_check,
    _text_mentions_project,
    _walk_json_files,
)


def test_legacy_helpers_remain_available_and_hardened(tmp_path):
    audit = tmp_path / "output" / "audits" / "department3" / "x.json"
    audit.parent.mkdir(parents=True)
    audit.write_text(json.dumps({"project_id": "Beverly Hills"}), encoding="utf-8")

    assert _is_forbidden_source(audit) is True
    matched, mode = _artifact_matches_project(audit, "Beverly Hills")
    assert matched is False
    assert mode == ""

    assert audit not in _walk_json_files(tmp_path / "output")


def test_legacy_inventory_normalizer_still_works():
    doc = {
        "selected": [
            {
                "asset_id": "a1",
                "category": "location",
                "description": "map",
            }
        ]
    }
    items = _opportunities_from_inventory(doc, "Beverly Hills")
    assert len(items) == 1
    assert items[0]["asset_ids"] == ["a1"]
    assert items[0]["project_id"] == "Beverly Hills"


def test_legacy_project_text_helper():
    assert _text_mentions_project(
        {"metadata": {"source_project": "Beverly Hills"}},
        "Beverly Hills",
    )


def test_legacy_score_check():
    c = _score_check("x", False, "bad", critical=True)
    assert c.status == "FAIL"
    assert c.critical is True
