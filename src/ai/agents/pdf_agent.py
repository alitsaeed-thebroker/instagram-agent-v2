"""Agent contract for transforming a source PDF into Markdown."""
from __future__ import annotations
from pathlib import Path
from src.ai.shared import PlaceholderAgent
from src.core.logger import get_logger


class PdfAgent(PlaceholderAgent):
    """Produce a Markdown artifact from one PDF artifact in a future workflow."""
    def __init__(self) -> None:
        """Initialize the PDF-agent logger."""
        self.logger = get_logger(__name__)

    def run(self, input_path: Path) -> Path | None:
        """Accept a PDF path; future implementations will return a Markdown path."""
        self._log_placeholder(input_path)
        return None
