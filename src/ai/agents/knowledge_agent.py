"""OpenAI-backed extraction of structured project knowledge from Markdown."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from src.core.logger import get_logger
from src.knowledge.schema import ProjectKnowledge
from src.knowledge.storage import save_project_knowledge
from src.utils.config import MARKDOWN_OUTPUT_DIRECTORY

DEFAULT_MODEL = "gpt-4o-mini"


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    """Return a strict JSON Schema object with every field required."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


PROJECT_KNOWLEDGE_JSON_SCHEMA = _object(
    {
        "project_identity": _object(
            {
                "project_name": {"type": "string"},
                "developer_name": {"type": "string"},
                "project_type": {"type": "string"},
                "location": {"type": "string"},
            }
        ),
        "project": _object(
            {
                "name": {"type": "string"},
                "developer": {"type": "string"},
                "location": {"type": "string"},
                "description": {"type": "string"},
            }
        ),
        "branding": _object(
            {
                "name": {"type": "string"},
                "tagline": {"type": "string"},
                "tone_of_voice": {"type": "string"},
                "key_messages": {"type": "array", "items": {"type": "string"}},
            }
        ),
        "pricing": _object(
            {
                "currency": {"type": "string"},
                "starting_price": {"type": ["number", "null"]},
                "payment_plan": {"type": "string", "const": ""},
                "notes": {"type": "string"},
            }
        ),
        "units": {
            "type": "array",
            "items": _object(
                {
                    "name": {"type": "string"},
                    "bedrooms": {"type": ["integer", "null"]},
                    "bathrooms": {"type": ["integer", "null"]},
                    "area_sqm": {"type": ["number", "null"]},
                    "starting_price": {"type": ["number", "null"]},
                    "features": {"type": "array", "items": {"type": "string"}},
                }
            ),
        },
        "amenities": {"type": "array", "items": {"type": "string"}},
        "architecture": _object(
            {
                "style": {"type": "string"},
                "architect": {"type": "string"},
                "materials": {"type": "array", "items": {"type": "string"}},
                "design_features": {"type": "array", "items": {"type": "string"}},
            }
        ),
        "investment": _object(
            {
                "highlights": {"type": "array", "items": {"type": "string"}},
                "expected_return": {"type": "string"},
                "rental_potential": {"type": "string"},
                "completion_date": {"type": "string"},
            }
        ),
        "marketing": _object(
            {
                "target_audience": {"type": "array", "items": {"type": "string"}},
                "selling_points": {"type": "array", "items": {"type": "string"}},
                "calls_to_action": {"type": "array", "items": {"type": "string"}},
            }
        ),
    }
)


class KnowledgeAgent:
    """Extract a validated ``ProjectKnowledge`` JSON artifact from catalogue Markdown."""

    def __init__(self, model: str | None = None) -> None:
        self.logger = get_logger(__name__)
        self.model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

    def run(
        self,
        input_path: Path | None = None,
        *,
        output_directory: Path | None = None,
        output_filename: str | None = None,
        source_document: str | None = None,
        source_project: str | None = None,
        source_id: str | None = None,
        source_sha256: str | None = None,
        extraction_method: str = "openai_structured_extraction",
    ) -> Path | None:
        """Read the first Markdown file by default and save extracted knowledge."""
        markdown_path = input_path or self._first_markdown_file()
        if markdown_path is None:
            self.logger.error("No Markdown files were found in %s.", MARKDOWN_OUTPUT_DIRECTORY)
            return None

        self.logger.info("Reading catalogue Markdown: %s", markdown_path.name)
        try:
            markdown = markdown_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            self.logger.error("Could not read '%s': %s", markdown_path.name, error)
            return None
        if not markdown.strip():
            self.logger.error("Cannot extract knowledge from an empty Markdown file.")
            return None

        api_key = self._load_api_key()
        if not api_key:
            return None

        self.logger.info("Extracting structured project knowledge with %s...", self.model)
        try:
            response_text = self._request_knowledge(markdown, api_key)
        except Exception as error:  # The SDK exposes several transport/API error subclasses.
            self.logger.error("OpenAI API request failed: %s", error)
            return None

        self.logger.info("Validating returned knowledge JSON...")
        try:
            knowledge = ProjectKnowledge.from_json(response_text)
            _synchronize_identity(knowledge)
            knowledge.fact_provenance = _fact_provenance(
                knowledge,
                markdown,
                source_document=source_document or markdown_path.name,
                source_project=source_project or knowledge.project_identity.project_name or knowledge.project.name,
                source_id=source_id,
                source_sha256=source_sha256,
                extraction_method=extraction_method,
            )
            errors = knowledge.validate()
            if errors:
                raise ValueError("; ".join(errors))
        except (TypeError, ValueError) as error:
            self.logger.error("OpenAI returned invalid project knowledge: %s", error)
            return None

        filename = output_filename or _artifact_filename(knowledge.project.name)
        try:
            if output_directory is None:
                output_path = save_project_knowledge(knowledge, filename)
            else:
                output_path = save_project_knowledge(knowledge, filename, output_directory)
        except (OSError, ValueError) as error:
            self.logger.error("Could not save knowledge JSON: %s", error)
            return None

        self.logger.info("Knowledge extraction complete. Saved: %s", output_path)
        return output_path

    def _first_markdown_file(self) -> Path | None:
        try:
            files = sorted(
                (path for path in MARKDOWN_OUTPUT_DIRECTORY.iterdir() if path.is_file() and path.suffix.lower() == ".md"),
                key=lambda path: path.name.casefold(),
            )
        except OSError as error:
            self.logger.error("Could not read Markdown directory: %s", error)
            return None
        return files[0] if files else None

    def _load_api_key(self) -> str | None:
        try:
            from dotenv import load_dotenv
        except ImportError:
            self.logger.error("Missing dependency: install packages with 'python -m pip install -r requirements.txt'.")
            return None

        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self.logger.error("OPENAI_API_KEY is not set. Add it to the local .env file.")
            return None
        return api_key

    def _request_knowledge(self, markdown: str, api_key: str) -> str:
        """Request strict JSON from OpenAI's Responses API."""
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=self.model,
            instructions="""
You are a senior real-estate analyst with more than 20 years of international
residential and commercial development experience. Apply the judgment of a
luxury property marketing director, investment consultant, sales manager, and
architectural analyst. Your sole deliverable is one ProjectKnowledge JSON
object that conforms exactly to the supplied schema.

Work privately and methodically before producing the JSON:
1. Read the entire catalogue, including tables, captions, footnotes, and later
   pages. Do not start extracting from only the opening pages.
2. Build an internal evidence inventory of direct facts: project identity,
   developer, geography, status and dates, project and unit types, dimensions,
   approved price facts, amenities, architecture, materials, landmarks,
   access, views, and distinctive features.
3. Separate direct evidence from reasoned conclusions. Assess the confidence of
   every candidate as High, Medium, Low, or Unknown before deciding whether it
   belongs in the output.
4. Analyse the evidence for likely buyers, positioning, emotional benefits,
   unique selling propositions, architectural identity, and visual character.
   Include an analytical conclusion only where the catalogue provides a clear,
   specific basis for it.

Evidence rules are non-negotiable:
- Never invent, assume, complete, or embellish a fact. Do not use outside
  knowledge about the developer, area, market, country, or project.
- Populate project, branding, pricing, units, amenities, architecture, and
  investment fields only with direct catalogue facts or faithful, non-creative
  paraphrases of those facts. If the catalogue does not state a value, use the
  schema's empty value (empty string, empty list, or null).
- Treat a statement as High confidence only when it is explicit and unambiguous
  in the catalogue. Do not output Low or Unknown candidates as facts.
- The schema has no provenance or confidence fields. Keep scalar factual values
  clean (for example, use the project name, not a confidence annotation).
- Analytical content is permitted only in the existing marketing lists. Every
  marketing-list item must be self-contained and begin with either
  "[Fact | High]" for an explicit catalogue claim or
  "[Inference | Medium]" for a conservative conclusion supported by multiple
  direct facts. Never mix a fact and an inference in one item. Omit any
  conclusion that would be Low or Unknown confidence.
- Do not invent calls to action, campaign copy, image prompts, captions,
  recommendations, or facts that are absent from the catalogue. Leave
  calls_to_action empty unless a call to action is explicitly present.

Map the evidence carefully to the schema:
- project_identity: exactly project_name, developer_name, project_type, and
  location. Distinguish the developer from architect, contractor, consultant,
  operator, broker, and marketing brand. Use an empty string when unavailable.
- project: identity, developer, location, and a concise factual description.
- branding: only stated brand language, taglines, tone, and messages.
- pricing and units: commercial extraction is limited to price per square
  meter, unit total price, and unit starting price. Never extract, summarize,
  infer, or populate payment plans, installments, down payments, booking terms,
  discounts, financing terms, or payment schedules. Keep pricing.payment_plan
  as the required empty string. Preserve stated currencies, figures, areas,
  and unit distinctions; use null rather than guessing a number.
- amenities, architecture, and investment: record only catalogue-supported
  information.
- marketing: use the labelled fact/inference rule above for target audiences
  and selling points; do not add fields for unsupported concepts such as visual
  identity or confidence.

Return valid JSON only. Include every schema field, add no keys, use no Markdown,
and provide no explanation outside the JSON.
""",
            input=markdown,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "project_knowledge",
                    "strict": True,
                    "schema": PROJECT_KNOWLEDGE_JSON_SCHEMA,
                }
            },
        )
        if not response.output_text:
            raise ValueError("The API returned no JSON output")
        return response.output_text


def _artifact_filename(project_name: str) -> str:
    """Create a portable JSON filename from a validated project name."""
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", project_name)
    filename = re.sub(r"\s+", "-", filename).strip(" .-")
    return filename.casefold() or "project-knowledge"


def _synchronize_identity(knowledge: ProjectKnowledge) -> None:
    """Keep legacy consumers working while canonical identity remains authoritative."""
    identity = knowledge.project_identity
    knowledge.project.name = identity.project_name or knowledge.project.name
    knowledge.project.developer = identity.developer_name or knowledge.project.developer
    knowledge.project.location = identity.location or knowledge.project.location


def _fact_provenance(
    knowledge: ProjectKnowledge,
    markdown: str,
    *,
    source_document: str,
    source_project: str,
    source_id: str | None,
    source_sha256: str | None,
    extraction_method: str,
) -> dict[str, list[dict[str, Any]]]:
    """Build fact-level provenance only from source-supported evidence.

    Every record is bound to the exact knowledge path and extracted value. A
    value that cannot be grounded in a source block deliberately receives no
    provenance and therefore cannot become VERIFIED/marketing-eligible later.
    """
    blocks = _evidence_blocks(markdown)
    result: dict[str, list[dict[str, Any]]] = {}
    for path, value, support_kind in _knowledge_fact_values(knowledge):
        records: list[dict[str, Any]] = []
        for block in blocks:
            if str(block.get("structure_status") or "regular").casefold() != "regular":
                continue
            if str(block.get("block_type") or "").casefold() in {"table_header", "table_repeated_header"}:
                continue
            if not _block_supports_value(block["text"], value):
                continue
            excerpt = _evidence_excerpt(block["text"], value)
            evidence_id = _evidence_id(
                source_project, source_document, source_id, path, value,
                block.get("page"), block.get("line_range"), block.get("paragraph"),
                block.get("table_index"), block.get("row_index"),
            )
            record = {
                "evidence_id": evidence_id,
                "fact_path": path,
                "fact_value": value,
                "source_project": source_project,
                "source_file": source_document,
                "source_document": source_document,
                "source_id": source_id,
                "source_sha256": source_sha256,
                "page": block.get("page"),
                "source_page": block.get("page"),
                "line_range": block.get("line_range"),
                "paragraph": block.get("paragraph"),
                "table_index": block.get("table_index"),
                "row_index": block.get("row_index"),
                "block_type": block.get("block_type"),
                "structure_status": block.get("structure_status"),
                "structure_warnings": block.get("structure_warnings"),
                "source_text": excerpt,
                "source_text_reference": excerpt,
                "extraction_method": extraction_method,
                "support_status": "direct" if support_kind == "direct" else "inferred",
                "status": "supported" if support_kind == "direct" else "inferred",
                "confidence": "high" if support_kind == "direct" else "medium",
                "evidence_origin": "department1_source_evidence",
            }
            records.append(record)
        result[path] = _dedupe_provenance(records)

    # Identity aliases are kept synchronized for legacy readers, but provenance
    # remains attached to both canonical and legacy paths where the value exists.
    aliases = {
        "project.name": "project_identity.project_name",
        "project.developer": "project_identity.developer_name",
        "project.location": "project_identity.location",
    }
    for legacy_path, canonical_path in aliases.items():
        if canonical_path in result:
            result[legacy_path] = [dict(x, fact_path=legacy_path) for x in result[canonical_path]]
    return result


def _knowledge_fact_values(knowledge: ProjectKnowledge) -> list[tuple[str, Any, str]]:
    """Enumerate source-derived values without inventing schema relationships."""
    result: list[tuple[str, Any, str]] = []

    def add(path: str, value: Any, support_kind: str = "direct") -> None:
        if value is None or value == "" or value == []:
            return
        result.append((path, value, support_kind))

    identity = knowledge.project_identity
    for field in ("project_name", "developer_name", "project_type", "location"):
        add(f"project_identity.{field}", getattr(identity, field))

    for field in ("name", "developer", "location", "description"):
        add(f"project.{field}", getattr(knowledge.project, field))

    for field in ("name", "tagline", "tone_of_voice"):
        add(f"branding.{field}", getattr(knowledge.branding, field))
    for i, value in enumerate(knowledge.branding.key_messages):
        add(f"branding.key_messages[{i}]", value)

    for field in ("currency", "starting_price", "notes"):
        add(f"pricing.{field}", getattr(knowledge.pricing, field))

    for i, unit in enumerate(knowledge.units):
        for field in ("name", "bedrooms", "bathrooms", "area_sqm", "starting_price"):
            add(f"units[{i}].{field}", getattr(unit, field))
        for j, value in enumerate(unit.features):
            add(f"units[{i}].features[{j}]", value)

    for i, value in enumerate(knowledge.amenities):
        add(f"amenities[{i}]", value)

    for field in ("style", "architect"):
        add(f"architecture.{field}", getattr(knowledge.architecture, field))
    for field in ("materials", "design_features"):
        for i, value in enumerate(getattr(knowledge.architecture, field)):
            add(f"architecture.{field}[{i}]", value)

    for i, value in enumerate(knowledge.investment.highlights):
        add(f"investment.highlights[{i}]", value)
    for field in ("expected_return", "rental_potential", "completion_date"):
        add(f"investment.{field}", getattr(knowledge.investment, field))

    for field in ("target_audience", "selling_points", "calls_to_action"):
        for i, raw in enumerate(getattr(knowledge.marketing, field)):
            text = str(raw or "").strip()
            kind = "inferred" if text.casefold().startswith("[inference |") else "direct"
            # Strip the extraction-control label when searching source evidence;
            # the original stored value remains the fact value.
            search_value = re.sub(r"^\[(?:Fact|Inference)\s*\|\s*(?:High|Medium)\]\s*", "", text, flags=re.I)
            if search_value:
                result.append((f"marketing.{field}[{i}]", search_value, kind))
    return result


def _evidence_blocks(markdown: str) -> list[dict[str, Any]]:
    """Parse D1/source-reader Markdown into exact source locator blocks."""
    heading = re.compile(
        r"(?m)^## (?:(?:Page (?P<page>\d+))|(?:Lines (?P<line_start>\d+)-(?P<line_end>\d+))|(?:Paragraph (?P<paragraph>\d+))|Evidence)\s*$"
    )
    matches = list(heading.finditer(markdown))
    if matches:
        result = []
        for i, match in enumerate(matches):
            text = markdown[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(markdown)].strip()
            if not text:
                continue
            line_range = None
            if match.group("line_start"):
                line_range = (
                    match.group("line_start")
                    if match.group("line_start") == match.group("line_end")
                    else f"{match.group('line_start')}-{match.group('line_end')}"
                )
            result.append({
                "text": text,
                "page": int(match.group("page")) if match.group("page") else None,
                "line_range": line_range,
                "paragraph": int(match.group("paragraph")) if match.group("paragraph") else None,
                "table_index": None,
                "row_index": None,
                "block_type": "page_or_text",
                "structure_status": "regular",
            })
        return result

    source_blocks = list(re.finditer(r"(?m)^## Source block \d+\s*$", markdown))
    if source_blocks:
        result = []
        for i, match in enumerate(source_blocks):
            body = markdown[match.end():source_blocks[i + 1].start() if i + 1 < len(source_blocks) else len(markdown)]
            metadata: dict[str, str] = {}
            content_lines = []
            in_metadata = True
            for raw in body.splitlines():
                line = raw.strip()
                if in_metadata and line.startswith("- ") and ":" in line:
                    key, value = line[2:].split(":", 1)
                    metadata[key.strip().casefold()] = value.strip()
                    continue
                if line:
                    in_metadata = False
                    content_lines.append(raw)
            location = metadata.get("document location", "")
            paragraph = None
            line_range = None
            table_index = None
            row_index = None
            if m := re.fullmatch(r"paragraph (\d+)", location, re.I):
                paragraph = int(m.group(1))
            elif m := re.fullmatch(r"lines? ([\d-]+)", location, re.I):
                line_range = m.group(1)
            elif m := re.fullmatch(r"table (\d+) row (\d+)", location, re.I):
                table_index, row_index = int(m.group(1)), int(m.group(2))
            result.append({
                "text": "\n".join(content_lines).strip(),
                "page": None,
                "line_range": line_range,
                "paragraph": paragraph,
                "table_index": table_index,
                "row_index": row_index,
                "block_type": metadata.get("block type", "text"),
                "structure_status": metadata.get("structure status", "regular"),
                "headers": metadata.get("headers"),
                "cells": metadata.get("cells"),
                "structure_warnings": metadata.get("structure warnings"),
            })
        return [x for x in result if x["text"]]
    return [{"text": markdown, "page": None, "line_range": None, "paragraph": None,
             "table_index": None, "row_index": None, "block_type": "text", "structure_status": "regular"}]


def _normalize_evidence_text(value: Any) -> str:
    text = str(value if value is not None else "")
    text = text.replace(",", "")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def _block_supports_value(text: str, value: Any) -> bool:
    """Conservative source support check for strings and numeric values."""
    haystack = _normalize_evidence_text(text)
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        candidates = {str(value), f"{float(value):g}"}
        return any(re.search(rf"(?<!\d){re.escape(x)}(?!\d)", haystack) for x in candidates)

    needle = _normalize_evidence_text(value)
    if not needle:
        return False
    if needle in haystack:
        return True

    # A faithful short paraphrase may differ in punctuation/articles. Require
    # strong token coverage and at least one distinctive multi-character token.
    tokens = [x for x in re.findall(r"[\w]+", needle, flags=re.UNICODE) if len(x) >= 3]
    if len(tokens) < 2:
        return False
    present = sum(1 for token in set(tokens) if token in haystack)
    coverage = present / max(1, len(set(tokens)))
    return coverage >= 0.85


def _evidence_excerpt(text: str, value: Any, limit: int = 500) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    needle = _normalize_evidence_text(value)
    normalized = _normalize_evidence_text(clean)
    pos = normalized.find(needle) if needle else -1
    if pos < 0:
        return clean[:limit]
    start = max(0, pos - limit // 3)
    return clean[start:start + limit]


def _evidence_id(
    project: str,
    document: str,
    source_id: str | None,
    path: str,
    value: Any,
    page: int | None,
    line_range: str | None,
    paragraph: int | None,
    table_index: int | None = None,
    row_index: int | None = None,
) -> str:
    import hashlib
    payload = "|".join(str(x or "") for x in (
        project, document, source_id, path, value, page, line_range, paragraph, table_index, row_index
    ))
    return "ev_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _dedupe_provenance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for record in records:
        key = record.get("evidence_id")
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result

