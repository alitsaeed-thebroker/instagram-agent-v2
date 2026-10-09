"""Stable stage graph, cache validation, and resumable run manifests."""

from __future__ import annotations

from src.department3.live_orchestration import LiveDepartment3Orchestrator, quarantine_legacy_result
from src.department3.runtime_guard import assert_noncanonical_output

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
import time
from typing import Any, Iterable

from src.utils.config import CACHE_METADATA_OUTPUT_DIRECTORY, MANIFESTS_OUTPUT_DIRECTORY, PROJECT_VISUAL_MODE

STAGE_ORDER = (
    "discover", "document-analysis", "text-extraction", "knowledge-extraction",
    "knowledge-fusion", "knowledge-evaluation", "visual-extraction",
    "asset-intelligence", "deep-source-analysis", "source-image-ranking", "project-brand-identity", "visual-inventory", "creative-intelligence", "campaign-intelligence", "marketing-strategy",
    "visual-opportunities", "campaign-planner", "content-planner", "branded-content",
    "creative-director", "scene-planner", "shot-planner", "image-processing-planner", "image-prompt-generator",
    "visual-art-director", "detail-preservation-enhancer", "deterministic-image-processor",
    "brand-composer", "image-output-qa", "branded-image-qa", "creative-visual-qa", "self-correction",
    "provenance-audit", "production-quality-report", "release-manager", "content-grouping-analyzer", "caption-generator", "hashtag-generator",
    "alt-text-generator", "post-package-builder", "post-package-qa", "social-content-review", "publishing-queue", "scheduling-engine", "publish-preflight", "mock-platform-adapter", "meta-platform-adapter", "publication-manifest", "production-manifest", "review-gallery",
)
DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "discover": (), "document-analysis": ("discover",), "text-extraction": ("document-analysis",),
    "knowledge-extraction": ("text-extraction",), "knowledge-fusion": ("knowledge-extraction",),
    "knowledge-evaluation": ("knowledge-fusion",), "visual-extraction": ("discover",),
    "asset-intelligence": ("visual-extraction",), "deep-source-analysis": ("asset-intelligence",), "source-image-ranking": ("asset-intelligence", "deep-source-analysis"),
    "project-brand-identity": ("visual-extraction","knowledge-fusion"), "branded-content": ("source-image-ranking","project-brand-identity","content-planner"),
    "visual-inventory": ("asset-intelligence", "source-image-ranking"),
    "creative-intelligence": ("knowledge-evaluation", "visual-inventory"),
    "campaign-intelligence": ("creative-intelligence",),
    "marketing-strategy": ("knowledge-fusion", "visual-inventory", "creative-intelligence", "campaign-intelligence"),
    "visual-opportunities": ("knowledge-fusion", "marketing-strategy", "visual-inventory"),
    "campaign-planner": ("visual-opportunities", "marketing-strategy", "campaign-intelligence"),
    "content-planner": ("campaign-planner", "visual-opportunities", "visual-inventory", "knowledge-fusion"),
    "creative-director": ("content-planner",), "scene-planner": ("creative-director",),
    "shot-planner": ("scene-planner",), "image-processing-planner": ("shot-planner",),
    "image-prompt-generator": ("image-processing-planner",),
    "visual-art-director": ("image-prompt-generator", "content-planner", "project-brand-identity"),
    "detail-preservation-enhancer": ("visual-art-director",),
    "deterministic-image-processor": ("detail-preservation-enhancer",),
    "brand-composer": ("visual-art-director",), "image-output-qa": ("brand-composer",),
    "branded-image-qa": ("image-output-qa",),
    "creative-visual-qa": ("branded-image-qa",), "self-correction": ("creative-visual-qa",),
    "provenance-audit": ("self-correction",), "production-quality-report": ("provenance-audit",),
    "release-manager": ("production-quality-report",),
    "content-grouping-analyzer": ("release-manager",), "caption-generator": ("content-grouping-analyzer",), "hashtag-generator": ("caption-generator",), "alt-text-generator": ("caption-generator",),
    "post-package-builder": ("hashtag-generator","alt-text-generator"), "post-package-qa": ("post-package-builder",),
    "social-content-review": ("post-package-qa",),
    "publishing-queue": ("social-content-review",), "scheduling-engine": ("publishing-queue",),
    "publish-preflight": ("scheduling-engine",), "mock-platform-adapter": ("publish-preflight",),
    "meta-platform-adapter": (),
    "publication-manifest": ("mock-platform-adapter",),
    "production-manifest": ("image-output-qa", "post-package-qa"), "review-gallery": ("production-manifest",),
}
STATUSES = {"pending", "running", "completed", "completed_with_warnings", "skipped_cached", "skipped_not_requested", "failed", "stale"}
EXECUTION_STATES = {"executed", "skipped_cached", "skipped_not_requested", "skipped_valid_prerequisite", "failed", "blocked", "stale", "pending"}
AI_POWERED_STAGES = {"knowledge-extraction", "asset-intelligence", "marketing-strategy", "campaign-planner", "content-planner", "creative-director", "scene-planner"}

# Single source of truth for platform-strategy cache and execution semantics.
EARLIEST_PLATFORM_DEPENDENT_STAGE = "campaign-planner"
PLATFORM_INDEPENDENT_STAGES = frozenset(STAGE_ORDER[:STAGE_ORDER.index(EARLIEST_PLATFORM_DEPENDENT_STAGE)])
PLATFORM_DEPENDENT_STAGES = frozenset(STAGE_ORDER[STAGE_ORDER.index(EARLIEST_PLATFORM_DEPENDENT_STAGE):])
EXPLICIT_ONLY_STAGES = frozenset({"branded-content", "detail-preservation-enhancer", "deterministic-image-processor"})


def validate_stage_graph() -> None:
    """Fail fast when a dependency is unknown, cyclic, or ordered after its consumer."""
    if set(DEPENDENCIES) != set(STAGE_ORDER):
        missing = set(STAGE_ORDER) - set(DEPENDENCIES)
        extra = set(DEPENDENCIES) - set(STAGE_ORDER)
        raise ValueError(f"Invalid stage graph keys: missing={sorted(missing)}, extra={sorted(extra)}")
    positions = {stage: index for index, stage in enumerate(STAGE_ORDER)}
    for stage, parents in DEPENDENCIES.items():
        for parent in parents:
            if parent not in positions:
                raise ValueError(f"Stage '{stage}' has unknown dependency '{parent}'")
            if positions[parent] >= positions[stage]:
                raise ValueError(f"Stage '{stage}' has impossible forward dependency '{parent}'")
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(stage: str) -> None:
        if stage in visiting: raise ValueError(f"Stage dependency cycle detected at '{stage}'")
        if stage in visited: return
        visiting.add(stage)
        for parent in DEPENDENCIES[stage]: visit(parent)
        visiting.remove(stage); visited.add(stage)
    for stage in STAGE_ORDER: visit(stage)


validate_stage_graph()


@dataclass(frozen=True)
class StageSelection:
    requested: tuple[str, ...]
    forced: frozenset[str]


def descendants(stage: str) -> set[str]:
    result = {stage}
    changed = True
    while changed:
        changed = False
        for candidate, parents in DEPENDENCIES.items():
            if candidate not in result and any(parent in result for parent in parents):
                result.add(candidate); changed = True
    return result


def ancestors(stage: str) -> set[str]:
    """Return the transitive prerequisite set from the canonical stage graph."""
    result:set[str]=set();pending=list(DEPENDENCIES.get(stage,()))
    while pending:
        current=pending.pop()
        if current in result:continue
        result.add(current);pending.extend(DEPENDENCIES.get(current,()))
    return result


def select_stages(*, stage: str | None = None, from_stage: str | None = None, force_stage: str | None = None, force_all: bool = False) -> StageSelection:
    for value in (stage, from_stage, force_stage):
        if value and value not in STAGE_ORDER: raise ValueError(f"Unknown stage '{value}'. Use --list-stages.")
    if stage and from_stage: raise ValueError("--stage and --from-stage cannot be used together")
    if force_all:
        requested, forced = STAGE_ORDER, frozenset(STAGE_ORDER)
    elif force_stage:
        requested, forced = (force_stage,), frozenset({force_stage})
    elif stage:
        requested, forced = (stage,), frozenset()
    else:
        requested = tuple(
            name for name in STAGE_ORDER
            if name not in EXPLICIT_ONLY_STAGES and (not from_stage or name in descendants(from_stage))
        )
        forced = frozenset()
    return StageSelection(requested, forced)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def hash_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class StageCache:
    """Persist sidecar metadata so existing strict business artifacts stay compatible."""

    def __init__(self, project_id: str, source_files: Iterable[Path]) -> None:
        self.project_id = project_id
        self.source_hashes = {str(p.resolve()): sha256_file(p) for p in sorted(source_files) if p.is_file()}
        self.manifest_path = MANIFESTS_OUTPUT_DIRECTORY / f"{project_id}-run-manifest.json"
        self.manifest = self._load_manifest()
        self.forced_stage: str | None = None
        self._stage_started: dict[str, float] = {}
        self.runtime_records: dict[str, dict[str, Any]] = {}

    def reset_runtime_accounting(self, *, requested_mode: str, requested_stage: str | None, stage_forced: bool) -> None:
        self.runtime_records = {}
        self.manifest["stage_statuses"] = {stage: "pending" for stage in STAGE_ORDER}
        self.manifest["output_paths"] = {}
        self.manifest["cache_keys"] = {}
        self.manifest.update(requested_mode=requested_mode, requested_stage=requested_stage, stage_forced=stage_forced,
                             upstream_artifacts_reused=[], downstream_marked_stale=[], stages_actually_executed=[],
                             stage_records=[], project_summary={})
        self._save()

    def _record_runtime(self, stage: str, state: str, *, cache_hit: bool = False, duration_ms: int = 0,
                        output_paths: Iterable[Path] = (), warnings: Iterable[str] = ()) -> None:
        if state not in EXECUTION_STATES: raise ValueError(f"invalid execution state: {state}")
        self.runtime_records[stage] = {"stage_name": stage, "execution_state": state, "cache_hit": cache_hit,
                                       "executed": state == "executed", "duration_ms": max(0, duration_ms),
                                       "output_paths": [str(path.resolve()) for path in output_paths], "warnings": list(warnings)}
        self.manifest["stage_records"] = [self.runtime_records[name] for name in STAGE_ORDER if name in self.runtime_records]
        self.manifest["project_summary"] = self.accounting_summary()
        self._save()

    def accounting_summary(self) -> dict[str, Any]:
        counts = {state: sum(record["execution_state"] == state for record in self.runtime_records.values()) for state in EXECUTION_STATES}
        api_executed = sum(record["execution_state"] == "executed" and name in AI_POWERED_STAGES for name, record in self.runtime_records.items())
        api_avoided = sum(record["execution_state"] == "skipped_cached" and name in AI_POWERED_STAGES for name, record in self.runtime_records.items())
        api_failed = sum(record["execution_state"] == "failed" and name in AI_POWERED_STAGES for name, record in self.runtime_records.items())
        return {"stages_executed": counts["executed"], "stages_skipped_cached": counts["skipped_cached"],
                "prerequisites_reused": counts["skipped_valid_prerequisite"], "stages_not_requested": counts["skipped_not_requested"],
                "stages_failed": counts["failed"], "stages_blocked": counts["blocked"], "stages_stale": counts["stale"],
                "api_calls_executed": api_executed, "api_calls_avoided_by_cache": api_avoided, "api_calls_failed": api_failed,
                "api_calls_retried": 0, "executed_stage_duration_ms": sum(r["duration_ms"] for r in self.runtime_records.values() if r["execution_state"] == "executed"),
                "cached_stage_lookup_duration_ms": sum(r["duration_ms"] for r in self.runtime_records.values() if r["execution_state"] == "skipped_cached")}

    def _load_manifest(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                value["run_id"] = uuid.uuid4().hex; value["started_at"] = now; value["completed_at"] = None
                return value
        except (OSError, ValueError): pass
        return {"project_id": self.project_id, "source_file_hashes": self.source_hashes, "stage_order": list(STAGE_ORDER),
                "stage_statuses": {s: "pending" for s in STAGE_ORDER}, "output_paths": {}, "cache_keys": {},
                "started_at": now, "completed_at": None, "last_successful_stage": None, "failed_stage": None,
                "warnings": [], "run_id": uuid.uuid4().hex}

    def metadata_path(self, stage: str) -> Path:
        return CACHE_METADATA_OUTPUT_DIRECTORY / self.project_id / f"{stage}.json"

    def expected(self, stage: str, inputs: Iterable[Path], *, module_version: str = "1.0.0", schema_version: str = "1.0.0", prompt_version: str | None = None, model_policy: str | None = None, config: dict[str, Any] | None = None, semantic_json_inputs: bool = False, canonical_department2_fingerprint: str | None = None) -> dict[str, Any]:
        input_hashes = {str(p.resolve()): _semantic_file_hash(p) if semantic_json_inputs and p.suffix.casefold()==".json" else sha256_file(p) for p in inputs if p and p.is_file()}
        relevant_config_hash = hash_json(config or {"visual_mode": PROJECT_VISUAL_MODE})
        base = {"stage_name": stage, "module_version": module_version, "schema_version": schema_version,
                "prompt_template_version": prompt_version, "model_policy": model_policy,
                "input_artifact_hashes": input_hashes, "source_file_hashes": self.source_hashes,
                "relevant_config_hash": relevant_config_hash,
                "canonical_department2_fingerprint": canonical_department2_fingerprint}
        base["cache_key"] = hash_json(base)
        return base

    def valid(self, stage: str, outputs: Iterable[Path], expected: dict[str, Any]) -> tuple[bool, str]:
        paths = list(outputs)
        if not paths or any(not p.is_file() for p in paths): return False, "output missing"
        for path in paths:
            if path.suffix.casefold() == ".json":
                try: json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError): return False, f"corrupted JSON: {path.name}"
        try: actual = json.loads(self.metadata_path(stage).read_text(encoding="utf-8"))
        except (OSError, ValueError): return False, "cache metadata missing or corrupt"
        for key, value in expected.items():
            if actual.get(key) != value: return False, f"{key} changed"
        if actual.get("status") not in {"completed", "completed_with_warnings"}: return False, "previous stage was not successful"
        return True, "valid cached artifact"

    def begin(self, stage: str) -> None:
        self.manifest["stage_statuses"][stage] = "running"
        self._stage_started[stage] = time.monotonic()
        executed = self.manifest.setdefault("stages_actually_executed", [])
        if stage not in executed: executed.append(stage)
        self._save()

    def complete(self, stage: str, outputs: Iterable[Path], expected: dict[str, Any], *, warnings: list[str] | None = None) -> None:
        paths = list(outputs); status = "completed_with_warnings" if warnings else "completed"
        try: previous_hashes = json.loads(self.metadata_path(stage).read_text(encoding="utf-8")).get("output_hashes", {})
        except (OSError, ValueError, AttributeError): previous_hashes = {}
        metadata = {**expected, "created_at": datetime.now(timezone.utc).isoformat(), "status": status,
                    "output_paths": [str(p.resolve()) for p in paths], "output_hashes": {str(p.resolve()): sha256_file(p) for p in paths if p.is_file()}}
        target = self.metadata_path(stage); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(metadata, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
        self.manifest["stage_statuses"][stage] = status; self.manifest["output_paths"][stage] = metadata["output_paths"]
        self.manifest["cache_keys"][stage] = expected["cache_key"]; self.manifest["last_successful_stage"] = stage
        self.manifest["failed_stage"] = None; self.manifest["warnings"].extend(warnings or [])
        if self.forced_stage == stage and previous_hashes and previous_hashes != metadata["output_hashes"]:
            stale = [name for name in STAGE_ORDER if name in descendants(stage) and name != stage]
            for name in stale: self.manifest["stage_statuses"][name] = "stale"
            self.manifest["downstream_marked_stale"] = stale
        self._save()
        duration=round((time.monotonic()-self._stage_started.pop(stage,time.monotonic()))*1000)
        self._record_runtime(stage,"executed",duration_ms=duration,output_paths=paths,warnings=warnings or [])

    def skip(self, stage: str, cached: bool, *, duration_ms: int = 0) -> None:
        state="skipped_cached" if cached else "skipped_not_requested"
        self.manifest["stage_statuses"][stage] = state; self._save();self._record_runtime(stage,state,cache_hit=cached,duration_ms=duration_ms)

    def not_requested(self, stage: str, *, preserve_persistent_status: bool = False) -> None:
        if not preserve_persistent_status:self.manifest["stage_statuses"][stage]="skipped_not_requested"
        self._record_runtime(stage,"skipped_not_requested")

    def reuse_prerequisite(self, stage: str, path: Path) -> None:
        self._record_runtime(stage,"skipped_valid_prerequisite",output_paths=[path])

    def record_executed(self, stage: str, outputs: Iterable[Path] = (), *, duration_ms: int = 0, warnings: Iterable[str] = ()) -> None:
        self._record_runtime(stage,"executed",duration_ms=duration_ms,output_paths=outputs,warnings=warnings)

    def fail(self, stage: str, error: Exception | str) -> None:
        self.manifest["stage_statuses"][stage] = "failed"; self.manifest["failed_stage"] = stage
        self.manifest["failure"] = {"stage":stage,"reason":str(error),"artifact":None,"recorded_at":datetime.now(timezone.utc).isoformat()}
        self.manifest["warnings"].append(str(error)); self._save()
        duration=round((time.monotonic()-self._stage_started.pop(stage,time.monotonic()))*1000)
        self._record_runtime(stage,"failed",duration_ms=duration,warnings=[str(error)])

    def block(self, stage: str, reason: str) -> None:
        self.manifest["warnings"].append(reason);self._record_runtime(stage,"blocked",warnings=[reason])

    def first_incomplete(self) -> str | None:
        statuses = self.manifest.get("stage_statuses", {})
        return next((s for s in STAGE_ORDER if statuses.get(s) not in {"completed", "completed_with_warnings", "skipped_cached"}), None)

    def finish(self) -> None:
        self.manifest["source_file_hashes"] = self.source_hashes
        self.manifest["completed_at"] = datetime.now(timezone.utc).isoformat(); self._save()

    def _save(self) -> None:
        if any(v not in STATUSES for v in self.manifest["stage_statuses"].values()): raise ValueError("invalid stage status")
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")


_VOLATILE_CACHE_FIELDS={"created_at","updated_at","generated_at","timestamp","run_id","started_at","completed_at","selected_at","validated_at","checked_at"}
def _semantic_value(value:Any)->Any:
    if isinstance(value,dict):return {key:_semantic_value(item) for key,item in sorted(value.items()) if key not in _VOLATILE_CACHE_FIELDS}
    if isinstance(value,list):return [_semantic_value(item) for item in value]
    return value
def _semantic_file_hash(path:Path)->str:
    try:return hash_json(_semantic_value(json.loads(path.read_text(encoding="utf-8"))))
    except (OSError,ValueError,TypeError):return sha256_file(path)

# DEPARTMENT3_PHASE4C_LIVE_BRIDGE
# Canonical Department 3 live strategy boundary.
# Advisory engines may contribute intelligence, but only this bridge may convert
# candidates into an Approved Content Plan.
def _department3_canonical_approve(
    *,
    project_id,
    candidates,
    creative_engine=None,
    creative_args=(),
    creative_kwargs=None,
    campaign_engine=None,
    campaign_args=(),
    campaign_kwargs=None,
):
    return LiveDepartment3Orchestrator().approve(
        project_id=project_id,
        candidates=candidates,
        creative_engine=creative_engine,
        creative_args=creative_args,
        creative_kwargs=creative_kwargs or {},
        campaign_engine=campaign_engine,
        campaign_args=campaign_args,
        campaign_kwargs=campaign_kwargs or {},
    )

