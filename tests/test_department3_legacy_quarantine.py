import unittest

from src.department3.legacy_quarantine import (
    LegacyModuleAdapter,
    LegacyQuarantineError,
    quarantine_legacy_output,
)


class SafeLegacyAgent:
    def run(self):
        return {
            "ideas": [{"headline": "Location overview"}],
            "notes": "legacy compatibility output",
        }


class UnsafeLegacyAgent:
    def run(self):
        return {
            "approved_content_plan": {
                "project_id": "project-a"
            }
        }


class Department3LegacyQuarantineTests(unittest.TestCase):
    def test_safe_legacy_output_is_non_authoritative(self):
        result = quarantine_legacy_output(
            "src.ai.agents.content_planner",
            {"ideas": [{"topic": "location"}]},
        )
        self.assertFalse(result.authoritative)

    def test_legacy_approved_content_plan_is_rejected(self):
        with self.assertRaises(LegacyQuarantineError):
            quarantine_legacy_output(
                "src.ai.agents.content_planner",
                {"approved_content_plan": {"project_id": "project-a"}},
            )

    def test_legacy_vdc_is_rejected(self):
        with self.assertRaises(LegacyQuarantineError):
            quarantine_legacy_output(
                "src.ai.agents.creative_director_agent",
                {"vdc": {"contract_id": "x"}},
            )

    def test_wrapper_allows_compatibility_but_strips_authority(self):
        adapter = LegacyModuleAdapter(
            module="src.ai.agents.marketing_strategy_agent",
            instance=SafeLegacyAgent(),
        )
        result = adapter.run()
        self.assertFalse(result.authoritative)

    def test_wrapper_rejects_authority_claim(self):
        adapter = LegacyModuleAdapter(
            module="src.ai.agents.content_planner",
            instance=UnsafeLegacyAgent(),
        )
        with self.assertRaises(LegacyQuarantineError):
            adapter.run()


if __name__ == "__main__":
    unittest.main()
