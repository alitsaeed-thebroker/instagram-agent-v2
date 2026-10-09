from __future__ import annotations

import unittest

from src.knowledge.consumer import (
    canonical_project_identity,
    canonical_verified_facts,
    require_canonical_graph,
)
from src.post_package.grounding import authoritative_facts


def evidence(project: str, value: str, page: int = 1) -> dict:
    return {
        "evidence_id": f"ev_{page}_{abs(hash(value))}",
        "source_project": project,
        "source_file": "fixture.pdf",
        "source_id": "src_fixture",
        "source_sha256": "hash_fixture",
        "source_document": "fixture.pdf",
        "page": page,
        "source_page": page,
        "source_text": value,
        "extraction_method": "test_authoritative_fixture",
        "support_status": "direct",
    }


def canonical_knowledge(project: str = "Project A") -> dict:
    ev_name=evidence(project,"Canonical Name",1)
    ev_loc=evidence(project,"Canonical Road",2)
    ev_price=evidence(project,"USD 850 per sqm",3)
    ev_payment=evidence(project,"20% down payment",4)
    return {
        # Deliberately hostile legacy values: production consumers must ignore them.
        "project":{"name":"WRONG LEGACY NAME","location":"WRONG LEGACY LOCATION"},
        "project_identity":{"project_name":"WRONG IDENTITY","location":"WRONG IDENTITY LOCATION"},
        "fact_provenance":{"project_identity.project_name":[evidence(project,"WRONG IDENTITY",9)]},
        "commercial_intelligence":{
            "contract_role":"authoritative_project_intelligence","project":project,
            "pricing":{"facts":[{"fact_type":"starting_price","value":1,"status":"verified"}]},
            "payment_plan":{"installments":[{"fact_type":"down_payment","percentage":20,"status":"verified"}]},
        },
        "canonical_intelligence":{
            "project_namespace":project,
            "schema_version":"2.0.0",
            "contract_role":"authoritative_department2_relational_intelligence",
            "entities":[{"entity_id":"project_a","entity_type":"project","project_namespace":project,"label":"Canonical Name","parent_entity_id":None,"attributes":{}}],
            "facts":[
                {"fact_id":"fact_name","entity_id":"project_a","fact_type":"project.project_name","value":"Canonical Name","unit":None,"currency":None,"state":"VERIFIED","confidence":1.0,"authority":90,"marketing_eligible":True,"provenance":[ev_name],"relationship_context":{"project_namespace":project},"effective_date":None,"conflicts":[]},
                {"fact_id":"fact_location","entity_id":"project_a","fact_type":"project.location","value":"Canonical Road","unit":None,"currency":None,"state":"VERIFIED","confidence":1.0,"authority":90,"marketing_eligible":True,"provenance":[ev_loc],"relationship_context":{"project_namespace":project},"effective_date":None,"conflicts":[]},
                {"fact_id":"fact_ppsqm","entity_id":"project_a","fact_type":"commercial.price_per_sqm","value":850,"unit":None,"currency":"USD","state":"VERIFIED","confidence":1.0,"authority":90,"marketing_eligible":True,"provenance":[ev_price],"relationship_context":{"project_namespace":project,"relationship_status":"project_scope"},"effective_date":None,"conflicts":[]},
                # This is syntactically canonical but intentionally outside current commercial policy.
                {"fact_id":"fact_payment","entity_id":"project_a","fact_type":"commercial.down_payment","value":20,"unit":"percent","currency":None,"state":"VERIFIED","confidence":1.0,"authority":90,"marketing_eligible":True,"provenance":[ev_payment],"relationship_context":{"project_namespace":project},"effective_date":None,"conflicts":[]},
            ],
            "conflicts":[],"unknowns":[],"metadata":{},
        },
    }


class CanonicalConsumerMigrationTests(unittest.TestCase):
    def test_missing_canonical_contract_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"Canonical Department 2"):
            require_canonical_graph({"project":{"name":"Legacy Only"}},expected_project="Project A")

    def test_project_identity_comes_only_from_canonical_graph(self):
        knowledge=canonical_knowledge()
        identity=canonical_project_identity(knowledge,expected_project="Project A")
        self.assertEqual(identity["project_name"],"Canonical Name")
        self.assertEqual(identity["location"],"Canonical Road")
        self.assertNotIn("WRONG",str(identity))

    def test_legacy_fact_provenance_and_flat_commercial_cannot_enter_registry(self):
        knowledge=canonical_knowledge()
        facts=canonical_verified_facts(knowledge,"Project A")
        values={str(x.value) for x in facts.values()}
        self.assertNotIn("WRONG IDENTITY",values)
        self.assertNotIn("1",values)
        self.assertIn("850",values)

    def test_only_three_approved_commercial_fact_types_are_consumable(self):
        facts=canonical_verified_facts(canonical_knowledge(),"Project A",include_commercial=True)
        commercial={x.canonical_path for x in facts.values() if x.commercial}
        self.assertEqual(commercial,{"commercial.price_per_sqm"})

    def test_post_package_grounding_uses_same_canonical_fact_ids(self):
        knowledge=canonical_knowledge()
        consumer=canonical_verified_facts(knowledge,"Project A")
        grounding=authoritative_facts(knowledge,"Project A")
        self.assertEqual(set(grounding),set(consumer))
        self.assertEqual(grounding["fact_name"]["value"],"Canonical Name")
        self.assertEqual(grounding["fact_ppsqm"]["value"],850)

    def test_wrong_canonical_project_cannot_be_aliased_by_legacy_project_name(self):
        knowledge=canonical_knowledge("Project B")
        knowledge["project"]["name"]="Project A"
        knowledge["project_identity"]["project_name"]="Project A"
        with self.assertRaisesRegex(ValueError,"project mismatch"):
            canonical_verified_facts(knowledge,"Project A")


if __name__=="__main__":
    unittest.main()
