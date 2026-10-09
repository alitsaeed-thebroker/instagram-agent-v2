"""Run AI knowledge extraction for the first Markdown catalogue artifact."""

from __future__ import annotations

import sys

from src.ai.agents.knowledge_agent import KnowledgeAgent


def main() -> int:
    """Extract and save project knowledge, returning a shell exit code."""
    return 0 if KnowledgeAgent().run() else 1


if __name__ == "__main__":
    sys.exit(main())
