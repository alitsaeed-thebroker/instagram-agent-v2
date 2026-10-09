"""Safe discovery and inventory of user-supplied official brand assets."""

from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError

from .defaults import DEFAULT_BRAND_CONFIG
from .validation import ValidationResult, validate_brand_config

BRAND_KIT_VERSION = "1.0.0"
SUPPORTED_EXTENSIONS = {".svg", ".png", ".webp", ".jpg", ".jpeg"}
TEMPLATE_README = """# Approved brand templates

This directory is reserved for future approved Domus Erbil layout templates.
Templates must use approved brand assets only. Do not place project source images here.
"""


@dataclass(frozen=True)
class BrandKitResult:
    inventory_path: Path
    config_path: Path
    validation: ValidationResult
    inventory: dict[str, Any]
    cached: bool = False


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_brand_foundation(root: Path) -> tuple[Path, Path, Path]:
    brand = root / "input" / "brand"
    for name in ("logos", "assets", "templates", "fonts"):
        (brand / name).mkdir(parents=True, exist_ok=True)
    readme = brand / "templates" / "README.md"
    if not readme.exists(): readme.write_text(TEMPLATE_README, encoding="utf-8")
    config = brand / "brand-config.json"
    if not config.exists(): _write_json(config, copy.deepcopy(DEFAULT_BRAND_CONFIG))
    output = root / "output" / "brand-analysis"
    output.mkdir(parents=True, exist_ok=True)
    return brand, config, output


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def _number(value: str | None) -> int | None:
    if not value: return None
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", value)
    return round(float(match.group(1))) if match else None


def _inspect_svg(path: Path) -> tuple[int | None, int | None, str, bool]:
    root = ElementTree.parse(path).getroot()
    if not root.tag.casefold().endswith("svg"): raise ValueError("Root element is not SVG")
    width, height = _number(root.get("width")), _number(root.get("height"))
    if (not width or not height) and root.get("viewBox"):
        parts = root.get("viewBox", "").replace(",", " ").split()
        if len(parts) == 4: width, height = round(float(parts[2])), round(float(parts[3]))
    if not width or not height: raise ValueError("SVG has no usable dimensions")
    return width, height, "vector", True


def _inspect_raster(path: Path) -> tuple[int, int, str, bool]:
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
        transparency = image.mode in {"RGBA", "LA"} or "transparency" in image.info
        return width, height, image.mode, transparency


def _logo_id(path: Path, digest: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", path.stem.casefold()).strip("-") or "logo"
    return f"{slug}-{digest[:12]}"


def _record(path: Path) -> dict[str, Any]:
    digest = _sha256(path)
    base: dict[str, Any] = {
        "logo_id": _logo_id(path, digest), "filename": path.name,
        "path": path.as_posix(), "format": path.suffix[1:].upper(), "width": None, "height": None,
        "aspect_ratio": None, "color_mode": None, "has_transparency": None,
        "file_size_bytes": path.stat().st_size, "sha256": digest,
        "suitability": "review_required", "warnings": [],
    }
    try:
        if path.suffix.casefold() == ".svg": width, height, mode, transparent = _inspect_svg(path)
        else: width, height, mode, transparent = _inspect_raster(path)
        base.update(width=width, height=height, aspect_ratio=round(width / height, 6), color_mode=mode, has_transparency=transparent)
        if width < 120 or height < 40:
            base["suitability"] = "unsuitable"
            base["warnings"].append("Logo dimensions are too small for approved production use.")
        elif path.suffix.casefold() == ".svg": base["suitability"] = "preferred"
        elif path.suffix.casefold() == ".png" and transparent and width >= 600: base["suitability"] = "preferred"
        elif path.suffix.casefold() == ".webp" and transparent: base["suitability"] = "usable"
        elif path.suffix.casefold() in {".jpg", ".jpeg"}: base["suitability"] = "limited"; base["warnings"].append("JPEG cannot preserve logo transparency.")
        else: base["suitability"] = "usable"
    except (OSError, ValueError, ElementTree.ParseError, UnidentifiedImageError) as error:
        base["suitability"] = "unsuitable"
        base["warnings"].append(f"File is corrupted or unreadable: {error}")
    return base


def _rank(logo: dict[str, Any]) -> tuple[int, int, int, str]:
    if logo["suitability"] in {"unsuitable", "review_required"}: return (99, 0, 0, logo["filename"].casefold())
    fmt, alpha = logo["format"], logo["has_transparency"]
    priority = 0 if fmt == "SVG" else 1 if fmt == "PNG" and alpha else 2 if fmt == "WEBP" and alpha else 3 if fmt not in {"JPG", "JPEG"} else 4
    return (priority, -(logo["width"] or 0) * (logo["height"] or 0), -logo["file_size_bytes"], logo["filename"].casefold())


def _signature(config_path: Path, logo_paths: list[Path], schema_version: str) -> dict[str, Any]:
    values = {"brand_config_sha256": _sha256(config_path), "logo_file_hashes": {p.name: _sha256(p) for p in logo_paths},
              "brand_kit_module_version": BRAND_KIT_VERSION, "schema_version": schema_version}
    values["cache_key"] = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return values


def run_brand_kit_analysis(root: Path, *, force: bool = False) -> BrandKitResult:
    brand, config_path, output_dir = ensure_brand_foundation(root)
    inventory_path = output_dir / "domus-erbil-logo-inventory.json"
    cache_path = output_dir / ".brand-kit-cache.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    logo_paths = sorted((p for p in (brand / "logos").iterdir() if p.is_file() and p.suffix.casefold() in SUPPORTED_EXTENSIONS), key=lambda p: (p.name.casefold(), p.name))
    signature = _signature(config_path, logo_paths, str(config.get("schema_version", "")))
    if not force and inventory_path.is_file() and cache_path.is_file():
        try:
            if json.loads(cache_path.read_text(encoding="utf-8")) == signature:
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                return BrandKitResult(inventory_path, config_path, validate_brand_config(config), inventory, True)
        except (OSError, ValueError): pass
    logos = [_record(path) for path in logo_paths]
    candidates = [logo for logo in logos if logo["suitability"] not in {"unsuitable", "review_required"}]
    preferred = min(candidates, key=_rank) if candidates else None
    for logo in logos:
        if preferred and logo["logo_id"] == preferred["logo_id"]: logo["suitability"] = "preferred"
        elif logo["suitability"] == "preferred": logo["suitability"] = "usable"
    warnings: list[str] = []
    if not logo_paths: warnings.append("No official Domus Erbil logo was found in input/brand/logos/.")
    if logo_paths and not preferred: warnings.append("No supplied logo is safe for automatic selection; manual review is required.")
    inventory = {
        "brand_id": "domus-erbil", "logos": logos,
        "preferred_logo_id": preferred["logo_id"] if preferred else None, "warnings": warnings,
        "summary": {"files_found": len(logos), "usable_logos": len(candidates), "preferred_logos": 1 if preferred else 0,
                    "review_required": sum(logo["suitability"] in {"review_required", "unsuitable"} for logo in logos)},
    }
    policy = config.get("visual_identity", {}).get("logo_policy", {})
    desired_status, desired_id = ("available", preferred["logo_id"]) if preferred else ("missing", None)
    if policy.get("status") != desired_status or policy.get("preferred_logo_id") != desired_id:
        policy["status"], policy["preferred_logo_id"] = desired_status, desired_id
        _write_json(config_path, config)
    validation = validate_brand_config(config)
    _write_json(inventory_path, inventory)
    signature = _signature(config_path, logo_paths, str(config.get("schema_version", "")))
    _write_json(cache_path, signature)
    return BrandKitResult(inventory_path, config_path, validation, inventory)
