from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from .authority import AuthorityRole, role_for


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


class AdvisoryProvider(Protocol):
    def build(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class AdvisoryEnvelope:
    provider_module: str
    provider_role: str
    project_id: str
    payload: Mapping[str, Any]
    fingerprint: str
    authoritative: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_module": self.provider_module,
            "provider_role": self.provider_role,
            "project_id": self.project_id,
            "payload": dict(self.payload),
            "fingerprint": self.fingerprint,
            "authoritative": self.authoritative,
        }


class AdvisoryIntegrationError(RuntimeError):
    pass


def normalize_advisory_payload(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        converted = value.to_dict()
        if not isinstance(converted, Mapping):
            raise AdvisoryIntegrationError("advisory to_dict() must return a mapping")
        return dict(converted)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise AdvisoryIntegrationError(
        f"unsupported advisory payload type: {type(value).__name__}"
    )


class AdvisoryEngineAdapter:
    """Wrap an existing intelligence engine and strip it of authority.

    The wrapped engine may score, infer, rank, critique, or recommend, but its output
    is always returned as an AdvisoryEnvelope with authoritative=False.
    """

    def __init__(self, *, provider_module: str, engine: Any):
        if role_for(provider_module) != AuthorityRole.ADVISORY_INTELLIGENCE:
            raise AdvisoryIntegrationError(
                f"{provider_module} is not registered as advisory intelligence"
            )
        self.provider_module = provider_module
        self.engine = engine

    def build(
        self,
        *,
        project_id: str,
        args: Iterable[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> AdvisoryEnvelope:
        if not project_id or not str(project_id).strip():
            raise AdvisoryIntegrationError("project_id is required")

        fn = getattr(self.engine, "build", None)
        if not callable(fn):
            raise AdvisoryIntegrationError(
                f"{self.provider_module} does not expose build()"
            )

        raw = fn(*tuple(args), **dict(kwargs or {}))
        payload = normalize_advisory_payload(raw)

        observed_project = (
            payload.get("project_id")
            or payload.get("project")
            or payload.get("project_name")
        )
        if observed_project and str(observed_project) != str(project_id):
            raise AdvisoryIntegrationError(
                f"cross-project advisory output rejected: expected {project_id!r}, "
                f"got {observed_project!r}"
            )

        body = {
            "provider_module": self.provider_module,
            "project_id": project_id,
            "payload": payload,
        }
        return AdvisoryEnvelope(
            provider_module=self.provider_module,
            provider_role=AuthorityRole.ADVISORY_INTELLIGENCE.value,
            project_id=str(project_id),
            payload=payload,
            fingerprint=_fingerprint(body),
            authoritative=False,
        )


def validate_advisory_envelopes(
    project_id: str,
    envelopes: Iterable[AdvisoryEnvelope],
) -> tuple[AdvisoryEnvelope, ...]:
    result = []
    seen = set()
    for env in envelopes:
        if env.authoritative:
            raise AdvisoryIntegrationError(
                f"advisory provider {env.provider_module} attempted to claim authority"
            )
        if env.project_id != project_id:
            raise AdvisoryIntegrationError("cross-project advisory envelope rejected")
        if role_for(env.provider_module) != AuthorityRole.ADVISORY_INTELLIGENCE:
            raise AdvisoryIntegrationError(
                f"non-advisory module supplied as intelligence: {env.provider_module}"
            )
        key = (env.provider_module, env.fingerprint)
        if key in seen:
            continue
        seen.add(key)
        result.append(env)
    return tuple(result)
