import json

from src.department3.phase4f5_regenerator import _category_from_text, regenerate


def test_category_inference():
    assert _category_from_text("Beverly Hills masterplan page 4") == "masterplan"
    assert _category_from_text("tower exterior render") == "exterior"
    assert _category_from_text("amenity pool") == "amenity"


def test_regenerator_uses_real_metadata_and_excludes_releases(tmp_path):
    meta_dir = tmp_path / "output" / "source-images" / "Beverly Hills"
    meta_dir.mkdir(parents=True)
    meta = meta_dir / "inventory.json"
    meta.write_text(json.dumps({
        "project_id": "Beverly Hills",
        "selected": [
            {
                "asset_id": "a1",
                "category": "location",
                "source_path": "input/Beverly Hills/location.jpg",
                "evidence": [{"fact_id": "f1"}],
            }
        ],
    }), encoding="utf-8")

    release = tmp_path / "output" / "releases" / "Beverly Hills"
    release.mkdir(parents=True)
    (release / "fake.json").write_text(json.dumps({
        "project_id": "Beverly Hills",
        "selected": [{"asset_id": "bad", "category": "exterior"}],
    }), encoding="utf-8")

    result = regenerate(tmp_path, "Beverly Hills")
    payload = result["payload"]
    assert payload["metrics"]["opportunities"] == 1
    assert payload["opportunities"][0]["id"] == "a1"
    assert payload["source_policy"]["release_sources_allowed"] is False
