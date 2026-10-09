from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


class AuthorityRole(str, Enum):
    CANONICAL_STRATEGY = "canonical_strategy"
    CANONICAL_VISUAL_DIRECTION = "canonical_visual_direction"
    ADVISORY_INTELLIGENCE = "advisory_intelligence"
    LEGACY_NON_AUTHORITATIVE = "legacy_non_authoritative"
    D4_EXECUTOR = "d4_executor"


@dataclass(frozen=True)
class AuthorityRegistration:
    module: str
    role: AuthorityRole
    may_create_approved_content_plan: bool = False
    may_create_visual_direction_contract: bool = False
    may_execute_visual_direction: bool = False
    may_write_authoritative_d3_state: bool = False


REGISTRY: tuple[AuthorityRegistration, ...] = (
    # Canonical D3 authority
    AuthorityRegistration(
        module="src.department3.strategy_authority",
        role=AuthorityRole.CANONICAL_STRATEGY,
        may_create_approved_content_plan=True,
        may_write_authoritative_d3_state=True,
    ),
    AuthorityRegistration(
        module="src.creative.visual_art_director",
        role=AuthorityRole.CANONICAL_VISUAL_DIRECTION,
        may_create_visual_direction_contract=True,
        may_write_authoritative_d3_state=True,
    ),
    AuthorityRegistration(
        module="src.creative.visual_direction",
        role=AuthorityRole.CANONICAL_VISUAL_DIRECTION,
        may_create_visual_direction_contract=True,
        may_write_authoritative_d3_state=True,
    ),
    AuthorityRegistration(
        module="src.creative.production_contract",
        role=AuthorityRole.CANONICAL_VISUAL_DIRECTION,
        may_write_authoritative_d3_state=False,
    ),

    # Advisory intelligence providers
    AuthorityRegistration(
        module="src.creative_intelligence.engine",
        role=AuthorityRole.ADVISORY_INTELLIGENCE,
    ),
    AuthorityRegistration(
        module="src.campaign_intelligence.engine",
        role=AuthorityRole.ADVISORY_INTELLIGENCE,
    ),

    # Legacy modules kept only for compatibility/tests
    AuthorityRegistration(
        module="src.ai.agents.content_planner",
        role=AuthorityRole.LEGACY_NON_AUTHORITATIVE,
    ),
    AuthorityRegistration(
        module="src.ai.agents.creative_director_agent",
        role=AuthorityRole.LEGACY_NON_AUTHORITATIVE,
    ),
    AuthorityRegistration(
        module="src.ai.agents.marketing_strategy_agent",
        role=AuthorityRole.LEGACY_NON_AUTHORITATIVE,
    ),
    AuthorityRegistration(
        module="src.ai.agents.campaign_planner",
        role=AuthorityRole.LEGACY_NON_AUTHORITATIVE,
    ),
    AuthorityRegistration(
        module="src.ai.agents.visual_art_director_agent",
        role=AuthorityRole.LEGACY_NON_AUTHORITATIVE,
    ),
    AuthorityRegistration(
        module="src.planning.engine",
        role=AuthorityRole.LEGACY_NON_AUTHORITATIVE,
    ),

    # D4 execution boundary
    AuthorityRegistration(
        module="src.branding.composer",
        role=AuthorityRole.D4_EXECUTOR,
        may_execute_visual_direction=True,
    ),
    AuthorityRegistration(
        module="src.image_processing.planner",
        role=AuthorityRole.D4_EXECUTOR,
        may_execute_visual_direction=True,
    ),
    AuthorityRegistration(
        module="src.image_processing.schema",
        role=AuthorityRole.D4_EXECUTOR,
        may_execute_visual_direction=True,
    ),
    AuthorityRegistration(
        module="src.image_prompts.generator",
        role=AuthorityRole.D4_EXECUTOR,
        may_execute_visual_direction=True,
    ),
    AuthorityRegistration(
        module="src.production.workflow",
        role=AuthorityRole.D4_EXECUTOR,
        may_execute_visual_direction=True,
    ),
)


_BY_MODULE = {r.module: r for r in REGISTRY}


class Department3AuthorityError(RuntimeError):
    pass


def registration(module: str) -> AuthorityRegistration:
    try:
        return _BY_MODULE[module]
    except KeyError as exc:
        raise Department3AuthorityError(
            f"Unregistered Department 3 authority participant: {module}"
        ) from exc


def role_for(module: str) -> AuthorityRole:
    return registration(module).role


def assert_can_create_approved_content_plan(module: str) -> None:
    reg = registration(module)
    if not reg.may_create_approved_content_plan:
        raise Department3AuthorityError(
            f"{module} is {reg.role.value} and may not create an Approved Content Plan"
        )


def assert_can_create_visual_direction_contract(module: str) -> None:
    reg = registration(module)
    if not reg.may_create_visual_direction_contract:
        raise Department3AuthorityError(
            f"{module} is {reg.role.value} and may not create a Visual Direction Contract"
        )


def assert_can_write_authoritative_d3_state(module: str) -> None:
    reg = registration(module)
    if not reg.may_write_authoritative_d3_state:
        raise Department3AuthorityError(
            f"{module} is {reg.role.value} and may not write authoritative Department 3 state"
        )


def assert_can_execute_visual_direction(module: str) -> None:
    reg = registration(module)
    if not reg.may_execute_visual_direction:
        raise Department3AuthorityError(
            f"{module} is {reg.role.value} and may not execute production visual direction"
        )


def advisory_modules() -> tuple[str, ...]:
    return tuple(
        r.module for r in REGISTRY if r.role == AuthorityRole.ADVISORY_INTELLIGENCE
    )


def legacy_modules() -> tuple[str, ...]:
    return tuple(
        r.module for r in REGISTRY if r.role == AuthorityRole.LEGACY_NON_AUTHORITATIVE
    )


def canonical_modules() -> tuple[str, ...]:
    return tuple(
        r.module
        for r in REGISTRY
        if r.role in {
            AuthorityRole.CANONICAL_STRATEGY,
            AuthorityRole.CANONICAL_VISUAL_DIRECTION,
        }
    )


def validate_registry() -> None:
    modules = [r.module for r in REGISTRY]
    if len(modules) != len(set(modules)):
        raise Department3AuthorityError("Duplicate module registrations detected")

    strategy_writers = [
        r for r in REGISTRY if r.may_create_approved_content_plan
    ]
    if len(strategy_writers) != 1:
        raise Department3AuthorityError(
            f"Exactly one Approved Content Plan authority is required; found {len(strategy_writers)}"
        )

    for r in REGISTRY:
        if r.role in {
            AuthorityRole.ADVISORY_INTELLIGENCE,
            AuthorityRole.LEGACY_NON_AUTHORITATIVE,
            AuthorityRole.D4_EXECUTOR,
        } and r.may_write_authoritative_d3_state:
            raise Department3AuthorityError(
                f"{r.module} cannot be {r.role.value} and an authoritative D3 writer"
            )

    for r in REGISTRY:
        if r.role == AuthorityRole.D4_EXECUTOR and (
            r.may_create_approved_content_plan or r.may_create_visual_direction_contract
        ):
            raise Department3AuthorityError(
                f"D4 executor {r.module} cannot create D3 authority artifacts"
            )


validate_registry()
