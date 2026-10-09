import unittest

from src.department3.advisory import (
    AdvisoryEngineAdapter,
    AdvisoryIntegrationError,
)
from src.department3.integration import Department3CanonicalPlanner


class FakeCreativeIntelligence:
    def build(self, project_id):
        return {
            "project_id": project_id,
            "opportunities": [{"type": "location", "score": 0.95}],
        }


class CrossProjectIntelligence:
    def build(self, project_id):
        return {"project_id": "other-project", "opportunities": []}


class Department3AdvisoryIntegrationTests(unittest.TestCase):
    def test_creative_intelligence_is_advisory_only(self):
        adapter = AdvisoryEngineAdapter(
            provider_module="src.creative_intelligence.engine",
            engine=FakeCreativeIntelligence(),
        )
        env = adapter.build(project_id="project-a", args=("project-a",))
        self.assertFalse(env.authoritative)
        self.assertEqual(env.project_id, "project-a")

    def test_cross_project_advisory_output_fails_closed(self):
        adapter = AdvisoryEngineAdapter(
            provider_module="src.creative_intelligence.engine",
            engine=CrossProjectIntelligence(),
        )
        with self.assertRaises(AdvisoryIntegrationError):
            adapter.build(project_id="project-a", args=("project-a",))

    def test_canonical_planner_consumes_advisory_fingerprint(self):
        adapter = AdvisoryEngineAdapter(
            provider_module="src.creative_intelligence.engine",
            engine=FakeCreativeIntelligence(),
        )
        env = adapter.build(project_id="project-a", args=("project-a",))
        planner = Department3CanonicalPlanner()
        plan = planner.approve(
            project_id="project-a",
            advisory=[env],
            candidates=[
                {
                    "project_id": "project-a",
                    "production_item_id": "item-1",
                    "objective": "Communicate location advantage",
                    "audience": "end-user buyer",
                    "proposition": "Convenient access supported by verified location evidence",
                    "content_category": "location",
                    "format_intent": "story",
                    "approved_source_asset_ids": ["asset-1"],
                    "evidence": [
                        {
                            "fact_id": "fact-1",
                            "source_id": "knowledge-1",
                            "confidence": 0.98,
                        }
                    ],
                }
            ],
        )
        self.assertIn(
            env.fingerprint,
            plan.decisions[0].advisory_fingerprints,
        )


if __name__ == "__main__":
    unittest.main()
