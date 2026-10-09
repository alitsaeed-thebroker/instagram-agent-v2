"""Persistence for content plan JSON artifacts."""

from __future__ import annotations

from pathlib import Path

from src.content.schema import ContentPlan
from src.utils.config import CONTENT_OUTPUT_DIRECTORY


def save_content_plan(plan: ContentPlan, filename: str | Path, output_directory: Path = CONTENT_OUTPUT_DIRECTORY) -> Path:
    """Validate and save a plan as ``output/content/<name>.json``."""
    name = Path(filename)
    if name.name != str(filename) or name.name in {"", ".", ".."}:
        raise ValueError("filename must not contain directory components")
    errors = plan.validate()
    if errors:
        raise ValueError("Cannot save invalid content plan: " + "; ".join(errors))
    destination = output_directory / name.with_suffix(".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(plan.to_json() + "\n", encoding="utf-8")
    return destination
