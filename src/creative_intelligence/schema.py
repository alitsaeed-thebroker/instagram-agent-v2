"""Machine-readable contracts for the RECI creative opportunity map."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class TruthLayer(str, Enum):
    VERIFIED_FACT = "VERIFIED_FACT"
    SOURCE_MARKETING_CLAIM = "SOURCE_MARKETING_CLAIM"
    COMMERCIAL_INTERPRETATION = "COMMERCIAL_INTERPRETATION"
    CREATIVE_HYPOTHESIS = "CREATIVE_HYPOTHESIS"
    AUDIENCE_HYPOTHESIS = "AUDIENCE_HYPOTHESIS"
    CONTENT_OPPORTUNITY = "CONTENT_OPPORTUNITY"
    RESTRICTION = "RESTRICTION"


@dataclass
class Opportunity:
    opportunity_id: str
    opportunity_type: str
    category: str
    title: str
    objective: str
    buyer_value: list[str]
    sales_value: str
    recommended_message: str
    supporting_fact_ids: list[str]
    supporting_asset_ids: list[str]
    evidence_strength: int
    buyer_relevance: int
    visual_strength: int
    commercial_strength: int
    content_strength: int
    differentiation_potential: int
    lead_generation_potential: int
    score: int
    status: str
    priority: str
    recommended_formats: list[str]
    recommended_platforms: list[str]
    restrictions: list[str] = field(default_factory=list)
    blocked_claims: list[str] = field(default_factory=list)
    audience_hypotheses: list[str] = field(default_factory=list)
    recommended_asset_types: list[str] = field(default_factory=list)
    candidate_asset_ids: list[str] = field(default_factory=list)
    asset_relevance_scores: dict[str, int] = field(default_factory=dict)
    visual_evidence_notes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    explanation: str = ""
    truth_layers: list[dict[str, Any]] = field(default_factory=list)
    layout_sensitive: bool = False
    recommended_patterns: list[dict[str, Any]] = field(default_factory=list)
    relevant_anti_patterns: list[dict[str, Any]] = field(default_factory=list)
    pattern_usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class CreativeOpportunityMap:
    project_id: str
    reci_version: str
    generated_at: str
    contract_role: str
    input_fingerprint: str
    knowledge_version: str
    project_marketing_profile: dict[str, int]
    facts: list[dict[str, Any]]
    interpretations: list[dict[str, Any]]
    audience_hypotheses: list[dict[str, Any]]
    opportunities: list[Opportunity]
    weaknesses: list[str]
    restrictions: list[str]
    self_critique: dict[str, Any]
    metrics: dict[str, Any]
    provenance: dict[str, Any]
    creative_library_version: str = "unavailable"
    performance_learning_version: str = "unavailable"
    performance_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
