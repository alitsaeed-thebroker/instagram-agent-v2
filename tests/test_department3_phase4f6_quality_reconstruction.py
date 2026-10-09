from src.department3.phase4f6_quality_reconstruction import _group_assets


def test_grouping_creates_carousel_and_story():
    assets = [
        {
            "asset_id": "e1",
            "asset_path": "e1.jpg",
            "category": "exterior",
            "evidence": [{"fact_id": "f1"}],
            "visible_summary": "exterior 1",
            "source_metadata": "x",
        },
        {
            "asset_id": "e2",
            "asset_path": "e2.jpg",
            "category": "exterior",
            "evidence": [{"fact_id": "f2"}],
            "visible_summary": "exterior 2",
            "source_metadata": "x",
        },
        {
            "asset_id": "a1",
            "asset_path": "a1.jpg",
            "category": "amenity",
            "evidence": [{"fact_id": "fa"}],
            "visible_summary": "pool",
            "source_metadata": "x",
        },
    ]

    opps = _group_assets(assets)

    assert any(x["format_intent"] == "carousel" for x in opps)
    assert any(x["format_intent"] == "story" for x in opps)


def test_plan_without_evidence_is_restricted():
    assets = [
        {
            "asset_id": "p1",
            "asset_path": "p1.jpg",
            "category": "unit layout",
            "evidence": [],
            "visible_summary": "unit layout",
            "source_metadata": "x",
        }
    ]

    opps = _group_assets(assets)
    assert opps[0]["restrictions"] == ["PLAN_EVIDENCE_REQUIRED"]
