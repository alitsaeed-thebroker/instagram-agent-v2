from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from src.planning.creative_reviewer import RealEstateCreativeReviewer

class RealEstateCreativeReviewerTests(unittest.TestCase):
    def test_portfolio_approves_distinct_grounded_visual_and_rejects_missing_asset(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);project="Commercial Project";paths={x:root/f"{x}.json" for x in ("content","knowledge","strategy","inventory")}
            ideas=[{"content_idea_id":"good","title":"Office Architecture","content_objective":"Present authentic office architecture","concept_summary":"Exterior design","target_persona":"Business owners","funnel_stage":"consideration","selected_source_asset_ids":["src_a"],"selected_fact_refs":["project_identity.project_name"],"source_support_status":"fully_supported","planned_destinations":["instagram"],"feasible_formats":["single_feed_post"],"forbidden_claims":["price"]},{"content_idea_id":"bad","title":"Imagined amenity","selected_source_asset_ids":["src_missing"],"planned_destinations":["instagram"],"feasible_formats":["single_feed_post"]}]
            values={"content":{"project_id":project,"content_ideas":ideas},"knowledge":{"project_identity":{"project_name":project}},"strategy":{"project_id":project},"inventory":{"project_id":project,"assets":[{"asset_id":"src_a","asset_type":"exterior","analysis_status":"analyzed"}]}}
            for k,v in values.items():paths[k].write_text(json.dumps(v))
            original=paths["content"].read_text();content,report=RealEstateCreativeReviewer(root).review(project,paths["content"],paths["knowledge"],paths["strategy"],paths["inventory"]);review=json.loads(report.read_text());result=json.loads(content.read_text());preserved=paths["content"].read_text()
        self.assertEqual([x["content_idea_id"] for x in result["content_ideas"]],["good"]);self.assertEqual({x["content_idea_id"]:x["decision"] for x in review["decisions"]},{"good":"approve","bad":"reject"})
        self.assertEqual(preserved,original)
        self.assertEqual(content.name,f"{project}-content-plan.json")

    def test_canonical_category_inventory_resolves_assets(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);project="P";files={k:root/f"{k}.json" for k in ("content","knowledge","strategy","inventory")}
            idea={"content_idea_id":"a","title":"Exterior","content_objective":"Show architecture","concept_summary":"Authentic exterior","target_persona":"Buyers","funnel_stage":"awareness","selected_source_asset_ids":["src_a"],"selected_fact_refs":["f"],"planned_destinations":["instagram"],"feasible_formats":["single_feed_post"]}
            data={"content":{"project_id":project,"content_ideas":[idea]},"knowledge":{},"strategy":{},"inventory":{"project":project,"available_exterior_images":[{"asset_id":"src_a","asset_type":"exterior","analysis_status":"analyzed"}],"available_floorplans":[]}}
            for k,v in data.items():files[k].write_text(json.dumps(v))
            content,_=RealEstateCreativeReviewer(root).review(project,files["content"],files["knowledge"],files["strategy"],files["inventory"]);result=json.loads(content.read_text())
        self.assertEqual([x["content_idea_id"] for x in result["content_ideas"]],["a"])
    def test_duplicate_portfolio_item_is_not_blindly_approved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);project="P";base={"title":"Office Exterior","content_objective":"Show office exterior","concept_summary":"Architecture","target_persona":"Owners","funnel_stage":"awareness","selected_fact_refs":["f"],"source_support_status":"fully_supported","planned_destinations":["instagram"],"feasible_formats":["single_feed_post"]};ideas=[{**base,"content_idea_id":"a","selected_source_asset_ids":["src_a"]},{**base,"content_idea_id":"b","selected_source_asset_ids":["src_b"]}]
            files={k:root/f"{k}.json" for k in ("content","knowledge","strategy","inventory")};data={"content":{"project_id":project,"content_ideas":ideas},"knowledge":{},"strategy":{},"inventory":{"project_id":project,"assets":[{"asset_id":"src_a","asset_type":"exterior","analysis_status":"analyzed"},{"asset_id":"src_b","asset_type":"exterior","analysis_status":"analyzed"}]}}
            for k,v in data.items():files[k].write_text(json.dumps(v))
            _,report=RealEstateCreativeReviewer(root).review(project,files["content"],files["knowledge"],files["strategy"],files["inventory"]);decisions=json.loads(report.read_text())["decisions"]
        self.assertEqual(decisions[0]["decision"],"approve");self.assertEqual(decisions[1]["decision"],"reject")
if __name__=="__main__":unittest.main()
