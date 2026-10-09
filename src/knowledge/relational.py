"""Relational, provenance-aware real-estate intelligence contract.

This is the canonical Department 2 model. Legacy ProjectKnowledge fields remain
compatibility projections only and must not be used to join commercial/unit data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable

RELATIONAL_SCHEMA_VERSION = "2.0.0"
FACT_STATES = frozenset({"VERIFIED", "UNVERIFIED", "CONFLICTING", "UNKNOWN", "ABSENT"})
ENTITY_TYPES = frozenset({
    "project", "building", "tower", "unit_type", "unit", "plan",
    "amenity", "location_relationship", "commercial_offer",
})


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(x or "").strip().casefold() for x in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


@dataclass
class EntityRecord:
    entity_id: str
    entity_type: str
    project_namespace: str
    label: str = ""
    parent_entity_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors = []
        if self.entity_type not in ENTITY_TYPES:
            errors.append(f"unsupported entity_type: {self.entity_type}")
        if not self.entity_id:
            errors.append("entity_id is required")
        if not self.project_namespace:
            errors.append("project_namespace is required")
        return errors


@dataclass
class FactRecord:
    fact_id: str
    entity_id: str
    fact_type: str
    value: Any = None
    unit: str | None = None
    currency: str | None = None
    state: str = "UNVERIFIED"
    confidence: float = 0.0
    authority: int | None = None
    marketing_eligible: bool = False
    provenance: list[dict[str, Any]] = field(default_factory=list)
    relationship_context: dict[str, Any] = field(default_factory=dict)
    effective_date: str | None = None
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def validate(self) -> list[str]:
        errors = []
        if not self.fact_id or not self.entity_id or not self.fact_type:
            errors.append("fact_id, entity_id and fact_type are required")
        if self.state not in FACT_STATES:
            errors.append(f"unsupported fact state: {self.state}")
        if self.state == "VERIFIED":
            if not self.provenance:
                errors.append(f"verified fact {self.fact_id} has no provenance")
            for record in self.provenance:
                missing = [
                    key for key in (
                        "evidence_id", "source_project", "source_file",
                        "source_id", "source_sha256",
                        "source_text", "extraction_method",
                    )
                    if not record.get(key)
                ]
                if missing:
                    errors.append(
                        f"verified fact {self.fact_id} has incomplete provenance: {','.join(missing)}"
                    )
                if not (
                    any(record.get(key) is not None for key in ("page", "source_page", "line_range", "paragraph"))
                    or (record.get("table_index") is not None and record.get("row_index") is not None)
                ):
                    errors.append(f"verified fact {self.fact_id} has no exact source locator")
        if self.marketing_eligible and self.state != "VERIFIED":
            errors.append(f"non-verified fact {self.fact_id} cannot be marketing eligible")
        return errors


@dataclass
class CanonicalIntelligence:
    project_namespace: str
    schema_version: str = RELATIONAL_SCHEMA_VERSION
    contract_role: str = "authoritative_department2_relational_intelligence"
    entities: list[EntityRecord] = field(default_factory=list)
    facts: list[FactRecord] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    unknowns: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.schema_version != RELATIONAL_SCHEMA_VERSION:
            errors.append(f"unsupported relational schema version: {self.schema_version}")
        if self.contract_role != "authoritative_department2_relational_intelligence":
            errors.append("invalid relational intelligence contract role")
        if not self.project_namespace:
            errors.append("project_namespace is required")
        ids: set[str] = set()
        for entity in self.entities:
            errors.extend(entity.validate())
            if entity.entity_id in ids:
                errors.append(f"duplicate entity_id: {entity.entity_id}")
            ids.add(entity.entity_id)
        fact_ids: set[str] = set()
        for fact in self.facts:
            errors.extend(fact.validate())
            if fact.entity_id not in ids:
                errors.append(f"fact {fact.fact_id} references missing entity {fact.entity_id}")
            if fact.fact_id in fact_ids:
                errors.append(f"duplicate fact_id: {fact.fact_id}")
            fact_ids.add(fact.fact_id)
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CanonicalIntelligence":
        if not isinstance(data, dict):
            raise ValueError("canonical_intelligence must be an object")
        obj = cls(
            project_namespace=str(data.get("project_namespace") or ""),
            schema_version=str(data.get("schema_version") or RELATIONAL_SCHEMA_VERSION),
            contract_role=str(data.get("contract_role") or ""),
            entities=[EntityRecord(**x) for x in data.get("entities", [])],
            facts=[FactRecord(**x) for x in data.get("facts", [])],
            conflicts=list(data.get("conflicts", [])),
            unknowns=list(data.get("unknowns", [])),
            metadata=dict(data.get("metadata", {})),
        )
        errors = obj.validate()
        if errors:
            raise ValueError("Invalid canonical intelligence: " + "; ".join(errors))
        return obj


def _prov(
    records: Any,
    project_namespace: str,
    *,
    expected_value: Any = None,
    require_direct: bool = True,
) -> list[dict[str, Any]]:
    """Return only provenance that belongs to this project and exact fact value."""
    result = []
    for raw in records if isinstance(records, list) else []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        owner = str(item.get("source_project") or item.get("project") or "")
        if owner.strip().casefold() != project_namespace.strip().casefold():
            continue
        if expected_value is not None and "fact_value" in item:
            if _clean(item.get("fact_value")).casefold() != _clean(expected_value).casefold():
                continue
        status = str(item.get("support_status") or item.get("status") or "").casefold()
        if require_direct and status not in {"direct", "supported", "verified"}:
            continue
        if str(item.get("structure_status") or "regular").casefold() != "regular":
            continue
        result.append(item)
    return result


def _provenance_complete(records: list[dict[str, Any]]) -> bool:
    if not records:
        return False
    for record in records:
        if not all(record.get(key) for key in (
            "evidence_id", "source_project", "source_file", "source_id", "source_sha256", "source_text", "extraction_method"
        )):
            return False
        if not (
            any(record.get(key) is not None for key in ("page", "source_page", "line_range", "paragraph"))
            or (record.get("table_index") is not None and record.get("row_index") is not None)
        ):
            return False
    return True


def _state(provenance: list[dict[str, Any]], *, verified_hint: bool = False, conflicting: bool = False) -> str:
    if conflicting:
        return "CONFLICTING"
    if provenance and verified_hint and _provenance_complete(provenance):
        return "VERIFIED"
    if provenance:
        return "UNVERIFIED"
    return "UNKNOWN"


def _fact(
    *,
    project_namespace: str,
    entity_id: str,
    fact_type: str,
    value: Any,
    provenance: list[dict[str, Any]],
    unit: str | None = None,
    currency: str | None = None,
    confidence: float = 0.0,
    authority: int | None = None,
    verified_hint: bool = False,
    relationship_context: dict[str, Any] | None = None,
    effective_date: str | None = None,
    conflicts: list[dict[str, Any]] | None = None,
) -> FactRecord:
    state = _state(provenance, verified_hint=verified_hint, conflicting=bool(conflicts))
    context = dict(relationship_context or {})
    context.setdefault("project_namespace", project_namespace)
    fid = _stable_id("fact", project_namespace, entity_id, fact_type, json.dumps(value, sort_keys=True, default=str), unit, currency)
    return FactRecord(
        fact_id=fid,
        entity_id=entity_id,
        fact_type=fact_type,
        value=value,
        unit=unit,
        currency=currency,
        state=state,
        confidence=float(confidence or 0.0),
        authority=authority,
        marketing_eligible=(state == "VERIFIED"),
        provenance=provenance,
        relationship_context=context,
        effective_date=effective_date,
        conflicts=list(conflicts or []),
    )


def build_canonical_intelligence(
    legacy: dict[str, Any],
    *,
    project_namespace: str,
    fusion_conflicts: Iterable[Any] = (),
) -> CanonicalIntelligence:
    """Build the relational source of truth from fused legacy+commercial evidence.

    The function deliberately does not infer relationships that are absent from
    evidence. Unknown unit/building context stays project-scoped rather than
    being guessed.
    """
    project_id = _stable_id("project", project_namespace)
    entities: list[EntityRecord] = [
        EntityRecord(project_id, "project", project_namespace, label=project_namespace)
    ]
    facts: list[FactRecord] = []
    provenance = legacy.get("fact_provenance", {}) if isinstance(legacy.get("fact_provenance"), dict) else {}

    identity = legacy.get("project_identity", {}) if isinstance(legacy.get("project_identity"), dict) else {}
    fallback_project = legacy.get("project", {}) if isinstance(legacy.get("project"), dict) else {}
    identity_fields = {
        "project_name": identity.get("project_name") or fallback_project.get("name"),
        "developer_name": identity.get("developer_name") or fallback_project.get("developer"),
        "project_type": identity.get("project_type"),
        "location": identity.get("location") or fallback_project.get("location"),
    }
    for key, value in identity_fields.items():
        value = _clean(value)
        if not value:
            continue
        p = _prov(provenance.get(f"project_identity.{key}", []), project_namespace, expected_value=value)
        facts.append(_fact(
            project_namespace=project_namespace, entity_id=project_id,
            fact_type=f"project.{key}", value=value, provenance=p,
            verified_hint=bool(p), confidence=1.0 if p else 0.0,
        ))

    # Source-grounded project-level descriptive facts. These remain facts only
    # when their exact producer provenance survives; otherwise they are UNKNOWN
    # and never marketing eligible.
    general_scalars = [
        ("project.description", fallback_project.get("description"), "project.description"),
        ("branding.name", (legacy.get("branding") or {}).get("name"), "branding.name"),
        ("branding.tagline", (legacy.get("branding") or {}).get("tagline"), "branding.tagline"),
        ("branding.tone_of_voice", (legacy.get("branding") or {}).get("tone_of_voice"), "branding.tone_of_voice"),
        ("architecture.style", (legacy.get("architecture") or {}).get("style"), "architecture.style"),
        ("architecture.architect", (legacy.get("architecture") or {}).get("architect"), "architecture.architect"),
        ("investment.expected_return", (legacy.get("investment") or {}).get("expected_return"), "investment.expected_return"),
        ("investment.rental_potential", (legacy.get("investment") or {}).get("rental_potential"), "investment.rental_potential"),
        ("investment.completion_date", (legacy.get("investment") or {}).get("completion_date"), "investment.completion_date"),
    ]
    for fact_type, raw_value, provenance_path in general_scalars:
        value = _clean(raw_value)
        if not value:
            continue
        p = _prov(provenance.get(provenance_path, []), project_namespace, expected_value=value)
        facts.append(_fact(
            project_namespace=project_namespace, entity_id=project_id,
            fact_type=fact_type, value=value, provenance=p,
            verified_hint=bool(p), confidence=1.0 if p else 0.0,
        ))

    for root, fields in (
        ("branding", ("key_messages",)),
        ("architecture", ("materials", "design_features")),
        ("investment", ("highlights",)),
    ):
        container = legacy.get(root) or {}
        for field_name in fields:
            for index, raw_value in enumerate(container.get(field_name, []) or []):
                value = _clean(raw_value)
                if not value:
                    continue
                path = f"{root}.{field_name}[{index}]"
                p = _prov(provenance.get(path, []), project_namespace, expected_value=value)
                facts.append(_fact(
                    project_namespace=project_namespace, entity_id=project_id,
                    fact_type=f"{root}.{field_name}", value=value, provenance=p,
                    verified_hint=bool(p), confidence=1.0 if p else 0.0,
                ))

    # Marketing facts are source language only. Conservative analytical
    # inferences remain non-authoritative even if they cite supporting evidence.
    marketing = legacy.get("marketing") or {}
    for field_name in ("target_audience", "selling_points", "calls_to_action"):
        for index, raw_value in enumerate(marketing.get(field_name, []) or []):
            text = _clean(raw_value)
            if not text:
                continue
            is_inference = text.casefold().startswith("[inference |")
            value = re.sub(r"^\[(?:Fact|Inference)\s*\|\s*(?:High|Medium)\]\s*", "", text, flags=re.I).strip()
            path = f"marketing.{field_name}[{index}]"
            p = _prov(
                provenance.get(path, []),
                project_namespace,
                expected_value=value,
                require_direct=not is_inference,
            )
            facts.append(_fact(
                project_namespace=project_namespace, entity_id=project_id,
                fact_type=f"marketing.{field_name}", value=value, provenance=p,
                verified_hint=bool(p) and not is_inference,
                confidence=1.0 if p and not is_inference else 0.5 if p else 0.0,
            ))

    # Amenities are individual entities so provenance and future relationships
    # can be attached without a flat string-array join.
    for index, raw in enumerate(legacy.get("amenities", []) or []):
        label = _clean(raw)
        if not label:
            continue
        eid = _stable_id("amenity", project_namespace, label)
        entities.append(EntityRecord(eid, "amenity", project_namespace, label=label, parent_entity_id=project_id))
        p = _prov(provenance.get(f"amenities[{index}]", []), project_namespace, expected_value=label)
        facts.append(_fact(
            project_namespace=project_namespace, entity_id=eid, fact_type="amenity.name",
            value=label, provenance=p, verified_hint=bool(p), confidence=1.0 if p else 0.0,
            relationship_context={"project_id": project_id},
        ))

    # Legacy unit records become separate entities. Values from different unit
    # records can therefore never be joined merely because their fact types match.
    for index, raw in enumerate(legacy.get("units", []) or []):
        unit = raw if isinstance(raw, dict) else {}
        label = _clean(unit.get("name")) or f"unit-{index + 1}"
        bedrooms = unit.get("bedrooms")
        area = unit.get("area_sqm")
        eid = _stable_id("unit_type", project_namespace, label, bedrooms, area)
        entities.append(EntityRecord(
            eid, "unit_type", project_namespace, label=label, parent_entity_id=project_id,
            attributes={"legacy_index": index},
        ))
        context = {"project_id": project_id, "unit_entity_id": eid, "unit_label": label}
        for field_name, unit_name in (
            ("name", None), ("bedrooms", "bedrooms"), ("bathrooms", "bathrooms"),
            ("area_sqm", "sqm"), ("starting_price", None),
        ):
            value = unit.get(field_name)
            if value in (None, ""):
                continue
            p = _prov(
                provenance.get(f"units[{index}].{field_name}", provenance.get(f"units[{index}]", [])),
                project_namespace,
                expected_value=value,
            )
            facts.append(_fact(
                project_namespace=project_namespace, entity_id=eid,
                fact_type=f"unit.{field_name}", value=value, unit=unit_name,
                provenance=p, verified_hint=bool(p), confidence=1.0 if p else 0.0,
                relationship_context=context,
            ))

    commercial = legacy.get("commercial_intelligence", {}) if isinstance(legacy.get("commercial_intelligence"), dict) else {}
    commercial_facts: list[dict[str, Any]] = []
    commercial_facts.extend(commercial.get("pricing", {}).get("facts", []) or [])
    commercial_facts.extend(commercial.get("commercial_terms", []) or [])

    entity_cache: dict[tuple[Any, ...], str] = {}
    for raw in commercial_facts:
        if not isinstance(raw, dict):
            continue
        context = dict(raw.get("relationship_context") or {})
        # Never guess missing context. If specific unit/tower context exists,
        # create a distinct entity keyed by that exact relationship tuple.
        relationship_key = (
            _clean(context.get("building")),
            _clean(context.get("tower")),
            _clean(context.get("unit_id")),
            _clean(context.get("unit_type")),
            context.get("bedrooms"),
            context.get("floor"),
            context.get("area_sqm"),
            _clean(context.get("payment_plan_id")),
        )
        fact_type = str(raw.get("fact_type") or "")
        specific = any(x not in ("", None) for x in relationship_key)
        if specific:
            cache_key = ("commercial_offer", *relationship_key)
            if cache_key not in entity_cache:
                eid = _stable_id("commercial_offer", project_namespace, *relationship_key)
                entity_cache[cache_key] = eid
                entities.append(EntityRecord(
                    eid,
                    "commercial_offer",
                    project_namespace,
                    label=_clean(context.get("unit_id") or context.get("unit_type") or "commercial offer"),
                    parent_entity_id=project_id,
                    attributes={k: v for k, v in context.items() if v not in ("", None)},
                ))
            entity_id = entity_cache[cache_key]
        else:
            entity_id = project_id

        evidence = _prov(raw.get("evidence", []), project_namespace, require_direct=False)
        status = str(raw.get("status") or "").casefold()
        relationship_safe = raw.get("relationship_status") != "ambiguous"
        verified = status == "verified" and bool(evidence) and relationship_safe
        value = raw.get("value")
        if value is None and ("minimum" in raw or "maximum" in raw):
            value = {"minimum": raw.get("minimum"), "maximum": raw.get("maximum")}
        if value is None and "percentage" in raw:
            value = raw.get("percentage")
        effective = next((e.get("document_date") for e in evidence if e.get("document_date")), None)
        facts.append(_fact(
            project_namespace=project_namespace,
            entity_id=entity_id,
            fact_type=f"commercial.{raw.get('fact_type')}",
            value=value,
            unit="percent" if "percentage" in raw else raw.get("unit"),
            currency=raw.get("currency"),
            provenance=evidence,
            verified_hint=verified,
            confidence=float(raw.get("confidence") or 0.0),
            authority=int(raw.get("authority") or 0),
            relationship_context={
                **context,
                "project_id": project_id,
                "relationship_status": raw.get("relationship_status"),
                "relationship_key": raw.get("relationship_key"),
            },
            effective_date=effective,
        ))

    entities = list({entity.entity_id: entity for entity in entities}.values())
    facts = list({fact.fact_id: fact for fact in facts}.values())
    all_conflicts = [
        {"legacy_conflict": c} if isinstance(c, str) else dict(c)
        for c in fusion_conflicts
    ]
    all_conflicts.extend(
        dict(c) for c in commercial.get("conflicts", [])
        if isinstance(c, dict)
    )
    graph = CanonicalIntelligence(
        project_namespace=project_namespace,
        entities=entities,
        facts=facts,
        conflicts=all_conflicts,
        metadata={
            "legacy_fields_are_compatibility_only": True,
            "commercial_flat_projection_is_compatibility_only": True,
            "payment_plan_intelligence_disabled_by_policy": True,
            "ambiguous_unit_scoped_commercial_facts_are_not_marketing_eligible": True,
        },
    )
    errors = graph.validate()
    if errors:
        raise ValueError("Cannot build canonical relational intelligence: " + "; ".join(errors))
    return graph
