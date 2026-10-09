"""Available-content inventory built only from extracted knowledge and visuals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.knowledge.schema import ProjectKnowledge
from src.utils.config import VISUAL_INVENTORY_OUTPUT_DIRECTORY


_CATEGORY_FIELDS = {
    "Exterior": "available_exterior_images", "Interior": "available_interior_images",
    "Amenity": "available_amenity_images", "Pool": "available_amenity_images",
    "Clubhouse": "available_amenity_images", "Garden": "available_amenity_images",
    "Lifestyle": "available_lifestyle_images", "Masterplan": "available_masterplans",
    "Floorplan": "available_floorplans", "Location Map": "available_location_maps",
    "Logo": "available_logos", "Developer Graphic": "available_decorative_graphics",
    "Text Page": "available_text_heavy_pages", "Architectural Detail": "available_diagrams",
}
_ALL_CATEGORY_FIELDS = tuple(dict.fromkeys(_CATEGORY_FIELDS.values()))


def create_available_content_inventory(
    knowledge_path: Path,
    source_manifest_path: Path,
    analysis_path: Path,
    output_root: Path = VISUAL_INVENTORY_OUTPUT_DIRECTORY,
) -> Path:
    """Describe the maximum producible content from authentic supplied sources."""
    knowledge = ProjectKnowledge.from_json(knowledge_path.read_text(encoding="utf-8"))
    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    source_by_id = {asset["asset_id"]: asset for asset in manifest["assets"]}
    categories: dict[str, list[dict[str, Any]]] = {name: [] for name in _ALL_CATEGORY_FIELDS}
    unclassified: list[dict[str, Any]] = []
    for item in analysis["assets"]:
        source = source_by_id[item["asset_id"]]
        record = {
            "asset_id": item["asset_id"], "asset_type": item["asset_type"],
            "quality_score": item["quality_score"], "marketing_suitability": item["marketing_suitability"],
            "source_document": source["source_document"], "source_page": source["source_page"],
            "width": source["width"], "height": source["height"],
            "visible_project_features": item["visible_project_features"],
            "recommended_platforms": item["recommended_platforms"],
        }
        category = _CATEGORY_FIELDS.get(item["asset_type"])
        (categories[category] if category else unclassified).append(record)
    inventory = {
        "project": manifest["project"], "visual_mode": "source_only",
        "available_text_facts": _flatten_facts(knowledge.to_dict()),
        **categories, "unclassified_assets_requiring_review": unclassified,
        "all_source_asset_ids": list(source_by_id),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"{manifest['project']}-visual-inventory.json"
    destination.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


def _flatten_facts(value: Any, path: str = "") -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            facts.extend(_flatten_facts(item, f"{path}.{key}".lstrip(".")))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            facts.extend(_flatten_facts(item, f"{path}[{index}]"))
    elif value not in (None, "", [], {}):
        facts.append({"knowledge_path": path, "value": value})
    return facts
