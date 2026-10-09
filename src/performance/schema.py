"""Data contracts for publication performance and creative attribution."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MetricSnapshot:
    observed_at: str
    window: str
    maturity: str
    metrics: dict[str, float | int | None]
    metric_definitions: dict[str, str] = field(default_factory=dict)
    paid_status: str = "unknown"
    freshness: str = "CURRENT"
    outlier_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PublicationPerformance:
    publication_id: str
    project_id: str
    platform: str
    format: str
    objective: str
    published_at: str
    post_package_id: str | None = None
    content_id: str | None = None
    asset_ids: list[str] = field(default_factory=list)
    visual_direction_contract_id: str | None = None
    pattern_ids: list[str] = field(default_factory=list)
    reci_opportunity_id: str | None = None
    campaign_id: str | None = None
    caption_version: str | None = None
    creative_family: str = "unknown"
    composition_strategy: str = "unknown"
    logo_prominence: str = "unknown"
    information_density: str = "unknown"
    asset_type: str = "unknown"
    headline_style: str = "unknown"
    content_category: str = "unknown"
    carousel_length: int | None = None
    cta_type: str = "no_cta"
    caption_structure: str = "unknown"
    story_structure: list[str] = field(default_factory=list)
    factual_safety: str = "VERIFIED"
    reci_attribution: dict[str, Any] = field(default_factory=dict)
    snapshots: list[MetricSnapshot] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceExperiment:
    experiment_id: str
    hypothesis: str
    control: str
    variant: str
    changed_dimension: str
    constant_dimensions: list[str]
    success_metric: str
    result: str = "PENDING"
    confidence: str = "INSUFFICIENT_DATA"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
