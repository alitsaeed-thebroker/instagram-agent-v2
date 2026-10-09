from src.department3.phase4f7br2_catalogue_visual_recovery import (
    _asset_id,
    _category_from_context,
    _is_plan_like,
)


def test_deterministic_asset_id():
    assert _asset_id(b"same") == _asset_id(b"same")
    assert _asset_id(b"same") != _asset_id(b"different")


def test_context_classification_and_plan_detection():
    category, source = _category_from_context(
        "Beverly Hills Master Plan and site plan overview"
    )
    assert category == "masterplan"
    assert source.startswith("context_token:")

    plan_category, _ = _category_from_context(
        "Typical floor plan - apartment plan"
    )
    assert _is_plan_like(plan_category, "Typical floor plan - apartment plan") is True
