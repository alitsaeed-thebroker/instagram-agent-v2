"""Project domain model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Project:
    """Structured representation of a source project."""

    name: str
    source_file: str
    metadata: dict[str, str] = field(default_factory=dict)
