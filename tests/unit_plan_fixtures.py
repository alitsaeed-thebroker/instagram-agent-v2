"""Actual PDF/image fixtures; no mock verification or model authority."""
import hashlib
from pathlib import Path
import tempfile
import fitz


_TEMP = tempfile.TemporaryDirectory()
_ROOT = Path(_TEMP.name)


def source_plan(*, project="A", area=270, bedrooms=3, text=None):
    if text is None:
        text = f"UNIT PLAN\nProject: {project}\nUnit Type: Type B\nBedrooms: {bedrooms}\nArea sqm: {area}\nTower: West"
    key = hashlib.sha256(text.encode()).hexdigest()
    folder = _ROOT / key
    folder.mkdir(exist_ok=True)
    pdf = folder / "brochure.pdf"
    image = folder / "plan.png"
    if not pdf.exists():
        with fitz.open() as doc:
            page = doc.new_page(width=300, height=360)
            page.insert_text((15, 20), text, fontsize=10)
            page.draw_rect(fitz.Rect(20, 200, 280, 330))
            page.draw_line(fitz.Point(150, 200), fitz.Point(150, 330))
            doc.save(pdf)
            image.write_bytes(page.get_pixmap(dpi=300, alpha=True).tobytes("png"))
    return {
        "asset_id": "layout-270", "project_id": project, "asset_type": "unit_layout",
        "source_document": pdf.name, "source_document_path": str(pdf), "source_page": 1,
        "source_document_hash": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "source_hash": hashlib.sha256(image.read_bytes()).hexdigest(), "source_path": str(image),
        "source_kind": "pdf_page_render", "contains_entire_page": True, "render_dpi": 300,
        "plan_completeness_status": "COMPLETE", "plan_legibility_status": "READABLE",
        "relationship_status": "UNVERIFIED",
        "unit_identity": {"unit_type": "Type B", "area_sqm": area, "bedrooms": bedrooms},
    }
