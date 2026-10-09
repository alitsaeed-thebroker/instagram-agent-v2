from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .live_orchestration import LiveDepartment3Orchestrator
from .runtime_guard import assert_noncanonical_output
from src.execution.lineage import artifact_fingerprint


class PlanningCutoverError(RuntimeError):
    pass

class PlanningNoContentError(PlanningCutoverError):
    """Valid inputs have no approved source-supported production candidates."""

PLANNING_CUTOVER_VERSION = "1.3.1"

_CANDIDATE_LIST_KEYS = (
    "candidates", "items", "content_ideas", "content_items", "content", "posts", "plans", "campaign_items",
)
_ASSET_KEYS = ("approved_source_asset_ids", "selected_source_asset_ids", "asset_ids", "source_asset_ids", "assets")
_EVIDENCE_KEYS = ("evidence", "selected_fact_refs", "evidence_refs", "facts", "fact_refs")
_FORMAT_KEYS = ("format_intent", "selected_format", "format", "surface", "platform_format")
_CATEGORY_KEYS = ("content_category", "category", "content_type", "type")
_OBJECTIVE_KEYS = ("objective", "content_objective", "marketing_objective", "goal", "intent")
_AUDIENCE_KEYS = ("audience", "target_persona", "target_audience", "persona")
_PROPOSITION_KEYS = ("proposition", "concept_summary", "message", "value_proposition", "angle", "headline_concept")


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise PlanningCutoverError(f"planning artifact not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanningCutoverError(f"invalid planning artifact {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise PlanningCutoverError(f"planning artifact must be a JSON object: {path}")
    return value


def _first(mapping: Mapping[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", [], {}):
            return mapping[key]
    return default


def _normalize_format(value: Any) -> str:
    raw = str(value or "").strip().casefold()
    aliases = {
        "single": "feed",
        "single_post": "feed",
        "single-post": "feed",
        "post": "feed",
        "instagram_feed": "feed",
        "instagram-feed": "feed",
        "carousel_post": "carousel",
        "carousel-post": "carousel",
        "stories": "story",
        "instagram_story": "story",
        "instagram-story": "story",
    }
    raw = aliases.get(raw, raw)
    if raw not in {"feed", "carousel", "story"}:
        raise PlanningCutoverError(f"unsupported canonical format intent: {value!r}")
    return raw


def _normalize_assets(item: Mapping[str, Any]) -> list[str]:
    raw = _first(item, _ASSET_KEYS, [])
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, Mapping):
        raw = list(raw.values())
    if not isinstance(raw, Iterable):
        raise PlanningCutoverError("candidate assets must be iterable")
    result = []
    for value in raw:
        if isinstance(value, Mapping):
            value = value.get("asset_id") or value.get("id") or value.get("source_asset_id")
        if value is not None and str(value).strip():
            result.append(str(value).strip())
    if not result:
        raise PlanningCutoverError("candidate has no approved source assets")
    return result


def _normalize_evidence(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = _first(item, _EVIDENCE_KEYS, [])
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        raise PlanningCutoverError("candidate evidence must be iterable")

    result = []
    for value in raw:
        if isinstance(value, str):
            if value.strip():
                result.append({"fact_id": value.strip()})
            continue
        if not isinstance(value, Mapping):
            continue
        fact_id = (
            value.get("fact_id")
            or value.get("id")
            or value.get("fact")
            or value.get("knowledge_fact_id")
        )
        if not fact_id:
            continue
        record = {"fact_id": str(fact_id).strip()}
        source_id = value.get("source_id") or value.get("source")
        confidence = value.get("confidence")
        if source_id:
            record["source_id"] = str(source_id).strip()
        if confidence is not None:
            record["confidence"] = float(confidence)
        result.append(record)
    return result


def _extract_items(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in _CANDIDATE_LIST_KEYS:
        value = document.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, Mapping)]
    for key in ("content_plan", "campaign_plan", "plan"):
        value = document.get(key)
        if isinstance(value, Mapping):
            nested = _extract_items(value)
            if nested:
                return nested
    return []


def legacy_artifact_to_candidates(
    *,
    project_id: str,
    content_document: Mapping[str, Any],
    campaign_document: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if "content_ideas" in content_document:
        if content_document.get("project_id") != project_id:
            raise PlanningCutoverError("cross-project content artifact rejected")
        if not isinstance(content_document["content_ideas"], list):
            raise PlanningCutoverError("content_ideas must be a list")
        if not content_document["content_ideas"]:
            return []
    raw_items = _extract_items(content_document)
    if not raw_items and campaign_document is not None:
        raw_items = _extract_items(campaign_document)
    if not raw_items:
        raise PlanningCutoverError("legacy planning artifact contains no candidate items")

    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, 1):
        item_project = (
            item.get("project_id")
            or item.get("project")
            or content_document.get("project_id")
            or content_document.get("project")
            or project_id
        )
        if str(item_project) != str(project_id):
            raise PlanningCutoverError(
                f"cross-project legacy candidate rejected: expected {project_id!r}, got {item_project!r}"
            )

        # Unsupported visual candidates stay outside production authority.
        if item.get("source_support_status") in {"unavailable", "text_only"} and "content_idea_id" in item:
            continue
        production_item_id = (
            item.get("production_item_id")
            or item.get("content_idea_id")
            or item.get("item_id")
            or item.get("id")
            or item.get("content_id")
            or f"legacy-{index:03d}"
        )
        category = _first(item, _CATEGORY_KEYS)
        fmt = _first(item, _FORMAT_KEYS)
        objective = _first(item, _OBJECTIVE_KEYS)
        audience = _first(item, _AUDIENCE_KEYS)
        proposition = _first(item, _PROPOSITION_KEYS)

        missing = [
            name
            for name, value in (
                ("content_category", category),
                ("format_intent", fmt),
                ("objective", objective),
                ("audience", audience),
                ("proposition", proposition),
            )
            if value in (None, "")
        ]
        if missing:
            raise PlanningCutoverError(
                f"{production_item_id}: legacy candidate missing canonical fields: {missing}"
            )

        candidate = {
            "project_id": str(project_id),
            "production_item_id": str(production_item_id),
            "objective": str(objective).strip(),
            "audience": str(audience).strip(),
            "proposition": str(proposition).strip(),
            "content_category": str(category).strip(),
            "format_intent": _normalize_format(fmt),
            "approved_source_asset_ids": _normalize_assets(item),
            "evidence": _normalize_evidence(item),
        }
        if item.get("cta_intent"):
            candidate["cta_intent"] = str(item["cta_intent"]).strip()
        elif item.get("cta"):
            candidate["cta_intent"] = str(item["cta"]).strip()
        if item.get("story_sequence_role"):
            candidate["story_sequence_role"] = str(item["story_sequence_role"]).strip()
        if item.get("carousel_position") is not None:
            candidate["carousel_position"] = int(item["carousel_position"])
        if item.get("restrictions") or item.get("forbidden_claims"):
            restrictions = item.get("restrictions") or item["forbidden_claims"]
            if isinstance(restrictions, str):
                restrictions = [restrictions]
            candidate["restrictions"] = [str(x).strip() for x in restrictions if str(x).strip()]
        candidates.append(candidate)

    return candidates


def _canonical_compatibility_document(
    *,
    project_id: str,
    legacy_document: Mapping[str, Any],
    live_result: Any,
    artifact_kind: str,
) -> dict[str, Any]:
    canonical = live_result.approved_content_plan
    result = dict(legacy_document)
    result["schema_version"] = f"department3.{artifact_kind}.canonical-compat.v1"
    result["project_id"] = project_id
    result["authority"] = {
        "authoritative": True,
        "authority_module": canonical.authority_module,
        "approved_content_plan_id": canonical.plan_id,
        "plan_version": canonical.plan_version,
    }
    result["approved_content_plan"] = canonical.to_dict() | {"plan_id": canonical.plan_id}
    result["legacy_compatibility"] = {
        "source": "src.planning.engine",
        "authoritative": False,
        "purpose": "candidate generation and downstream schema compatibility only",
    }
    if isinstance(result.get("content_ideas"), list):
        approved = {d.production_item_id for d in canonical.decisions}
        result["skipped_candidates"] = [
            {"content_idea_id": item.get("content_idea_id"), "reason": "not approved for visual production",
             "source_support_status": item.get("source_support_status")}
            for item in result["content_ideas"] if item.get("content_idea_id") not in approved]
        result["content_ideas"] = [item for item in result["content_ideas"] if item.get("content_idea_id") in approved]
    if "lineage" in result:
        result["artifact_fingerprint"] = artifact_fingerprint(result)
    return result


def cutover_legacy_planning_products(
    *,
    project_id: str,
    planning_engine: Any,
    planning_args: Iterable[Any],
    planning_kwargs: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    args = tuple(planning_args)
    products = planning_engine.run(*args, **dict(planning_kwargs or {}))
    if not isinstance(products, Mapping):
        raise PlanningCutoverError("PlanningEngine.run() must return a mapping of artifact paths")

    content_path = Path(products.get("content_plan", ""))
    campaign_path = Path(products["campaign_plan"]) if products.get("campaign_plan") else None

    campaign_generated = dict(planning_kwargs or {}).get("write_campaign", True)
    content_document = _read_json(content_path)
    campaign_document = _read_json(campaign_path) if campaign_path and campaign_path.is_file() else None

    assert_noncanonical_output("src.planning.engine", content_document)
    if campaign_document is not None and campaign_generated:
        assert_noncanonical_output("src.planning.engine", campaign_document)

    candidates = legacy_artifact_to_candidates(
        project_id=project_id,
        content_document=content_document,
        campaign_document=campaign_document,
    )

    if "content_ideas" in content_document:
        # Validate the real producer's facts and assets before granting authority.
        if len(args) < 3:
            raise PlanningCutoverError("Live planner cutover requires knowledge and visual inventory inputs")
        from src.knowledge.consumer import require_canonical_graph, canonical_verified_facts
        from src.planning.engine import _project_assets
        from src.plan_integrity import UNIT_TYPES
        from src.unit_plan_relationship import relationship_errors
        import hashlib
        knowledge = dict(_read_json(Path(args[0])))
        require_canonical_graph(knowledge, expected_project=project_id)
        facts = canonical_verified_facts(knowledge, project_id)
        assets = {a["asset_id"]: a for a in _project_assets(dict(_read_json(Path(args[2]))), project_id)}
        for candidate in candidates:
            for evidence in candidate["evidence"]:
                if evidence["fact_id"] not in facts:
                    raise PlanningCutoverError(f"Unverified or foreign fact reference: {evidence['fact_id']}")
                fact = facts[evidence["fact_id"]]
                evidence["source_id"] = fact.evidence[0].get("source_id") or fact.evidence[0].get("source_document") or fact.evidence[0].get("source_file")
            for aid in candidate["approved_source_asset_ids"]:
                if aid not in assets:
                    raise PlanningCutoverError(f"Unknown or foreign source asset: {aid}")
                asset = assets[aid]
                source = Path(str(asset.get("source_path") or ""))
                expected = asset.get("source_hash") or asset.get("sha256")
                if not source.is_file() or not expected or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                    raise PlanningCutoverError(f"Source hash mismatch: {aid}")
                if asset.get("asset_type") in UNIT_TYPES:
                    errors = relationship_errors(asset, expected_project=project_id, asset_id=aid, source_path=str(source))
                    if errors or not asset.get("marketing_eligible"):
                        raise PlanningCutoverError(f"Unit plan requires validation: {aid}")

    if not candidates:
        raise PlanningNoContentError(
            f"{project_id}: no approved source-supported visual candidates; "
            "check campaign category approvals, visual readiness, reservations and source reuse limits. "
            "Downstream production and publishing remain blocked."
        )

    live_result = LiveDepartment3Orchestrator().approve(
        project_id=project_id,
        candidates=candidates,
    )

    content_path.write_text(
        json.dumps(
            _canonical_compatibility_document(
                project_id=project_id,
                legacy_document=content_document,
                live_result=live_result,
                artifact_kind="content-plan",
            ),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    if campaign_generated and campaign_path is not None and campaign_document is not None:
        campaign_path.write_text(
            json.dumps(
                _canonical_compatibility_document(
                    project_id=project_id,
                    legacy_document=campaign_document,
                    live_result=live_result,
                    artifact_kind="campaign-plan",
                ),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    return {k: Path(v) for k, v in products.items()}
