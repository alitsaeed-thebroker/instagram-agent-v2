"""Persistence for campaign planning JSON artifacts."""

from __future__ import annotations

from pathlib import Path

from src.campaign.schema import CampaignPlan
from src.utils.config import CAMPAIGNS_OUTPUT_DIRECTORY


def save_campaign_plan(plan: CampaignPlan, filename: str | Path, output_directory: Path = CAMPAIGNS_OUTPUT_DIRECTORY) -> Path:
    """Validate and save a plan as ``output/campaigns/<name>.json``."""
    name = Path(filename)
    if name.name != str(filename) or name.name in {"", ".", ".."}:
        raise ValueError("filename must not contain directory components")
    errors = plan.validate()
    if errors:
        raise ValueError("Cannot save invalid campaign plan: " + "; ".join(errors))
    destination = output_directory / name.with_suffix(".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(plan.to_json() + "\n", encoding="utf-8")
    return destination
