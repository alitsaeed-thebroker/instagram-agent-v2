"""Provenance-preserving extraction for plain-text and Word documents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree


@dataclass(frozen=True)
class ExtractedTextBlock:
    text: str
    original_filename: str
    project: str
    location: str
    block_type: str = "text"
    paragraph: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_count: int | None = None
    headers: tuple[str, ...] = ()
    cells: tuple[str, ...] = ()
    structure_status: str = "regular"
    structure_warnings: tuple[str, ...] = ()


def extract_text_document(path: Path, project: str) -> list[ExtractedTextBlock]:
    """Extract non-empty blocks with stable source locations."""
    suffix = path.suffix.casefold()
    if suffix == ".txt":
        return _txt_blocks(path, project)
    if suffix == ".docx":
        return _docx_blocks(path, project)
    raise ValueError(f"Unsupported text document: {path.name}")


def save_extracted_text(
    output_directory: Path, source: Path, project: str, blocks: list[ExtractedTextBlock]
) -> tuple[Path, Path]:
    """Persist downstream-readable Markdown plus a machine-readable provenance map."""
    output_directory.mkdir(parents=True, exist_ok=True)
    markdown_path = output_directory / f"{source.stem}.md"
    provenance_path = output_directory / f"{source.stem}.provenance.json"
    sections = [f"# Extracted text: {source.name}", "", f"Project: {project}", ""]
    for index, block in enumerate(blocks, 1):
        sections.extend([
            f"## Source block {index}", "",
            f"- Original filename: {block.original_filename}",
            f"- Project: {block.project}",
            f"- Document location: {block.location}",
            f"- Block type: {block.block_type}",
            f"- Structure status: {block.structure_status}",
        ])
        if block.table_index is not None:
            sections.append(f"- Table index: {block.table_index}")
        if block.row_index is not None:
            sections.append(f"- Row index: {block.row_index}")
        if block.column_count is not None:
            sections.append(f"- Column count: {block.column_count}")
        if block.headers:
            sections.append("- Headers: " + " | ".join(block.headers))
        if block.cells:
            sections.append("- Cells: " + " | ".join(block.cells))
        if block.structure_warnings:
            sections.append("- Structure warnings: " + "; ".join(block.structure_warnings))
        sections.extend(["", block.text, ""])
    markdown_path.write_text("\n".join(sections), encoding="utf-8")
    provenance_path.write_text(
        json.dumps({"source_document": source.name, "project": project,
                    "blocks": [asdict(block) for block in blocks]}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return markdown_path, provenance_path


def _txt_blocks(path: Path, project: str) -> list[ExtractedTextBlock]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    blocks: list[ExtractedTextBlock] = []
    start: int | None = None
    content: list[str] = []
    for number, line in enumerate([*lines, ""], 1):
        if line.strip():
            if start is None:
                start = number
            content.append(line)
        elif content:
            end = number - 1
            location = f"lines {start}-{end}" if start != end else f"line {start}"
            blocks.append(ExtractedTextBlock(
                "\n".join(content).strip(), path.name, project, location,
                block_type="text",
                line_start=start,
                line_end=end,
            ))
            start, content = None, []
    return blocks


def _docx_blocks(path: Path, project: str) -> list[ExtractedTextBlock]:
    try:
        with zipfile.ZipFile(path) as archive:
            document = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as error:
        raise ValueError(f"'{path.name}' is not a readable DOCX file") from error

    root = ElementTree.fromstring(document)
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = root.find(f"{ns}body")
    if body is None:
        return []

    blocks: list[ExtractedTextBlock] = []
    paragraph_number = 0
    table_number = 0

    for child in list(body):
        if child.tag == f"{ns}p":
            paragraph_number += 1
            text = _paragraph_text(child, ns)
            if text:
                blocks.append(ExtractedTextBlock(
                    text, path.name, project, f"paragraph {paragraph_number}",
                    block_type="paragraph",
                    paragraph=paragraph_number,
                ))
            continue

        if child.tag != f"{ns}tbl":
            continue

        table_number += 1
        rows = list(child.findall(f"{ns}tr"))
        if not rows:
            continue

        parsed_rows = [_table_row(row, ns) for row in rows]
        header_cells = tuple(parsed_rows[0]["cells"])
        header_regular = (
            bool(header_cells)
            and len(set(x.casefold() for x in header_cells if x)) == len([x for x in header_cells if x])
            and _looks_like_header(header_cells)
        )
        expected_columns = len(header_cells)

        for row_index, row in enumerate(parsed_rows, 1):
            cells = tuple(row["cells"])
            warnings = list(row["warnings"])
            if row_index == 1:
                warnings.append("header_row")
            if expected_columns and len(cells) != expected_columns:
                warnings.append("irregular_column_count")
            if any(not cell for cell in cells):
                warnings.append("blank_cell")
            if not header_regular:
                warnings.append("ambiguous_or_missing_headers")

            structure_status = "ambiguous" if any(
                warning in {
                    "horizontal_merge", "vertical_merge", "nested_table",
                    "irregular_column_count", "ambiguous_or_missing_headers"
                }
                for warning in warnings
            ) else "regular"

            # Header rows are preserved for provenance but are not represented
            # as data relationships. Data rows are rendered as explicit
            # header=value pairs only when the structure is regular.
            repeated_header = (
                row_index > 1
                and len(cells) == len(header_cells)
                and tuple(x.casefold() for x in cells) == tuple(x.casefold() for x in header_cells)
            )
            if row_index == 1 or repeated_header:
                rendered = " | ".join(cells)
                block_type = "table_header" if row_index == 1 else "table_repeated_header"
                if repeated_header:
                    warnings.append("repeated_header")
            elif structure_status == "regular" and expected_columns == len(cells):
                rendered = " | ".join(
                    f"{header_cells[i]}: {cell}"
                    for i, cell in enumerate(cells)
                    if header_cells[i] and cell
                )
                block_type = "table_row"
            else:
                rendered = " | ".join(cells)
                block_type = "table_row_ambiguous"

            if not rendered.strip():
                continue

            blocks.append(ExtractedTextBlock(
                rendered,
                path.name,
                project,
                f"table {table_number} row {row_index}",
                block_type=block_type,
                table_index=table_number,
                row_index=row_index,
                column_count=len(cells),
                headers=header_cells if row_index > 1 else (),
                cells=cells,
                structure_status=structure_status,
                structure_warnings=tuple(dict.fromkeys(warnings)),
            ))
    return blocks


def _looks_like_header(cells: tuple[str, ...]) -> bool:
    """Require explicit schema-like labels before joining table columns."""
    labels = " ".join(cells).casefold()
    header_terms = (
        "unit", "type", "area", "sqm", "m²", "m2", "price",
        "tower", "building", "floor", "bedroom", "bathroom",
        "location", "amenity", "developer", "project",
    )
    textual = sum(bool(re.search(r"[A-Za-z]", cell)) and not re.search(r"\d", cell) for cell in cells)
    return textual >= max(1, len(cells) // 2) and any(term in labels for term in header_terms)


def _paragraph_text(paragraph: ElementTree.Element, namespace: str) -> str:
    text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
    return re.sub(r"[ \t]+", " ", text).strip()


def _table_row(row: ElementTree.Element, namespace: str) -> dict[str, object]:
    cells: list[str] = []
    warnings: list[str] = []
    for cell in row.findall(f"{namespace}tc"):
        text = " ".join(
            part for part in (
                _paragraph_text(paragraph, namespace)
                for paragraph in cell.findall(f".//{namespace}p")
            )
            if part
        ).strip()
        cells.append(text)

        if cell.find(f".//{namespace}tbl") is not None:
            warnings.append("nested_table")
        props = cell.find(f"{namespace}tcPr")
        if props is not None:
            grid_span = props.find(f"{namespace}gridSpan")
            if grid_span is not None:
                raw = grid_span.attrib.get(f"{namespace}val")
                try:
                    if int(raw or "1") > 1:
                        warnings.append("horizontal_merge")
                except ValueError:
                    warnings.append("horizontal_merge")
            if props.find(f"{namespace}vMerge") is not None:
                warnings.append("vertical_merge")
    return {"cells": cells, "warnings": warnings}

