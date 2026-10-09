import ast
from pathlib import Path


def test_phase4c_live_bridge_is_installed_on_real_entrypoints():
    root = Path(__file__).resolve().parents[1]
    for rel in ("app.py", "src/execution/stages.py"):
        path = root / rel
        text = path.read_text(encoding="utf-8")
        ast.parse(text, filename=str(path))
        assert "from src.department3.live_orchestration import" in text
        assert "from src.department3.runtime_guard import" in text
        assert "# DEPARTMENT3_PHASE4C_LIVE_BRIDGE" in text
        assert "def _department3_canonical_approve(" in text
