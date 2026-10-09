"""Shared interfaces and constants for the AI-agent workflow.

Agents exchange file paths to structured artifacts. The artifacts themselves are
the integration boundary; agents must not invoke one another directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Agent(Protocol):
    """Define the common interface implemented by every workflow agent."""

    def run(self, input_path: Path) -> Path | None:
        """Process one input artifact and return its output artifact when implemented."""


class PlaceholderAgent:
    """Provide consistent no-op behavior for agents awaiting implementation."""

    def _log_placeholder(self, input_path: Path) -> None:
        """Log that a placeholder received an artifact without processing it."""
        self.logger.info("%s is not implemented; received: %s", self.__class__.__name__, input_path)
