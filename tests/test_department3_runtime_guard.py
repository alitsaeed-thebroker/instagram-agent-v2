import unittest

from src.department3.runtime_guard import (
    RuntimeAuthorityViolation,
    assert_noncanonical_output,
)


class Department3RuntimeGuardTests(unittest.TestCase):
    def test_advisory_cannot_emit_approved_plan(self):
        with self.assertRaises(RuntimeAuthorityViolation):
            assert_noncanonical_output(
                "src.creative_intelligence.engine",
                {"approved_content_plan": {"project_id": "x"}},
            )

    def test_campaign_advisory_cannot_emit_vdc(self):
        with self.assertRaises(RuntimeAuthorityViolation):
            assert_noncanonical_output(
                "src.campaign_intelligence.engine",
                {"vdc": {"contract_id": "x"}},
            )

    def test_plain_advisory_is_allowed(self):
        assert_noncanonical_output(
            "src.creative_intelligence.engine",
            {"project_id": "x", "opportunities": []},
        )


if __name__ == "__main__":
    unittest.main()
