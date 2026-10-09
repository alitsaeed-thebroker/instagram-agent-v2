from __future__ import annotations
import ast
from pathlib import Path
ROOT=Path.cwd().resolve(); APP=ROOT/'app.py'
OLD_CALLS=(
'output=MarketingStrategyAgent().run(knowledge,reci,campaign_intelligence)',
'output = VisualOpportunityEngine().run(knowledge, inventory, strategy)',
'result = CreativeDirectorAgent().run(knowledge, strategy, paths["content_plan"])',)
if __name__=='__main__':
    text=APP.read_text(encoding='utf-8'); ast.parse(text,filename=str(APP))
    checks={'demotion_import':'from src.department3.legacy_live import' in text,'strategy_demoted':'run_legacy_strategy_advisory(' in text,'opportunity_demoted':'run_legacy_visual_opportunity_compat(' in text,'creative_demoted':'run_legacy_creative_compat(' in text,'old_direct_calls_removed':all(call not in text for call in OLD_CALLS)}
    print(checks)
    if not all(checks.values()): raise SystemExit('Phase 4D.2 verification: FAIL')
    print('Phase 4D.2 verification: PASS')
