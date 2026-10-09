from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .advisory import AdvisoryEnvelope, validate_advisory_envelopes
from .strategy_authority import ApprovedContentPlan, Department3StrategyAuthority


@dataclass(frozen=True)
class Department3DecisionContext:
    project_id: str
    advisory: tuple[AdvisoryEnvelope, ...]

    @property
    def advisory_fingerprints(self) -> tuple[str, ...]:
        return tuple(sorted(env.fingerprint for env in self.advisory))


class Department3CanonicalPlanner:
    """Canonical integration point for advisory intelligence -> Approved Content Plan."""

    def __init__(self, authority: Department3StrategyAuthority | None = None):
        self.authority = authority or Department3StrategyAuthority()

    def build_context(
        self,
        *,
        project_id: str,
        advisory: Iterable[AdvisoryEnvelope],
    ) -> Department3DecisionContext:
        checked = validate_advisory_envelopes(project_id, advisory)
        return Department3DecisionContext(project_id=project_id, advisory=checked)

    def approve(
        self,
        *,
        project_id: str,
        candidates: Iterable[Mapping[str, Any]],
        advisory: Iterable[AdvisoryEnvelope] = (),
    ) -> ApprovedContentPlan:
        ctx = self.build_context(project_id=project_id, advisory=advisory)

        # Preserve the provider-issued fingerprints as the canonical provenance IDs.
        # Do not re-hash AdvisoryEnvelope.to_dict(), because that creates a second,
        # unrelated identity and breaks traceability back to the advisory provider.
        advisory_inputs = [
            {
                "provider_module": env.provider_module,
                "project_id": env.project_id,
                "fingerprint": env.fingerprint,
                "authoritative": False,
            }
            for env in ctx.advisory
        ]

        plan = self.authority.approve(
            project_id=project_id,
            candidates=candidates,
            advisory_inputs=advisory_inputs,
        )

        # strategy_authority v1 hashes advisory input mappings. Replace those derived
        # hashes with the already-authenticated advisory fingerprints at this boundary.
        # This keeps Phase 4A backwards-compatible while making Phase 4B provenance exact.
        from .strategy_authority import StrategyDecision

        decisions = tuple(
            StrategyDecision(
                project_id=d.project_id,
                production_item_id=d.production_item_id,
                objective=d.objective,
                audience=d.audience,
                proposition=d.proposition,
                content_category=d.content_category,
                format_intent=d.format_intent,
                approved_source_asset_ids=d.approved_source_asset_ids,
                evidence=d.evidence,
                cta_intent=d.cta_intent,
                story_sequence_role=d.story_sequence_role,
                carousel_position=d.carousel_position,
                restrictions=d.restrictions,
                advisory_fingerprints=ctx.advisory_fingerprints,
            )
            for d in plan.decisions
        )

        return ApprovedContentPlan(
            project_id=plan.project_id,
            decisions=decisions,
            plan_version=plan.plan_version,
            authority_module=plan.authority_module,
        )
