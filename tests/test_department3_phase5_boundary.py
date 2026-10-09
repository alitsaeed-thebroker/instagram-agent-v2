from pathlib import Path

def test_department4_boundary_still_has_live_bridge():
    root = Path(__file__).resolve().parents[1]
    app = (root / "app.py").read_text(encoding="utf-8")
    stages = (root / "src" / "execution" / "stages.py").read_text(encoding="utf-8")
    assert "from src.department3.live_orchestration import" in app
    assert "from src.department3.live_orchestration import" in stages
