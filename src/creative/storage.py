"""Persistence for creative direction JSON artifacts."""

from __future__ import annotations

from pathlib import Path

from src.creative.schema import CreativeDirectionPlan
from src.utils.config import CREATIVE_DIRECTIONS_OUTPUT_DIRECTORY


def save_creative_directions(
    plan: CreativeDirectionPlan,
    filename: str | Path,
    output_directory: Path = CREATIVE_DIRECTIONS_OUTPUT_DIRECTORY,
) -> Path:
    """Validate and save directions under ``output/creative-directions``."""
    name = Path(filename)
    if name.name != str(filename) or name.name in {"", ".", ".."}:
        raise ValueError("filename must not contain directory components")
    errors = plan.validate()
    if errors:
        raise ValueError("Cannot save invalid creative directions: " + "; ".join(errors))
    destination = output_directory / name.with_suffix(".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(plan.to_json() + "\n", encoding="utf-8")
    return destination
