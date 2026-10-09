"""Objective brand readiness scoring and approval lock management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .identity import approved_config_hash
from .validation import validate_brand_config

READINESS_VERSION = "20.1.0"
URL = re.compile(r"^(?:https?://)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:[/#?].*)?$")


@dataclass(frozen=True)
class ReadinessResult:
    path: Path
    report: dict[str, Any]


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elements(config: dict[str, Any], identity: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    confirmed = [f"company.{name}" for name in ("official_name", "display_name", "website") if config.get("company", {}).get(name)]
    derived = [f"visual_identity.colors.{name}" for name in ("primary", "secondary", "accent") if config.get("visual_identity", {}).get("colors", {}).get(name, {}).get("status") == "logo_derived"]
    system = ["visual_identity.typography"] if identity.get("typography_system", {}).get("status") == "system_selected" else []
    return confirmed, derived, system


def run_brand_readiness_validator(root: Path) -> ReadinessResult:
    config_path = root / "input" / "brand" / "brand-config.json"
    identity_path = root / "output" / "brand-analysis" / "domus-erbil-brand-identity.json"
    output = root / "output" / "brand-analysis" / "domus-erbil-brand-readiness.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    validation = validate_brand_config(config)
    company, visual = config.get("company", {}), config.get("visual_identity", {})
    blocking: list[str] = list(validation.errors)
    if not company.get("official_name") or not company.get("display_name"): blocking.append("Official company/display name is invalid.")
    if not URL.fullmatch(str(company.get("website", ""))): blocking.append("Website is invalid.")
    logo = identity.get("preferred_logo", {})
    logo_path = Path(logo.get("path", "")) if logo.get("path") else None
    actual_logo_hash = hashlib.sha256(logo_path.read_bytes()).hexdigest() if logo_path and logo_path.is_file() else None
    live_logo_valid = bool(logo.get("valid") and logo.get("hash_verified") and actual_logo_hash == logo.get("sha256"))
    if not live_logo_valid: blocking.append("Preferred logo is missing, invalid, changed, or its hash is not verified.")
    palette = identity.get("palette", {})
    safe_policy = bool(palette.get("primary") or palette.get("neutrals")) and bool(identity.get("contrast_recommendations") or palette.get("neutrals"))
    if not safe_policy: blocking.append("No safe usable color policy exists.")
    typography = identity.get("typography_system", {})
    if typography.get("status") != "system_selected" or not typography.get("production_safe"): blocking.append("Typography system is not production safe.")
    rules = identity.get("language_typography_rules", {})
    rtl_ready = all(rules.get(lang, {}).get("direction") == "rtl" for lang in ("Arabic", "Kurdish Sorani"))
    warnings = ["No official company font is supplied; production-safe system typography is selected."]
    if visual.get("colors", {}).get("status") == "logo_derived": warnings.append("Colors are logo-derived, not officially documented corporate colors.")
    optional = []
    for key, label in (("phone_numbers", "phone"), ("email_addresses", "email"), ("social_handles", "social handles"), ("address", "address")):
        if not company.get(key): optional.append(label); warnings.append(f"Missing optional {label}.")
    # Category scores are all-or-nothing where integrity matters, partial only for optional contact.
    scores = {
        "official_identity": 20 if company.get("official_name") and company.get("display_name") else 0,
        "logo_integrity": 25 if live_logo_valid else 0,
        "color_system": 15 if safe_policy else 0,
        "typography_system": 15 if typography.get("production_safe") else 0,
        "website_contact_readiness": (6 if URL.fullmatch(str(company.get("website", ""))) else 0) + sum(bool(company.get(k)) for k in ("phone_numbers", "email_addresses", "social_handles", "address")),
        "multilingual_readiness": 10 if rtl_ready else 0,
        "config_provenance_completeness": 5 if validation.valid and identity.get("provenance") else 0,
    }
    score = int(sum(scores.values()))
    numeric = "ready" if score >= 95 else "ready_with_warnings" if score >= 85 else "manual_review_required" if score >= 70 else "blocked"
    status = "blocked" if blocking else numeric
    confirmed, derived, system = _elements(config, identity)
    approval = dict(config.get("approval", {}))
    current_hash = approved_config_hash(config)
    stored_hash, stored_logo = approval.get("approved_config_hash"), approval.get("approved_logo_hash")
    stale = bool(approval.get("locked") and (stored_hash != current_hash or stored_logo != actual_logo_hash))
    if stale:
        approval.update(status="revoked", locked=False)
        note = "Approval revoked: approved configuration or logo hash changed."
        approval.setdefault("notes", []).append(note)
        config["approval"] = approval; _write(config_path, config)
        warnings.append(note)
    report = {"brand_id": config.get("brand_id", "domus-erbil"), "readiness_status": status, "score": score,
              "score_breakdown": scores, "blocking_issues": list(dict.fromkeys(blocking)), "warnings": list(dict.fromkeys(warnings)),
              "confirmed_elements": confirmed, "derived_elements": derived, "system_selected_elements": system,
              "missing_optional_elements": optional, "approval": {**approval, "hash_current": not stale, "current_config_hash": current_hash},
              "recommended_next_action": "Resolve blocking issues and rerun validation." if blocking else "Review warnings, then approve the brand." if approval.get("status") != "approved" else "Brand is approved and locked for production use.",
              "validator_version": READINESS_VERSION, "created_at": _now()}
    _write(output, report)
    return ReadinessResult(output, report)


def approve_brand(root: Path, *, approved_by: str = "local_user") -> ReadinessResult:
    result = run_brand_readiness_validator(root)
    if result.report["readiness_status"] not in {"ready", "ready_with_warnings"}:
        raise ValueError(f"Brand cannot be approved while readiness is {result.report['readiness_status']}.")
    config_path = root / "input" / "brand" / "brand-config.json"
    identity_path = root / "output" / "brand-analysis" / "domus-erbil-brand-identity.json"
    config = json.loads(config_path.read_text(encoding="utf-8")); identity = json.loads(identity_path.read_text(encoding="utf-8"))
    approval = config.setdefault("approval", {})
    approval.update(status="approved", locked=True, approved_by=approved_by, approved_at=_now(),
                    approved_config_hash=None, approved_logo_hash=identity.get("preferred_logo", {}).get("sha256"))
    # Approval bookkeeping is normalized by approved_config_hash, so this is stable after assignment.
    approval["approved_config_hash"] = approved_config_hash(config)
    _write(config_path, config)
    return run_brand_readiness_validator(root)
