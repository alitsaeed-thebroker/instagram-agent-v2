from pathlib import Path


def test_live_planning_authority_call_is_cut_over():
    root = Path(__file__).resolve().parents[1]
    text = (root / "app.py").read_text(encoding="utf-8")
    old = 'products = PlanningEngine().run(knowledge, strategy, inventory, paths["opportunities"], creative_intelligence_path=reci, campaign_intelligence_path=campaign_intelligence, write_campaign=stage == "campaign-planner", platform_strategy=_PLATFORM_STRATEGY)'
    assert old not in text
    assert "cutover_legacy_planning_products(" in text
    assert "from src.department3.planning_cutover import cutover_legacy_planning_products" in text
