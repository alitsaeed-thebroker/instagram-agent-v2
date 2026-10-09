"""PDF text extraction utilities."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract readable text from every page of a PDF in page order."""
    reader = PdfReader(pdf_path)
    pages: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        pages.append(f"## Page {page_number}\n\n{page_text.strip()}")
    return "\n\n".join(pages)
