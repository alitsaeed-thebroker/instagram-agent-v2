"""Fail-closed policy for authentic project visuals."""

from __future__ import annotations

from src.utils.config import PROJECT_VISUAL_MODE


FORBIDDEN_OPERATIONS = {
    "text_to_image", "generate", "inpaint", "outpaint", "replace_building",
    "replace_interior", "replace_landscape", "add_people", "add_cars",
    "add_feature", "remove_feature",
}
ALLOWED_ENHANCEMENTS = {
    "brightness", "contrast", "exposure", "white_balance", "noise_reduction",
    "sharpening", "super_resolution", "perspective_correction", "color_recovery",
    "margin_removal", "compression_cleanup", "crop", "resize", "export",
}


def enforce_source_only(operation: str) -> None:
    """Reject any synthetic or content-changing image operation."""
    if PROJECT_VISUAL_MODE != "source_only":
        raise ValueError("PROJECT_VISUAL_MODE must remain source_only for production visuals")
    if operation.casefold() in FORBIDDEN_OPERATIONS or operation.casefold() not in ALLOWED_ENHANCEMENTS:
        raise ValueError(f"Operation is forbidden in source-only mode: {operation}")
