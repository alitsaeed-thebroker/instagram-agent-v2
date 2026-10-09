"""Persistence helpers for project knowledge JSON artifacts."""

from __future__ import annotations

from pathlib import Path

from src.knowledge.schema import ProjectKnowledge
from src.utils.config import KNOWLEDGE_OUTPUT_DIRECTORY


def _knowledge_path(filename: str | Path, output_directory: Path) -> Path:
    """Resolve a JSON artifact name safely within the knowledge directory."""
    name = Path(filename)
    if name.name != str(filename) or name.name in {"", ".", ".."}:
        raise ValueError("filename must not contain directory components")
    return output_directory / name.with_suffix(".json")


def save_project_knowledge(
    knowledge: ProjectKnowledge,
    filename: str | Path,
    output_directory: Path = KNOWLEDGE_OUTPUT_DIRECTORY,
) -> Path:
    """Validate and save project knowledge as ``output/knowledge/<name>.json``."""
    errors = knowledge.validate()
    if errors:
        raise ValueError("Cannot save invalid project knowledge: " + "; ".join(errors))

    destination = _knowledge_path(filename, output_directory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(knowledge.to_json() + "\n", encoding="utf-8")
    return destination


def load_project_knowledge(
    filename: str | Path,
    output_directory: Path = KNOWLEDGE_OUTPUT_DIRECTORY,
) -> ProjectKnowledge:
    """Load project knowledge from ``output/knowledge/<name>.json``."""
    source = _knowledge_path(filename, output_directory)
    knowledge = ProjectKnowledge.from_json(source.read_text(encoding="utf-8"))
    errors = knowledge.validate()
    if errors:
        raise ValueError("Loaded invalid project knowledge: " + "; ".join(errors))
    return knowledge


def load_authoritative_project_intelligence(
    filename: str | Path, output_directory: Path = KNOWLEDGE_OUTPUT_DIRECTORY,
) -> dict:
    """Load the sole downstream commercial-intelligence contract.

    Page-native/deep knowledge is intermediate source analysis and must not be
    used to make pricing, payment, or other commercial decisions.
    """
    knowledge = load_project_knowledge(filename, output_directory)
    contract = knowledge.commercial_intelligence
    if contract and contract.get("contract_role") != "authoritative_project_intelligence":
        raise ValueError("Commercial intelligence artifact is not authoritative")
    return contract


def load_authoritative_department2_intelligence(
    filename: str | Path,
    output_directory: Path = KNOWLEDGE_OUTPUT_DIRECTORY,
) -> dict:
    """Load and validate the canonical Department 2 relational contract.

    Legacy ProjectKnowledge fields and the flat commercial projection are
    compatibility-only after relational schema v2.
    """
    from src.knowledge.relational import CanonicalIntelligence

    knowledge = load_project_knowledge(filename, output_directory)
    if not knowledge.canonical_intelligence:
        raise ValueError("Canonical Department 2 relational intelligence is unavailable")
    graph = CanonicalIntelligence.from_dict(knowledge.canonical_intelligence)
    return graph.to_dict()
