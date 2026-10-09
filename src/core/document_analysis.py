"""Content-derived document analysis and inventory reporting."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from PIL import Image
from pypdf import PdfReader

from src.knowledge.document_classifier import ClassificationResult
from src.utils.config import DOCUMENT_ANALYSIS_OUTPUT_DIRECTORY


def analyze_document(
    path: Path,
    content: str,
    classification: ClassificationResult,
    project_assignment: str,
) -> dict[str, Any]:
    """Describe one file from contents and decoded structure, never its name semantics."""
    page_count, image_count = _counts(path)
    text_length = len(content.strip())
    headings = [
        line.lstrip("#").strip() for line in content.splitlines()
        if line.strip().startswith("#") and not re.fullmatch(r"#+\s*Page\s+\d+", line.strip(), re.IGNORECASE)
    ][:30]
    return {
        "file_identifier": path.name,
        "format": path.suffix.lstrip(".").upper(),
        "classification": classification.document_type.value,
        "confidence": classification.confidence,
        "supporting_evidence": list(classification.evidence),
        "roles": list(classification.roles),
        "document_language": _language(content),
        "document_purpose": classification.reason,
        "page_count": page_count,
        "image_count": image_count,
        "text_density": round(text_length / max(page_count, 1), 2),
        "visual_density": round(image_count / max(page_count, 1), 2),
        "text_quality": "empty" if not text_length else "low" if text_length < 100 else "usable",
        "document_structure": _structure(content),
        "headings": headings,
        "tables_detected": _table_count(content),
        "recurring_keywords": _recurring_keywords(content),
        "project_assignment": project_assignment,
        "warnings": ["Low-confidence content classification"] if classification.confidence < 0.70 else [],
    }


def save_document_analysis(project: str, documents: list[dict[str, Any]], warnings: list[str] | None = None) -> Path:
    DOCUMENT_ANALYSIS_OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = DOCUMENT_ANALYSIS_OUTPUT_DIRECTORY / f"{project}-document-analysis.json"
    destination.write_text(json.dumps({
        "project_assignment": project, "documents": documents,
        "warnings": warnings or [], "classification_policy": "content_only",
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


def _counts(path: Path) -> tuple[int, int]:
    if path.suffix.casefold() == ".pdf":
        reader = PdfReader(path)
        return len(reader.pages), sum(len(page.images) for page in reader.pages)
    try:
        with Image.open(path):
            return 1, 1
    except Exception:
        return 1, 0


def _language(content: str) -> str:
    arabic = len(re.findall(r"[\u0600-\u06ff]", content))
    latin = len(re.findall(r"[A-Za-z]", content))
    if arabic and latin:
        return "mixed_arabic_latin"
    if arabic:
        return "arabic"
    if latin:
        return "latin_script"
    return "unknown"


def _structure(content: str) -> str:
    pages = len(re.findall(r"^##\s+Page\s+\d+", content, re.MULTILINE | re.IGNORECASE))
    tables = _table_count(content)
    return f"{pages or 1} text section(s), {tables} table-like structure(s)"


def _table_count(content: str) -> int:
    return sum(1 for line in content.splitlines() if line.count("|") >= 2 or len(re.findall(r"\s{2,}", line.strip())) >= 2)


def _recurring_keywords(content: str) -> list[str]:
    words = re.findall(r"\b[a-zA-Z]{5,}\b", content.casefold())
    counts: dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    return [word for word, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])) if count >= 2][:20]
