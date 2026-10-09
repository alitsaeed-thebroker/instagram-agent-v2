import unittest

from src.department3.authority import (
    AuthorityRole,
    Department3AuthorityError,
    assert_can_create_approved_content_plan,
    assert_can_create_visual_direction_contract,
    assert_can_execute_visual_direction,
    assert_can_write_authoritative_d3_state,
    role_for,
)


class Department3AuthorityPolicyTests(unittest.TestCase):
    def test_exactly_one_strategy_authority(self):
        assert_can_create_approved_content_plan("src.department3.strategy_authority")

    def test_advisory_engines_cannot_write_authoritative_state(self):
        for module in (
            "src.creative_intelligence.engine",
            "src.campaign_intelligence.engine",
        ):
            self.assertEqual(role_for(module), AuthorityRole.ADVISORY_INTELLIGENCE)
            with self.assertRaises(Department3AuthorityError):
                assert_can_write_authoritative_d3_state(module)

    def test_legacy_agents_are_non_authoritative(self):
        for module in (
            "src.ai.agents.content_planner",
            "src.ai.agents.creative_director_agent",
            "src.ai.agents.marketing_strategy_agent",
            "src.ai.agents.campaign_planner",
            "src.ai.agents.visual_art_director_agent",
            "src.planning.engine",
        ):
            self.assertEqual(role_for(module), AuthorityRole.LEGACY_NON_AUTHORITATIVE)
            with self.assertRaises(Department3AuthorityError):
                assert_can_create_approved_content_plan(module)
            with self.assertRaises(Department3AuthorityError):
                assert_can_create_visual_direction_contract(module)
            with self.assertRaises(Department3AuthorityError):
                assert_can_write_authoritative_d3_state(module)

    def test_d4_can_execute_but_not_create_d3_authority(self):
        assert_can_execute_visual_direction("src.branding.composer")
        with self.assertRaises(Department3AuthorityError):
            assert_can_create_approved_content_plan("src.branding.composer")
        with self.assertRaises(Department3AuthorityError):
            assert_can_create_visual_direction_contract("src.branding.composer")


if __name__ == "__main__":
    unittest.main()
