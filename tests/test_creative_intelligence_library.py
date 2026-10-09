from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from src.creative_library import CreativeIntelligenceLibrary,LibraryValidationError,PatternRetriever,RetrievalContext
from src.creative_library.seeds import anti_patterns,seed_patterns
from src.creative_intelligence import RealEstateCreativeIntelligence

class CreativeIntelligenceLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.lib=CreativeIntelligenceLibrary(self.root/"data/creative-intelligence/library.json");self.payload=self.lib.initialize();self.retriever=PatternRetriever(self.lib,self.root/"cache")
    def tearDown(self):self.temp.cleanup()
    def get(self,kind,asset,**kw):return self.retriever.retrieve(RetrievalContext("Project A",kind,asset_type=asset,**kw))

    def test_seed_library_metrics_schema_and_originality_boundary(self):
        self.assertGreaterEqual(self.payload["metrics"]["active_patterns"],15);self.assertGreaterEqual(self.payload["metrics"]["anti_patterns"],10)
        self.assertTrue(all(p["source_type"]=="original_abstraction" for p in self.payload["patterns"]))
        self.assertTrue(all(p["quality_score"]>=75 for p in self.payload["patterns"]))

    def test_exterior_hero_contextual_ranking(self):
        result=self.get("project_hero","exterior",platform="instagram_feed",information_density="very_low",visual_strength=90,evidence_strength=90)
        ids=result["pattern_ids_selected"]
        self.assertIn("pat_arch_editorial_hero",ids);self.assertIn("pat_luxury_minimal_hero",ids)
        self.assertEqual(result["factual_authority"],"NONE")

    def test_unit_layout_returns_integrity_pattern_and_anti_patterns_without_overriding_block(self):
        result=self.get("unit_layout","floor_plan",platform="instagram_carousel",information_density="technical",visual_strength=90,evidence_strength=40,relationship_status="UNVERIFIED")
        self.assertEqual(result["pattern_ids_selected"][0],"pat_unit_layout")
        anti={x["anti_pattern_id"] for x in result["relevant_anti_patterns"]}
        self.assertTrue({"ap_tiny_plan","ap_wrong_layout"}<=anti)
        self.assertIn("plan relationship gate"," ".join(result["top_relevant_patterns"][0]["reason"]))

    def test_payment_plan_requires_current_strong_evidence(self):
        weak=self.get("payment_plan","commercial_table",platform="instagram_carousel",evidence_strength=40,commercial_freshness="STALE")
        self.assertNotIn("pat_payment_breakdown",weak["pattern_ids_selected"])
        strong=self.get("payment_plan","commercial_table",platform="instagram_carousel",evidence_strength=95,commercial_freshness="CURRENT")
        self.assertEqual(strong["pattern_ids_selected"][0],"pat_payment_breakdown")

    def test_weak_visual_and_technical_asset_avoid_image_lifestyle_primary(self):
        weak=self.get("project_overview","text_only",visual_strength=10,evidence_strength=90)
        self.assertTrue(all("text_only" in next(p for p in self.payload["patterns"] if p["pattern_id"]==x)["asset_fit"] for x in weak["pattern_ids_selected"]))
        technical=self.get("unit_layout","floor_plan",platform="instagram_carousel",visual_strength=90,evidence_strength=90)
        self.assertNotIn("pat_interior_lifestyle",technical["pattern_ids_selected"])

    def test_story_platform_changes_ranking_and_cache_key(self):
        feed=self.get("project_hero","exterior",platform="instagram_feed",visual_strength=90,evidence_strength=90)
        story=self.get("project_hero","exterior",platform="instagram_story",visual_strength=90,evidence_strength=90)
        self.assertNotEqual(feed["retrieval_cache_key"],story["retrieval_cache_key"])
        self.assertTrue(all("instagram_story" in next(p for p in self.payload["patterns"] if p["pattern_id"]==x)["platform_fit"] for x in story["pattern_ids_selected"]))

    def test_dedup_version_history_and_library_cache_invalidation(self):
        a=self.payload["patterns"][0];b=deepcopy(a);b["pattern_id"]="variant";b["name"]="Editorial Architecture Hero"
        self.assertEqual(self.lib.classify_similarity(a,b),"near_duplicate")
        before=self.retriever.cache_key(RetrievalContext("P","project_hero"),self.payload["library_version"])
        updated=self.lib.update_pattern(a["pattern_id"],{"trend_status":"CURRENT"})
        self.assertEqual(updated["patterns"][0]["pattern_version"],2);self.assertTrue((self.lib.path.parent/"versions"/"library-1.0.0.json").is_file())
        self.assertNotEqual(before,self.retriever.cache_key(RetrievalContext("P","project_hero"),updated["library_version"]))

    def test_admission_blocks_project_facts_geometry_and_low_quality(self):
        for mutation in ({"project_name":"Foreign Project"},{"logo_x":20},{"quality_score":20}):
            value=deepcopy(self.payload);value["patterns"][0].update(mutation)
            with self.assertRaises(LibraryValidationError):self.lib.validate(value)

    def test_reci_enrichment_preserves_project_isolation_and_adds_no_facts(self):
        k={"project_id":"Project A","project":{"name":"Project A","location":"Road"},"fact_provenance":{"project_identity.location":[{"page":1}]}}
        inv={"project_id":"Project A","assets":[{"asset_id":"hero","project_id":"Project A","asset_type":"exterior","quality_score":90}]}
        result=RealEstateCreativeIntelligence().build(k,inventory=inv)
        project=next(x for x in result.opportunities if x.category=="project")
        self.assertTrue(project.recommended_patterns);self.assertTrue(all(not x["project_fact_contribution"] for x in project.recommended_patterns))
        self.assertEqual(result.creative_library_version,CreativeIntelligenceLibrary.default(Path(__file__).resolve().parents[1]).load()["library_version"])
        with self.assertRaisesRegex(ValueError,"cross-project"):RealEstateCreativeIntelligence().build(k,inventory={"project_id":"Project B"})

if __name__=="__main__":unittest.main()
