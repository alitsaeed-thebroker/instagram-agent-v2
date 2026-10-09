"""Agent contract for generating image-prompt JSON."""
from __future__ import annotations
from pathlib import Path
from src.ai.shared import PlaceholderAgent
from src.core.logger import get_logger


class PromptAgent(PlaceholderAgent):
    """Produce ``image_prompts.json`` from creative direction in a future workflow."""
    def __init__(self) -> None:
        """Initialize the prompt-agent logger."""
        self.logger = get_logger(__name__)

    def run(self, input_path: Path) -> Path | None:
        """Accept creative-direction JSON; future implementations will return prompt JSON."""
        self._log_placeholder(input_path)
        return None
