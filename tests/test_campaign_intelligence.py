from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.campaign_intelligence import CampaignIntelligenceEngine

def opp(oid,category,status="STRONG",score=85,evidence=90,visual=80,restrictions=None,layout=False,assets=None,message=None):
    return {"opportunity_id":oid,"category":category,"opportunity_type":category,"title":category.title(),"objective":"awareness","buyer_value":["clarity"],"recommended_message":message or category,
            "supporting_fact_ids":["fact_"+oid],"candidate_asset_ids":assets or ["asset_"+oid],"evidence_strength":evidence,"buyer_relevance":80,"visual_strength":visual,"commercial_strength":70,"lead_generation_potential":60,
            "score":score,"status":status,"recommended_formats":["Instagram Carousel"],"recommended_platforms":["Instagram Feed"],"restrictions":restrictions or [],"blocked_claims":[],"audience_hypotheses":["buyer"],"confidence":.9,"layout_sensitive":layout,"recommended_patterns":[{"pattern_id":"pat_"+category,"creative_family":category}]}

def reci(opps,project="A"):
    return {"project_id":project,"contract_role":"canonical_creative_opportunity_map","reci_version":"1","knowledge_version":"1","input_fingerprint":"fp","creative_library_version":"1","opportunities":opps}

class CampaignIntelligenceTests(unittest.TestCase):
    def engine(self):return CampaignIntelligenceEngine(Path("."),now=datetime(2026,8,1,tzinfo=timezone.utc))
    def build(self,opps,memory=None,performance=None,project="A"):
        inventory={"project_id":project,"inventory_version":"1","assets":[{"asset_id":a} for x in opps for a in x.get("candidate_asset_ids",[])]}
        return self.engine().build(project,{"knowledge_version":"1"},reci(opps,project),{"library_version":"1"},performance or {},inventory, {},memory)
    def test_new_project_is_discovery_and_location_wins_after_architecture_repetition(self):
        state,_=self.build([opp("arch","architecture",score=75),opp("loc","location",score=95)])
        self.assertEqual(state.campaign_stage,"DISCOVERY")
        memory={"project_id":"A","history":[{"publication_id":str(i),"category":"architecture","content_angle":"architecture","asset_ids":[],"status":"published"} for i in range(3)]}
        _,contract=self.build([opp("arch","architecture",score=75),opp("loc","location",score=95)],memory)
        self.assertEqual(contract["next_best_content"]["reci_opportunity_id"],"loc")
    def test_repetition_penalty_changes_next_content(self):
        memory={"project_id":"A","history":[{"publication_id":str(i),"category":"location","content_angle":"prime location","asset_ids":[],"status":"published"} for i in range(3)]}
        _,contract=self.build([opp("loc","location",score=99),opp("amen","amenity",score=85)],memory)
        self.assertEqual(contract["next_best_content"]["reci_opportunity_id"],"amen")
    def test_stale_commercial_and_unverified_layout_blocked(self):
        _,contract=self.build([opp("price","commercial",restrictions=["Stale commercial fact"]),opp("plan","unit",layout=True,status="STRONG",restrictions=["Exact unit layout relationship is not VERIFIED."])])
        self.assertIsNone(contract["next_best_content"]);self.assertEqual({x["status"] for x in contract["conditional_candidates"]},{"BLOCKED"})
    def test_verified_layout_reopens(self):
        _,contract=self.build([opp("plan","unit",layout=True,status="STRONG")])
        self.assertEqual(contract["next_best_content"]["status"],"APPROVED")
    def test_asset_exhaustion_prefers_fresh_assets(self):
        memory={"project_id":"A","history":[{"publication_id":"1","category":"architecture","asset_ids":["hero"],"status":"published"}]}
        _,contract=self.build([opp("old","architecture",assets=["hero"]),opp("new","architecture",assets=["fresh"])],memory)
        self.assertEqual(contract["next_best_content"]["reci_opportunity_id"],"new")
    def test_performance_boost_is_bounded_and_cold_start_not_fabricated(self):
        perf={"learning_version":"1","account_effectiveness":{"category_performance":[{"content_category":"location","average_performance_score":90,"performance_confidence":"MODERATE_CONFIDENCE"}]}}
        _,learned=self.build([opp("loc","location"),opp("arch","architecture")],performance=perf)
        _,cold=self.build([opp("loc","location"),opp("arch","architecture")])
        learned_loc=next(x for x in learned["strategic_queue"] if x["reci_opportunity_id"]=="loc");cold_loc=next(x for x in cold["strategic_queue"] if x["reci_opportunity_id"]=="loc")
        self.assertGreater(learned_loc["performance_context"]["category_score"],cold_loc["performance_context"]["category_score"])
        self.assertEqual(cold_loc["performance_context"]["scope"],"NONE")
    def test_project_isolation(self):
        with self.assertRaises(ValueError):self.engine().build("A",{},reci([opp("x","project")],"B"),{"library_version":"1"},{},{"project_id":"A","assets":[{"asset_id":"asset_x"}]})
        with self.assertRaises(ValueError):self.build([opp("x","project")],{"project_id":"B","history":[]})
    def test_conversion_balance_and_cta(self):
        _,contract=self.build([opp("commercial","commercial"),opp("conversion","conversion"),opp("hero","project")])
        self.assertLessEqual(sum(x["campaign_role"] in {"SELL","CONVERT"} for x in contract["strategic_queue"]),1)
        hero=next(x for x in contract["strategic_queue"] if x["campaign_role"]=="DISCOVER");self.assertIn(hero["cta_intensity"],{"NONE","SOFT"})
    def test_semantic_repetition_and_explainability(self):
        memory={"project_id":"A","history":[{"publication_id":"1","category":"location","content_angle":"Prime Location","asset_ids":[],"status":"published"},{"publication_id":"2","category":"location","content_angle":"Strategic Location","asset_ids":[],"status":"published"},{"publication_id":"3","category":"location","content_angle":"Perfectly Located","asset_ids":[],"status":"published"}]}
        _,contract=self.build([opp("loc","location",message="Connected Living"),opp("project","project")],memory)
        for item in contract["strategic_queue"]:self.assertTrue(item["reason"] and item["why_now"] and item["supporting_fact_ids"] and item["contract_hash"])
    def test_missing_upstream_fails_closed(self):
        with TemporaryDirectory() as d:
            with self.assertRaises(ValueError):self.engine().run(project_id="A",knowledge_path=Path(d)/"none",reci_path=Path(d)/"r",library_path=Path(d)/"l")

if __name__=="__main__":unittest.main()
