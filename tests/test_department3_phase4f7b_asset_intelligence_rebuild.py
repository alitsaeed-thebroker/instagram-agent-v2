import json

from src.department3.phase4f7b_asset_intelligence_rebuild import (
    _excluded,
    rebuild,
)


def test_downstream_sources_are_excluded(tmp_path):
    p = tmp_path / "output" / "simulation" / "x.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"project_id": "Beverly Hills"}), encoding="utf-8")

    assert _excluded(p) is True


def test_rebuild_creates_authentic_asset_intelligence(tmp_path):
    base = tmp_path / "output" / "source-images" / "Beverly Hills"
    base.mkdir(parents=True)

    meta = base / "inventory.json"
    meta.write_text(json.dumps({
        "project_id": "Beverly Hills",
        "assets": [
            {
                "asset_id": "src_abc",
                "source_path": "Beverly Hills/originals/src_abc.jpg",
                "category": "exterior",
                "evidence": [
                    {
                        "fact_id": "fact-1",
                        "source_id": "catalogue",
                        "confidence": 0.98,
                    }
                ],
            }
        ],
    }), encoding="utf-8")

    path, payload = rebuild(tmp_path, "Beverly Hills")

    assert path.is_file()
    assert payload["metrics"]["assets"] == 1
    assert payload["assets"][0]["category"] == "exterior"
    assert payload["assets"][0]["evidence"][0]["fact_id"] == "fact-1"
    assert payload["source_policy"]["simulation_allowed"] is False
