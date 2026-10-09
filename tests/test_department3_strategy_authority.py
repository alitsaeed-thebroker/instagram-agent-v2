import unittest

from src.department3.strategy_authority import (
    Department3StrategyAuthority,
    StrategyAuthorityError,
)


class Department3StrategyAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.authority = Department3StrategyAuthority()

    def candidate(self, **overrides):
        base = {
            "project_id": "project-a",
            "production_item_id": "item-1",
            "objective": "Communicate location advantage",
            "audience": "end-user buyer",
            "proposition": "The project is positioned for convenient access",
            "content_category": "location",
            "format_intent": "feed",
            "approved_source_asset_ids": ["asset-1"],
            "evidence": [
                {
                    "fact_id": "fact-location-1",
                    "source_id": "knowledge-1",
                    "confidence": 0.98,
                }
            ],
        }
        base.update(overrides)
        return base

    def test_creates_deterministic_approved_plan(self):
        a = self.authority.approve(project_id="project-a", candidates=[self.candidate()])
        b = self.authority.approve(project_id="project-a", candidates=[self.candidate()])
        self.assertEqual(a.plan_id, b.plan_id)
        self.assertEqual(a.decisions[0].decision_id, b.decisions[0].decision_id)

    def test_cross_project_candidate_fails_closed(self):
        with self.assertRaises(StrategyAuthorityError):
            self.authority.approve(
                project_id="project-a",
                candidates=[self.candidate(project_id="project-b")],
            )

    def test_story_is_first_class(self):
        plan = self.authority.approve(
            project_id="project-a",
            candidates=[
                self.candidate(
                    format_intent="story",
                    story_sequence_role="hook",
                )
            ],
        )
        self.assertEqual(plan.decisions[0].format_intent, "story")
        self.assertEqual(plan.decisions[0].story_sequence_role, "hook")

    def test_reels_are_not_enabled(self):
        with self.assertRaises(StrategyAuthorityError):
            self.authority.approve(
                project_id="project-a",
                candidates=[self.candidate(format_intent="reel")],
            )

    def test_plan_layout_requires_evidence(self):
        with self.assertRaises(StrategyAuthorityError):
            self.authority.approve(
                project_id="project-a",
                candidates=[
                    self.candidate(
                        content_category="unit layout",
                        evidence=[],
                    )
                ],
            )

    def test_duplicate_production_items_fail_closed(self):
        item = self.candidate()
        with self.assertRaises(StrategyAuthorityError):
            self.authority.approve(
                project_id="project-a",
                candidates=[item, item],
            )


if __name__ == "__main__":
    unittest.main()
