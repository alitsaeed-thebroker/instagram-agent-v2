from __future__ import annotations

from typing import Any, Mapping

from .authority import AuthorityRole, role_for
from .legacy_quarantine import LegacyQuarantineError, quarantine_legacy_output


class RuntimeAuthorityViolation(RuntimeError):
    pass


CANONICAL_PLAN_MARKERS = {
    "approved_content_plan",
    "approved-content-plan",
    "authority_module",
    "plan_version",
}

VDC_MARKERS = {
    "visual_direction_contract",
    "visual-direction-contract",
    "vdc",
    "contract_integrity_hash",
}


def _keys(value: Any):
    if isinstance(value, Mapping):
        for k, v in value.items():
            yield str(k).casefold()
            yield from _keys(v)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _keys(item)


def assert_noncanonical_output(module: str, payload: Any) -> None:
    role = role_for(module)
    if role not in {
        AuthorityRole.ADVISORY_INTELLIGENCE,
        AuthorityRole.LEGACY_NON_AUTHORITATIVE,
    }:
        return

    found = set(_keys(payload))
    forbidden = {x.casefold() for x in CANONICAL_PLAN_MARKERS | VDC_MARKERS}
    collision = sorted(found & forbidden)
    if collision:
        raise RuntimeAuthorityViolation(
            f"{module} attempted to emit canonical Department 3 authority fields: {collision}"
        )


def guard_legacy_output(module: str, payload: Any) -> Mapping[str, Any]:
    try:
        return quarantine_legacy_output(module, payload).to_dict()
    except LegacyQuarantineError as exc:
        raise RuntimeAuthorityViolation(str(exc)) from exc
