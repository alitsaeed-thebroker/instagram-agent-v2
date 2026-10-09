import json

from src.department3.phase4f7c_opportunity_reconstruction import reconstruct


def test_reconstruction_creates_carousel_story_and_conservative_feed(tmp_path):
    source_dir = (
        tmp_path
        / "output"
        / "asset-intelligence"
        / "Beverly Hills"
    )
    source_dir.mkdir(parents=True)

    source = source_dir / "Beverly Hills-asset-intelligence.json"

    source.write_text(json.dumps({
        "project_id": "Beverly Hills",
        "fingerprint": "abc",
        "assets": [
            {
                "asset_id": "e1",
                "category": "exterior",
                "paths": ["e1.jpg"],
                "evidence": [{"fact_id": "f1"}],
                "plan_relationships": [],
            },
            {
                "asset_id": "e2",
                "category": "exterior",
                "paths": ["e2.jpg"],
                "evidence": [{"fact_id": "f2"}],
                "plan_relationships": [],
            },
            {
                "asset_id": "a1",
                "category": "amenity",
                "paths": ["a1.jpg"],
                "evidence": [{"fact_id": "fa"}],
                "plan_relationships": [],
            },
            {
                "asset_id": "g1",
                "category": "project feature",
                "paths": ["g1.jpg"],
                "evidence": [{"fact_id": "fg"}],
                "plan_relationships": [],
            },
        ],
    }), encoding="utf-8")

    _, payload = reconstruct(
        tmp_path,
        "Beverly Hills",
        source,
    )

    formats = [x["format_intent"] for x in payload["opportunities"]]

    assert "carousel" in formats
    assert "story" in formats
    assert "feed" in formats


def test_unverified_plan_is_blocked(tmp_path):
    source_dir = (
        tmp_path
        / "output"
        / "asset-intelligence"
        / "Beverly Hills"
    )
    source_dir.mkdir(parents=True)

    source = source_dir / "Beverly Hills-asset-intelligence.json"

    source.write_text(json.dumps({
        "project_id": "Beverly Hills",
        "fingerprint": "abc",
        "assets": [
            {
                "asset_id": "p1",
                "category": "unit layout",
                "paths": ["p1.jpg"],
                "evidence": [{"fact_id": "fp"}],
                "plan_relationships": [],
            },
            {
                "asset_id": "i1",
                "category": "interior",
                "paths": ["i1.jpg"],
                "evidence": [{"fact_id": "fi"}],
                "plan_relationships": [],
            },
        ],
    }), encoding="utf-8")

    _, payload = reconstruct(
        tmp_path,
        "Beverly Hills",
        source,
    )

    assert payload["metrics"]["blocked_plan_assets"] == 1
    assert all(
        "p1.jpg" not in x["asset_ids"]
        for x in payload["opportunities"]
    )
