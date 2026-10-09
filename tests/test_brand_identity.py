"""Phase 20A brand identity, readiness, migration, and approval tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from src.brand_kit import (approve_brand, ensure_brand_foundation, run_brand_identity_analyzer,
                           run_brand_kit_analysis, run_brand_readiness_validator)
from src.brand_kit.defaults import DEFAULT_BRAND_CONFIG
from src.brand_kit.identity import analyze_logo_colors, contrast, migrate_config


class BrandIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        _, config, _ = ensure_brand_foundation(self.root)
        data = json.loads(config.read_text(encoding="utf-8")); data["company"]["display_name"] = "Domus Erbil"
        config.write_text(json.dumps(data), encoding="utf-8")

    def tearDown(self) -> None: self.temp.cleanup()

    def logo(self, colors=((15, 42, 68, 255), (210, 150, 40, 255)), transparent=False) -> Path:
        path = self.root/"input"/"brand"/"logos"/"official.png"
        image = Image.new("RGBA", (800, 300), (0, 0, 0, 0) if transparent else colors[0])
        draw = ImageDraw.Draw(image); draw.rectangle((400, 0, 799, 299), fill=colors[-1]); image.save(path)
        return path

    def analyze(self):
        run_brand_kit_analysis(self.root); return run_brand_identity_analyzer(self.root)

    def test_colorful_transparent_logo_is_deterministic_and_noise_ignored(self) -> None:
        path = self.logo(transparent=True)
        image = Image.open(path); image.putpixel((1, 1), (255, 0, 255, 20)); image.save(path)
        first, transparent = analyze_logo_colors(path); second, _ = analyze_logo_colors(path)
        self.assertTrue(transparent); self.assertEqual(first, second)
        self.assertEqual(len(first["logo_colors"]), 1)  # transparent half and near-transparent noise are ignored

    def test_monochrome_has_no_invented_secondary_or_accent(self) -> None:
        path = self.logo(colors=((20, 40, 60, 255), (20, 40, 60, 255)))
        palette, _ = analyze_logo_colors(path)
        self.assertIsNotNone(palette["primary"]); self.assertIsNone(palette["secondary"]); self.assertIsNone(palette["accent"])

    def test_svg_colors_and_contrast(self) -> None:
        path = self.root/"input"/"brand"/"logos"/"official.svg"
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="300"><rect width="500" height="300" fill="#0F2A44"/><circle fill="#D29628"/></svg>', encoding="utf-8")
        palette, _ = analyze_logo_colors(path)
        self.assertEqual(palette["primary"]["hex"], "#0F2A44"); self.assertGreater(contrast((0, 0, 0), (255, 255, 255)), 20)

    def test_migration_preserves_legacy_values_and_typography_is_system_selected(self) -> None:
        config = copy.deepcopy(DEFAULT_BRAND_CONFIG); config["visual_identity"]["colors"]["primary"] = "#123456"
        migrated, notes = migrate_config(config)
        self.assertEqual(migrated["visual_identity"]["colors"]["primary"]["value"], "#123456")
        self.assertEqual(migrated["visual_identity"]["colors"]["primary"]["status"], "user_confirmed")
        self.assertEqual(migrated["visual_identity"]["typography"]["status"], "system_selected"); self.assertTrue(notes)
        self.assertEqual(list((self.root/"input"/"brand"/"fonts").iterdir()), [])

    def test_user_confirmed_color_is_not_overwritten_and_rtl_is_ready(self) -> None:
        self.logo(); config_path = self.root/"input"/"brand"/"brand-config.json"
        config = json.loads(config_path.read_text()); config["visual_identity"]["colors"]["primary"] = {"value":"#ABCDEF","status":"user_confirmed","source":"user","confidence":1}
        config_path.write_text(json.dumps(config))
        result = self.analyze(); saved = json.loads(config_path.read_text())
        self.assertEqual(saved["visual_identity"]["colors"]["primary"]["value"], "#ABCDEF")
        for language in ("Arabic", "Kurdish Sorani"): self.assertEqual(result.identity["language_typography_rules"][language]["direction"], "rtl")

    def test_missing_logo_blocks_but_optional_contacts_only_warn(self) -> None:
        run_brand_kit_analysis(self.root); run_brand_identity_analyzer(self.root)
        blocked = run_brand_readiness_validator(self.root).report
        self.assertEqual(blocked["readiness_status"], "blocked")
        self.logo(); self.analyze(); ready = run_brand_readiness_validator(self.root).report
        self.assertIn(ready["readiness_status"], {"ready", "ready_with_warnings"})
        self.assertIn("phone", ready["missing_optional_elements"]); self.assertFalse(any("phone" in x for x in ready["blocking_issues"]))

    def test_invalid_website_blocks(self) -> None:
        self.logo(); self.analyze(); path = self.root/"input"/"brand"/"brand-config.json"
        config = json.loads(path.read_text()); config["company"]["website"] = "not a website"; path.write_text(json.dumps(config))
        self.assertEqual(run_brand_readiness_validator(self.root).report["readiness_status"], "blocked")

    def test_approval_lock_and_config_or_logo_change_revokes(self) -> None:
        logo = self.logo(); self.analyze(); approved = approve_brand(self.root).report
        self.assertTrue(approved["approval"]["locked"]); self.assertTrue(approved["approval"]["approved_config_hash"])
        path = self.root/"input"/"brand"/"brand-config.json"; config = json.loads(path.read_text()); config["brand_voice"]["tone"].append("warm"); path.write_text(json.dumps(config))
        stale = run_brand_readiness_validator(self.root).report; self.assertEqual(stale["approval"]["status"], "revoked")
        self.analyze(); approve_brand(self.root); image = Image.open(logo); image.putpixel((0, 0), (1, 2, 3, 255)); image.save(logo)
        changed = run_brand_readiness_validator(self.root).report; self.assertEqual(changed["approval"]["status"], "revoked")

    def test_cannot_approve_blocked_brand(self) -> None:
        run_brand_kit_analysis(self.root); run_brand_identity_analyzer(self.root)
        with self.assertRaises(ValueError): approve_brand(self.root)


if __name__ == "__main__": unittest.main()
