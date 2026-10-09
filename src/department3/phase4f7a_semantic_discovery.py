from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

EXCLUDED_PARTS = {
    "visual-opportunities",
    "simulation",
    "audits",
    "releases",
    "backups",
    "provenance",
    "produced-images",
    "branded-images",
    "post-packages",
    "publishing",
    "queue",
    "output-packages",
    "certification",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
}

AUTHENTIC_ROOTS = (
    "output/source-images",
    "output/visual-assets",
    "output/visual-inventory",
    "output/asset-intelligence",
    "output/plan-intelligence",
    "output/creative-intelligence",
    "output/campaign-intelligence",
    "output/knowledge",
    "output/knowledge-evaluation",
    "output/markdown",
    "input",
)

IDENTITY_KEYS = (
    "asset_id",
    "source_asset_id",
    "image_id",
    "visual_id",
    "production_item_id",
    "item_id",
    "id",
)

PATH_KEYS = (
    "source_path",
    "image_path",
    "path",
    "file",
    "filename",
    "asset_path",
    "selected_image_path",
    "original_path",
)

CATEGORY_KEYS = (
    "content_category",
    "category",
    "asset_type",
    "classification",
    "visual_type",
    "type",
    "semantic_class",
)

EVIDENCE_KEYS = (
    "evidence",
    "evidence_refs",
    "facts",
    "fact_refs",
    "provenance",
    "knowledge_refs",
)

PLAN_RELATION_KEYS = (
    "plan_relationship",
    "relationship",
    "unit_relationship",
    "floor_relationship",
    "layout_relationship",
    "plan_type",
    "layout_type",
)

RECORD_LIST_KEYS = (
    "selected",
    "selected_images",
    "approved",
    "assets",
    "visual_assets",
    "ranked",
    "images",
    "items",
    "eligible_assets",
    "relationships",
    "plans",
    "candidates",
    "opportunities",
)


class SemanticDiscoveryError(RuntimeError):
    pass


def _norm(value: Any) -> str:
    return str(value or "").casefold().replace("\\", "/").replace("-", " ").replace("_", " ").strip()


def _excluded(path: Path) -> bool:
    return bool({part.casefold() for part in path.parts} & EXCLUDED_PARTS)


def _try_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _project_tokens(project: str) -> tuple[str, ...]:
    return tuple(x for x in _norm(project).split() if x)


def _project_match(value: Any, project: str, depth: int = 0) -> bool:
    if depth > 6:
        return False

    tokens = _project_tokens(project)
    if isinstance(value, str):
        hay = _norm(value)
        return bool(tokens) and all(t in hay for t in tokens)

    if isinstance(value, Mapping):
        for key in (
            "project_id",
            "project",
            "project_name",
            "source_project",
            "namespace",
            "canonical_project_name",
        ):
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


def _extract_records(doc: Any) -> list[Mapping[str, Any]]:
    if isinstance(doc, list):
        return [x for x in doc if isinstance(x, Mapping)]

    if not isinstance(doc, Mapping):
        return []

    for key in RECORD_LIST_KEYS:
        value = doc.get(key)
        if isinstance(value, list):
            records = [x for x in value if isinstance(x, Mapping)]
            if records:
                return records
        if isinstance(value, Mapping):
            nested = _extract_records(value)
            if nested:
                return nested

    # Last-resort: direct child mappings that look asset-like.
    direct = []
    for value in doc.values():
        if isinstance(value, Mapping):
            if any(value.get(k) for k in IDENTITY_KEYS + PATH_KEYS + CATEGORY_KEYS):
                direct.append(value)
    return direct


def _asset_ids_from_record(item: Mapping[str, Any]) -> list[str]:
    result = []
    for key in IDENTITY_KEYS:
        value = item.get(key)
        if value:
            result.append(str(value))
    for key in PATH_KEYS:
        value = item.get(key)
        if value:
            result.append(str(value))
            stem = Path(str(value)).stem
            if stem:
                result.append(stem)
    # preserve order, remove dupes
    seen = set()
    out = []
    for value in result:
        key = _norm(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _category(item: Mapping[str, Any]) -> str | None:
    for key in CATEGORY_KEYS:
        value = item.get(key)
        if value:
            return str(value).strip()
    return None


def _paths(item: Mapping[str, Any]) -> list[str]:
    result = []
    for key in PATH_KEYS:
        value = item.get(key)
        if value:
            result.append(str(value))
    return result


def _evidence(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = None
    for key in EVIDENCE_KEYS:
        if item.get(key):
            raw = item.get(key)
            break

    if raw is None:
        return []

    if isinstance(raw, Mapping):
        raw = [raw]

    result = []
    if isinstance(raw, list):
        for value in raw:
            if isinstance(value, str) and value.strip():
                result.append({"fact_id": value.strip()})
                continue

            if not isinstance(value, Mapping):
                continue

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
                or value.get("filename")
            )
            confidence = value.get("confidence")

            if source_id:
                rec["source_id"] = str(source_id)
            if confidence is not None:
                try:
                    rec["confidence"] = float(confidence)
                except Exception:
                    pass

            result.append(rec)

    return result


def _plan_relationships(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for key in PLAN_RELATION_KEYS:
        value = item.get(key)
        if not value:
            continue
        if isinstance(value, Mapping):
            rec = {"field": key, "value": dict(value)}
        elif isinstance(value, list):
            rec = {"field": key, "value": list(value)}
        else:
            rec = {"field": key, "value": value}
        result.append(rec)
    return result


def _candidate_files(repo: Path, project: str) -> list[Path]:
    result = []
    seen = set()

    for rel in AUTHENTIC_ROOTS:
        base = repo / rel
        if not base.exists():
            continue

        for path in base.rglob("*.json"):
            if not path.is_file() or _excluded(path):
                continue

            rp = path.resolve()
            if rp in seen:
                continue
            seen.add(rp)

            path_match = all(t in _norm(str(path)) for t in _project_tokens(project))
            if path_match:
                result.append(path)
                continue

            doc = _try_json(path)
            if doc is not None and _project_match(doc, project):
                result.append(path)

    return sorted(result, key=lambda p: (str(p).casefold(),))


def _source_rank(path: Path) -> int:
    low = _norm(str(path))
    ranking = (
        ("plan intelligence", 0),
        ("asset intelligence", 1),
        ("visual inventory", 2),
        ("visual assets", 3),
        ("source images", 4),
        ("creative intelligence", 5),
        ("campaign intelligence", 6),
        ("knowledge", 7),
        ("input", 8),
    )
    for token, rank in ranking:
        if token in low:
            return rank
    return 99


def _best_source(entries: list[dict[str, Any]]) -> str | None:
    if not entries:
        return None

    scored = []
    for entry in entries:
        score = 0
        if entry.get("category"):
            score += 4
        if entry.get("paths"):
            score += 3
        if entry.get("evidence"):
            score += 5
        if entry.get("plan_relationships"):
            score += 6

        source = entry["source_file"]
        score -= _source_rank(Path(source)) * 0.1
        scored.append((score, source))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][1]


def discover(repo: Path, project: str, target_asset_ids: list[str] | None = None) -> dict[str, Any]:
    repo = repo.resolve()
    files = _candidate_files(repo, project)

    if not files:
        raise SemanticDiscoveryError(
            f"no authentic upstream JSON sources found for {project!r}"
        )

    target_norm = {_norm(x) for x in target_asset_ids or []}
    asset_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    aliases: dict[str, str] = {}

    files_with_records = 0

    for path in files:
        doc = _try_json(path)
        if doc is None:
            continue

        records = _extract_records(doc)
        if not records:
            continue

        files_with_records += 1

        for item in records:
            ids = _asset_ids_from_record(item)
            if not ids:
                continue

            canonical = None
            # Prefer src_* identity where available.
            for value in ids:
                if Path(str(value)).stem.startswith("src_"):
                    canonical = Path(str(value)).stem
                    break
            canonical = canonical or Path(str(ids[0])).stem or str(ids[0])

            entry = {
                "source_file": str(path),
                "category": _category(item),
                "paths": _paths(item),
                "evidence": _evidence(item),
                "plan_relationships": _plan_relationships(item),
                "raw_identity_values": ids,
            }

            for value in ids:
                aliases[_norm(value)] = canonical
                aliases[_norm(Path(str(value)).stem)] = canonical

            asset_map[canonical].append(entry)

    # If explicit target asset ids were supplied, constrain output to those/aliases.
    if target_norm:
        resolved_targets = set()
        for raw in target_norm:
            canonical = aliases.get(raw)
            if canonical:
                resolved_targets.add(canonical)
            else:
                stem = _norm(Path(raw).stem)
                if stem in aliases:
                    resolved_targets.add(aliases[stem])
        asset_map = {
            k: v for k, v in asset_map.items()
            if k in resolved_targets
        }

    output_assets = {}
    for asset_id in sorted(asset_map):
        entries = asset_map[asset_id]

        categories = sorted({
            str(e["category"])
            for e in entries
            if e.get("category")
        })

        paths = sorted({
            p
            for e in entries
            for p in e.get("paths", [])
            if p
        })

        evidence = []
        seen_ev = set()
        for e in entries:
            for ev in e.get("evidence", []):
                key = (
                    str(ev.get("fact_id")),
                    str(ev.get("source_id") or ""),
                    ev.get("confidence"),
                )
                if key in seen_ev:
                    continue
                seen_ev.add(key)
                evidence.append(ev)

        plan_relationships = [
            rel
            for e in entries
            for rel in e.get("plan_relationships", [])
        ]

        output_assets[asset_id] = {
            "sources_found": [e["source_file"] for e in entries],
            "classifications_found": categories,
            "paths_found": paths,
            "evidence_found": evidence,
            "plan_relationships_found": plan_relationships,
            "canonical_source": _best_source(entries),
        }

    summary = {
        "authentic_files_scanned": len(files),
        "files_with_asset_records": files_with_records,
        "assets_mapped": len(output_assets),
        "assets_with_classification": sum(
            1 for x in output_assets.values()
            if x["classifications_found"]
        ),
        "assets_with_evidence": sum(
            1 for x in output_assets.values()
            if x["evidence_found"]
        ),
        "assets_with_plan_relationships": sum(
            1 for x in output_assets.values()
            if x["plan_relationships_found"]
        ),
    }

    return {
        "schema_version": "department3.phase4f7a.authentic-semantic-discovery.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project,
        "read_only": True,
        "excluded_source_families": sorted(EXCLUDED_PARTS),
        "authentic_roots": list(AUTHENTIC_ROOTS),
        "summary": summary,
        "assets": output_assets,
    }


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Department 3 Phase 4F.7A — Authentic Upstream Semantic Discovery Audit",
        "",
        f"- Project: {report['project_id']}",
        "- Production files modified: **0**",
        "",
        "## Summary",
        "",
    ]

    for key, value in report["summary"].items():
        lines.append(f"- {key}: {value}")

    lines += ["", "## Asset Mapping", ""]

    for asset_id, data in report["assets"].items():
        lines.append(f"### `{asset_id}`")
        lines.append(f"- canonical_source: `{data['canonical_source']}`")
        lines.append(f"- classifications_found: {data['classifications_found']}")
        lines.append(f"- paths_found: {data['paths_found']}")
        lines.append(f"- evidence_count: {len(data['evidence_found'])}")
        lines.append(f"- plan_relationship_count: {len(data['plan_relationships_found'])}")
        lines.append("- sources_found:")
        for source in data["sources_found"]:
            lines.append(f"  - `{source}`")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="Beverly Hills")
    parser.add_argument("--repo", default=".")
    parser.add_argument(
        "--asset-file",
        default="",
        help="Optional visual-opportunities JSON whose asset_index/opportunities supply target ids.",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    target_asset_ids = None

    if args.asset_file:
        asset_doc = _try_json(Path(args.asset_file))
        if not isinstance(asset_doc, Mapping):
            raise SystemExit(f"cannot read target asset file: {args.asset_file}")

        ids = []
        for key in ("asset_index", "opportunities"):
            value = asset_doc.get(key)
            if isinstance(value, list):
                for item in value:
                    if not isinstance(item, Mapping):
                        continue
                    if item.get("asset_id"):
                        ids.append(str(item["asset_id"]))
                    raw_assets = item.get("asset_ids")
                    if isinstance(raw_assets, list):
                        ids.extend(str(x) for x in raw_assets)
        target_asset_ids = ids or None

    report = discover(repo, args.project, target_asset_ids)

    out = repo / "output" / "audits" / "department3"
    out.mkdir(parents=True, exist_ok=True)

    slug = "-".join(x for x in _norm(args.project).split() if x)
    json_path = out / f"department3-phase4f7a-{slug}-semantic-discovery.json"
    md_path = out / f"department3-phase4f7a-{slug}-semantic-discovery.md"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(_markdown(report), encoding="utf-8")

    print("Department 3 Phase 4F.7A authentic semantic discovery audit completed")
    print(f"- Project: {args.project}")
    for key, value in report["summary"].items():
        print(f"- {key}: {value}")
    print("- Production files modified: 0")
    print("- Meta writes: 0")
    print("- Instagram publish attempts: 0")
    print(f"- JSON: {json_path}")
    print(f"- Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
