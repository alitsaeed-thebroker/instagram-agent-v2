import json
from pathlib import Path

def test_phase4f_plan_safety_is_fail_closed():
    root = Path(__file__).resolve().parents[1]
    path = root / "output" / "audits" / "department3" / "department3-phase4f-beverly-hills-certification.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["metrics"]["unsupported_plan_inputs"] == 0
