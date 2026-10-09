from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zlib
from collections import Counter
from copy import deepcopy
from pathlib import Path

from src.branding.visual_regression import EXACT_COMPARISON, validate_baseline


ROOT = Path(__file__).parents[1]
BASELINE_PATH = ROOT / "tests/visual_baselines/canonical/manifest.json"
FIXTURE_ROOT = ROOT / "tests/visual_baselines/canonical"


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = (zlib.crc32(kind + data) & 0xFFFFFFFF).to_bytes(4, "big")
    return len(data).to_bytes(4, "big") + kind + data + checksum


def _fixture_png(label: str) -> bytes:
    """Return a deterministic, test-owned 1080x1350 RGB PNG."""
    rgb = hashlib.sha256(label.encode("utf-8")).digest()[:3]
    raw = (b"\x00" + rgb * 1080) * 1350
    header = (1080).to_bytes(4, "big") + (1350).to_bytes(4, "big") + bytes((8, 2, 0, 0, 0))
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


class ApprovedCanonicalVisualBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        cls.temporary = tempfile.TemporaryDirectory()
        cls.fixture_root = Path(cls.temporary.name)
        cls.runtime_baseline = deepcopy(cls.baseline)
        fixture_hashes = json.loads((FIXTURE_ROOT / "fixture-hashes.json").read_text(encoding="utf-8"))["items"]
        if len(fixture_hashes) != len(cls.runtime_baseline["items"]):
            raise AssertionError("visual fixture hash count does not match approved baseline")
        for index, item in enumerate(cls.runtime_baseline["items"], 1):
            output = Path("fixtures") / f"output-{index:02d}.png"
            source = Path("fixtures") / f"source-{index:02d}.png"
            (cls.fixture_root / output).parent.mkdir(parents=True, exist_ok=True)
            (cls.fixture_root / output).write_bytes(_fixture_png(f"output-{index}"))
            (cls.fixture_root / source).write_bytes(_fixture_png(f"source-{index}"))
            item["baseline_reference_path"] = str(output)
            item["source_asset_path"] = str(source)
            item["output_hash"] = fixture_hashes[index - 1]["output_hash"]
            item["source_asset_hash"] = fixture_hashes[index - 1]["source_hash"]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_all_approved_posts_and_slides_pass_exact_baseline(self):
        before = hashlib.sha256(BASELINE_PATH.read_bytes()).hexdigest()
        self.assertEqual(validate_baseline(self.fixture_root, self.runtime_baseline), [])
        self.assertEqual(before, hashlib.sha256(BASELINE_PATH.read_bytes()).hexdigest())
        counts = Counter((item["post_number"], item["layout_family"]) for item in self.baseline["items"])
        self.assertEqual(counts[(1, "PROJECT_OVERVIEW_EDITORIAL")], 1)
        self.assertEqual(counts[(2, "PROPERTY_SHOWCASE")], 10)
        self.assertEqual(counts[(3, "ARCHITECTURE_SHOWCASE")], 1)
        self.assertEqual(counts[(4, "INTERIOR_SHOWCASE")], 2)
        self.assertEqual(counts[(5, "AMENITY_SHOWCASE")], 2)

    def test_approval_metadata_and_protected_upstream_references_are_complete(self):
        self.assertEqual(self.baseline["status"], "approved")
        self.assertEqual(self.baseline["comparison_strategy"], EXACT_COMPARISON)
        self.assertEqual(self.baseline["renderer_version"], "7.0.0")
        self.assertEqual(self.baseline["renderer_schema_version"], "7.0.0")
        self.assertEqual(len(self.baseline["items"]), 16)
        self.assertTrue(self.baseline["content_plan_reference"]["sha256"])
        self.assertTrue(self.baseline["ranking_reference"]["sha256"])
        required = {"status", "project_fixture", "post_number", "slide_number", "content_topic", "layout_family", "renderer_version", "schema_version", "source_asset_hash", "output_hash", "width", "height", "aspect_ratio", "approval_timestamp", "baseline_reference_path"}
        self.assertTrue(all(required.issubset(item) for item in self.baseline["items"]))
        self.assertTrue(all((item["width"], item["height"], item["aspect_ratio"]) == (1080, 1350, 0.8) for item in self.baseline["items"]))

    def test_baseline_creation_has_no_generation_or_publishing_side_effects(self):
        production = json.loads((FIXTURE_ROOT / "production-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(production["api_calls"], {"ai": 0, "image_generation": 0, "meta": 0})
        self.assertEqual(production["publishing_writes"], 0)
        implementation = (ROOT / "src/branding/visual_regression.py").read_text(encoding="utf-8")
        self.assertNotIn("Beverly Hills", implementation)
        self.assertNotIn("NorthLight", implementation)

    def test_current_plan_preserves_approved_post_001_to_005_sources_and_order(self):
        plan = json.loads((FIXTURE_ROOT / "content-plan.json").read_text(encoding="utf-8"))["projects"][0]["posts"]
        expected = [(item["post_number"], item["slide_number"], item["source_asset_hash"]) for item in self.baseline["items"]]
        actual = [(post["post_number"], slide["slide_number"], slide["source_sha256"]) for post in plan if post["post_number"] <= 5 for slide in post["slides"]]
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
