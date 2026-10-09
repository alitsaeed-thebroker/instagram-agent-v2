from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.creative_intelligence import RealEstateCreativeIntelligence
from src.execution.stages import DEPENDENCIES, STAGE_ORDER


def knowledge(**extra):
    value={"project_id":"Project A","project_identity":{"project_name":"Project A","project_type":"residential","location":"Airport Road","developer_name":"Developer"},"project":{"name":"Project A","location":"Airport Road"},"fact_provenance":{"project_identity.location":[{"source":"brochure.pdf","page":2}]}}
    value.update(extra);return value


class RealEstateCreativeIntelligenceTests(unittest.TestCase):
    def setUp(self): self.engine=RealEstateCreativeIntelligence()
    def opportunity(self,result,category): return next(x for x in result.opportunities if x.category==category)

    def test_canonical_stage_precedes_department_three(self):
        self.assertLess(STAGE_ORDER.index("creative-intelligence"),STAGE_ORDER.index("marketing-strategy"))
        self.assertIn("creative-intelligence",DEPENDENCIES["marketing-strategy"])

    def test_strong_location_and_typed_broker_translation(self):
        k=knowledge(location_intelligence={"airport_proximity":"10 minutes","main_road":"Airport Road"})
        inv={"project_id":"Project A","assets":[{"asset_id":"map1","project_id":"Project A","asset_type":"location_map","quality_score":90}]}
        result=self.engine.build(k,inventory=inv,project_hint="Project A")
        op=self.opportunity(result,"location")
        self.assertGreaterEqual(op.score,70);self.assertIn("fact_",op.supporting_fact_ids[0])
        self.assertEqual(result.interpretations[0]["truth_layer"],"COMMERCIAL_INTERPRETATION")

    def test_missing_price_is_limited_and_never_invented(self):
        result=self.engine.build(knowledge(),project_hint="Project A")
        op=self.opportunity(result,"commercial")
        self.assertEqual(op.status,"LIMITED");self.assertFalse(op.supporting_fact_ids)
        self.assertNotIn("price",op.recommended_message.casefold())

    def test_unverified_layout_is_blocked_but_exact_verified_layout_is_allowed(self):
        k=knowledge(plan_intelligence={"layout":{"unit_type":"Type B","area_sqm":270}})
        blocked=self.opportunity(self.engine.build(k,plans={"project_id":"Project A","assets":[]}),"unit")
        self.assertEqual(blocked.status,"BLOCKED")
        plan={"project_id":"Project A","assets":[{"asset_id":"plan1","project_id":"Project A","asset_type":"unit_layout","relationship_status":"VERIFIED","evidence":{"area_sqm":[{"page":4}]}}]}
        self.assertEqual(self.opportunity(self.engine.build(k,plans=plan),"unit").status,"BLOCKED")
        from src.plan_integrity import make_plan_record
        from tests.unit_plan_fixtures import source_plan
        plan={"project_id":"Project A","assets":[make_plan_record(source_plan(project="Project A"))]}
        allowed=self.opportunity(self.engine.build(k,plans=plan),"unit")
        self.assertNotIn(allowed.status,{"BLOCKED","REVIEW_REQUIRED"})

    def test_visual_and_knowledge_strength_are_independent(self):
        inv={"project_id":"Project A","assets":[{"asset_id":"hero","project_id":"Project A","asset_type":"exterior","quality_score":98}]}
        weak=self.opportunity(self.engine.build(knowledge(),inventory=inv),"project")
        self.assertGreater(weak.visual_strength,weak.evidence_strength)
        rich=self.opportunity(self.engine.build(knowledge(amenities=["Pool","Gym","Garden"])),"amenity")
        self.assertEqual(rich.visual_strength,0);self.assertTrue(rich.visual_evidence_notes)

    def test_investment_missing_conflict_stale_and_provenance_fail_closed(self):
        missing=self.opportunity(self.engine.build(knowledge()),"investment")
        self.assertEqual(missing.status,"LIMITED")
        unsafe=knowledge(investment={"expected_return":{"value":"12% ROI","freshness":"STALE","relationship_status":"CONFLICTED"}})
        op=self.opportunity(self.engine.build(unsafe),"investment")
        self.assertEqual(op.status,"BLOCKED");self.assertFalse(op.supporting_fact_ids)

    def test_audience_is_hypothesis_duplicates_consolidated_and_projects_isolated(self):
        result=self.engine.build(knowledge(units=[{"name":"3 bedroom family apartment"},{"name":"3 bedroom family apartment"}]))
        self.assertTrue(result.audience_hypotheses)
        self.assertTrue(all(x["status"]=="HYPOTHESIS" and x["truth_layer"]=="AUDIENCE_HYPOTHESIS" for x in result.audience_hypotheses))
        self.assertEqual(len([x for x in result.opportunities if x.category=="unit"]),1)
        with self.assertRaisesRegex(ValueError,"cross-project"):
            self.engine.build(knowledge(),inventory={"project_id":"Project B","assets":[]})

    def test_artifact_is_machine_readable_and_fingerprint_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);kp=root/"Project A.json";ip=root/"inventory.json"
            kp.write_text(json.dumps(knowledge()),encoding="utf-8");ip.write_text(json.dumps({"project_id":"Project A","assets":[]}),encoding="utf-8")
            first=self.engine.run(kp,inventory_path=ip,output_directory=root);a=json.loads(first.read_text(encoding="utf-8"))
            kp.write_text(json.dumps(knowledge(amenities=["Pool"])),encoding="utf-8")
            second=self.engine.run(kp,inventory_path=ip,output_directory=root);b=json.loads(second.read_text(encoding="utf-8"))
            self.assertNotEqual(a["input_fingerprint"],b["input_fingerprint"])
            self.assertEqual(b["contract_role"],"canonical_creative_opportunity_map")


if __name__ == "__main__": unittest.main()
