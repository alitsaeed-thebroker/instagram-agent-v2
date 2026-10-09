"""Cancel local operational schedules without touching publication truth or signed jobs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import re

ROOT = Path(__file__).resolve().parents[1]


def run():
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    recovery = ROOT / "output/cancellations" / stamp
    recovery.mkdir(parents=True, exist_ok=False)
    def read(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    def save(path, data):
        target = recovery / "before" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    protected = list(ROOT.rglob("publication-ledger.sqlite3")) + list(ROOT.rglob("*-publication-manifest.json"))
    jobs = sorted(p for p in (ROOT / "deployment/cloudflare/.private-migration/jobs").glob("*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", p.name))
    protected += jobs
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in protected}
    cloud_jobs = []
    for path in jobs:
        job = json.loads(read(path)["payload"])
        cloud_jobs.append({k: job.get(k) for k in ("project_id", "campaign_id", "publication_identity", "scheduled_at")})
    identities = {j["publication_identity"] for j in cloud_jobs}
    report = {"requested_at": now.isoformat(), "scope": "all projects and all scheduled posts",
              "files_changed": [], "cancelled_local_items": [], "uncertain_items_preserved": [],
              "cloud_jobs_requested_cancelled": cloud_jobs, "cloud_cancellation_confirmed": False,
              "cloud_blocker": "Cloudflare CLI is unauthenticated; live management changes unavailable",
              "meta_writes": 0, "published_posts_deleted": 0}
    terminal = {"cancelled", "superseded", "published", "published_with_warnings"}
    uncertain = {"publishing", "publishing_uncertain"}
    for base in (ROOT, ROOT / "output/restarts/2026-10-08"):
        config = base / "input/publishing/publishing-config.json"
        if config.is_file():
            data = read(config)
            data.update(default_mode="manual", manual_schedule={}, cancellation_requested_at=now.isoformat())
            data.pop("sequential_start_at", None)
            data.setdefault("worker", {})["enabled"] = False
            save(config, data)
            report["files_changed"].append(str(config.relative_to(ROOT)))
        cancelled_ids = set()
        for path in sorted((base / "output/publishing").glob("*-publishing-queue.json")):
            data = read(path)
            changed = False
            for item in data.get("items", []):
                if item.get("status") in terminal:
                    continue
                scheduled = any(item.get(k) for k in ("scheduled_at", "scheduled_at_local", "scheduled_at_utc"))
                targeted = scheduled or item.get("status") in {"scheduled", "retry_wait", "reserved"} or item.get("publication_identity") in identities
                if not targeted:
                    continue
                if item.get("status") in uncertain:
                    report["uncertain_items_preserved"].append(item.get("publication_identity"))
                    continue
                previous = {k: item.get(k) for k in ("status", "scheduled_at", "scheduled_at_local", "scheduled_at_utc", "next_retry_at")}
                item.setdefault("status_history", []).append({"from": item.get("status"), "to": "cancelled", "at": now.isoformat(), "reason": "USER_CANCEL_ALL_SCHEDULED_POSTS", "previous_schedule": previous})
                item.update(status="cancelled", scheduled_at=None, scheduled_at_local=None, scheduled_at_utc=None, next_retry_at=None, updated_at=now.isoformat())
                cancelled_ids.add(item["queue_item_id"])
                report["cancelled_local_items"].append({"file": str(path.relative_to(ROOT)), "queue_item_id": item["queue_item_id"], "publication_identity": item.get("publication_identity"), "previous": previous})
                changed = True
            if changed:
                from src.publishing.foundation import _queue_summary
                data["summary"] = _queue_summary(data["items"])
                data["updated_at"] = now.isoformat()
                save(path, data)
                report["files_changed"].append(str(path.relative_to(ROOT)))
        for path in sorted((base / "output/publishing").glob("*-schedule.json")):
            data = read(path)
            changed = False
            for item in data.get("items", []):
                if item.get("status") in terminal | uncertain:
                    continue
                if item.get("queue_item_id") in cancelled_ids or any(item.get(k) for k in ("scheduled_at", "scheduled_at_local", "scheduled_at_utc")):
                    item["cancelled_schedule"] = {k: item.get(k) for k in ("scheduled_at", "scheduled_at_local", "scheduled_at_utc")}
                    item.update(status="cancelled", scheduled_at=None, scheduled_at_local=None, scheduled_at_utc=None, cancellation_reason="USER_CANCEL_ALL_SCHEDULED_POSTS", cancelled_at=now.isoformat())
                    changed = True
            if changed:
                active = [i for i in data["items"] if i.get("status") not in terminal | uncertain]
                data.setdefault("summary", {}).update(scheduled_active=sum(bool(i.get("scheduled_at_utc")) for i in active), scheduler_active_input=len(active), unscheduled_active=sum(not i.get("scheduled_at_utc") for i in active), cancelled_ignored=sum(i.get("status")=="cancelled" for i in data["items"]))
                data["cancelled_at"] = now.isoformat()
                save(path, data)
                report["files_changed"].append(str(path.relative_to(ROOT)))
    config = ROOT / "deployment/cloudflare/wrangler.jsonc"
    data = read(config)
    data["vars"].update(LIVE_ENABLED="false", PUBLISH_DATES="", SCHEDULED_HOURS_UTC="")
    data["triggers"]["crons"] = []
    save(config, data)
    report["files_changed"].append(str(config.relative_to(ROOT)))
    report["cloud_config_disabled_locally_only"] = True
    report["protected_files_checked"] = len(hashes)
    report["changed_protected_files"] = [p for p, digest in hashes.items() if sha(ROOT / p) != digest]
    assert not report["changed_protected_files"]
    (recovery / "protected-before.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    (recovery / "cancellation-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(recovery / "cancellation-report.json"), "cancelled_local_items": len(report["cancelled_local_items"]), "cloud_cancellation_confirmed": False, "protected_files_unchanged": len(hashes)}, indent=2))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    run()
