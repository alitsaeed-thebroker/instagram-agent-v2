"""Global Domus Erbil brand-kit analysis."""

from .analysis import BRAND_KIT_VERSION, BrandKitResult, ensure_brand_foundation, run_brand_kit_analysis
from .validation import ValidationResult, validate_brand_config
from .identity import (ANALYZER_VERSION, IdentityResult, approved_config_hash,
                       run_brand_identity_analyzer)
from .readiness import ReadinessResult, approve_brand, run_brand_readiness_validator


def ensure_brand_analysis(root):
    """Produce or reuse the complete shared, company-level brand foundation."""
    kit = run_brand_kit_analysis(root)
    if not kit.validation.valid:
        raise ValueError("Invalid shared brand configuration: " + "; ".join(kit.validation.errors))
    identity = run_brand_identity_analyzer(root)
    # Identity analysis may deterministically persist a derived palette. Recompute
    # the inventory signature once so the shared cache represents final inputs.
    stabilized_kit = run_brand_kit_analysis(root)
    if not stabilized_kit.cached:
        kit = stabilized_kit
        identity = run_brand_identity_analyzer(root)
    else:
        kit = stabilized_kit
    readiness = run_brand_readiness_validator(root)
    return kit, identity, readiness

__all__ = [
    "BRAND_KIT_VERSION", "BrandKitResult", "ValidationResult",
    "ensure_brand_foundation", "run_brand_kit_analysis", "validate_brand_config",
    "ANALYZER_VERSION", "IdentityResult", "ReadinessResult", "approved_config_hash",
    "run_brand_identity_analyzer", "run_brand_readiness_validator", "approve_brand",
    "ensure_brand_analysis",
]
