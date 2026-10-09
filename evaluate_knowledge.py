"""Evaluate a generated project knowledge artifact without calling external services."""

from __future__ import annotations

import sys
from pathlib import Path

from src.knowledge.evaluator import KnowledgeEvaluator
from src.utils.config import KNOWLEDGE_OUTPUT_DIRECTORY


def main() -> int:
    """Evaluate a named knowledge file, or the first available one."""
    candidates = [Path(sys.argv[1])] if len(sys.argv) > 1 else sorted(KNOWLEDGE_OUTPUT_DIRECTORY.glob("*.json"))
    if not candidates:
        print("No knowledge JSON files were found in output/knowledge/.")
        return 1

    knowledge_path = candidates[0]
    if not knowledge_path.exists() and not knowledge_path.is_absolute():
        knowledge_path = KNOWLEDGE_OUTPUT_DIRECTORY / knowledge_path
    evaluator = KnowledgeEvaluator()
    evaluation = evaluator.evaluate_file(knowledge_path)
    report_path = evaluator.save_report(evaluation, knowledge_path)
    print(evaluator.format_report(evaluation))
    print(f"Saved report: {report_path}")
    return 0 if evaluation.json_validity["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
