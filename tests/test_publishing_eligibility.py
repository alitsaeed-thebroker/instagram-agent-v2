from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest

from src.publishing.eligibility import DecisionType, select_next_eligible_publication, semantic_creative_identity
from src.publishing.foundation import _lock

NOW=datetime(2026,8,12,10,0,tzinfo=timezone.utc)
POLICY={"scheduling_policy":{"minimum_global_interval_minutes":0,"minimum_feed_interval_minutes":0,"minimum_story_interval_minutes":0,"minimum_project_interval_minutes":0,"cross_surface_reuse_cooldown_minutes":1440,"allow_same_surface_recycling":False,"simultaneous_cross_surface_allowed":False}}

def item(qid="q",surface="feed",hashes=None,project="A",priority=100,kind=None):
    hashes=hashes or ["h1"];kind=kind or ("story" if surface=="story" else "single_post")
    return {"queue_item_id":qid,"project_id":project,"package_type":kind,"surface":surface,"format":"story_sequence" if surface=="story" else "carousel" if kind=="carousel" else "single_image","image_hashes":hashes,"semantic_creative_identity":semantic_creative_identity(project,hashes,kind),"priority":priority,"status":"preflight_ready","created_at":"2026-08-01T00:00:00+00:00"}

def receipt(surface="feed",hashes=None,project="A",at=None,kind=None,rid="r"):
    base=item(surface=surface,hashes=hashes,project=project,kind=kind)
    return {"receipt_id":rid,"status":"published","project_id":project,"surface":surface,"format":base["format"],"media_hashes":base["image_hashes"],"semantic_creative_identity":base["semantic_creative_identity"],"published_at":(at or NOW-timedelta(minutes=1)).isoformat()}

def decision(candidate,history=(),policy=None):
    result=select_next_eligible_publication({"items":[candidate]},list(history),now=NOW,config=policy or POLICY)
    return result["evaluated"][0]["decision"],result

class PublishingEligibilityTests(unittest.TestCase):
    def test_feed_to_feed_blocked(self):self.assertEqual(decision(item(),[receipt()])[0],DecisionType.BLOCKED_DUPLICATE)
    def test_story_to_story_blocked(self):self.assertEqual(decision(item(surface="story"),[receipt(surface="story")])[0],DecisionType.BLOCKED_DUPLICATE)
    def test_feed_to_story_after_cooldown(self):self.assertEqual(decision(item(surface="story"),[receipt(at=NOW-timedelta(days=2))])[0],DecisionType.ELIGIBLE)
    def test_story_to_feed_after_cooldown(self):self.assertEqual(decision(item(),[receipt(surface="story",at=NOW-timedelta(days=2))])[0],DecisionType.ELIGIBLE)
    def test_feed_to_story_collision_deferred(self):self.assertEqual(decision(item(surface="story"),[receipt()])[0],DecisionType.DEFERRED_CROSS_SURFACE_REUSE)
    def test_story_to_feed_collision_deferred(self):self.assertEqual(decision(item(),[receipt(surface="story")])[0],DecisionType.DEFERRED_CROSS_SURFACE_REUSE)
    def test_carousel_child_story_after_cooldown(self):self.assertEqual(decision(item(surface="story",hashes=["b"]),[receipt(hashes=["a","b","c"],kind="carousel",at=NOW-timedelta(days=2))])[0],DecisionType.ELIGIBLE)
    def test_carousel_child_story_before_cooldown(self):self.assertEqual(decision(item(surface="story",hashes=["b"]),[receipt(hashes=["a","b","c"],kind="carousel")])[0],DecisionType.DEFERRED_CROSS_SURFACE_REUSE)
    def test_regenerated_carousel_blocked(self):self.assertEqual(decision(item(hashes=["a","b"],kind="carousel"),[receipt(hashes=["a","b"],kind="carousel")])[0],DecisionType.BLOCKED_DUPLICATE)
    def test_renamed_feed_duplicate_blocked(self):self.assertEqual(decision(item(),[receipt()])[0],DecisionType.BLOCKED_DUPLICATE)
    def test_same_hash_different_project_not_cross_blocked(self):self.assertEqual(decision(item(project="B"),[receipt(project="A",at=NOW-timedelta(days=2))])[0],DecisionType.ELIGIBLE)
    def test_global_cooldown(self):
        policy=deepcopy(POLICY);policy["scheduling_policy"]["minimum_global_interval_minutes"]=60
        self.assertEqual(decision(item(hashes=["new"]),[receipt(hashes=["old"])],policy)[0],DecisionType.DEFERRED_GLOBAL_COOLDOWN)
    def test_feed_cooldown(self):
        policy=deepcopy(POLICY);policy["scheduling_policy"]["minimum_feed_interval_minutes"]=60
        self.assertEqual(decision(item(hashes=["new"]),[receipt(hashes=["old"])],policy)[0],DecisionType.DEFERRED_SURFACE_COOLDOWN)
    def test_story_cooldown(self):
        policy=deepcopy(POLICY);policy["scheduling_policy"]["minimum_story_interval_minutes"]=60
        self.assertEqual(decision(item(surface="story",hashes=["new"]),[receipt(surface="story",hashes=["old"])],policy)[0],DecisionType.DEFERRED_SURFACE_COOLDOWN)
    def test_project_cooldown(self):
        policy=deepcopy(POLICY);policy["scheduling_policy"]["minimum_project_interval_minutes"]=60
        self.assertEqual(decision(item(hashes=["new"]),[receipt(hashes=["old"])],policy)[0],DecisionType.DEFERRED_PROJECT_COOLDOWN)
    def test_scheduler_can_return_nothing(self):self.assertEqual(decision(item(),[receipt()])[1]["decision"],DecisionType.NO_ELIGIBLE_PUBLICATION)
    def test_priority_wins(self):
        result=select_next_eligible_publication({"items":[item("story","story",["s"],priority=50),item("feed","feed",["f"],priority=100)]},[],now=NOW,config=POLICY);self.assertEqual(result["selected_queue_item_id"],"feed")
    def test_tie_break_is_deterministic(self):
        a=item("b",hashes=["b"]);b=item("a",hashes=["a"]);self.assertEqual(select_next_eligible_publication({"items":[a,b]},[],now=NOW,config=POLICY)["selected_queue_item_id"],"a")
    def test_restart_uses_receipt_history(self):self.assertEqual(decision(deepcopy(item()),deepcopy([receipt()]))[0],DecisionType.BLOCKED_DUPLICATE)
    def test_story_expiration_does_not_erase_history(self):self.assertEqual(decision(item(surface="story"),[receipt(surface="story",at=NOW-timedelta(days=30))])[0],DecisionType.BLOCKED_DUPLICATE)
    def test_uncertain_is_blocked(self):
        candidate=item();candidate["status"]="publishing_uncertain";self.assertEqual(decision(candidate)[0],DecisionType.BLOCKED_UNCERTAIN_PUBLICATION)
    def test_not_before_is_deferred(self):
        candidate=item();candidate["scheduled_at_utc"]=(NOW+timedelta(hours=1)).isoformat();self.assertEqual(decision(candidate)[0],DecisionType.DEFERRED_NOT_BEFORE)
    def test_naive_clock_rejected(self):
        with self.assertRaises(ValueError):select_next_eligible_publication({"items":[]},[],now=datetime(2026,1,1),config=POLICY)
    def test_decision_audit_names_conflicting_receipt(self):self.assertEqual(decision(item(),[receipt(rid="proof")])[1]["evaluated"][0]["conflicting_receipt_id"],"proof")
    def test_selection_does_not_mutate_queue(self):
        queue={"items":[item()]};before=deepcopy(queue);select_next_eligible_publication(queue,[],now=NOW,config=POLICY);self.assertEqual(queue,before)
    def test_overlapping_worker_cannot_enter_selection_claim_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"project.lock";entered=[];started=threading.Event();release=threading.Event()
            def owner():
                with _lock(path):started.set();release.wait(2)
            worker=threading.Thread(target=owner);worker.start();self.assertTrue(started.wait(1))
            try:
                with self.assertRaises(TimeoutError):
                    with _lock(path,timeout=.05):entered.append(True)
            finally:release.set();worker.join()
            self.assertEqual(entered,[])

if __name__=="__main__":unittest.main()
