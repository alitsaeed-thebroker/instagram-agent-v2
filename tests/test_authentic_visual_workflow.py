"""Tests for source-only visual extraction, selection, processing, and provenance."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from src.utils.config import PROJECT_VISUAL_MODE
from src.visual_assets.analysis import analyze_visual_assets
from src.visual_assets.extraction import extract_visual_assets, verify_source_integrity
from src.visual_assets.policy import enforce_source_only
from src.visual_assets.metadata import json_safe_metadata
from src.visual_assets.processing import create_brand_provenance, enhance_source_image
from src.visual_assets.selection import assert_selection_ready, plan_asset_selection
from tests.test_scene_planner import _content_plan


class AuthenticVisualWorkflowTests(unittest.TestCase):
    def test_pdf_image_extraction_and_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "Catalogue.pdf"
            Image.new("RGB", (900, 600), (110, 90, 70)).save(pdf, "PDF")
            manifest_path = extract_visual_assets("Project", [pdf], output_root=root / "source")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["assets"])
            asset = manifest["assets"][0]
            extracted = manifest_path.parent / asset["filename"]
            self.assertEqual(asset["sha256"], hashlib.sha256(extracted.read_bytes()).hexdigest())
            self.assertEqual(asset["source_document"], "Catalogue.pdf")
            self.assertEqual(asset["source_page"], 1)

    def test_pypdf_limit_error_uses_successful_pymupdf_fallback(self) -> None:
        class BrokenPage:
            @property
            def images(self):
                from pypdf.errors import LimitReachedError
                raise LimitReachedError("decompression limit")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"pdf")
            reader = SimpleNamespace(pages=[BrokenPage()])
            with (
                patch("src.visual_assets.extraction.PdfReader", return_value=reader),
                patch("src.visual_assets.extraction._extract_page_pymupdf", return_value=({1: (b"fallback-image", ".png", "pymupdf")}, [{"extraction_method": "pymupdf", "source_document": "source.pdf", "page": 1, "image_index": 1, "status": "success", "error_type": None, "error_message": None}])),
            ):
                manifest_path = extract_visual_assets("Project", [pdf], output_root=root / "out")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["assets"][0]["extraction_method"], "pymupdf")
            self.assertEqual(manifest["extraction_summary"]["failed_image_extractions"], 0)

    def test_both_extractors_failing_records_failure_without_raising(self) -> None:
        broken = MagicMock()
        type(broken).images = property(lambda _: (_ for _ in ()).throw(RuntimeError("pypdf failed")))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); pdf = root / "bad.pdf"; pdf.write_bytes(b"pdf")
            with (
                patch("src.visual_assets.extraction.PdfReader", return_value=SimpleNamespace(pages=[broken])),
                patch("src.visual_assets.extraction._extract_page_pymupdf", return_value=({}, [{"extraction_method": "pymupdf", "source_document": "bad.pdf", "page": 1, "image_index": None, "status": "failure", "error_type": "RuntimeError", "error_message": "fallback failed"}])),
            ):
                manifest = json.loads(extract_visual_assets("Project", [pdf], output_root=root / "out").read_text(encoding="utf-8"))
            self.assertEqual(manifest["assets"], [])
            self.assertEqual(manifest["extraction_failures"][0]["status"], "extraction_failed")

    def test_failed_page_does_not_prevent_later_page_success(self) -> None:
        broken = MagicMock(); type(broken).images = property(lambda _: (_ for _ in ()).throw(RuntimeError("bad page")))
        good = SimpleNamespace(images=[SimpleNamespace(data=b"good-image", name="good.png")])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); pdf = root / "pages.pdf"; pdf.write_bytes(b"pdf")
            with (
                patch("src.visual_assets.extraction.PdfReader", return_value=SimpleNamespace(pages=[broken, good])),
                patch("src.visual_assets.extraction._extract_page_pymupdf", return_value=({}, [])),
            ):
                manifest = json.loads(extract_visual_assets("Project", [pdf], output_root=root / "out").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["assets"]), 1)
            self.assertEqual(manifest["assets"][0]["source_page"], 2)

    def test_one_project_failure_does_not_block_another_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bad = root / "bad.pdf"; good = root / "good.pdf"
            bad.write_bytes(b"bad"); good.write_bytes(b"good")
            readers = [RuntimeError("unreadable"), SimpleNamespace(pages=[SimpleNamespace(images=[SimpleNamespace(data=b"image", name="image.png")])])]
            with patch("src.visual_assets.extraction.PdfReader", side_effect=readers):
                first = json.loads(extract_visual_assets("First", [bad], output_root=root / "out").read_text(encoding="utf-8"))
                second = json.loads(extract_visual_assets("Second", [good], output_root=root / "out").read_text(encoding="utf-8"))
            self.assertEqual(first["extraction_summary"]["failed_image_extractions"], 1)
            self.assertEqual(second["extraction_summary"]["extracted_images"], 1)

    def test_missing_exif_metadata_is_preserved_as_empty_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = extract_visual_assets(
                "Project", [], [_image(root / "NoExif.jpg")], root / "source",
            )
            asset = json.loads(manifest_path.read_text(encoding="utf-8"))["assets"][0]
            self.assertEqual(asset["image_metadata"]["exif"], {})

    def test_source_integrity_detects_changed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = _image(root / "Exterior.jpg")
            manifest_path = extract_visual_assets("Project", [], [image], root / "source")
            self.assertEqual(verify_source_integrity(manifest_path), [])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            (manifest_path.parent / manifest["assets"][0]["filename"]).write_bytes(b"changed")
            self.assertEqual(verify_source_integrity(manifest_path), [manifest["assets"][0]["asset_id"]])

    def test_metadata_generation_is_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = extract_visual_assets("Project", [], [_image(root / "Exterior.jpg")], root / "source")
            analysis_path = analyze_visual_assets(manifest, root / "analysis")
            asset = json.loads(analysis_path.read_text(encoding="utf-8"))["assets"][0]
            self.assertEqual(asset["asset_type"], "Exterior")
            self.assertEqual(asset["visible_project_features"], [])
            self.assertIn("Unknown", asset["weather"])
            self.assertTrue(asset["source_sha256"])

    def test_asset_selection_uses_only_extracted_asset_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = extract_visual_assets("Project", [], [_image(root / "Exterior.jpg")], root / "source")
            analysis = analyze_visual_assets(manifest, root / "analysis")
            content = root / "Project-content-plan.json"
            content.write_text(_content_plan().to_json(), encoding="utf-8")
            selection_path = plan_asset_selection(content, analysis, root / "selection")
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            source_ids = {item["asset_id"] for item in json.loads(manifest.read_text(encoding="utf-8"))["assets"]}
            self.assertEqual(selection["workflow_status"], "ready")
            self.assertTrue(set(selection["selections"][0]["selected_asset_ids"]).issubset(source_ids))

    def test_missing_assets_skip_only_unavailable_items_without_project_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = root / "analysis.json"
            analysis.write_text(json.dumps({"project": "Project", "assets": []}), encoding="utf-8")
            content = root / "Project-content-plan.json"
            plan = _content_plan()
            plan.pillars[0].content_ideas[0].source_support_status = "unavailable"
            content.write_text(plan.to_json(), encoding="utf-8")
            selection_path = plan_asset_selection(content, analysis, root / "selection")
            assert_selection_ready(selection_path)
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            self.assertEqual(selection["workflow_status"], "ready")
            self.assertEqual(selection["selections"][0]["status"], "skipped_unavailable")
            self.assertEqual(selection["content_production_summary"]["skipped_unavailable"], 1)

    def test_source_only_mode_is_default(self) -> None:
        self.assertEqual(PROJECT_VISUAL_MODE, "source_only")

    def test_text_to_image_generation_is_forbidden(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbidden"):
            enforce_source_only("text_to_image")

    def test_enhancement_preserves_source_and_records_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _image(root / "source.jpg")
            original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            output = root / "enhanced.jpg"
            provenance_path = enhance_source_image(
                source, output, [{"name": "brightness", "value": 1.05}, {"name": "sharpening"}],
                asset_id="src_1", source_document="Catalogue.pdf", source_page=3,
            )
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
            self.assertEqual(provenance["source_sha256"], original_hash)
            self.assertEqual(provenance["geometry_policy"], "source_geometry_preserved")
            self.assertFalse(provenance["synthetic_content"])
            self.assertEqual(provenance["output_dimensions"], {"width": 1000, "height": 800})

    def test_enhancement_rejects_content_changing_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "forbidden"):
                enhance_source_image(
                    _image(root / "source.jpg"), root / "bad.jpg", [{"name": "inpaint"}],
                    asset_id="src_1", source_document="Catalogue.pdf", source_page=1,
                )

    def test_branding_keeps_complete_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _image(root / "source.jpg")
            enhanced = root / "enhanced.jpg"
            enhancement_metadata = enhance_source_image(
                source, enhanced, [{"name": "contrast", "value": 1.05}],
                asset_id="src_1", source_document="Catalogue.pdf", source_page=2,
            )
            branded = root / "branded.jpg"
            shutil.copyfile(enhanced, branded)
            brand_metadata = create_brand_provenance(
                enhancement_metadata, branded,
                layout_template="feed_4x5", branding_template="domus_erbil_v1",
            )
            provenance = json.loads(brand_metadata.read_text(encoding="utf-8"))
            for field in (
                "asset_id", "source_document", "source_page", "crop_coordinates",
                "enhancement_operations", "layout_template", "branding_template",
                "output_dimensions", "generation_timestamp", "output_hash",
            ):
                self.assertIn(field, provenance)


def _image(path: Path) -> Path:
    Image.new("RGB", (1000, 800), (120, 100, 80)).save(path, quality=95)
    return path


class JsonSafeMetadataTests(unittest.TestCase):
    def test_ifd_rational_converts_to_float(self) -> None:
        value = json_safe_metadata(IFDRational(1, 4))
        self.assertEqual(value, 0.25)
        json.dumps(value)

    def test_nested_dictionaries_are_sanitized_recursively(self) -> None:
        value = {"gps": {1: IFDRational(3, 2), "stamp": datetime(2026, 8, 6, 12, 30)}}
        sanitized = json_safe_metadata(value)
        self.assertEqual(sanitized["gps"]["1"], 1.5)
        self.assertEqual(sanitized["gps"]["stamp"], "2026-08-06T12:30:00")
        json.dumps(sanitized)

    def test_tuples_and_lists_become_json_arrays(self) -> None:
        sanitized = json_safe_metadata((1, [IFDRational(1, 2), ("nested",)]))
        self.assertEqual(sanitized, [1, [0.5, ["nested"]]])
        json.dumps(sanitized)

    def test_bytes_decode_or_fall_back_to_hex(self) -> None:
        self.assertEqual(json_safe_metadata(b"camera"), "camera")
        self.assertEqual(json_safe_metadata(b"\xff\x00"), "ff00")

    def test_normal_json_native_values_are_preserved(self) -> None:
        value = {"name": "Exterior", "width": 1000, "valid": True, "score": 0.9, "none": None}
        self.assertEqual(json_safe_metadata(value), value)
        json.dumps(json_safe_metadata(value))
