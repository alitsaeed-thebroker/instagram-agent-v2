import json

from src.department3.phase4f7a_semantic_discovery import (
    _excluded,
    discover,
)


def test_contaminated_downstream_sources_are_excluded(tmp_path):
    bad = tmp_path / "output" / "simulation" / "x.json"
    bad.parent.mkdir(parents=True)
    bad.write_text(json.dumps({"project_id": "Beverly Hills"}), encoding="utf-8")
    assert _excluded(bad) is True


def test_authentic_asset_semantics_are_discovered(tmp_path):
    base = tmp_path / "output" / "asset-intelligence" / "Beverly Hills"
    base.mkdir(parents=True)

    path = base / "assets.json"
    path.write_text(json.dumps({
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
                        "confidence": 0.99,
                    }
                ],
            }
        ],
    }), encoding="utf-8")

    report = discover(tmp_path, "Beverly Hills", ["src_abc"])
    asset = report["assets"]["src_abc"]

    assert "exterior" in asset["classifications_found"]
    assert asset["evidence_found"][0]["fact_id"] == "fact-1"
    assert asset["canonical_source"].endswith("assets.json")
