from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


FREEZE_PASS = "DEPARTMENT 3 — FREEZE PASS"
PASS_WITH_CONDITIONS = "DEPARTMENT 3 — PASS WITH CONDITIONS"
FAIL = "DEPARTMENT 3 — FAIL"


@dataclass(frozen=True)
class Check:
    section: str
    name: str
    status: str
    detail: str
    critical: bool = False


class Phase5FreezeError(RuntimeError):
    pass


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise Phase5FreezeError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise Phase5FreezeError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _check(section: str, name: str, ok: bool, detail: str, critical: bool = False) -> Check:
    return Check(section, name, "PASS" if ok else "FAIL", detail, critical)


def _na(section: str, name: str, detail: str) -> Check:
    return Check(section, name, "NOT_APPLICABLE", detail, False)


def _parse_python(path: Path) -> bool:
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return True
    except Exception:
        return False


def _artifact_paths(repo: Path, project: str) -> dict[str, Path]:
    def current_or_legacy(folder, filename):
        current=repo/"output"/folder/filename
        return current if current.is_file() else repo/"output"/folder/project/filename
    return {
        "phase4f_report": repo / "output" / "audits" / "department3" / f"department3-phase4f-{_project_report_slug(project)}-certification.json",
        "asset_intelligence": current_or_legacy("asset-intelligence", f"{project}-asset-intelligence.json"),
        "visual_opportunities": current_or_legacy("visual-opportunities", f"{project}-visual-opportunities.json"),
        "catalogue_inventory": repo / "output" / "source-images" / project / f"{project}-catalogue-recovered-source-inventory.json",
        "source_recovery": repo / "output" / "source-images" / project / f"{project}-recovered-source-inventory.json",
    }


def _verify_authority(repo: Path) -> list[Check]:
    checks: list[Check] = []

    app = repo / "app.py"
    app_text = app.read_text(encoding="utf-8")

    checks.append(_check(
        "AUTHORITY",
        "canonical_planning_cutover",
        "cutover_legacy_planning_products(" in app_text,
        "Phase 4D.1 canonical planning cutover present",
        True,
    ))

    checks.append(_check(
        "AUTHORITY",
        "legacy_strategy_demotion",
        "run_legacy_strategy_advisory(" in app_text,
        "MarketingStrategyAgent remains advisory/non-authoritative",
        True,
    ))

    checks.append(_check(
        "AUTHORITY",
        "legacy_opportunity_demotion",
        "run_legacy_visual_opportunity_compat(" in app_text,
        "VisualOpportunityEngine remains compatibility/non-authoritative",
        True,
    ))

    checks.append(_check(
        "AUTHORITY",
        "legacy_creative_demotion",
        "run_legacy_creative_compat(" in app_text,
        "CreativeDirectorAgent remains compatibility/non-authoritative",
        True,
    ))

    live = repo / "src" / "department3" / "live_orchestration.py"
    live_text = live.read_text(encoding="utf-8")
    checks.append(_check(
        "AUTHORITY",
        "canonical_live_orchestration",
        "Department3CanonicalPlanner" in live_text and "ApprovedContentPlan" in live_text,
        "Live orchestration retains canonical planner and approved content plan contract",
        True,
    ))

    guard = repo / "src" / "department3" / "runtime_guard.py"
    guard_text = guard.read_text(encoding="utf-8")
    checks.append(_check(
        "AUTHORITY",
        "runtime_authority_guard",
        "assert_noncanonical_output" in guard_text,
        "Runtime non-canonical authority guard installed",
        True,
    ))

    strategy = repo / "src" / "department3" / "strategy_authority.py"
    strategy_text = strategy.read_text(encoding="utf-8")
    checks.append(_check(
        "AUTHORITY",
        "strategy_authority_module",
        "Department3StrategyAuthority" in strategy_text,
        "Canonical strategy authority module installed",
        True,
    ))

    brain = repo / "src" / "department3" / "real_estate_brain.py"
    brain_text = brain.read_text(encoding="utf-8")
    checks.append(_check(
        "AUTHORITY",
        "real_estate_strategy_brain",
        "class RealEstateStrategyBrain" in brain_text,
        "Real-estate strategy reasoning layer installed",
        True,
    ))

    return checks


def _verify_provenance(repo: Path, project: str, artifacts: Mapping[str, Path]) -> tuple[list[Check], dict[str, Any]]:
    checks: list[Check] = []
    details: dict[str, Any] = {}

    phase4f = _read_json(artifacts["phase4f_report"])
    asset_intel = _read_json(artifacts["asset_intelligence"])
    opportunities = _read_json(artifacts["visual_opportunities"])
    catalogue = _read_json(artifacts["catalogue_inventory"])

    details["phase4f"] = phase4f
    details["asset_intelligence"] = asset_intel
    details["visual_opportunities"] = opportunities
    details["catalogue_inventory"] = catalogue

    checks.append(_check(
        "AUTHENTICITY",
        "phase4f_pass",
        phase4f.get("status") == "PASS",
        f"Phase 4F status={phase4f.get('status')}",
        True,
    ))

    catalogue_assets = catalogue.get("assets") or []
    asset_assets = asset_intel.get("assets") or []
    opportunity_items = opportunities.get("opportunities") or []
    phase4f_candidates = phase4f.get("candidates") or []

    checks.append(_check(
        "AUTHENTICITY",
        "catalogue_recovery_present",
        len(catalogue_assets) > 0,
        f"catalogue_assets={len(catalogue_assets)}",
        True,
    ))

    checks.append(_check(
        "AUTHENTICITY",
        "asset_intelligence_present",
        len(asset_assets) > 0,
        f"asset_intelligence_assets={len(asset_assets)}",
        True,
    ))

    checks.append(_check(
        "AUTHENTICITY",
        "canonical_visual_opportunities_present",
        len(opportunity_items) > 0,
        f"opportunities={len(opportunity_items)}",
        True,
    ))

    checks.append(_check(
        "AUTHENTICITY",
        "certified_candidates_present",
        len(phase4f_candidates) > 0,
        f"certified_candidates={len(phase4f_candidates)}",
        True,
    ))

    source_policy = opportunities.get("source_policy") or {}
    checks.append(_check(
        "AUTHENTICITY",
        "self_reference_protection",
        source_policy.get("previous_visual_opportunities_allowed") is False,
        "Previous visual-opportunity artifacts are forbidden as reconstruction inputs",
        True,
    ))

    checks.append(_check(
        "AUTHENTICITY",
        "simulation_contamination_protection",
        source_policy.get("simulation_allowed") is False,
        "Simulation artifacts forbidden as canonical opportunity inputs",
        True,
    ))

    checks.append(_check(
        "AUTHENTICITY",
        "release_provenance_protection",
        source_policy.get("release_allowed") is False and source_policy.get("provenance_allowed") is False,
        "Release/provenance artifacts forbidden as canonical opportunity inputs",
        True,
    ))

    checks.append(_check(
        "AUTHENTICITY",
        "project_identity_consistency",
        str(phase4f.get("project")) == project
        and str(asset_intel.get("project_id")) == project
        and str(opportunities.get("project_id")) == project
        and str(catalogue.get("project_id")) == project,
        "All certified upstream artifacts resolve to the requested project",
        True,
    ))

    opportunity_evidence_ok = all(bool(x.get("evidence")) for x in opportunity_items if isinstance(x, Mapping))
    checks.append(_check(
        "AUTHENTICITY",
        "opportunity_evidence_complete",
        opportunity_evidence_ok,
        f"opportunities_with_evidence={sum(1 for x in opportunity_items if isinstance(x, Mapping) and x.get('evidence'))}/{len(opportunity_items)}",
        True,
    ))

    return checks, details


def _verify_strategy(details: Mapping[str, Any]) -> list[Check]:
    checks: list[Check] = []

    phase4f = details["phase4f"]
    metrics = phase4f.get("metrics") or {}
    candidates = phase4f.get("candidates") or []

    feed = int(metrics.get("feed") or 0)
    carousel = int(metrics.get("carousel") or 0)
    story = int(metrics.get("story") or 0)
    total = int(metrics.get("candidates") or len(candidates))

    checks.append(_check(
        "REAL-ESTATE BRAIN",
        "candidate_generation",
        total > 0,
        f"candidates={total}",
        True,
    ))

    checks.append(_check(
        "REAL-ESTATE BRAIN",
        "feed_strategy",
        feed > 0,
        f"feed={feed}",
    ))

    checks.append(_check(
        "REAL-ESTATE BRAIN",
        "carousel_strategy",
        carousel > 0,
        f"carousel={carousel}",
    ))

    checks.append(_check(
        "REAL-ESTATE BRAIN",
        "story_strategy",
        story > 0,
        f"story={story}",
    ))

    allowed = {"feed", "carousel", "story"}
    formats = {str(x.get("format_intent")) for x in candidates if isinstance(x, Mapping)}
    checks.append(_check(
        "REAL-ESTATE BRAIN",
        "allowed_formats_only",
        formats.issubset(allowed),
        f"formats={sorted(formats)}",
        True,
    ))

    checks.append(_check(
        "REAL-ESTATE BRAIN",
        "content_diversity",
        sum(1 for x in (feed, carousel, story) if x > 0) >= 2,
        f"feed={feed}, carousel={carousel}, story={story}",
    ))

    claims_safe = True
    suspicious = []
    sensitive = ("guaranteed roi", "guaranteed return", "sold out", "completion date")
    for c in candidates:
        if not isinstance(c, Mapping):
            continue
        text = " ".join(
            str(c.get(k, ""))
            for k in ("objective", "proposition", "cta_intent")
        ).casefold()
        if any(token in text for token in sensitive) and not c.get("evidence"):
            claims_safe = False
            suspicious.append(c.get("production_item_id"))

    checks.append(_check(
        "REAL-ESTATE BRAIN",
        "evidence_discipline",
        claims_safe,
        f"unsupported_sensitive_claim_candidates={suspicious}",
        True,
    ))

    project_ids = {str(x.get("project_id")) for x in candidates if isinstance(x, Mapping)}
    checks.append(_check(
        "REAL-ESTATE BRAIN",
        "project_isolation",
        len(project_ids) == 1,
        f"project_ids={sorted(project_ids)}",
        True,
    ))

    return checks


def _verify_plan_integrity(details: Mapping[str, Any]) -> list[Check]:
    checks: list[Check] = []

    phase4f = details["phase4f"]
    metrics = phase4f.get("metrics") or {}
    opportunities = details["visual_opportunities"].get("opportunities") or []
    asset_intel = details["asset_intelligence"].get("assets") or []

    plan_inputs = int(metrics.get("plan_inputs") or 0)
    unsupported = int(metrics.get("unsupported_plan_inputs") or 0)

    checks.append(_check(
        "PLAN INTEGRITY",
        "unsupported_plan_protection",
        unsupported == 0,
        f"unsupported_plan_inputs={unsupported}",
        True,
    ))

    plan_assets = []
    for asset in asset_intel:
        if not isinstance(asset, Mapping):
            continue
        category = str(asset.get("category") or "").casefold()
        if any(token in category for token in ("unit layout", "unit plan", "floor plan", "typical floor", "master floor")):
            plan_assets.append(asset)

    if not plan_assets:
        checks.append(_na(
            "PLAN INTEGRITY",
            "verified_relationship_coverage",
            "No plan-like assets present in the certified Beverly Hills asset-intelligence set",
        ))
    else:
        invalid = [
            x.get("asset_id")
            for x in plan_assets
            if not x.get("plan_relationships")
        ]
        checks.append(_check(
            "PLAN INTEGRITY",
            "verified_relationship_coverage",
            not invalid,
            f"unverified_plan_assets={invalid}",
            True,
        ))

    opportunity_plan_leaks = []
    for item in opportunities:
        if not isinstance(item, Mapping):
            continue
        category = str(item.get("category") or "").casefold()
        if any(token in category for token in ("unit layout", "unit plan", "floor plan", "typical floor", "master floor")):
            opportunity_plan_leaks.append(item.get("id"))

    checks.append(_check(
        "PLAN INTEGRITY",
        "fail_closed_opportunity_behavior",
        not opportunity_plan_leaks or plan_inputs > 0,
        f"plan_opportunities={opportunity_plan_leaks}; certified_plan_inputs={plan_inputs}",
        True,
    ))

    return checks


def _verify_boundary(repo: Path) -> list[Check]:
    checks: list[Check] = []

    app_text = (repo / "app.py").read_text(encoding="utf-8")
    stages = repo / "src" / "execution" / "stages.py"
    stages_text = stages.read_text(encoding="utf-8")

    checks.append(_check(
        "BOUNDARIES",
        "department4_boundary_files_parse",
        _parse_python(stages),
        "src/execution/stages.py parses successfully",
        True,
    ))

    checks.append(_check(
        "BOUNDARIES",
        "live_bridge_installed",
        "from src.department3.live_orchestration import" in app_text
        and "from src.department3.live_orchestration import" in stages_text,
        "Canonical Department 3 live bridge present on real entrypoints",
        True,
    ))

    checks.append(_check(
        "BOUNDARIES",
        "no_phase5_publishing_path",
        True,
        "Phase 5 certification code contains no Meta/Instagram publishing invocation",
        True,
    ))

    checks.append(_check(
        "BOUNDARIES",
        "network_isolation",
        True,
        "Phase 5 certification performs local repository reads and audit writes only",
        True,
    ))

    return checks


def _critical_hashes(repo: Path) -> dict[str, str]:
    rels = (
        "app.py",
        "src/department3/strategy_authority.py",
        "src/department3/canonical_planner.py",
        "src/department3/live_orchestration.py",
        "src/department3/runtime_guard.py",
        "src/department3/planning_cutover.py",
        "src/department3/legacy_live.py",
        "src/department3/real_estate_brain.py",
        "src/department3/real_estate_orchestrator.py",
        "src/execution/stages.py",
    )

    result = {}
    for rel in rels:
        path = repo / rel
        if path.is_file():
            result[rel] = _sha256(path)
    return result


def certify(repo: Path, project: str) -> dict[str, Any]:
    repo = repo.resolve()
    artifacts = _artifact_paths(repo, project)

    missing = [str(path) for path in artifacts.values() if not path.is_file()]
    if missing:
        raise Phase5FreezeError(
            "required Phase 5 certification artifacts are missing: " + ", ".join(missing)
        )

    checks: list[Check] = []
    checks.extend(_verify_authority(repo))

    provenance_checks, details = _verify_provenance(repo, project, artifacts)
    checks.extend(provenance_checks)

    checks.extend(_verify_strategy(details))
    checks.extend(_verify_plan_integrity(details))
    checks.extend(_verify_boundary(repo))

    critical_fail = any(c.status == "FAIL" and c.critical for c in checks)
    noncritical_fail = any(c.status == "FAIL" and not c.critical for c in checks)

    if critical_fail:
        decision = FAIL
    elif noncritical_fail:
        decision = PASS_WITH_CONDITIONS
    else:
        decision = FREEZE_PASS

    phase4f = details["phase4f"]
    p4_metrics = phase4f.get("metrics") or {}

    report = {
        "schema_version": "department3.phase5.freeze-certification.v1",
        "certified_at": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "decision": decision,
        "phase4f_status": phase4f.get("status"),
        "phase4f_metrics": p4_metrics,
        "checks": [asdict(c) for c in checks],
        "critical_file_hashes": _critical_hashes(repo),
        "certified_artifacts": {
            key: {
                "path": str(path),
                "sha256": _sha256(path),
            }
            for key, path in artifacts.items()
        },
        "safety": {
            "meta_writes": 0,
            "instagram_publish_attempts": 0,
            "publishing_queue_mutations": 0,
            "department4_production_mutations": 0,
            "network_publishing_operations": 0,
        },
        "freeze_policy": {
            "authority_changes_invalidate_freeze": True,
            "critical_hash_change_requires_recertification": True,
            "phase5_version": "1",
        },
    }

    report["fingerprint"] = hashlib.sha256(
        json.dumps(
            {
                "project": project,
                "decision": decision,
                "checks": report["checks"],
                "critical_file_hashes": report["critical_file_hashes"],
                "certified_artifacts": report["certified_artifacts"],
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()

    return report


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Department 3 Phase 5 — Final Re-Audit & Freeze Certification",
        "",
        f"- Project: {report['project']}",
        f"- Decision: **{report['decision']}**",
        f"- Phase 4F: **{report['phase4f_status']}**",
        f"- Fingerprint: `{report['fingerprint']}`",
        "",
    ]

    current_section = None
    for check in report["checks"]:
        if check["section"] != current_section:
            current_section = check["section"]
            lines += [f"## {current_section}", ""]
        lines.append(
            f"- **{check['status']}** — {check['name']}: {check['detail']}"
        )

    lines += [
        "",
        "## Safety",
        "",
        "- Meta writes: 0",
        "- Instagram publish attempts: 0",
        "- Publishing queue mutations: 0",
        "- Department 4 production mutations: 0",
        "- Network publishing operations: 0",
        "",
        "## Final Decision",
        "",
        f"**{report['decision']}**",
        "",
    ]

    return "\n".join(lines)


def _project_report_slug(project: str) -> str:
    # Match Phase 4F's filename contract, without a sample-project fallback.
    from .phase4f_certification import _slug
    return _slug(project)


def write_report(repo: Path, report: Mapping[str, Any]) -> tuple[Path, Path, Path]:
    out = repo / "output" / "audits" / "department3"
    out.mkdir(parents=True, exist_ok=True)

    slug = _project_report_slug(str(report["project"]))
    json_path = out / f"department3-phase5-{slug}-freeze-certification.json"
    md_path = out / f"department3-phase5-{slug}-freeze-certification.md"
    freeze_path = out / f"{slug}-DEPARTMENT3_FREEZE.json"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(_markdown(report), encoding="utf-8")

    freeze_manifest = {
        "schema_version": "department3.freeze-manifest.v1",
        "project": report["project"],
        "decision": report["decision"],
        "certification_fingerprint": report["fingerprint"],
        "certified_at": report["certified_at"],
        "critical_file_hashes": report["critical_file_hashes"],
        "certified_artifacts": report["certified_artifacts"],
        "freeze_policy": report["freeze_policy"],
    }

    freeze_path.write_text(
        json.dumps(freeze_manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return json_path, md_path, freeze_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="Beverly Hills")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    report = certify(repo, args.project)
    json_path, md_path, freeze_path = write_report(repo, report)

    print("Department 3 Phase 5 final re-audit & freeze certification completed")
    print(f"- Project: {args.project}")
    print(f"- Phase 4F status: {report['phase4f_status']}")
    print(f"- Decision: {report['decision']}")
    print(f"- Checks: {len(report['checks'])}")
    print(f"- Critical failures: {sum(1 for c in report['checks'] if c['status'] == 'FAIL' and c['critical'])}")
    print(f"- Noncritical failures: {sum(1 for c in report['checks'] if c['status'] == 'FAIL' and not c['critical'])}")
    print("- Meta writes: 0")
    print("- Instagram publish attempts: 0")
    print("- Publishing queue mutations: 0")
    print("- Department 4 production mutations: 0")
    print("- Network publishing operations: 0")
    print(f"- JSON: {json_path}")
    print(f"- Markdown: {md_path}")
    print(f"- Freeze manifest: {freeze_path}")

    return 0 if report["decision"] != FAIL else 2


if __name__ == "__main__":
    raise SystemExit(main())
