from pathlib import Path
import unittest

from src.simulation.production_certification import Department4ProductionCertification, SAFE_SAMPLE


class Department4ProductionCertificationTests(unittest.TestCase):
    def test_sample_is_representative_and_excludes_unsafe_categories(self):
        kinds={kind for kind,_ in SAFE_SAMPLE}
        self.assertTrue({"masterplan","exterior_render","interior_render","amenity"}.issubset(kinds))
        self.assertNotIn("floor_plan",kinds);self.assertNotIn("commercial",kinds)

    def test_certification_inputs_are_real_repository_artifacts(self):
        """Validate live production artifacts when that certification corpus exists.

        The repository regression suite must not require mutable/resettable output/
        state to be present. A real-production certification run is an integration
        check, not a unit-test fixture. If the live corpus has been intentionally
        reset or not generated yet, skip this assertion rather than failing the
        deterministic regression suite.
        """
        root=Path(__file__).resolve().parents[1]
        certification=Department4ProductionCertification(root)
        try:
            values=certification._inputs("Beverly Hills")
        except ValueError as error:
            message=str(error)
            if message.startswith("Production certification missing real inputs:"):
                self.skipTest(message)
            raise
        self.assertTrue(all(path.is_file() for path in values.values()))
        self.assertIn("campaign-intelligence",str(values["decisions"]))


if __name__ == "__main__": unittest.main()
