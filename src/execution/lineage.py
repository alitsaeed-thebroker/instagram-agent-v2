"""Deterministic artifact lineage for stale-stage rejection."""

from __future__ import annotations

import hashlib
import json
from typing import Any

LINEAGE_VERSION = "1.0.0"
_VOLATILE_KEYS = frozenset({
    "created_at", "generated_at", "updated_at", "validated_at",
    "started_at", "completed_at", "run_id",
})


def canonical_graph_fingerprint(knowledge: dict[str, Any]) -> str:
    raw = knowledge.get("canonical_intelligence")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("Canonical Department 2 relational intelligence is required for lineage")
    return _hash(_stable(raw))


def artifact_fingerprint(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Artifact payload must be an object")
    clean = {k: v for k, v in payload.items() if k not in {"lineage", "artifact_fingerprint"}}
    return _hash(_stable(clean))


def attach_lineage(
    payload: dict[str, Any],
    *,
    stage: str,
    canonical_fingerprint: str,
    parents: dict[str, str] | None = None,
    inputs: dict[str, str] | None = None,
) -> dict[str, Any]:
    value = dict(payload)
    value["lineage"] = {
        "lineage_version": LINEAGE_VERSION,
        "stage": stage,
        "canonical_department2_fingerprint": canonical_fingerprint,
        "parent_artifact_fingerprints": dict(sorted((parents or {}).items())),
        "input_artifact_fingerprints": dict(sorted((inputs or {}).items())),
    }
    value["artifact_fingerprint"] = artifact_fingerprint(value)
    return value


def validate_lineage(
    payload: dict[str, Any],
    *,
    expected_stage: str | None = None,
    canonical_fingerprint: str,
    parents: dict[str, str] | None = None,
) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "artifact is not an object"
    lineage = payload.get("lineage")
    if not isinstance(lineage, dict):
        return False, "lineage missing"
    if lineage.get("lineage_version") != LINEAGE_VERSION:
        return False, "lineage version changed"
    if expected_stage and lineage.get("stage") != expected_stage:
        return False, "lineage stage mismatch"
    if lineage.get("canonical_department2_fingerprint") != canonical_fingerprint:
        return False, "canonical Department 2 fingerprint changed"
    for name, expected in (parents or {}).items():
        actual = (lineage.get("parent_artifact_fingerprints") or {}).get(name)
        if actual != expected:
            return False, f"parent artifact fingerprint changed: {name}"
    if payload.get("artifact_fingerprint") != artifact_fingerprint(payload):
        return False, "artifact fingerprint mismatch"
    return True, "lineage valid"


def require_lineage(
    payload: dict[str, Any],
    *,
    expected_stage: str | None = None,
    canonical_fingerprint: str,
    parents: dict[str, str] | None = None,
) -> None:
    valid, reason = validate_lineage(
        payload,
        expected_stage=expected_stage,
        canonical_fingerprint=canonical_fingerprint,
        parents=parents,
    )
    if not valid:
        raise ValueError(f"Stale artifact rejected: {reason}")


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _stable(item)
            for key, item in sorted(value.items())
            if key not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_content_plan_lineage(content,knowledge,root,project):
    """Validate a canonical plan or a reviewed subset against its current parent."""
    from pathlib import Path
    fingerprint=canonical_graph_fingerprint(knowledge)
    stage=(content.get('lineage') or {}).get('stage')
    if stage=='department3-content-plan':
        require_lineage(content,expected_stage=stage,canonical_fingerprint=fingerprint)
        return
    canonical=json.loads((Path(root)/'output'/'content'/f'{project}-content-plan.json').read_text(encoding='utf-8'))
    if canonical.get('project_id')!=project or content.get('project_id')!=project:
        raise ValueError('Reviewed content parent belongs to another project')
    require_lineage(canonical,expected_stage='department3-content-plan',canonical_fingerprint=fingerprint)
    require_lineage(content,expected_stage='creative-reviewed-content-plan',canonical_fingerprint=fingerprint,parents={'canonical_content_plan':canonical['artifact_fingerprint']})
    ideas={x['content_idea_id']:x for x in canonical.get('content_ideas',[])}
    for idea in content.get('content_ideas',[]):
        clean={k:v for k,v in idea.items() if k!='creative_review'}
        if clean!=ideas.get(idea.get('content_idea_id')):
            raise ValueError('Reviewed content changed canonical facts or source selection')
