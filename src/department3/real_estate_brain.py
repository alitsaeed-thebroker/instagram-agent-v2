from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


class RealEstateStrategyError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrainConfig:
    location_priority: float = 1.0
    masterplan_priority: float = 0.95
    exterior_priority: float = 0.90
    interior_priority: float = 0.82
    amenity_priority: float = 0.84
    developer_priority: float = 0.30
    construction_priority: float = 0.30
    duplicate_penalty: float = 0.45
    fatigue_penalty: float = 0.30
    low_confidence_penalty: float = 0.40


@dataclass(frozen=True)
class StrategyCandidate:
    project_id: str
    production_item_id: str
    objective: str
    audience: str
    proposition: str
    content_category: str
    format_intent: str
    approved_source_asset_ids: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]
    cta_intent: str | None = None
    story_sequence_role: str | None = None
    carousel_position: int | None = None
    restrictions: tuple[str, ...] = ()
    score: float = 0.0
    decision_reasons: tuple[str, ...] = ()

    def to_authority_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "production_item_id": self.production_item_id,
            "objective": self.objective,
            "audience": self.audience,
            "proposition": self.proposition,
            "content_category": self.content_category,
            "format_intent": self.format_intent,
            "approved_source_asset_ids": list(self.approved_source_asset_ids),
            "evidence": [dict(x) for x in self.evidence],
            "cta_intent": self.cta_intent,
            "story_sequence_role": self.story_sequence_role,
            "carousel_position": self.carousel_position,
            "restrictions": list(self.restrictions),
        }


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _cf(value: Any) -> str:
    return _norm(value).casefold()


def _asset_category(asset: Mapping[str, Any]) -> str:
    raw = (
        asset.get("content_category")
        or asset.get("category")
        or asset.get("asset_type")
        or asset.get("classification")
        or ""
    )
    return _cf(raw)


def _priority_for_category(category: str, config: BrainConfig) -> float:
    c = category.casefold()
    if "location" in c or "map" in c:
        return config.location_priority
    if "masterplan" in c or "site plan" in c:
        return config.masterplan_priority
    if "exterior" in c or "facade" in c:
        return config.exterior_priority
    if "interior" in c:
        return config.interior_priority
    if "amenit" in c or "lifestyle" in c:
        return config.amenity_priority
    if "developer" in c:
        return config.developer_priority
    if "construction" in c or "progress" in c:
        return config.construction_priority
    if "unit plan" in c or "floor plan" in c or "layout" in c:
        return 0.78
    return 0.65


def _is_plan_like(category: str) -> bool:
    c = category.casefold()
    return any(x in c for x in (
        "unit plan", "floor plan", "layout", "typical floor", "master floor",
        "apartment plan", "office plan", "villa plan", "commercial-unit",
    ))


def _evidence(item: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    raw = item.get("evidence") or item.get("evidence_refs") or []
    if isinstance(raw, Mapping):
        raw = [raw]
    result = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        fact_id = entry.get("fact_id") or entry.get("id") or entry.get("fact")
        if not fact_id:
            continue
        out = {"fact_id": str(fact_id)}
        if entry.get("source_id"):
            out["source_id"] = str(entry["source_id"])
        if entry.get("confidence") is not None:
            out["confidence"] = float(entry["confidence"])
        result.append(out)
    return tuple(result)


def _mean_confidence(evidence: Sequence[Mapping[str, Any]]) -> float:
    values = []
    for e in evidence:
        if e.get("confidence") is not None:
            values.append(float(e["confidence"]))
    if not values:
        return 1.0
    return sum(values) / len(values)


def _audience_for(item: Mapping[str, Any], category: str) -> str:
    supplied = _norm(item.get("audience") or item.get("target_audience"))
    if supplied:
        return supplied
    c = category.casefold()
    if "office" in c or "commercial" in c:
        return "business owner or commercial investor"
    if "unit plan" in c or "floor plan" in c or "layout" in c:
        return "qualified buyer comparing unit suitability"
    if "location" in c or "map" in c:
        return "end-user buyer or investor evaluating accessibility"
    if "amenit" in c or "lifestyle" in c or "interior" in c:
        return "end-user buyer evaluating lifestyle and daily experience"
    return "qualified real-estate buyer"


def _objective_for(item: Mapping[str, Any], category: str) -> str:
    supplied = _norm(item.get("objective") or item.get("marketing_objective"))
    if supplied:
        return supplied
    c = category.casefold()
    if "location" in c or "map" in c:
        return "Communicate verified location and accessibility value"
    if "masterplan" in c or "site plan" in c:
        return "Explain project scale, organization, and spatial context"
    if "exterior" in c or "facade" in c:
        return "Build architectural desire and project recognition"
    if "interior" in c:
        return "Show the quality and experience of interior living or working space"
    if "amenit" in c or "lifestyle" in c:
        return "Demonstrate lifestyle utility and project experience"
    if _is_plan_like(c):
        return "Help a qualified buyer evaluate layout suitability using verified plan evidence"
    return "Communicate a verified project advantage"


def _proposition_for(item: Mapping[str, Any], category: str) -> str:
    supplied = _norm(
        item.get("proposition")
        or item.get("value_proposition")
        or item.get("angle")
        or item.get("message")
    )
    if supplied:
        return supplied

    visible = _norm(item.get("visible_summary") or item.get("visual_summary"))
    fact_summary = _norm(item.get("fact_summary") or item.get("verified_fact_summary"))
    if fact_summary:
        return fact_summary
    if visible:
        return visible

    c = category.casefold()
    if "location" in c or "map" in c:
        return "Verified location context that helps buyers understand access and positioning"
    if "masterplan" in c or "site plan" in c:
        return "Verified project layout and spatial organization"
    if "exterior" in c:
        return "The project's architecture and exterior identity"
    if "interior" in c:
        return "The interior environment and spatial experience"
    if "amenit" in c:
        return "The amenity experience supported by the source asset"
    if _is_plan_like(c):
        return "Verified unit or floor-plan information for suitability evaluation"
    return "A verified project feature supported by the source material"


def _format_for(item: Mapping[str, Any], category: str) -> str:
    supplied = _cf(item.get("format_intent") or item.get("format") or item.get("surface"))
    aliases = {
        "post": "feed",
        "single": "feed",
        "single_post": "feed",
        "stories": "story",
    }
    supplied = aliases.get(supplied, supplied)
    if supplied:
        if supplied not in {"feed", "carousel", "story"}:
            raise RealEstateStrategyError(f"unsupported format intent: {supplied!r}")
        return supplied

    asset_count = len(item.get("approved_source_asset_ids") or item.get("asset_ids") or [])
    c = category.casefold()
    if asset_count > 1 or "masterplan" in c or "site plan" in c:
        return "carousel"
    if "amenit" in c or "lifestyle" in c:
        return "story"
    return "feed"


def _cta_for(item: Mapping[str, Any], category: str) -> str:
    supplied = _norm(item.get("cta_intent") or item.get("cta"))
    if supplied:
        return supplied
    if _is_plan_like(category):
        return "Ask for the verified unit details and availability"
    if "location" in category.casefold():
        return "Ask for project location details or arrange a viewing"
    return "Contact the broker for verified availability and next steps"


def _restrictions_for(category: str, evidence: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    restrictions = [
        "Do not invent price, availability, ROI, completion date, payment plan, distance, or legal claims",
        "Use only verified project facts and authenticated source assets",
    ]
    if _is_plan_like(category):
        restrictions.extend([
            "Do not infer unit area, dimensions, unit type, or floor relationship",
            "Use plan/layout content only when authoritative relationships are verified",
        ])
    if not evidence:
        restrictions.append("Avoid factual overlay claims that are not visually self-evident")
    return tuple(restrictions)


class RealEstateStrategyBrain:
    """Evidence-safe real-estate strategy layer for canonical D3 candidate generation."""

    def __init__(self, config: BrainConfig | None = None):
        self.config = config or BrainConfig()

    def build_candidates(
        self,
        *,
        project_id: str,
        opportunities: Iterable[Mapping[str, Any]],
        recent_history: Iterable[Mapping[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        if not _norm(project_id):
            raise RealEstateStrategyError("project_id is required")

        history = list(recent_history)
        recent_categories = [_cf(x.get("content_category") or x.get("category")) for x in history]
        recent_assets = {
            str(a)
            for x in history
            for a in (x.get("approved_source_asset_ids") or x.get("asset_ids") or [])
        }

        built: list[StrategyCandidate] = []

        for idx, item in enumerate(opportunities, 1):
            item_project = _norm(item.get("project_id") or project_id)
            if item_project != project_id:
                raise RealEstateStrategyError("cross-project opportunity rejected")

            category = _asset_category(item)
            if not category:
                category = "project feature"

            assets_raw = item.get("approved_source_asset_ids") or item.get("asset_ids") or []
            if isinstance(assets_raw, str):
                assets_raw = [assets_raw]
            assets = tuple(str(x).strip() for x in assets_raw if str(x).strip())
            if not assets:
                raise RealEstateStrategyError("opportunity has no approved source assets")

            evidence = _evidence(item)
            if _is_plan_like(category) and not evidence:
                # Fail closed instead of creating unsupported layout marketing.
                continue

            production_item_id = _norm(
                item.get("production_item_id")
                or item.get("item_id")
                or item.get("id")
                or f"strategy-{idx:03d}"
            )

            priority = _priority_for_category(category, self.config)
            score = priority
            reasons = [f"category_priority={priority:.2f}"]

            if any(a in recent_assets for a in assets):
                score -= self.config.duplicate_penalty
                reasons.append("duplicate_asset_penalty")

            if category in recent_categories:
                score -= self.config.fatigue_penalty
                reasons.append("category_fatigue_penalty")

            confidence = _mean_confidence(evidence)
            if confidence < 0.75:
                score -= self.config.low_confidence_penalty
                reasons.append("low_confidence_penalty")

            if score <= 0:
                continue

            fmt = _format_for(item, category)
            story_role = None
            carousel_position = None
            if fmt == "story":
                story_role = _norm(item.get("story_sequence_role")) or (
                    "hook" if "location" in category or "exterior" in category else "proof"
                )
            if fmt == "carousel":
                carousel_position = int(item.get("carousel_position") or 1)

            candidate = StrategyCandidate(
                project_id=project_id,
                production_item_id=production_item_id,
                objective=_objective_for(item, category),
                audience=_audience_for(item, category),
                proposition=_proposition_for(item, category),
                content_category=category,
                format_intent=fmt,
                approved_source_asset_ids=assets,
                evidence=evidence,
                cta_intent=_cta_for(item, category),
                story_sequence_role=story_role,
                carousel_position=carousel_position,
                restrictions=_restrictions_for(category, evidence),
                score=round(score, 4),
                decision_reasons=tuple(reasons),
            )
            built.append(candidate)

        built.sort(key=lambda x: (-x.score, x.production_item_id))
        return [x.to_authority_dict() for x in built]
