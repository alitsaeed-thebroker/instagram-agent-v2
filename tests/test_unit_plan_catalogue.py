from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import fitz

from src.plan_integrity import make_plan_record, validate_package_layouts, validate_plan_contract
from src.unit_plan_catalogue import extract_catalogue_leaves, inspect_catalogue
from src.production.workflow import ProductionWorkflow, ValidationError, _index


def catalogue_fixture(path, *, first_area=192, built_up=396.5, duplicate_type=False, omit_marker=False):
    with fitz.open() as document:
        page = document.new_page(width=600, height=300)
        page.insert_text((20, 25), "Beverly Hills features only standalone villas", fontsize=10)
        page.insert_text((20, 45), "Plans & Layouts", fontsize=10)
        for index, side in enumerate(("right", "left")):
            page = document.new_page(width=600, height=300)
            base = 300 if side == "right" else 0
            if index == 0:
                page.insert_text((20, 100), "Type D", fontsize=14)
                page.insert_text((20, 130), "345M2", fontsize=14)
                if duplicate_type:
                    page.insert_text((20, 170), "Type D", fontsize=14)
            page.insert_text((base+10, 20), "Ground Floor" if index == 0 else "First Floor", fontsize=14)
            page.insert_text((base+100, 35), "Ground F. Area: 204.5m2", fontsize=8)
            page.insert_text((base+100, 50), f"First F. Area: {first_area}m2", fontsize=8)
            page.insert_text((base+100, 65), f"Buildup Area: {built_up}m2", fontsize=8)
            for number in range(1, (2 if index == 0 else 4)):
                page.insert_text((base+10, 85+number*45), f"{number:02d} | M.BED ROOM", fontsize=8)
                page.insert_text((base+10, 99+number*45), "20.0 M2", fontsize=8)
                if not omit_marker:
                    page.insert_text((base+150, 85+number*45), f"{number:02d}", fontsize=8)
            page.draw_rect(fitz.Rect(base+130, 90, base+250, 250))
        document.save(path)


class CatalogueRelationshipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pdf = self.root/"catalogue.pdf"

    def tearDown(self):
        self.temp.cleanup()

    def records(self, **kwargs):
        catalogue_fixture(self.pdf, **kwargs)
        assets, candidates = extract_catalogue_leaves("Beverly Hills", self.pdf, self.root/"leaves")
        return [make_plan_record(asset) for asset in assets], assets, candidates

    def test_complete_linked_villa_verifies_from_both_floor_legends(self):
        records, assets, candidates = self.records()
        self.assertEqual(candidates[0]["bedrooms"], 4)
        self.assertTrue(all(record["marketing_eligible"] for record in records))
        self.assertEqual(records[0]["unit_identity"]["area_sqm"], 396.5)
        self.assertEqual(records[0]["unit_plan_relationship"]["catalogue_relationship"]["advertised_area_meaning"],
                         "UNSPECIFIED_IN_SOURCE")
        self.assertEqual(make_plan_record(records[0]), records[0])
        self.assertEqual(_index({"assets":records}, "asset_id")[records[0]["asset_id"]], records[0])

    def test_area_conflict_duplicate_type_and_missing_plan_marker_fail_closed(self):
        for kwargs in ({"built_up":328}, {"duplicate_type":True}, {"omit_marker":True}):
            with self.subTest(kwargs=kwargs):
                directory=self.root/str(len(list(self.root.iterdir())))
                directory.mkdir()
                pdf=directory/"catalogue.pdf"
                catalogue_fixture(pdf, **kwargs)
                assets,candidates=extract_catalogue_leaves("Beverly Hills",pdf,directory/"leaves")
                self.assertTrue(candidates[0]["reasons"])
                self.assertTrue(all(not make_plan_record(asset)["marketing_eligible"] for asset in assets))

    def test_complete_set_caption_passes_and_partial_or_wrong_unit_fails(self):
        records, assets, candidates = self.records()
        inventory={"project_id":"Beverly Hills","assets":records}
        package={"master_caption":{"full_caption":"Type D villa layout, 4-bedroom, 396.5 sqm built-up."},
                 "slides":[{"source_asset_ids":[record["asset_id"]]} for record in records]}
        self.assertEqual(validate_package_layouts(package,inventory,expected_project="Beverly Hills"),[])
        partial=deepcopy(package);partial["slides"].pop()
        self.assertIn("complete villa unit requires all canonical floor plan assets",
                      validate_package_layouts(partial,inventory,expected_project="Beverly Hills"))
        wrong=deepcopy(package);wrong["master_caption"]["full_caption"]="Type E villa layout, 4-bedroom, 345 sqm."
        self.assertTrue(validate_package_layouts(wrong,inventory,expected_project="Beverly Hills"))

    def test_half_leaf_substitution_and_wrong_plan_type_are_rejected(self):
        records, assets, candidates = self.records()
        for updates in ({"asset_type":"floor_plan"}, {"source_region":[300,0,500,300]},
                        {"asset_id":"wrong"}, {"project_id":"Other"}):
            asset={**assets[0],**updates}
            self.assertFalse(make_plan_record(asset)["marketing_eligible"])

    def test_asset_intelligence_uses_structural_source_proof(self):
        from src.ai.agents.asset_intelligence_agent import _with_provenance
        from tests.test_asset_intelligence_agent import _semantic
        records,assets,candidates=self.records()
        semantic=_semantic("floor_plan")
        analyzed=_with_provenance(semantic,assets[0],Path(assets[0]["source_path"]),"Beverly Hills","fixture","analyzed")
        self.assertEqual(analyzed["asset_type"],"villa_layout")
        self.assertTrue(analyzed["marketing_eligible"],analyzed["review_reasons"])
        self.assertEqual(analyzed["unit_identity"]["bedrooms"],4)

    def test_render_size_controls_source_label_legibility(self):
        records, assets, candidates = self.records()
        record=records[0]
        contract={"project_id":"Beverly Hills","asset_id":record["asset_id"],"plan_integrity":record,
                  "source_image":{"asset_type":"villa_layout","path":record["source_path"],
                                  "crop_mode":"fit","placement":[0,0,1080,1080]},
                  "graphics":{"overlay_geometry":[0,1100,1080,1300]}}
        self.assertEqual(validate_plan_contract(contract),[])
        contract["source_image"]["placement"]=[0,0,200,200]
        self.assertTrue(any("unreadable" in error for error in validate_plan_contract(contract)))

    def test_processor_blocks_unverified_record_before_rendering(self):
        records, assets, candidates = self.records(built_up=328)
        record=records[0]
        prompt={"project_id":"Beverly Hills","prompt_type":"floorplan_presentation",
                "target_width":1080,"target_height":1350,
                "source_asset_ids":[record["asset_id"]],"source_asset_paths":[record["source_path"]],
                "source_hashes":[record["source_hash"]]}
        with self.assertRaisesRegex(ValidationError,"REVIEW_REQUIRED"):
            ProductionWorkflow("Beverly Hills")._validate(prompt,{},set([record["asset_id"]]),{record["asset_id"]:record})


if __name__ == "__main__":
    unittest.main()
