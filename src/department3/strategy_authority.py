from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from src.project_sequence import contract, rank
from .authority import assert_can_create_approved_content_plan

_MODULE_ID = "src.department3.strategy_authority"


class StrategyAuthorityError(RuntimeError):
    pass


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceRef:
    fact_id: str
    source_id: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class StrategyDecision:
    project_id: str
    production_item_id: str
    objective: str
    audience: str
    proposition: str
    content_category: str
    format_intent: str
    approved_source_asset_ids: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    cta_intent: str | None = None
    story_sequence_role: str | None = None
    carousel_position: int | None = None
    restrictions: tuple[str, ...] = ()
    advisory_fingerprints: tuple[str, ...] = ()

    @property
    def decision_id(self) -> str:
        return "d3_" + _fingerprint(self.to_dict())[:20]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "production_item_id": self.production_item_id,
            "objective": self.objective,
            "audience": self.audience,
            "proposition": self.proposition,
            "content_category": self.content_category,
            "project_sequence": contract(self.content_category),
            "format_intent": self.format_intent,
            "approved_source_asset_ids": list(self.approved_source_asset_ids),
            "evidence": [
                {
                    "fact_id": e.fact_id,
                    "source_id": e.source_id,
                    "confidence": e.confidence,
                }
                for e in self.evidence
            ],
            "cta_intent": self.cta_intent,
            "story_sequence_role": self.story_sequence_role,
            "carousel_position": self.carousel_position,
            "restrictions": list(self.restrictions),
            "advisory_fingerprints": list(self.advisory_fingerprints),
        }


@dataclass(frozen=True)
class ApprovedContentPlan:
    project_id: str
    decisions: tuple[StrategyDecision, ...]
    plan_version: str = "d3.approved-content-plan.v1"
    authority_module: str = _MODULE_ID

    @property
    def plan_id(self) -> str:
        return "acp_" + _fingerprint(self.to_dict())[:20]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "authority_module": self.authority_module,
            "project_id": self.project_id,
            "decisions": [d.to_dict() | {"decision_id": d.decision_id} for d in self.decisions],
        }


class Department3StrategyAuthority:
    """The only canonical creator of Approved Content Plans.

    Advisory engines may propose, score, critique, or enrich candidates, but this class
    is the authority boundary that converts those inputs into an approved plan.
    """

    def __init__(self) -> None:
        assert_can_create_approved_content_plan(_MODULE_ID)

    def approve(
        self,
        *,
        project_id: str,
        candidates: Iterable[Mapping[str, Any]],
        advisory_inputs: Iterable[Mapping[str, Any]] = (),
    ) -> ApprovedContentPlan:
        if not project_id or not str(project_id).strip():
            raise StrategyAuthorityError("project_id is required")

        advisory_fps = tuple(sorted({_fingerprint(dict(x)) for x in advisory_inputs}))
        decisions: list[StrategyDecision] = []
        seen_items: set[str] = set()

        for raw in candidates:
            item = dict(raw)
            if str(item.get("project_id") or "") != str(project_id):
                raise StrategyAuthorityError("cross-project strategy candidate rejected")

            production_item_id = str(item.get("production_item_id") or "").strip()
            if not production_item_id:
                raise StrategyAuthorityError("production_item_id is required")
            if production_item_id in seen_items:
                raise StrategyAuthorityError(
                    f"duplicate production_item_id rejected: {production_item_id}"
                )
            seen_items.add(production_item_id)

            assets = tuple(
                str(x).strip()
                for x in item.get("approved_source_asset_ids", ())
                if str(x).strip()
            )
            if not assets:
                raise StrategyAuthorityError(
                    f"{production_item_id}: at least one approved source asset is required"
                )

            evidence_raw = item.get("evidence") or ()
            evidence: list[EvidenceRef] = []
            for e in evidence_raw:
                if not isinstance(e, Mapping):
                    raise StrategyAuthorityError(
                        f"{production_item_id}: evidence entries must be mappings"
                    )
                fact_id = str(e.get("fact_id") or "").strip()
                if not fact_id:
                    raise StrategyAuthorityError(
                        f"{production_item_id}: evidence fact_id is required"
                    )
                confidence = e.get("confidence")
                if confidence is not None:
                    confidence = float(confidence)
                    if confidence < 0 or confidence > 1:
                        raise StrategyAuthorityError(
                            f"{production_item_id}: confidence must be between 0 and 1"
                        )
                evidence.append(
                    EvidenceRef(
                        fact_id=fact_id,
                        source_id=(str(e.get("source_id")).strip() if e.get("source_id") else None),
                        confidence=confidence,
                    )
                )

            category = str(item.get("content_category") or "").strip()
            format_intent = str(item.get("format_intent") or "").strip().lower()
            objective = str(item.get("objective") or "").strip()
            audience = str(item.get("audience") or "").strip()
            proposition = str(item.get("proposition") or "").strip()

            if not all((category, format_intent, objective, audience, proposition)):
                raise StrategyAuthorityError(
                    f"{production_item_id}: objective, audience, proposition, "
                    "content_category and format_intent are required"
                )

            if format_intent not in {"feed", "carousel", "story"}:
                raise StrategyAuthorityError(
                    f"{production_item_id}: unsupported format_intent={format_intent!r}"
                )

            # Unit/floor-plan content must be evidence-bound.
            plan_like = any(
                token in category.casefold()
                for token in ("unit plan", "floor plan", "layout", "typical floor", "master floor")
            )
            if plan_like and not evidence:
                raise StrategyAuthorityError(
                    f"{production_item_id}: plan/layout content requires verified evidence"
                )

            decisions.append(
                StrategyDecision(
                    project_id=project_id,
                    production_item_id=production_item_id,
                    objective=objective,
                    audience=audience,
                    proposition=proposition,
                    content_category=category,
                    format_intent=format_intent,
                    approved_source_asset_ids=assets,
                    evidence=tuple(evidence),
                    cta_intent=(str(item.get("cta_intent")).strip() if item.get("cta_intent") else None),
                    story_sequence_role=(
                        str(item.get("story_sequence_role")).strip()
                        if item.get("story_sequence_role")
                        else None
                    ),
                    carousel_position=(
                        int(item["carousel_position"])
                        if item.get("carousel_position") is not None
                        else None
                    ),
                    restrictions=tuple(
                        str(x).strip()
                        for x in item.get("restrictions", ())
                        if str(x).strip()
                    ),
                    advisory_fingerprints=advisory_fps,
                )
            )

        if not decisions:
            raise StrategyAuthorityError("cannot approve an empty Department 3 plan")

        decisions.sort(key=lambda d: (rank(d.content_category), d.production_item_id))
        return ApprovedContentPlan(project_id=project_id, decisions=tuple(decisions))
