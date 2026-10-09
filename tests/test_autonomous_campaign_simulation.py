import json
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.simulation import AutonomousCampaignSimulation

def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding="utf-8");return path
def opportunity(i,category):
    return {"opportunity_id":f"opp{i}","category":category,"objective":"awareness","buyer_value":["buyer clarity"],"recommended_message":f"Verified {category}","supporting_fact_ids":[f"fact{i}"],"candidate_asset_ids":[f"asset{i}"],"evidence_strength":90,"buyer_relevance":85,"visual_strength":85,"commercial_strength":70,"lead_generation_potential":60,"score":88,"status":"STRONG","recommended_formats":["Instagram Carousel"],"recommended_platforms":["Instagram Feed"],"restrictions":[],"blocked_claims":[],"audience_hypotheses":["buyer"],"confidence":.9,"layout_sensitive":False,"recommended_patterns":[{"pattern_id":f"pat{i}","creative_family":category}]}

class AutonomousSimulationTests(unittest.TestCase):
    def execute(self,root,production=None):
        cats=["project","architecture","location","interior","amenity","lifestyle"]
        knowledge=write(root/"knowledge.json",{"project_id":"Fixture","knowledge_version":"1","facts":[{"fact_id":f"fact{i}"} for i in range(6)]})
        reci=write(root/"reci.json",{"project_id":"Fixture","reci_version":"1","knowledge_version":"1","input_fingerprint":"fp","creative_library_version":"1","opportunities":[opportunity(i,c) for i,c in enumerate(cats)]})
        library=write(root/"library.json",{"library_version":"1","patterns":[]})
        inventory=write(root/"inventory.json",{"project_id":"Fixture","inventory_version":"1","assets":[{"asset_id":f"asset{i}"} for i in range(6)]})
        return AutonomousCampaignSimulation(root,now=datetime(2026,8,1,tzinfo=timezone.utc)).run("Fixture",knowledge_path=knowledge,reci_path=reci,library_path=library,inventory_path=inventory,production_evidence=production)
    def test_three_cycle_isolated_certification(self):
        with TemporaryDirectory() as d:
            root=Path(d);report=json.loads(self.execute(root,{"production_contract_version":"1","production_items":12,"VDCs":12,"creative_quality":94,"visual_variation":90,"brand_integrity":100,"qa_reliability":98}).read_text(encoding="utf-8"))
            self.assertEqual(report["campaign_cycles"]["cycles"],3);self.assertGreaterEqual(report["campaign_cycles"]["feed_carousel_items"],10);self.assertGreaterEqual(report["campaign_cycles"]["stories"],15)
            self.assertEqual(report["simulated_publishing"]["live_publications"],0);self.assertEqual(report["simulation_identity"]["live_state_paths_written"],[])
    def test_adversarial_safety_has_no_false_acceptance_or_crash(self):
        with TemporaryDirectory() as d:
            report=json.loads(self.execute(Path(d),{"production_items":1,"brand_integrity":100,"qa_reliability":100,"creative_quality":90,"visual_variation":90}).read_text(encoding="utf-8"));result=report["adversarial_results"]
            self.assertEqual(result["false_acceptances"],0);self.assertEqual(result["unhandled_exceptions"],0);self.assertEqual(report["readiness_scores"]["Project Isolation"],100);self.assertEqual(report["readiness_scores"]["Commercial Safety"],100);self.assertEqual(report["readiness_scores"]["Plan Integrity"],100);self.assertEqual(report["readiness_scores"]["Publishing Safety"],100)
    def test_missing_production_evidence_forces_fail(self):
        with TemporaryDirectory() as d:
            report=json.loads(self.execute(Path(d)).read_text(encoding="utf-8"));self.assertEqual(report["final_verdict"],"FAIL — DO NOT ENABLE AUTONOMOUS PUBLISHING");self.assertTrue(report["remaining_issues"]["Critical"])
    def test_reproducible_safety_snapshot(self):
        with TemporaryDirectory() as d:
            root=Path(d);first=self.execute(root,{"production_items":1,"brand_integrity":100,"qa_reliability":100,"creative_quality":90,"visual_variation":90});a=json.loads((first.parent/"regression-snapshot.json").read_text(encoding="utf-8"));second=self.execute(root,{"production_items":1,"brand_integrity":100,"qa_reliability":100,"creative_quality":90,"visual_variation":90});b=json.loads((second.parent/"regression-snapshot.json").read_text(encoding="utf-8"));self.assertEqual(a,b)

if __name__=="__main__":unittest.main()
