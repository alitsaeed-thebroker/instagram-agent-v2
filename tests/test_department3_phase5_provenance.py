import json
from pathlib import Path

def test_phase4f_certified_source_is_canonical_visual_opportunities():
    root = Path(__file__).resolve().parents[1]
    path = root / "output" / "audits" / "department3" / "department3-phase4f-beverly-hills-certification.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["status"] == "PASS"
    assert "visual-opportunities" in doc["opportunity_source"].replace("\\", "/")
    assert doc["safety"]["meta_writes"] == 0
