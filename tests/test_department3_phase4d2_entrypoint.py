from pathlib import Path

def test_remaining_legacy_live_calls_are_demoted():
    root=Path(__file__).resolve().parents[1]
    text=(root/'app.py').read_text(encoding='utf-8')
    assert 'output=MarketingStrategyAgent().run(knowledge,reci,campaign_intelligence)' not in text
    assert 'output = VisualOpportunityEngine().run(knowledge, inventory, strategy)' not in text
    assert 'result = CreativeDirectorAgent().run(knowledge, strategy, paths["content_plan"])' not in text
    assert 'run_legacy_strategy_advisory(' in text
    assert 'run_legacy_visual_opportunity_compat(' in text
    assert 'run_legacy_creative_compat(' in text
