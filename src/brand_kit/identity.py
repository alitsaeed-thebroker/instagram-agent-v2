"""Deterministic brand identity analysis, migration, and palette policy."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError

ANALYZER_VERSION = "20.1.0"
COLOR_ANALYSIS_VERSION = "1.0.1"
TYPOGRAPHY_POLICY_VERSION = "1.0.0"
CANONICAL_STATUSES = {"official_confirmed", "logo_derived", "system_selected", "user_confirmed", "missing", "invalid"}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class IdentityResult:
    path: Path
    identity: dict[str, Any]
    config_path: Path
    cached: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config_hash(config: dict[str, Any], *, approval_neutral: bool = False) -> str:
    value = json.loads(json.dumps(config))
    if approval_neutral:
        value["approval"] = {"status": "draft", "locked": False, "approved_by": None, "approved_at": None,
                             "approved_config_hash": None, "approved_logo_hash": None, "notes": []}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def approved_config_hash(config: dict[str, Any]) -> str:
    """Hash production configuration while excluding mutable approval bookkeeping."""
    return _config_hash(config, approval_neutral=True)


def _analysis_config_hash(config: dict[str, Any]) -> str:
    """Exclude analyzer-owned derived values and audit timestamps from its input signature."""
    value = json.loads(json.dumps(config))
    value.pop("migration_notes", None)
    colors = value.get("visual_identity", {}).get("colors", {})
    for name in ("primary", "secondary", "accent"):
        if isinstance(colors.get(name), dict) and colors[name].get("status") in {"logo_derived", "missing"}:
            colors[name] = {"value": None, "status": "missing", "source": "analyzer_managed", "confidence": 1.0}
    if colors.get("status") in {"logo_derived", "missing"}: colors["status"] = "missing"
    return _config_hash(value, approval_neutral=True)


def _rgb(hex_value: str) -> tuple[int, int, int]:
    return tuple(int(hex_value[i:i+2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % rgb


def _linear(value: int) -> float:
    channel = value / 255
    return channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    return round(.2126 * _linear(rgb[0]) + .7152 * _linear(rgb[1]) + .0722 * _linear(rgb[2]), 6)


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return round((high + .05) / (low + .05), 2)


def _neutral(rgb: tuple[int, int, int]) -> bool:
    return max(rgb) - min(rgb) <= 18 or (max(rgb) < 35) or (min(rgb) > 235)


def _color_record(rgb: tuple[int, int, int], count: int, total: int, confidence: float = .95) -> dict[str, Any]:
    white, dark = contrast(rgb, (255, 255, 255)), contrast(rgb, (17, 17, 17))
    best_text, best_ratio = ("#FFFFFF", white) if white >= dark else ("#111111", dark)
    return {"hex": _hex(rgb), "rgb": list(rgb), "coverage_percent": round(100 * count / total, 3),
            "luminance": luminance(rgb), "contrast_on_white": white, "contrast_on_dark": dark,
            "status": "logo_derived", "source": "preferred_logo", "confidence": confidence,
            "text_safety": {"background": _hex(rgb), "recommended_text": best_text,
                            "contrast_ratio": best_ratio, "safe_for_normal_text": best_ratio >= 4.5,
                            "safe_for_large_text": best_ratio >= 3.0,
                            "classification": "safe_with_white_text" if white >= 4.5 else "safe_with_dark_text" if dark >= 4.5 else "not_safe_for_text_background"}}


def _raster_colors(path: Path) -> tuple[list[tuple[tuple[int, int, int], int]], bool]:
    with Image.open(path) as source:
        source.verify()
    with Image.open(path) as source:
        image = source.convert("RGBA")
        image.thumbnail((600, 600))
        visible = [(r, g, b) for r, g, b, a in image.getdata() if a >= 32]
        transparency = any(a < 255 for _, _, _, a in image.getdata())
    if not visible: return [], transparency
    # Five-bit buckets remove antialias/compression noise deterministically.
    buckets = Counter((min(255, ((r + 4) // 8) * 8), min(255, ((g + 4) // 8) * 8), min(255, ((b + 4) // 8) * 8)) for r, g, b in visible)
    minimum = max(2, math.ceil(len(visible) * .002))
    significant = [(rgb, count) for rgb, count in buckets.most_common() if count >= minimum]
    merged: list[tuple[tuple[int, int, int], int]] = []
    for rgb, count in significant:
        match = next((index for index, (representative, _) in enumerate(merged)
                      if math.dist(rgb, representative) <= 28), None)
        if match is None: merged.append((rgb, count))
        else: merged[match] = (merged[match][0], merged[match][1] + count)
    return sorted(merged, key=lambda item: (-item[1], item[0]))[:12], transparency


def _svg_colors(path: Path) -> tuple[list[tuple[tuple[int, int, int], int]], bool]:
    root = ElementTree.parse(path).getroot()
    colors: Counter[tuple[int, int, int]] = Counter()
    for node in root.iter():
        style = dict(part.split(":", 1) for part in node.get("style", "").split(";") if ":" in part)
        for value in (node.get("fill"), node.get("stroke"), style.get("fill"), style.get("stroke")):
            if value and HEX.fullmatch(value): colors[_rgb(value.upper())] += 1
    return colors.most_common(12), True


def analyze_logo_colors(path: Path) -> tuple[dict[str, Any], bool]:
    raw, transparency = _svg_colors(path) if path.suffix.casefold() == ".svg" else _raster_colors(path)
    total = sum(count for _, count in raw) or 1
    records = [_color_record(rgb, count, total) for rgb, count in raw]
    meaningful = [item for item in records if not _neutral(tuple(item["rgb"]))]
    neutrals = [item for item in records if _neutral(tuple(item["rgb"]))]
    primary = meaningful[0] if meaningful else (records[0] if records else None)
    secondary = meaningful[1] if len(meaningful) > 1 else None
    accent = meaningful[2] if len(meaningful) > 2 and meaningful[2]["coverage_percent"] >= .5 else None
    # Black/white are intentional neutral policy entries; logo grays remain logo-derived.
    neutral_policy = [_color_record((255, 255, 255), 0, 1, 1.0), _color_record((0, 0, 0), 0, 1, 1.0)]
    for item in neutral_policy: item.update(status="system_selected", source="contrast_policy", coverage_percent=0.0)
    palette = {"primary": primary, "secondary": secondary, "accent": accent,
               "neutrals": neutral_policy + neutrals, "logo_colors": records}
    return palette, transparency


def _property(value: Any, status: str, source: str, confidence: float = 1.0) -> dict[str, Any]:
    return {"value": value, "status": status, "source": source, "confidence": confidence}


def typography_system() -> dict[str, Any]:
    roles = {
        "headline": ("Bold", 1.0, 1.1, "max_2_lines"), "subheadline": ("Semibold", .7, 1.2, "sentence_case"),
        "body": ("Regular", .45, 1.45, "sentence_case"), "caption": ("Regular", .32, 1.35, "sentence_case"),
        "cta": ("Semibold", .42, 1.2, "sentence_case"), "contact": ("Regular", .34, 1.3, "preserve"),
        "technical_label": ("Semibold", .28, 1.2, "uppercase_latin_only"),
    }
    return {"status": "system_selected", "official_font_available": False, "production_safe": True,
            "primary_font": "Segoe UI", "fallback_fonts": ["Arial", "Helvetica", "sans-serif"],
            "optional_editorial_serif": "Georgia", "allow_unapproved_font_files": False,
            "roles": {name: {"preferred_font_family": "Segoe UI", "fallbacks": ["Arial", "Helvetica", "sans-serif"],
                              "weight": values[0], "relative_size": values[1], "letter_spacing_policy": "normal",
                              "line_height": values[2], "case_policy": values[3], "rtl_support": True}
                      for name, values in roles.items()},
            "language_rules": {
                "English": {"direction": "ltr", "alignment": "left", "fonts": ["Segoe UI", "Arial", "Helvetica", "sans-serif"]},
                "Arabic": {"direction": "rtl", "alignment": "right", "fonts": ["Segoe UI", "Arial", "Tahoma", "sans-serif"], "punctuation": "unicode_bidi", "numbers": "compatible", "mixed_latin_website": "bidi_isolate"},
                "Kurdish Sorani": {"direction": "rtl", "alignment": "right", "fonts": ["Segoe UI", "Arial", "Tahoma", "sans-serif"], "punctuation": "unicode_bidi", "numbers": "compatible", "mixed_latin_website": "bidi_isolate"},
            }}


def migrate_config(config: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    notes: list[dict[str, Any]] = []
    visual = config.setdefault("visual_identity", {})
    colors = visual.setdefault("colors", {})
    if colors.get("status") in {"unconfirmed", "default", None}:
        old = colors.get("status")
        colors["status"] = "missing"
        notes.append({"field": "visual_identity.colors.status", "previous_value": old, "new_value": "missing", "reason": "canonical_source_status_migration", "timestamp": _now()})
    for name in ("primary", "secondary", "accent"):
        old = colors.get(name)
        if not isinstance(old, dict):
            status = "missing" if old is None else "user_confirmed"
            colors[name] = _property(old, status, "legacy_config" if old is not None else "none")
            notes.append({"field": f"visual_identity.colors.{name}", "previous_value": old, "new_value": colors[name], "reason": "per_value_provenance_migration", "timestamp": _now()})
    typography = visual.setdefault("typography", {})
    if typography.get("status") == "system_defaults":
        old = dict(typography)
        typography.clear(); typography.update(typography_system())
        notes.append({"field": "visual_identity.typography", "previous_value": old, "new_value": "system_selected", "reason": "intentional_production_safe_system", "timestamp": _now()})
    approval = config.setdefault("approval", {})
    for key, default in (("status", "draft"), ("locked", False), ("approved_by", None), ("approved_at", None),
                         ("approved_config_hash", None), ("approved_logo_hash", None), ("notes", [])):
        approval.setdefault(key, default)
    return config, notes


def run_brand_identity_analyzer(root: Path, *, force: bool = False) -> IdentityResult:
    config_path = root / "input" / "brand" / "brand-config.json"
    inventory_path = root / "output" / "brand-analysis" / "domus-erbil-logo-inventory.json"
    output = root / "output" / "brand-analysis" / "domus-erbil-brand-identity.json"
    cache = root / "output" / "brand-analysis" / ".brand-identity-cache.json"
    config = json.loads(config_path.read_text(encoding="utf-8")); config, migrations = migrate_config(config)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    preferred_id = inventory.get("preferred_logo_id")
    record = next((item for item in inventory.get("logos", []) if item.get("logo_id") == preferred_id), None)
    logo_path = Path(record["path"]) if record else None
    logo_valid = bool(record and logo_path and logo_path.is_file() and record.get("suitability") in {"preferred", "usable"} and _sha(logo_path) == record.get("sha256"))
    signature = {"preferred_logo_hash": record.get("sha256") if record else None,
                 "brand_config_hash": _analysis_config_hash(config), "analyzer_version": ANALYZER_VERSION,
                 "color_analysis_version": COLOR_ANALYSIS_VERSION, "typography_policy_version": TYPOGRAPHY_POLICY_VERSION}
    signature["cache_key"] = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    if not force and output.is_file() and cache.is_file():
        try:
            if json.loads(cache.read_text(encoding="utf-8")) == signature:
                return IdentityResult(output, json.loads(output.read_text(encoding="utf-8")), config_path, True)
        except (OSError, ValueError): pass
    palette: dict[str, Any] = {"primary": None, "secondary": None, "accent": None, "neutrals": [], "logo_colors": []}
    transparency = False
    blocked: list[str] = []
    if logo_valid and logo_path:
        try: palette, transparency = analyze_logo_colors(logo_path)
        except (OSError, ValueError, ElementTree.ParseError, UnidentifiedImageError) as error: blocked.append(f"Preferred logo is corrupted or unreadable: {error}"); logo_valid = False
    else: blocked.append("No valid hash-verified preferred logo exists.")
    changes: list[dict[str, Any]] = []
    colors = config["visual_identity"]["colors"]
    for name in ("primary", "secondary", "accent"):
        current, derived = colors[name], palette[name]
        if current.get("status") not in {"official_confirmed", "user_confirmed"}:
            new = _property(derived["hex"], "logo_derived", "preferred_logo", derived["confidence"]) if derived else _property(None, "missing", "preferred_logo")
            if current != new:
                changes.append({"field": f"visual_identity.colors.{name}", "previous_value": current, "new_value": new,
                                "update_reason": "deterministic_logo_palette", "source": "preferred_logo", "timestamp": _now()})
                colors[name] = new
    colors["status"] = "logo_derived" if palette["primary"] else "missing"
    config["visual_identity"]["typography"].update(typography_system())
    config.setdefault("migration_notes", []).extend(migrations)
    _write(config_path, config)
    company = config.get("company", {})
    identity = {"brand_id": config.get("brand_id"), "identity_status": "blocked" if blocked else "analyzed",
                "brand_identity": {"official_name": _property(company.get("official_name"), "official_confirmed", "brand_config"),
                                   "display_name": _property(company.get("display_name"), "official_confirmed", "brand_config"),
                                   "website": _property(company.get("website"), "official_confirmed", "brand_config")},
                "preferred_logo": {**(record or {}), "valid": logo_valid, "hash_verified": logo_valid},
                "palette": palette, "transparency": transparency,
                "background_compatibility": {"white": any(c.get("contrast_on_white", 0) >= 3 for c in palette["logo_colors"]),
                                             "dark_neutral": any(c.get("contrast_on_dark", 0) >= 3 for c in palette["logo_colors"])},
                "color_usage_roles": {"primary": ["headings", "accent_bars", "cta_if_contrast_passes"], "secondary": ["supporting_graphics", "secondary_information"],
                                      "accent": ["limited_emphasis_only"], "neutral_light": ["clean_backgrounds"], "neutral_dark": ["dark_text", "panel_backgrounds"]},
                "contrast_recommendations": [item["text_safety"] for item in palette["logo_colors"]],
                "typography_system": typography_system(), "language_typography_rules": typography_system()["language_rules"],
                "contact_readiness": {"phone": "available" if company.get("phone_numbers") else "missing_optional", "email": "available" if company.get("email_addresses") else "missing_optional",
                                      "social_handles": "available" if company.get("social_handles") else "missing_optional", "address": "available" if company.get("address") else "missing_optional"},
                "blocked_reasons": blocked, "config_updates": changes, "migration_notes": migrations,
                "provenance": signature, "analyzer_version": ANALYZER_VERSION, "created_at": _now()}
    _write(output, identity); _write(cache, signature)
    return IdentityResult(output, identity, config_path)
