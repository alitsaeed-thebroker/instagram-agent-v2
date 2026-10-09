import json
from pathlib import Path

from src.department3.phase4f_certification import (
    _artifact_matches_project,
    _is_forbidden_source,
    _walk_json_files,
)


def test_certification_output_is_never_eligible_source(tmp_path):
    path = tmp_path / "output" / "audits" / "department3"
    path.mkdir(parents=True)
    cert = path / "department3-phase4f-beverly-hills-certification.json"
    cert.write_text(json.dumps({"project": "Beverly Hills"}), encoding="utf-8")
    assert _is_forbidden_source(cert) is True
    matched, mode = _artifact_matches_project(cert, "Beverly Hills")
    assert matched is False
    assert mode == ""


def test_walk_excludes_audit_tree(tmp_path):
    good_dir = tmp_path / "output" / "creative-intelligence"
    good_dir.mkdir(parents=True)
    good = good_dir / "generic.json"
    good.write_text(json.dumps({"project_id": "Beverly Hills"}), encoding="utf-8")

    bad_dir = tmp_path / "output" / "audits" / "department3"
    bad_dir.mkdir(parents=True)
    bad = bad_dir / "generic.json"
    bad.write_text(json.dumps({"project_id": "Beverly Hills"}), encoding="utf-8")

    files = _walk_json_files(tmp_path / "output")
    assert good in files
    assert bad not in files
