"""Shared authority, freshness, and structured resolution primitives."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
import re
from typing import Any

from src.knowledge.document_classifier import DocumentType

AUTHORITY_POLICY_VERSION = "2.0.0"

_AUTHORITY = {
    DocumentType.PRICE_LIST: 90,
    DocumentType.PAYMENT_PLAN: 88,
    DocumentType.CONTRACT: 86,
    DocumentType.LEGAL_DOCUMENT: 85,
    DocumentType.SALES_OFFER: 75,
    DocumentType.TECHNICAL_SPECIFICATIONS: 70,
    DocumentType.INVESTMENT_DOCUMENT: 65,
    DocumentType.CATALOGUE: 60,
    DocumentType.CONSTRUCTION_UPDATE: 55,
    DocumentType.BROCHURE: 50,
    DocumentType.PRESENTATION: 45,
    DocumentType.MIXED_DOCUMENT: 40,
    DocumentType.PROJECT_NOTES: 30,
    DocumentType.UNKNOWN: 10,
}


@dataclass(frozen=True)
class FreshnessEvidence:
    effective_date: str | None = None
    revision: int | None = None
    basis: str = "unknown"
    raw_evidence: str | None = None

    @property
    def comparable(self) -> bool:
        return self.effective_date is not None or self.revision is not None

    def rank(self) -> tuple[str, int]:
        return self.effective_date or "", self.revision or -1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def source_authority(document_type: DocumentType, filename: str = "") -> int:
    """Authority depends on semantic source class, never filename freshness."""
    base = _AUTHORITY.get(document_type, 20)
    # Internal/ad-hoc notes remain lower authority even when misclassified.
    if filename.casefold().endswith(".txt") and document_type is not DocumentType.CONTRACT:
        base = min(base, 30)
    return max(0, base)


def explicit_freshness(filename: str, text: str) -> FreshnessEvidence:
    """Extract only explicit source freshness evidence.

    Arbitrary dates such as handover/completion dates are deliberately ignored.
    Filename dates are accepted only when the filename itself is clearly a
    dated/revisioned source artifact.
    """
    candidates: list[FreshnessEvidence] = []

    # Strong labels inside the document.
    labelled_patterns = (
        r"(?im)^\s*(?:effective\s+date|valid\s+from|issued\s+on|issue\s+date|price\s+list\s+date|as\s+of)\s*[:\-]\s*(?P<date>20\d{2}[-_/](?:0?[1-9]|1[0-2])[-_/](?:0?[1-9]|[12]\d|3[01]))\s*$",
        r"(?im)^\s*(?:effective\s+date|valid\s+from|issued\s+on|issue\s+date|price\s+list\s+date|as\s+of)\s*[:\-]\s*(?P<date>(?:0?[1-9]|[12]\d|3[01])[-_/](?:0?[1-9]|1[0-2])[-_/]20\d{2})\s*$",
    )
    for pattern in labelled_patterns:
        for match in re.finditer(pattern, text):
            parsed = _iso_date(match.group("date"))
            if parsed:
                candidates.append(FreshnessEvidence(parsed, None, "explicit_document_date", match.group(0).strip()))

    revision_matches = list(re.finditer(
        r"(?im)^\s*(?:revision|rev|version)\s*[:\-]?\s*(?:v|r)?(?P<rev>\d{1,3})\s*$",
        text,
    ))
    revisions = {int(m.group("rev")) for m in revision_matches}
    if len(revisions) == 1:
        raw = revision_matches[-1].group(0).strip()
        candidates.append(FreshnessEvidence(None, next(iter(revisions)), "explicit_document_revision", raw))

    # Filename evidence is allowed only with date/revision tokens and an
    # artifact-like name. It never changes authority, only freshness.
    filename_date = re.search(
        r"(?i)(?:^|[_\-\s])(?P<date>20\d{2}[-_](?:0?[1-9]|1[0-2])[-_](?:0?[1-9]|[12]\d|3[01]))(?:[_\-\s.]|$)",
        filename,
    )
    if filename_date:
        parsed = _iso_date(filename_date.group("date"))
        if parsed:
            candidates.append(FreshnessEvidence(parsed, None, "explicit_filename_date", filename_date.group(0).strip()))

    filename_rev = re.search(r"(?i)(?:^|[_\-\s])(?:rev|revision|v)(?P<rev>\d{1,3})(?:[_\-\s.]|$)", filename)
    if filename_rev:
        candidates.append(FreshnessEvidence(None, int(filename_rev.group("rev")), "explicit_filename_revision", filename_rev.group(0).strip()))

    dated = [c for c in candidates if c.effective_date]
    revised = [c for c in candidates if c.revision is not None]
    best_date = max(dated, key=lambda x: x.effective_date or "") if dated else None
    best_rev = max(revised, key=lambda x: x.revision or -1) if revised else None
    if best_date and best_rev:
        return FreshnessEvidence(
            best_date.effective_date,
            best_rev.revision,
            f"{best_date.basis}+{best_rev.basis}",
            f"{best_date.raw_evidence}; {best_rev.raw_evidence}",
        )
    return best_date or best_rev or FreshnessEvidence()


def compare_candidates(
    left: dict[str, Any],
    right: dict[str, Any],
) -> tuple[int, str]:
    """Compare two candidates.

    Returns (1, reason) if left wins, (-1, reason) if right wins, and
    (0, reason) when the conflict must remain unresolved.
    """
    la, ra = int(left.get("authority", 0)), int(right.get("authority", 0))
    if la != ra:
        return (1 if la > ra else -1), "higher_source_authority"

    lf = _candidate_freshness(left)
    rf = _candidate_freshness(right)
    if lf.comparable and rf.comparable and lf.rank() != rf.rank():
        return (1 if lf.rank() > rf.rank() else -1), "newer_explicit_freshness"

    # A dated candidate does not automatically beat an undated candidate.
    # That would manufacture freshness ordering without comparable evidence.
    return 0, "equal_authority_without_comparable_explicit_freshness"


def structured_resolution(
    *,
    fact_key: Any,
    candidates: list[dict[str, Any]],
    selected: dict[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    selected_id = selected.get("candidate_id") if selected else None
    supersession = []
    if selected is not None and reason == "newer_explicit_freshness":
        supersession = [
            {
                "superseded_candidate_id": candidate.get("candidate_id"),
                "superseded_by_candidate_id": selected_id,
                "basis": reason,
            }
            for candidate in candidates
            if candidate.get("candidate_id") != selected_id
        ]
    return {
        "resolution_version": AUTHORITY_POLICY_VERSION,
        "fact_key": list(fact_key) if isinstance(fact_key, tuple) else fact_key,
        "fact_type": candidates[0].get("fact_type") if candidates else None,
        "status": "RESOLVED" if selected is not None else "CONFLICTING",
        "selected_candidate_id": selected_id,
        "selected_value": _candidate_value(selected) if selected else None,
        "resolution_reason": reason,
        "candidates": candidates,
        "supersession": supersession,
    }


def candidate_id(*parts: Any) -> str:
    import hashlib
    raw = "|".join(str(x or "") for x in parts)
    return "cand_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:18]


def _candidate_freshness(candidate: dict[str, Any]) -> FreshnessEvidence:
    value = candidate.get("freshness")
    if isinstance(value, dict):
        return FreshnessEvidence(
            effective_date=value.get("effective_date"),
            revision=value.get("revision"),
            basis=str(value.get("basis") or "unknown"),
            raw_evidence=value.get("raw_evidence"),
        )
    evidence = (candidate.get("evidence") or [{}])[0]
    return FreshnessEvidence(
        effective_date=evidence.get("effective_date") or evidence.get("document_date"),
        revision=evidence.get("document_revision_number"),
        basis=str(evidence.get("freshness_basis") or "unknown"),
        raw_evidence=evidence.get("freshness_evidence"),
    )


def _candidate_value(candidate: dict[str, Any] | None) -> Any:
    if not candidate:
        return None
    if "value" in candidate:
        return candidate.get("value")
    if "percentage" in candidate:
        return candidate.get("percentage")
    if "minimum" in candidate or "maximum" in candidate:
        return {"minimum": candidate.get("minimum"), "maximum": candidate.get("maximum")}
    return None


def _iso_date(raw: str) -> str | None:
    raw = raw.strip()
    for pattern, order in (
        (r"^(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})$", "ymd"),
        (r"^(\d{1,2})[-_/](\d{1,2})[-_/](20\d{2})$", "dmy"),
    ):
        match = re.match(pattern, raw)
        if not match:
            continue
        try:
            if order == "ymd":
                y, m, d = map(int, match.groups())
            else:
                d, m, y = map(int, match.groups())
            return date(y, m, d).isoformat()
        except ValueError:
            return None
    return None
