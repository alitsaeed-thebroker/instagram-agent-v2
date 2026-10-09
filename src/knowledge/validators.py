"""Validation helpers for project knowledge artifacts."""

from __future__ import annotations

from src.knowledge.schema import ProjectKnowledge


def validate_project_knowledge(knowledge: ProjectKnowledge) -> list[str]:
    """Return validation errors for required project knowledge fields."""
    return knowledge.validate()
