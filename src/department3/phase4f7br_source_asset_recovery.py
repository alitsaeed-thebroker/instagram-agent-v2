from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
DOC_EXTS = {".pdf", ".txt", ".md", ".docx"}

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

CATEGORY_RULES = (
    ("location", ("location", "map", "site location", "access")),
    ("masterplan", ("masterplan", "master plan", "site plan")),
    ("unit layout", ("unit plan", "unit layout", "apartment plan", "office plan", "villa plan")),
    ("floor plan", ("floor plan", "typical floor", "master floor")),
    ("exterior", ("exterior", "facade", "façade", "elevation", "tower render", "building render")),
    ("interior", ("interior", "living room", "bedroom", "lobby", "kitchen", "office interior")),
    ("amenity", ("amenity", "pool", "gym", "park", "garden", "clubhouse", "playground", "lifestyle")),
    ("commercial", ("commercial", "retail", "shop", "office", "business")),
)

PLAN_TOKENS = (
    "unit layout",
    "unit plan",
    "floor plan",
    "typical floor",
    "master floor",
)

class SourceAssetRecoveryError(RuntimeError):
    pass


def _norm(value: Any) -> str:
    return (
        str(value or "")
        .casefold()
        .replace("\\", "/")
        .replace("-", " ")
        .replace("_", " ")
        .strip()
    )


def _project_tokens(project: str) -> tuple[str, ...]:
    return tuple(x for x in _norm(project).split() if x)


def _excluded(path: Path) -> bool:
    return bool({p.casefold() for p in path.parts} & EXCLUDED_PARTS)


def _path_matches_project(path: Path, project: str) -> bool:
    hay = _norm(str(path))
    tokens = _project_tokens(project)
    return bool(tokens) and all(t in hay for t in tokens)


def _category_from_text(text: str) -> str:
    low = _norm(text)
    for category, tokens in CATEGORY_RULES:
        if any(token in low for token in tokens):
            return category
    return "project feature"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _asset_id_for(path: Path) -> str:
    digest = _sha256(path)[:20]
    return f"src_{digest}"


def _original_input_roots(repo: Path, project: str) -> list[Path]:
    candidates = []

    direct = repo / "input" / project
    if direct.exists():
        candidates.append(direct)

    # Root-level input files whose names contain project identity.
    input_root = repo / "input"
    if input_root.exists():
        candidates.append(input_root)

    # Preserved source/import trees if they exist.
    for rel in (
        "source",
        "sources",
        "originals",
        "project-inputs",
        "uploads",
        "data",
    ):
        base = repo / rel
        if base.exists():
            candidates.append(base)

    result = []
    seen = set()
    for p in candidates:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            result.append(p)
    return result


def _discover_images(repo: Path, project: str) -> list[Path]:
    found = []
    seen = set()

    for root in _original_input_roots(repo, project):
        for path in root.rglob("*"):
            if (
                not path.is_file()
                or path.suffix.casefold() not in IMAGE_EXTS
                or _excluded(path)
            ):
                continue

            # Project-local directory or project identity in path.
            if root == repo / "input" / project or _path_matches_project(path, project):
                rp = path.resolve()
                if rp not in seen:
                    seen.add(rp)
                    found.append(path)

    return sorted(found)


def _discover_documents(repo: Path, project: str) -> list[Path]:
    found = []
    seen = set()

    for root in _original_input_roots(repo, project):
        for path in root.rglob("*"):
            if (
                not path.is_file()
                or path.suffix.casefold() not in DOC_EXTS
                or _excluded(path)
            ):
                continue

            if root == repo / "input" / project or _path_matches_project(path, project):
                rp = path.resolve()
                if rp not in seen:
                    seen.add(rp)
                    found.append(path)

    return sorted(found)


def _existing_image_metadata(repo: Path, project: str) -> dict[str, dict[str, Any]]:
    """Read only fresh/trusted current source-image metadata, if present.

    This is optional enrichment. It never reads simulation/release/audit/downstream trees.
    """
    roots = (
        repo / "output" / "source-images" / project,
        repo / "output" / "visual-assets" / project,
        repo / "output" / "plan-intelligence" / project,
    )

    index: dict[str, dict[str, Any]] = {}

    for base in roots:
        if not base.exists():
            continue

        for path in base.rglob("*.json"):
            if not path.is_file() or _excluded(path):
                continue

            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            records = []
            if isinstance(doc, list):
                records = [x for x in doc if isinstance(x, Mapping)]
            elif isinstance(doc, Mapping):
                for key in (
                    "assets",
                    "selected",
                    "selected_images",
                    "images",
                    "visual_assets",
                    "items",
                    "plans",
                ):
                    value = doc.get(key)
                    if isinstance(value, list):
                        records.extend(x for x in value if isinstance(x, Mapping))

            for item in records:
                asset_id = (
                    item.get("asset_id")
                    or item.get("source_asset_id")
                    or item.get("image_id")
                    or item.get("id")
                )
                asset_path = (
                    item.get("source_path")
                    or item.get("image_path")
                    or item.get("path")
                    or item.get("file")
                    or item.get("filename")
                )

                keys = []
                if asset_id:
                    keys.append(_norm(asset_id))
                if asset_path:
                    keys.append(_norm(Path(str(asset_path)).name))
                    keys.append(_norm(Path(str(asset_path)).stem))

                category = (
                    item.get("content_category")
                    or item.get("category")
                    or item.get("asset_type")
                    or item.get("classification")
                    or item.get("visual_type")
                )

                evidence = item.get("evidence") or item.get("evidence_refs") or item.get("facts") or []
                plan_relationship = (
                    item.get("plan_relationship")
                    or item.get("relationship")
                    or item.get("unit_relationship")
                    or item.get("floor_relationship")
                    or item.get("layout_relationship")
                )

                meta = {
                    "category": str(category).strip() if category else None,
                    "evidence": evidence if isinstance(evidence, list) else [],
                    "plan_relationship": plan_relationship,
                    "metadata_source": str(path),
                }

                for key in keys:
                    if key:
                        index[key] = meta

    return index


def recover(repo: Path, project: str) -> tuple[Path, dict[str, Any]]:
    repo = repo.resolve()

    images = _discover_images(repo, project)
    documents = _discover_documents(repo, project)
    metadata_index = _existing_image_metadata(repo, project)

    if not images and not documents:
        raise SourceAssetRecoveryError(
            f"no preserved project inputs found for {project!r}; "
            "expected project-local files under input/ or preserved source/upload trees"
        )

    assets = []

    for image in images:
        asset_id = _asset_id_for(image)

        meta = (
            metadata_index.get(_norm(asset_id))
            or metadata_index.get(_norm(image.name))
            or metadata_index.get(_norm(image.stem))
            or {}
        )

        category = meta.get("category") or _category_from_text(str(image))
        evidence = meta.get("evidence") or []
        plan_relationship = meta.get("plan_relationship")

        plan_like = any(token in category.casefold() for token in PLAN_TOKENS)

        assets.append({
            "asset_id": asset_id,
            "source_path": str(image),
            "source_filename": image.name,
            "sha256": _sha256(image),
            "bytes": image.stat().st_size,
            "category": category,
            "classification_source": (
                meta.get("metadata_source")
                if meta.get("category")
                else "path_inference"
            ),
            "evidence": evidence,
            "plan_relationship": plan_relationship,
            "restrictions": (
                ["PLAN_RELATIONSHIP_REQUIRED"]
                if plan_like and not plan_relationship
                else []
            ),
            "authenticated": True,
        })

    source_documents = []
    for doc in documents:
        source_documents.append({
            "path": str(doc),
            "filename": doc.name,
            "sha256": _sha256(doc),
            "bytes": doc.stat().st_size,
            "type": doc.suffix.casefold().lstrip("."),
        })

    out_dir = repo / "output" / "source-images" / project
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{project}-recovered-source-inventory.json"

    metrics = {
        "project_images_found": len(images),
        "project_documents_found": len(documents),
        "assets_recovered": len(assets),
        "assets_with_non_generic_category": sum(
            1 for x in assets if x["category"] != "project feature"
        ),
        "assets_with_existing_metadata_classification": sum(
            1 for x in assets if x["classification_source"] != "path_inference"
        ),
        "assets_with_evidence": sum(
            1 for x in assets if x["evidence"]
        ),
        "assets_with_plan_relationship": sum(
            1 for x in assets if x["plan_relationship"]
        ),
        "plan_like_assets": sum(
            1 for x in assets
            if any(token in x["category"].casefold() for token in PLAN_TOKENS)
        ),
    }

    payload = {
        "schema_version": "department2.recovered-source-inventory.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project,
        "authority": {
            "authoritative": False,
            "role": "recovered_authenticated_source_inventory",
        },
        "source_policy": {
            "original_input_only": True,
            "simulation_allowed": False,
            "visual_opportunities_allowed": False,
            "release_allowed": False,
            "audit_allowed": False,
            "provenance_allowed": False,
            "network_used": False,
        },
        "metrics": metrics,
        "assets": assets,
        "source_documents": source_documents,
    }

    payload["fingerprint"] = hashlib.sha256(
        json.dumps(
            {
                "project": project,
                "assets": assets,
                "documents": source_documents,
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

    path, payload = recover(Path(args.repo), args.project)

    print("Department 3 Phase 4F.7B-R Beverly Hills source asset recovery completed")
    print(f"- Project: {args.project}")

    for key, value in payload["metrics"].items():
        print(f"- {key}: {value}")

    print("- Production files modified: 0")
    print("- Meta writes: 0")
    print("- Instagram publish attempts: 0")
    print("- Network used: False")
    print(f"- Output: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
