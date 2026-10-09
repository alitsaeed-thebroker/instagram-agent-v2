from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .authority import (
    AuthorityRole,
    Department3AuthorityError,
    role_for,
)


FORBIDDEN_AUTHORITY_KEYS = frozenset(
    {
        "approved_content_plan",
        "approved-content-plan",
        "visual_direction_contract",
        "visual-direction-contract",
        "vdc",
        "authority_module",
        "authority_signature",
        "contract_integrity_hash",
    }
)


class LegacyQuarantineError(Department3AuthorityError):
    pass


@dataclass(frozen=True)
class LegacyAdvisoryResult:
    source_module: str
    payload: Mapping[str, Any]
    authoritative: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_module": self.source_module,
            "payload": dict(self.payload),
            "authoritative": False,
        }


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for k, v in value.items():
            yield str(k)
            yield from _walk_keys(v)
    elif isinstance(value, (list, tuple, set)):
        for x in value:
            yield from _walk_keys(x)


def quarantine_legacy_output(module: str, payload: Any) -> LegacyAdvisoryResult:
    if role_for(module) != AuthorityRole.LEGACY_NON_AUTHORITATIVE:
        raise LegacyQuarantineError(
            f"{module} is not registered as legacy non-authoritative"
        )

    if payload is None:
        normalized = {}
    elif isinstance(payload, Mapping):
        normalized = dict(payload)
    elif hasattr(payload, "to_dict") and callable(payload.to_dict):
        normalized = dict(payload.to_dict())
    elif hasattr(payload, "__dict__"):
        normalized = dict(vars(payload))
    else:
        raise LegacyQuarantineError(
            f"unsupported legacy output type: {type(payload).__name__}"
        )

    found = {k.casefold() for k in _walk_keys(normalized)}
    forbidden = sorted(k for k in FORBIDDEN_AUTHORITY_KEYS if k.casefold() in found)
    if forbidden:
        raise LegacyQuarantineError(
            f"{module} attempted to emit canonical authority fields: {forbidden}"
        )

    return LegacyAdvisoryResult(
        source_module=module,
        payload=normalized,
        authoritative=False,
    )


class LegacyModuleAdapter:
    """Compatibility wrapper for legacy agents.

    It may execute the old code for migration/compatibility, but canonical authority
    artifacts are rejected at the boundary.
    """

    def __init__(self, *, module: str, instance: Any):
        if role_for(module) != AuthorityRole.LEGACY_NON_AUTHORITATIVE:
            raise LegacyQuarantineError(
                f"{module} cannot be wrapped as legacy non-authoritative"
            )
        self.module = module
        self.instance = instance

    def run(self, *args: Any, **kwargs: Any) -> LegacyAdvisoryResult:
        fn = getattr(self.instance, "run", None)
        if not callable(fn):
            raise LegacyQuarantineError(f"{self.module} does not expose run()")
        return quarantine_legacy_output(self.module, fn(*args, **kwargs))
