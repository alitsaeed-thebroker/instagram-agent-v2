"""Content-evidence classification of real-estate source documents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
import logging
import os
import re
from typing import Callable


class DocumentType(StrEnum):
    CATALOGUE = "Catalogue"
    BROCHURE = "Brochure"
    PRESENTATION = "Presentation"
    MASTER_PLAN = "Master Plan"
    FLOOR_PLANS = "Floor Plans"
    PRICE_LIST = "Price List"
    PAYMENT_PLAN = "Payment Plan"
    LOCATION_MAP = "Location Map"
    TECHNICAL_SPECIFICATIONS = "Technical Specifications"
    LIFESTYLE_GALLERY = "Lifestyle Gallery"
    ARCHITECTURAL_RENDER_COLLECTION = "Architectural Render Collection"
    LEGAL_DOCUMENT = "Legal Document"
    CONTRACT = "Contract"
    SALES_OFFER = "Sales Offer"
    PROJECT_NOTES = "Project Notes"
    CONSTRUCTION_UPDATE = "Construction Update"
    INVESTMENT_DOCUMENT = "Investment Document"
    BRAND_GUIDELINES = "Brand Guidelines"
    MIXED_DOCUMENT = "Mixed Document"
    UNKNOWN = "Unknown"
    OTHER = "Unknown"  # Backward-compatible alias.
    FAQ = "FAQ"
    LOCATION_GUIDE = "Location Map"  # Backward-compatible alias.


@dataclass(frozen=True)
class DocumentTypeDefinition:
    document_type: DocumentType
    content_phrases: tuple[str, ...]
    roles: tuple[str, ...]

    @property
    def aliases(self) -> tuple[str, ...]:
        """Compatibility name; these are content phrases, never filename aliases."""
        return self.content_phrases

    @property
    def keywords(self) -> tuple[str, ...]:
        return self.content_phrases


DOCUMENT_TYPE_REGISTRY: tuple[DocumentTypeDefinition, ...] = (
    DocumentTypeDefinition(DocumentType.PRICE_LIST, ("price list", "unit price", "starting price", "price per sqm", "currency", "total price", "price schedule"), ("Contains pricing", "Contains unit schedules")),
    DocumentTypeDefinition(DocumentType.PAYMENT_PLAN, ("payment plan", "down payment", "installment", "payment schedule", "payment due", "handover payment"), ("Contains payment plan",)),
    DocumentTypeDefinition(DocumentType.SALES_OFFER, ("sales offer", "limited offer", "offer valid until", "promotional price"), ("Contains commercial offer",)),
    DocumentTypeDefinition(DocumentType.CONTRACT, ("sale and purchase agreement", "purchase contract", "contract price", "contractual payment"), ("Contains contractual terms",)),
    DocumentTypeDefinition(DocumentType.PROJECT_NOTES, ("project notes", "internal notes", "sales notes"), ("Contains internal project notes",)),
    DocumentTypeDefinition(DocumentType.CONSTRUCTION_UPDATE, ("construction update", "construction progress", "work completed"), ("Contains construction update",)),
    DocumentTypeDefinition(DocumentType.INVESTMENT_DOCUMENT, ("investment memorandum", "investment return", "rental yield", "capital appreciation"), ("Contains investment information",)),
    DocumentTypeDefinition(DocumentType.FLOOR_PLANS, ("floor plan", "unit plan", "bedroom", "bathroom", "gross area", "net area", "sqm"), ("Contains unit layouts",)),
    DocumentTypeDefinition(DocumentType.MASTER_PLAN, ("master plan", "site layout", "plot plan", "site plan", "land use"), ("Contains masterplan",)),
    DocumentTypeDefinition(DocumentType.LOCATION_MAP, ("location map", "minutes from", "nearby", "connectivity", "distance to"), ("Contains location information",)),
    DocumentTypeDefinition(DocumentType.TECHNICAL_SPECIFICATIONS, ("technical specifications", "materials", "finishes", "specification", "construction system"), ("Contains specifications",)),
    DocumentTypeDefinition(DocumentType.BRAND_GUIDELINES, ("brand guidelines", "logo usage", "color palette", "typography", "clear space"), ("Contains branding assets",)),
    DocumentTypeDefinition(DocumentType.LEGAL_DOCUMENT, ("terms and conditions", "legal notice", "disclaimer", "legal agreement", "liability"), ("Contains legal information",)),
    DocumentTypeDefinition(DocumentType.LIFESTYLE_GALLERY, ("lifestyle", "gallery", "community life", "resident experience"), ("Contains lifestyle imagery",)),
    DocumentTypeDefinition(DocumentType.ARCHITECTURAL_RENDER_COLLECTION, ("architectural renders", "artist impression", "exterior render", "interior render"), ("Contains architectural renders",)),
    DocumentTypeDefinition(DocumentType.BROCHURE, ("brochure", "project overview", "discover", "residences", "amenities"), ("Contains marketing text", "Contains amenities")),
    DocumentTypeDefinition(DocumentType.CATALOGUE, ("catalogue", "project overview", "unit types", "amenities", "architecture", "developer"), ("Contains marketing text", "Contains amenities")),
    DocumentTypeDefinition(DocumentType.PRESENTATION, ("presentation", "investment opportunity", "agenda", "project introduction", "sales deck"), ("Contains marketing text",)),
    DocumentTypeDefinition(DocumentType.FAQ, ("frequently asked questions", "questions and answers"), ("Contains marketing text",)),
)


@dataclass(frozen=True)
class ClassificationResult:
    document_type: DocumentType
    confidence: float
    classification_method: str
    reason: str
    evidence: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    fallback_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["classification"] = self.document_type.value
        data["document_type"] = self.document_type.value
        data["evidence"] = list(self.evidence)
        data["roles"] = list(self.roles)
        return data


AiClassifier = Callable[[str, str, tuple[DocumentTypeDefinition, ...]], ClassificationResult | None]


class DocumentClassifier:
    """Classify only from extracted content; filename is traceability-only."""

    def __init__(self, registry: tuple[DocumentTypeDefinition, ...] = DOCUMENT_TYPE_REGISTRY, ai_classifier: AiClassifier | None = None) -> None:
        self.registry = registry
        self.ai_classifier = ai_classifier or _classify_with_openai

    def classify(self, filename: str, content: str = "") -> ClassificationResult:
        del filename  # Explicitly prevent filename evidence from entering classification.
        normalized = _normalize(content)
        scored: list[tuple[float, DocumentTypeDefinition, tuple[str, ...]]] = []
        title = first_page_title(content)
        normalized_title = _normalize(title)
        for definition in self.registry:
            matches = tuple(phrase for phrase in definition.content_phrases if _contains_phrase(normalized, _normalize(phrase)))
            title_matches = tuple(phrase for phrase in definition.content_phrases if _contains_phrase(normalized_title, _normalize(phrase)))
            distinct = len(set(matches))
            score = min(0.96, (0.72 if title_matches else 0.0) + min(0.84, distinct * 0.18))
            if distinct:
                evidence = tuple([*(f'Heading/title contains "{item}"' for item in title_matches), *(f'Content contains "{item}"' for item in matches if item not in title_matches)])
                scored.append((score, definition, evidence))
        scored.sort(key=lambda item: item[0], reverse=True)
        if scored and scored[0][0] >= 0.70:
            top_score, top, evidence = scored[0]
            if len(scored) > 1 and scored[1][0] >= 0.75 and abs(top_score - scored[1][0]) <= 0.08:
                combined_roles = tuple(dict.fromkeys((*top.roles, *scored[1][1].roles)))
                combined_evidence = tuple((*evidence, *scored[1][2]))
                return ClassificationResult(DocumentType.MIXED_DOCUMENT, min(top_score, scored[1][0]), "content", "Multiple strong content roles detected", combined_evidence, combined_roles)
            return ClassificationResult(top.document_type, top_score, "content", "Classification derived from document contents", evidence, top.roles)
        fallback_error = None
        try:
            ai_result = self.ai_classifier("", content, self.registry) if normalized else None
        except Exception as exc:
            # Keep the failure machine-readable, without raw service payloads.
            fallback_error = type(exc).__name__
            logging.getLogger(__name__).warning("Content classification fallback failed (%s); classification remains Unknown", fallback_error)
            ai_result = None
        if ai_result is not None and ai_result.confidence >= 0.70:
            return ai_result
        return ClassificationResult(DocumentType.UNKNOWN, 0.0, "content", "Insufficient content evidence; classification left Unknown", (), discover_roles(content), fallback_error)


def discover_roles(content: str) -> tuple[str, ...]:
    normalized = _normalize(content)
    roles = []
    for definition in DOCUMENT_TYPE_REGISTRY:
        if any(_contains_phrase(normalized, _normalize(phrase)) for phrase in definition.content_phrases):
            roles.extend(definition.roles)
    return tuple(dict.fromkeys(roles))


def classify_document(filename: str, content: str = "") -> DocumentType:
    return DocumentClassifier().classify(filename, content).document_type


def first_page_title(content: str) -> str:
    first_page = re.split(r"^##\s+Page\s+2\b", content, maxsplit=1, flags=re.IGNORECASE | re.MULTILINE)[0]
    for line in first_page.splitlines():
        value = line.strip().lstrip("#").strip()
        if value and not re.fullmatch(r"(?:extracted text:.*|page\s+1)", value, re.IGNORECASE):
            return value
    return ""


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(phrase) and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _classify_with_openai(_filename: str, content: str, registry: tuple[DocumentTypeDefinition, ...]) -> ClassificationResult | None:
    """Use content-only AI fallback; filename is intentionally ignored."""
    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError:
        return None
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    types = [definition.document_type.value for definition in registry]
    try:
        response = OpenAI(api_key=api_key).responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            instructions="Return JSON with classification, confidence, evidence, and roles. Evidence must contain verbatim nonempty quotations from the supplied content. Use only supplied document content. If confidence is below 0.70 return Unknown. Never use or request a filename.",
            input=f"Document content:\n{content[:12000]}\n\nAllowed classifications: {', '.join(types)}",
            text={"format": {"type": "json_schema", "name": "document_classification", "strict": True, "schema": {
                "type": "object", "properties": {
                    "classification": {"type": "string", "enum": [*types, "Unknown"]},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "roles": {"type": "array", "items": {"type": "string"}}
                }, "required": ["classification", "confidence", "evidence", "roles"], "additionalProperties": False
            }}},
        )
        data = json.loads(response.output_text)
        if not isinstance(data, dict) or set(data) != {"classification", "confidence", "evidence", "roles"}:
            raise ValueError("Invalid classification response shape")
        classification = DocumentType(data["classification"])
        if isinstance(data["confidence"], bool) or not isinstance(data["confidence"], (int, float)):
            raise ValueError("Invalid classification confidence")
        confidence = float(data["confidence"])
        if classification is DocumentType.UNKNOWN or not 0.70 <= confidence <= 1.0:
            return None
        if not isinstance(data["evidence"], list) or not data["evidence"] or any(not isinstance(item, str) or not item.strip() or _normalize(item) not in _normalize(content[:12000]) for item in data["evidence"]):
            raise ValueError("Classification lacks exact content evidence")
        allowed_roles = {role for definition in registry for role in definition.roles}
        if not isinstance(data["roles"], list) or any(item not in allowed_roles for item in data["roles"]):
            raise ValueError("Invalid classification roles")
        evidence = tuple(data["evidence"])
        roles = tuple(data["roles"])
        return ClassificationResult(classification, confidence, "ai_content", "AI content analysis", evidence, roles)
    except Exception:
        # The caller converts parse/transport failures into an auditable Unknown.
        raise
