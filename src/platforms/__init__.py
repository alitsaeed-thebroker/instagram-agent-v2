"""Platform strategy, capability, variant, and destination contracts."""

from .domain import (
    AuthMode, CampaignPlatformStrategy, DestinationOverride, Platform,
    PlatformCapability, PlatformIntent, PlatformVariant, CAPABILITIES,
    apply_destination_override, build_variants, capability_for,
)

__all__ = ["AuthMode", "CampaignPlatformStrategy", "DestinationOverride", "Platform",
           "PlatformCapability", "PlatformIntent", "PlatformVariant", "CAPABILITIES",
           "apply_destination_override", "build_variants", "capability_for"]
