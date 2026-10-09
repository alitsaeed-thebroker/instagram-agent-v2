import json
import tempfile
from pathlib import Path

from src.department3.planning_cutover import cutover_legacy_planning_products


class FakePlanningEngine:
    def __init__(self, root: Path):
        self.root = root

    def run(self, *args, **kwargs):
        content = self.root / "content.json"
        campaign = self.root / "campaign.json"
        item = {
            "project_id": "project-a",
            "production_item_id": "item-1",
            "objective": "Communicate location advantage",
            "audience": "buyer",
            "proposition": "Verified location advantage",
            "content_category": "location",
            "format_intent": "story",
            "approved_source_asset_ids": ["asset-1"],
            "evidence": [{"fact_id": "fact-1", "confidence": 0.98}],
        }
        content.write_text(json.dumps({"project_id": "project-a", "items": [item]}), encoding="utf-8")
        campaign.write_text(json.dumps({"project_id": "project-a", "items": [item]}), encoding="utf-8")
        return {"content_plan": content, "campaign_plan": campaign}


def test_planning_cutover_rewrites_same_paths_with_canonical_authority():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        products = cutover_legacy_planning_products(
            project_id="project-a",
            planning_engine=FakePlanningEngine(root),
            planning_args=(),
        )
        doc = json.loads(products["content_plan"].read_text(encoding="utf-8"))
        assert doc["authority"]["authoritative"] is True
        assert doc["authority"]["authority_module"] == "src.department3.strategy_authority"
        assert doc["legacy_compatibility"]["authoritative"] is False
        assert doc["approved_content_plan"]["decisions"][0]["format_intent"] == "story"
