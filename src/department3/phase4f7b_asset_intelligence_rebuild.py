from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

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
    "certification",
    "output-packages",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
}

TRUSTED_JSON_ROOTS = (
    "output/source-images",
    "output/visual-assets",
    "output/visual-inventory",
    "output/plan-intelligence",
    "output/knowledge",
    "output/markdown",
)

TRUSTED_IMAGE_ROOTS = (
    "output/source-images",
    "input",
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

RECORD_KEYS = (
    "selected",
    "selected_images",
    "approved",
    "assets",
    "visual_assets",
    "ranked",
    "images",
    "items",
    "eligible_assets",
    "plans",
    "relationships",
)

IDENTITY_KEYS = (
    "asset_id",
    "source_asset_id",
    "image_id",
    "visual_id",
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


class AssetIntelligenceRebuildError(RuntimeError):
    pass


def _norm(value: Any) -> str:
    return str(value or "").casefold().replace("\\", "/").replace("-", " ").replace("_", " ").strip()


def _excluded(path: Path) -> bool:
    return bool({p.casefold() for p in path.parts} & EXCLUDED_PARTS)


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

    for key in RECORD_KEYS:
        value = doc.get(key)
        if isinstance(value, list):
            records = [x for x in value if isinstance(x, Mapping)]
            if records:
                return records
        if isinstance(value, Mapping):
            nested = _extract_records(value)
            if nested:
                return nested

    direct = []
    for value in doc.values():
        if isinstance(value, Mapping) and any(
            value.get(k) for k in IDENTITY_KEYS + PATH_KEYS + CATEGORY_KEYS
        ):
            direct.append(value)
    return direct


def _identity(item: Mapping[str, Any], fallback: str) -> str:
    for key in IDENTITY_KEYS:
        value = item.get(key)
        if value:
            return str(value)

    for key in PATH_KEYS:
        value = item.get(key)
        if value:
            stem = Path(str(value)).stem
            return stem or str(value)

    return fallback


def _paths(item: Mapping[str, Any]) -> list[str]:
    result = []
    for key in PATH_KEYS:
        value = item.get(key)
        if value:
            result.append(str(value))
    return result


def _category(item: Mapping[str, Any], source_hint: str = "") -> str:
    for key in CATEGORY_KEYS:
        value = item.get(key)
        if value:
            raw = str(value).strip()
            inferred = _category_from_text(raw)
            return inferred if inferred != "project feature" else raw

    combined = " ".join(
        str(item.get(k) or "")
        for k in (
            "description",
            "visual_summary",
            "visible_summary",
            "caption",
            "label",
            "name",
        )
    )
    return _category_from_text(combined + " " + source_hint)


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
        result.append({
            "field": key,
            "value": value,
        })
    return result


def _json_sources(repo: Path, project: str) -> list[Path]:
    found = []
    seen = set()

    for rel in TRUSTED_JSON_ROOTS:
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
                found.append(path)
                continue

            doc = _try_json(path)
            if doc is not None and _project_match(doc, project):
                found.append(path)

    return sorted(found)


def _image_sources(repo: Path, project: str) -> list[Path]:
    found = []
    seen = set()

    for rel in TRUSTED_IMAGE_ROOTS:
        base = repo / rel
        if not base.exists():
            continue

        for path in base.rglob("*"):
            if (
                not path.is_file()
                or path.suffix.casefold() not in IMAGE_EXTS
                or _excluded(path)
            ):
                continue

            if not all(t in _norm(str(path)) for t in _project_tokens(project)):
                continue

            rp = path.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            found.append(path)

    return sorted(found)


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()

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


def _merge_asset(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    categories = list(existing.get("categories", []))
    if incoming["category"] not in categories:
        categories.append(incoming["category"])

    paths = list(existing.get("paths", []))
    for p in incoming["paths"]:
        if p not in paths:
            paths.append(p)

    evidence = _dedupe_evidence(
        list(existing.get("evidence", []))
        + list(incoming["evidence"])
    )

    plan_relationships = list(existing.get("plan_relationships", []))
    for rel in incoming["plan_relationships"]:
        if rel not in plan_relationships:
            plan_relationships.append(rel)

    source_files = list(existing.get("source_files", []))
    if incoming["source_file"] not in source_files:
        source_files.append(incoming["source_file"])

    preferred_category = existing.get("category") or incoming["category"]
    if preferred_category == "project feature" and incoming["category"] != "project feature":
        preferred_category = incoming["category"]

    return {
        "asset_id": existing["asset_id"],
        "category": preferred_category,
        "categories": categories,
        "paths": paths,
        "evidence": evidence,
        "plan_relationships": plan_relationships,
        "source_files": source_files,
        "visible_summary": (
            existing.get("visible_summary")
            if existing.get("visible_summary") not in (None, "", "project feature")
            else incoming.get("visible_summary")
        ),
    }


def rebuild(repo: Path, project: str) -> tuple[Path, dict[str, Any]]:
    repo = repo.resolve()

    json_files = _json_sources(repo, project)
    image_files = _image_sources(repo, project)

    assets: dict[str, dict[str, Any]] = {}

    for path in json_files:
        doc = _try_json(path)
        if doc is None:
            continue

        records = _extract_records(doc)

        for idx, item in enumerate(records, 1):
            asset_id = _identity(item, f"{path.stem}-{idx:03d}")

            if not asset_id:
                continue

            category = _category(item, str(path))

            incoming = {
                "asset_id": asset_id,
                "category": category,
                "categories": [category],
                "paths": _paths(item),
                "evidence": _evidence(item),
                "plan_relationships": _plan_relationships(item),
                "source_files": [str(path)],
                "source_file": str(path),
                "visible_summary": str(
                    item.get("visible_summary")
                    or item.get("visual_summary")
                    or item.get("description")
                    or item.get("caption")
                    or category
                ),
            }

            key = _norm(asset_id)

            if key in assets:
                assets[key] = _merge_asset(assets[key], incoming)
            else:
                assets[key] = {
                    "asset_id": asset_id,
                    "category": category,
                    "categories": [category],
                    "paths": incoming["paths"],
                    "evidence": incoming["evidence"],
                    "plan_relationships": incoming["plan_relationships"],
                    "source_files": [str(path)],
                    "visible_summary": incoming["visible_summary"],
                }

            for p in incoming["paths"]:
                pkey = _norm(Path(p).stem)
                if pkey and pkey in assets and pkey != key:
                    assets[key] = _merge_asset(assets[key], {
                        "asset_id": assets[key]["asset_id"],
                        "category": assets[pkey]["category"],
                        "paths": assets[pkey]["paths"],
                        "evidence": assets[pkey]["evidence"],
                        "plan_relationships": assets[pkey]["plan_relationships"],
                        "source_file": assets[pkey]["source_files"][0],
                        "visible_summary": assets[pkey]["visible_summary"],
                    })

    # Preserve authenticated original images even if structured metadata is sparse.
    for path in image_files:
        stem = path.stem
        key = _norm(stem)

        if key in assets:
            if str(path) not in assets[key]["paths"]:
                assets[key]["paths"].append(str(path))
            continue

        category = _category_from_text(str(path))

        assets[key] = {
            "asset_id": stem,
            "category": category,
            "categories": [category],
            "paths": [str(path)],
            "evidence": [],
            "plan_relationships": [],
            "source_files": [str(path)],
            "visible_summary": category,
        }

    if not assets:
        raise AssetIntelligenceRebuildError(
            f"no authentic upstream asset state could be rebuilt for {project!r}; "
            f"trusted_json_files={len(json_files)}, trusted_image_files={len(image_files)}"
        )

    ordered_assets = sorted(
        assets.values(),
        key=lambda x: x["asset_id"],
    )

    metrics = {
        "trusted_json_files": len(json_files),
        "trusted_image_files": len(image_files),
        "assets": len(ordered_assets),
        "assets_with_non_generic_category": sum(
            1 for x in ordered_assets
            if x["category"] != "project feature"
        ),
        "assets_with_paths": sum(
            1 for x in ordered_assets
            if x["paths"]
        ),
        "assets_with_evidence": sum(
            1 for x in ordered_assets
            if x["evidence"]
        ),
        "assets_with_plan_relationships": sum(
            1 for x in ordered_assets
            if x["plan_relationships"]
        ),
    }

    out_dir = repo / "output" / "asset-intelligence" / project
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{project}-asset-intelligence.json"

    payload = {
        "schema_version": "department3.asset-intelligence.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project,
        "authority": {
            "authoritative": False,
            "role": "upstream_asset_intelligence",
            "consumer": "Department3 visual-opportunity reconstruction",
        },
        "source_policy": {
            "simulation_allowed": False,
            "visual_opportunities_allowed": False,
            "audit_allowed": False,
            "release_allowed": False,
            "provenance_allowed": False,
            "network_used": False,
        },
        "metrics": metrics,
        "assets": ordered_assets,
    }

    payload["fingerprint"] = hashlib.sha256(
        json.dumps(
            {
                "project": project,
                "assets": ordered_assets,
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
    args = parser.parse_args()

    path, payload = rebuild(Path(args.repo), args.project)

    print("Department 3 Phase 4F.7B authentic upstream asset intelligence rebuild completed")
    print(f"- Project: {args.project}")

    for key, value in payload["metrics"].items():
        print(f"- {key}: {value}")

    print("- Production publishing changes: 0")
    print("- Meta writes: 0")
    print("- Instagram publish attempts: 0")
    print("- Network used: False")
    print(f"- Output: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
