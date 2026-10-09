"""Central coordinator for the file-based multi-agent marketing workflow.

The orchestrator documents ordering only. It deliberately does not execute
agents until their JSON contracts and implementations are available.
"""

from __future__ import annotations

from src.core.logger import get_logger


class Orchestrator:
    """Own the workflow order while keeping agents independent from one another."""

    workflow = (
        "PDF Agent",
        "Knowledge Agent",
        "Marketing Strategist Agent",
        "Creative Director Agent",
        "Prompt Agent",
        "Image Agent",
        "Brand Agent",
        "Caption Agent",
    )

    def __init__(self) -> None:
        """Initialize the coordinator logger."""
        self.logger = get_logger(__name__)

    def run(self) -> None:
        """Reserve the central execution point for the future agent pipeline."""
        self.logger.info("Agent workflow is defined but not implemented: %s", " -> ".join(self.workflow))
