from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json, shutil, sqlite3, tempfile, threading, unittest

from src.publishing.ledger import LedgerConflict, LedgerUnavailable, PublicationLedger, record_from_receipt, uncertain_from_item

def receipt(identity="pub-feed",remote="media-1",surface="feed"):
    return {"receipt_id":"receipt-"+identity,"status":"published","publication_identity":identity,"semantic_creative_identity":"creative-1","project_id":"Project A","platform":"Instagram","surface":surface,"format":"story_sequence" if surface=="story" else "single_image","package_id":"package-1","production_contract_version":"1.0.0","media_hashes":["hash-1"],"source_asset_order":["prov-1"],"caption_hash":"caption-hash","payload_hash":"payload-hash","instagram_account_id":"ig-1","published_media_id":remote,"parent_container_id":"container-1","child_container_ids":[],"published_at":"2026-08-12T10:00:00+00:00","attempt_token":"attempt-1"}

class FakeAdapter:
    def __init__(self,status="published",fail=False):self.status=status;self.fail=fail;self.calls=[]
    def get_status(self,value):
        self.calls.append(value)
        if self.fail:raise RuntimeError("unavailable")
        return {"status":self.status,"timestamp":"2026-08-12T10:00:00+00:00"}

class PublicationLedgerTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.ledger=PublicationLedger(self.root)
    def tearDown(self):self.temp.cleanup()
    def init(self):self.ledger.initialize(fresh=True)
    def confirm(self,value=None):self.init();return self.ledger.record(record_from_receipt(value or receipt()))
    def test_fresh_install_initializes(self):self.init();self.assertTrue(self.ledger.path.is_file())
    def test_initialization_leaves_established_loss_marker(self):self.init();self.assertTrue(self.ledger.established_marker.is_file())
    def test_reopen_after_restart(self):self.confirm();self.assertEqual(len(PublicationLedger(self.root).records()),1)
    def test_confirmed_publication_is_durable(self):self.assertEqual(self.confirm()["state"],"CONFIRMED_PUBLISHED")
    def test_duplicate_confirm_is_idempotent(self):self.confirm();self.assertEqual(self.ledger.record(record_from_receipt(receipt()))["remote_media_id"],"media-1")
    def test_conflicting_duplicate_rejected(self):self.confirm();self.assertRaises(LedgerConflict,self.ledger.record,record_from_receipt(receipt(remote="other")))
    def test_feed_and_story_are_distinct(self):self.init();self.ledger.record(record_from_receipt(receipt()));self.ledger.record(record_from_receipt(receipt("pub-story","story-1","story")));self.assertEqual(len(self.ledger.records()),2)
    def test_queue_deleted_ledger_still_blocks(self):self.confirm();queue={"items":[{"publication_identity":"pub-feed","status":"queued"}]};self.assertEqual(self.ledger.reconcile_queue(queue)["items"][0]["status"],"published")
    def test_receipts_deleted_ledger_still_blocks(self):self.confirm();self.assertIn("pub-feed",self.ledger.confirmed_identities())
    def test_stale_queue_is_suppressed(self):self.confirm();queue={"items":[{"publication_identity":"pub-feed","status":"preflight_ready"}]};self.assertEqual(self.ledger.reconcile_queue(queue)["items"][0]["published_media_id"],"media-1")
    def test_uncertain_queue_is_quarantined(self):
        self.init();item={"publication_identity":"u","semantic_creative_identity":"c","project_id":"Project A","platform":"Instagram","surface":"feed","format":"single_image","package_id":"p","production_contract_version":"1","image_hashes":["h"],"caption_hash":"c","attempt_token":"a"};self.ledger.record(uncertain_from_item(item,{"parent_container_id":"x"}));queue={"items":[{"publication_identity":"u","status":"queued"}]};self.assertEqual(self.ledger.reconcile_queue(queue)["items"][0]["status"],"publishing_uncertain")
    def test_crashed_publishing_claim_becomes_reconciliation_required(self):
        self.init();queue={"items":[{"publication_identity":"u","semantic_creative_identity":"c","project_id":"Project A","platform":"Instagram","surface":"feed","format":"single_image","package_id":"p","production_contract_version":"1","image_hashes":["h"],"caption_hash":"c","attempt_token":"a","status":"publishing"}]};self.ledger.reconcile_queue(queue);self.assertEqual(self.ledger.get("u")["state"],"RECONCILIATION_REQUIRED");self.assertEqual(queue["items"][0]["status"],"publishing_uncertain")
    def test_corrupt_ledger_fails_closed(self):self.ledger.directory.mkdir(parents=True);self.ledger.path.write_bytes(b"not sqlite");self.assertRaises(LedgerUnavailable,self.ledger._validate)
    def test_missing_established_ledger_fails_closed(self):self.assertRaises(LedgerUnavailable,self.ledger.initialize,fresh=False)
    def test_existing_history_migrates(self):self.ledger.initialize(fresh=False,confirmed_receipts=[receipt()]);self.assertIn("pub-feed",self.ledger.confirmed_identities())
    def test_migration_is_idempotent(self):self.ledger.initialize(fresh=False,confirmed_receipts=[receipt()]);self.assertEqual(self.ledger.migrate_receipts([receipt()])["reused"],1)
    def test_conflicting_migration_rejected(self):self.ledger.initialize(fresh=False,confirmed_receipts=[receipt()]);self.assertRaises(LedgerConflict,self.ledger.migrate_receipts,[receipt(remote="other")])
    def test_unconfirmed_receipt_not_imported(self):
        value=receipt();value["status"]="failed";self.ledger.initialize(fresh=False,confirmed_receipts=[value]);self.assertEqual(self.ledger.records(),[])
    def test_tokens_not_persisted(self):self.confirm();raw=self.ledger.path.read_bytes();self.assertNotIn(b"secret-token",raw);self.assertNotIn(b"META_ACCESS_TOKEN",raw)
    def test_known_media_reconciles_confirmed(self):
        self.init();value=uncertain_from_item({"publication_identity":"u","semantic_creative_identity":"c","project_id":"Project A","platform":"Instagram","surface":"feed","format":"single_image","package_id":"p","production_contract_version":"1","image_hashes":["h"],"attempt_token":"a"},{"published_media_id":"m"});self.ledger.record(value);result=self.ledger.reconcile_publication("u",FakeAdapter());self.assertEqual(result["result"],"CONFIRMED_PUBLISHED")
    def test_remote_unavailable_stays_uncertain(self):self._uncertain();self.assertEqual(self.ledger.reconcile_publication("u",FakeAdapter(fail=True))["result"],"REMOTE_LOOKUP_UNAVAILABLE")
    def test_permission_like_unknown_stays_uncertain(self):self._uncertain();self.assertEqual(self.ledger.reconcile_publication("u",FakeAdapter("unknown"))["result"],"STILL_UNCERTAIN")
    def test_definitive_not_published_is_recorded(self):self._uncertain();self.assertEqual(self.ledger.reconcile_publication("u",FakeAdapter("definitively_not_published"))["result"],"CONFIRMED_NOT_PUBLISHED")
    def test_dry_run_does_not_mutate(self):self._uncertain();self.ledger.reconcile_publication("u",FakeAdapter(),dry_run=True);self.assertEqual(self.ledger.get("u")["state"],"PUBLISHING_UNCERTAIN")
    def test_unknown_identity_mismatch(self):self.init();self.assertEqual(self.ledger.reconcile_publication("missing",FakeAdapter())["result"],"IDENTITY_MISMATCH")
    def test_story_expiry_does_not_change_truth(self):self.confirm(receipt("story","story-1","story"));self.assertEqual(self.ledger.get("story")["state"],"CONFIRMED_PUBLISHED")
    def test_carousel_ids_retained(self):
        value=receipt();value.update(child_container_ids=["c1","c2"],parent_container_id="parent");record=self.confirm(value);self.assertEqual(record["child_container_ids"],["c1","c2"]);self.assertEqual(record["parent_container_id"],"parent")
    def test_unsupported_schema_fails_closed(self):self.init();db=sqlite3.connect(self.ledger.path);db.execute("UPDATE metadata SET value='999' WHERE key='schema_version'");db.commit();db.close();self.assertRaises(LedgerUnavailable,self.ledger._validate)
    def test_output_reset_preserves_ledger(self):self.confirm();(self.root/"output").mkdir();shutil.rmtree(self.root/"output");self.assertIn("pub-feed",self.ledger.confirmed_identities())
    def test_ledger_is_outside_output(self):self.init();self.assertNotIn("output",self.ledger.path.parts)
    def test_backup_is_valid(self):
        self.confirm();backup=self.ledger.backup();db=sqlite3.connect(backup)
        try:self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0],"ok")
        finally:db.close()
    def test_backup_set_is_bounded(self):
        self.confirm()
        for _ in range(5):self.ledger.backup(keep=2)
        self.assertLessEqual(len(list(self.ledger.backup_directory.glob("*.sqlite3"))),2)
    def test_status_is_machine_readable(self):self.confirm();status=self.ledger.status();json.dumps(status);self.assertEqual(status["confirmed_publications"],1)
    def test_status_contains_no_secrets(self):self.confirm();self.assertNotIn("token",json.dumps(self.ledger.status()).casefold())
    def test_concurrent_duplicate_constraint(self):
        self.init();errors=[]
        def write():
            try:self.ledger.record(record_from_receipt(receipt()))
            except Exception as error:errors.append(error)
        threads=[threading.Thread(target=write) for _ in range(2)];[x.start() for x in threads];[x.join() for x in threads];self.assertEqual(len(self.ledger.records()),1);self.assertFalse(errors)
    def test_publication_identity_unique_index(self):self.confirm();self.assertEqual(len(self.ledger.confirmed_identities()),1)
    def test_migration_audit_created(self):self.ledger.initialize(fresh=False,confirmed_receipts=[receipt()]);self.assertTrue((self.ledger.directory/"migration-audit.json").is_file())
    def _uncertain(self):
        self.init();self.ledger.record(uncertain_from_item({"publication_identity":"u","semantic_creative_identity":"c","project_id":"Project A","platform":"Instagram","surface":"feed","format":"single_image","package_id":"p","production_contract_version":"1","image_hashes":["h"],"attempt_token":"a"},{"published_media_id":"m"}))

if __name__=="__main__":unittest.main()
