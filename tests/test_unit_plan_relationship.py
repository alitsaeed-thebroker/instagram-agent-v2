from copy import deepcopy
import unittest

from src.plan_integrity import make_plan_record, validate_layout_claims, validate_plan_contract
from src.unit_plan_relationship import relationship_errors
from tests.unit_plan_fixtures import source_plan


class CanonicalRelationshipTests(unittest.TestCase):
    def test_valid_source_verifies_without_model_verified_flag(self):
        record = make_plan_record(source_plan())
        self.assertTrue(record["marketing_eligible"], record["review_reasons"])
        self.assertEqual(record["unit_plan_relationship"]["status"], "VERIFIED")
        self.assertEqual(relationship_errors(record), [])
        self.assertEqual(make_plan_record(record), record)

    def test_conflicting_candidate_metadata(self):
        for field, value in (("area_sqm", 900), ("bedrooms", 5), ("unit_type", "Type Z"), ("tower", "East")):
            asset = source_plan()
            asset["unit_identity"][field] = value
            self.assertFalse(make_plan_record(asset)["marketing_eligible"], field)

    def test_missing_provenance(self):
        for field in ("project_id", "asset_id", "source_page", "source_hash", "source_document_hash", "source_document_path"):
            asset = source_plan()
            del asset[field]
            self.assertEqual(make_plan_record(asset)["review_status"], "REVIEW_REQUIRED", field)

    def test_ambiguous_source_and_missing_required_labels(self):
        base = "UNIT PLAN\nProject: A\nUnit Type: Type B\nBedrooms: 3\nArea sqm: 270\nTower: West"
        for text in (base + "\nUnit Type: Type C", base + "\nUNIT PLAN",
                     base.replace("Tower: West", ""), base.replace("Bedrooms: 3", ""),
                     base.replace("UNIT PLAN", "FLOOR PLAN"), base.replace("Project: A", "Project: B")):
            self.assertFalse(make_plan_record(source_plan(text=text))["marketing_eligible"], text)

    def test_llm_only_and_forged_proof_rejected(self):
        asset = source_plan()
        asset.pop("source_document_path")
        asset.update(relationship_status="VERIFIED", marketing_eligible=True,
                     unit_plan_relationship={"status": "VERIFIED"})
        record = make_plan_record(asset)
        self.assertFalse(record["marketing_eligible"])
        record.update(relationship_status="VERIFIED", marketing_eligible=True)
        self.assertTrue(validate_layout_claims(record, {}, expected_project="A"))

    def test_all_non_unit_substitutions_rejected(self):
        for kind in ("floor_plan", "site_plan", "masterplan", "typical_floor_plan", "technical_plan"):
            asset = source_plan()
            asset["asset_type"] = kind
            self.assertFalse(make_plan_record(asset)["marketing_eligible"])

    def test_wrong_image_and_hash_rejected(self):
        asset = source_plan()
        other = source_plan(area=320)
        asset["source_path"] = other["source_path"]
        asset["source_hash"] = other["source_hash"]
        self.assertFalse(make_plan_record(asset)["marketing_eligible"])
        for field in ("source_hash", "source_document_hash"):
            asset = source_plan()
            asset[field] = "0" * 64
            self.assertFalse(make_plan_record(asset)["marketing_eligible"])

    def test_persisted_ambiguity_stays_closed(self):
        asset = source_plan()
        asset["relationship_status"] = "AMBIGUOUS"
        for _ in range(3):
            asset = make_plan_record(asset)
            self.assertFalse(asset["marketing_eligible"])

    def test_unknown_completeness_is_not_inferred_from_protected_regions(self):
        asset = source_plan()
        asset.pop("plan_completeness_status")
        asset["protected_regions"] = [[0, 0, 1200, 1500]]
        self.assertFalse(make_plan_record(asset)["marketing_eligible"])

    def test_case_insensitive_ambiguity_is_preserved(self):
        asset = source_plan()
        asset["relationship_status"] = "ambiguous"
        self.assertFalse(make_plan_record(asset)["marketing_eligible"])

    def test_canonical_proof_and_evidence_tampering_fail_at_consumption(self):
        record = make_plan_record(source_plan())
        record["unit_plan_relationship"]["unit_identity"]["area_sqm"] = 900
        self.assertTrue(validate_layout_claims(record, {}, expected_project="A"))
        record = make_plan_record(source_plan())
        record["evidence"]["area_sqm"][0]["value"] = 900
        self.assertTrue(validate_layout_claims(record, {}, expected_project="A"))

    def test_contract_rechecks_actual_source_and_protects_geometry(self):
        record = make_plan_record(source_plan())
        contract = {"project_id": "A", "asset_id": record["asset_id"], "plan_integrity": record,
                    "source_image": {"asset_type": "unit_layout", "path": record["source_path"],
                                     "crop_mode": "fit", "placement": [0, 0, 500, 600]},
                    "graphics": {"overlay_geometry": [0, 650, 500, 700]}}
        self.assertEqual(validate_plan_contract(contract), [])
        for key, value in (("crop_mode", "fill"), ("rotation", 90),
                           ("path", source_plan(area=320)["source_path"])):
            changed = deepcopy(contract)
            changed["source_image"][key] = value
            self.assertTrue(validate_plan_contract(changed), key)
        changed = deepcopy(contract)
        changed["asset_id"] = "other"
        self.assertTrue(validate_plan_contract(changed))
        changed = deepcopy(contract)
        changed.pop("plan_integrity")
        self.assertTrue(validate_plan_contract(changed))
        changed = deepcopy(contract)
        changed["headline"] = {"visible": True, "text": "Type B", "x": 10, "y": 10, "width": 200, "height": 50}
        self.assertTrue(any("obscures" in error for error in validate_plan_contract(changed)))
        changed = deepcopy(contract)
        changed["headline"] = {"visible": True, "text": "900 sqm", "x": 0, "y": 650, "width": 200, "height": 50}
        self.assertTrue(any("area_sqm mismatch" in error for error in validate_plan_contract(changed)))


if __name__ == "__main__":
    unittest.main()
