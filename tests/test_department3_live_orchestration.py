import unittest

from src.department3.live_orchestration import LiveDepartment3Orchestrator


class CreativeEngine:
    def build(self, project_id):
        return {"project_id": project_id, "opportunities": [{"type": "location"}]}


class CampaignEngine:
    def build(self, project_id):
        return {"project_id": project_id, "campaign_stage": "awareness"}


class Department3LiveOrchestrationTests(unittest.TestCase):
    def test_live_orchestrator_is_single_conversion_boundary(self):
        result = LiveDepartment3Orchestrator().approve(
            project_id="project-a",
            creative_engine=CreativeEngine(),
            creative_args=("project-a",),
            campaign_engine=CampaignEngine(),
            campaign_args=("project-a",),
            candidates=[{
                "project_id": "project-a",
                "production_item_id": "item-1",
                "objective": "Communicate location advantage",
                "audience": "buyer",
                "proposition": "Verified location advantage",
                "content_category": "location",
                "format_intent": "story",
                "approved_source_asset_ids": ["asset-1"],
                "evidence": [{"fact_id": "fact-1", "confidence": 0.98}],
            }],
        )
        decision = result.approved_content_plan.decisions[0]
        self.assertEqual(decision.format_intent, "story")
        self.assertEqual(len(decision.advisory_fingerprints), 2)
        self.assertFalse(result.creative_intelligence.authoritative)
        self.assertFalse(result.campaign_intelligence.authoritative)


if __name__ == "__main__":
    unittest.main()
