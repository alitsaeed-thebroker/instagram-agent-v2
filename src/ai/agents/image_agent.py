"""Agent contract for rendering images from image-prompt JSON."""
from __future__ import annotations
from pathlib import Path
from src.ai.shared import PlaceholderAgent
from src.core.logger import get_logger


class ImageAgent(PlaceholderAgent):
    """Produce PNG or JPG artifacts from prompt JSON in a future workflow."""
    def __init__(self) -> None:
        """Initialize the image-agent logger."""
        self.logger = get_logger(__name__)

    def run(self, input_path: Path) -> Path | None:
        """Accept prompt JSON; future implementations will return image artifacts."""
        self._log_placeholder(input_path)
        return None
