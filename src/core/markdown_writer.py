"""Markdown output utilities."""

from __future__ import annotations

from pathlib import Path


def save_markdown(output_directory: Path, pdf_path: Path, content: str) -> Path:
    """Create the output directory and save extracted content as UTF-8 Markdown."""
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"{pdf_path.stem}.md"
    output_path.write_text(f"# Extracted text: {pdf_path.name}\n\n{content}\n", encoding="utf-8")
    return output_path
