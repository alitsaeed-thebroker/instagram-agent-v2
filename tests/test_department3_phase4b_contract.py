import unittest

from src.department3.authority import (
    AuthorityRole,
    Department3AuthorityError,
    assert_can_create_approved_content_plan,
    assert_can_create_visual_direction_contract,
    role_for,
)


class Department3Phase4BContractTests(unittest.TestCase):
    def test_two_intelligence_engines_are_advisory(self):
        self.assertEqual(
            role_for("src.creative_intelligence.engine"),
            AuthorityRole.ADVISORY_INTELLIGENCE,
        )
        self.assertEqual(
            role_for("src.campaign_intelligence.engine"),
            AuthorityRole.ADVISORY_INTELLIGENCE,
        )

    def test_legacy_modules_cannot_be_promoted(self):
        for module in (
            "src.ai.agents.content_planner",
            "src.ai.agents.creative_director_agent",
            "src.ai.agents.marketing_strategy_agent",
            "src.ai.agents.campaign_planner",
            "src.ai.agents.visual_art_director_agent",
            "src.planning.engine",
        ):
            with self.assertRaises(Department3AuthorityError):
                assert_can_create_approved_content_plan(module)
            with self.assertRaises(Department3AuthorityError):
                assert_can_create_visual_direction_contract(module)


if __name__ == "__main__":
    unittest.main()
