"""Tests for the global, immutable Domus Erbil brand foundation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from src.brand_kit import ensure_brand_analysis, ensure_brand_foundation, run_brand_kit_analysis, validate_brand_config
from src.brand_kit.defaults import DEFAULT_BRAND_CONFIG


class BrandKitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _logo(self, name: str, size: tuple[int, int] = (800, 300), mode: str = "RGBA") -> Path:
        path = self.root / "input" / "brand" / "logos" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new(mode, size, (20, 40, 60, 0) if mode == "RGBA" else (20, 40, 60)).save(path)
        return path

    def test_foundation_and_valid_default_config(self) -> None:
        brand, config, output = ensure_brand_foundation(self.root)
        for name in ("logos", "assets", "templates", "fonts"): self.assertTrue((brand/name).is_dir())
        self.assertTrue((brand/"templates"/"README.md").is_file()); self.assertTrue(output.is_dir())
        data = json.loads(config.read_text(encoding="utf-8"))
        self.assertTrue(validate_brand_config(data).valid)
        self.assertEqual(data["company"]["official_name"], "Domus Erbil Company for Real Estate")

    def test_missing_logo_is_nonfatal_and_warned(self) -> None:
        result = run_brand_kit_analysis(self.root)
        self.assertTrue(result.validation.valid); self.assertIsNone(result.inventory["preferred_logo_id"])
        self.assertEqual(result.inventory["summary"]["files_found"], 0)
        self.assertTrue(any("logo" in warning.casefold() for warning in result.validation.warnings))

    def test_svg_is_preferred_and_hash_recorded_without_modification(self) -> None:
        ensure_brand_foundation(self.root)
        logo = self.root/"input"/"brand"/"logos"/"official.svg"
        logo.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="300"><path d="M0 0"/></svg>', encoding="utf-8")
        before = logo.read_bytes(); result = run_brand_kit_analysis(self.root)
        record = result.inventory["logos"][0]
        self.assertEqual(record["suitability"], "preferred")
        self.assertEqual(record["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(logo.read_bytes(), before)

    def test_transparent_png_and_jpg_fallback(self) -> None:
        png = self._logo("official.png")
        jpg = self._logo("fallback.jpg", mode="RGB")
        result = run_brand_kit_analysis(self.root)
        self.assertTrue(result.inventory["preferred_logo_id"].startswith("official-"))
        records = {item["filename"]: item for item in result.inventory["logos"]}
        self.assertTrue(records[png.name]["has_transparency"]); self.assertEqual(records[jpg.name]["suitability"], "limited")

    def test_jpg_is_selected_only_when_no_better_logo_exists(self) -> None:
        self._logo("only.jpg", mode="RGB")
        result = run_brand_kit_analysis(self.root)
        self.assertTrue(result.inventory["preferred_logo_id"].startswith("only-"))

    def test_corrupt_and_tiny_logos_are_not_selected(self) -> None:
        ensure_brand_foundation(self.root)
        corrupt = self.root/"input"/"brand"/"logos"/"bad.png"; corrupt.write_bytes(b"not an image")
        self._logo("tiny.png", (30, 20))
        result = run_brand_kit_analysis(self.root)
        self.assertIsNone(result.inventory["preferred_logo_id"])
        self.assertTrue(all(item["suitability"] == "unsuitable" for item in result.inventory["logos"]))

    def test_preferred_selection_is_deterministic(self) -> None:
        self._logo("z.png"); self._logo("a.png")
        first = run_brand_kit_analysis(self.root).inventory["preferred_logo_id"]
        second = run_brand_kit_analysis(self.root, force=True).inventory["preferred_logo_id"]
        self.assertEqual(first, second); self.assertTrue(first.startswith("a-"))

    def test_validation_warnings_and_invalid_values(self) -> None:
        config = copy.deepcopy(DEFAULT_BRAND_CONFIG)
        result = validate_brand_config(config)
        for text in ("phone", "email", "colors", "system-default", "draft"): self.assertTrue(any(text in warning.casefold() for warning in result.warnings))
        config["visual_identity"]["colors"]["primary"] = "red"
        config["platform_defaults"]["instagram_feed"]["width"] = 0
        invalid = validate_brand_config(config)
        self.assertFalse(invalid.valid); self.assertGreaterEqual(len(invalid.errors), 2)

    def test_cache_is_global_and_project_independent(self) -> None:
        first = run_brand_kit_analysis(self.root)
        second = run_brand_kit_analysis(self.root)
        self.assertFalse(first.cached); self.assertTrue(second.cached)
        self.assertEqual(second.inventory_path, self.root/"output"/"brand-analysis"/"domus-erbil-logo-inventory.json")
        self.assertEqual(list((self.root/"output"/"brand-analysis").glob("*inventory.json")), [second.inventory_path])

    def test_complete_shared_analysis_is_generated_and_reused(self) -> None:
        self._logo("official.png")
        first = ensure_brand_analysis(self.root)
        second = ensure_brand_analysis(self.root)
        self.assertTrue(all(result.path.is_file() for result in first[1:]))
        self.assertTrue(second[0].cached)
        self.assertTrue(second[1].cached)
        self.assertEqual(first[2].report["brand_id"], "domus-erbil")

    def test_project_source_changes_do_not_invalidate_shared_brand_cache(self) -> None:
        self._logo("official.png")
        ensure_brand_analysis(self.root)
        project = self.root / "input" / "Project A"; project.mkdir(parents=True)
        (project / "catalogue.pdf").write_bytes(b"changed project source")
        kit, identity, _ = ensure_brand_analysis(self.root)
        self.assertTrue(kit.cached)
        self.assertTrue(identity.cached)

    def test_changed_logo_invalidates_shared_analysis(self) -> None:
        logo = self._logo("official.png")
        ensure_brand_analysis(self.root)
        Image.new("RGBA", (900, 300), (90, 20, 10, 255)).save(logo)
        kit, identity, readiness = ensure_brand_analysis(self.root)
        self.assertFalse(kit.cached)
        self.assertEqual(identity.identity["preferred_logo"]["sha256"], hashlib.sha256(logo.read_bytes()).hexdigest())
        self.assertEqual(readiness.report["approval"]["status"], "draft")

    def test_font_directory_stays_empty_and_no_download_occurs(self) -> None:
        run_brand_kit_analysis(self.root)
        self.assertEqual(list((self.root/"input"/"brand"/"fonts").iterdir()), [])

    def test_cli_accepts_project_without_creating_project_output(self) -> None:
        import app
        with patch.object(app, "PROJECT_ROOT", self.root):
            self.assertEqual(app.main(["--project", "Any Project", "--stage", "brand-kit-analysis"]), 0)
        inventory = self.root/"output"/"brand-analysis"/"domus-erbil-logo-inventory.json"
        self.assertTrue(inventory.is_file())
        self.assertEqual(list((self.root/"output"/"brand-analysis").glob("*inventory.json")), [inventory])


if __name__ == "__main__": unittest.main()
