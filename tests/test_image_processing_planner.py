"""Tests for deterministic, non-destructive image-processing planning."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.ai.agents.shot_planner import _assemble_shot_plans
from src.image_processing.planner import ImageProcessingPlanner, _build_processing_plans
from src.image_processing.schema import FORBIDDEN_FIELDS, ImageProcessingPlanCollection
from tests.test_scene_planner import _scene_collection


def _inputs(root: Path, *, asset_id: str = "asset_a", width: int = 1000, height: int = 800):
    source_root = root / "source"; source_root.mkdir()
    image_path = source_root / "asset.jpg"
    Image.new("RGB", (width, height), (120, 100, 80)).save(image_path, quality=95)
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    asset = {
        "asset_id": asset_id, "filename": image_path.name, "width": width, "height": height,
        "format": "JPEG", "orientation": "landscape", "sha256": digest,
        "source_document": "Catalogue.pdf", "source_page": 2,
    }
    manifest = {"project": "Project", "assets": [asset]}
    inventory = {"project": "Project", "all_source_asset_ids": [asset_id]}
    scenes = _scene_collection()
    for scene in scenes.scene_plans[0].scenes:
        scene.reusable_asset_ids = [asset_id]
    framing = _assemble_shot_plans(scenes, {}, {asset_id}, [])
    return source_root, manifest, inventory, framing


class ImageProcessingAssemblyTests(unittest.TestCase):
    def test_valid_authentic_asset_and_deterministic_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, manifest, inventory, framing = _inputs(root)
            result = _build_processing_plans("Project", inventory, manifest, source, framing)
        self.assertEqual(result.summary.processing_plans_created, 2)
        for plan in result.image_processing_plans:
            self.assertEqual(plan.processing_plan_id, f"{plan.framing_plan_id}-IP1")
            self.assertEqual(plan.source_asset_ids, ["asset_a"])

    def test_invalid_and_foreign_asset_ids_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, manifest, inventory, framing = _inputs(root)
            for group in framing.shot_plans[0].scene_framing_groups:
                group.source_asset_ids.extend(["unknown", "other_project_asset"])
            result = _build_processing_plans("Project", inventory, manifest, source, framing)
        self.assertEqual(result.summary.invalid_asset_references_removed, 4)
        self.assertTrue(all(plan.source_asset_ids == ["asset_a"] for plan in result.image_processing_plans))

    def test_missing_source_file_skips_without_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, manifest, inventory, framing = _inputs(root)
            (source / "asset.jpg").unlink()
            result = _build_processing_plans("Project", inventory, manifest, source, framing)
        self.assertEqual(result.image_processing_plans, [])
        self.assertEqual(result.summary.skipped_unavailable, 2)

    def test_hash_mismatch_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, manifest, inventory, framing = _inputs(root)
            (source / "asset.jpg").write_bytes(b"changed")
            result = _build_processing_plans("Project", inventory, manifest, source, framing)
        self.assertEqual(result.summary.invalid_asset_references_removed, 2)
        self.assertTrue(any("hash mismatch" in warning for warning in result.warnings))

    def test_full_image_fallback_and_safe_normalized_crop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, manifest, inventory, framing = _inputs(Path(directory))
            result = _build_processing_plans("Project", inventory, manifest, source, framing)
        operation = result.image_processing_plans[0].source_asset_operations[0]
        self.assertEqual(operation.crop, {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0})
        self.assertEqual(operation.resize["mode"], "contain_letterbox")

    def test_invalid_crop_is_rejected_strictly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, manifest, inventory, framing = _inputs(Path(directory))
            result = _build_processing_plans("Project", inventory, manifest, source, framing)
        result.image_processing_plans[0].source_asset_operations[0].crop["width"] = 1.2
        self.assertTrue(any("normalized bounds" in error for error in result.validate()))

    def test_multiple_export_variants_have_positive_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, manifest, inventory, framing = _inputs(Path(directory))
            framing_plan = framing.shot_plans[0].scene_framing_groups[0].framing_plans[0]
            framing_plan.platforms = ["Instagram Feed", "Instagram Story", "LinkedIn"]
            framing_plan.aspect_ratios = ["4:5", "9:16", "1:1"]
            result = _build_processing_plans("Project", inventory, manifest, source, framing)
        variants = result.image_processing_plans[0].export_variants
        self.assertEqual(len(variants), 3)
        self.assertTrue(all(item.width > 0 and item.height > 0 for item in variants))

    def test_low_resolution_source_enables_super_resolution_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, manifest, inventory, framing = _inputs(Path(directory), width=100, height=80)
            result = _build_processing_plans("Project", inventory, manifest, source, framing)
        enhancements = result.image_processing_plans[0].source_asset_operations[0].technical_enhancements
        super_resolution = next(item for item in enhancements if item["operation"] == "super_resolution")
        self.assertTrue(super_resolution["enabled"])
        self.assertTrue(result.warnings)

    def test_text_only_plan_does_not_fabricate_background(self) -> None:
        scenes = _scene_collection()
        framing = _assemble_shot_plans(scenes, {"architecture_01": {"status": "text_only", "text_evidence": ["project.location"]}}, set(), [])
        result = _build_processing_plans("Project", {"project": "Project", "all_source_asset_ids": []}, {"project": "Project", "assets": []}, Path("unused"), framing)
        plan = result.image_processing_plans[0]
        self.assertEqual(plan.source_asset_ids, [])
        self.assertIn("do not create a synthetic", plan.text_layout_preparation["recommended_background_policy"])

    def test_unavailable_item_is_retained_as_skipped(self) -> None:
        scenes = _scene_collection()
        framing = _assemble_shot_plans(scenes, {"architecture_01": {"status": "unavailable", "text_evidence": []}}, set(), [])
        result = _build_processing_plans("Project", {"all_source_asset_ids": []}, {"assets": []}, Path("unused"), framing)
        self.assertEqual(result.summary.skipped_unavailable, 2)
        self.assertEqual(result.image_processing_plans, [])

    def test_provenance_is_complete_and_has_no_synthetic_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, manifest, inventory, framing = _inputs(Path(directory))
            result = _build_processing_plans("Project", inventory, manifest, source, framing)
        provenance = result.image_processing_plans[0].provenance
        for field in ("source_asset_ids", "source_documents", "source_pages", "source_hashes", "crop_coordinates", "resize_dimensions", "planned_enhancements", "output_formats", "module_version", "creation_timestamp"):
            self.assertIn(field, provenance)
        serialized = result.to_json()
        self.assertFalse(any(f'"{field}"' in serialized for field in FORBIDDEN_FIELDS))


class ImageProcessingPlannerRunTests(unittest.TestCase):
    def test_successful_completion_with_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, manifest, inventory, framing = _inputs(root)
            manifest_path = source / "manifest.json"; inventory_path = root / "inventory.json"; framing_path = root / "shot.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
            framing_path.write_text(framing.to_json(), encoding="utf-8")
            destination = root / "plans"
            with patch("src.image_processing.planner.save_image_processing_plans") as save:
                save.side_effect = lambda collection, project: _save(collection, project, destination)
                result_path = ImageProcessingPlanner().run(inventory_path, framing_path, manifest_path)
            self.assertIsNotNone(result_path)
            saved = ImageProcessingPlanCollection.from_json(result_path.read_text(encoding="utf-8"))
            self.assertEqual(saved.summary.fallback_plans_created, 2)


def _save(collection: ImageProcessingPlanCollection, project: str, root: Path) -> Path:
    root.mkdir()
    path = root / f"{project}-image-processing-plans.json"
    path.write_text(collection.to_json(), encoding="utf-8")
    return path
