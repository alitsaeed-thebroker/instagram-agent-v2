"""Read-only, evidence-based completeness audit for project knowledge."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from src.knowledge.schema import IDENTITY_FIELDS, ProjectKnowledge

VISUAL_TAXONOMY = (
    "project_hero", "villa_exterior", "villa_interior", "building_exterior",
    "building_interior", "site_plan", "masterplan", "villa_layout", "floor_plan",
    "community_services", "greenery_landscape", "amenities", "location_map",
    "project_entrance", "streetscape", "clubhouse", "swimming_pool",
    "commercial_area", "parking", "technical_plan", "architectural_detail",
    "other_verified_project_visual", "unknown",
)


def audit_project(project: str, root: Path) -> tuple[Path, Path, dict[str, Any]]:
    """Compare source/document/structured/fused artifacts without mutating them."""
    output = root / "output"
    analysis = _read(output / "inventory" / f"{project}-document-analysis.json")
    if not analysis:
        analysis = _read(output / "reports" / f"{project}-document-analysis.json")
    knowledge_path = output / "knowledge" / f"{project}.json"
    knowledge_raw = _read(knowledge_path)
    knowledge = ProjectKnowledge.from_dict(knowledge_raw) if knowledge_raw else ProjectKnowledge()
    intelligence = _read(output / "asset-intelligence" / f"{project}-asset-intelligence.json")
    docs = analysis.get("documents", [])
    assets = intelligence.get("assets", [])
    identity = knowledge.project_identity.__dict__
    identity_coverage = {
        name: {
            "status": "available" if str(value).strip() else "unavailable",
            "provenance_count": len(knowledge.fact_provenance.get(f"project_identity.{name}", [])),
        } for name, value in identity.items()
    }
    category_counts = Counter(_canonical_visual(a) for a in assets)
    categories = _knowledge_categories(knowledge_raw)
    visual_pages = {(a.get("source_document"), a.get("source_page")) for a in assets if a.get("source_page")}
    text_pages = sum(_markdown_page_stats(output / "markdown" / project)[0])
    total_pages = sum(int(d.get("page_count", 0)) for d in docs)
    gaps = []
    if total_pages and text_pages < total_pages:
        gaps.append(f"{total_pages - text_pages} source page(s) have no extracted text representation")
    unrepresented = sorted(k for k, v in category_counts.items() if v and k != "unknown" and not _represented(k, knowledge_raw))
    if unrepresented:
        gaps.append("Visual categories not represented in structured knowledge: " + ", ".join(unrepresented))
    report = {
        "schema_version": "2.0.0", "audit_type": "knowledge_completeness", "project": project,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_analysis": {"documents_analyzed": len(docs), "document_names": [d.get("file_identifier") for d in docs],
            "pages_analyzed": total_pages, "pages_containing_text": text_pages,
            "pages_containing_visual_information": len(visual_pages), "tables_detected": sum(int(d.get("tables_detected", 0)) for d in docs)},
        "structured_knowledge": {"categories_discovered": categories, "categories_preserved": categories},
        "project_identity": {"values": identity, "coverage": identity_coverage,
            "complete": all(str(identity[x]).strip() for x in IDENTITY_FIELDS)},
        "visual_taxonomy": {"supported_categories": list(VISUAL_TAXONOMY), "counts": dict(sorted(category_counts.items())),
            "classified_assets": sum(v for k, v in category_counts.items() if k != "unknown"), "unknown_assets": category_counts["unknown"]},
        "provenance": {"facts_with_provenance": sum(bool(v) for v in knowledge.fact_provenance.values()),
            "identity_fields_with_provenance": sum(identity_coverage[x]["provenance_count"] > 0 for x in IDENTITY_FIELDS)},
        "potentially_lost_information": gaps, "incomplete_categories": [x for x in IDENTITY_FIELDS if not identity[x]],
        "visual_information_not_represented": unrepresented,
        "measurement_note": "Counts come from persisted source, extraction, knowledge, and asset artifacts; no arbitrary percentage is calculated.",
    }
    commercial = knowledge.commercial_intelligence
    if commercial:
        report["commercial_intelligence"] = {
            "contract_role": commercial.get("contract_role"),
            "pricing": commercial.get("pricing", {}).get("status", "unavailable"),
            "payment_plan": "not_supported_by_policy",
            **commercial.get("audit", {}),
        }
    destination = output / "reports" / f"{project}-knowledge-audit.json"
    human = output / "reports" / f"{project}-knowledge-audit.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    human.write_text(_human(report), encoding="utf-8")
    return human, destination, report


def _canonical_visual(asset: dict[str, Any]) -> str:
    explicit = str(asset.get("visual_category") or "")
    if explicit in VISUAL_TAXONOMY: return explicit
    kind = str(asset.get("asset_type") or "unknown")
    subtype = " ".join((str(asset.get("asset_subtype") or ""), str(asset.get("dominant_subject") or ""))).casefold()
    if kind == "exterior": return "villa_exterior" if "villa" in subtype else "building_exterior"
    if kind in {"interior", "residential_space"}: return "villa_interior" if "villa" in subtype else "building_interior"
    return {"floorplan":"floor_plan", "garden_landscape":"greenery_landscape", "amenity":"amenities",
        "street_access":"streetscape", "commercial_space":"commercial_area", "diagram":"technical_plan",
        "infographic":"technical_plan", "aerial_view":"project_hero"}.get(kind, kind if kind in VISUAL_TAXONOMY else "unknown")


def _knowledge_categories(data: dict[str, Any]) -> list[str]:
    return sorted(k for k, v in data.items() if k not in {"fact_provenance"} and bool(v) and (not isinstance(v, dict) or any(bool(x) for x in v.values())))


def _markdown_page_stats(folder: Path) -> tuple[list[int], int]:
    counts=[]
    for path in folder.glob("*.md") if folder.is_dir() else []:
        text=path.read_text(encoding="utf-8", errors="replace")
        sections=re.split(r"(?m)^## Page \d+\s*$", text)[1:]
        counts.append(sum(bool(x.strip()) for x in sections))
    return counts, len(counts)


def _represented(category: str, data: dict[str, Any]) -> bool:
    blob=json.dumps(data, ensure_ascii=False).casefold().replace("_", " ")
    return category.replace("_", " ") in blob or (category == "amenities" and bool(data.get("amenities")))


def _read(path: Path) -> dict[str, Any]:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def _human(r: dict[str, Any]) -> str:
    s=r["source_analysis"]; identity=r["project_identity"]["values"]; visual=r["visual_taxonomy"]
    lines=[f"KNOWLEDGE COMPLETENESS AUDIT — {r['project']}", "", "PROJECT IDENTITY"]
    lines += [f"{k}: {identity[k] or 'UNAVAILABLE'}" for k in IDENTITY_FIELDS]
    lines += ["", "SOURCE ANALYSIS", f"Documents analyzed: {s['documents_analyzed']}", f"Pages analyzed: {s['pages_analyzed']}", f"Pages containing text: {s['pages_containing_text']}", f"Visual-information pages: {s['pages_containing_visual_information']}", "", "VISUAL TAXONOMY"]
    lines += [f"{k}: {v}" for k,v in visual["counts"].items()]
    lines += ["", "POTENTIAL GAPS"] + ([f"- {x}" for x in r["potentially_lost_information"]] or ["- None detected by measurable checks"])
    return "\n".join(lines)+"\n"
