"""Export only fresh, source-bound production packages to the cloud publisher."""
from datetime import datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from src.content.visual_purpose import assess_visual_purpose, validate_overview_slides
from src.publishing.foundation import final_publish_errors, _slides, _timezone
from src.unit_plan_relationship import verify_unit_plan_relationship


def signed_job(item, package, context, hosting, *, account_id, day, signing_key, scheduled_at=None):
    errors = final_publish_errors(item, package, context)
    if errors:
        raise ValueError("Fresh final gates failed: " + "; ".join(errors))
    if len(signing_key) < 32:
        raise ValueError("Missing private signing key")
    when = datetime.fromisoformat(day + "T09:00:00").replace(tzinfo=_timezone("Asia/Baghdad"))
    if scheduled_at is not None:
        when=datetime.fromisoformat(scheduled_at)
        if when.tzinfo is None or when.astimezone(_timezone("Asia/Baghdad")).date().isoformat()!=day or item.get("scheduled_at_utc") is None or datetime.fromisoformat(item["scheduled_at_utc"])!=when:raise ValueError("Cloud timestamp does not match approved queue schedule")
        when=when.astimezone(_timezone("Asia/Baghdad"))
    scope = package.get("campaign_scope") or {"campaign_id":package.get("campaign_id")}
    if not account_id or not scope.get("campaign_id"):
        raise ValueError("Missing approved account or campaign")
    assets = {a["asset_id"]: a for a in context.get("visual_assets", [])}
    media, evidence = [], []
    for slide in _slides(package):
        source_ids = slide.get("source_asset_ids") or package.get("source_asset_ids", [])
        if len(source_ids) != 1 or source_ids[0] not in assets:
            raise ValueError("Cloud export requires one exact source per image")
        source = assets[source_ids[0]]
        image_hash = hashlib.sha256(Path(slide["image_path"]).read_bytes()).hexdigest()
        if image_hash != slide.get("image_hash"):
            raise ValueError("Production image changed")
        source_path = Path(source["source_path"])
        doc_path = Path(source["source_document_path"])
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != source.get("source_hash"):
            raise ValueError("Source image changed")
        if hashlib.sha256(doc_path.read_bytes()).hexdigest() != source.get("source_document_hash"):
            raise ValueError("Source document changed")
        if not source.get("source_page") or source.get("project_id") != package["project_id"]:
            raise ValueError("Incomplete source provenance")
        row = next((r for r in hosting.get("records", []) if r.get("package_id") == package["package_id"] and r.get("local_sha256") == image_hash), None)
        if not row or not row.get("verified_accessible"):
            raise ValueError("Hosted media is not verified")
        with urlopen(Request(row["public_url"], headers={"User-Agent": "InstagramAgentMediaHost/1.0"}), timeout=30) as response:
            if not response.headers.get("Content-Type", "").startswith("image/") or hashlib.sha256(response.read()).hexdigest() != image_hash:
                raise ValueError("Hosted image differs from production")
        media.append({"url": row["public_url"], "sha256": image_hash, "source_asset_id": source_ids[0]})
        evidence.append({k: source[k] for k in ("asset_id", "project_id", "source_hash", "source_document_hash", "source_page")})
    role = package["project_sequence"]["role"]
    cert = {"final_gate_passed": True, "package_hash": item["package_hash"], "source_evidence": evidence}
    if role == "project_overview":
        ordered=[assets[m["source_asset_id"]] for m in media]
        if validate_overview_slides(ordered,package["project_id"]):raise ValueError("Overview source approval or sequence is missing")
        cert["overview_source_approved"]=True
    if role == "project_site_plan":
        decisions = [assess_visual_purpose(assets[m["source_asset_id"]], role, package["project_id"]) for m in media]
        if any(d["status"] != "MATCH" for d in decisions):
            raise ValueError("Unverified project layout")
        cert["project_layout"] = {"verified": True, "representations": [d.get("representation", "technical_drawing") for d in decisions], "disclosures": [d.get("required_disclosure") for d in decisions if d.get("required_disclosure")]}
    if role == "unit_layouts":
        relationships = [verify_unit_plan_relationship(assets[m["source_asset_id"]]) for m in media]
        if any(r.get("status") != "VERIFIED" for r in relationships):
            raise ValueError("Canonical unit relationship is not verified")
        cert.update(canonical_relationships_verified=True, canonical_relationships=relationships)
    caption = package.get("master_caption") or package.get("caption") or {}
    job = {"account_id": account_id, "project_id": package["project_id"], "campaign_id": scope["campaign_id"], "scheduled_day": day, "scheduled_at": when.isoformat(), "valid_until": int((when + timedelta(hours=6)).timestamp()*1000), "publication_identity": item["publication_identity"], "semantic_creative_identity": item["semantic_creative_identity"], "package_type": package["package_type"], "role": role, "caption": caption["full_caption"], "media": media, "certification": cert}
    payload = json.dumps(job, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"payload": payload, "signature": hmac.new(signing_key.encode(), payload.encode(), hashlib.sha256).hexdigest()}
