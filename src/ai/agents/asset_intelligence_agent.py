"""Vision analysis of immutable authentic assets into a semantic inventory."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from copy import deepcopy
from datetime import datetime, timezone
import json
import mimetypes
import os
from pathlib import Path
import time
from typing import Any, Callable

from PIL import Image, ImageStat

from src.core.logger import get_logger
from src.knowledge.schema import ProjectKnowledge
from src.utils.config import ASSET_INTELLIGENCE_OUTPUT_DIRECTORY, PROJECT_ROOT, PROJECT_VISUAL_MODE, VISUAL_INVENTORY_OUTPUT_DIRECTORY
from src.plan_integrity import PLAN_TYPES, write_plan_inventory, make_plan_record

MODULE_VERSION = "2.3.1"
PROMPT_TEMPLATE_VERSION = "2.2.0"
ASSET_TYPES = {
    "exterior", "interior", "amenity", "clubhouse", "swimming_pool", "garden_landscape",
    "street_access", "architectural_detail", "aerial_view", "masterplan", "site_plan",
    "floorplan", "unit_layout", "apartment_layout", "office_layout", "villa_layout", "commercial_unit_layout",
    "floor_plan", "typical_floor_plan", "master_floor_plan", "technical_plan", "location_map", "diagram", "infographic", "lifestyle", "logo",
    "branding_graphic", "text_heavy_page", "decorative_graphic", "construction_progress",
    "commercial_space", "residential_space", "mixed_visual", "unsuitable", "unknown",
}
STATUSES = {"analyzed", "cached", "partially_analyzed", "failed", "review_required", "unsuitable"}
SUITABILITY = {
    "hero_ready", "feed_ready", "carousel_ready", "story_ready", "banner_ready",
    "information_graphic_ready", "usable_after_enhancement", "limited_use", "review_required", "unsuitable",
}
SAFE_CROPS = {"flexible", "moderately_flexible", "limited", "full_image_required", "unsafe_to_crop"}
PLAN_COMPLETENESS = {"complete", "incomplete", "uncertain", "not_applicable"}
PLAN_LEGIBILITY = {"readable", "partially_readable", "unreadable", "uncertain", "not_applicable"}
_CATEGORY_MAP = {
    "exterior": "available_exterior_images", "aerial_view": "available_exterior_images",
    "interior": "available_interior_images", "residential_space": "available_interior_images", "commercial_space": "available_interior_images",
    "amenity": "available_amenity_images", "clubhouse": "available_amenity_images", "swimming_pool": "available_amenity_images", "garden_landscape": "available_amenity_images",
    "lifestyle": "available_lifestyle_images", "masterplan": "available_masterplans", "site_plan": "available_site_plans",
    **{name:"available_floorplans" for name in PLAN_TYPES if name not in {"masterplan","site_plan"}},
    "floorplan": "available_floorplans", "location_map": "available_location_maps", "diagram": "available_diagrams", "infographic": "available_diagrams",
    "logo": "available_logos", "branding_graphic": "available_branding_graphics", "text_heavy_page": "available_text_heavy_pages",
    "decorative_graphic": "available_decorative_graphics", "construction_progress": "available_construction_images",
    "unknown": "unknown_assets", "unsuitable": "unsuitable_assets",
}
_CATEGORY_FIELDS = tuple(dict.fromkeys((*_CATEGORY_MAP.values(), "unknown_assets", "unsuitable_assets", "failed_analyses")))
logger = get_logger(__name__)


class AssetIntelligenceAgent:
    """Analyze authentic source bytes without modifying or generating visuals."""

    def __init__(self, model: str | None = None, batch_size: int | None = None, analyzer: Callable[[Path], dict[str, Any]] | None = None) -> None:
        self.model = model or os.getenv("ASSET_INTELLIGENCE_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
        self.batch_size = batch_size or int(os.getenv("ASSET_INTELLIGENCE_BATCH_SIZE", "4"))
        self.analyzer = analyzer

    def run(self, source_manifest_path: Path, knowledge_path: Path, *, retry_failed: bool = False) -> tuple[Path, Path] | None:
        logger.info("Starting Asset Intelligence Agent...")
        logger.info("Reading authentic source asset inventory...")
        try:
            if PROJECT_VISUAL_MODE != "source_only":
                raise ValueError("Asset Intelligence requires source_only mode")
            manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
            knowledge = ProjectKnowledge.from_json(knowledge_path.read_text(encoding="utf-8"))
            project = manifest["project"]
            assets = manifest.get("assets", [])
        except (OSError, UnicodeError, KeyError, TypeError, ValueError) as error:
            logger.error("Could not read Asset Intelligence inputs: %s", error)
            return None
        ASSET_INTELLIGENCE_OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        intelligence_path = ASSET_INTELLIGENCE_OUTPUT_DIRECTORY / f"{project}-asset-intelligence.json"
        previous = _read_previous(intelligence_path)
        cache = {item.get("cache_key"): item for item in previous.get("assets", [])}
        hash_results: dict[str, dict[str, Any]] = {}
        completed: list[dict[str, Any]] = []
        cached_count = 0
        logger.info("Analyzing %d unique authentic assets...", len({item.get('sha256') for item in assets}))
        executor=ThreadPoolExecutor(max_workers=max(1,min(self.batch_size,4)))
        futures={}
        if self.analyzer is None:
            for asset in assets:
                key=_cache_key(asset["sha256"],self.model)
                reusable=key in cache and not (retry_failed and cache[key].get("analysis_status")=="failed")
                if not reusable and asset["sha256"] not in futures:
                    futures[asset["sha256"]]=executor.submit(self._request_with_retry,source_manifest_path.parent/asset["filename"])
        for index, asset in enumerate(assets, start=1):
            path = source_manifest_path.parent / asset["filename"]
            cache_key = _cache_key(asset["sha256"], self.model)
            if cache_key in cache and not (retry_failed and cache[cache_key].get("analysis_status") == "failed"):
                analysis = _with_provenance(deepcopy(cache[cache_key]), asset, path, project, cache_key, "cached")
                cached_count += 1
            elif asset["sha256"] in hash_results:
                analysis = _with_provenance(deepcopy(hash_results[asset["sha256"]]), asset, path, project, cache_key, "cached")
                cached_count += 1
            else:
                logger.info("Analyzing asset %d of %d...", index, len(assets))
                analysis = self._analyze_one(path, asset, project, cache_key, raw_provider=futures[asset["sha256"]].result if asset["sha256"] in futures else None)
                hash_results[asset["sha256"]] = deepcopy(analysis)
            completed.append(analysis)
            _save_intelligence(intelligence_path, project, completed, previous.get("historical_revisions", []))
        executor.shutdown(wait=True)
        current_keys = {item["cache_key"] for item in completed}
        history = [*previous.get("historical_revisions", []), *[
            item for item in previous.get("assets", []) if item.get("cache_key") not in current_keys
        ]]
        _save_intelligence(intelligence_path, project, completed, history)
        logger.info("Using cached analysis for %d assets...", cached_count)
        logger.info("Building semantic visual inventory...")
        inventory = _semantic_inventory(project, completed, knowledge)
        VISUAL_INVENTORY_OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        inventory_path = VISUAL_INVENTORY_OUTPUT_DIRECTORY / f"{project}-visual-inventory.json"
        inventory_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        write_plan_inventory(project, _project_root(source_manifest_path), completed)
        logger.info("Semantic visual inventory saved:\n%s", _display(inventory_path))
        summary = _summary(completed, cached_count)
        logger.info(
            "Asset Intelligence completed:\n- Assets analyzed: %d\n- Cached: %d\n- Review required: %d\n- Failed: %d\n- Exterior: %d\n- Interior: %d\n- Amenities: %d\n- Floor plans: %d\n- Masterplans: %d\n- Maps: %d\n- Text-heavy assets: %d\n- Unsuitable: %d",
            *summary,
        )
        return intelligence_path, inventory_path

    def _analyze_one(self, path: Path, asset: dict[str, Any], project: str, cache_key: str, raw_provider=None) -> dict[str, Any]:
        if not path.is_file():
            return _failed(asset, path, project, cache_key, "Source file is missing")
        try:
            raw = raw_provider() if raw_provider else self.analyzer(path) if self.analyzer else self._request_with_retry(path)
            semantic, warnings = _sanitize_semantics(raw)
            result = _with_provenance(semantic, asset, path, project, cache_key, semantic.get("analysis_status", "analyzed"))
            result["warnings"] = list(dict.fromkeys([*result.get("warnings", []), *warnings]))
            return result
        except Exception as error:
            return _failed(asset, path, project, cache_key, f"{type(error).__name__}: {error}")

    def _request_with_retry(self, path: Path) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return self._request_analysis(path)
            except Exception as error:
                last_error = error
                if attempt < 2:
                    time.sleep(0.25 * (attempt + 1))
        raise last_error or RuntimeError("Asset analysis failed")

    def _request_analysis(self, path: Path) -> dict[str, Any]:
        from dotenv import load_dotenv
        from openai import OpenAI
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        payload,mime=_vision_payload(path)
        data_url = f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"
        response = OpenAI(api_key=api_key).responses.create(
            model=self.model,
            instructions=_VISION_PROMPT,
            input=[{"role": "user", "content": [{"type": "input_text", "text": "Analyze only visibly verifiable content in this authentic project asset."}, {"type": "input_image", "image_url": data_url}]}],
            text={"format": {"type": "json_schema", "name": "asset_intelligence", "strict": True, "schema": _VISION_SCHEMA}},
        )
        if not response.output_text:
            raise ValueError("Vision API returned no JSON")
        return json.loads(response.output_text)

def _vision_payload(path:Path)->tuple[bytes,str]:
    """Bound the complete-image analysis transport; never edit source pixels."""
    from PIL import Image, ImageOps
    mime=mimetypes.guess_type(path.name)[0]
    with Image.open(path) as source:
        if max(source.size)<=2048 and path.stat().st_size<=4*1024*1024 and mime in {"image/jpeg","image/png","image/gif","image/webp"}:
            return path.read_bytes(),mime
        image=ImageOps.exif_transpose(source)
        image.thumbnail((2048,2048),Image.Resampling.LANCZOS)
        buffer=BytesIO()
        if mime not in {"image/jpeg","image/png","image/gif","image/webp"} and max(source.size)<=2048:
            image.convert("RGBA" if "A" in image.getbands() else "RGB").save(buffer,format="PNG")
            return buffer.getvalue(),"image/png"
        rgba=image.convert("RGBA");background=Image.new("RGB",rgba.size,"white");background.paste(rgba,mask=rgba.getchannel("A"))
        background.save(buffer,format="JPEG",quality=90,optimize=True)
        return buffer.getvalue(),"image/jpeg"


_SEMANTIC_FIELDS = {
    "asset_type", "asset_subtype", "confidence", "analysis_status", "dominant_subject", "supporting_subjects",
    "visible_project_features", "visible_architectural_elements", "visible_amenities", "visible_spaces", "contains_people",
    "people_context", "contains_text", "visible_text_summary", "contains_logo", "logo_description", "contains_map",
    "contains_masterplan", "contains_floorplan", "contains_diagram", "exterior_or_interior", "apparent_time_of_day",
    "visible_weather", "lighting_character", "dominant_colors", "marketing_suitability", "recommended_content_uses",
    "recommended_platforms", "recommended_formats", "safe_crop_assessment", "text_safe_area_assessment",
    "logo_safe_area_assessment", "restrictions", "warnings",
    "unit_identity", "evidence", "relationship_confidence", "relationship_status", "verification_status",
    "visible_unit_numbers", "visible_dimension_labels", "plan_completeness_status", "plan_legibility_status",
}
_ARRAY_FIELDS = {
    "supporting_subjects", "visible_project_features", "visible_architectural_elements", "visible_amenities", "visible_spaces",
    "dominant_colors", "recommended_content_uses", "recommended_platforms", "recommended_formats", "restrictions", "warnings",
    "visible_unit_numbers", "visible_dimension_labels",
}
_BOOL_FIELDS = {"contains_people", "contains_text", "contains_logo", "contains_map", "contains_masterplan", "contains_floorplan", "contains_diagram"}
_UNIT_FIELDS=("unit_type","area_sqm","bedrooms","bathrooms","floor","unit_number","building","tower","orientation","balcony","terrace","commercial_residential_classification","dimensions")


def _sanitize_semantics(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    data = {key: raw.get(key) for key in _SEMANTIC_FIELDS}
    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        confidence = 0.0
        warnings.append("Invalid confidence was reset to 0.0")
    asset_type = data.get("asset_type") if data.get("asset_type") in ASSET_TYPES else "unknown"
    if confidence < 0.5:
        asset_type = "unknown"
    status = data.get("analysis_status") if data.get("analysis_status") in STATUSES else "review_required"
    suitability = data.get("marketing_suitability") if data.get("marketing_suitability") in SUITABILITY else "review_required"
    crop = data.get("safe_crop_assessment") if isinstance(data.get("safe_crop_assessment"), dict) else {}
    crop_level = crop.get("level") if crop.get("level") in SAFE_CROPS else "full_image_required"
    for field in _ARRAY_FIELDS:
        value = data.get(field)
        data[field] = [str(item) for item in value if str(item).strip()] if isinstance(value, list) else []
    for field in _BOOL_FIELDS:
        data[field] = bool(data.get(field))
    evidence_text = " ".join([
        str(data.get("dominant_subject") or ""), *data["supporting_subjects"],
        *data["visible_architectural_elements"], *data["visible_amenities"], *data["visible_spaces"],
    ]).casefold()
    supported_features = []
    for feature in data["visible_project_features"]:
        tokens = [token for token in feature.casefold().replace("-", " ").split() if len(token) >= 4]
        if tokens and any(token in evidence_text for token in tokens):
            supported_features.append(feature)
        else:
            warnings.append(f"Unsupported visible feature claim removed: {feature}")
    data.update({
        "asset_type": asset_type, "asset_subtype": str(data.get("asset_subtype") or ""), "confidence": float(confidence),
        "analysis_status": "review_required" if asset_type == "unknown" and status == "analyzed" else status,
        "marketing_suitability": "review_required" if asset_type == "unknown" else suitability,
        "visible_project_features": supported_features,
        "safe_crop_assessment": {"level": crop_level, "reason": str(crop.get("reason") or "Preserve the full visible source when crop safety is uncertain")},
    })
    if data.get("plan_completeness_status") not in PLAN_COMPLETENESS:
        data["plan_completeness_status"] = "uncertain" if asset_type in PLAN_TYPES or asset_type == "floorplan" else "not_applicable"
    if data.get("plan_legibility_status") not in PLAN_LEGIBILITY:
        data["plan_legibility_status"] = "uncertain" if asset_type in PLAN_TYPES or asset_type == "floorplan" else "not_applicable"
    if asset_type in PLAN_TYPES or asset_type == "floorplan":
        if data["plan_completeness_status"] != "complete" or data["plan_legibility_status"] != "readable":
            data["analysis_status"] = "review_required"
            data["marketing_suitability"] = "review_required"
    for field in _SEMANTIC_FIELDS - _ARRAY_FIELDS - _BOOL_FIELDS - {"confidence", "safe_crop_assessment", "unit_identity", "evidence", "relationship_confidence"}:
        if field not in {"asset_type", "analysis_status", "marketing_suitability"}:
            data[field] = str(data.get(field) or "")
    for field in ("unit_identity","evidence","relationship_confidence"):
        data[field]=data.get(field) if isinstance(data.get(field),dict) else {}
    return data, warnings


def _with_provenance(data: dict[str, Any], asset: dict[str, Any], path: Path, project: str, cache_key: str, status: str) -> dict[str, Any]:
    result = deepcopy(data)
    quality = _quality(path, int(asset.get("width", 0)), int(asset.get("height", 0)))
    source_page = asset.get("source_page")
    if source_page is None:
        source_page = 0
    result.update({
        "asset_id": asset["asset_id"], "project_id": project, "source_document": asset.get("source_document"),
        "source_page": source_page, "source_image_index": asset.get("image_index"),
        "source_path": str(path), "source_hash": asset["sha256"], "width": asset.get("width", 0),
        "height": asset.get("height", 0), "orientation": asset.get("orientation", "unknown"),
        "source_kind": asset.get("source_kind"),
        "source_document_hash": asset.get("source_document_sha256"),
        "source_document_path": asset.get("source_document_path"),
        "contains_entire_page": bool(asset.get("contains_entire_page")),
        "contains_complete_plan_leaf": asset.get("contains_complete_plan_leaf"),
        "source_region": asset.get("source_region"),
        "extraction_fidelity": asset.get("extraction_fidelity"),
        "render_dpi": asset.get("render_dpi"),
        "analysis_status": status, "image_quality": quality, "cache_key": cache_key,
        "module_version": MODULE_VERSION, "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "model_policy": "vision-capable configured model; visible evidence only", "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
    })
    if asset.get("source_kind") == "pdf_villa_plan_leaf":
        result["asset_type"] = "villa_layout"
        result["plan_completeness_status"] = asset.get("plan_completeness_status", "UNCERTAIN")
        result["plan_legibility_status"] = asset.get("plan_legibility_status", "UNCERTAIN")
    result.pop("unit_plan_relationship", None)
    result["evidence"] = _bind_exact_evidence(result, asset, project, source_page)
    plan_kind = str(result.get("asset_type") or "").casefold()
    if plan_kind in PLAN_TYPES or plan_kind == "floorplan":
        result.setdefault("plan_completeness_status", "uncertain")
        result.setdefault("plan_legibility_status", "uncertain")
        if asset.get("source_kind") == "pdf_embedded_image" and not asset.get("contains_entire_page"):
            result["plan_completeness_status"] = "incomplete"
        if str(result.get("plan_completeness_status")).upper() != "COMPLETE" or str(result.get("plan_legibility_status")).upper() != "READABLE":
            result["analysis_status"] = "review_required"
            result["marketing_suitability"] = "review_required"
    record = make_plan_record(result)
    if record:
        result.update({key: value for key, value in record.items() if key != "confidence"})
        if not record["marketing_eligible"]:
            result["analysis_status"] = "review_required"
            result["marketing_suitability"] = "review_required"
    result.update({
        "visual_category": _visual_category(result),
        "visible_subject": result.get("dominant_subject", ""),
        "associated_verified_facts": list(result.get("visible_project_features", [])),
        "suitability_for_marketing": result.get("marketing_suitability", "review_required"),
        "suitability_for_text_overlay": result.get("text_safe_area_assessment", ""),
        "preservation_requirements": _preservation_requirements(result),
    })
    return result


def _bind_exact_evidence(
    data: dict[str, Any],
    asset: dict[str, Any],
    project: str,
    source_page: int,
) -> dict[str, list[dict[str, Any]]]:
    """Bind visible transcriptions to the exact source asset being analyzed."""
    supplied = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
    identity = data.get("unit_identity") if isinstance(data.get("unit_identity"), dict) else {}
    bound: dict[str, list[dict[str, Any]]] = {}
    for field in _UNIT_FIELDS:
        items = supplied.get(field) if isinstance(supplied.get(field), list) else []
        bound[field] = []
        if identity.get(field) in (None, "", "UNKNOWN", "UNVERIFIED"):
            continue
        for item in items:
            if isinstance(item, str):
                evidence_text = item.strip()
            elif isinstance(item, dict):
                evidence_text = str(
                    item.get("evidence_text") or item.get("source_text") or item.get("text") or ""
                ).strip()
            else:
                evidence_text = ""
            if not evidence_text:
                continue
            bound[field].append({
                "source_project": project,
                "source_document": asset.get("source_document"),
                "source_page": source_page,
                "source_hash": asset.get("sha256"),
                "source_document_hash": asset.get("source_document_sha256"),
                "asset_id": asset.get("asset_id"),
                "evidence_text": evidence_text,
                "extraction_method": "vision_visible_plan",
            })
    return bound


def _visual_category(data: dict[str, Any]) -> str:
    """Map visible evidence to the Phase 26 taxonomy without forcing ambiguity."""
    kind=str(data.get("asset_type") or "unknown"); subject=" ".join((str(data.get("asset_subtype") or ""), str(data.get("dominant_subject") or ""))).casefold()
    if float(data.get("confidence") or 0) < .5: return "unknown"
    if kind == "exterior": return "villa_exterior" if "villa" in subject else "building_exterior"
    if kind in {"interior", "residential_space"}: return "villa_interior" if "villa" in subject else "building_interior"
    if kind in PLAN_TYPES:
        return kind
    return {"aerial_view":"project_hero", "masterplan":"masterplan", "site_plan":"site_plan",
        "floorplan":"villa_layout" if "villa" in subject else "floor_plan", "garden_landscape":"greenery_landscape",
        "amenity":"amenities", "clubhouse":"clubhouse", "swimming_pool":"swimming_pool",
        "location_map":"location_map", "street_access":"streetscape", "commercial_space":"commercial_area",
        "architectural_detail":"architectural_detail", "diagram":"technical_plan", "infographic":"technical_plan"}.get(kind, "unknown")


def _preservation_requirements(data: dict[str, Any]) -> list[str]:
    category=_visual_category(data)
    if category in {"site_plan", "masterplan"}: return ["preserve exact roads, plots, orientation, labels, landscape zones, and geometry"]
    if category in PLAN_TYPES or category in {"villa_layout", "floor_plan", "technical_plan"}: return ["preserve the complete plan and exact walls, rooms, unit numbers, openings, dimensions, circulation, labels, and geometry"]
    if category in {"villa_exterior", "building_exterior", "architectural_detail"}: return ["preserve exact architecture, geometry, proportions, openings, and structural relationships"]
    if category in {"villa_interior", "building_interior"}: return ["preserve room geometry, openings, fixed elements, and visible design relationships"]
    return ["preserve authentic source content; do not invent project features"]


def _failed(asset: dict[str, Any], path: Path, project: str, cache_key: str, error: str) -> dict[str, Any]:
    semantic, _ = _sanitize_semantics({"asset_type": "unknown", "confidence": 0.0, "analysis_status": "failed", "marketing_suitability": "review_required", "warnings": [error]})
    return _with_provenance(semantic, asset, path, project, cache_key, "failed")


def _quality(path: Path, width: int, height: int) -> dict[str, Any]:
    pixels = width * height
    score = min(90, max(5, int(25 + min(pixels / 2_000_000, 1) * 55)))
    sharpness = "unknown"
    issues: list[str] = []
    try:
        with Image.open(path) as image:
            gray = image.convert("L").resize((64, 64))
            variance = ImageStat.Stat(gray).var[0]
            sharpness = "good" if variance > 500 else "soft" if variance > 80 else "low"
            if sharpness == "low":
                issues.append("low measurable tonal detail; visual review required")
    except Exception:
        issues.append("technical image inspection failed")
    resolution = "high" if pixels >= 2_000_000 else "medium" if pixels >= 800_000 else "low"
    return {"score": score, "resolution": resolution, "sharpness": sharpness, "compression": "unknown", "issues": issues, "enhancement_may_help": resolution == "low" or sharpness in {"soft", "low"}}


def _semantic_inventory(project: str, analyses: list[dict[str, Any]], knowledge: ProjectKnowledge) -> dict[str, Any]:
    categories = {field: [] for field in _CATEGORY_FIELDS}
    for analysis in analyses:
        if analysis["analysis_status"] == "failed":
            categories["failed_analyses"].append(analysis)
            continue
        category = _CATEGORY_MAP.get(analysis["asset_type"], "unknown_assets")
        record = deepcopy(analysis)
        record["quality_score"] = analysis["image_quality"]["score"]
        categories[category].append(record)
    return {
        "project": project, "visual_mode": "source_only", "inventory_type": "semantic",
        "available_text_facts": _flatten_facts(knowledge.to_dict()), **categories,
        "all_source_asset_ids": [item["asset_id"] for item in analyses],
    }


def _flatten_facts(value: Any, path: str = "") -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items(): facts.extend(_flatten_facts(item, f"{path}.{key}".lstrip(".")))
    elif isinstance(value, list):
        for index, item in enumerate(value): facts.extend(_flatten_facts(item, f"{path}[{index}]"))
    elif value not in (None, "", [], {}): facts.append({"knowledge_path": path, "value": value})
    return facts


def _cache_key(source_hash: str, model: str) -> str:
    import hashlib
    return hashlib.sha256(f"{source_hash}|{MODULE_VERSION}|{PROMPT_TEMPLATE_VERSION}|{model}".encode()).hexdigest()


def _read_previous(path: Path) -> dict[str, Any]:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {"assets": [], "historical_revisions": []}


def _save_intelligence(path: Path, project: str, assets: list[dict[str, Any]], history: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"project": project, "visual_mode": "source_only", "assets": assets, "historical_revisions": history}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _summary(items: list[dict[str, Any]], cached: int) -> tuple[int, ...]:
    count = lambda *types: sum(item["asset_type"] in types for item in items)
    return (len(items) - cached, cached, sum(item["analysis_status"] == "review_required" for item in items), sum(item["analysis_status"] == "failed" for item in items), count("exterior", "aerial_view"), count("interior", "residential_space", "commercial_space"), count("amenity", "clubhouse", "swimming_pool", "garden_landscape"), count("floorplan"), count("masterplan"), count("location_map"), count("text_heavy_page"), count("unsuitable"))


def _display(path: Path) -> Path:
    try: return path.relative_to(PROJECT_ROOT)
    except ValueError: return path

def _project_root(manifest:Path)->Path:
    for parent in manifest.parents:
        if parent.name=="output":return parent.parent
    return PROJECT_ROOT


_VISION_PROMPT = """Analyze every relevant visible element in this authentic real-estate source image. Never use filenames as evidence. Never infer unseen architecture, amenities, interiors, people, landscaping, location, developer, materials, or claims. Distinguish villas/buildings, exterior/interior, site plans/masterplans, individual unit layouts/floor plans, services, landscape, amenities, maps, entrances, streets, pools, commercial areas, parking, and technical details where visible. Treat an individual unit plan differently from photography and from a masterplan or typical floor plan. For a plan, transcribe every clearly visible unit number and dimension label exactly; never repair, estimate, calculate, or complete unclear text. Mark whether the whole plan is present and whether its numbers, room labels and dimensions are readable. Any cropped, partial, ambiguous or unreadable plan must use review_required. Text, maps, plans, diagrams, and logos must be classified as graphics rather than lifestyle photography. Return JSON only."""
_VISION_SCHEMA = {"type": "object", "properties": {
    **{name: {"type": "array", "items": {"type": "string"}} for name in _ARRAY_FIELDS},
    **{name: {"type": "boolean"} for name in _BOOL_FIELDS},
    **{name: {"type": "string"} for name in _SEMANTIC_FIELDS - _ARRAY_FIELDS - _BOOL_FIELDS - {"confidence", "safe_crop_assessment", "asset_type", "analysis_status", "marketing_suitability", "unit_identity", "evidence", "relationship_confidence"}},
    "asset_type": {"type": "string", "enum": sorted(ASSET_TYPES)}, "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "analysis_status": {"type": "string", "enum": sorted(STATUSES)}, "marketing_suitability": {"type": "string", "enum": sorted(SUITABILITY)},
    "plan_completeness_status": {"type": "string", "enum": sorted(PLAN_COMPLETENESS)},
    "plan_legibility_status": {"type": "string", "enum": sorted(PLAN_LEGIBILITY)},
    "safe_crop_assessment": {"type": "object", "properties": {"level": {"type": "string", "enum": sorted(SAFE_CROPS)}, "reason": {"type": "string"}}, "required": ["level", "reason"], "additionalProperties": False},
    "unit_identity":{"type":"object","properties":{name:{"type":["string","number","boolean","null"]} for name in _UNIT_FIELDS},"required":list(_UNIT_FIELDS),"additionalProperties":False},
    "evidence":{"type":"object","properties":{name:{"type":"array","items":{"type":"string"}} for name in _UNIT_FIELDS},"required":list(_UNIT_FIELDS),"additionalProperties":False},
    "relationship_confidence":{"type":"object","properties":{name:{"type":"number","minimum":0,"maximum":1} for name in _UNIT_FIELDS},"required":list(_UNIT_FIELDS),"additionalProperties":False},
}, "required": sorted(_SEMANTIC_FIELDS), "additionalProperties": False}
