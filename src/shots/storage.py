"""Persistence for validated shot plan artifacts."""

from __future__ import annotations

from pathlib import Path

from src.shots.schema import ShotPlanCollection
from src.utils.config import SHOT_PLANS_OUTPUT_DIRECTORY


def save_shot_plans(
    collection: ShotPlanCollection,
    filename: str | Path,
    output_directory: Path = SHOT_PLANS_OUTPUT_DIRECTORY,
) -> Path:
    """Validate and save shot plans under ``output/shot-plans``."""
    name = Path(filename)
    if name.name != str(filename) or name.name in {"", ".", ".."}:
        raise ValueError("filename must not contain directory components")
    errors = collection.validate()
    if errors:
        raise ValueError("Cannot save invalid shot plans: " + "; ".join(errors))
    destination = output_directory / name.with_suffix(".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(collection.to_json() + "\n", encoding="utf-8")
    return destination
