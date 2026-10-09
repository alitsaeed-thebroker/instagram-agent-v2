from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .advisory import AdvisoryEngineAdapter, AdvisoryEnvelope
from .integration import Department3CanonicalPlanner
from .legacy_quarantine import quarantine_legacy_output
from .strategy_authority import ApprovedContentPlan


class LiveDepartment3Error(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveDepartment3Result:
    project_id: str
    approved_content_plan: ApprovedContentPlan
    creative_intelligence: AdvisoryEnvelope | None
    campaign_intelligence: AdvisoryEnvelope | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "approved_content_plan": self.approved_content_plan.to_dict()
            | {"plan_id": self.approved_content_plan.plan_id},
            "creative_intelligence": (
                self.creative_intelligence.to_dict()
                if self.creative_intelligence is not None
                else None
            ),
            "campaign_intelligence": (
                self.campaign_intelligence.to_dict()
                if self.campaign_intelligence is not None
                else None
            ),
        }


class LiveDepartment3Orchestrator:
    """Canonical live Department 3 orchestration boundary.

    Existing intelligence engines remain responsible for producing advisory analysis.
    This class is the only bridge allowed to convert advisory inputs + candidates into
    an Approved Content Plan.
    """

    def __init__(self, planner: Department3CanonicalPlanner | None = None):
        self.planner = planner or Department3CanonicalPlanner()

    def _advisory(
        self,
        *,
        module: str,
        engine: Any | None,
        project_id: str,
        args: Iterable[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> AdvisoryEnvelope | None:
        if engine is None:
            return None
        return AdvisoryEngineAdapter(
            provider_module=module,
            engine=engine,
        ).build(project_id=project_id, args=args, kwargs=kwargs or {})

    def approve(
        self,
        *,
        project_id: str,
        candidates: Iterable[Mapping[str, Any]],
        creative_engine: Any | None = None,
        creative_args: Iterable[Any] = (),
        creative_kwargs: Mapping[str, Any] | None = None,
        campaign_engine: Any | None = None,
        campaign_args: Iterable[Any] = (),
        campaign_kwargs: Mapping[str, Any] | None = None,
    ) -> LiveDepartment3Result:
        creative = self._advisory(
            module="src.creative_intelligence.engine",
            engine=creative_engine,
            project_id=project_id,
            args=creative_args,
            kwargs=creative_kwargs,
        )
        campaign = self._advisory(
            module="src.campaign_intelligence.engine",
            engine=campaign_engine,
            project_id=project_id,
            args=campaign_args,
            kwargs=campaign_kwargs,
        )
        advisory = tuple(x for x in (creative, campaign) if x is not None)

        plan = self.planner.approve(
            project_id=project_id,
            candidates=candidates,
            advisory=advisory,
        )
        return LiveDepartment3Result(
            project_id=project_id,
            approved_content_plan=plan,
            creative_intelligence=creative,
            campaign_intelligence=campaign,
        )


def quarantine_legacy_result(module: str, payload: Any) -> Mapping[str, Any]:
    """Live compatibility gate used by legacy callers during migration."""
    return quarantine_legacy_output(module, payload).to_dict()
