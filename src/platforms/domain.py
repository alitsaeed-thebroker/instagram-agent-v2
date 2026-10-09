"""Central, deliberately conservative Meta platform domain model.

Exact limits that are not verified by this project remain configurable rather
than being represented here as guessed API constraints.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable


class _StrictEnum(str, Enum):
    @classmethod
    def parse(cls, value: Any):
        try: return cls(str(value).strip().casefold())
        except ValueError as error:
            allowed = ", ".join(x.value for x in cls)
            raise ValueError(f"Unknown {cls.__name__} '{value}'. Expected one of: {allowed}") from error


class Platform(_StrictEnum):
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"


class CampaignPlatformStrategy(_StrictEnum):
    INSTAGRAM_ONLY = "instagram_only"
    FACEBOOK_ONLY = "facebook_only"
    BOTH_MIRRORED = "both_mirrored"
    BOTH_PLATFORM_OPTIMIZED = "both_platform_optimized"


class DestinationOverride(_StrictEnum):
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    BOTH = "both"
    USE_PLANNED = "use_planned"


class AuthMode(_StrictEnum):
    INSTAGRAM_LOGIN = "instagram_login"
    FACEBOOK_LOGIN = "facebook_login"


@dataclass(frozen=True)
class PlatformCapability:
    platform: Platform
    feed_image: bool = True
    carousel: bool = True
    story: bool = False
    caption: bool = True
    hashtags: bool = True
    alt_text: bool = True
    aspect_ratios: tuple[str, ...] = ()
    media_count: dict[str, int | None] = field(default_factory=lambda: {"minimum": 1, "maximum": None})
    publishing_prerequisites: tuple[str, ...] = ()


CAPABILITIES = {
    Platform.INSTAGRAM: PlatformCapability(Platform.INSTAGRAM, story=True,
        publishing_prerequisites=("access_token", "instagram_professional_account")),
    Platform.FACEBOOK: PlatformCapability(Platform.FACEBOOK,
        publishing_prerequisites=("access_token", "facebook_page")),
}


def capability_for(platform: Platform | str) -> PlatformCapability:
    return CAPABILITIES[platform if isinstance(platform, Platform) else Platform.parse(platform)]


@dataclass(frozen=True)
class PlatformIntent:
    content_id: str
    master_concept_id: str
    strategy: CampaignPlatformStrategy
    planned_destinations: tuple[Platform, ...]
    rationale: str
    packaging: str = "shared"
    source_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.content_id or not self.master_concept_id: raise ValueError("content_id and master_concept_id are required")
        if not self.planned_destinations or len(set(self.planned_destinations)) != len(self.planned_destinations): raise ValueError("planned_destinations must be unique and non-empty")
        if not self.rationale.strip(): raise ValueError("platform rationale is required")
        expected = {Platform.INSTAGRAM} if self.strategy == CampaignPlatformStrategy.INSTAGRAM_ONLY else {Platform.FACEBOOK} if self.strategy == CampaignPlatformStrategy.FACEBOOK_ONLY else None
        if expected and set(self.planned_destinations) != expected: raise ValueError(f"{self.strategy.value} requires {next(iter(expected)).value}")
        if self.strategy == CampaignPlatformStrategy.BOTH_MIRRORED and set(self.planned_destinations) != set(Platform): raise ValueError("both_mirrored requires both destinations")
        if self.packaging not in {"shared", "platform_specific"}: raise ValueError("packaging must be shared or platform_specific")


@dataclass(frozen=True)
class PlatformVariant:
    platform: Platform
    master_content_id: str
    content_version: str
    factual_claims: tuple[str, ...]
    source_references: tuple[str, ...]
    caption: str = ""
    cta: str = ""
    hashtags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def build_variants(master: dict[str, Any], intent: PlatformIntent) -> list[PlatformVariant]:
    """Create variants while copying the factual/provenance foundation verbatim."""
    claims = tuple(master.get("verified_facts", ())); refs = tuple(master.get("source_references", ()))
    content_id = str(master.get("content_id") or intent.content_id); version = str(master.get("content_version", "1"))
    variants = []
    for platform in intent.planned_destinations:
        metadata = {"packaging": intent.packaging, "strategy": intent.strategy.value, "platform": platform.value}
        variants.append(PlatformVariant(platform, content_id, version, claims, refs,
                                        str(master.get("caption", "")), str(master.get("cta", "")),
                                        tuple(master.get("hashtags", ())), metadata))
    return variants


def apply_destination_override(planned: Iterable[Platform | str], override: DestinationOverride | str) -> tuple[Platform, ...]:
    destinations = tuple(x if isinstance(x, Platform) else Platform.parse(x) for x in planned)
    if not destinations: raise ValueError("planned destinations cannot be empty")
    selected = override if isinstance(override, DestinationOverride) else DestinationOverride.parse(override)
    if selected == DestinationOverride.USE_PLANNED: return destinations
    if selected == DestinationOverride.BOTH: return tuple(Platform)
    return (Platform.parse(selected.value),)
