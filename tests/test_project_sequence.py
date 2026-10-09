import unittest,tempfile
from pathlib import Path
from datetime import datetime,timezone
from src.project_sequence import contract,sequence_error
from src.publishing.eligibility import select_next_eligible_publication
from src.publishing.ledger import PublicationLedger,record_from_receipt
from tests.test_department5_final_integration import candidate

class ProjectSequenceTests(unittest.TestCase):
    def job(self,category,project="A",priority=1):
        j=candidate(category,project,"feed",[category],priority);j["project_sequence"]=contract(category);return j
    def receipt(self,category,project="A",at="2020-01-01T00:00:00+00:00"):
        return {"project_id":project,"platform":"instagram","status":"published","published_at":at,"project_sequence":contract(category)}
    def test_overview_wins_even_against_high_priority_units(self):
        jobs=[self.job("unit_layout",priority=999),self.job("site_plan",priority=888),self.job("project_overview")]
        r=select_next_eligible_publication({"items":jobs},[],now=datetime.now(timezone.utc),config={})
        self.assertEqual(r["selected_queue_item_id"],"project_overview")
    def test_site_plan_is_second(self):
        self.assertIsNone(sequence_error(self.job("site_plan"),[self.receipt("project_overview")]))
        self.assertTrue(sequence_error(self.job("unit_layout"),[self.receipt("project_overview")]))
    def test_missing_or_failed_required_item_cannot_be_skipped(self):
        self.assertTrue(sequence_error(self.job("unit_layout"),[]))
        self.assertTrue(sequence_error(self.job("site_plan"),[]))
    def test_later_sequence_flexible_after_two_confirmations(self):
        receipts=[self.receipt("project_overview"),self.receipt("site_plan",at="2020-01-02T00:00:00+00:00")]
        for category in ("community","unit_layout","construction","other"):
            self.assertIsNone(sequence_error(self.job(category),receipts))
    def test_wrong_order_wrong_project_and_unknown_history_block(self):
        for history in ([self.receipt("site_plan"),self.receipt("project_overview",at="2020-01-02T00:00:00+00:00")],[self.receipt("project_overview",project="B")],[{"project_id":"A","platform":"instagram","status":"published"}]):
            self.assertTrue(sequence_error(self.job("unit_layout"),history))
    def test_tampering_and_repeated_overview_block(self):
        j=self.job("unit_layout");j["project_sequence"]["required_predecessors"]=[]
        self.assertTrue(sequence_error(j,[]));self.assertTrue(sequence_error(self.job("project_overview"),[self.receipt("project_overview")]))
    def test_sequence_survives_durable_intent_confirmation_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ledger=PublicationLedger(root);ledger.initialize(fresh=True)
            j=self.job("project_overview");j["attempt_token"]="attempt"
            ledger.reserve(j,{"media":[]},"account",{})
            row=ledger.get(j["publication_identity"]);row.update(state="CONFIRMED_PUBLISHED",remote_media_id="remote",publication_timestamp="2020-01-01T00:00:00+00:00")
            ledger.record(row);restored=PublicationLedger(root).records()[0]
            self.assertEqual(restored["project_sequence"],contract("project_overview"))
            self.assertIsNone(sequence_error(self.job("site_plan"),[restored]))

    def test_failed_receipt_does_not_unlock_site_plan(self):
        receipt=self.receipt("project_overview");receipt["status"]="failed"
        self.assertTrue(sequence_error(self.job("site_plan"),[receipt]))
    def test_site_plan_cannot_be_a_location_map(self):
        from tests import test_post_package as fixtures
        from src.post_package import PostPackagePipeline
        from unittest.mock import patch
        fixture=fixtures.PostPackageTests();fixture.setUp()
        try:
            pipeline=PostPackagePipeline(fixture.project,fixture.root)
            for name in ("groups","captions","hashtags","alt_text"):getattr(pipeline,name)()
            ctx=pipeline._context()
            for idea in ctx["content"]["content_ideas"]:idea["content_category"]="site_plan"
            with patch.object(pipeline,"_context",return_value=ctx):
                with self.assertRaisesRegex(ValueError,"actual site/masterplan"):pipeline.build()
        finally:fixture.tearDown()
    def test_final_execution_rejects_legacy_missing_sequence(self):
        from tests import test_publishing as fixtures
        from src.publishing.foundation import final_publish_errors
        fixture=fixtures.PublishingFoundationTests();fixture.setUp()
        try:
            import json
            queue=json.loads(fixture.pub.queue().read_text());fixture.pub.schedule();fixture.pub.preflight()
            item=queue["items"][0];ctx=fixture.pub._inputs();package=ctx["packages"]["packages"][0]
            item.pop("project_sequence")
            self.assertIn("missing or altered project publication sequence",final_publish_errors(item,package,ctx))
        finally:fixture.tearDown()
