"""Shared fail-closed eligibility contract for deterministic production prompts."""
from __future__ import annotations

from typing import Any

ELIGIBILITY_VERSION = "1.0.0"
WARNING_SCHEMA_VERSION = "1.0.0"

WARNING_TYPES = {
    "missing_verified_fact_reference": ("factual_provenance", "advisory", False),
    "optional_context_missing": ("context_completeness", "advisory", False),
    "invalid_asset_removed": ("asset_resolution", "advisory", False),
    "semantic_asset_repaired": ("asset_resolution", "advisory", False),
    "manual_safety_review": ("production_safety", "error", True),
}


def warning(code: str, message: str) -> dict[str, Any]:
    category, severity, blocking = WARNING_TYPES.get(code, ("unclassified", "error", True))
    return {"code": code, "category": category, "severity": severity,
            "blocking": blocking, "message": message}


def warning_for_message(message: str) -> dict[str, Any]:
    if message == "Factual objective has no verified fact references":
        return warning("missing_verified_fact_reference", message)
    if message.startswith("Optional context missing:"):
        return warning("optional_context_missing", message)
    if message.startswith("Invalid asset "):
        return warning("invalid_asset_removed", message)
    if message == "Semantic asset mismatch repaired using approved content-plan assets":
        return warning("semantic_asset_repaired", message)
    return warning("unclassified_warning", message)


def production_eligibility(prompt: dict[str, Any]) -> tuple[bool, str]:
    if prompt.get("execution_route") != "deterministic_processor" or prompt.get("ai_prompt_required") is not False:
        return False, "unsupported_execution_route"
    status = prompt.get("confidence", {}).get("status")
    if status not in {"production_ready", "production_ready_with_warnings"}:
        return False, "not_production_eligible"
    messages = prompt.get("warnings", [])
    details = prompt.get("warning_details")
    if not isinstance(messages, list) or not isinstance(details, list) or len(messages) != len(details):
        return False, "unknown_warning_semantics"
    for item in details:
        if not isinstance(item, dict) or set(item) != {"code", "category", "severity", "blocking", "message"}:
            return False, "unknown_warning_semantics"
        if item.get("code") not in WARNING_TYPES or item.get("severity") not in {"info", "advisory", "warning", "error"}:
            return False, "unknown_warning_semantics"
        if item.get("blocking") is True:
            return False, "blocking_warning"
        if item.get("blocking") is not False:
            return False, "unknown_warning_semantics"
    if status == "production_ready_with_warnings" and not details:
        return False, "unknown_warning_semantics"
    return True, "production_eligible"
