"""Fusion of per-document knowledge artifacts into one ProjectKnowledge object."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from src.knowledge.document_classifier import DocumentType
from src.knowledge.schema import ProjectKnowledge
from src.knowledge.commercial import resolve_project_intelligence
from src.knowledge.relational import build_canonical_intelligence
from src.knowledge.authority import candidate_id, source_authority, structured_resolution


FUSION_VERSION = "2.1.0"


class KnowledgeFusionError(ValueError):
    """Raised when validated artifacts disagree about the shape of a field."""


def fuse_knowledge(
    documents: list[tuple[ProjectKnowledge, DocumentType, Path]],
    *,
    project_namespace: str | None = None,
) -> tuple[ProjectKnowledge, list[dict]]:
    """Merge evidence without inventing facts; retain structured scalar conflicts."""
    merged: dict = ProjectKnowledge().to_dict()
    priorities: dict[str, dict] = {}
    conflicts: list[dict] = []
    document_intelligence = []
    identity_candidates: list[tuple[dict, int, str]] = []
    project = ""
    for knowledge, document_type, source in documents:
        candidate = asdict(knowledge)
        commercial = candidate.pop("commercial_intelligence", {})
        if commercial:
            document_intelligence.append(commercial)
            project = project or str(commercial.get("project") or "")
            identity_candidates.append((candidate.get("project_identity", {}), int(commercial.get("authority", 0)), str(commercial.get("source_file", source.name))))
        _merge_value(merged, candidate, (), document_type, priorities, conflicts, source.name)
    merged["commercial_intelligence"] = resolve_project_intelligence(document_intelligence, project) if project else {}
    _resolve_identity(merged, identity_candidates)
    _synchronize_legacy_pricing(merged)
    namespace = str(project_namespace or project or merged.get("project_identity", {}).get("project_name") or merged.get("project", {}).get("name") or "").strip()
    if namespace:
        merged["canonical_intelligence"] = build_canonical_intelligence(
            merged,
            project_namespace=namespace,
            fusion_conflicts=conflicts,
        ).to_dict()
    result = ProjectKnowledge.from_dict(merged)
    return result, conflicts


def _synchronize_legacy_pricing(data: dict) -> None:
    """Keep old readers stable while canonical commercial facts remain authoritative."""
    commercial = data.get("commercial_intelligence", {})
    pricing = commercial.get("pricing", {})
    starting = next((f for f in pricing.get("facts", []) if f.get("fact_type") == "starting_price" and f.get("status") == "verified"), None)
    if starting:
        data["pricing"]["starting_price"] = starting.get("value")
        data["pricing"]["currency"] = starting.get("currency") or data["pricing"].get("currency", "")
    data["pricing"]["payment_plan"] = ""


def _resolve_identity(data: dict, candidates: list[tuple[dict, int, str]]) -> None:
    conflicts = data.get("commercial_intelligence", {}).setdefault("conflicts", [])
    legacy = {"project_name": "name", "developer_name": "developer", "location": "location"}
    for field in ("project_name", "developer_name", "project_type", "location"):
        values: dict[str, list[tuple[int, str]]] = {}
        for identity, authority, source in candidates:
            value = str(identity.get(field) or "").strip()
            if value: values.setdefault(value, []).append((authority, source))
        if len(values) <= 1: continue
        ranked = sorted(((max(x[0] for x in refs), value, refs) for value, refs in values.items()), reverse=True)
        selected = ranked[0][1] if ranked[0][0] > ranked[1][0] else None
        data["project_identity"][field] = selected or ""
        if field in legacy: data["project"][legacy[field]] = selected or ""
        conflicts.append({"fact_type": f"project_identity.{field}", "status": "RESOLVED" if selected else "CONFLICTING",
                          "selected_value": selected, "candidates": [{"value": value, "authority": authority,
                          "sources": [source for _, source in refs]} for authority, value, refs in ranked],
                          "resolution_reason": "higher_source_authority" if selected else "equal_authority_conflict_requires_review"})


def _merge_value(target, candidate, path, document_type, priorities, conflicts, source):
    """Merge a value using path segments so mapping keys may contain literal dots."""
    segments = _path_segments(path)
    display_path = ".".join(segments)
    if isinstance(candidate, dict):
        if segments:
            container, key = _container(target, segments, source)
            existing = container.get(key)
            if existing is None:
                container[key] = {}
            elif not isinstance(existing, dict):
                raise _structural_conflict(display_path, existing, candidate, source)
        for key, value in candidate.items():
            _merge_value(target, value, (*segments, key), document_type, priorities, conflicts, source)
        return
    if isinstance(candidate, list):
        container, key = _container(target, segments, source)
        existing = container.get(key)
        if existing is not None and not isinstance(existing, list):
            raise _structural_conflict(display_path, existing, candidate, source)
        if candidate and all(isinstance(item, dict) for item in candidate):
            container[key] = _merge_records(container.get(key, []), candidate)
        elif candidate:
            container[key] = list(dict.fromkeys([*container.get(key, []), *candidate]))
        return
    if not _present(candidate):
        return
    confidence = _confidence(document_type, display_path)
    authority = source_authority(document_type, source)
    container, key = _container(target, segments, source)
    existing = container.get(key)
    if isinstance(existing, (dict, list)):
        raise _structural_conflict(display_path, existing, candidate, source)
    incoming_meta = {
        "candidate_id": candidate_id(display_path, source, candidate),
        "fact_type": display_path,
        "value": candidate,
        "source_file": source,
        "document_type": document_type.value,
        "authority": authority,
        "path_confidence": confidence,
        "freshness": {"basis": "unknown"},
    }
    previous = priorities.get(display_path, {})
    pool = list(previous.get("_candidates", []))
    if not pool and _present(existing):
        pool.append(previous or {
            "candidate_id": candidate_id(display_path, "unknown", existing),
            "fact_type": display_path, "value": existing, "source_file": "unknown",
            "document_type": "Unknown", "authority": 0, "path_confidence": 0,
            "freshness": {"basis": "unknown"},
        })
    pool = {item["candidate_id"]: item for item in [*pool, incoming_meta]}
    candidates = sorted(pool.values(), key=lambda item: item["candidate_id"])
    rank = lambda item: (int(item.get("path_confidence", 0)), int(item.get("authority", 0)))
    best_rank = max(map(rank, candidates))
    leaders = [item for item in candidates if rank(item) == best_rank]
    values = {json.dumps(item["value"], sort_keys=True, ensure_ascii=False) for item in leaders}
    selected = leaders[0] if len(values) == 1 else None
    container[key] = selected["value"] if selected else ""
    # Keep the complete candidate set even while its compatibility value is blank.
    priorities[display_path] = {**(selected or {}), "_candidates": candidates}
    conflicts[:] = [item for item in conflicts if not isinstance(item, dict) or item.get("fact_key") != display_path]
    all_values = {json.dumps(item["value"], sort_keys=True, ensure_ascii=False) for item in candidates}
    if len(all_values) > 1:
        conflicts.append(structured_resolution(
            fact_key=display_path, candidates=candidates, selected=selected,
            reason="higher_field_authority" if selected else "equal_field_authority_conflict_requires_review",
        ))



def _path_segments(path: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(path, tuple):
        return path
    return tuple(path.split(".")) if path else ()


def _container(data: dict, path: tuple[str, ...], source: str) -> tuple[dict, str]:
    if not path:
        raise KnowledgeFusionError(f"Cannot merge a scalar at the knowledge root from {source}")
    parts = path
    for part in parts[:-1]:
        existing = data.get(part)
        if existing is None:
            data[part] = {}
        elif not isinstance(existing, dict):
            raise _structural_conflict(".".join(parts), existing, {}, source)
        data = data[part]
    return data, parts[-1]


def _structural_conflict(path: str, existing, incoming, source: str) -> KnowledgeFusionError:
    def kind(value) -> str:
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "list"
        return type(value).__name__

    return KnowledgeFusionError(
        f"Structural knowledge conflict at '{path}': existing {kind(existing)} "
        f"cannot be merged with incoming {kind(incoming)} from {source}"
    )


def _merge_records(existing: list[dict], incoming: list[dict]) -> list[dict]:
    result = list(existing)
    for record in incoming:
        if record not in result:
            result.append(record)
    return result


def _present(value) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _confidence(document_type: DocumentType, path: str) -> int:
    """Rank the document best suited to each factual field."""
    if path.startswith("pricing."):
        if path == "pricing.payment_plan":
            return 0
        return {DocumentType.PRICE_LIST: 100}.get(document_type, 70)
    if path.startswith("units"):
        return {DocumentType.FLOOR_PLANS: 100, DocumentType.PRICE_LIST: 90}.get(document_type, 70)
    if path.startswith("architecture"):
        return {DocumentType.TECHNICAL_SPECIFICATIONS: 100, DocumentType.CATALOGUE: 85}.get(document_type, 70)
    if path.startswith("project"):
        return {DocumentType.CATALOGUE: 100, DocumentType.PRESENTATION: 80}.get(document_type, 70)
    return {DocumentType.CATALOGUE: 85, DocumentType.MASTER_PLAN: 80}.get(document_type, 70)
