from __future__ import annotations
import unittest
from src.post_package.grounding import authoritative_facts, make_claim, remove_unsupported_claims, validate_claims

class FactGroundingTests(unittest.TestCase):
    def setUp(self):
        self.project="Project A"
        def ev(page,value):
            return {"evidence_id":f"ev_{page}","source_project":self.project,"source_file":"catalogue.pdf","source_document":"catalogue.pdf","source_id":"src_catalogue","source_sha256":"hash_catalogue","source_page":page,"page":page,"source_text":value,"extraction_method":"test_authoritative_fixture","support_status":"direct"}
        self.knowledge={"canonical_intelligence":{
            "project_namespace":self.project,"schema_version":"2.0.0","contract_role":"authoritative_department2_relational_intelligence",
            "entities":[{"entity_id":"project_a","entity_type":"project","project_namespace":self.project,"label":"Verified Place","parent_entity_id":None,"attributes":{}}],
            "facts":[
                {"fact_id":"fact_name","entity_id":"project_a","fact_type":"project.project_name","value":"Verified Place","unit":None,"currency":None,"state":"VERIFIED","confidence":1.0,"authority":90,"marketing_eligible":True,"provenance":[ev(3,"Verified Place")],"relationship_context":{"project_namespace":self.project},"effective_date":None,"conflicts":[]},
                {"fact_id":"fact_location","entity_id":"project_a","fact_type":"project.location","value":"120m Road","unit":None,"currency":None,"state":"VERIFIED","confidence":1.0,"authority":90,"marketing_eligible":True,"provenance":[ev(4,"120m Road")],"relationship_context":{"project_namespace":self.project},"effective_date":None,"conflicts":[]},
            ],"conflicts":[],"unknowns":[],"metadata":{}
        }}
        self.facts=authoritative_facts(self.knowledge,self.project);self.name=next(x for x in self.facts.values() if x["path"].endswith("project_name"));self.location=next(x for x in self.facts.values() if x["path"].endswith("location"))
    def caption(self,claim,refs):return {"full_caption":claim,"claims":[make_claim(claim,"project_identity",refs)],"verified_fact_refs":refs}
    def test_correct_authoritative_fact_passes(self):self.assertEqual(validate_claims(self.caption("Verified Place",[self.name["fact_id"]]),self.facts,self.project)["status"],"grounded")
    def test_missing_and_unrelated_fact_block(self):
        self.assertEqual(validate_claims(self.caption("Verified Place",[]),self.facts,self.project)["diagnostics"][0]["reason"],"missing_fact_reference")
        self.assertEqual(validate_claims(self.caption("Verified Place",[self.location["fact_id"]]),self.facts,self.project)["diagnostics"][0]["reason"],"unrelated_fact_reference")
    def test_cross_project_and_unknown_fact_fail_closed(self):
        foreign={k:{**v,"project_id":"Project B"} for k,v in self.facts.items()};self.assertEqual(validate_claims(self.caption("Verified Place",[self.name["fact_id"]]),foreign,self.project)["diagnostics"][0]["reason"],"fact_project_mismatch")
        self.assertEqual(validate_claims(self.caption("Verified Place",["fact_unknown"]),self.facts,self.project)["diagnostics"][0]["reason"],"fact_not_authoritative")
    def test_numeric_mismatch_and_commercial_without_commercial_fact_block(self):
        self.assertEqual(validate_claims(self.caption("Located on 100m Road",[self.location["fact_id"]]),self.facts,self.project)["diagnostics"][0]["reason"],"unsupported_numeric_claim")
        result=validate_claims(self.caption("Guaranteed return at Verified Place",[self.name["fact_id"]]),self.facts,self.project);self.assertEqual(result["diagnostics"][0]["reason"],"unsupported_commercial_claim")
    def test_nonfactual_copy_needs_no_fake_reference(self):self.assertEqual(validate_claims({"full_caption":"Your private world","claims":[make_claim("Your private world","creative",[],factual=False)],"verified_fact_refs":[]},self.facts,self.project)["status"],"grounded")
    def test_mixed_copy_binds_only_factual_claim(self):
        value={"full_caption":"Your private world. Verified Place.","claims":[make_claim("Your private world","creative",[],factual=False),make_claim("Verified Place","project_identity",[self.name["fact_id"]])],"verified_fact_refs":[self.name["fact_id"]]};self.assertEqual(validate_claims(value,self.facts,self.project)["grounded_claim_count"],1)
    def test_visual_reference_cannot_substitute_and_recovery_does_not_invent(self):
        value=self.caption("Located on 100m Road",["src_visual"]);check=validate_claims(value,self.facts,self.project);self.assertEqual(check["status"],"blocked");recovered=remove_unsupported_claims(value,check);self.assertEqual(recovered["verified_fact_refs"],[]);self.assertFalse(recovered["grounding_recovery"]["invented_facts"])
    def test_stale_or_conflicted_fact_blocks(self):
        stale={k:{**v,"status":"conflicted"} for k,v in self.facts.items()};self.assertEqual(validate_claims(self.caption("Verified Place",[self.name["fact_id"]]),stale,self.project)["diagnostics"][0]["reason"],"fact_stale_or_conflicted")

if __name__=="__main__":unittest.main()
