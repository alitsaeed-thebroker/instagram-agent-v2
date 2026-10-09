"""Non-generative enhancement and provenance metadata for authentic visuals."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter

from src.visual_assets.policy import enforce_source_only
from src.visual_assets.metadata import json_safe_metadata


def enhance_source_image(
    source_path: Path,
    destination: Path,
    operations: list[dict[str, Any]],
    *,
    asset_id: str,
    source_document: str,
    source_page: int | None,
) -> Path:
    """Apply deterministic technical corrections without synthesizing content."""
    for operation in operations:
        enforce_source_only(str(operation.get("name", "")))
    with Image.open(source_path) as source:
        image = source.convert("RGB")
        for operation in operations:
            name = operation["name"]
            value = operation.get("value")
            if name in {"brightness", "exposure"}:
                image = ImageEnhance.Brightness(image).enhance(float(value or 1.0))
            elif name == "contrast":
                image = ImageEnhance.Contrast(image).enhance(float(value or 1.0))
            elif name in {"sharpening", "compression_cleanup"}:
                image = image.filter(ImageFilter.SHARPEN)
            elif name == "noise_reduction":
                image = image.filter(ImageFilter.MedianFilter(size=3))
            elif name in {"crop", "margin_removal"}:
                box = tuple(int(item) for item in operation["box"])
                image = image.crop(box)
            elif name in {"resize", "super_resolution"}:
                size = tuple(int(item) for item in operation["size"])
                image = image.resize(size, Image.Resampling.LANCZOS)
            elif name in {"white_balance", "color_recovery"}:
                image = ImageEnhance.Color(image).enhance(float(value or 1.0))
            elif name in {"perspective_correction", "export"}:
                # Perspective correction requires approved coordinates; an absent
                # transform deliberately leaves source geometry unchanged.
                pass
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination)
    metadata = {
        "asset_id": asset_id, "source_document": source_document, "source_page": source_page,
        "source_sha256": _hash(source_path), "crop_coordinates": _crop(operations),
        "enhancement_operations": operations, "geometry_policy": "source_geometry_preserved",
        "synthetic_content": False, "output_dimensions": _dimensions(destination),
        "generation_timestamp": datetime.now(timezone.utc).isoformat(),
        "output_hash": _hash(destination),
    }
    metadata_path = destination.with_suffix(destination.suffix + ".provenance.json")
    metadata_path.write_text(json.dumps(json_safe_metadata(metadata), indent=2) + "\n", encoding="utf-8")
    return metadata_path


def create_brand_provenance(
    enhanced_provenance_path: Path,
    branded_output_path: Path,
    *,
    layout_template: str,
    branding_template: str,
) -> Path:
    """Carry source lineage into a final branded asset record."""
    source = json.loads(enhanced_provenance_path.read_text(encoding="utf-8"))
    metadata = {
        **source, "layout_template": layout_template, "branding_template": branding_template,
        "output_dimensions": _dimensions(branded_output_path),
        "generation_timestamp": datetime.now(timezone.utc).isoformat(),
        "output_hash": _hash(branded_output_path), "synthetic_content": False,
    }
    destination = branded_output_path.with_suffix(branded_output_path.suffix + ".provenance.json")
    destination.write_text(json.dumps(json_safe_metadata(metadata), indent=2) + "\n", encoding="utf-8")
    return destination


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dimensions(path: Path) -> dict[str, int]:
    with Image.open(path) as image:
        return {"width": image.width, "height": image.height}


def _crop(operations: list[dict[str, Any]]) -> list[int] | None:
    return next((operation["box"] for operation in operations if operation["name"] in {"crop", "margin_removal"}), None)
