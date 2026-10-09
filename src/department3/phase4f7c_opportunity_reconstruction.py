from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class CanonicalOpportunityReconstructionError(RuntimeError):
    pass


CAROUSEL_CATEGORIES = {
    "masterplan",
    "exterior",
    "interior",
    "commercial",
}

STORY_CATEGORIES = {
    "location",
    "amenity",
}

PLAN_TOKENS = (
    "unit layout",
    "unit plan",
    "floor plan",
    "typical floor",
    "master floor",
    "apartment plan",
    "office plan",
    "villa plan",
)

ALLOWED_FORMATS = {"feed", "carousel", "story"}


def _norm(value: Any) -> str:
    return (
        str(value or "")
        .casefold()
        .replace("\\", "/")
        .replace("-", " ")
        .replace("_", " ")
        .strip()
    )


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CanonicalOpportunityReconstructionError(
            f"cannot read asset intelligence: {path}: {exc}"
        ) from exc

    if not isinstance(value, Mapping):
        raise CanonicalOpportunityReconstructionError(
            f"asset intelligence must be a JSON object: {path}"
        )

    return value


def _is_plan_like(category: str) -> bool:
    low = _norm(category)
    return any(token in low for token in PLAN_TOKENS)


def _asset_paths(asset: Mapping[str, Any]) -> list[str]:
    raw = asset.get("paths") or []
    if isinstance(raw, str):
        raw = [raw]

    result = []
    if isinstance(raw, Sequence):
        for value in raw:
            if str(value).strip():
                result.append(str(value))
    return result


def _evidence(asset: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = asset.get("evidence") or []
    if isinstance(raw, Mapping):
        raw = [raw]

    result = []
    seen = set()

    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        for value in raw:
            if isinstance(value, str):
                rec = {"fact_id": value}
            elif isinstance(value, Mapping):
                fact_id = (
                    value.get("fact_id")
                    or value.get("knowledge_fact_id")
                    or value.get("claim_id")
                    or value.get("id")
                    or value.get("fact")
                )
                if not fact_id:
                    continue

                rec = {"fact_id": str(fact_id)}

                source_id = (
                    value.get("source_id")
                    or value.get("source")
                    or value.get("document_id")
                )
                confidence = value.get("confidence")

                if source_id:
                    rec["source_id"] = str(source_id)

                if confidence is not None:
                    try:
                        rec["confidence"] = float(confidence)
                    except Exception:
                        pass
            else:
                continue

            key = (
                rec.get("fact_id"),
                rec.get("source_id"),
                rec.get("confidence"),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(rec)

    return result


def _plan_relationships(asset: Mapping[str, Any]) -> list[Any]:
    raw = asset.get("plan_relationships") or []

    if isinstance(raw, Mapping):
        return [dict(raw)]

    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return list(raw)

    return []


def _category(asset: Mapping[str, Any]) -> str:
    value = asset.get("category")
    if value:
        return str(value).strip()
    return "project feature"


def _asset_id(asset: Mapping[str, Any], fallback: str) -> str:
    value = asset.get("asset_id")
    return str(value).strip() if value else fallback


def _asset_reference(asset: Mapping[str, Any], fallback: str) -> str:
    paths = _asset_paths(asset)
    if paths:
        return paths[0]
    return _asset_id(asset, fallback)


def _merge_evidence(assets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()

    for asset in assets:
        for ev in _evidence(asset):
            key = (
                ev.get("fact_id"),
                ev.get("source_id"),
                ev.get("confidence"),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(ev)

    return out


def _make_feed(
    project: str,
    asset: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    category = _category(asset)
    return {
        "project_id": project,
        "id": f"feed-{index:03d}",
        "category": category,
        "asset_ids": [_asset_reference(asset, f"asset-{index:03d}")],
        "evidence": _evidence(asset),
        "visible_summary": str(
            asset.get("visible_summary")
            or category
        ),
        "format_intent": "feed",
        "restrictions": [],
    }


def _make_story(
    project: str,
    asset: Mapping[str, Any],
    index: int,
    role: str,
) -> dict[str, Any]:
    category = _category(asset)
    return {
        "project_id": project,
        "id": f"story-{index:03d}",
        "category": category,
        "asset_ids": [_asset_reference(asset, f"asset-{index:03d}")],
        "evidence": _evidence(asset),
        "visible_summary": str(
            asset.get("visible_summary")
            or category
        ),
        "format_intent": "story",
        "story_sequence_role": role,
        "restrictions": [],
    }


def _make_carousel(
    project: str,
    category: str,
    assets: Sequence[Mapping[str, Any]],
    index: int,
) -> dict[str, Any]:
    return {
        "project_id": project,
        "id": f"carousel-{index:03d}",
        "category": category,
        "asset_ids": [
            _asset_reference(asset, f"asset-{index:03d}-{i:02d}")
            for i, asset in enumerate(assets, 1)
        ],
        "evidence": _merge_evidence(assets),
        "visible_summary": f"{category} visual set with {len(assets)} authenticated assets",
        "format_intent": "carousel",
        "carousel_position": 1,
        "restrictions": [],
    }


def _make_plan_review(
    project: str,
    asset: Mapping[str, Any],
    index: int,
) -> dict[str, Any] | None:
    category = _category(asset)
    relationships = _plan_relationships(asset)

    # No verified relationship => do not create a marketing opportunity.
    if not relationships:
        return None

    return {
        "project_id": project,
        "id": f"plan-{index:03d}",
        "category": category,
        "asset_ids": [_asset_reference(asset, f"plan-{index:03d}")],
        "evidence": _evidence(asset),
        "visible_summary": str(
            asset.get("visible_summary")
            or category
        ),
        "format_intent": "feed",
        "restrictions": [
            "Use plan/layout content only with verified relationship metadata",
            "Do not infer unit area, dimensions, unit type, or floor relationship",
        ],
    }


def reconstruct(
    repo: Path,
    project: str,
    asset_intelligence_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    repo = repo.resolve()

    if asset_intelligence_path is None:
        asset_intelligence_path = (
            repo
            / "output"
            / "asset-intelligence"
            / project
            / f"{project}-asset-intelligence.json"
        )

    asset_intelligence_path = asset_intelligence_path.resolve()

    expected_parent = (
        repo
        / "output"
        / "asset-intelligence"
        / project
    ).resolve()

    if expected_parent not in asset_intelligence_path.parents:
        raise CanonicalOpportunityReconstructionError(
            "4F.7C only accepts the canonical asset-intelligence source family"
        )

    doc = _read_json(asset_intelligence_path)

    if str(doc.get("project_id") or "") != project:
        raise CanonicalOpportunityReconstructionError(
            f"project mismatch: expected {project!r}, got {doc.get('project_id')!r}"
        )

    assets = doc.get("assets")
    if not isinstance(assets, list) or not assets:
        raise CanonicalOpportunityReconstructionError(
            "asset-intelligence contains no assets"
        )

    assets = [x for x in assets if isinstance(x, Mapping)]

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    generic_assets: list[Mapping[str, Any]] = []
    plan_assets: list[Mapping[str, Any]] = []

    for asset in assets:
        category = _category(asset)
        category_norm = _norm(category)

        if _is_plan_like(category):
            plan_assets.append(asset)
            continue

        if category_norm == "project feature":
            generic_assets.append(asset)
            continue

        grouped[category_norm].append(asset)

    opportunities: list[dict[str, Any]] = []
    carousel_index = 1
    story_index = 1
    feed_index = 1
    plan_index = 1

    # Structured categories first.
    for category in sorted(grouped):
        members = grouped[category]

        if category in CAROUSEL_CATEGORIES and len(members) >= 2:
            # Group in bounded carousel sets.
            for start in range(0, len(members), 5):
                chunk = members[start:start + 5]

                if len(chunk) >= 2:
                    opportunities.append(
                        _make_carousel(
                            project,
                            category,
                            chunk,
                            carousel_index,
                        )
                    )
                    carousel_index += 1
                else:
                    opportunities.append(
                        _make_feed(
                            project,
                            chunk[0],
                            feed_index,
                        )
                    )
                    feed_index += 1
            continue

        if category in STORY_CATEGORIES:
            for idx, member in enumerate(members, 1):
                opportunities.append(
                    _make_story(
                        project,
                        member,
                        story_index,
                        "hook" if idx == 1 else "proof",
                    )
                )
                story_index += 1
            continue

        for member in members:
            opportunities.append(
                _make_feed(
                    project,
                    member,
                    feed_index,
                )
            )
            feed_index += 1

    # Generic assets remain conservative individual feed candidates.
    for asset in generic_assets:
        opportunities.append(
            _make_feed(
                project,
                asset,
                feed_index,
            )
        )
        feed_index += 1

    # Plans only become marketing opportunities if relationships are verified.
    blocked_plans = 0

    for asset in plan_assets:
        opportunity = _make_plan_review(
            project,
            asset,
            plan_index,
        )

        if opportunity is None:
            blocked_plans += 1
        else:
            opportunities.append(opportunity)
            plan_index += 1

    if not opportunities:
        raise CanonicalOpportunityReconstructionError(
            "no canonical opportunities could be reconstructed"
        )

    for opportunity in opportunities:
        if opportunity["format_intent"] not in ALLOWED_FORMATS:
            raise CanonicalOpportunityReconstructionError(
                f"unsupported format generated: {opportunity['format_intent']}"
            )

        if not opportunity.get("asset_ids"):
            raise CanonicalOpportunityReconstructionError(
                f"opportunity missing authenticated assets: {opportunity['id']}"
            )

    metrics = {
        "source_assets": len(assets),
        "structured_category_assets": sum(len(v) for v in grouped.values()),
        "generic_assets": len(generic_assets),
        "plan_assets": len(plan_assets),
        "blocked_plan_assets": blocked_plans,
        "opportunities": len(opportunities),
        "feed": sum(1 for x in opportunities if x["format_intent"] == "feed"),
        "carousel": sum(1 for x in opportunities if x["format_intent"] == "carousel"),
        "story": sum(1 for x in opportunities if x["format_intent"] == "story"),
        "opportunities_with_evidence": sum(
            1 for x in opportunities if x.get("evidence")
        ),
    }

    out_dir = (
        repo
        / "output"
        / "visual-opportunities"
        / project
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{project}-visual-opportunities.json"

    payload = {
        "schema_version": "department3.visual-opportunities.v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project,
        "authority": {
            "authoritative": False,
            "role": "canonical_candidate_source",
            "consumer": "RealEstateStrategyBrain",
        },
        "source": {
            "asset_intelligence": str(asset_intelligence_path),
            "asset_intelligence_fingerprint": doc.get("fingerprint"),
        },
        "source_policy": {
            "asset_intelligence_only": True,
            "simulation_allowed": False,
            "release_allowed": False,
            "provenance_allowed": False,
            "audit_allowed": False,
            "previous_visual_opportunities_allowed": False,
            "network_used": False,
        },
        "metrics": metrics,
        "opportunities": opportunities,
    }

    payload["fingerprint"] = hashlib.sha256(
        json.dumps(
            {
                "project": project,
                "source_fingerprint": doc.get("fingerprint"),
                "opportunities": opportunities,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()

    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return out_path, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="Beverly Hills")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--asset-intelligence", default="")
    args = parser.parse_args()

    source = (
        Path(args.asset_intelligence)
        if args.asset_intelligence
        else None
    )

    path, payload = reconstruct(
        Path(args.repo),
        args.project,
        source,
    )

    print("Department 3 Phase 4F.7C canonical visual opportunity reconstruction completed")
    print(f"- Project: {args.project}")

    for key, value in payload["metrics"].items():
        print(f"- {key}: {value}")

    print("- Production authority changes: 0")
    print("- Meta writes: 0")
    print("- Instagram publish attempts: 0")
    print("- Network used: False")
    print(f"- Output: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
