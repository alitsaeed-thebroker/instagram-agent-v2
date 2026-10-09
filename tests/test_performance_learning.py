from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.performance.engine import PerformanceLearningEngine, normalize_metrics, objective_aware_score, publication_from_ledger
from src.performance.integration import library_effectiveness_view, visual_art_director_context


def post(pid="p1", project="A", objective="awareness", metrics=None, pattern="pat_a", category="location", paid="organic", outliers=None):
    return {"publication_id":pid,"project_id":project,"platform":"Instagram","format":"carousel","objective":objective,
            "published_at":"2026-07-01T00:00:00+00:00","pattern_ids":[pattern],"content_category":category,"asset_type":"exterior",
            "factual_safety":"VERIFIED","snapshots":[{"observed_at":"2026-07-08T00:00:00+00:00","window":"7_day","maturity":"MATURE",
            "metrics":metrics or {"reach":1000,"shares":30,"saves":40,"profile_visits":20},"paid_status":paid,"outlier_reasons":outliers or []}]}


class PerformanceLearningTests(unittest.TestCase):
    def setUp(self): self.now=datetime(2026,8,1,tzinfo=timezone.utc)
    def test_missing_is_null_not_zero(self): self.assertIsNone(normalize_metrics({})["reach"])
    def test_objective_aware_scoring(self):
        m=normalize_metrics({"reach":10000,"shares":2,"qualified_leads":10,"conversions":3})
        self.assertNotEqual(objective_aware_score(m,"awareness"),objective_aware_score(m,"conversion"))
    def test_small_sample_and_project_isolation(self):
        with TemporaryDirectory() as d:
            review,_=PerformanceLearningEngine(Path(d),now=self.now).analyze([post(),post("other","B",metrics={"reach":999999})],"A")
        self.assertEqual(review["publications_analyzed"],1);self.assertEqual(review["pattern_performance"][0]["performance_confidence"],"INSUFFICIENT_DATA")
    def test_outlier_paid_and_unsafe_excluded(self):
        rows=[post("out",outliers=["viral resharing"]),post("paid",paid="paid"),{**post("unsafe"),"factual_safety":"UNSUPPORTED"}]
        review,_=PerformanceLearningEngine(Path("."),now=self.now).analyze(rows,"A")
        self.assertEqual(review["pattern_performance"],[])
    def test_conversion_weights_business_value(self):
        high_reach=normalize_metrics({"reach":50000,"qualified_leads":0,"inquiries":0})
        leads=normalize_metrics({"reach":8000,"qualified_leads":12,"inquiries":12})
        self.assertGreater(objective_aware_score(leads,"conversion"),objective_aware_score(high_reach,"conversion"))
    def test_cold_start_and_persistence(self):
        with TemporaryDirectory() as d:
            review_path,profile_path=PerformanceLearningEngine(Path(d),now=self.now).write([],"A")
            self.assertTrue(review_path.is_file());self.assertTrue(profile_path.is_file())
            self.assertIn("COLD_START",profile_path.read_text())
    def test_library_and_vad_are_advisory(self):
        profile={"learning_version":"1","account_effectiveness":{"pattern_performance":[{"pattern_id":"p","average_performance_score":80,"usage_count":5,"performance_confidence":"MODERATE_CONFIDENCE"}]},"planning_advice":{"recommendations":[]}}
        self.assertNotIn("pattern_quality",library_effectiveness_view(profile)["p"])
        self.assertFalse(visual_art_director_context(profile)["raw_metrics_included"])
    def test_ledger_identity_join(self):
        value=publication_from_ledger({"publication_identity":"pub","project_id":"A","platform":"Instagram","format":"carousel","package_id":"pkg","publication_timestamp":"2026-01-01T00:00:00+00:00"},{"content_id":"c","pattern_ids":["pat"]})
        self.assertEqual(value.post_package_id,"pkg");self.assertEqual(value.pattern_ids,["pat"])
    def test_stale_snapshot_is_not_learned(self):
        value=post();value["snapshots"][0]["freshness"]="STALE"
        review,_=PerformanceLearningEngine(Path("."),now=self.now).analyze([value],"A")
        self.assertEqual(review["pattern_performance"],[])
    def test_recency_decay_preserves_old_signal_at_lower_weight(self):
        engine=PerformanceLearningEngine(Path("."),now=self.now)
        self.assertGreater(engine._recency_weight("2026-07-31T00:00:00+00:00"),engine._recency_weight("2024-01-01T00:00:00+00:00"))
        self.assertGreater(engine._recency_weight("2024-01-01T00:00:00+00:00"),0)
    def test_declining_repetition_can_flag_fatigue(self):
        rows=[{"pattern_ids":["pat"],"score":score} for score in (90,80,70,60)]
        self.assertEqual(PerformanceLearningEngine._fatigue(rows)[0]["status"],"FATIGUE_RISK")

if __name__=="__main__":unittest.main()
