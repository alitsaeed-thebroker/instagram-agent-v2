"""Tests for visible-evidence asset intelligence, cache, and isolation."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.ai.agents.asset_intelligence_agent import AssetIntelligenceAgent, _sanitize_semantics, _vision_payload
from src.knowledge.schema import ProjectDetails, ProjectKnowledge


def _semantic(asset_type: str, *, confidence: float = 0.9, subject: str | None = None) -> dict:
    subject = subject or asset_type.replace("_", " ")
    return {
        "asset_type": asset_type, "asset_subtype": "", "confidence": confidence, "analysis_status": "analyzed",
        "dominant_subject": subject, "supporting_subjects": [], "visible_project_features": [subject],
        "visible_architectural_elements": [subject], "visible_amenities": [], "visible_spaces": [],
        "contains_people": False, "people_context": "", "contains_text": asset_type in {"text_heavy_page", "floorplan", "masterplan", "location_map"},
        "visible_text_summary": "", "contains_logo": asset_type == "logo", "logo_description": "",
        "contains_map": asset_type == "location_map", "contains_masterplan": asset_type == "masterplan",
        "contains_floorplan": asset_type == "floorplan", "contains_diagram": asset_type == "diagram",
        "exterior_or_interior": "interior" if asset_type == "interior" else "exterior" if asset_type == "exterior" else "not_applicable",
        "apparent_time_of_day": "unknown", "visible_weather": "unknown", "lighting_character": "neutral",
        "dominant_colors": ["#777777"], "marketing_suitability": "feed_ready",
        "recommended_content_uses": ["project introduction"], "recommended_platforms": ["Instagram Feed"],
        "recommended_formats": ["Carousel"], "safe_crop_assessment": {"level": "limited", "reason": "Edges approach frame"},
        "text_safe_area_assessment": "review", "logo_safe_area_assessment": "review",
        "restrictions": ["Do not invent content"], "warnings": [],
    }


def _project_files(root: Path, project: str = "Project", count: int = 1, duplicate: bool = False):
    source = root / project; source.mkdir(parents=True)
    assets = []
    first_bytes = None
    for index in range(count):
        path = source / f"source-{index}.jpg"
        Image.new("RGB", (900, 600), (100, 100 if duplicate else 100 + index, 80)).save(path)
        if duplicate and first_bytes is not None: path.write_bytes(first_bytes)
        first_bytes = path.read_bytes()
        digest = hashlib.sha256(first_bytes).hexdigest()
        assets.append({"asset_id": f"{project}_asset_{index}", "filename": path.name, "sha256": digest, "width": 900, "height": 600, "orientation": "landscape", "source_document": "source.pdf", "source_page": index + 1, "image_index": 1})
    manifest = source / "manifest.json"; manifest.write_text(json.dumps({"project": project, "assets": assets}), encoding="utf-8")
    knowledge = root / f"{project}.json"; knowledge.write_text(ProjectKnowledge(project=ProjectDetails(name=project)).to_json(), encoding="utf-8")
    return manifest, knowledge


class AssetSemanticsTests(unittest.TestCase):
    def test_api_unsupported_decodable_image_is_transcoded(self)->None:
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"plan.jp2";Image.new("RGB",(64,48),"white").save(path,format="JPEG2000");before=path.read_bytes();payload,mime=_vision_payload(path);after=path.read_bytes()
        self.assertEqual(mime,"image/png");self.assertTrue(payload.startswith(b"\x89PNG"));self.assertEqual(after,before)
    def test_clear_visual_types_are_preserved(self) -> None:
        for asset_type in ("exterior", "interior", "swimming_pool", "floorplan", "masterplan", "location_map", "logo", "text_heavy_page", "decorative_graphic"):
            with self.subTest(asset_type=asset_type):
                normalized, _ = _sanitize_semantics(_semantic(asset_type))
                self.assertEqual(normalized["asset_type"], asset_type)

    def test_ambiguous_and_invalid_confidence_become_unknown(self) -> None:
        normalized, warnings = _sanitize_semantics(_semantic("exterior", confidence=2.0))
        self.assertEqual(normalized["asset_type"], "unknown")
        self.assertEqual(normalized["confidence"], 0.0)
        self.assertTrue(warnings)

    def test_low_confidence_becomes_unknown_review_required(self) -> None:
        normalized, _ = _sanitize_semantics(_semantic("swimming_pool", confidence=0.3))
        self.assertEqual(normalized["asset_type"], "unknown")
        self.assertEqual(normalized["marketing_suitability"], "review_required")

    def test_unsupported_feature_claim_is_removed(self) -> None:
        raw = _semantic("exterior", subject="villa exterior")
        raw["visible_project_features"] = ["olympic swimming pool"]
        normalized, warnings = _sanitize_semantics(raw)
        self.assertEqual(normalized["visible_project_features"], [])
        self.assertTrue(any("Unsupported" in warning for warning in warnings))


class AssetIntelligenceWorkflowTests(unittest.TestCase):
    def _run(self, root: Path, manifest: Path, knowledge: Path, analyzer):
        intelligence = root / "intelligence"; inventory = root / "inventory"
        with (
            patch("src.ai.agents.asset_intelligence_agent.ASSET_INTELLIGENCE_OUTPUT_DIRECTORY", intelligence),
            patch("src.ai.agents.asset_intelligence_agent.VISUAL_INVENTORY_OUTPUT_DIRECTORY", inventory),
        ):
            return AssetIntelligenceAgent(analyzer=analyzer).run(manifest, knowledge)

    def test_duplicate_assets_are_analyzed_once_and_provenance_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest, knowledge = _project_files(root, count=2, duplicate=True)
            calls = []
            result = self._run(root, manifest, knowledge, lambda path: calls.append(path) or _semantic("exterior"))
            data = json.loads(result[0].read_text(encoding="utf-8"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(data["assets"]), 2)
        self.assertNotEqual(data["assets"][0]["asset_id"], data["assets"][1]["asset_id"])

    def test_cache_hit_and_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest, knowledge = _project_files(root)
            calls = []
            analyzer = lambda path: calls.append(path) or _semantic("exterior")
            self._run(root, manifest, knowledge, analyzer)
            self._run(root, manifest, knowledge, analyzer)
            self.assertEqual(len(calls), 1)
            source = manifest.parent / "source-0.jpg"
            Image.new("RGB", (900, 600), (10, 20, 30)).save(source)
            payload = json.loads(manifest.read_text(encoding="utf-8")); payload["assets"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            self._run(root, manifest, knowledge, analyzer)
            self.assertEqual(len(calls), 2)

    def test_failed_asset_does_not_block_later_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest, knowledge = _project_files(root, count=2)
            calls = 0
            def analyzer(_):
                nonlocal calls; calls += 1
                if calls == 1: raise RuntimeError("vision failed")
                return _semantic("interior")
            result = self._run(root, manifest, knowledge, analyzer)
            data = json.loads(result[0].read_text(encoding="utf-8"))
        self.assertEqual([item["analysis_status"] for item in data["assets"]], ["failed", "analyzed"])

    def test_multiple_projects_remain_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); first = _project_files(root, "First"); second = _project_files(root, "Second")
            result_a = self._run(root, *first, lambda _: _semantic("exterior"))
            result_b = self._run(root, *second, lambda _: _semantic("interior"))
            inventory_a = json.loads(result_a[1].read_text(encoding="utf-8")); inventory_b = json.loads(result_b[1].read_text(encoding="utf-8"))
        self.assertEqual(inventory_a["project"], "First")
        self.assertEqual(inventory_b["project"], "Second")
        self.assertFalse(set(inventory_a["all_source_asset_ids"]) & set(inventory_b["all_source_asset_ids"]))
