"""Deterministic, source-grounded commercial real-estate intelligence.

This module is the authority for the three approved commercial price facts:
price per square meter, unit total price, and unit starting price. It never
calculates missing commercial values and never models payment schedules.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from src.knowledge.document_classifier import DocumentType
from src.knowledge.authority import (
    candidate_id,
    compare_candidates,
    explicit_freshness,
    source_authority as policy_source_authority,
    structured_resolution,
)

SCHEMA_VERSION = "1.0.0"
COMMERCIAL_FACT_TYPES = frozenset({
    "price_per_sqm",
    "total_unit_price",
    "starting_price",
})

# Department 2 intentionally does NOT model payment plans, installments,
# booking schedules, discounts, fees, promotions, financing terms, ROI, or
# other commercial terms. Only the three price facts above are authoritative.
PAYMENT_FACT_TYPES = frozenset()
UNIT_SCOPED_FACT_TYPES = frozenset({
    "total_unit_price",
    "starting_price",
})
RELATIONSHIP_DIMENSIONS = (
    "building", "tower", "unit_id", "unit_type", "bedrooms",
    "floor", "area_sqm",
)

_CURRENCY = r"(?P<currency>US\$|USD|IQD|AED|EUR|\$)"
_NUMBER = r"(?P<value>\d[\d,]*(?:\.\d+)?)"
_AMOUNT = rf"(?:{_CURRENCY}\s*{_NUMBER}|(?P<value_after>\d[\d,]*(?:\.\d+)?)\s*(?P<currency_after>USD|IQD|AED|EUR))"


def extract_document_intelligence(
    text: str, *, project: str, source_file: str, document_type: DocumentType,
    classification_confidence: float = 1.0, extraction_method: str = "deterministic_text",
    source_id: str | None = None, source_sha256: str | None = None,
) -> dict[str, Any]:
    """Extract explicitly typed facts from provenance-bearing source text."""
    freshness = explicit_freshness(source_file, text)
    version = f"V{freshness.revision:02d}" if freshness.revision is not None else None
    date = freshness.effective_date
    facts: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    for block in _source_blocks(text):
        body = block["text"]
        if str(block.get("structure_status") or "regular").casefold() != "regular":
            continue
        if str(block.get("block_type") or "").casefold() in {"table_header", "table_repeated_header"}:
            continue
        evidence = {
            "source_file": source_file, "source_project": project,
            "document_type": document_type.value, "page": block.get("page"),
            "line_range": block.get("line_range"), "paragraph": block.get("paragraph"),
            "table_index": block.get("table_index"), "row_index": block.get("row_index"),
            "block_type": block.get("block_type"), "structure_status": block.get("structure_status", "regular"),
            "structure_warnings": block.get("structure_warnings"),
            "source_text": body.strip(), "extraction_method": extraction_method,
            "source_id": source_id, "source_sha256": source_sha256,
            "document_version": version, "document_date": date,
            "effective_date": freshness.effective_date,
            "document_revision_number": freshness.revision,
            "freshness_basis": freshness.basis,
            "freshness_evidence": freshness.raw_evidence,
        }
        extracted = _extract_block(body, evidence, classification_confidence)
        facts.extend(_apply_relationship_safety(fact) for fact in extracted)
        if re.search(r"\b(?:prime investment|excellent roi|guaranteed return|best investment)\b", body, re.I):
            claims.append({**evidence, "claim_type": "marketing_claim", "status": "supported"})
    return {
        "schema_version": SCHEMA_VERSION, "contract_role": "intermediate_document_evidence",
        "project": project, "source_file": source_file, "document_type": document_type.value,
        "document_version": version, "document_date": date,
        "authority": source_authority(document_type, source_file, date),
        "freshness": freshness.to_dict(),
        "facts": _dedupe_document_facts(facts), "marketing_claims": claims,
    }


def resolve_project_intelligence(documents: Iterable[dict[str, Any]], project: str) -> dict[str, Any]:
    """Resolve document evidence into the one authoritative commercial contract."""
    docs = [d for d in documents if d and d.get("project") == project]
    candidates = []
    for doc in docs:
        for fact in doc.get("facts", []):
            if fact.get("source_project") != project:
                continue
            if fact.get("fact_type") not in COMMERCIAL_FACT_TYPES:
                continue
            item = dict(
                fact,
                authority=int(doc.get("authority", 0)),
                freshness=dict(doc.get("freshness") or {}),
            )
            item["candidate_id"] = candidate_id(
                project, doc.get("source_file"), fact.get("fact_type"),
                _resolution_key(fact), _value_key(fact),
            )
            candidates.append(item)
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for fact in candidates:
        grouped.setdefault(_resolution_key(fact), []).append(fact)
    canonical: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for key, group in grouped.items():
        values: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for fact in group:
            values.setdefault(_value_key(fact), []).append(fact)
        merged = [_merge_same_value(items) for items in values.values()]
        if len(merged) == 1:
            canonical.append(merged[0]); continue
        ranked = sorted(merged, key=lambda x: (int(x.get("authority", 0)), x.get("candidate_id", "")), reverse=True)
        selected, reason = _select_candidate(ranked)
        if selected is not None:
            canonical.append(dict(selected))
        conflicts.append(structured_resolution(
            fact_key=key,
            candidates=ranked,
            selected=selected,
            reason=reason,
        ))
    # Payment plans/installments are intentionally outside Department 2 scope.
    payment_facts: list[dict[str, Any]] = []
    payment_plans: list[dict[str, Any]] = []
    payment_plan = {
        "status": "not_supported",
        "installments": [],
        "percentage_total": None,
        "reason": "payment_plan_intelligence_disabled_by_policy",
    }
    warnings = _validation_warnings(canonical, payment_plan)
    relationship_diagnostics = _relationship_diagnostics(candidates, canonical, conflicts, payment_plans)
    warnings.extend(x for x in relationship_diagnostics["warnings"] if x not in warnings)
    statuses = [f["status"] for f in canonical]
    pricing_facts = [
        f for f in canonical
        if f.get("fact_type") in COMMERCIAL_FACT_TYPES
    ]
    pricing_groups = _pricing_relationship_groups(pricing_facts)
    return {
        "schema_version": SCHEMA_VERSION, "contract_role": "authoritative_project_intelligence",
        "project": project,
        "pricing": {
            "status": _availability(pricing_facts, conflicts, relationship_diagnostics),
            "facts": pricing_facts,
            "relationship_groups": pricing_groups,
        },
        "payment_plan": payment_plan,
        "payment_plans": payment_plans,
        "commercial_terms": [],
        "conflicts": conflicts, "unsupported_claims": [],
        "marketing_claims": [c for d in docs for c in d.get("marketing_claims", [])],
        "sources": [{
            **{k: d.get(k) for k in ("source_file", "document_type", "document_version", "document_date", "authority")},
            "freshness": d.get("freshness", {}),
        } for d in docs],
        "warnings": warnings,
        "relationship_diagnostics": relationship_diagnostics,
        "audit": {
            "verified": statuses.count("verified"), "conflicting": len(conflicts),
            "supported": statuses.count("supported"),
            "unsupported": 0, "source_conflicts": len(conflicts), "warnings": warnings,
        },
    }


def verified_fact(fact: dict[str, Any], project: str) -> bool:
    """Hard gate for downstream-usable commercial facts."""
    return bool(
        fact.get("fact_type") in COMMERCIAL_FACT_TYPES
        and fact.get("status") == "verified"
        and fact.get("relationship_status") != "ambiguous"
        and fact.get("source_project") == project
        and fact.get("evidence")
        and all(
            e.get("source_file")
            and e.get("source_text")
            and e.get("evidence_id")
            and e.get("extraction_method")
            for e in fact["evidence"]
        )
    )


def source_authority(document_type: DocumentType, filename: str, date: str | None = None) -> int:
    """Compatibility wrapper; date never changes semantic source authority."""
    del date
    return policy_source_authority(document_type, filename)


def document_version(filename: str) -> str | None:
    freshness = explicit_freshness(filename, "")
    return f"V{freshness.revision:02d}" if freshness.revision is not None else None


def document_date(filename: str, text: str) -> str | None:
    """Compatibility wrapper returning only explicit freshness dates."""
    return explicit_freshness(filename, text).effective_date


def _extract_block(text: str, evidence: dict[str, Any], confidence: float) -> list[dict[str, Any]]:
    """Extract only the three approved price facts.

    Explicitly ignored even when present in source text:
    payment plans, installments, down payments, booking/reservation fees,
    discounts, taxes, service charges, financing terms, promotions, ROI,
    rental yield, guarantees, and all other commercial claims.
    """
    patterns = [
        (
            "price_per_sqm",
            rf"{_AMOUNT}\s*(?:/|per\s*)(?:m2|m²|sqm|square\s*met(?:er|re)s?)\b",
            "per_sqm",
        ),
        (
            "price_per_sqm",
            rf"price\s+per\s+(?:m2|m²|sqm|square\s*met(?:er|re)s?)\s*[:\-]?\s*{_AMOUNT}",
            "per_sqm",
        ),
        (
            "starting_price",
            rf"(?:unit\s+)?(?:starting\s+price|starting\s+from|prices?\s+from)\s*[:\-]?\s*{_AMOUNT}",
            "starting_from",
        ),
        (
            "total_unit_price",
            rf"(?:total\s+(?:unit\s+)?price|unit\s+total\s+price|unit\s+price)\s*[:\-]?\s*{_AMOUNT}",
            "exact",
        ),
    ]
    facts: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for fact_type, pattern, qualifier in patterns:
        for match in re.finditer(pattern, text, re.I):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            if _non_authoritative_price_context(text, match.start(), match.end()):
                continue
            occupied.append(match.span())
            data: dict[str, Any] = {
                "fact_type": fact_type,
                "qualifier": qualifier,
                "value": _number(
                    match.groupdict().get("value")
                    or match.groupdict().get("value_after")
                ),
                "currency": _currency(
                    match.groupdict().get("currency")
                    or match.groupdict().get("currency_after")
                ),
                "relationship_context": _relationship_context(
                    text, match.start(), match.end()
                ),
            }
            facts.append(_fact(data, evidence, confidence, match.group(0)))
    return facts


def _non_authoritative_price_context(text: str, start: int, end: int) -> bool:
    """Reject examples, placeholders, negations, and instruction-like price text."""
    left = max(
        text.rfind("\n", 0, start),
        text.rfind(".", 0, start),
        text.rfind(";", 0, start),
    ) + 1
    rights = [x for x in (text.find("\n", end), text.find(".", end), text.find(";", end)) if x != -1]
    right = min(rights) if rights else len(text)
    window = re.sub(r"\s+", " ", text[left:right]).strip().casefold()
    blockers = (
        r"\bexample\b", r"\bsample\b", r"\bplaceholder\b", r"\billustrative\b",
        r"\bhypothetical\b", r"\bdummy\b", r"\btest\s+data\b", r"\bdraft\s+only\b",
        r"\bnot\s+(?:actual|final|official|valid)\b", r"\bdo\s+not\s+(?:use|publish|claim)\b",
        r"\bignore\s+(?:this|the)\b", r"\b(?:invent|fabricate|assume|create|generate)\b",
        r"\bfake\b", r"\bfor\s+testing\s+only\b",
    )
    return any(re.search(pattern, window, re.I) for pattern in blockers)


def _fact(data: dict[str, Any], evidence: dict[str, Any], confidence: float, source_text: str) -> dict[str, Any]:
    import hashlib
    locator = evidence.get("page") or evidence.get("line_range") or evidence.get("paragraph")
    evidence_id = "ev_" + hashlib.sha256(
        "|".join(str(x or "") for x in (
            evidence.get("source_project"), evidence.get("source_file"),
            evidence.get("source_id"), data.get("fact_type"), source_text, locator,
        )).encode("utf-8")
    ).hexdigest()[:20]
    ev = dict(
        evidence,
        evidence_id=evidence_id,
        fact_value=data.get("value", data.get("percentage", data.get("minimum"))),
        source_block_text=evidence.get("source_text"),
        source_text=source_text.strip(),
        support_status="direct",
        status="supported",
        evidence_origin="department1_source_evidence",
    )
    low_authority = evidence.get("document_type") in {DocumentType.UNKNOWN.value, DocumentType.PROJECT_NOTES.value}
    status = "supported" if low_authority or confidence < .7 else "verified"
    return {
        **data,
        "status": status,
        "confidence": round(min(.99, max(.0, confidence)), 2),
        "source_project": evidence["source_project"],
        "evidence": [ev],
        "occurrence_count": 1,
    }


def _source_blocks(text: str) -> list[dict[str, Any]]:
    heading = re.compile(
        r"(?m)^## (?:(?:Page (?P<page>\d+))|(?:Lines (?P<line_start>\d+)-(?P<line_end>\d+))|(?:Paragraph (?P<paragraph>\d+))|Evidence)\s*$"
    )
    matches = list(heading.finditer(text))
    if matches:
        result = []
        for i, match in enumerate(matches):
            body = text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
            if not body:
                continue
            line_range = None
            if match.group("line_start"):
                line_range = (
                    match.group("line_start")
                    if match.group("line_start") == match.group("line_end")
                    else f"{match.group('line_start')}-{match.group('line_end')}"
                )
            result.append({
                "page": int(match.group("page")) if match.group("page") else None,
                "line_range": line_range,
                "paragraph": int(match.group("paragraph")) if match.group("paragraph") else None,
                "table_index": None,
                "row_index": None,
                "block_type": "page_or_text",
                "structure_status": "regular",
                "text": body,
            })
        return result

    blocks = list(re.finditer(r"(?m)^## Source block \d+\s*$", text))
    if blocks:
        result=[]
        for i,m in enumerate(blocks):
            body=text[m.end():blocks[i+1].start() if i+1<len(blocks) else len(text)]
            metadata={}
            content=[]
            in_metadata=True
            for raw in body.splitlines():
                line=raw.strip()
                if in_metadata and line.startswith("- ") and ":" in line:
                    key,value=line[2:].split(":",1)
                    metadata[key.strip().casefold()]=value.strip()
                    continue
                if line:
                    in_metadata=False
                    content.append(raw)
            location=metadata.get("document location","")
            line_range=paragraph=table_index=row_index=None
            if mloc:=re.fullmatch(r"lines? ([\d-]+)",location,re.I):
                line_range=mloc.group(1)
            elif mloc:=re.fullmatch(r"paragraph (\d+)",location,re.I):
                paragraph=int(mloc.group(1))
            elif mloc:=re.fullmatch(r"table (\d+) row (\d+)",location,re.I):
                table_index,row_index=int(mloc.group(1)),int(mloc.group(2))
            result.append({
                "line_range":line_range,
                "paragraph":paragraph,
                "table_index":table_index,
                "row_index":row_index,
                "block_type":metadata.get("block type","text"),
                "structure_status":metadata.get("structure status","regular"),
                "structure_warnings":metadata.get("structure warnings"),
                "text":"\n".join(content).strip(),
            })
        return [x for x in result if x["text"]]
    return [{"text": text, "block_type":"text", "structure_status":"regular"}]


def _relationship_context(text: str, start: int, end: int) -> dict[str, Any]:
    """Extract only explicit nearby relationship anchors.

    This intentionally prefers missing context over guessed joins. The local
    window prevents a price on one row/section from inheriting identifiers from
    a distant unit.
    """
    # Prefer the containing sentence/row. Relationship anchors from adjacent
    # rows are more dangerous than missing context.
    left_candidates = [text.rfind("\n", 0, start), text.rfind(".", 0, start), text.rfind(";", 0, start)]
    right_candidates = [x for x in (text.find("\n", end), text.find(".", end), text.find(";", end)) if x != -1]
    left = max(left_candidates) + 1
    right = min(right_candidates) if right_candidates else len(text)
    window = text[left:right]
    context: dict[str, Any] = {}

    def one(pattern: str, group: str = "value") -> str | None:
        matches = list(re.finditer(pattern, window, re.I))
        values = {_clean_context(m.group(group)) for m in matches if m.groupdict().get(group)}
        return next(iter(values)) if len(values) == 1 else None

    building = one(r"\bbuilding\s*[:#-]?\s*(?P<value>[A-Z0-9][A-Z0-9 _-]{0,20})")
    tower = one(r"\btower\s*[:#-]?\s*(?P<value>[A-Z0-9][A-Z0-9 _-]{0,20})")
    unit_id = one(r"\b(?:unit|apartment|office|villa)\s*(?:no\.?|number|#|id)?\s*[:#-]?\s*(?P<value>[A-Z]?\d[A-Z0-9-]{0,12})\b")
    unit_type = one(r"\b(?P<value>studio|apartment|office|villa|retail|shop|commercial(?:\s+unit)?)\b")
    bedrooms = one(r"\b(?P<value>\d+)\s*(?:bed(?:room)?s?|br)\b")
    floor = one(r"\b(?:floor|level)\s*[:#-]?\s*(?P<value>\d{1,3})\b")
    area = one(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?:m2|m²|sqm|square\s*met(?:er|re)s?)\b")
    for key, value in (
        ("building", building), ("tower", tower), ("unit_id", unit_id),
        ("unit_type", unit_type), ("bedrooms", bedrooms), ("floor", floor),
        ("area_sqm", area),
    ):
        if value is None:
            continue
        if key in {"bedrooms", "floor"}:
            context[key] = int(value)
        elif key == "area_sqm":
            context[key] = float(value)
        else:
            context[key] = value
    return context


def _clean_context(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" :-#")


def _dedupe_document_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[tuple[Any, ...], dict[str, Any]] = {}
    for fact in facts:
        key = (*_resolution_key(fact), *_value_key(fact))
        if key in result:
            result[key]["evidence"].extend(fact["evidence"])
            result[key]["occurrence_count"] = int(result[key].get("occurrence_count", 1)) + int(fact.get("occurrence_count", 1))
        else:
            result[key] = fact
    return list(result.values())


def _resolution_key(f: dict[str, Any]) -> tuple[Any, ...]:
    context = f.get("relationship_context") or {}
    return (
        f.get("fact_type"), f.get("currency"), f.get("unit"),
        f.get("sequence"), f.get("trigger"),
        context.get("building"), context.get("tower"), context.get("unit_id"),
        context.get("unit_type"), context.get("bedrooms"), context.get("floor"),
        context.get("area_sqm"),
    )


def _value_key(f: dict[str, Any]) -> tuple[Any, ...]:
    return f.get("value"), f.get("minimum"), f.get("maximum"), f.get("percentage"), f.get("milestone")


def _merge_same_value(items: list[dict[str, Any]]) -> dict[str, Any]:
    best = max(items, key=lambda x: (int(x.get("authority", 0)), str(x.get("candidate_id", ""))))
    merged = dict(best)
    merged["evidence"] = [e for item in items for e in item.get("evidence", [])]
    merged["confidence"] = max(float(x.get("confidence", 0)) for x in items)
    merged["occurrence_count"] = sum(int(x.get("occurrence_count", 1)) for x in items)
    return merged


def _select_candidate(candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """Resolve only when authority or comparable explicit freshness is decisive."""
    if not candidates:
        return None, "no_candidates"
    winner = candidates[0]
    reason = "single_candidate"
    for challenger in candidates[1:]:
        comparison, comparison_reason = compare_candidates(winner, challenger)
        if comparison == 0:
            return None, comparison_reason
        if comparison < 0:
            winner = challenger
        reason = comparison_reason
    return winner, reason




def _stable_commercial_id(prefix: str, value: Any) -> str:
    import hashlib, json
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _commercial_scope(fact: dict[str, Any]) -> dict[str, Any]:
    context = fact.get("relationship_context") or {}
    return {key: context.get(key) for key in RELATIONSHIP_DIMENSIONS if context.get(key) not in (None, "")}


def _apply_relationship_safety(fact: dict[str, Any]) -> dict[str, Any]:
    item = dict(fact)
    scope = _commercial_scope(item)
    fact_type = str(item.get("fact_type") or "")
    if fact_type in UNIT_SCOPED_FACT_TYPES:
        has_unit_anchor = any(
            scope.get(key) not in (None, "")
            for key in ("unit_id", "unit_type", "building", "tower", "area_sqm")
        )
        item["relationship_status"] = "scoped" if has_unit_anchor else "ambiguous"
    else:
        item["relationship_status"] = "scoped" if scope else "project_scope"
    item["relationship_key"] = _stable_commercial_id(
        "scope", scope or {"project_scope": True}
    )
    return item


def _relationship_diagnostics(
    candidates: list[dict[str, Any]],
    canonical: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    payment_plans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    del canonical, payment_plans
    warnings: list[str] = []
    ambiguous = [f for f in candidates if f.get("relationship_status") == "ambiguous"]
    if ambiguous:
        warnings.append("ambiguous_unit_scoped_commercial_fact")
    unresolved = [c for c in conflicts if str(c.get("status")).casefold() == "conflicting"]
    return {
        "ambiguous_fact_count": len(ambiguous),
        "ambiguous_candidate_ids": [f.get("candidate_id") for f in ambiguous if f.get("candidate_id")],
        "unresolved_conflict_count": len(unresolved),
        "warnings": warnings,
    }


def _pricing_relationship_groups(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for fact in facts:
        key = str(fact.get("relationship_key") or _stable_commercial_id(
            "scope", _commercial_scope(fact) or {"project_scope": True}
        ))
        group = groups.setdefault(key, {
            "relationship_key": key,
            "relationship_context": _commercial_scope(fact),
            "currencies": set(),
            "fact_types": set(),
            "fact_ids": [],
        })
        if fact.get("currency"):
            group["currencies"].add(fact["currency"])
        group["fact_types"].add(fact.get("fact_type"))
        if fact.get("candidate_id"):
            group["fact_ids"].append(fact["candidate_id"])
    result = []
    for group in groups.values():
        result.append({
            **group,
            "currencies": sorted(group["currencies"]),
            "fact_types": sorted(x for x in group["fact_types"] if x),
            "currency_mode": "single" if len(group["currencies"]) <= 1 else "multi_currency_explicit",
        })
    return sorted(result, key=lambda x: x["relationship_key"])



def _validation_warnings(
    facts: list[dict[str, Any]],
    plan: dict[str, Any] | None = None,
) -> list[str]:
    """Validate only price relationships; payment schedule checks are disabled."""
    del plan
    warnings: list[str] = []
    totals = [f for f in facts if f.get("fact_type") == "total_unit_price"]
    rates = [f for f in facts if f.get("fact_type") == "price_per_sqm"]
    for total in totals:
        for rate in rates:
            if _commercial_scope(total) != _commercial_scope(rate):
                continue
            texts = [
                str(e.get("source_block_text") or "")
                for e in [*total.get("evidence", []), *rate.get("evidence", [])]
            ]
            area = next(
                (
                    float(m.group(1))
                    for text in texts
                    if (m := re.search(
                        r"(\d+(?:\.\d+)?)\s*(?:m2|m²|sqm)\b",
                        text,
                        re.I,
                    ))
                ),
                None,
            )
            if (
                area
                and total.get("currency") == rate.get("currency")
                and abs(
                    area * float(rate["value"]) - float(total["value"])
                ) > max(1, float(total["value"]) * .001)
            ):
                warnings.append("calculated_total_mismatch")
                break
    return warnings


def _availability(
    facts: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    diagnostics: dict[str, Any] | None = None,
) -> str:
    if any(
        str(c.get("status")).casefold() == "conflicting"
        and c.get("fact_type") in COMMERCIAL_FACT_TYPES
        for c in conflicts
    ):
        return "conflicting"
    if diagnostics and diagnostics.get("ambiguous_fact_count"):
        if any(f.get("fact_type") in UNIT_SCOPED_FACT_TYPES for f in facts):
            return "uncertain"
    if not facts:
        return "unavailable"
    return "complete" if all(
        f.get("status") == "verified" and f.get("relationship_status") != "ambiguous"
        for f in facts
    ) else "uncertain"


def _number(value: str | None) -> float | None:
    if not value: return None
    number=float(value.replace(",", "")); return int(number) if number.is_integer() else number


def _currency(value: str | None) -> str | None:
    if not value: return None
    return "USD" if value.upper() in {"$", "US$", "USD"} else value.upper()


def _sequence(value: str | None) -> int | None:
    if not value:return None
    words={"first":1,"second":2,"third":3,"fourth":4}
    return words.get(value.casefold()) or int(re.match(r"\d+",value).group())
