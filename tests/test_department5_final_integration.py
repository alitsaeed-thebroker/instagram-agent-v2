from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from src.publishing.eligibility import select_next_eligible_publication
from src.publishing.ledger import PublicationLedger, record_from_receipt, uncertain_from_item


POLICY={"scheduling_policy":{"minimum_global_interval_minutes":60,"minimum_feed_interval_minutes":720,
    "minimum_story_interval_minutes":120,"minimum_project_interval_minutes":180,
    "cross_surface_reuse_cooldown_minutes":1440,"same_story_reuse_cooldown_minutes":10080,
    "allow_same_surface_recycling":False,"simultaneous_cross_surface_allowed":False}}


def candidate(qid,project,surface,media,priority):
    kind="story" if surface=="story" else "carousel" if len(media)>1 else "single_post"
    return {"queue_item_id":qid,"project_id":project,"publication_identity":f"publication-{project}-{surface}-{qid}",
        "semantic_creative_identity":f"creative-{project}-{'-'.join(media)}-{kind}","package_id":f"package-{qid}",
        "package_type":kind,"platform":"instagram","surface":surface,"format":"story_sequence" if surface=="story" else "carousel" if kind=="carousel" else "single_image",
        "image_hashes":media,"priority":priority,"status":"preflight_ready","created_at":"2026-08-01T00:00:00+00:00"}


class FakeRemote:
    account={"instagram_account_id":"ig-safe"}
    def get_status(self,value):return {"status":"published","timestamp":"2026-08-15T12:00:00+00:00","id":value.get("published_media_id")}


class Department5FinalIntegrationTests(unittest.TestCase):
    def test_multi_project_multi_day_restart_rollback_uncertainty_campaign(self):
        with tempfile.TemporaryDirectory() as temporary:
            ledger=PublicationLedger(Path(temporary));ledger.initialize(fresh=True);base=datetime(2026,8,12,6,tzinfo=timezone.utc)
            a_feed=candidate("a-feed","A","feed",["a1","a2"],100)
            a_story=candidate("a-story","A","story",["a2"],95)
            b_feed=candidate("b-feed","B","feed",["b1"],90)
            b_story=candidate("b-story","B","story",["b2"],80)
            queue=[a_feed,a_story,b_feed,b_story];remote_calls=[];receipts=[]

            def history():
                return [{**row,"status":"published","published_at":row.get("publication_timestamp")} for row in ledger.records() if row["state"]=="CONFIRMED_PUBLISHED"]
            def choose(at,items=None):return select_next_eligible_publication({"items":items or queue},history(),now=at,config=POLICY)
            def publish(item,at):
                self.assertIsNone(ledger.get(item["publication_identity"]));remote_calls.append(item["queue_item_id"])
                receipt={**item,"receipt_id":"receipt-"+item["queue_item_id"],"status":"published","published_media_id":"media-"+item["queue_item_id"],
                    "published_at":at.isoformat(),"instagram_account_id":"ig-safe","media_hashes":item["image_hashes"],"payload_hash":"payload","caption_hash":"caption","attempt_token":"attempt"}
                receipts.append(receipt);ledger.record(record_from_receipt(receipt))

            first=choose(base);self.assertEqual(first["selected_queue_item_id"],"a-feed");publish(a_feed,base)
            second=choose(base+timedelta(minutes=61));self.assertEqual(second["selected_queue_item_id"],"b-story");publish(b_story,base+timedelta(minutes=61))
            self.assertEqual(choose(base+timedelta(minutes=121))["decision"],"NO_ELIGIBLE_PUBLICATION")
            third=choose(base+timedelta(hours=13));self.assertEqual(third["selected_queue_item_id"],"b-feed");publish(b_feed,base+timedelta(hours=13))

            # Restart, queue regeneration and receipt deletion cannot erase truth.
            receipts.clear();ledger=PublicationLedger(Path(temporary));regenerated=[dict(x,status="preflight_ready") for x in queue]
            fourth=choose(base+timedelta(hours=25),regenerated);self.assertEqual(fourth["selected_queue_item_id"],"a-story");publish(a_story,base+timedelta(hours=25))
            self.assertEqual(set(remote_calls),{"a-feed","a-story","b-feed","b-story"});self.assertEqual(len(remote_calls),4)
            self.assertEqual(choose(base+timedelta(days=3),regenerated)["decision"],"NO_ELIGIBLE_PUBLICATION")

            # An ambiguous new Story remains blocked across restart until reconciliation.
            uncertain=candidate("b-story-new","B","story",["b3"],110)
            uncertain["attempt_token"]="attempt-uncertain"
            ledger.record(uncertain_from_item(uncertain,{"published_media_id":"media-b-story-new","parent_container_id":"container-new"}))
            quarantined=ledger.reconcile_queue({"items":[dict(uncertain,status="queued")]})
            self.assertEqual(quarantined["items"][0]["status"],"publishing_uncertain")
            before=len(remote_calls);self.assertEqual(choose(base+timedelta(days=4),quarantined["items"])["decision"],"NO_ELIGIBLE_PUBLICATION");self.assertEqual(len(remote_calls),before)
            result=ledger.reconcile_publication(uncertain["publication_identity"],FakeRemote());self.assertEqual(result["result"],"CONFIRMED_PUBLISHED")
            self.assertEqual(ledger.get(uncertain["publication_identity"])["state"],"CONFIRMED_PUBLISHED");self.assertEqual(len(remote_calls),before)


if __name__=="__main__":unittest.main()
