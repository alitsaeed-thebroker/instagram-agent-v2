from pathlib import Path

from src.department3.phase5_freeze_certification import certify

def test_phase5_certifier_reaches_freeze_decision():
    root = Path(__file__).resolve().parents[1]
    report = certify(root, "Beverly Hills")
    assert report["decision"] in {
        "DEPARTMENT 3 — FREEZE PASS",
        "DEPARTMENT 3 — PASS WITH CONDITIONS",
    }
    assert report["safety"]["meta_writes"] == 0
    assert report["safety"]["instagram_publish_attempts"] == 0
