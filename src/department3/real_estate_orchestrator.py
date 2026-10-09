from __future__ import annotations

from typing import Any, Iterable, Mapping

from .live_orchestration import LiveDepartment3Orchestrator, LiveDepartment3Result
from .real_estate_brain import BrainConfig, RealEstateStrategyBrain


class RealEstateDepartment3Orchestrator:
    """High-level D3 reasoning -> canonical approval.

    This does not replace the authority chain. It creates better real-estate candidates
    and then sends them through LiveDepartment3Orchestrator for canonical approval.
    """

    def __init__(
        self,
        *,
        brain: RealEstateStrategyBrain | None = None,
        live: LiveDepartment3Orchestrator | None = None,
    ):
        self.brain = brain or RealEstateStrategyBrain()
        self.live = live or LiveDepartment3Orchestrator()

    def approve_opportunities(
        self,
        *,
        project_id: str,
        opportunities: Iterable[Mapping[str, Any]],
        recent_history: Iterable[Mapping[str, Any]] = (),
        creative_engine: Any | None = None,
        creative_args: Iterable[Any] = (),
        creative_kwargs: Mapping[str, Any] | None = None,
        campaign_engine: Any | None = None,
        campaign_args: Iterable[Any] = (),
        campaign_kwargs: Mapping[str, Any] | None = None,
    ) -> LiveDepartment3Result:
        candidates = self.brain.build_candidates(
            project_id=project_id,
            opportunities=opportunities,
            recent_history=recent_history,
        )
        if not candidates:
            raise RuntimeError("real-estate strategy brain produced no approvable candidates")

        return self.live.approve(
            project_id=project_id,
            candidates=candidates,
            creative_engine=creative_engine,
            creative_args=creative_args,
            creative_kwargs=creative_kwargs,
            campaign_engine=campaign_engine,
            campaign_args=campaign_args,
            campaign_kwargs=campaign_kwargs,
        )
