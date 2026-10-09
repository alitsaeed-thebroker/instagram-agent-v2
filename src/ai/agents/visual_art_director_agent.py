"""Compatibility-facing entry point for the Department 4 Visual Art Director."""

from src.creative.visual_direction import (
    DirectionResult, VisualArtDirector, VisualDirectionContract, VisualDirectionError,
    validate_visual_direction_contract,
)

VisualArtDirectorAgent = VisualArtDirector

__all__ = ["DirectionResult", "VisualArtDirector", "VisualArtDirectorAgent", "VisualDirectionContract", "VisualDirectionError", "validate_visual_direction_contract"]
