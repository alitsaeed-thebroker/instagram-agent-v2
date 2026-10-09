import pytest

from src.department3.real_estate_brain import RealEstateStrategyBrain, RealEstateStrategyError


def test_location_is_prioritized_over_developer_content():
    brain = RealEstateStrategyBrain()
    items = brain.build_candidates(
        project_id="p",
        opportunities=[
            {
                "project_id": "p",
                "id": "developer",
                "category": "developer",
                "asset_ids": ["a-dev"],
                "fact_summary": "Verified developer fact",
                "evidence": [{"fact_id": "f-dev", "confidence": 0.95}],
            },
            {
                "project_id": "p",
                "id": "location",
                "category": "location",
                "asset_ids": ["a-loc"],
                "fact_summary": "Verified location context",
                "evidence": [{"fact_id": "f-loc", "confidence": 0.95}],
            },
        ],
    )
    assert items[0]["production_item_id"] == "location"


def test_plan_without_evidence_is_skipped():
    brain = RealEstateStrategyBrain()
    items = brain.build_candidates(
        project_id="p",
        opportunities=[{
            "project_id": "p",
            "id": "layout",
            "category": "unit layout",
            "asset_ids": ["plan-1"],
        }],
    )
    assert items == []


def test_story_is_first_class_and_reel_is_rejected():
    brain = RealEstateStrategyBrain()
    items = brain.build_candidates(
        project_id="p",
        opportunities=[{
            "project_id": "p",
            "id": "amenity",
            "category": "amenity",
            "asset_ids": ["a1"],
            "evidence": [{"fact_id": "f1"}],
        }],
    )
    assert items[0]["format_intent"] == "story"

    with pytest.raises(RealEstateStrategyError):
        brain.build_candidates(
            project_id="p",
            opportunities=[{
                "project_id": "p",
                "id": "x",
                "category": "exterior",
                "format_intent": "reel",
                "asset_ids": ["a2"],
                "evidence": [{"fact_id": "f2"}],
            }],
        )


def test_recent_duplicate_asset_is_penalized():
    brain = RealEstateStrategyBrain()
    items = brain.build_candidates(
        project_id="p",
        recent_history=[{
            "content_category": "exterior",
            "asset_ids": ["same"],
        }],
        opportunities=[
            {
                "project_id": "p",
                "id": "repeated",
                "category": "exterior",
                "asset_ids": ["same"],
                "evidence": [{"fact_id": "f1"}],
            },
            {
                "project_id": "p",
                "id": "fresh",
                "category": "interior",
                "asset_ids": ["fresh"],
                "evidence": [{"fact_id": "f2"}],
            },
        ],
    )
    assert items[0]["production_item_id"] == "fresh"


def test_cross_project_opportunity_fails_closed():
    with pytest.raises(RealEstateStrategyError):
        RealEstateStrategyBrain().build_candidates(
            project_id="a",
            opportunities=[{
                "project_id": "b",
                "id": "x",
                "category": "location",
                "asset_ids": ["a"],
                "evidence": [{"fact_id": "f"}],
            }],
        )
