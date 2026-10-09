"""Short-lived autonomous Department 5 publishing worker.

Windows Task Scheduler owns recurrence.  This module owns only one safe cycle;
it deliberately has no loop and no retry scheduler.
"""
from __future__ import annotations

import json
import os
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .controlled import controlled_publish
from .eligibility import select_next_eligible_publication
from .foundation import PublishingFoundation, _atomic_json, _lock, _read
from .ledger import LedgerUnavailable, PublicationLedger

EXIT_OK = 0
EXIT_CONFIGURATION = 2
EXIT_LEDGER = 10
EXIT_LOCKED = 11
EXIT_PUBLICATION = 20
EXIT_UNEXPECTED = 70


class WorkerError(RuntimeError):
    pass


def worker_config(root: Path) -> dict[str, Any]:
    path = root / "input" / "publishing" / "publishing-config.json"
    value = _read(path)
    config = value.get("worker", {})
    interval = config.get("poll_interval_minutes", 15)
    if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 1440:
        raise WorkerError("worker.poll_interval_minutes must be an integer from 1 to 1440")
    retention = config.get("log_retention", 30)
    if isinstance(retention, bool) or not isinstance(retention, int) or not 1 <= retention <= 365:
        raise WorkerError("worker.log_retention must be an integer from 1 to 365")
    return {"task_name": str(config.get("task_name", "InstagramAgent-PublishingWorker")),
            "poll_interval_minutes": interval, "log_retention": retention,
            "enabled_by_default": bool(config.get("enabled", True)), "timezone": value.get("timezone", "Asia/Baghdad")}


class WorkerState:
    """Non-authoritative controls, health and bounded operational logs."""
    def __init__(self, root: Path) -> None:
        self.directory = root / "state" / "publishing"
        self.control_path = self.directory / "worker-control.json"
        self.status_path = self.directory / "worker-status.json"
        self.logs = self.directory / "logs"

    def enabled(self, default: bool = True) -> bool:
        if not self.control_path.is_file():
            return default
        try:
            value = _read(self.control_path)
            return value.get("enabled") is True
        except (OSError, ValueError, json.JSONDecodeError):
            return False  # A corrupt pause control fails closed.

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        value = {"schema_version": "1.0.0", "enabled": bool(enabled), "updated_at": _now()}
        _atomic_json(self.control_path, value)
        return value

    def observe(self, result: dict[str, Any], retention: int) -> None:
        safe = _safe_result(result)
        previous: dict[str, Any] = {}
        try:
            if self.status_path.is_file(): previous = _read(self.status_path)
        except Exception:
            previous = {}
        status = {"schema_version": "1.0.0", "authoritative": False, **safe,
                  "last_invocation_at": safe["ended_at"],
                  "last_successful_invocation": safe["ended_at"] if safe["exit_code"] == 0 else previous.get("last_successful_invocation")}
        _atomic_json(self.status_path, status)
        self.logs.mkdir(parents=True, exist_ok=True)
        name = datetime.now(timezone.utc).strftime("worker-%Y%m%dT%H%M%S%fZ.json")
        _atomic_json(self.logs / name, {"authoritative": False, **safe})
        for stale in sorted(self.logs.glob("worker-*.json"), reverse=True)[retention:]:
            stale.unlink(missing_ok=True)


def discover_projects(root: Path) -> list[str]:
    directory = root / "output" / "publishing"
    suffix = "-publishing-queue.json"
    return sorted(path.name[:-len(suffix)] for path in directory.glob(f"*{suffix}") if path.name.endswith(suffix)) if directory.is_dir() else []


def ledger_precheck(root: Path, *, initialize_fresh: bool = False) -> str:
    """Validate the ledger or recognize a provably fresh publishing install."""
    ledger = PublicationLedger(root)
    try:
        ledger._validate()
        if initialize_fresh: ledger._mark_established()
        return "valid"
    except LedgerUnavailable:
        output = root / "output" / "publishing"
        state = root / "state" / "publishing"
        established = ((output.is_dir() and any(output.glob("*-publishing-queue.json"))) or
                       (output.is_dir() and any(output.glob("*-publication-manifest.json"))) or
                       (state / "ledger-established.json").is_file() or
                       (state / "migration-audit.json").exists() or
                       (state / "backups").is_dir() and any((state / "backups").glob("*.sqlite3")))
        if established: raise
        if initialize_fresh: ledger.initialize(fresh=True); return "initialized_fresh"
        return "valid_fresh_install"


def run_worker(root: Path, *, dry_run: bool = False, now: datetime | None = None,
               publisher: Callable[..., dict[str, Any]] = controlled_publish) -> dict[str, Any]:
    """Run one cycle and perform no more than one real publication transaction."""
    started = _now(); config = worker_config(root); state = WorkerState(root)
    base = {"started_at": started, "dry_run": dry_run, "meta_publication_writes": 0}
    if not state.enabled(config["enabled_by_default"]):
        result = {**base, "classification": "PAUSED", "published": False, "selected_publication_identity": None,
                  "candidate_count": 0, "exit_code": EXIT_OK, "ended_at": _now()}
        if not dry_run: state.observe(result, config["log_retention"])
        return result
    lock_path = root / "state" / "publishing" / ".worker.lock"
    try:
        with (nullcontext() if dry_run else _lock(lock_path, timeout=0.1)):
            ledger_health = ledger_precheck(root, initialize_fresh=not dry_run)
            ledger = PublicationLedger(root)
            if dry_run and ledger_health == "valid_fresh_install":
                ledger_rows = []
            else:
                ledger_rows = ledger.records()
            if any(row["state"] in {"PUBLISHING_UNCERTAIN", "RECONCILIATION_REQUIRED"} for row in ledger_rows):
                result = {**base, "classification": "RECONCILIATION_REQUIRED", "published": False,
                          "selected_publication_identity": None, "candidate_count": 0,
                          "exit_code": EXIT_LEDGER, "ended_at": _now()}
                if not dry_run: state.observe(result, config["log_retention"])
                return result
            queue_items: list[dict[str, Any]] = []
            projects = discover_projects(root)
            for project in projects:
                foundation = PublishingFoundation(project, root)
                queue = _read(foundation.queue_path)
                if queue.get("project_id") != project: raise WorkerError("Publishing queue project identity mismatch")
                foundation._inputs()  # Department 4 contract/release boundary.
                queue_items.extend(queue.get("items", []))
            receipts = [{**row, "status": "published", "published_at": row.get("publication_timestamp"),
                         "published_media_id": row.get("remote_media_id")} for row in ledger_rows if row["state"] == "CONFIRMED_PUBLISHED"]
            decision = select_next_eligible_publication({"items": queue_items}, receipts,
                now=now or datetime.now(timezone.utc), config=_publishing_config(root))
            qid = decision.get("selected_queue_item_id")
            selected = next((item for item in queue_items if item.get("queue_item_id") == qid), None)
            if not selected:
                result = {**base, "classification": "NO_ELIGIBLE_PUBLICATION", "published": False,
                          "selected_publication_identity": None, "candidate_count": len(queue_items),
                          "exit_code": EXIT_OK, "ended_at": _now()}
                if not dry_run: state.observe(result, config["log_retention"])
                return result
            identity = selected.get("publication_identity") or selected.get("idempotency_key")
            if dry_run:
                return {**base, "classification": "DRY_RUN_ELIGIBLE", "published": False,
                        "selected_publication_identity": identity, "selected_project": selected.get("project_id"),
                        "candidate_count": len(queue_items), "exit_code": EXIT_OK, "ended_at": _now()}
            outcome = publisher(root, str(selected["project_id"]), queue_item_id=qid, confirm=True)
            published = outcome.get("status") == "published"
            result = {**base, "classification": "PUBLISHED" if published else str(outcome.get("status", "BLOCKED")).upper(),
                      "published": published, "selected_publication_identity": identity,
                      "selected_project": selected.get("project_id"), "candidate_count": len(queue_items),
                      "meta_publication_writes": 1 if published else 0, "exit_code": EXIT_OK if published or outcome.get("status") == "already_published" else EXIT_PUBLICATION,
                      "ended_at": _now()}
            state.observe(result, config["log_retention"]); return result
    except LedgerUnavailable as error:
        result = {**base, "classification": "LEDGER_UNAVAILABLE", "safe_error": str(error), "published": False,
                  "selected_publication_identity": None, "candidate_count": 0, "exit_code": EXIT_LEDGER, "ended_at": _now()}
    except TimeoutError:
        result = {**base, "classification": "WORKER_LOCK_UNAVAILABLE", "published": False,
                  "selected_publication_identity": None, "candidate_count": 0, "exit_code": EXIT_LOCKED, "ended_at": _now()}
    except (OSError, ValueError, WorkerError) as error:
        result = {**base, "classification": "SAFETY_FAILURE", "safe_error": str(error), "published": False,
                  "selected_publication_identity": None, "candidate_count": 0, "exit_code": EXIT_CONFIGURATION, "ended_at": _now()}
    except Exception as error:
        result = {**base, "classification": "UNEXPECTED_FAILURE", "safe_error": type(error).__name__, "published": False,
                  "selected_publication_identity": None, "candidate_count": 0, "exit_code": EXIT_UNEXPECTED, "ended_at": _now()}
    try:
        if not dry_run: state.observe(result, config["log_retention"])
    except Exception: pass
    return result


def _publishing_config(root: Path) -> dict[str, Any]:
    return _read(root / "input" / "publishing" / "publishing-config.json")


def _safe_result(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"started_at", "ended_at", "dry_run", "classification", "published", "selected_publication_identity",
               "selected_project", "candidate_count", "meta_publication_writes", "exit_code", "safe_error"}
    return {key: value[key] for key in allowed if key in value}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
