"""Persistence for validated scene plan artifacts."""

from __future__ import annotations

from pathlib import Path

from src.scenes.schema import ScenePlanCollection
from src.utils.config import SCENE_PLANS_OUTPUT_DIRECTORY


def save_scene_plans(
    collection: ScenePlanCollection,
    filename: str | Path,
    output_directory: Path = SCENE_PLANS_OUTPUT_DIRECTORY,
) -> Path:
    """Validate and save scene plans under ``output/scene-plans``."""
    name = Path(filename)
    if name.name != str(filename) or name.name in {"", ".", ".."}:
        raise ValueError("filename must not contain directory components")
    errors = collection.validate()
    if errors:
        raise ValueError("Cannot save invalid scene plans: " + "; ".join(errors))
    destination = output_directory / name.with_suffix(".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(collection.to_json() + "\n", encoding="utf-8")
    return destination
