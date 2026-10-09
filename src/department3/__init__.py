from .authority import (
    AuthorityRole,
    Department3AuthorityError,
    advisory_modules,
    canonical_modules,
    legacy_modules,
    role_for,
)
from .strategy_authority import (
    ApprovedContentPlan,
    Department3StrategyAuthority,
    EvidenceRef,
    StrategyAuthorityError,
    StrategyDecision,
)
from .advisory import (
    AdvisoryEngineAdapter,
    AdvisoryEnvelope,
    AdvisoryIntegrationError,
    validate_advisory_envelopes,
)
from .integration import (
    Department3CanonicalPlanner,
    Department3DecisionContext,
)
from .legacy_quarantine import (
    LegacyAdvisoryResult,
    LegacyModuleAdapter,
    LegacyQuarantineError,
    quarantine_legacy_output,
)

__all__ = [
    "AuthorityRole",
    "Department3AuthorityError",
    "ApprovedContentPlan",
    "Department3StrategyAuthority",
    "EvidenceRef",
    "StrategyAuthorityError",
    "StrategyDecision",
    "AdvisoryEngineAdapter",
    "AdvisoryEnvelope",
    "AdvisoryIntegrationError",
    "Department3CanonicalPlanner",
    "Department3DecisionContext",
    "LegacyAdvisoryResult",
    "LegacyModuleAdapter",
    "LegacyQuarantineError",
    "advisory_modules",
    "canonical_modules",
    "legacy_modules",
    "quarantine_legacy_output",
    "role_for",
    "validate_advisory_envelopes",
]
