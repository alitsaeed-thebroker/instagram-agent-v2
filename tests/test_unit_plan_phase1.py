from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

import fitz
from PIL import Image

from src.ai.agents.asset_intelligence_agent import _sanitize_semantics, _with_provenance
from src.content.inventory import VISUAL_TYPES
from src.department1.pipeline import Department1Pipeline
from src.plan_integrity import claims_from_text, make_plan_record, validate_plan_contract
from src.visual_assets.extraction import extract_visual_assets
from tests.test_asset_intelligence_agent import _semantic


def _mixed_plan_pdf(path: Path) -> None:
    logo = BytesIO()
    Image.new("RGB", (80, 80), (120, 20, 20)).save(logo, "PNG")
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(25, 25, 105, 105), stream=logo.getvalue())
    page.draw_rect(fitz.Rect(80, 180, 510, 700), color=(0, 0, 0), width=2)
    page.draw_line(fitz.Point(295, 180), fitz.Point(295, 700), color=(0, 0, 0), width=1)
    page.insert_text(fitz.Point(100, 220), "UNIT NO: A-12", fontsize=15)
    page.insert_text(fitz.Point(100, 250), "LIVING 4.20 x 5.10 m", fontsize=12)
    page.insert_text(fitz.Point(320, 250), "BEDROOM 3.60 x 4.00 m", fontsize=12)
    document.save(path)
    document.close()


def _verified_semantic() -> dict:
    raw = _semantic("unit_layout", subject="complete individual apartment unit plan")
    raw.update({
        "analysis_status": "analyzed",
        "marketing_suitability": "information_graphic_ready",
        "unit_identity": {
            "unit_type": "Type A", "area_sqm": 142, "bedrooms": 3,
            "bathrooms": None, "floor": None, "unit_number": "A-12",
            "building": None, "tower": None, "orientation": None,
            "balcony": None, "terrace": None,
            "commercial_residential_classification": "residential",
            "dimensions": ["Living 4.20 x 5.10 m", "Bedroom 3.60 x 4.00 m"],
        },
        "evidence": {
            "unit_type": ["Visible label: TYPE A"],
            "area_sqm": ["Visible label: 142 m2"],
            "bedrooms": ["Three visible bedroom labels"],
            "bathrooms": [], "floor": [],
            "unit_number": ["Visible label: UNIT NO: A-12"],
            "building": [], "tower": [], "orientation": [], "balcony": [],
            "terrace": [],
            "commercial_residential_classification": ["Visible residential room labels"],
            "dimensions": ["Visible labels: 4.20 x 5.10 m and 3.60 x 4.00 m"],
        },
        "relationship_confidence": {field: .99 for field in (
            "unit_type", "area_sqm", "bedrooms", "bathrooms", "floor",
            "unit_number", "building", "tower", "orientation", "balcony",
            "terrace", "commercial_residential_classification", "dimensions"
        )},
        "relationship_status": "VERIFIED",
        "verification_status": "VERIFIED",
        "visible_unit_numbers": ["A-12"],
        "visible_dimension_labels": ["4.20 x 5.10 m", "3.60 x 4.00 m"],
        "plan_completeness_status": "complete",
        "plan_legibility_status": "readable",
    })
    return raw


class UnitPlanPhase1Tests(unittest.TestCase):
    def test_every_pdf_page_has_complete_render_in_addition_to_embedded_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "plans.pdf"
            _mixed_plan_pdf(pdf)
            manifest_path = extract_visual_assets("Project", [pdf], output_root=root / "out")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            page_renders = [x for x in payload["assets"] if x.get("source_kind") == "pdf_page_render"]
            embedded = [x for x in payload["assets"] if x.get("source_kind") == "pdf_embedded_image"]
            self.assertEqual(len(page_renders), 1)
            self.assertTrue(embedded)
            self.assertTrue(page_renders[0]["contains_entire_page"])
            self.assertEqual(page_renders[0]["render_dpi"], 300)
            self.assertEqual(len(page_renders[0]["source_document_sha256"]), 64)
            self.assertGreater(page_renders[0]["width"], 2000)
            self.assertEqual(payload["extraction_summary"]["pages_missing_complete_render"], 0)

    def test_department1_read_handoff_contains_complete_page_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "input" / "Project"
            project.mkdir(parents=True)
            _mixed_plan_pdf(project / "plans.pdf")
            pipeline = Department1Pipeline(project, output_root=root / "output")
            read_package = pipeline.read_stage(pipeline.input_stage())
            assets = read_package["sources"][0]["assets"]
            complete = [x for x in assets if x["kind"] == "pdf_page_render"]
            self.assertEqual(len(complete), 1)
            self.assertEqual(complete[0]["authenticity"], "source_rendered_complete_page")
            self.assertTrue(complete[0]["contains_entire_page"])
            self.assertEqual(complete[0]["provenance"]["locator"]["page"], 1)

    def test_visible_llm_evidence_is_bound_but_cannot_become_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.png"
            Image.new("RGB", (1800, 1400), "white").save(path)
            semantic, warnings = _sanitize_semantics(_verified_semantic())
            self.assertEqual(warnings, [])
            asset = {
                "asset_id": "plan-A12", "sha256": "hash-A12", "width": 1800,
                "height": 1400, "orientation": "landscape",
                "source_document": "brochure.pdf", "source_page": 12,
                "image_index": 0, "source_kind": "pdf_page_render",
                "contains_entire_page": True,
                "source_document_sha256": "pdf-hash",
                "extraction_fidelity": "complete_page_render", "render_dpi": 300,
            }
            analyzed = _with_provenance(semantic, asset, path, "Project", "cache", "analyzed")
            record = make_plan_record(analyzed)
            self.assertFalse(record["marketing_eligible"])
            evidence = record["evidence"]["unit_number"][0]
            self.assertEqual(
                (evidence["source_project"], evidence["source_document"], evidence["source_page"], evidence["source_hash"], evidence["asset_id"]),
                ("Project", "brochure.pdf", 12, "hash-A12", "plan-A12"),
            )
            self.assertEqual(record["visible_dimension_labels"], ["4.20 x 5.10 m", "3.60 x 4.00 m"])
            self.assertEqual(record["source_document_hash"], "pdf-hash")
            self.assertEqual(record["review_status"], "REVIEW_REQUIRED")

    def test_empty_verified_record_fails_closed(self):
        record = make_plan_record({
            "asset_id": "empty", "project_id": "Project", "asset_type": "unit_layout",
            "source_document": "brochure.pdf", "source_page": 1, "source_hash": "hash",
            "relationship_status": "VERIFIED", "plan_completeness_status": "complete",
            "plan_legibility_status": "readable",
        })
        self.assertEqual(record["relationship_status"], "UNVERIFIED")
        self.assertFalse(record["marketing_eligible"])

    def test_partial_evidence_metadata_cannot_verify_fact(self):
        record = make_plan_record({
            "asset_id": "A12", "project_id": "Project", "asset_type": "unit_layout",
            "source_document": "brochure.pdf", "source_page": 12, "source_hash": "hash",
            "unit_identity": {"unit_number": "A-12"},
            "evidence": {"unit_number": [{
                "source_project": "Project", "source_document": "brochure.pdf", "source_page": 12
            }]},
            "relationship_status": "VERIFIED", "plan_completeness_status": "complete",
            "plan_legibility_status": "readable",
        })
        self.assertEqual(record["relationship_status"], "UNVERIFIED")
        self.assertFalse(record["marketing_eligible"])

    def test_embedded_partial_plan_is_review_required_even_if_model_says_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.png"
            Image.new("RGB", (1000, 800), "white").save(path)
            semantic, _ = _sanitize_semantics(_verified_semantic())
            analyzed = _with_provenance(semantic, {
                "asset_id": "partial", "sha256": "hash", "width": 1000, "height": 800,
                "source_document": "brochure.pdf", "source_page": 12, "image_index": 1,
                "source_kind": "pdf_embedded_image", "contains_entire_page": False,
            }, path, "Project", "cache", "analyzed")
            record = make_plan_record(analyzed)
            self.assertEqual(record["plan_completeness_status"], "INCOMPLETE")
            self.assertEqual(record["review_status"], "REVIEW_REQUIRED")
            self.assertFalse(record["marketing_eligible"])

    def test_unit_plan_contract_blocks_unverified_plan(self):
        record = make_plan_record({
            "asset_id": "partial", "project_id": "Project", "asset_type": "unit_layout",
            "source_document": "brochure.pdf", "source_page": 12, "source_hash": "hash",
            "relationship_status": "UNVERIFIED", "plan_completeness_status": "incomplete",
            "plan_legibility_status": "partially_readable",
        })
        errors = validate_plan_contract({
            "plan_integrity": record,
            "source_image": {"crop_mode": "fit", "placement": [0, 0, 1080, 900]},
            "graphics": {"overlay_geometry": [0, 900, 1080, 1080]},
        })
        self.assertTrue(any("not eligible" in error for error in errors))

    def test_unit_numbers_and_dimensions_are_detected_as_claims(self):
        claims = claims_from_text("Unit No: A-12 — living room 4.20 x 5.10 m")
        self.assertEqual(claims["unit_number"], "A-12")
        self.assertEqual(claims["dimensions"], ["4.20 x 5.10 m"])

    def test_all_unit_plan_aliases_enter_the_layout_inventory(self):
        for kind in ("unit_layout", "apartment_layout", "office_layout", "villa_layout", "commercial_unit_layout"):
            self.assertIn(kind, VISUAL_TYPES["layout"])


if __name__ == "__main__":
    unittest.main()
