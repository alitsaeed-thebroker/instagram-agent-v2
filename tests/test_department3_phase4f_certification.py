from pathlib import Path

from src.department3.phase4f_certification import _opportunities_from_inventory, _score_check


def test_inventory_can_be_normalized_without_inventing_assets():
    doc = {
        "selected": [
            {"asset_id": "a1", "category": "location", "description": "map"},
            {"asset_id": "a2", "category": "exterior", "description": "tower"},
        ]
    }
    items = _opportunities_from_inventory(doc, "Beverly Hills")
    assert [x["asset_ids"] for x in items] == [["a1"], ["a2"]]
    assert all(x["project_id"] == "Beverly Hills" for x in items)


def test_check_marks_critical_failure():
    c = _score_check("x", False, "bad", critical=True)
    assert c.status == "FAIL"
    assert c.critical is True


def test_runner_source_contains_no_meta_publish_call():
    root = Path(__file__).resolve().parents[1]
    text = (root / "src" / "department3" / "phase4f_certification.py").read_text(encoding="utf-8")
    assert "graph.facebook.com" not in text
    assert "publish_to_instagram" not in text
