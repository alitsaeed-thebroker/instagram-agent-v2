import ast
from pathlib import Path

from tools.department3_phase4d0_capture import LEGACY_SYMBOLS


def test_capture_tool_compiles_and_has_expected_legacy_symbols():
    root = Path(__file__).resolve().parents[1]
    source = (root / "tools" / "department3_phase4d0_capture.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "ContentPlanner" in LEGACY_SYMBOLS
    assert "CreativeDirectorAgent" in LEGACY_SYMBOLS
    assert "MarketingStrategyAgent" in LEGACY_SYMBOLS
    assert "PlanningEngine" in LEGACY_SYMBOLS
