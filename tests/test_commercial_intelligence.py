"""Regression coverage for canonical real-estate commercial intelligence."""

from __future__ import annotations

import unittest
import tempfile

from src.knowledge.commercial import (
    extract_document_intelligence, resolve_project_intelligence, verified_fact,
)
from src.knowledge.document_classifier import DocumentType
from src.knowledge.fusion import fuse_knowledge
from src.knowledge.schema import ProjectIdentity, ProjectKnowledge
from src.knowledge.storage import load_authoritative_project_intelligence, save_project_knowledge
from pathlib import Path


def doc(text: str, name: str = "Price List V02.pdf", kind: DocumentType = DocumentType.PRICE_LIST, project: str = "P") -> dict:
    return extract_document_intelligence(f"## Page 3\n\n{text}", project=project, source_file=name,
        document_type=kind, classification_confidence=.98)


def facts(text: str, **kwargs):
    return doc(text, **kwargs)["facts"]


class CommercialExtractionTests(unittest.TestCase):
    def one(self, text: str, fact_type: str):
        return next(x for x in facts(text) if x["fact_type"] == fact_type)

    def test_extract_starting_price_and_qualifier(self):
        fact=self.one("Starting from $144,900", "starting_price")
        self.assertEqual((fact["value"],fact["currency"],fact["qualifier"]),(144900,"USD","starting_from"))
        self.assertEqual(fact["evidence"][0]["page"],3)

    def test_extract_exact_unit_price(self):
        self.assertEqual(self.one("Unit price: USD 250,000", "total_unit_price")["value"],250000)

    def test_extract_price_per_sqm_not_total_price(self):
        found=facts("USD 850 per sqm")
        self.assertEqual([x["fact_type"] for x in found],["price_per_sqm"])

    def test_price_per_sqft_is_intentionally_ignored(self):
        self.assertEqual(facts("US$ 90/sqft"), [])

    def test_price_range_is_intentionally_ignored(self):
        self.assertEqual(facts("Price range: $140,000 - $190,000"), [])

    def test_booking_amount_is_intentionally_ignored(self):
        self.assertEqual(facts("Booking amount: $5,000"), [])

    def test_reservation_fee_is_intentionally_ignored(self):
        self.assertEqual(facts("Reservation fee AED 10,000"), [])

    def test_down_payment_is_intentionally_ignored(self):
        self.assertEqual(facts("20% down payment"), [])

    def test_discount_is_intentionally_ignored(self):
        self.assertEqual(facts("5% discount"), [])

    def test_installment_schedule_is_intentionally_ignored(self):
        self.assertEqual(facts("26.7% second installment"), [])

    def test_milestone_payment_is_intentionally_ignored(self):
        self.assertEqual(facts("30% at structure completion"), [])

    def test_service_and_maintenance_charges_are_intentionally_ignored(self):
        self.assertEqual(facts("Service charge: USD 2,000\nMaintenance fee: $500"), [])

    def test_currency_normalization(self):
        self.assertEqual(self.one("Starting from US$ 1,000", "starting_price")["currency"],"USD")

    def test_marketing_claim_not_verified_fact(self):
        result=doc("Prime investment destination with excellent ROI")
        self.assertFalse(result["facts"]);self.assertEqual(result["marketing_claims"][0]["claim_type"],"marketing_claim")

    def test_roi_not_invented(self):
        result=doc("Price: $150,000. Rent: $1,500/month")
        self.assertNotIn("roi",{x["fact_type"] for x in result["facts"]})

    def test_txt_and_docx_locations_for_allowed_prices(self):
        txt=extract_document_intelligence("## Source block 1\n\n- Original filename: pricing.txt\n- Project: P\n- Document location: lines 2-3\n\nUnit A101 starting price: $100,000",project="P",source_file="pricing.txt",document_type=DocumentType.PROJECT_NOTES)
        word=extract_document_intelligence("## Source block 1\n\n- Original filename: pricing.docx\n- Project: P\n- Document location: paragraph 7\n\nPrice per sqm: USD 850",project="P",source_file="pricing.docx",document_type=DocumentType.PRICE_LIST)
        self.assertEqual(txt["facts"][0]["evidence"][0]["line_range"],"2-3")
        self.assertEqual(word["facts"][0]["evidence"][0]["paragraph"],7)


class CommercialResolutionTests(unittest.TestCase):
    def test_missing_price_is_unavailable_and_payment_intelligence_disabled(self):
        result=resolve_project_intelligence([doc("Swimming pool")],"P")
        self.assertEqual(result["pricing"]["status"],"unavailable")
        self.assertEqual(result["payment_plan"]["status"],"not_supported")
        self.assertEqual(result["payment_plans"],[])

    def test_same_fact_multiple_sources_deduplicates(self):
        result=resolve_project_intelligence([doc("Starting from $100,000","Price List V01.pdf"),doc("Starting from USD 100,000","Catalogue.pdf",DocumentType.CATALOGUE)],"P")
        fact=result["pricing"]["facts"][0]
        self.assertEqual(len(fact["evidence"]),2)

    def test_newer_official_price_list_wins_and_history_remains(self):
        result=resolve_project_intelligence([doc("Starting from $140,000","Price List V02.pdf"),doc("Starting from $144,900","Price List V03.pdf")],"P")
        self.assertEqual(result["pricing"]["facts"][0]["value"],144900)
        self.assertEqual(len(result["conflicts"][0]["candidates"]),2)

    def test_catalogue_does_not_override_price_list(self):
        result=resolve_project_intelligence([doc("Starting from $140,000","Catalogue.pdf",DocumentType.CATALOGUE),doc("Starting from $144,900")],"P")
        self.assertEqual(result["pricing"]["facts"][0]["value"],144900)

    def test_equal_authority_conflict_unresolved(self):
        result=resolve_project_intelligence([doc("Starting from $100,000","A.pdf"),doc("Starting from $110,000","B.pdf")],"P")
        self.assertEqual(result["pricing"]["status"],"conflicting")
        self.assertFalse(result["pricing"]["facts"])
        self.assertIsNone(result["conflicts"][0]["selected_value"])

    def test_payment_plan_terms_are_never_extracted(self):
        result=resolve_project_intelligence([doc("20% down payment. 53.4% second installment",kind=DocumentType.PAYMENT_PLAN)],"P")
        self.assertEqual(result["payment_plan"]["status"],"not_supported")
        self.assertEqual(result["payment_plans"],[])
        self.assertEqual(result["commercial_terms"],[])

    def test_price_math_mismatch_is_warning_not_override(self):
        result=resolve_project_intelligence([doc("Area 170 sqm. Price per sqm: $850. Total price: $144,900")],"P")
        total=next(x for x in result["pricing"]["facts"] if x["fact_type"]=="total_unit_price")
        self.assertEqual(total["value"],144900)
        self.assertIn("calculated_total_mismatch",result["warnings"])

    def test_complete_payment_plan_text_is_still_ignored(self):
        result=resolve_project_intelligence([doc("20% down payment. 80% at handover",kind=DocumentType.PAYMENT_PLAN)],"P")
        self.assertEqual(result["payment_plan"]["status"],"not_supported")
        self.assertEqual(result["payment_plans"],[])

    def test_cross_project_isolation(self):
        other=doc("Starting from $1",project="Other")
        result=resolve_project_intelligence([other,doc("Starting from $2")],"P")
        self.assertEqual(result["pricing"]["facts"][0]["value"],2)

    def test_cross_project_payment_plan_text_is_ignored_for_all_projects(self):
        other=doc("90% down payment",project="Other",kind=DocumentType.PAYMENT_PLAN)
        result=resolve_project_intelligence([other,doc("20% down payment",kind=DocumentType.PAYMENT_PLAN)],"P")
        self.assertEqual(result["payment_plan"]["status"],"not_supported")
        self.assertEqual(result["payment_plans"],[])

    def test_fact_without_provenance_not_verified(self):
        self.assertFalse(verified_fact({"fact_type":"starting_price","value":10,"status":"verified","source_project":"P"},"P"))

    def test_verified_fact_gate_requires_unit_scope_for_unit_starting_price(self):
        result=resolve_project_intelligence([doc("Unit A101 starting price: $100,000")],"P")
        self.assertTrue(verified_fact(result["pricing"]["facts"][0],"P"))

    def test_unknown_document_does_not_gain_high_authority(self):
        unknown=doc("Starting from $90,000","Unknown.pdf",DocumentType.UNKNOWN)
        official=doc("Starting from $100,000","Price List.pdf",DocumentType.PRICE_LIST)
        result=resolve_project_intelligence([unknown,official],"P")
        self.assertEqual(result["pricing"]["facts"][0]["value"],100000)

    def test_developer_equal_authority_conflict_is_cleared(self):
        left=ProjectKnowledge(project_identity=ProjectIdentity(project_name="P",developer_name="A",location="L"))
        right=ProjectKnowledge(project_identity=ProjectIdentity(project_name="P",developer_name="B",location="L"))
        left.commercial_intelligence=doc("Starting from $1","A.pdf")
        right.commercial_intelligence=doc("Starting from $1","B.pdf")
        merged,_=fuse_knowledge([(left,DocumentType.PRICE_LIST,Path("A.json")),(right,DocumentType.PRICE_LIST,Path("B.json"))])
        self.assertEqual(merged.project_identity.developer_name,"")
        conflict=next(x for x in merged.commercial_intelligence["conflicts"] if x["fact_type"]=="project_identity.developer_name")
        self.assertEqual(conflict["status"],"CONFLICTING")

    def test_downstream_loader_reads_authoritative_contract_only(self):
        intelligence=resolve_project_intelligence([doc("Starting from $100,000")],"P")
        knowledge=ProjectKnowledge(project_identity=ProjectIdentity(project_name="P",location="L"),commercial_intelligence=intelligence)
        with tempfile.TemporaryDirectory() as directory:
            save_project_knowledge(knowledge,"P",Path(directory))
            loaded=load_authoritative_project_intelligence("P",Path(directory))
        self.assertEqual(loaded["contract_role"],"authoritative_project_intelligence")
        self.assertEqual(loaded["pricing"]["facts"][0]["value"],100000)


if __name__ == "__main__": unittest.main()
