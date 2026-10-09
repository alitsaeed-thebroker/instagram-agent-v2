"""Agent contract for producing caption JSON from project knowledge and strategy."""
from __future__ import annotations
from pathlib import Path
from src.ai.shared import PlaceholderAgent
from src.core.logger import get_logger


class CaptionAgent(PlaceholderAgent):
    """Produce ``captions.json`` from knowledge and strategy in a future workflow."""
    def __init__(self) -> None:
        """Initialize the caption-agent logger."""
        self.logger = get_logger(__name__)

    def run(self, input_path: Path) -> Path | None:
        """Accept JSON; future implementations will return captions JSON.

        The final implementation will receive knowledge and strategy through an
        orchestrator-created JSON artifact rather than another agent call.
        """
        self._log_placeholder(input_path)
        return None
