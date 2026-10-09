"""Project-agnostic semantic linking from full source inventories to content topics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


LINKER_VERSION = "1.0.0"
SUPPORTED_TOPICS = ("unit_information", "location", "features", "property_types", "lifestyle", "investment_facts")
TOPIC_LIMITS = {"unit_information": 6, "location": 3, "features": 4, "property_types": 4, "lifestyle": 4, "investment_facts": 3}
TOPIC_TYPES = {
    "unit_information": {"floor_plan", "unit_plan", "technical_drawing", "full_project_site_plan"},
    "location": {"map", "masterplan", "full_project_site_plan"},
    "features": {"exterior_render", "interior_render", "amenity", "landscape", "brochure_graphic", "unknown"},
    "property_types": {"floor_plan", "unit_plan", "exterior_render", "interior_render", "technical_drawing"},
    "lifestyle": {"lifestyle", "landscape", "amenity", "exterior_render", "interior_render"},
    "investment_facts": {"map", "brochure_graphic", "text_heavy", "masterplan", "full_project_site_plan"},
}
TOPIC_TERMS = {
    "unit_information": ("floor plan", "floor_plan", "unit plan", "layout", "buildup", "built up", "area", "bedroom", "ground floor", "first floor", "second floor"),
    "location": ("location", "map", "vicinity", "access", "road", "airport", "citadel", "minutes", "landmark"),
    "features": ("features", "smart home", "charging", "electric vehicle", "material", "facade", "window", "kitchen", "landscap", "parking", "heating", "cooling", "playground"),
    "property_types": ("property type", "unit type", "villa type", "apartment", "office", "retail", "commercial", "plot", "hospitality", "bedroom", "layout", "floor plan"),
    "lifestyle": ("lifestyle", "community", "family", "outdoor living", "recreation", "clubhouse", "pool", "wellness", "walking", "park", "playground", "tennis", "horse", "cafe"),
    "investment_facts": ("investment", "payment", "return", "roi", "commercial value", "capital appreciation", "rental", "yield"),
}


def link_visual_topics(
    records: list[dict[str, Any]], knowledge: dict[str, Any], *, protected_paths: set[str] | None = None, limit: int = 10
) -> dict[str, Any]:
    """Score the complete canonical inventory and link evidence-backed visual candidates."""
    protected = protected_paths or set()
    canonical = [record for record in records if not record.get("likely_duplicate") and record.get("width") and record.get("height")]
    results: dict[str, Any] = {"linker_version": LINKER_VERSION, "visuals_evaluated": len(canonical), "topics": {}}
    used = set(protected)
    for topic in SUPPORTED_TOPICS:
        facts = _topic_facts(knowledge, topic)
        candidates = [_score(record, topic, facts) for record in canonical]
        candidates = [candidate for candidate in candidates if candidate["candidate"]]
        candidates.sort(key=lambda item: (-item["semantic_topic_score"], -item["combined_score"], int(item.get("source_page") or 9999), str(item.get("path"))))
        selected: list[dict[str, Any]] = []
        for candidate in candidates:
            reason = _rejection(candidate, topic, facts, used)
            candidate["link_status"] = "rejected" if reason else "approved"
            candidate["link_rejection_reason"] = reason
            if reason:
                continue
            selected.append(candidate);used.add(str(candidate["path"]))
            if len(selected) >= min(limit, TOPIC_LIMITS[topic]):
                break
        if not selected:
            reason = "no_source_visual_found" if not candidates else _topic_empty_reason(candidates, topic, facts)
        else:
            reason = None
        results["topics"][topic] = {"candidates": candidates, "selected": selected, "status": "renderable" if selected else "planned_not_renderable", "reason": reason}
    return results


def _score(record: dict[str, Any], topic: str, facts: list[dict[str, Any]]) -> dict[str, Any]:
    kind = str(record.get("source_image_type") or "unknown")
    context = _context(record)
    terms = TOPIC_TERMS[topic]
    matched = [term for term in terms if term in context]
    evidence = _knowledge_links(record, facts, matched)
    type_match = kind in TOPIC_TYPES[topic]
    direct_type = (
        topic == "unit_information" and kind in {"floor_plan", "unit_plan", "technical_drawing"}
        or topic == "location" and kind == "map"
        or topic == "lifestyle" and kind in {"lifestyle", "landscape"}
    )
    page_context = bool(record.get("source_section") or record.get("page_title") or record.get("nearby_text"))
    semantic = min(1.0, (.46 if direct_type else .25 if type_match else 0) + min(.42, .105 * len(matched)) + (.10 if page_context and matched else 0) + (.15 if evidence else 0))
    quality = max(0.0, min(1.0, float(record.get("visual_quality_score") or 0) / 100))
    confidence = max(0.0, min(1.0, float(record.get("source_confidence") or .75)))
    combined = .55 * semantic + .22 * quality + .15 * confidence + .08 * (1.0 if not record.get("likely_duplicate") else 0.0)
    result = dict(record)
    result.update(
        candidate=bool(type_match or matched), topic=topic, matched_context_terms=matched,
        semantic_topic_score=round(semantic, 4), visual_quality_component=round(quality, 4),
        source_confidence_component=round(confidence, 4), combined_score=round(combined, 4),
        page_context_used=page_context, verified_knowledge_linkage=evidence,
        selection_rationale=f"{kind} on page {record.get('source_page') or 'unknown'} matched {', '.join(matched) or 'the topic visual type'}; semantic {semantic:.2f} outweighed generic visual quality {quality:.2f}."
    )
    return result


def _rejection(candidate: dict[str, Any], topic: str, facts: list[dict[str, Any]], used: set[str]) -> str | None:
    if candidate.get("likely_duplicate"):
        return "duplicate_or_near_duplicate"
    if str(candidate.get("path")) in used and not (topic == "property_types" and candidate.get("verified_knowledge_linkage")):
        return "already_used_by_stronger_story"
    if candidate["semantic_topic_score"] < .52:
        return "no_semantically_relevant_visual"
    if candidate["visual_quality_component"] < .35:
        return "source_visual_below_quality_threshold"
    kind = candidate.get("source_image_type")
    if topic == "features" and (not facts or not candidate["verified_knowledge_linkage"]):
        return "feature_not_supported_by_verified_knowledge"
    if topic == "property_types" and not candidate["verified_knowledge_linkage"]:
        return "property_type_not_supported_by_verified_knowledge"
    if topic == "lifestyle" and kind == "amenity" and not any(x in candidate["matched_context_terms"] for x in ("lifestyle", "community", "family", "recreation", "walking", "outdoor living")):
        return "facility_only_not_lifestyle_experience"
    if topic == "investment_facts" and (not _investment_supported(facts) or not candidate["verified_knowledge_linkage"]):
        return "no_explicit_investment_fact_support"
    return None


def _topic_empty_reason(candidates: list[dict[str, Any]], topic: str, facts: list[dict[str, Any]]) -> str:
    if topic == "investment_facts" and not _investment_supported(facts):
        return "no_explicit_investment_fact_support"
    reasons = [item.get("link_rejection_reason") for item in candidates if item.get("link_rejection_reason")]
    if reasons and all(reason == "source_visual_below_quality_threshold" for reason in reasons):
        return "source_visual_below_quality_threshold"
    if reasons and all(reason == "feature_not_supported_by_verified_knowledge" for reason in reasons):
        return "no_semantically_relevant_visual"
    return "no_semantically_relevant_visual"


def _context(record: dict[str, Any]) -> str:
    values = [record.get(key) for key in ("source_image_type", "deep_image_type", "deep_description", "source_section", "page_title", "nearby_text", "caption", "related_property_type", "deep_marketing_topic")]
    return " ".join(str(value or "").replace("_", " ").casefold() for value in values)


def _knowledge_links(record: dict[str, Any], facts: list[dict[str, Any]], matched: list[str]) -> list[dict[str, Any]]:
    page = record.get("source_page");document = record.get("source_document");links=[]
    for fact in facts:
        value = str(fact.get("value") or fact.get("name") or fact.get("label") or fact.get("type") or fact.get("text") or fact.get("description") or "").strip()
        sources = fact.get("sources") or fact.get("source_pages") or []
        if fact.get("asset_id") == record.get("asset_id"):
            links.append({"value": value or str(fact.get("related_property_type") or fact.get("section") or "source visual"), "sources": [{"source_document": document, "source_page": page}], "relationship": "direct_asset"});continue
        same_page = any((source.get("source_page") or source.get("page")) == page and (not document or not (source.get("source_document") or source.get("document")) or (source.get("source_document") or source.get("document")) == document) for source in sources if isinstance(source, dict))
        overlap = any(term in value.casefold() for term in matched)
        if same_page or overlap:
            links.append({"value": value, "sources": sources, "relationship": "same_page" if same_page else "semantic_overlap"})
    return links[:8]


def _investment_supported(facts: list[dict[str, Any]]) -> bool:
    text = " ".join(str(fact.get("value") or fact.get("text") or "") for fact in facts).casefold()
    return any(term in text for term in TOPIC_TERMS["investment_facts"])


def _topic_facts(knowledge: dict[str, Any], topic: str) -> list[dict[str, Any]]:
    mapping = {
        "unit_information": knowledge.get("plans_and_layouts", []),
        "location": (knowledge.get("location") or {}).get("facts", []),
        "features": knowledge.get("features", []),
        "property_types": knowledge.get("unit_types") or knowledge.get("property_types") or knowledge.get("villa_types", []),
        "lifestyle": knowledge.get("lifestyle", []),
        "investment_facts": [fact for fact in knowledge.get("canonical_facts", []) if str(fact.get("category")) in {"investment", "commercial", "financial", "payment"}],
    }
    facts=[fact for fact in mapping.get(topic, []) if isinstance(fact, dict)];expanded=[]
    for fact in facts:
        nested=fact.get("value")
        if isinstance(nested,list) and all(isinstance(item,dict) for item in nested):expanded.extend(nested)
        else:expanded.append(fact)
    return expanded
