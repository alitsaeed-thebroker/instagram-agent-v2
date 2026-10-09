"""Persistence for marketing strategy JSON artifacts."""

from __future__ import annotations

from pathlib import Path

from src.strategy.schema import MarketingStrategy
from src.utils.config import STRATEGY_OUTPUT_DIRECTORY


def save_marketing_strategy(strategy: MarketingStrategy, filename: str | Path, output_directory: Path = STRATEGY_OUTPUT_DIRECTORY) -> Path:
    """Validate and save a strategy as ``output/strategy/<name>.json``."""
    name = Path(filename)
    if name.name != str(filename) or name.name in {"", ".", ".."}:
        raise ValueError("filename must not contain directory components")
    errors = strategy.validate()
    if errors:
        raise ValueError("Cannot save invalid marketing strategy: " + "; ".join(errors))
    destination = output_directory / name.with_suffix(".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(strategy.to_json() + "\n", encoding="utf-8")
    return destination
