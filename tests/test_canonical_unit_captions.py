from copy import deepcopy
import unittest
from tests.test_unit_plan_catalogue import CatalogueRelationshipTests
from src.post_package.grounding import canonical_unit_facts,make_claim,validate_claims

class CanonicalUnitCaptionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=CatalogueRelationshipTests();self.fixture.setUp()
        self.records,_,_=self.fixture.records()
        self.ids={r["asset_id"] for r in self.records}
    def tearDown(self):self.fixture.tearDown()
    def facts(self,records=None,ids=None,project="Beverly Hills"):
        return canonical_unit_facts({"assets":self.records if records is None else records},project,self.ids if ids is None else ids)
    def test_source_grounding_and_area_basis(self):
        facts=self.facts();values=[f["value"] for f in facts.values()]
        self.assertIn("396.5 m² built-up area",values);self.assertNotIn("345",str(values))
        caption={"claims":[make_claim(f["value"],"unit_plan",[fid]) for fid,f in facts.items()],"verified_fact_refs":list(facts)}
        self.assertEqual(validate_claims(caption,facts,"Beverly Hills")["status"],"grounded")
    def test_partial_floor_set_is_blocked(self):
        with self.assertRaises(ValueError):self.facts(ids={self.records[0]["asset_id"]})
    def test_stale_metadata_and_llm_only_are_blocked(self):
        for field,value in (("unit_identity",{"bedrooms":99}), ("unit_plan_relationship",{"status":"VERIFIED"}), ("source_document_hash","0"*64)):
            records=deepcopy(self.records);records[0][field]=value
            with self.assertRaises(ValueError):self.facts(records=records)
    def test_wrong_project_and_asset_are_blocked(self):
        with self.assertRaises(ValueError):self.facts(project="Other")
        with self.assertRaises(ValueError):self.facts(ids=self.ids|{"wrong-plan"})
    def test_conflicting_source_is_blocked(self):
        records,_,_=self.fixture.records(built_up=328)
        with self.assertRaises(ValueError):self.facts(records=records,ids={r["asset_id"] for r in records})
