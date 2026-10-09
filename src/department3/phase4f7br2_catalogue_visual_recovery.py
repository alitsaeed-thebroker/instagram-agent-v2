from __future__ import annotations

import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

CATEGORY_RULES = (
    ("location", ("location", "map", "site location", "access", "nearby")),
    ("masterplan", ("masterplan", "master plan", "site plan", "overall plan")),
    ("unit layout", ("unit plan", "unit layout", "apartment plan", "office plan", "villa plan")),
    ("floor plan", ("floor plan", "typical floor", "master floor")),
    ("exterior", ("exterior", "facade", "façade", "elevation", "tower", "building")),
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
    "apartment plan",
    "office plan",
    "villa plan",
)

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


class CatalogueVisualRecoveryError(RuntimeError):
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


def _discover_catalogues(repo: Path, project: str) -> list[Path]:
    roots = [
        repo / "input" / project,
        repo / "input",
        repo / "source",
        repo / "sources",
        repo / "originals",
        repo / "uploads",
        repo / "data",
    ]

    found = []
    seen = set()

    for root in roots:
        if not root.exists():
            continue

        for path in root.rglob("*.pdf"):
            if not path.is_file() or _excluded(path):
                continue

            direct_project_root = root == repo / "input" / project
            if not direct_project_root and not _path_matches_project(path, project):
                continue

            rp = path.resolve()
            if rp in seen:
                continue

            seen.add(rp)
            found.append(path)

    # Prefer catalog/catalogue filenames, then larger files, then deterministic path.
    def key(path: Path):
        name = _norm(path.name)
        catalogue_rank = 0 if ("catalogue" in name or "catalog" in name) else 1
        return (catalogue_rank, -path.stat().st_size, str(path).casefold())

    return sorted(found, key=key)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _asset_id(data: bytes) -> str:
    return f"src_{_sha256_bytes(data)[:20]}"


def _category_from_context(text: str) -> tuple[str, str]:
    low = _norm(text)
    for category, tokens in CATEGORY_RULES:
        for token in tokens:
            if token in low:
                return category, f"context_token:{token}"
    return "project feature", "context_fallback"


def _is_plan_like(category: str, context: str) -> bool:
    combined = f"{category} {context}".casefold()
    return any(token in combined for token in PLAN_TOKENS)


def _guess_extension(raw_ext: str | None, data: bytes) -> str:
    ext = (raw_ext or "").casefold().lstrip(".")
    if ext in {"jpg", "jpeg"}:
        return ".jpg"
    if ext == "png":
        return ".png"
    if ext == "webp":
        return ".webp"

    # Signature fallback.
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:4] == b"RIFF" and b"WEBP" in data[:16]:
        return ".webp"
    return ".bin"


def _dimensions(data: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            return int(img.width), int(img.height)
    except Exception:
        return None, None


def _page_context_fitz(page: Any) -> str:
    try:
        return page.get_text("text") or ""
    except Exception:
        return ""


def _extract_with_fitz(pdf_path: Path) -> list[dict[str, Any]]:
    try:
        import fitz
    except Exception as exc:
        raise ImportError("PyMuPDF/fitz unavailable") from exc

    doc = fitz.open(pdf_path)
    recovered = []
    seen_page_xref = set()

    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            context = _page_context_fitz(page)

            images = page.get_images(full=True)
            for image_index, image_info in enumerate(images, 1):
                xref = int(image_info[0])
                key = (page_index, xref)
                if key in seen_page_xref:
                    continue
                seen_page_xref.add(key)

                extracted = doc.extract_image(xref)
                if not extracted or not extracted.get("image"):
                    continue

                data = extracted["image"]
                ext = _guess_extension(extracted.get("ext"), data)
                width = extracted.get("width")
                height = extracted.get("height")

                recovered.append({
                    "page_number": page_index + 1,
                    "image_index_on_page": image_index,
                    "extraction_method": "pymupdf_xref",
                    "xref": xref,
                    "raw_extension": ext,
                    "bytes": data,
                    "width": int(width) if width else None,
                    "height": int(height) if height else None,
                    "page_context": context,
                })
    finally:
        doc.close()

    return recovered


def _extract_with_pypdf(pdf_path: Path) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise ImportError("pypdf unavailable") from exc

    reader = PdfReader(str(pdf_path))
    recovered = []

    for page_index, page in enumerate(reader.pages):
        try:
            context = page.extract_text() or ""
        except Exception:
            context = ""

        images = getattr(page, "images", None)
        if not images:
            continue

        for image_index, image in enumerate(images, 1):
            data = getattr(image, "data", None)
            name = getattr(image, "name", "") or ""
            if not data:
                continue

            ext = _guess_extension(Path(name).suffix, data)
            width, height = _dimensions(data)

            recovered.append({
                "page_number": page_index + 1,
                "image_index_on_page": image_index,
                "extraction_method": "pypdf_page_images",
                "xref": None,
                "raw_extension": ext,
                "bytes": data,
                "width": width,
                "height": height,
                "page_context": context,
            })

    return recovered


def _extract_images(pdf_path: Path) -> tuple[list[dict[str, Any]], str]:
    errors = []

    try:
        return _extract_with_fitz(pdf_path), "pymupdf"
    except Exception as exc:
        errors.append(f"pymupdf:{exc}")

    try:
        return _extract_with_pypdf(pdf_path), "pypdf"
    except Exception as exc:
        errors.append(f"pypdf:{exc}")

    raise CatalogueVisualRecoveryError(
        "no supported PDF image extractor available; "
        + "; ".join(errors)
    )


def _valid_visual(data: bytes, width: int | None, height: int | None) -> bool:
    # Reject tiny icon/logo fragments but retain real catalogue visuals.
    if len(data) < 4096:
        return False

    if width is not None and height is not None:
        if width < 240 or height < 180:
            return False

    return True


def recover(repo: Path, project: str) -> tuple[Path, dict[str, Any]]:
    repo = repo.resolve()
    catalogues = _discover_catalogues(repo, project)

    if not catalogues:
        raise CatalogueVisualRecoveryError(
            f"no preserved PDF/catalogue found for project {project!r}"
        )

    catalogue = catalogues[0]
    extracted, backend = _extract_images(catalogue)

    out_dir = repo / "output" / "source-images" / project
    originals_dir = out_dir / "originals"
    plans_dir = out_dir / "plans"
    originals_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)

    assets = []
    duplicate_count = 0
    rejected_small = 0
    seen_hashes = {}

    for item in extracted:
        data = item["bytes"]
        sha = _sha256_bytes(data)

        if sha in seen_hashes:
            duplicate_count += 1
            continue

        width = item.get("width")
        height = item.get("height")

        if width is None or height is None:
            width, height = _dimensions(data)

        if not _valid_visual(data, width, height):
            rejected_small += 1
            continue

        seen_hashes[sha] = True

        context = item.get("page_context") or ""
        category, classification_source = _category_from_context(context)
        plan_like = _is_plan_like(category, context)

        asset_id = _asset_id(data)
        ext = item.get("raw_extension") or _guess_extension(None, data)
        target_dir = plans_dir if plan_like else originals_dir
        target_path = target_dir / f"{asset_id}{ext}"
        target_path.write_bytes(data)

        assets.append({
            "asset_id": asset_id,
            "source_pdf": str(catalogue),
            "source_pdf_sha256": _sha256_file(catalogue),
            "page_number": item["page_number"],
            "image_index_on_page": item["image_index_on_page"],
            "extraction_method": item["extraction_method"],
            "xref": item.get("xref"),
            "source_path": str(target_path),
            "sha256": sha,
            "bytes": len(data),
            "width": width,
            "height": height,
            "category": category,
            "classification_source": classification_source,
            "classification_confidence": (
                0.90 if classification_source != "context_fallback" else 0.25
            ),
            "plan_like": plan_like,
            "evidence": [
                {
                    "fact_id": f"pdf-page-{item['page_number']}",
                    "source_id": catalogue.name,
                    "confidence": 1.0,
                }
            ],
            "restrictions": (
                ["PLAN_RELATIONSHIP_REQUIRED"]
                if plan_like
                else []
            ),
            "authenticated": True,
        })

    if not assets:
        raise CatalogueVisualRecoveryError(
            f"catalogue found but no recoverable visual assets survived filtering; "
            f"pdf={catalogue}; extracted={len(extracted)}; rejected_small={rejected_small}"
        )

    category_counts: dict[str, int] = {}
    for asset in assets:
        category_counts[asset["category"]] = category_counts.get(asset["category"], 0) + 1

    metrics = {
        "catalogues_found": len(catalogues),
        "catalogue_used": str(catalogue),
        "pdf_backend": backend,
        "embedded_images_seen": len(extracted),
        "duplicates_removed": duplicate_count,
        "small_fragments_rejected": rejected_small,
        "assets_recovered": len(assets),
        "plan_like_assets": sum(1 for x in assets if x["plan_like"]),
        "assets_with_non_generic_category": sum(
            1 for x in assets if x["category"] != "project feature"
        ),
        "assets_with_page_evidence": len(assets),
        "category_counts": category_counts,
    }

    inventory_path = out_dir / f"{project}-catalogue-recovered-source-inventory.json"

    payload = {
        "schema_version": "department2.catalogue-recovered-source-inventory.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project,
        "authority": {
            "authoritative": False,
            "role": "authenticated_catalogue_visual_inventory",
        },
        "source_policy": {
            "catalogue_only": True,
            "simulation_allowed": False,
            "visual_opportunities_allowed": False,
            "release_allowed": False,
            "audit_allowed": False,
            "provenance_allowed": False,
            "network_used": False,
        },
        "metrics": metrics,
        "assets": assets,
        "source_documents": [
            {
                "path": str(catalogue),
                "sha256": _sha256_file(catalogue),
                "bytes": catalogue.stat().st_size,
                "type": "pdf",
            }
        ],
    }

    payload["fingerprint"] = hashlib.sha256(
        json.dumps(
            {
                "project": project,
                "catalogue": str(catalogue),
                "assets": assets,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()

    inventory_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return inventory_path, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="Beverly Hills")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    path, payload = recover(Path(args.repo), args.project)

    print("Department 3 Phase 4F.7B-R2 Beverly Hills catalogue embedded visual recovery completed")
    print(f"- Project: {args.project}")

    for key, value in payload["metrics"].items():
        print(f"- {key}: {value}")

    print("- Production authority changes: 0")
    print("- Meta writes: 0")
    print("- Instagram publish attempts: 0")
    print("- Network used: False")
    print(f"- Inventory: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
