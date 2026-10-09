from pathlib import Path

def test_phase5_authority_chain_is_present():
    root = Path(__file__).resolve().parents[1]
    app = (root / "app.py").read_text(encoding="utf-8")
    assert "cutover_legacy_planning_products(" in app
    assert "run_legacy_strategy_advisory(" in app
    assert "run_legacy_visual_opportunity_compat(" in app
    assert "run_legacy_creative_compat(" in app
