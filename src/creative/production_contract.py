"""Fail-closed Department 4 production and handoff contract validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any

from PIL import Image

CONTRACT_VERSION = "1.0.0"
FORMAT_DIMENSIONS = {
    "instagram_feed_portrait": (1080, 1350),
    "instagram_feed_square": (1080, 1080),
    "instagram_story": (1080, 1920),
}
LANGUAGE_DIRECTIONS = {"en": "ltr", "ar": "rtl", "ku": "rtl"}
UNSUPPORTED_CLAIMS = re.compile(
    r"\b(?:guaranteed|guarantee|ROI|return on investment|rental yield|best investment|"
    r"limited time|last chance|selling fast|scarcity|price|payment plan|discount|availability)\b",
    re.I,
)


@dataclass(frozen=True)
class CreativeProductionInput:
    project_id: str
    opportunity_id: str
    asset_ids: tuple[str, ...]
    verified_fact_refs: tuple[str, ...]
    brand_config_hash: str
    format_name: str
    language_code: str
    provenance_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_project_context(project: str, artifacts: dict[str, dict[str, Any]]) -> None:
    """Reject any project-bearing upstream artifact from a different project."""
    mismatches = []
    for name, payload in artifacts.items():
        actual = payload.get("project_id", payload.get("project"))
        if isinstance(actual, (dict, list)):
            actual = None
        if actual is not None and str(actual) not in {"", project}:
            mismatches.append(f"{name}={actual}")
    if mismatches:
        raise ValueError("Department 4 blocked cross-project inputs: " + ", ".join(mismatches))


def infer_format(platform: str, width: int | None = None, height: int | None = None) -> str:
    value = str(platform).casefold()
    if "story" in value:
        return "instagram_story"
    if "portrait" in value or "4:5" in value:
        return "instagram_feed_portrait"
    if width == height and width:
        return "instagram_feed_square"
    return "instagram_feed_portrait"


def validate_publication_package(package: dict[str, Any], *, expected_project: str) -> list[str]:
    """Return deterministic blockers; an empty list is publication approval."""
    errors: list[str] = []
    if package.get("project_id") != expected_project:
        errors.append("cross-project package")
    code = str(package.get("language_code") or "")
    if code not in LANGUAGE_DIRECTIONS:
        errors.append("unsupported language")
    caption = package.get("master_caption") or package.get("caption") or {}
    if caption.get("project_id") not in {None, expected_project}:
        errors.append("cross-project caption")
    if caption.get("text_direction") != LANGUAGE_DIRECTIONS.get(code):
        errors.append("language direction mismatch")
    text = str(caption.get("full_caption") or "")
    if UNSUPPORTED_CLAIMS.search(text):
        errors.append("unsupported commercial or urgency claim")
    single = package.get("image") or {}
    records = package.get("slides") or [{**single, **{
        key: package.get(key) if package.get(key) is not None else single.get(key)
        for key in ("provenance_id", "source_asset_ids")
    }}]
    if not records or not all(isinstance(x, dict) for x in records):
        errors.append("missing media records")
        return errors
    if package.get("package_type") == "carousel" and [x.get("slide_number") for x in records] != list(range(1, len(records) + 1)):
        errors.append("invalid carousel order")
    if package.get("package_type")=="story":
        if str(package.get("platform","")).casefold() not in {"instagram","instagram story"}:errors.append("Story target must be Instagram")
        if len(records)!=1:errors.append("V1 Story requires exactly one image")
    for record in records:
        if not record.get("branded_item_id") or not record.get("provenance_id"):
            errors.append("incomplete item provenance")
        if not record.get("source_asset_ids"):
            errors.append("missing authentic source asset identity")
        path = Path(str(record.get("image_path") or ""))
        if not path.is_file():
            errors.append("missing rendered media")
            continue
        try:
            with Image.open(path) as image:
                expected = FORMAT_DIMENSIONS["instagram_story"] if package.get("package_type")=="story" else FORMAT_DIMENSIONS[infer_format(str(package.get("platform") or ""), *image.size)]
                if image.size != expected:
                    errors.append(f"invalid platform dimensions: {image.size[0]}x{image.size[1]}")
                if package.get("package_type")=="story" and image.size!=(1080,1920):errors.append("Story media must be 1080x1920")
        except OSError:
            errors.append("unreadable rendered media")
    return list(dict.fromkeys(errors))
