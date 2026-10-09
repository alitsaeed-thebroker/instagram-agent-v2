"""Read-only contract audit of the isolated recovery's D3 through D5 outputs."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.publishing.foundation import _slides


def run():
    recovery = ROOT / "output/recovery/20261009T193500Z"
    output = recovery / "beverly-isolated/output"
    def read(relative):
        return json.loads((output / relative).read_text(encoding="utf-8"))
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    manifest = read("source-images/Beverly Hills/manifest.json")
    assert manifest["project"] == "Beverly Hills"
    extracted = {a["asset_id"]: a for a in manifest["assets"]}
    assets = {a["asset_id"]: a for a in read("asset-intelligence/Beverly Hills-asset-intelligence.json")["assets"]}
    assert set(assets) == set(extracted)
    ideas = read("content/Beverly Hills-content-plan.json")["content_ideas"]
    overview = next(i for i in ideas if i["content_category"] == "project_overview")
    scenes = read("scene-plans/Beverly Hills-scene-plans.json")["scene_plans"]
    plan = next(p for p in scenes if p["content_idea_id"] == overview["content_idea_id"])
    assert [s["reusable_asset_ids"] for s in sorted(plan["scenes"], key=lambda s: s["sequence"])] == [[i] for i in overview["selected_source_asset_ids"]]
    packages = read("post-packages/Beverly Hills-post-packages.json")["packages"]
    media_checked = 0
    for package in packages:
        assert package["project_id"] == "Beverly Hills"
        for slide in _slides(package):
            assert sha(slide["image_path"]) == slide["image_hash"]
            source_ids = slide.get("source_asset_ids", package.get("source_asset_ids", []))
            assert source_ids
            for aid in source_ids:
                asset = assets[aid]
                assert asset["project_id"] == "Beverly Hills"
                assert sha(asset["source_path"]) == asset["source_hash"]
                assert asset["source_hash"] == extracted[aid]["sha256"]
                assert sha(asset["source_document_path"]) == asset["source_document_hash"]
            media_checked += 1
    package = next(p for p in packages if p["content_idea_id"] == overview["content_idea_id"])
    assert [s["source_asset_ids"] for s in package["slides"]] == [[i] for i in overview["selected_source_asset_ids"]]
    queue = read("publishing/Beverly Hills-publishing-queue.json")["items"]
    assert len(queue) == len(packages)
    assert all(not i.get("scheduled_at") and not i.get("scheduled_at_utc") and i["attempt_count"] == 0 for i in queue)
    assert all(i["status"] in {"queued", "blocked"} for i in queue)
    review = read("social-review/Beverly Hills-social-review.json")
    overview_review = next(p for p in review["packages"] if p["package_id"] == package["package_id"])
    report = {
        "status": "PASSED", "scope": "input/output contracts and byte provenance; no approval or live certification",
        "packages": len(packages), "media_checked": media_checked,
        "queue_statuses": dict(Counter(i["status"] for i in queue)),
        "overview_source_order": overview["selected_source_asset_ids"],
        "overview_package_id": package["package_id"],
        "overview_social_readiness": overview_review["readiness"],
        "overview_semantic_warnings": overview_review["semantic_warnings"],
        "overview_marketing_comprehension": overview_review["marketing_comprehension"],
        "queue_blockers": [{"package_id": i["package_id"], "errors": i.get("errors", [])} for i in queue if i["status"] == "blocked"],
        "schedules_created": 0, "meta_writes": 0, "publication_certified": False,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    (recovery / "downstream-contract-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run()
