import json
from pathlib import Path

def test_phase4f_has_meaningful_format_mix_and_evidence():
    root = Path(__file__).resolve().parents[1]
    path = root / "output" / "audits" / "department3" / "department3-phase4f-beverly-hills-certification.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    metrics = doc["metrics"]
    assert metrics["feed"] > 0
    assert metrics["carousel"] > 0
    assert metrics["story"] > 0
    assert all(x.get("evidence") for x in doc["candidates"])
