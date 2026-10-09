"""Metadata-only analysis of immutable approved source images."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from src.utils.config import VISUAL_ANALYSIS_OUTPUT_DIRECTORY


ASSET_TYPES = {
    "Exterior", "Interior", "Masterplan", "Floorplan", "Location Map", "Amenity",
    "Pool", "Clubhouse", "Garden", "Street", "Bedroom", "Living Room", "Kitchen",
    "Bathroom", "Lifestyle", "Architectural Detail", "Logo", "Developer Graphic",
    "Text Page", "Low Quality", "Unknown",
}


def analyze_visual_assets(manifest_path: Path, output_root: Path = VISUAL_ANALYSIS_OUTPUT_DIRECTORY) -> Path:
    """Create conservative metadata without inferring invisible content."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    analyses = [_analyze_asset(manifest_path.parent, asset) for asset in manifest["assets"]]
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"{manifest['project']}-visual-analysis.json"
    destination.write_text(json.dumps({
        "project": manifest["project"], "visual_mode": "source_only", "assets": analyses,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


def _analyze_asset(root: Path, asset: dict[str, Any]) -> dict[str, Any]:
    path = root / asset["filename"]
    asset_type = _asset_type(asset["source_document"], asset["width"], asset["height"])
    dominant_colors: list[str] = []
    quality_score = 0
    try:
        with Image.open(path) as image:
            sample = image.convert("RGB").resize((1, 1))
            rgb = tuple(int(value) for value in ImageStat.Stat(sample).mean)
            dominant_colors = ["#%02x%02x%02x" % rgb]
            pixels = image.width * image.height
            quality_score = min(100, max(1, int((pixels / 2_000_000) * 100)))
    except Exception:
        asset_type = "Low Quality"
    ratios = _ratios(asset["width"], asset["height"])
    return {
        "asset_id": asset["asset_id"], "asset_type": asset_type,
        "dominant_subject": "Unknown; requires visual review",
        "secondary_subjects": [], "visible_project_features": [],
        "lighting": "Unknown; not deterministically verified",
        "weather": "Unknown; not deterministically verified",
        "time_of_day": "Unknown; not deterministically verified",
        "dominant_colors": dominant_colors,
        "safe_text_areas": [], "recommended_aspect_ratios": ratios,
        "recommended_platforms": _platforms(ratios),
        "marketing_suitability": (
            "suitable" if quality_score >= 30 and asset_type != "Unknown"
            else "review_required" if quality_score >= 30 else "low_quality"
        ),
        "quality_score": quality_score,
        "source_sha256": asset["sha256"],
    }


def _asset_type(name: str, width: int, height: int) -> str:
    normalized = name.casefold().replace("_", " ").replace("-", " ")
    terms = {
        "masterplan": "Masterplan", "master plan": "Masterplan", "floorplan": "Floorplan",
        "floor plan": "Floorplan", "location": "Location Map", "map": "Location Map",
        "pool": "Pool", "clubhouse": "Clubhouse", "garden": "Garden", "street": "Street",
        "bedroom": "Bedroom", "living": "Living Room", "kitchen": "Kitchen",
        "bathroom": "Bathroom", "interior": "Interior", "exterior": "Exterior",
        "logo": "Logo", "amenity": "Amenity",
    }
    if width < 400 or height < 300:
        return "Low Quality"
    return next((value for term, value in terms.items() if term in normalized), "Unknown")


def _ratios(width: int, height: int) -> list[str]:
    if width <= 0 or height <= 0:
        return []
    ratio = width / height
    if ratio > 1.3:
        return ["16:9", "3:2"]
    if ratio < 0.8:
        return ["9:16", "4:5"]
    return ["1:1", "4:5"]


def _platforms(ratios: list[str]) -> list[str]:
    platforms: list[str] = []
    if "9:16" in ratios:
        platforms.extend(["Instagram Story", "Instagram Reel"])
    if "4:5" in ratios or "1:1" in ratios:
        platforms.extend(["Instagram Feed", "Instagram Carousel", "LinkedIn"])
    if "16:9" in ratios or "3:2" in ratios:
        platforms.extend(["Website Banner", "Facebook"])
    return platforms
