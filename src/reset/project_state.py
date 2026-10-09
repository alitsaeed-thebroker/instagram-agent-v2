"""Project-scoped reset of generated pipeline state.

The reset deliberately treats input, configuration, source, and immutable
publication truth as separate security domains.  Only paths below ``output``
are candidates for removal; the publication ledger is read and verified but
never changed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from typing import Any

from src.core.file_manager import find_project_inputs
from src.publishing.ledger import PublicationLedger


class ProjectResetError(RuntimeError):
    pass


PRESERVED_ROOTS = ("input", "src", "tests", "prompts", ".git", ".env", "state/publishing")
GLOBAL_OUTPUT_ROOTS = {"brand-analysis", "health"}
RESET_CATEGORIES = {
    "department_1": {"inventory", "knowledge", "markdown", "reports"},
    "department_2": {"asset-intelligence", "content-inventory", "project-brand", "selected-images", "source-images", "visual-analysis", "visual-inventory"},
    "department_3": {"asset-selections", "asset-usage", "campaign-intelligence", "campaigns", "content", "content-memory", "creative-directions", "creative-intelligence", "creative-reviews", "performance", "performance-reviews", "plan-intelligence", "platform-strategy", "strategy", "visual-opportunities"},
    "department_4": {"brand-composition-plans", "branded-images", "corrections", "detail-enhanced", "image-processing-plans", "image-prompts", "produced-images", "production-manifests", "provenance", "qa", "releases", "review", "scene-plans", "shot-plans", "visual-directions", "visual-history"},
    "department_5": {"alt-text", "captions", "content-groups", "hashtags", "post-packages", "publishing", "runs", "social-review"},
    "cache": {"cache-metadata", "manifests"},
    "simulation": {"simulation"},
}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve_project(root: Path, requested: str) -> str:
    if not requested or any(token in requested for token in ("*", "?", "[", "]")):
        raise ProjectResetError("A literal --project value is required; wildcards are forbidden")
    projects = find_project_inputs(root / "input")
    matches = [item.name for item in projects if item.name.casefold() == requested.strip().casefold()]
    if len(matches) != 1:
        raise ProjectResetError(f"Project {requested!r} could not be resolved uniquely from input")
    return matches[0]


def _variants(project: str) -> set[str]:
    slug = re.sub(r"[^a-z0-9]+", "-", project.casefold()).strip("-")
    compact = re.sub(r"[^a-z0-9]+", "", project.casefold())
    return {project.casefold(), slug, compact}


def _path_matches(path: Path, project: str) -> bool:
    variants = _variants(project)
    values = [part.casefold() for part in path.parts]
    for value in values:
        normalized = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
        compact = re.sub(r"[^a-z0-9]+", "", value)
        if any(v and (v in value or v in normalized or v in compact) for v in variants):
            return True
    if path.suffix.casefold() == ".json":
        payload = _read(path)
        return str(payload.get("project_id") or payload.get("project") or "").casefold() == project.casefold()
    return False


def _published_truth(root: Path, project: str) -> dict[str, Any]:
    ledger = PublicationLedger(root)
    records = [row for row in ledger.records() if row.get("project_id", "").casefold() == project.casefold() and row.get("state") == "CONFIRMED_PUBLISHED"]
    manifest_path = root / "output" / "publishing" / f"{project}-publication-manifest.json"
    manifest = _read(manifest_path)
    receipts = [row for row in manifest.get("real_receipts", []) if row.get("status") in {"published", "published_with_warnings"} and row.get("published_media_id")]
    receipt_ids = {row.get("receipt_id") for row in receipts}
    identities = {row.get("publication_identity") or row.get("idempotency_key") for row in receipts}
    history = [row for row in manifest.get("publication_history", []) if row.get("receipt_id") in receipt_ids or row.get("status") in {"published", "published_with_warnings", "real_publication_already_recorded"}]
    queue = manifest.get("queue_items", [])
    protected_release_ids = {row.get("release_id") for row in queue if (row.get("publication_identity") or row.get("idempotency_key")) in identities and row.get("release_id")}
    return {"records": records, "receipts": receipts, "history": history, "protected_release_ids": protected_release_ids, "manifest_path": manifest_path}


def _collect(root: Path, project: str, protected_release_ids: set[str]) -> list[tuple[str, Path]]:
    output = (root / "output").resolve()
    candidates: list[tuple[str, Path]] = []
    for category, roots in RESET_CATEGORIES.items():
        for name in sorted(roots):
            base = output / name
            if not base.exists() or name in GLOBAL_OUTPUT_ROOTS:
                continue
            for path in sorted(base.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                if not (path.is_file() or path.is_symlink()):
                    continue
                if not _path_matches(path.relative_to(output), project):
                    continue
                if name == "publishing" and path.name == f"{project}-publication-manifest.json":
                    continue
                if name == "releases" and any(release in path.parts for release in protected_release_ids):
                    continue
                candidates.append((category, path.resolve()))
    unique: dict[Path, str] = {}
    for category, path in candidates:
        if not path.is_relative_to(output):
            raise ProjectResetError(f"Reset target escaped output root: {path}")
        unique[path] = category
    return sorted(((category, path) for path, category in unique.items()), key=lambda item: str(item[1]))


def _preserved_manifest(project: str, truth: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {"project_id": project, "release_id": None, "manifest_version": "reset-preserved-history-v1", "queue_items": [], "scheduled_items": [], "preflight_results": [], "mock_receipts": [], "real_receipts": truth["receipts"], "retries": [], "failures": [], "publication_history": truth["history"], "created_at": now, "updated_at": now, "reset_state": "historical_truth_only"}


def reset_project_derived_state(root: Path, requested_project: str, *, confirm: bool = False) -> dict[str, Any]:
    root = root.resolve()
    project = _resolve_project(root, requested_project)
    truth = _published_truth(root, project)
    before = {(row["publication_identity"], row.get("remote_media_id"), row.get("receipt_id")) for row in truth["records"]}
    targets = _collect(root, project, set(truth["protected_release_ids"]))
    by_category = {category: sum(item_category == category for item_category, _ in targets) for category in RESET_CATEGORIES}
    report = {"project_id": project, "mode": "confirmed" if confirm else "dry_run", "status": "planned", "files_removed": 0, "cache_entries_removed": by_category["cache"], "targets_by_category": by_category, "targets": [str(path.relative_to(root)) for _, path in targets], "preserved_categories": ["input project sources", "input brand resources", ".env and credentials", "application source/tests/prompts/Git", "global brand analysis", "immutable publication ledger", "successful real receipts and Instagram media IDs", "published release evidence"], "real_receipts_preserved": len(truth["receipts"]), "published_ledger_records_preserved": len(truth["records"]), "meta_write_requests": 0}
    if not confirm:
        return report
    failures: list[str] = []
    for _, path in targets:
        try:
            path.unlink(missing_ok=True)
            report["files_removed"] += 1
        except OSError as error:
            failures.append(f"{path}: {error}")
    # Remove empty project directories, never broad output roots.
    for base in (root / "output").iterdir():
        if not base.is_dir() or base.name in GLOBAL_OUTPUT_ROOTS:
            continue
        for directory in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                if not any(directory.iterdir()): directory.rmdir()
            except OSError: pass
    if truth["receipts"]:
        try: _write(truth["manifest_path"], _preserved_manifest(project, truth))
        except OSError as error: failures.append(f"preserved manifest: {error}")
    after = {(row["publication_identity"], row.get("remote_media_id"), row.get("receipt_id")) for row in PublicationLedger(root).records() if row.get("project_id", "").casefold() == project.casefold() and row.get("state") == "CONFIRMED_PUBLISHED"}
    if before != after:
        failures.append("immutable publication ledger changed during reset")
    report["status"] = "failed" if failures else "completed"
    report["failures"] = failures
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    audit = root / "archive" / "reset-audits" / f"{re.sub(r'[^A-Za-z0-9]+','-',project).strip('-')}-{report['completed_at'].replace(':','').replace('+','_')}.json"
    try: _write(audit, report); report["audit_path"] = str(audit.relative_to(root))
    except OSError as error: failures.append(f"audit: {error}"); report["status"] = "failed"
    if failures:
        raise ProjectResetError("Partial reset failure: " + "; ".join(failures))
    return report
