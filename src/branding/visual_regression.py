"""Read-only validation and explicit approval of canonical visual baselines."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from PIL import Image, ImageChops, ImageStat


BASELINE_SCHEMA_VERSION = "1.1.0"
EXACT_COMPARISON = "sha256_exact"


def baseline_from_manifest(
    manifest: dict[str, Any], *, approval_timestamp: str | None = None, baseline_path: str | None = None
) -> dict[str, Any]:
    approved_at = approval_timestamp or datetime.now(timezone.utc).isoformat()
    return {
        "baseline_schema_version": BASELINE_SCHEMA_VERSION,
        "status": "approved",
        "comparison_strategy": EXACT_COMPARISON,
        "normalized_pixel_tolerance": 0.0001,
        "renderer_version": manifest.get("module_version"),
        "renderer_schema_version": manifest.get("schema_version"),
        "project_fixture": manifest.get("project"),
        "approval_timestamp": approved_at,
        "baseline_manifest_path": baseline_path,
        "items": [
            {
                "status": "approved",
                "project_fixture": manifest.get("project"),
                "post_number": item["post_number"],
                "slide_number": item["slide_number"],
                "content_topic": item["content_topic"],
                "layout_family": item["renderer"],
                "renderer_version": manifest.get("module_version"),
                "schema_version": manifest.get("schema_version"),
                "source_asset_hash": item["source_sha256"],
                "output_hash": item["output_sha256"],
                "width": item["width"],
                "height": item["height"],
                "aspect_ratio": round(item["width"] / item["height"], 6),
                "approval_timestamp": approved_at,
                "baseline_reference_path": item["output_path"],
                "source_asset_path": item["source_image"],
            }
            for item in manifest.get("items", [])
        ],
    }


def compare_baseline(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Return stable metadata differences; an empty result is an exact pass."""
    differences: list[str] = []
    for field in ("renderer_version", "renderer_schema_version", "project_fixture"):
        if expected.get(field) != actual.get(field):
            differences.append(f"{field}: {expected.get(field)!r} != {actual.get(field)!r}")
    expected_items, actual_items = expected.get("items", []), actual.get("items", [])
    if len(expected_items) != len(actual_items):
        differences.append(f"item_count: {len(expected_items)} != {len(actual_items)}")
    fields = ("post_number", "slide_number", "content_topic", "layout_family", "source_asset_hash", "output_hash", "width", "height", "aspect_ratio")
    for index, (left, right) in enumerate(zip(expected_items, actual_items), 1):
        for field in fields:
            if left.get(field) != right.get(field):
                differences.append(f"item[{index}].{field}: {left.get(field)!r} != {right.get(field)!r}")
    return differences


def validate_baseline(root: Path, baseline: dict[str, Any]) -> list[str]:
    """Validate actual source/output files without mutating baseline or production data."""
    failures: list[str] = []
    baseline_path = baseline.get("baseline_manifest_path")
    # Whole inventory files may legitimately gain new, unapproved posts. The
    # approved contract is enforced per protected source/output item below, so
    # additions after the locked posts cannot silently alter their pixels.
    for item in baseline.get("items", []):
        label = f"{item['layout_family']} post-{item['post_number']:03d}/slide-{item['slide_number']:02d}"
        output = _resolve(root, item["baseline_reference_path"])
        source = _resolve(root, item["source_asset_path"])
        actual_hash = _sha(output) if output.is_file() else "missing"
        source_hash = _sha(source) if source.is_file() else "missing"
        dimensions: tuple[int, int] | None = None
        if output.is_file():
            with Image.open(output) as image:
                dimensions = image.size
        if actual_hash != item["output_hash"] or dimensions != (item["width"], item["height"]):
            failures.append(
                f"{label}: expected_hash={item['output_hash']} actual_hash={actual_hash} "
                f"comparison_score={'0.0' if actual_hash == item['output_hash'] else '1.0'} "
                f"baseline_path={baseline_path} newly_rendered_path={output}"
            )
        if source_hash != item["source_asset_hash"]:
            failures.append(f"{label}: source_hash expected={item['source_asset_hash']} actual={source_hash} source_path={source}")
    return failures


def update_baseline(
    manifest_path: Path, baseline_path: Path, *, root: Path, explicit: bool = False, approval_timestamp: str | None = None
) -> dict[str, Any]:
    """Create/replace a baseline only after an explicit developer-approved action."""
    if not explicit:
        raise PermissionError("Baseline updates require --update-visual-baseline")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative = str(baseline_path.relative_to(root)) if baseline_path.is_relative_to(root) else str(baseline_path)
    baseline = baseline_from_manifest(manifest, approval_timestamp=approval_timestamp, baseline_path=relative)
    content_plan = _resolve(root, manifest["content_plan"])
    project_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(manifest.get("project", "")).strip()).strip("-")
    ranking = root / "output" / "inventory" / f"source-image-ranking-{project_slug}.json"
    baseline["content_plan_reference"] = {"path": str(content_plan.relative_to(root)), "sha256": _sha(content_plan)}
    baseline["ranking_reference"] = {"path": str(ranking.relative_to(root)), "sha256": _sha(ranking)}
    failures = validate_baseline(root, baseline)
    if failures:
        raise ValueError("Cannot approve missing or mismatched files:\n" + "\n".join(failures))
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return baseline


def image_difference_ratio(left: Path, right: Path) -> float:
    """Normalized pixel difference for explicitly tolerance-based fixtures."""
    with Image.open(left) as left_raw, Image.open(right) as right_raw:
        first, second = left_raw.convert("RGB"), right_raw.convert("RGB")
        if first.size != second.size:
            return 1.0
        mean = ImageStat.Stat(ImageChops.difference(first, second)).mean
        return round(sum(mean) / (3 * 255), 8)


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or explicitly update canonical visual baselines.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--update-visual-baseline", action="store_true")
    args = parser.parse_args(argv)
    root, manifest_path, baseline_path = args.root.resolve(), args.manifest, args.baseline
    manifest_path = _resolve(root, str(manifest_path));baseline_path = _resolve(root, str(baseline_path))
    if args.update_visual_baseline:
        baseline = update_baseline(manifest_path, baseline_path, root=root, explicit=True)
        print(f"Approved {len(baseline['items'])} visual baselines: {baseline_path}")
        return 0
    if not baseline_path.is_file():
        parser.error("baseline does not exist; use --update-visual-baseline only after explicit approval")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    failures = validate_baseline(root, baseline)
    if failures:
        print("\n".join(failures))
        return 1
    print(f"PASS: {len(baseline['items'])} approved visual baselines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
