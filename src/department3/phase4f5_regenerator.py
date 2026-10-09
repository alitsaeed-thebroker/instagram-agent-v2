from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
EXCLUDED_PARTS = {
    "audits", "backups", "archive", "releases", "provenance",
    "produced-images", "branded-images", "post-packages",
}


class VisualOpportunityRegenerationError(RuntimeError):
    pass


def _norm(value: Any) -> str:
    return str(value or "").casefold().replace("-", " ").replace("_", " ").strip()


def _project_tokens(project: str) -> tuple[str, ...]:
    return tuple(x for x in _norm(project).split() if x)


def _path_mentions_project(path: Path, project: str) -> bool:
    hay = _norm(str(path))
    tokens = _project_tokens(project)
    return bool(tokens) and all(t in hay for t in tokens)


def _excluded(path: Path) -> bool:
    return bool({x.casefold() for x in path.parts} & EXCLUDED_PARTS)


def _try_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _project_in_json(value: Any, project: str, depth: int = 0) -> bool:
    if depth > 6:
        return False
    tokens = _project_tokens(project)
    if isinstance(value, str):
        hay = _norm(value)
        return bool(tokens) and all(t in hay for t in tokens)
    if isinstance(value, Mapping):
        for key in ("project_id", "project", "project_name", "source_project", "namespace"):
            if key in value and _project_in_json(value[key], project, depth + 1):
                return True
        return any(
            _project_in_json(k, project, depth + 1)
            or _project_in_json(v, project, depth + 1)
            for k, v in value.items()
        )
    if isinstance(value, list):
        return any(_project_in_json(v, project, depth + 1) for v in value[:500])
    return False


def _category_from_text(text: str) -> str:
    low = _norm(text)
    rules = (
        ("location", ("location", "map", "site location")),
        ("masterplan", ("masterplan", "master plan", "site plan")),
        ("unit layout", ("unit plan", "unit layout", "apartment plan", "office plan", "villa plan")),
        ("floor plan", ("floor plan", "typical floor", "master floor")),
        ("exterior", ("exterior", "facade", "façade", "elevation")),
        ("interior", ("interior", "living room", "bedroom", "lobby", "office interior")),
        ("amenity", ("amenity", "pool", "gym", "park", "garden", "clubhouse", "playground")),
        ("commercial", ("commercial", "retail", "shop", "office")),
    )
    for category, tokens in rules:
        if any(token in low for token in tokens):
            return category
    return "project feature"


def _extract_records(doc: Any) -> list[Mapping[str, Any]]:
    if isinstance(doc, list):
        return [x for x in doc if isinstance(x, Mapping)]
    if not isinstance(doc, Mapping):
        return []

    priority_keys = (
        "selected",
        "selected_images",
        "approved",
        "assets",
        "visual_assets",
        "ranked",
        "images",
        "items",
        "eligible_assets",
    )
    for key in priority_keys:
        value = doc.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, Mapping)]
        if isinstance(value, Mapping):
            nested = _extract_records(value)
            if nested:
                return nested

    return []


def _record_asset_path(item: Mapping[str, Any]) -> str | None:
    for key in (
        "source_path", "image_path", "path", "file", "filename",
        "asset_path", "selected_image_path",
    ):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _record_asset_id(item: Mapping[str, Any], fallback: str) -> str:
    for key in ("asset_id", "source_asset_id", "image_id", "visual_id", "id"):
        if item.get(key):
            return str(item[key])
    return fallback


def _record_category(item: Mapping[str, Any], path_hint: str = "") -> str:
    for key in (
        "content_category", "category", "asset_type",
        "classification", "visual_type", "type",
    ):
        if item.get(key):
            return str(item[key]).strip()
    combined = " ".join(
        str(item.get(k) or "")
        for k in ("description", "visual_summary", "visible_summary", "caption")
    )
    return _category_from_text(combined + " " + path_hint)


def _record_evidence(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = item.get("evidence") or item.get("evidence_refs") or item.get("facts") or []
    if isinstance(raw, Mapping):
        raw = [raw]
    out = []
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, str) and x.strip():
                out.append({"fact_id": x.strip()})
            elif isinstance(x, Mapping):
                fid = x.get("fact_id") or x.get("id") or x.get("fact")
                if fid:
                    rec = {"fact_id": str(fid)}
                    if x.get("source_id"):
                        rec["source_id"] = str(x["source_id"])
                    if x.get("confidence") is not None:
                        rec["confidence"] = float(x["confidence"])
                    out.append(rec)
    return out


def _metadata_sources(repo: Path, project: str) -> list[Path]:
    preferred = (
        repo / "output" / "source-images",
        repo / "output" / "visual-assets",
        repo / "output" / "visual-inventory",
        repo / "output" / "asset-intelligence",
        repo / "output" / "plan-intelligence",
        repo / "output",
    )
    found = []
    seen = set()

    for base in preferred:
        if not base.exists():
            continue
        for path in base.rglob("*.json"):
            if not path.is_file() or _excluded(path):
                continue
            rp = path.resolve()
            if rp in seen:
                continue
            seen.add(rp)

            if _path_mentions_project(path, project):
                found.append(path)
                continue

            doc = _try_json(path)
            if doc is not None and _project_in_json(doc, project):
                found.append(path)

    return sorted(found, key=lambda p: (-p.stat().st_mtime, str(p)))


def _image_sources(repo: Path, project: str) -> list[Path]:
    bases = (
        repo / "output" / "source-images",
        repo / "input",
    )
    out = []
    seen = set()
    for base in bases:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if (
                path.is_file()
                and path.suffix.casefold() in SUPPORTED_IMAGE_EXTS
                and not _excluded(path)
                and _path_mentions_project(path, project)
            ):
                rp = path.resolve()
                if rp not in seen:
                    seen.add(rp)
                    out.append(path)
    return sorted(out)


def regenerate(repo: Path, project: str) -> dict[str, Any]:
    repo = repo.resolve()
    metadata_files = _metadata_sources(repo, project)
    image_files = _image_sources(repo, project)

    opportunities: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    seen_assets: set[str] = set()

    # Prefer structured authenticated metadata.
    for meta_path in metadata_files:
        doc = _try_json(meta_path)
        if doc is None:
            continue
        records = _extract_records(doc)
        if not records:
            continue

        for idx, item in enumerate(records, 1):
            asset_path = _record_asset_path(item)
            asset_id = _record_asset_id(
                item,
                asset_path or f"{meta_path.stem}-{idx:03d}",
            )
            key = _norm(asset_id)
            if not key or key in seen_assets:
                continue

            category = _record_category(item, asset_path or str(meta_path))
            evidence = _record_evidence(item)

            # Plan/layout marketing must remain fail-closed when evidence is absent.
            plan_like = any(
                token in category.casefold()
                for token in ("unit layout", "floor plan", "layout", "typical floor", "master floor")
            )

            seen_assets.add(key)
            opportunities.append({
                "project_id": project,
                "id": asset_id,
                "category": category,
                "asset_ids": [asset_path or asset_id],
                "evidence": evidence,
                "visible_summary": str(
                    item.get("visible_summary")
                    or item.get("visual_summary")
                    or item.get("description")
                    or category
                ),
                "restrictions": (
                    ["PLAN_EVIDENCE_REQUIRED"] if plan_like and not evidence else []
                ),
            })
            provenance.append({
                "asset_id": asset_id,
                "metadata_source": str(meta_path),
                "asset_path": asset_path,
                "category": category,
                "evidence_count": len(evidence),
            })

    # Add authenticated source images not represented in structured metadata.
    for path in image_files:
        asset_id = str(path.relative_to(repo)).replace("\\", "/")
        key = _norm(asset_id)
        if key in seen_assets:
            continue
        category = _category_from_text(str(path))
        seen_assets.add(key)
        opportunities.append({
            "project_id": project,
            "id": asset_id,
            "category": category,
            "asset_ids": [str(path)],
            "evidence": [],
            "visible_summary": category,
            "restrictions": [],
        })
        provenance.append({
            "asset_id": asset_id,
            "metadata_source": None,
            "asset_path": str(path),
            "category": category,
            "evidence_count": 0,
        })

    if not opportunities:
        raise VisualOpportunityRegenerationError(
            f"no authenticated Beverly Hills source-image or structured asset metadata found; "
            f"metadata_files={len(metadata_files)} image_files={len(image_files)}"
        )

    out_dir = repo / "output" / "visual-opportunities" / project
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{project}-visual-opportunities.json"

    payload = {
        "schema_version": "department3.visual-opportunities.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project,
        "authority": {
            "authoritative": False,
            "role": "candidate_source",
            "consumer": "RealEstateStrategyBrain",
        },
        "source_policy": {
            "audit_sources_allowed": False,
            "release_sources_allowed": False,
            "provenance_sources_allowed": False,
            "network_used": False,
        },
        "metrics": {
            "metadata_files_scanned": len(metadata_files),
            "image_files_scanned": len(image_files),
            "opportunities": len(opportunities),
            "with_evidence": sum(1 for x in opportunities if x["evidence"]),
            "plan_like": sum(
                1 for x in opportunities
                if any(t in x["category"].casefold() for t in ("unit layout", "floor plan", "layout"))
            ),
        },
        "opportunities": opportunities,
        "provenance": provenance,
    }

    fingerprint = hashlib.sha256(
        json.dumps(payload["opportunities"], sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    payload["fingerprint"] = fingerprint

    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return {
        "path": out_path,
        "payload": payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="Beverly Hills")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    result = regenerate(Path(args.repo), args.project)
    payload = result["payload"]

    print("Department 3 Phase 4F.5 canonical visual opportunity regeneration completed")
    print(f"- Project: {args.project}")
    print(f"- Metadata files scanned: {payload['metrics']['metadata_files_scanned']}")
    print(f"- Image files scanned: {payload['metrics']['image_files_scanned']}")
    print(f"- Opportunities: {payload['metrics']['opportunities']}")
    print(f"- With evidence: {payload['metrics']['with_evidence']}")
    print(f"- Plan-like opportunities: {payload['metrics']['plan_like']}")
    print("- Meta writes: 0")
    print("- Instagram publish attempts: 0")
    print(f"- Output: {result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
