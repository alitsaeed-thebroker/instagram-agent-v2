from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path.cwd().resolve()
APP = ROOT / "app.py"
OLD = 'products = PlanningEngine().run(knowledge, strategy, inventory, paths["opportunities"], creative_intelligence_path=reci, campaign_intelligence_path=campaign_intelligence, write_campaign=stage == "campaign-planner", platform_strategy=_PLATFORM_STRATEGY)'

if __name__ == "__main__":
    text = APP.read_text(encoding="utf-8")
    ast.parse(text, filename=str(APP))
    checks = {
        "cutover_import": "from src.department3.planning_cutover import cutover_legacy_planning_products" in text,
        "canonical_cutover_call": "cutover_legacy_planning_products(" in text,
        "old_live_authority_call_removed": OLD not in text,
    }
    print(checks)
    if not all(checks.values()):
        raise SystemExit("Phase 4D.1 verification: FAIL")
    print("Phase 4D.1 verification: PASS")
