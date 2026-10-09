import unittest

from src.department3.advisory import AdvisoryEngineAdapter
from src.department3.integration import Department3CanonicalPlanner


class FakeCreativeIntelligence:
    def build(self, project_id):
        return {
            "project_id": project_id,
            "opportunities": [{"type": "location", "score": 0.95}],
        }


class FakeCampaignIntelligence:
    def build(self, project_id):
        return {
            "project_id": project_id,
            "campaign_stage": "awareness",
        }


class Department3Phase4B1FingerprintTests(unittest.TestCase):
    def test_provider_fingerprint_is_preserved_exactly(self):
        env = AdvisoryEngineAdapter(
            provider_module="src.creative_intelligence.engine",
            engine=FakeCreativeIntelligence(),
        ).build(project_id="project-a", args=("project-a",))

        plan = Department3CanonicalPlanner().approve(
            project_id="project-a",
            advisory=[env],
            candidates=[{
                "project_id": "project-a",
                "production_item_id": "item-1",
                "objective": "Communicate location advantage",
                "audience": "end-user buyer",
                "proposition": "Verified location advantage",
                "content_category": "location",
                "format_intent": "story",
                "approved_source_asset_ids": ["asset-1"],
                "evidence": [{"fact_id": "fact-1", "confidence": 0.98}],
            }],
        )
        self.assertEqual(plan.decisions[0].advisory_fingerprints, (env.fingerprint,))

    def test_multiple_provider_fingerprints_are_preserved_and_sorted(self):
        a = AdvisoryEngineAdapter(
            provider_module="src.creative_intelligence.engine",
            engine=FakeCreativeIntelligence(),
        ).build(project_id="project-a", args=("project-a",))
        b = AdvisoryEngineAdapter(
            provider_module="src.campaign_intelligence.engine",
            engine=FakeCampaignIntelligence(),
        ).build(project_id="project-a", args=("project-a",))

        plan = Department3CanonicalPlanner().approve(
            project_id="project-a",
            advisory=[b, a],
            candidates=[{
                "project_id": "project-a",
                "production_item_id": "item-1",
                "objective": "Build awareness",
                "audience": "buyer",
                "proposition": "Verified project proposition",
                "content_category": "location",
                "format_intent": "feed",
                "approved_source_asset_ids": ["asset-1"],
                "evidence": [{"fact_id": "fact-1"}],
            }],
        )
        self.assertEqual(
            plan.decisions[0].advisory_fingerprints,
            tuple(sorted((a.fingerprint, b.fingerprint))),
        )


if __name__ == "__main__":
    unittest.main()
