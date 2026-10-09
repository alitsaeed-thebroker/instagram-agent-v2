"""Immutable extraction of developer-approved project visuals."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Any

from PIL import Image
from pypdf import PdfReader

from src.utils.config import SOURCE_IMAGES_OUTPUT_DIRECTORY
from src.visual_assets.metadata import json_safe_metadata


def extract_visual_assets(
    project_name: str,
    pdf_files: list[Path],
    approved_image_files: list[Path] | None = None,
    output_root: Path = SOURCE_IMAGES_OUTPUT_DIRECTORY,
) -> Path:
    """Extract/copy approved source images without changing their bytes."""
    destination = output_root / project_name
    destination.mkdir(parents=True, exist_ok=True)
    originals = destination / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    page_render_failures: list[dict[str, Any]] = []
    pages_total = 0
    complete_page_renders = 0
    for pdf_path in pdf_files:
        document_hash = _sha256(pdf_path.read_bytes())
        try:
            reader = PdfReader(pdf_path)
        except Exception as error:
            failure = _attempt(pdf_path.name, None, None, "pypdf", False, error)
            attempts.append(failure)
            failures.append({**failure, "status": "extraction_failed"})
            continue
        for page_number in range(1, len(reader.pages) + 1):
            pages_total += 1

            # A PDF page is itself an authoritative visual source. Embedded
            # image extraction alone can return a logo or background while
            # silently dropping vector plan lines, labels and dimensions.
            # Therefore every page receives one complete, high-resolution
            # rendition in addition to any byte-exact embedded assets.
            rendered, render_attempts = _render_page_pymupdf(pdf_path, page_number, 300)
            attempts.extend(render_attempts)
            if rendered:
                data, suffix, method = rendered[0]
                record = _write_source_bytes(
                    originals, data, pdf_path.name, page_number, 0, suffix
                )
                record.update({
                    "source_kind": "pdf_page_render",
                    "extraction_method": method,
                    "direct_or_rendered": "rendered",
                    "extraction_fidelity": "complete_page_render",
                    "byte_preserving": False,
                    "render_dpi": 300,
                    "contains_entire_page": True,
                    "plan_preservation_candidate": True,
                    "status": "success",
                    "source_document_sha256": document_hash,
                    "source_document_path": str(pdf_path.resolve()),
                })
                assets.append(record)
                complete_page_renders += 1
            else:
                failure = {
                    **render_attempts[-1],
                    "status": "complete_page_render_failed",
                }
                page_render_failures.append(failure)

            try:
                page = reader.pages[page_number - 1]
            except Exception as error:
                attempts.append(_attempt(pdf_path.name, page_number, None, "pypdf", False, error))
                fallback, fallback_attempts = _extract_page_pymupdf(pdf_path, page_number)
                attempts.extend(fallback_attempts)
                if not fallback:
                    if not rendered:
                        failures.append({**(fallback_attempts[-1] if fallback_attempts else render_attempts[-1]), "status": "extraction_failed"})
                        continue
                for image_index, (data, suffix, method) in sorted(fallback.items()):
                    record = _write_source_bytes(originals, data, pdf_path.name, page_number, image_index, suffix)
                    record["extraction_method"] = method
                    record["source_document_sha256"] = document_hash
                    if "render" in method:record.update({"direct_or_rendered":"rendered","extraction_fidelity":"rendered_fallback","byte_preserving":False,"render_dpi":300})
                    record["status"] = "success"
                    assets.append(record)
                continue
            candidates, page_attempts, needs_fallback = _extract_page_pypdf(page, pdf_path.name, page_number)
            attempts.extend(page_attempts)
            if needs_fallback:
                fallback, fallback_attempts = _extract_page_pymupdf(pdf_path, page_number)
                attempts.extend(fallback_attempts)
                for image_index, candidate in fallback.items():
                    if image_index not in candidates or _candidate_quality(candidate[0]) > _candidate_quality(candidates[image_index][0]):
                        candidates[image_index] = candidate
                failed_indexes = {item["image_index"] for item in page_attempts if item["status"] == "failure"}
                unresolved = [index for index in failed_indexes if index is not None and index not in candidates]
                for image_index in unresolved:
                    matching = next((item for item in reversed(fallback_attempts) if item["image_index"] == image_index), page_attempts[-1])
                    failures.append({**matching, "status": "extraction_failed"})
                if None in failed_indexes and not fallback and not candidates:
                    final_error = fallback_attempts[-1] if fallback_attempts else page_attempts[-1]
                    failures.append({**final_error, "status": "extraction_failed"})
            for image_index, (data, suffix, method) in sorted(candidates.items()):
                record = _write_source_bytes(originals, data, pdf_path.name, page_number, image_index, suffix)
                record["extraction_method"] = method
                record["source_document_sha256"] = document_hash
                record["source_document_path"] = str(pdf_path.resolve())
                if "render" in method:
                    record.update({"direct_or_rendered":"rendered","extraction_fidelity":"rendered_fallback","byte_preserving":False,"render_dpi":300})
                record["status"] = "success"
                assets.append(record)
    # Structural catalogue adapters recover whole printed plan pages from
    # spreads. They never crop a drawing or substitute a generic floor plan.
    if project_name == "Beverly Hills":
        from src.unit_plan_catalogue import extract_catalogue_leaves
        for pdf_path in pdf_files:
            leaves, _ = extract_catalogue_leaves(project_name, pdf_path, destination / "plans" / "unit-layouts")
            for leaf in leaves:
                leaf["filename"] = str(Path(leaf["source_path"]).relative_to(destination.resolve())).replace("\\", "/")
            assets.extend(leaves)
    for image_index, source_path in enumerate(approved_image_files or [], start=1):
        data = source_path.read_bytes()
        record = _write_source_bytes(
            originals, data, source_path.name, None, image_index,
            source_path.suffix.lower() or ".bin",
        )
        record["source_kind"] = "approved_image_file"
        record["source_document_sha256"] = record["sha256"]
        record["extraction_method"] = "approved_file"
        record["status"] = "success"
        assets.append(record)
        attempts.append(_attempt(source_path.name, None, image_index, "approved_file", True))
    manifest = {
        "project": project_name,
        "visual_mode": "source_only",
        "assets": assets,
        "extraction_attempts": attempts,
        "extraction_failures": failures,
        "complete_page_render_failures": page_render_failures,
        "extraction_summary": {
            "extracted_images": len(assets),
            "failed_image_extractions": len(failures),
            "pdf_pages": pages_total,
            "complete_page_renders": complete_page_renders,
            "pages_missing_complete_render": pages_total - complete_page_renders,
            "complete_page_policy": "every_pdf_page",
        },
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(json_safe_metadata(manifest), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def _extract_page_pypdf(page: Any, source_document: str, page_number: int) -> tuple[dict[int, tuple[bytes, str, str]], list[dict[str, Any]], bool]:
    candidates: dict[int, tuple[bytes, str, str]] = {}
    attempts: list[dict[str, Any]] = []
    try:
        embedded_images = list(page.images)
    except Exception as error:
        attempts.append(_attempt(source_document, page_number, None, "pypdf", False, error))
        return candidates, attempts, True
    needs_fallback = not embedded_images
    for image_index, embedded in enumerate(embedded_images, start=1):
        try:
            data = embedded.data
            suffix = Path(embedded.name).suffix.lower() or ".bin"
            candidates[image_index] = (data, suffix, "pypdf")
            attempts.append(_attempt(source_document, page_number, image_index, "pypdf", True))
        except Exception as error:
            attempts.append(_attempt(source_document, page_number, image_index, "pypdf", False, error))
            needs_fallback = True
    return candidates, attempts, needs_fallback


def _extract_page_pymupdf(pdf_path: Path, page_number: int) -> tuple[dict[int, tuple[bytes, str, str]], list[dict[str, Any]]]:
    candidates: dict[int, tuple[bytes, str, str]] = {}
    attempts: list[dict[str, Any]] = []
    try:
        import fitz
        document = fitz.open(pdf_path)
        try:
            page = document.load_page(page_number - 1)
            images = page.get_images(full=True)
            for image_index, image_info in enumerate(images, start=1):
                try:
                    extracted = document.extract_image(image_info[0])
                    data = extracted["image"]
                    suffix = f".{extracted.get('ext', 'bin').lower()}"
                    candidates[image_index] = (data, suffix, "pymupdf")
                    attempts.append(_attempt(pdf_path.name, page_number, image_index, "pymupdf", True))
                except Exception as error:
                    attempts.append(_attempt(pdf_path.name, page_number, image_index, "pymupdf", False, error))
        finally:
            document.close()
    except Exception as error:
        attempts.append(_attempt(pdf_path.name, page_number, None, "pymupdf", False, error))
    return candidates, attempts


def _render_page_pymupdf(pdf_path: Path, page_number: int, dpi: int = 300) -> tuple[dict[int, tuple[bytes, str, str]], list[dict[str, Any]]]:
    """Render the complete page so vector plans, labels and dimensions survive."""
    attempts: list[dict[str, Any]] = []
    try:
        import fitz
        with fitz.open(pdf_path) as document:
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(dpi=max(300, dpi), alpha=True)
            data = pixmap.tobytes("png")
        attempts.append(_attempt(pdf_path.name, page_number, 0, f"pymupdf_page_render_{max(300,dpi)}dpi", True))
        return {0:(data,".png",f"pymupdf_page_render_{max(300,dpi)}dpi")}, attempts
    except Exception as error:
        attempts.append(_attempt(pdf_path.name,page_number,0,f"pymupdf_page_render_{max(300,dpi)}dpi",False,error))
        return {}, attempts


def _attempt(source_document: str, page: int | None, image_index: int | None, method: str, success: bool, error: Exception | None = None) -> dict[str, Any]:
    return {
        "extraction_method": method,
        "source_document": source_document,
        "page": page,
        "image_index": image_index,
        "status": "success" if success else "failure",
        "error_type": None if error is None else type(error).__name__,
        "error_message": None if error is None else str(error),
    }


def _candidate_quality(data: bytes) -> tuple[int, int]:
    """Prefer the successfully decoded candidate with the greatest pixel detail."""
    try:
        with Image.open(BytesIO(data)) as image:
            return image.width * image.height, len(data)
    except Exception:
        return 0, len(data)


def verify_source_integrity(manifest_path: Path) -> list[str]:
    """Return asset IDs whose immutable bytes no longer match the manifest."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for asset in data["assets"]:
        path = manifest_path.parent / asset["filename"]
        if not path.is_file() or _sha256(path.read_bytes()) != asset["sha256"]:
            failures.append(asset["asset_id"])
    return failures


def _write_source_bytes(
    destination: Path,
    data: bytes,
    source_document: str,
    source_page: int | None,
    image_index: int,
    suffix: str,
) -> dict[str, Any]:
    digest = _sha256(data)
    identity = hashlib.sha256(
        f"{source_document}|{source_page}|{image_index}|{digest}".encode("utf-8")
    ).hexdigest()[:20]
    asset_id = f"src_{identity}"
    filename = f"{asset_id}{suffix}"
    path = destination / filename
    if not path.exists():
        path.write_bytes(data)
    width, height, dpi, image_format, image_metadata = _inspect_image(path)
    info = image_metadata.get("image_info", {})
    return {
        "asset_id": asset_id,
        "source_kind": "pdf_embedded_image",
        "source_document": source_document,
        "source_page": source_page,
        "image_index": image_index,
        "filename": f"originals/{filename}",
        "width": width,
        "height": height,
        "orientation": _orientation(width, height),
        "dpi": dpi,
        "format": image_format or suffix.lstrip(".").upper(),
        "image_metadata": image_metadata,
        "original_byte_hash": digest,
        "extracted_file_hash": _sha256(path.read_bytes()),
        "direct_or_rendered": "direct",
        "extraction_fidelity": "byte_exact",
        "byte_preserving": path.read_bytes() == data,
        "source_xref": None,
        "source_bounding_box": None,
        "render_dpi": None,
        "color_profile": "icc_profile_present" if info.get("icc_profile") else None,
        "image_mode": image_metadata.get("mode"),
        "bit_depth": image_metadata.get("bit_depth"),
        "sha256": digest,
        "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
        "immutable": True,
    }


def _inspect_image(path: Path) -> tuple[int, int, Any, str | None, dict[str, Any]]:
    try:
        with Image.open(path) as image:
            dpi = json_safe_metadata(image.info.get("dpi"))
            exif = image.getexif()
            metadata = json_safe_metadata({"image_info": image.info, "exif": exif, "mode": image.mode,
                "bit_depth": 16 if "16" in image.mode else 8, "has_alpha": "A" in image.getbands()})
            return image.width, image.height, dpi, image.format, metadata
    except Exception:
        return 0, 0, None, None, {"image_info": {}, "exif": {}}


def _orientation(width: int, height: int) -> str:
    if width == height:
        return "square"
    return "landscape" if width > height else "portrait"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
