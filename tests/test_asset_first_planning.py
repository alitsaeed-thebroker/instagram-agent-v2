"""Phase 9.1 deterministic planning tests."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.planning.engine import PlanningEngine, VisualOpportunityEngine


def asset(asset_id: str, kind: str = "exterior", *, confidence: float = .9, quality: int = 85, people: bool = False, page: int = 1) -> dict:
    return {"asset_id": asset_id, "project_id": "p", "asset_type": kind, "asset_subtype": kind,
            "analysis_status": "analyzed", "marketing_suitability": "hero_ready", "confidence": confidence,
            "quality_score": quality, "image_quality": {"score": quality}, "orientation": "landscape",
            "dominant_subject": f"{kind} subject", "visible_spaces": [kind], "visible_project_features": [],
            "visible_amenities": [], "visible_architectural_elements": [], "contains_people": people,
            "source_page": page, "safe_crop_assessment": {"level": "flexible"},
            "recommended_platforms": ["Instagram"], "recommended_formats": ["image"]}


class AssetFirstPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.knowledge = self.root / "p.json"
        self.knowledge.write_text(json.dumps({
            "canonical_intelligence":{
                "project_namespace":"p","schema_version":"2.0.0",
                "contract_role":"authoritative_department2_relational_intelligence",
                "entities":[{"entity_id":"project_p","entity_type":"project","project_namespace":"p","label":"p","parent_entity_id":None,"attributes":{}}],
                "facts":[],"conflicts":[],"unknowns":[],"metadata":{"visual_only_fixture":True},
            }
        }), encoding="utf-8")
        self.strategy = self.root / "p-strategy.json"
        self.strategy.write_text(json.dumps({"target_audience": ["Investor"], "buyer_personas": []}), encoding="utf-8")

    def tearDown(self) -> None: self.temp.cleanup()

    def inventory(self, assets: list[dict]) -> Path:
        path = self.root / "inventory.json"
        path.write_text(json.dumps({"project_id": "p", "inventory_type": "semantic", "all_source_asset_ids": [a["asset_id"] for a in assets],
            "available_exterior_images": assets, "available_text_facts": [{"knowledge_path": "architecture.style", "value": "Modern architecture"}]}), encoding="utf-8")
        return path

    def test_only_exteriors_create_supported_opportunity_and_no_lifestyle(self) -> None:
        inv = self.inventory([asset("a1"), asset("a2", page=2)])
        with patch("src.planning.engine.VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY", self.root):
            output = json.loads(VisualOpportunityEngine().run(self.knowledge, inv, self.strategy).read_text(encoding="utf-8"))
        self.assertEqual(output["inventory_summary"]["exterior_count"], 2)
        self.assertEqual(output["visual_opportunity_groups"][0]["opportunity_type"], "exterior")
        self.assertTrue(any(x["story_type"] == "family routine" for x in output["unsupported_story_types"]))

    def test_low_confidence_asset_is_not_planned_as_hero(self) -> None:
        inv = self.inventory([asset("weak", confidence=.4)])
        with patch("src.planning.engine.VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY", self.root):
            opp = VisualOpportunityEngine().run(self.knowledge, inv, self.strategy)
        self.assertEqual(json.loads(opp.read_text(encoding="utf-8"))["asset_reservations"][0]["reservation_level"], "review_required")

    def test_deterministic_content_uses_real_ids_and_has_no_camera_language(self) -> None:
        inv = self.inventory([asset("a1"), asset("a2", page=2), asset("a3", page=3)])
        patches = [patch(f"src.planning.engine.{name}", self.root / name.lower()) for name in (
            "VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY", "CAMPAIGNS_OUTPUT_DIRECTORY", "CONTENT_OUTPUT_DIRECTORY",
            "ASSET_USAGE_OUTPUT_DIRECTORY", "CONTENT_MEMORY_OUTPUT_DIRECTORY", "REPORTS_OUTPUT_DIRECTORY")]
        for item in patches: item.start()
        try:
            opp = VisualOpportunityEngine().run(self.knowledge, inv, self.strategy)
            outputs = PlanningEngine().run(self.knowledge, self.strategy, inv, opp)
            content = json.loads(outputs["content_plan"].read_text(encoding="utf-8"))
            serialized = json.dumps(content).casefold()
            self.assertNotIn("lens", serialized); self.assertNotIn("camera motion", serialized)
            self.assertTrue(set(content["content_ideas"][0]["selected_source_asset_ids"]) <= {"a1", "a2", "a3"})
            graph = json.loads(outputs["campaign_graph"].read_text(encoding="utf-8"))
            self.assertTrue(any(n["type"] == "asset" for n in graph["nodes"]))
        finally:
            for item in reversed(patches): item.stop()

    def test_source_aliases_do_not_create_duplicate_carousel(self):
        self._assert_distinct_sources(False)

    def test_duplicate_alias_does_not_hide_distinct_carousel_candidate(self):
        self._assert_distinct_sources(True)

    def _assert_distinct_sources(self,with_distinct):
        assets=[{**asset('a1'),'source_hash':'a'*64},{**asset('a2',page=2),'source_hash':'a'*64}]
        if with_distinct:assets.append({**asset('a3',page=3),'source_hash':'b'*64})
        inv=self.inventory(assets)
        names=('VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY','CAMPAIGNS_OUTPUT_DIRECTORY','CONTENT_OUTPUT_DIRECTORY','ASSET_USAGE_OUTPUT_DIRECTORY','CONTENT_MEMORY_OUTPUT_DIRECTORY','REPORTS_OUTPUT_DIRECTORY')
        patches=[patch(f'src.planning.engine.{name}',self.root/name.lower()) for name in names]
        for entry in patches:entry.start()
        try:
            opp=VisualOpportunityEngine().run(self.knowledge,inv,self.strategy)
            outputs=PlanningEngine().run(self.knowledge,self.strategy,inv,opp)
            ideas=json.loads(outputs['content_plan'].read_text(encoding='utf-8'))['content_ideas']
            idea=next(i for i in ideas if i['selected_source_asset_ids'])
            selected=idea['selected_source_asset_ids'];hashes={a['asset_id']:a['source_hash'] for a in assets}
            self.assertEqual(len(selected),len({hashes[a] for a in selected}))
            self.assertEqual(len(selected),2 if with_distinct else 1)
            self.assertEqual(idea['selected_format'],'carousel' if with_distinct else 'single_post')
            self.assertEqual(idea['planned_publication']['publication_type'],idea['selected_format'])
            self.assertEqual(len(idea['duplicate_source_exclusions']),1)
        finally:
            for entry in reversed(patches):entry.stop()


if __name__ == "__main__": unittest.main()
