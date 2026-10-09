import json

from src.department3.phase4f_certification import (
    _excluded,
    _looks_like_visual_item,
)


def test_release_provenance_is_excluded(tmp_path):
    p = tmp_path / "output" / "releases" / "Beverly Hills" / "release-1" / "provenance" / "audit.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"project": "Beverly Hills"}), encoding="utf-8")
    assert _excluded(p) is True


def test_visual_item_requires_identity_and_semantics():
    assert _looks_like_visual_item({
        "asset_id": "a1",
        "category": "exterior",
    }) is True

    assert _looks_like_visual_item({
        "production_item_id": "x",
        "status": "released",
    }) is False
