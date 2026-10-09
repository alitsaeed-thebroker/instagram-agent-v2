"""Canonical Department 2 consumer contract for Departments 3-5.

Production consumers must not reconstruct authority from legacy ProjectKnowledge
fields. This module is the only sanctioned adapter from the relational graph to
downstream marketing/read models.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.knowledge.relational import CanonicalIntelligence

CANONICAL_CONSUMER_VERSION = "1.0.0"
ALLOWED_COMMERCIAL_FACTS = frozenset({
    "commercial.price_per_sqm",
    "commercial.total_unit_price",
    "commercial.starting_price",
})

_PATH_ALIASES = {
    "project.project_name": "project_identity.project_name",
    "project.developer_name": "project_identity.developer_name",
    "project.project_type": "project_identity.project_type",
    "project.location": "project_identity.location",
    "amenity.name": "amenities",
}


@dataclass(frozen=True)
class ConsumerFact:
    fact_id: str
    path: str
    canonical_path: str
    value: Any
    project_id: str
    category: str
    status: str
    commercial: bool
    evidence: list[dict[str, Any]]
    authority: int | None
    currency: str | None
    unit: str | None
    relationship_context: dict[str, Any]


def require_canonical_graph(
    knowledge: dict[str, Any],
    *,
    expected_project: str | None = None,
) -> CanonicalIntelligence:
    raw = knowledge.get("canonical_intelligence")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("Canonical Department 2 relational intelligence is required")
    graph = CanonicalIntelligence.from_dict(raw)
    if expected_project is not None and _norm(graph.project_namespace) != _norm(expected_project):
        raise ValueError(
            f"Canonical Department 2 project mismatch: {graph.project_namespace!r} != {expected_project!r}"
        )
    return graph


def canonical_project_identity(
    knowledge: dict[str, Any],
    *,
    expected_project: str | None = None,
) -> dict[str, str]:
    graph = require_canonical_graph(knowledge, expected_project=expected_project)
    result = {
        "project_name": "",
        "developer_name": "",
        "project_type": "",
        "location": "",
    }
    mapping = {
        "project.project_name": "project_name",
        "project.developer_name": "developer_name",
        "project.project_type": "project_type",
        "project.location": "location",
    }
    for fact in graph.facts:
        target = mapping.get(fact.fact_type)
        if not target:
            continue
        if fact.state != "VERIFIED" or not fact.marketing_eligible:
            continue
        result[target] = str(fact.value or "").strip()
    # Namespace is authoritative even when display-name evidence is missing.
    if not result["project_name"]:
        result["project_name"] = graph.project_namespace
    return result


def canonical_verified_facts(
    knowledge: dict[str, Any],
    project: str,
    *,
    include_commercial: bool = True,
) -> dict[str, ConsumerFact]:
    graph = require_canonical_graph(knowledge, expected_project=project)
    result: dict[str, ConsumerFact] = {}
    for fact in graph.facts:
        if fact.state != "VERIFIED" or fact.marketing_eligible is not True:
            continue
        commercial = fact.fact_type.startswith("commercial.")
        if commercial and (not include_commercial or fact.fact_type not in ALLOWED_COMMERCIAL_FACTS):
            continue
        evidence = [
            dict(item)
            for item in fact.provenance
            if _valid_evidence(item, project)
        ]
        if not evidence:
            continue
        path = _PATH_ALIASES.get(fact.fact_type, fact.fact_type)
        category = "commercial" if commercial else _category(path)
        result[fact.fact_id] = ConsumerFact(
            fact_id=fact.fact_id,
            path=path,
            canonical_path=fact.fact_type,
            value=fact.value,
            project_id=project,
            category=category,
            status="verified",
            commercial=commercial,
            evidence=evidence,
            authority=fact.authority,
            currency=fact.currency,
            unit=fact.unit,
            relationship_context=dict(fact.relationship_context or {}),
        )
    return result


def canonical_fact_records(
    knowledge: dict[str, Any],
    project: str,
    *,
    include_commercial: bool = True,
) -> list[dict[str, Any]]:
    return [
        {
            "fact_id": fact.fact_id,
            "path": fact.path,
            "canonical_path": fact.canonical_path,
            "value": fact.value,
            "project_id": fact.project_id,
            "category": fact.category,
            "status": fact.status,
            "commercial": fact.commercial,
            "evidence": fact.evidence,
            "authority": fact.authority,
            "currency": fact.currency,
            "unit": fact.unit,
            "relationship_context": fact.relationship_context,
            "consumer_contract_version": CANONICAL_CONSUMER_VERSION,
        }
        for fact in canonical_verified_facts(
            knowledge, project, include_commercial=include_commercial
        ).values()
    ]


def _valid_evidence(item: dict[str, Any], project: str) -> bool:
    if not isinstance(item, dict):
        return False
    owner = item.get("source_project") or item.get("project")
    if _norm(owner) != _norm(project):
        return False
    if not item.get("evidence_id"):
        return False
    if not item.get("source_id") or not item.get("source_sha256"):
        return False
    if not (item.get("source_file") or item.get("source_document")):
        return False
    if not item.get("source_text"):
        return False
    if not item.get("extraction_method"):
        return False
    if not (
        any(
            item.get(key) is not None
            for key in ("page", "source_page", "line_range", "paragraph")
        )
        or (item.get("table_index") is not None and item.get("row_index") is not None)
    ):
        return False
    return True


def _category(path: str) -> str:
    if path.startswith("project_identity."):
        return "project_identity"
    if path.startswith("amenit"):
        return "amenities"
    if path.startswith("unit."):
        return "units"
    return path.split(".", 1)[0]


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())
