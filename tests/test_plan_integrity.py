from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.plan_integrity import (make_plan_record, validate_layout_claims,
    validate_package_layouts, validate_plan_contract, write_plan_inventory)


def layout(asset_id="layout-270",project="A",area=270,bedrooms=3,state="VERIFIED",kind="unit_layout"):
    from tests.unit_plan_fixtures import source_plan
    asset = source_plan(project=project, area=area, bedrooms=bedrooms)
    asset.update(asset_id=asset_id, asset_type=kind, relationship_status=state)
    return make_plan_record(asset)



class UnitLayoutIntegrityTests(unittest.TestCase):
    def test_exact_area_and_bedroom_match_passes(self):
        self.assertEqual(validate_layout_claims(layout(),{"area_sqm":270,"bedrooms":3,"unit_type":"Type B"},expected_project="A"),[])

    def test_wrong_area_and_bedroom_fail(self):
        errors=validate_layout_claims(layout(),{"area_sqm":250,"bedrooms":4},expected_project="A")
        self.assertTrue(any("area_sqm mismatch" in x for x in errors));self.assertTrue(any("bedrooms mismatch" in x for x in errors))

    def test_same_project_does_not_make_false_relationship(self):
        first=layout();second=layout("layout-320",area=320)
        self.assertTrue(validate_layout_claims(first,{"area_sqm":second["unit_identity"]["area_sqm"]},expected_project="A"))

    def test_ambiguous_relationship_blocks_specific_claim(self):
        record=layout(state="AMBIGUOUS")
        self.assertIn("exact layout-to-fact relationship is not VERIFIED",validate_layout_claims(record,{"area_sqm":270},expected_project="A"))

    def test_floor_plan_cannot_become_unit_layout(self):
        record=layout(kind="floor_plan")
        errors=validate_layout_claims(record,{"area_sqm":270},expected_project="A")
        self.assertTrue(any("cannot be marketed as an individual unit layout" in x for x in errors))

    def test_crop_and_branding_obstruction_fail(self):
        record=layout();contract={"plan_integrity":record,"source_image":{"crop_mode":"controlled_crop","placement":[0,0,1000,800]},"graphics":{"overlay_geometry":[0,700,1000,900]}}
        errors=validate_plan_contract(contract);self.assertTrue(any("cropped" in x for x in errors));self.assertTrue(any("obstruction" in x for x in errors))

    def test_caption_and_carousel_mismatch_fail(self):
        inventory={"project_id":"A","assets":[layout(),layout("layout-320",area=320)]}
        wrong={"caption":{"full_caption":"This 250 m² 3-bedroom Type B residence"},"source_asset_ids":["layout-270"],"image":{}}
        self.assertTrue(any("area_sqm mismatch" in x for x in validate_package_layouts(wrong,inventory,expected_project="A")))
        carousel={"master_caption":{"full_caption":"This 270 m² residence"},"slides":[{"source_asset_ids":["layout-270"]},{"source_asset_ids":["layout-320"]}]}
        self.assertTrue(any("carousel/layout mismatch" in x for x in validate_package_layouts(carousel,inventory,expected_project="A")))

    def test_cross_project_contamination_fails(self):
        self.assertIn("plan project mismatch",validate_layout_claims(layout(project="B"),{"area_sqm":270},expected_project="A"))


    def test_same_document_wrong_page_cannot_verify_relationship(self):
        record=layout()
        record["evidence"]["area_sqm"][0]["source_page"]=13
        rebuilt=make_plan_record(record)
        self.assertEqual(rebuilt["relationship_status"],"UNVERIFIED")
        self.assertFalse(rebuilt["marketing_eligible"])

    def test_cross_asset_evidence_cannot_verify_relationship(self):
        record=layout()
        record["evidence"]["area_sqm"][0]["asset_id"]="layout-other"
        rebuilt=make_plan_record(record)
        self.assertEqual(rebuilt["relationship_status"],"UNVERIFIED")

    def test_cross_project_evidence_cannot_verify_relationship(self):
        record=layout()
        record["evidence"]["bedrooms"][0]["source_project"]="B"
        rebuilt=make_plan_record(record)
        self.assertEqual(rebuilt["relationship_status"],"UNVERIFIED")

    def test_missing_source_hash_downgrades_verified_record(self):
        record=layout()
        record["source_hash"]=None
        rebuilt=make_plan_record(record)
        self.assertEqual(rebuilt["relationship_status"],"UNVERIFIED")

    def test_floor_plan_with_unit_identity_is_conflicted_and_not_marketing_eligible(self):
        record=layout(kind="floor_plan")
        self.assertEqual(record["relationship_status"],"CONFLICTED")
        self.assertFalse(record["marketing_eligible"])

    def test_layout_claim_without_linked_plan_asset_fails_closed(self):
        inventory={"project_id":"A","assets":[layout()]}
        package={"caption":{"full_caption":"This 270 m² 3-bedroom Type B residence"},"source_asset_ids":[],"image":{}}
        self.assertIn("layout-specific claim has no exact source plan asset",validate_package_layouts(package,inventory,expected_project="A"))

    def test_unknown_cross_inventory_asset_reference_fails(self):
        inventory={"project_id":"A","assets":[layout()]}
        package={"caption":{"full_caption":"This 270 m² residence"},"source_asset_ids":["missing-plan"],"image":{}}
        errors=validate_package_layouts(package,inventory,expected_project="A")
        self.assertIn("package references plan asset outside verified project inventory",errors)

    def test_multi_layout_master_caption_cannot_bind_single_specification(self):
        inventory={"project_id":"A","assets":[layout(),layout("layout-320",area=320)]}
        package={"master_caption":{"full_caption":"3-bedroom residence"},"slides":[{"source_asset_ids":["layout-270"]},{"source_asset_ids":["layout-320"]}]}
        errors=validate_package_layouts(package,inventory,expected_project="A")
        self.assertTrue(any("carousel/layout mismatch" in x or "master caption cannot bind" in x for x in errors))

    def test_dedicated_inventory_preserves_identity_and_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=write_plan_inventory("A",root,[{"asset_id":"layout-270","project_id":"A","asset_type":"unit_layout","confidence":.99,"source_document":"brochure.pdf","source_page":12,"source_path":"original.png","source_hash":"abc","relationship_status":"UNVERIFIED"}])
            item=json.loads(path.read_text())["assets"][0];self.assertEqual((item["asset_id"],item["source_hash"],item["source_page"]),("layout-270","abc",12))
            self.assertTrue((root/"output/source-images/A/plans/unit-layouts").is_dir())


if __name__=="__main__":unittest.main()
