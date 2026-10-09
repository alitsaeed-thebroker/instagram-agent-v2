from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

EXCLUDED_PARTS = {
    "audits", "backups", "archive", "releases", "provenance",
    "produced-images", "branded-images", "post-packages",
}

CATEGORY_ORDER = (
    "location",
    "masterplan",
    "exterior",
    "interior",
    "amenity",
    "commercial",
    "unit layout",
    "floor plan",
    "project feature",
)

PLAN_TOKENS = (
    "unit plan", "unit layout", "floor plan", "typical floor",
    "master floor", "apartment plan", "office plan", "villa plan",
)

CATEGORY_RULES = (
    ("location", ("location", "map", "site location", "access")),
    ("masterplan", ("masterplan", "master plan", "site plan")),
    ("unit layout", ("unit plan", "unit layout", "apartment plan", "office plan", "villa plan")),
    ("floor plan", ("floor plan", "typical floor", "master floor")),
    ("exterior", ("exterior", "facade", "façade", "elevation", "tower render")),
    ("interior", ("interior", "living room", "bedroom", "lobby", "kitchen", "office interior")),
    ("amenity", ("amenity", "pool", "gym", "park", "garden", "clubhouse", "playground", "lifestyle")),
    ("commercial", ("commercial", "retail", "shop", "office", "business")),
)


class QualityReconstructionError(RuntimeError):
    pass


def _norm(value: Any) -> str:
    return str(value or "").casefold().replace("-", " ").replace("_", " ").strip()


def _excluded(path: Path) -> bool:
    return bool({x.casefold() for x in path.parts} & EXCLUDED_PARTS)


def _try_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _project_match(value: Any, project: str, depth: int = 0) -> bool:
    if depth > 6:
        return False
    tokens = tuple(x for x in _norm(project).split() if x)
    if isinstance(value, str):
        hay = _norm(value)
        return bool(tokens) and all(x in hay for x in tokens)
    if isinstance(value, Mapping):
        for key in ("project_id", "project", "project_name", "source_project", "namespace"):
            if key in value and _project_match(value[key], project, depth + 1):
                return True
        return any(
            _project_match(k, project, depth + 1)
            or _project_match(v, project, depth + 1)
            for k, v in value.items()
        )
    if isinstance(value, list):
        return any(_project_match(x, project, depth + 1) for x in value[:500])
    return False


def _category_from_text(text: str) -> str:
    low = _norm(text)
    for category, tokens in CATEGORY_RULES:
        if any(token in low for token in tokens):
            return category
    return "project feature"


def _extract_records(doc: Any) -> list[Mapping[str, Any]]:
    if isinstance(doc, list):
        return [x for x in doc if isinstance(x, Mapping)]
    if not isinstance(doc, Mapping):
        return []

    keys = (
        "selected", "selected_images", "approved", "assets",
        "visual_assets", "ranked", "images", "items",
        "eligible_assets", "opportunities", "visual_opportunities",
        "candidates", "relationships", "facts",
    )
    for key in keys:
        value = doc.get(key)
        if isinstance(value, list):
            records = [x for x in value if isinstance(x, Mapping)]
            if records:
                return records
        if isinstance(value, Mapping):
            nested = _extract_records(value)
            if nested:
                return nested

    return []


def _asset_identity(item: Mapping[str, Any], fallback: str) -> str:
    for key in (
        "asset_id", "source_asset_id", "image_id", "visual_id",
        "production_item_id", "item_id", "id",
    ):
        if item.get(key):
            return str(item[key])

    for key in (
        "source_path", "image_path", "path", "file",
        "filename", "asset_path", "selected_image_path",
    ):
        if item.get(key):
            return str(item[key])

    return fallback


def _asset_path(item: Mapping[str, Any]) -> str | None:
    for key in (
        "source_path", "image_path", "path", "file",
        "filename", "asset_path", "selected_image_path",
    ):
        if item.get(key):
            return str(item[key])
    return None


def _record_category(item: Mapping[str, Any], source_hint: str = "") -> str:
    for key in (
        "content_category", "category", "asset_type",
        "classification", "visual_type", "type",
    ):
        if item.get(key):
            raw = str(item[key]).strip()
            inferred = _category_from_text(raw)
            return inferred if inferred != "project feature" else raw

    combined = " ".join(
        str(item.get(k) or "")
        for k in (
            "description", "visual_summary", "visible_summary",
            "caption", "label", "name",
        )
    )
    return _category_from_text(combined + " " + source_hint)


def _extract_evidence(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = (
        item.get("evidence")
        or item.get("evidence_refs")
        or item.get("facts")
        or item.get("fact_refs")
        or item.get("provenance")
        or []
    )

    if isinstance(raw, Mapping):
        raw = [raw]

    result = []
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, str) and x.strip():
                result.append({"fact_id": x.strip()})
                continue
            if not isinstance(x, Mapping):
                continue

            fact_id = (
                x.get("fact_id")
                or x.get("knowledge_fact_id")
                or x.get("id")
                or x.get("fact")
                or x.get("claim_id")
            )
            if not fact_id:
                continue

            rec = {"fact_id": str(fact_id)}
            source_id = x.get("source_id") or x.get("source") or x.get("document_id")
            confidence = x.get("confidence")
            if source_id:
                rec["source_id"] = str(source_id)
            if confidence is not None:
                try:
                    rec["confidence"] = float(confidence)
                except Exception:
                    pass
            result.append(rec)

    return result


def _metadata_files(repo: Path, project: str) -> list[Path]:
    roots = (
        repo / "output" / "source-images",
        repo / "output" / "visual-assets",
        repo / "output" / "visual-inventory",
        repo / "output" / "asset-intelligence",
        repo / "output" / "plan-intelligence",
        repo / "output" / "creative-intelligence",
        repo / "output" / "campaign-intelligence",
        repo / "output",
    )

    found = []
    seen = set()

    for base in roots:
        if not base.exists():
            continue

        for path in base.rglob("*.json"):
            if not path.is_file() or _excluded(path):
                continue

            rp = path.resolve()
            if rp in seen:
                continue
            seen.add(rp)

            if all(x in _norm(str(path)) for x in _norm(project).split()):
                found.append(path)
                continue

            doc = _try_json(path)
            if doc is not None and _project_match(doc, project):
                found.append(path)

    return sorted(found, key=lambda p: (-p.stat().st_mtime, str(p)))


def _fact_index(files: list[Path]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for path in files:
        doc = _try_json(path)
        if not isinstance(doc, Mapping):
            continue

        records = _extract_records(doc)
        for idx, item in enumerate(records, 1):
            key = _norm(_asset_identity(item, f"{path.stem}-{idx:03d}"))
            evidence = _extract_evidence(item)
            if key and evidence:
                index[key].extend(evidence)

            asset_path = _asset_path(item)
            if asset_path and evidence:
                index[_norm(asset_path)].extend(evidence)

    return index


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = (
            str(item.get("fact_id")),
            str(item.get("source_id") or ""),
            item.get("confidence"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _collect_assets(files: list[Path], project: str) -> list[dict[str, Any]]:
    fact_index = _fact_index(files)
    result = []
    seen = set()

    for path in files:
        doc = _try_json(path)
        if doc is None:
            continue

        records = _extract_records(doc)
        for idx, item in enumerate(records, 1):
            asset_id = _asset_identity(item, f"{path.stem}-{idx:03d}")
            asset_path = _asset_path(item)
            dedupe_key = _norm(asset_path or asset_id)

            if not dedupe_key or dedupe_key in seen:
                continue

            category = _record_category(item, (asset_path or "") + " " + str(path))
            evidence = _extract_evidence(item)

            if not evidence:
                evidence.extend(fact_index.get(_norm(asset_id), []))
                if asset_path:
                    evidence.extend(fact_index.get(_norm(asset_path), []))

            evidence = _dedupe_evidence(evidence)

            seen.add(dedupe_key)
            result.append({
                "asset_id": asset_id,
                "asset_path": asset_path,
                "category": category,
                "evidence": evidence,
                "visible_summary": str(
                    item.get("visible_summary")
                    or item.get("visual_summary")
                    or item.get("description")
                    or item.get("caption")
                    or category
                ),
                "source_metadata": str(path),
            })

    return result


def _group_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for asset in assets:
        category = _category_from_text(asset["category"])
        if category == "project feature":
            category = asset["category"] or "project feature"
        groups[category].append(asset)

    opportunities = []
    counter = 1

    for category in CATEGORY_ORDER:
        members = groups.pop(category, [])
        if not members:
            continue

        members = sorted(members, key=lambda x: (x["asset_id"], x["asset_path"] or ""))

        if category in {"masterplan", "exterior", "interior", "commercial"} and len(members) >= 2:
            chunk_size = min(5, len(members))
            for start in range(0, len(members), chunk_size):
                chunk = members[start:start + chunk_size]
                opportunity_id = f"{category.replace(' ', '-')}-{counter:03d}"
                counter += 1
                evidence = _dedupe_evidence([e for x in chunk for e in x["evidence"]])
                opportunities.append({
                    "id": opportunity_id,
                    "category": category,
                    "asset_ids": [
                        x["asset_path"] or x["asset_id"]
                        for x in chunk
                    ],
                    "evidence": evidence,
                    "visible_summary": f"{category} visual set with {len(chunk)} authenticated assets",
                    "format_intent": "carousel",
                    "carousel_position": 1,
                })
            continue

        if category == "amenity":
            for idx, member in enumerate(members, 1):
                opportunity_id = f"amenity-{counter:03d}"
                counter += 1
                opportunities.append({
                    "id": opportunity_id,
                    "category": category,
                    "asset_ids": [member["asset_path"] or member["asset_id"]],
                    "evidence": member["evidence"],
                    "visible_summary": member["visible_summary"],
                    "format_intent": "story",
                    "story_sequence_role": "hook" if idx == 1 else "proof",
                })
            continue

        for member in members:
            opportunity_id = f"{category.replace(' ', '-')}-{counter:03d}"
            counter += 1
            plan_like = any(token in category.casefold() for token in PLAN_TOKENS)
            if plan_like and not member["evidence"]:
                # Keep the source visible but ensure the strategy brain fails closed.
                restrictions = ["PLAN_EVIDENCE_REQUIRED"]
            else:
                restrictions = []

            opportunities.append({
                "id": opportunity_id,
                "category": category,
                "asset_ids": [member["asset_path"] or member["asset_id"]],
                "evidence": member["evidence"],
                "visible_summary": member["visible_summary"],
                "format_intent": (
                    "story"
                    if category in {"location"}
                    else "feed"
                ),
                "story_sequence_role": "hook" if category == "location" else None,
                "restrictions": restrictions,
            })

    # Any unknown categories are preserved individually rather than discarded.
    for category in sorted(groups):
        for member in groups[category]:
            opportunity_id = f"feature-{counter:03d}"
            counter += 1
            opportunities.append({
                "id": opportunity_id,
                "category": category or "project feature",
                "asset_ids": [member["asset_path"] or member["asset_id"]],
                "evidence": member["evidence"],
                "visible_summary": member["visible_summary"],
                "format_intent": "feed",
                "restrictions": [],
            })

    return opportunities


def reconstruct(repo: Path, project: str):
    repo = repo.resolve()
    files = _metadata_files(repo, project)
    if not files:
        raise QualityReconstructionError("no Beverly Hills structured metadata files found")

    assets = _collect_assets(files, project)
    if not assets:
        raise QualityReconstructionError(
            f"structured metadata found ({len(files)} files), but no usable visual assets could be reconstructed"
        )

    opportunities = _group_assets(assets)
    if not opportunities:
        raise QualityReconstructionError("no opportunities produced from reconstructed assets")

    for item in opportunities:
        item["project_id"] = project

    metrics = {
        "metadata_files_scanned": len(files),
        "reconstructed_assets": len(assets),
        "opportunities": len(opportunities),
        "with_evidence": sum(1 for x in opportunities if x["evidence"]),
        "feed": sum(1 for x in opportunities if x.get("format_intent") == "feed"),
        "carousel": sum(1 for x in opportunities if x.get("format_intent") == "carousel"),
        "story": sum(1 for x in opportunities if x.get("format_intent") == "story"),
        "plan_like": sum(
            1 for x in opportunities
            if any(token in x["category"].casefold() for token in PLAN_TOKENS)
        ),
    }

    out_dir = repo / "output" / "visual-opportunities" / project
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{project}-visual-opportunities.json"

    payload = {
        "schema_version": "department3.visual-opportunities.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project,
        "authority": {
            "authoritative": False,
            "role": "candidate_source",
            "consumer": "RealEstateStrategyBrain",
        },
        "quality_reconstruction": {
            "grouping_enabled": True,
            "evidence_recovery_enabled": True,
            "plan_fail_closed": True,
            "audit_sources_allowed": False,
            "release_sources_allowed": False,
        },
        "metrics": metrics,
        "opportunities": opportunities,
        "asset_index": assets,
    }

    payload["fingerprint"] = hashlib.sha256(
        json.dumps(
            {
                "project": project,
                "opportunities": opportunities,
                "assets": assets,
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="Beverly Hills")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    path, payload = reconstruct(Path(args.repo), args.project)

    print("Department 3 Phase 4F.6 canonical visual opportunity quality reconstruction completed")
    print(f"- Project: {args.project}")
    for key, value in payload["metrics"].items():
        print(f"- {key}: {value}")
    print("- Meta writes: 0")
    print("- Instagram publish attempts: 0")
    print(f"- Output: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
