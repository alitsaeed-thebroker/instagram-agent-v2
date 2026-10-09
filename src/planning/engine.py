"""Asset-first planning with deterministic evidence, scarcity, and memory controls."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from src.platforms import CampaignPlatformStrategy
from src.content.inventory import ContentOpportunityInventoryEngine, legacy_visual_opportunities, load_content_opportunity_inventory
from src.execution.lineage import attach_lineage, artifact_fingerprint, canonical_graph_fingerprint, require_lineage
from src.content.visual_purpose import load_visual_reviews, assess_visual_purpose, validate_overview_slides
from src.project_sequence import role

from src.utils.config import (
    ASSET_USAGE_OUTPUT_DIRECTORY, CAMPAIGNS_OUTPUT_DIRECTORY,
    CONTENT_MEMORY_OUTPUT_DIRECTORY, CONTENT_OUTPUT_DIRECTORY,
    REPORTS_OUTPUT_DIRECTORY, VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY,
)

VERSION = "9.6.2"
FUNNEL = ("awareness", "interest", "consideration", "trust", "education", "conversion", "retention")
STILL_FORMATS = {
    "exterior": ["Instagram Single Image", "Instagram Carousel", "Facebook Post", "Website Banner"],
    "interior": ["Instagram Single Image", "Instagram Carousel", "Facebook Carousel"],
    "floorplan": ["Floorplan Post", "Instagram Carousel", "Informational Graphic"],
    "masterplan": ["Masterplan Post", "Informational Graphic"],
    "site_plan": ["Site Plan Post", "Informational Graphic"],
    "location_map": ["Informational Graphic", "LinkedIn Graphic"],
    "diagram": ["Informational Graphic", "LinkedIn Graphic"],
    "lifestyle": ["Instagram Single Image", "Instagram Carousel", "Facebook Post"],
    "amenity": ["Instagram Single Image", "Instagram Carousel", "Facebook Post"],
    "architectural_detail": ["Instagram Carousel", "Instagram Single Image"],
    "logo": ["Instagram Story Graphic", "LinkedIn Graphic"],
}
TYPE_TITLES = {
    "exterior": "Villa Exterior Showcase", "interior": "Interior Living Spaces",
    "floorplan": "Floorplan Education", "masterplan": "Masterplan Overview",
    "site_plan": "Site Layout Explanation", "location_map": "Location Explanation",
    "diagram": "Project Information", "lifestyle": "Supported Lifestyle",
    "amenity": "Visible Amenities", "architectural_detail": "Architectural Detail Series",
    "logo": "Project Introduction",
}
CAMERA_TERMS = re.compile(r"\b(lens|gimbal|drone|cinematic pan|tracking shot|depth of field|camera (?:angle|motion)|crop coordinates|framing coordinates)\b", re.I)

def _format_channel(value:str)->str:
    text=str(value).casefold()
    if "facebook" in text:return "facebook"
    if "instagram" in text:return "instagram"
    if "website" in text or "banner" in text:return "website"
    if "linkedin" in text:return "linkedin"
    if "youtube" in text:return "youtube"
    return "instagram"


def _read(path: Path | None, default: Any = None) -> Any:
    if path is None or not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part).strip().casefold() for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def _assets(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for key, values in inventory.items():
        if not key.startswith("available_") or key == "available_text_facts" or not isinstance(values, list):
            continue
        for asset in values:
            if isinstance(asset, dict) and asset.get("asset_id"):
                found[asset["asset_id"]] = asset
    return sorted(found.values(), key=lambda item: item["asset_id"])


def _project_assets(inventory: dict[str, Any], project_id: str, review_root: Path | None = None) -> list[dict[str, Any]]:
    """Return the sole asset collection allowed to influence Department 3 compatibility."""
    assets=[asset for asset in _assets(inventory)
            if _same_project(asset.get("project_id") or asset.get("source_project") or asset.get("project"),project_id)]
    return load_visual_reviews(review_root,assets) if review_root is not None else assets


def _reviewed_overview(asset: dict[str, Any]) -> bool:
    # A source-bound human review authorizes this purpose only; advisory AI
    # review_required must not discard its approved full-development cover.
    return all(asset.get(k) for k in ("asset_id","project_id","source_hash","source_document_hash","source_page")) and assess_visual_purpose(asset,"project_overview",asset.get("project_id"),allow_support=True)["status"]=="MATCH"


def _same_project(owner: Any, project_id: str) -> bool:
    normalize=lambda value:re.sub(r"[^\w]+"," ",str(value).casefold()).strip()
    return bool(owner) and normalize(owner)==normalize(project_id)


def _usable(asset: dict[str, Any]) -> bool:
    return (asset.get("analysis_status") not in {"failed", "review_required", "unsuitable"}
            and asset.get("asset_type") not in {"unknown", "unsuitable"}
            and asset.get("marketing_suitability") not in {"review_required", "unsuitable"})


def _quality(asset: dict[str, Any]) -> float:
    return max(0.0, min(100.0, float(asset.get("image_quality", {}).get("score", asset.get("quality_score", 0)) or 0)))


def _confidence(asset: dict[str, Any]) -> float:
    return max(0.0, min(1.0, float(asset.get("confidence", 0) or 0)))


def _canonical_type(asset: dict[str, Any]) -> str:
    kind = str(asset.get("asset_type", "unknown")).casefold().replace(" ", "_")
    subtype = str(asset.get("asset_subtype", "")).casefold().replace(" ", "_")
    flags = (("floorplan", "contains_floorplan"), ("masterplan", "contains_masterplan"), ("location_map", "contains_map"), ("diagram", "contains_diagram"), ("logo", "contains_logo"))
    for name, flag in flags:
        if asset.get(flag): return name
    if kind in {"residential_space", "commercial_space"}: return "interior"
    if kind == "aerial_view" and "master" in subtype: return "masterplan"
    return kind if kind in TYPE_TITLES else (subtype if subtype in TYPE_TITLES else kind)


def _facts(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in inventory.get("available_text_facts", []) if isinstance(item, dict) and item.get("knowledge_path")]


def _fact_matches(kind: str, asset: dict[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visual_parts: list[str] = []
    for key in ("dominant_subject", "visible_project_features", "visible_spaces", "visible_amenities", "visible_architectural_elements"):
        value = asset.get(key)
        visual_parts.extend([value] if isinstance(value, str) else (value or []))
    visual = " ".join(map(str, visual_parts)).casefold()
    tokens = set(re.findall(r"[a-z0-9]+", visual))
    result = []
    for fact in facts:
        text = f"{fact.get('knowledge_path')} {fact.get('value')}".casefold()
        overlap = sum(1 for token in tokens if len(token) > 4 and token in text)
        path = str(fact.get("knowledge_path", "")).casefold()
        compatible = overlap or (kind in {"exterior", "architectural_detail"} and any(x in path for x in ("project", "architecture", "unit", "marketing"))) or (kind in path)
        if compatible: result.append(fact)
    return result[:8]


def _diversity(assets: list[dict[str, Any]]) -> int:
    if not assets: return 0
    dimensions = []
    for key in ("asset_subtype", "orientation", "apparent_time_of_day", "dominant_subject", "source_page"):
        dimensions.append(len({str(a.get(key, "")).casefold() for a in assets}) / len(assets))
    families = len({_family(a) for a in assets}) / len(assets)
    return round(100 * (sum(dimensions) / len(dimensions) * .7 + families * .3))


def _family(asset: dict[str, Any]) -> str:
    parts = [_canonical_type(asset), asset.get("asset_subtype", ""), asset.get("dominant_subject", ""), asset.get("apparent_time_of_day", ""), asset.get("source_page", "")]
    return _stable_id("vf", *parts)


def _visual_strength(items: list[dict[str, Any]], diversity: int) -> int:
    if not items: return 0
    count = min(100, len(items) * 20)
    quality = sum(_quality(a) for a in items) / len(items)
    confidence = 100 * sum(_confidence(a) for a in items) / len(items)
    platform = min(100, 25 * len({p for a in items for p in a.get("recommended_platforms", [])}))
    crop = 100 * sum(a.get("safe_crop_assessment", {}).get("level") == "flexible" for a in items) / len(items)
    suitability = 100 * sum(a.get("marketing_suitability") in {"hero_ready", "feed_ready", "carousel_ready", "banner_ready", "information_graphic_ready"} for a in items) / len(items)
    return round(.12*count + .20*quality + .18*confidence + .10*platform + .12*diversity + .10*crop + .10*suitability + .08*diversity)


class VisualOpportunityEngine:
    """Discover marketable evidence before any content concept is written."""

    def run(self, knowledge_path: Path, inventory_path: Path, strategy_path: Path | None = None, asset_intelligence_path: Path | None = None) -> Path:
        inventory = _read(inventory_path, {})
        project_id = str(inventory.get("project_id") or inventory.get("project") or knowledge_path.stem)
        assets = _project_assets(inventory,project_id,knowledge_path.resolve().parents[2])
        facts = [fact for fact in _facts(inventory) if _same_project(fact.get("project_id") or fact.get("source_project") or fact.get("project"),project_id)]
        usable = [a for a in assets if _usable(a) or _reviewed_overview(a)]
        canonical_directory = (VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY.parent / "content-inventory"
                               if VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY.name == "visual-opportunities"
                               else VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY / "content-inventory")
        canonical_path = ContentOpportunityInventoryEngine().run(
            knowledge_path, inventory_path, strategy_path, canonical_directory, project_id=project_id
        )
        canonical = load_content_opportunity_inventory(canonical_path)
        groups: list[dict[str, Any]] = legacy_visual_opportunities(canonical, usable)
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for asset in usable: by_type[_canonical_type(asset)].append(asset)
        legacy_diagnostics: list[dict[str, Any]] = []
        for kind in sorted(by_type):
            items = by_type[kind]
            matched = {f["knowledge_path"]: f for a in items for f in _fact_matches(kind, a, facts)}
            diversity = _diversity(items)
            visual = _visual_strength(items, diversity)
            factual = min(100, round(25 + 12 * len(matched))) if matched else 20
            people = any(a.get("contains_people") for a in items)
            legacy_diagnostics.append({
                "opportunity_id": _stable_id("opp", project_id, kind), "title": TYPE_TITLES.get(kind, kind.replace("_", " ").title()),
                "opportunity_type": kind, "supported_asset_ids": [a["asset_id"] for a in items],
                "supporting_fact_refs": sorted(matched), "supported_personas": [],
                "supported_funnel_stages": ["awareness", "interest"] if kind in {"exterior", "lifestyle"} else ["consideration", "education", "trust"],
                "supported_platforms": sorted({p for a in items for p in a.get("recommended_platforms", [])}),
                "supported_formats": STILL_FORMATS.get(kind, ["Instagram Single Image"]),
                "visual_strength": visual, "factual_strength": factual,
                "overall_confidence": round((visual*.55 + factual*.45)/100, 3), "asset_diversity_score": diversity,
                "reuse_capacity": sum(_max_reuse(a, kind) for a in items),
                "limitations": ([] if people else ["No human activity may be implied unless visibly supported."]),
                "forbidden_claims": ["Unseen rooms, amenities, people, actions, viewpoints, statistics, returns, or video footage"],
                "recommended_priority": "high" if visual >= 75 and factual >= 60 else "medium" if visual >= 55 else "limited",
            })
        strategy = _read(strategy_path, {})
        personas = [p.get("name") for p in strategy.get("buyer_personas", []) if isinstance(p, dict) and p.get("name")] or strategy.get("target_audience", [])
        for group in groups: group["supported_personas"] = list(dict.fromkeys(personas))
        reservations = [_reservation(a) for a in usable]
        reserved_ids = {r["asset_id"] for r in reservations}
        unreserved = sorted({aid for group in groups for aid in group["supported_asset_ids"] if aid not in reserved_ids})
        type_counts = Counter(_canonical_type(a) for a in assets)
        orientations = Counter(str(a.get("orientation", "unknown")) for a in assets)
        platforms = Counter(p for a in assets for p in a.get("recommended_platforms", []))
        unsupported = _unsupported(type_counts, any(a.get("contains_people") for a in usable), facts)
        capacity = _capacity(by_type)
        output = {
            "project_id": project_id,
            "contract_role": "compatibility_visual_opportunities",
            "derived_from_canonical_inventory": True,
            "canonical_inventory_path": str(canonical_path),
            "canonical_inventory_version": canonical.inventory_version,
            "canonical_inventory_sha256": hashlib.sha256(canonical_path.read_bytes()).hexdigest(),
            "inventory_summary": {
                "total_authentic_assets": len(assets), **{f"{k}_count": type_counts.get(k, 0) for k in ("exterior", "interior", "lifestyle", "amenity", "floorplan", "masterplan", "site_plan", "location_map", "diagram", "logo", "unknown", "unsuitable")},
                "text_heavy_asset_count": sum(bool(a.get("contains_text")) for a in assets),
                "failed_analyses": sum(a.get("analysis_status") == "failed" for a in assets),
                "average_quality": round(sum(map(_quality, assets))/len(assets), 2) if assets else 0,
                "average_confidence": round(sum(map(_confidence, assets))/len(assets), 3) if assets else 0,
                "orientation_distribution": dict(sorted(orientations.items())), "platform_suitability_distribution": dict(sorted(platforms.items())),
            },
            "visual_opportunity_groups": groups, "asset_reservations": reservations,
            "unreserved_opportunity_asset_ids": unreserved,
            "legacy_visual_group_diagnostics": legacy_diagnostics,
            "unsupported_story_types": unsupported,
            "funnel_coverage": {stage: sum(stage in g["supported_funnel_stages"] for g in groups) for stage in FUNNEL},
            "persona_coverage": {p: sum(p in g["supported_personas"] for g in groups) for p in personas},
            "content_capacity": capacity,
            "warnings": (["No usable authentic visual opportunities were found."] if not groups else []) + (["Lifestyle evidence is unavailable."] if not type_counts["lifestyle"] else []) + (["Opportunity assets remain excluded pending reservation eligibility: " + ", ".join(unreserved)] if unreserved else []),
            "summary": {"opportunity_count": len(groups), "canonical_opportunity_count": len(canonical.opportunities), "usable_asset_count": len(usable), "unsupported_story_type_count": len(unsupported)},
        }
        return _write(VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY / f"{project_id}-visual-opportunities.json", output)


def _max_reuse(asset: dict[str, Any], kind: str) -> int:
    if kind in {"floorplan", "masterplan", "site_plan", "location_map", "diagram", "logo"}: return 4
    if _confidence(asset) < .5: return 1
    return 3 if _quality(asset) >= 75 else 2


def _reservation(asset: dict[str, Any]) -> dict[str, Any]:
    kind = _canonical_type(asset); quality = _quality(asset); confidence = _confidence(asset)
    reviewed_only=not _usable(asset) and _reviewed_overview(asset)
    if confidence < .5: level = "review_required"
    elif asset.get("marketing_suitability") == "hero_ready" and quality >= 75: level = "hero_reserved"
    elif quality >= 70: level = "campaign_anchor"
    elif kind in {"floorplan", "masterplan", "site_plan", "location_map", "diagram", "logo"}: level = "informational"
    elif asset.get("marketing_suitability") == "limited_use": level = "limited_use"
    else: level = "flexible"
    value={"asset_id": asset["asset_id"], "reservation_level": level, "recommended_primary_use": TYPE_TITLES.get(kind, kind),
            "permitted_secondary_uses": STILL_FORMATS.get(kind, ["supporting"]), "maximum_reuse_count": _max_reuse(asset, kind),
            "current_planned_use_count": 0, "reason": f"quality={quality:.0f}, confidence={confidence:.2f}, type={kind}"}
    return {**value,"reservation_level":"reviewed_overview","allowed_purposes":["project_overview"]} if reviewed_only else value


def _capacity(by_type: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    usable = sum(len(v) for v in by_type.values())
    result = {"maximum_unique_hero_posts": sum(_quality(a)>=75 and _confidence(a)>=.7 for values in by_type.values() for a in values),
              "maximum_unique_carousel_sets": usable//3, "maximum_campaign_duration_before_repetition_becomes_excessive": max(0, usable//2)}
    for kind in ("interior", "exterior", "floorplan", "masterplan", "lifestyle"):
        result[f"maximum_{kind}_posts"] = len({_family(a) for a in by_type.get(kind, [])})
    result["maximum_text_supported_graphics"] = sum(len(by_type.get(k, [])) for k in ("floorplan", "masterplan", "site_plan", "location_map", "diagram", "logo"))
    return result


def _unsupported(counts: Counter[str], people: bool, facts: list[dict[str, Any]]) -> list[dict[str, str]]:
    checks = [("resident testimonial", False, "No supplied testimonial"), ("expert interview", False, "No supplied interview"),
              ("lifestyle video", False, "No approved video footage"), ("drone footage", False, "No approved video footage"),
              ("family routine", people and counts["lifestyle"]>0, "No visible supported family activity"),
              ("bathroom relaxation", counts["interior"]>0, "No verified bathroom evidence"),
              ("amenity experience", counts["amenity"]>0, "No visible amenity evidence"),
              ("investment return chart", any("return" in str(f.get("value", "")).casefold() for f in facts), "No approved financial return data")]
    return [{"story_type": name, "reason": reason, "missing_evidence": reason, "possible_safe_alternative": "Use a supported asset showcase or factual informational graphic."} for name, supported, reason in checks if not supported]


class PlanningEngine:
    """Build campaigns and content only from approved opportunities and selected assets."""

    def run(self, knowledge_path: Path, strategy_path: Path, inventory_path: Path, opportunities_path: Path, *, creative_intelligence_path: Path | None = None,
            campaign_intelligence_path: Path | None = None, write_campaign: bool = True, platform_strategy: str = "both_platform_optimized", allowed_channels: Iterable[str] | None = None) -> dict[str, Path]:
        platform_strategy = CampaignPlatformStrategy.parse(platform_strategy)
        allowed_channels={str(x).casefold() for x in (allowed_channels or ("instagram","facebook"))}
        if not allowed_channels or not allowed_channels <= {"instagram","facebook","website"}:raise ValueError("allowed_channels contains an unsupported channel")
        knowledge, strategy, inventory, opportunities = map(lambda p: _read(p, {}), (knowledge_path, strategy_path, inventory_path, opportunities_path))
        project_id = opportunities["project_id"]
        reci = _read(creative_intelligence_path, {})
        campaign_intelligence = _read(campaign_intelligence_path, {})
        if creative_intelligence_path is not None:
            if reci.get("contract_role") != "canonical_creative_opportunity_map": raise ValueError("Department 3 requires a canonical Creative Opportunity Map")
            if not _same_project(reci.get("project_id"), project_id): raise ValueError("Creative Opportunity Map project does not match planning project")
        if campaign_intelligence_path is not None:
            if campaign_intelligence.get("contract_role") != "canonical_campaign_decision_contract":raise ValueError("Department 3 requires a canonical Campaign Decision Contract")
            if not _same_project(campaign_intelligence.get("project_id"),project_id):raise ValueError("Campaign Decision Contract project does not match planning project")
            expected=campaign_intelligence.get("contract_hash");unsigned={k:v for k,v in campaign_intelligence.items() if k!="contract_hash"}
            if not expected or expected!=hashlib.sha256(json.dumps(unsigned,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest():raise ValueError("Campaign Decision Contract integrity check failed")
        assets = {a["asset_id"]: a for a in _project_assets(inventory,project_id,knowledge_path.resolve().parents[2])}
        reservations = {r["asset_id"]: r for r in opportunities["asset_reservations"]}
        memory_path = CONTENT_MEMORY_OUTPUT_DIRECTORY / f"{project_id}-content-memory.json"
        memory = _read(memory_path, {"project_id": project_id, "items": []})
        previous_titles = {i.get("title", "").strip().casefold() for i in memory.get("items", [])}
        usage: dict[str, int] = Counter(aid for i in memory.get("items", []) if i.get("status") not in {"rejected", "archived"} for aid in i.get("selected_asset_ids", []))
        personas = [p.get("name") for p in strategy.get("buyer_personas", []) if isinstance(p, dict) and p.get("name")] or strategy.get("target_audience", []) or ["supported project buyer"]
        if opportunities.get("contract_role") != "compatibility_visual_opportunities" or opportunities.get("derived_from_canonical_inventory") is not True:
            raise ValueError("Planning requires a compatibility artifact derived from canonical inventory")
        canonical_path = Path(str(opportunities.get("canonical_inventory_path", "")))
        if not canonical_path.is_file():raise ValueError("Canonical content opportunity inventory is missing")
        canonical_payload=_read(canonical_path,{})
        d2_fingerprint=canonical_graph_fingerprint(knowledge)
        require_lineage(
            canonical_payload,
            expected_stage="department3-content-opportunity-inventory",
            canonical_fingerprint=d2_fingerprint,
        )
        canonical = load_content_opportunity_inventory(canonical_path)
        if canonical.project_id != project_id:raise ValueError("Canonical inventory project does not match planning project")
        if opportunities.get("canonical_inventory_version") != canonical.inventory_version:raise ValueError("Canonical inventory version mismatch")
        expected_hash=str(opportunities.get("canonical_inventory_sha256") or "")
        actual_hash=hashlib.sha256(canonical_path.read_bytes()).hexdigest()
        if not expected_hash or expected_hash!=actual_hash:raise ValueError("Canonical inventory hash mismatch")
        groups = legacy_visual_opportunities(canonical, list(assets.values()))
        groups = [g for g in groups if g["overall_confidence"] >= .5 and g.get("readiness") != "blocked"]
        if reci:
            blocked_categories={x.get("category") for x in reci.get("opportunities",[]) if x.get("status") in {"BLOCKED","REVIEW_REQUIRED"}}
            aliases={"introduction":"project","location":"location","architecture":"architecture","exterior":"architecture","interior":"interior","unit":"unit","layout":"unit","amenity":"amenity","commercial":"commercial","investment":"investment"}
            groups=[g for g in groups if aliases.get(g.get("canonical_category") or g.get("opportunity_type"),g.get("canonical_category")) not in blocked_categories]
            reci_by_category={x.get("category"):x for x in reci.get("opportunities",[])}
            for g in groups:
                entry=reci_by_category.get(aliases.get(g.get("canonical_category") or g.get("opportunity_type"),g.get("canonical_category")),{})
                g["recommended_patterns"]=entry.get("recommended_patterns",[])[:3];g["relevant_anti_patterns"]=entry.get("relevant_anti_patterns",[])
                g["pattern_usage"]=entry.get("pattern_usage",{})
        decision_by_category={}
        if campaign_intelligence:
            reci_by_id={x.get("opportunity_id"):x for x in reci.get("opportunities",[])}
            for decision in campaign_intelligence.get("strategic_queue",[]):
                if decision.get("status")!="APPROVED":continue
                source=reci_by_id.get(decision.get("reci_opportunity_id"),{});category=source.get("category")
                if category:decision_by_category[category]=decision
            aliases={"introduction":"project","location":"location","architecture":"architecture","exterior":"architecture","interior":"interior","unit":"unit","layout":"unit","amenity":"amenity","commercial":"commercial","investment":"investment"}
            groups=[g for g in groups if aliases.get(g.get("canonical_category") or g.get("opportunity_type"),g.get("canonical_category")) in decision_by_category]
        campaigns, items, repaired, prevented, downgraded = [], [], 0, 0, 0
        opening_selection_failures=[]
        for ci, group in enumerate(groups, 1):
            campaign_id = _stable_id("campaign", project_id, group["opportunity_id"])
            funnel = group["supported_funnel_stages"]
            selected = []
            selected_hashes = {}
            duplicate_sources = []
            purpose=role(group.get("canonical_subcategory") or group.get("canonical_category") or group["opportunity_type"])
            ranked = _reserved_candidates(group["supported_asset_ids"], assets, usage, reservations,purpose=purpose)
            if purpose=="project_overview":
                ranked=sorted(ranked,key=lambda a:(a.get("visual_purpose_review",{}).get("sequence",999),a["asset_id"]))
            for asset in ranked:
                reservation = reservations[asset["asset_id"]]
                if usage[asset["asset_id"]] >= reservation["maximum_reuse_count"]:
                    prevented += 1; continue
                if reservation["reservation_level"] == "review_required": downgraded += 1; continue
                source_hash=str(asset.get("source_hash") or "").strip().casefold()
                if source_hash and source_hash in selected_hashes:
                    duplicate_sources.append({"asset_id":asset["asset_id"],"same_source_as":selected_hashes[source_hash],"source_hash":source_hash,"reason":"identical source bytes"})
                    continue
                selected.append(asset)
                if source_hash:selected_hashes[source_hash]=asset["asset_id"]
                if len(selected) == min(10 if purpose=="project_overview" else 3, len(ranked)): break
            if purpose=="project_overview":
                errors=validate_overview_slides(selected,project_id)
                if errors:
                    opening_selection_failures.append({"opportunity_id":group["opportunity_id"],"errors":errors})
                    continue
            stage = funnel[min(ci-1, len(funnel)-1)]
            title = group["title"]
            if title.casefold() in previous_titles: title = f"{title}: {stage.title()}"
            fact_refs = group["supporting_fact_refs"][:4]
            visual_conf = (sum((_confidence(a)*.65 + _quality(a)/100*.35) for a in selected)/len(selected)) if selected else .5
            factual_conf = min(1.0, .45 + .1*len(fact_refs)) if fact_refs else .45
            overall = round(.55*visual_conf + .45*factual_conf, 3)
            if overall < .5: continue
            formats = [value for value in group["supported_formats"] if _format_channel(value) in allowed_channels]
            if not formats:formats=["Facebook Post" if platform_strategy==CampaignPlatformStrategy.FACEBOOK_ONLY else "Instagram Single Image"]
            fmt = formats[1] if len(selected)>1 and len(formats)>1 else formats[0]
            idea_id = _stable_id("content", project_id, campaign_id, group["opportunity_id"], stage)
            asset_ids = [a["asset_id"] for a in selected]
            concept = _concept(group, selected, fmt)
            concept = CAMERA_TERMS.sub("presentation", concept)
            item = {"content_idea_id": idea_id, "campaign_id": campaign_id, "pillar_id": _stable_id("pillar", campaign_id, group["opportunity_type"]),
                    "series_id": _stable_id("series", campaign_id, stage), "sequence": len(items)+1, "title": title,
                    "content_category": group.get("canonical_subcategory") or group.get("canonical_category") or group["opportunity_type"],
                    "content_objective": f"Support {stage} with verified {group['title'].casefold()} evidence.", "funnel_stage": stage,
                    "target_persona": personas[(ci-1)%len(personas)], "selected_opportunity_id": group["opportunity_id"],
                    "selected_source_asset_ids": asset_ids, "selected_fact_refs": fact_refs,
                    "visual_evidence": [f"{a['asset_id']}: {a.get('dominant_subject', group['opportunity_type'])}" for a in selected],
                    "factual_evidence": fact_refs, "concept_summary": concept,
                    "message_hierarchy": [group["title"], *fact_refs[:2]], "feasible_platforms": group["supported_platforms"] or ["Instagram"],
                    "feasible_formats": formats, "orientation": _orientation(selected),
                    "asset_usage_reason": "Highest-ranked unused compatible assets within reservation and reuse limits.",
                    "source_support_status": "fully_supported" if fact_refs and selected else "text_only" if fact_refs else "partially_supported",
                    "overall_confidence": overall, "visual_confidence": round(visual_conf, 3), "factual_confidence": round(factual_conf, 3),
                    "uniqueness_score": _set_uniqueness(selected, usage), "repetition_risk": "low", "limitations": group["limitations"],
                    "forbidden_claims": group["forbidden_claims"],
                    "creative_pattern_references": group.get("recommended_patterns",[])[:3],"creative_anti_patterns":group.get("relevant_anti_patterns",[]),
                    "pattern_usage":group.get("pattern_usage",{}),"pattern_factual_authority":"NONE",
                    "downstream_instructions": {"campaign_context": group["title"], "funnel_stage": stage, "message_hierarchy": [group["title"], *fact_refs[:2]], "asset_reservation_constraints": [reservations[x] for x in asset_ids]} }
            story_feasible=any(str(value).casefold() in {"story","instagram story","instagram_story"} for value in formats)
            story_suitable=purpose!="project_overview" and story_feasible and bool(selected) and ci % 3 == 0 and group.get("opportunity_type") not in {"commercial","investment","unit"}
            selected_format="story" if story_suitable else ("carousel" if len(selected)>1 and any("carousel" in str(x).casefold() for x in formats) else "single_post")
            from src.publication import publication_intent
            item["duplicate_source_exclusions"]=duplicate_sources
            item["selected_format"]=selected_format
            item["planned_publication"]=publication_intent(selected_format)
            item["public_copy"]={"project_name":project_id,"headline":title,"subheadline":None,"cta":None,"website":None}
            if decision_by_category:
                category_alias={"introduction":"project","location":"location","architecture":"architecture","exterior":"architecture","interior":"interior","unit":"unit","layout":"unit","amenity":"amenity","commercial":"commercial","investment":"investment"}
                decision=decision_by_category.get(category_alias.get(group.get("canonical_category") or group.get("opportunity_type"),group.get("canonical_category")),{})
                item.update(campaign_decision_id=decision.get("decision_id"),campaign_role=decision.get("campaign_role"),cta_intent=decision.get("cta_intent"),cta_intensity=decision.get("cta_intensity"),sequence_priority=decision.get("priority"),campaign_decision_restrictions=decision.get("restrictions",[]))
                item["downstream_instructions"]["campaign_decision"]={k:decision.get(k) for k in ("decision_id","objective","campaign_role","content_angle","cta_intent","cta_intensity","restrictions","blocked_claims")}
            item["repetition_risk"] = "high" if item["uniqueness_score"]<40 else "medium" if item["uniqueness_score"]<70 else "low"
            supported = {str(x).casefold() for x in item["feasible_platforms"]}
            if platform_strategy == CampaignPlatformStrategy.INSTAGRAM_ONLY: destinations = ["instagram"]
            elif platform_strategy == CampaignPlatformStrategy.FACEBOOK_ONLY: destinations = ["facebook"]
            elif platform_strategy == CampaignPlatformStrategy.BOTH_MIRRORED: destinations = ["instagram", "facebook"]
            else:
                eligible = [p for p in ("instagram", "facebook") if not supported or p in supported]
                destinations = eligible or ["instagram", "facebook"]
            item.update(master_concept_id=campaign_id, platform_strategy=platform_strategy.value,
                        planned_destinations=destinations,
                        platform_rationale=("Shared creative with semantic equivalence and compatibility-only adaptation."
                            if platform_strategy == CampaignPlatformStrategy.BOTH_MIRRORED else
                            "Destinations selected from verified asset format suitability and campaign objective."),
                        platform_packaging="platform_specific" if platform_strategy == CampaignPlatformStrategy.BOTH_PLATFORM_OPTIMIZED and len(destinations)>1 else "shared")
            items.append(item)
            for aid in asset_ids: usage[aid] += 1
            campaigns.append({"campaign_id": campaign_id, "campaign_name": group["title"], "campaign_objective": item["content_objective"],
                "target_personas": group["supported_personas"] or personas, "primary_funnel_stage": stage,
                "secondary_funnel_stage": funnel[1] if len(funnel)>1 else stage, "core_message": group["title"],
                "supporting_messages": fact_refs, "approved_opportunity_ids": [group["opportunity_id"]],
                "campaign_anchor_asset_ids": asset_ids[:1], "duration": min(4, group["reuse_capacity"]),
                "content_sequence": [idea_id], "asset_usage_budget": {aid: reservations[aid]["maximum_reuse_count"] for aid in asset_ids},
                "success_intent": f"Advance supported personas through {stage}.", "restrictions": group["forbidden_claims"]})
            campaigns[-1]["creative_pattern_ids"]=[x.get("pattern_id") for x in group.get("recommended_patterns",[])[:3]]
        allocation=_platform_allocation(items,platform_strategy)
        canonical_meta={"derived_from_canonical_inventory":True,"canonical_inventory_path":str(canonical_path),"canonical_inventory_version":canonical.inventory_version,"canonical_inventory_sha256":actual_hash,
            "creative_opportunity_map_path":str(creative_intelligence_path) if creative_intelligence_path else None,"creative_opportunity_map_fingerprint":reci.get("input_fingerprint") if reci else None,"reci_restrictions_enforced":bool(reci)}
        canonical_meta.update(campaign_decision_contract_path=str(campaign_intelligence_path) if campaign_intelligence_path else None,campaign_decision_contract_hash=campaign_intelligence.get("contract_hash") if campaign_intelligence else None,campaign_intelligence_enforced=bool(campaign_intelligence))
        parent_fingerprint=str(canonical_payload.get("artifact_fingerprint") or artifact_fingerprint(canonical_payload))
        campaign_plan = attach_lineage(
            {"project_id": project_id, "contract_role": "compatibility_campaign_plan", **canonical_meta, "platform_strategy": platform_strategy.value, "allowed_channels": sorted(allowed_channels), "platform_allocation":allocation, "campaigns": campaigns},
            stage="department3-campaign-plan",
            canonical_fingerprint=d2_fingerprint,
            parents={"content_opportunity_inventory":parent_fingerprint},
        )
        content_plan = attach_lineage(
            {"project_id": project_id, "contract_role": "compatibility_content_plan", **canonical_meta, "planner_version": VERSION, "planning_mode": "knowledge_first_canonical_inventory_adapter", "platform_strategy": platform_strategy.value, "allowed_channels": sorted(allowed_channels), "platform_allocation":allocation, "content_ideas": items,"opening_selection_failures":opening_selection_failures},
            stage="department3-content-plan",
            canonical_fingerprint=d2_fingerprint,
            parents={"content_opportunity_inventory":parent_fingerprint},
        )
        campaign_path = CAMPAIGNS_OUTPUT_DIRECTORY / f"{project_id}-campaign-plan.json"
        if write_campaign:
            _write(campaign_path, campaign_plan)
        content_path = _write(CONTENT_OUTPUT_DIRECTORY / f"{project_id}-content-plan.json", content_plan)
        ledger_items = []
        for aid, reservation in sorted(reservations.items()):
            uses = [i for i in items if aid in i["selected_source_asset_ids"]]
            ledger_items.append({"asset_id": aid, "campaign_ids": sorted({i["campaign_id"] for i in uses}), "content_idea_ids": [i["content_idea_id"] for i in uses],
                "usage_count": usage[aid], "maximum_reuse_count": reservation["maximum_reuse_count"], "last_planned_sequence": max([i["sequence"] for i in uses], default=None),
                "reservation_level": reservation["reservation_level"], "repetition_risk": "high" if usage[aid]>=reservation["maximum_reuse_count"] else "low"})
        ledger_path = _write(ASSET_USAGE_OUTPUT_DIRECTORY / f"{project_id}-asset-usage.json", {"project_id": project_id, "assets": ledger_items})
        now = datetime.now(timezone.utc).isoformat()
        new_memory = [{"content_idea_id": i["content_idea_id"], "campaign_id": i["campaign_id"], "title": i["title"], "funnel_stage": i["funnel_stage"],
            "selected_asset_ids": i["selected_source_asset_ids"], "selected_fact_refs": i["selected_fact_refs"], "content_theme": i["selected_opportunity_id"],
            "planned_sequence": i["sequence"], "status": "planned", "created_at": now, "planner_version": VERSION} for i in items]
        existing = {i.get("content_idea_id"): i for i in memory.get("items", [])}
        for item in new_memory: existing[item["content_idea_id"]] = item
        memory_path = _write(memory_path, {"project_id": project_id, "items": list(existing.values())})
        graph_path = _write(CAMPAIGNS_OUTPUT_DIRECTORY / f"{project_id}-campaign-graph.json", _graph(campaigns, items))
        report_path = _write(REPORTS_OUTPUT_DIRECTORY / f"{project_id}-planning-quality-report.json", _report(opportunities, campaigns, items, assets, usage, repaired, prevented, downgraded))
        return {"campaign_plan": campaign_path, "content_plan": content_path, "asset_usage": ledger_path, "content_memory": memory_path, "campaign_graph": graph_path, "quality_report": report_path}

def _platform_allocation(items:list[dict[str,Any]],strategy:CampaignPlatformStrategy)->dict[str,Any]:
    instagram_only=sum(x.get("planned_destinations")==["instagram"] for x in items);facebook_only=sum(x.get("planned_destinations")==["facebook"] for x in items);shared=sum(set(x.get("planned_destinations",[]))=={"instagram","facebook"} for x in items)
    instagram=sum("instagram" in x.get("planned_destinations",[]) for x in items);facebook=sum("facebook" in x.get("planned_destinations",[]) for x in items)
    justified=any("asymmetric" in str(x.get("platform_rationale","")).casefold() or "explicit" in str(x.get("platform_rationale","")).casefold() for x in items)
    warnings=[]
    if strategy==CampaignPlatformStrategy.BOTH_PLATFORM_OPTIMIZED and not justified and ((instagram==0 and facebook>1) or (facebook==0 and instagram>1)):warnings.append({"warning_type":"platform_allocation_warning","reason":"One configured Meta destination received no planned content while the other received multiple ideas."})
    return {"instagram_only_ideas":instagram_only,"facebook_only_ideas":facebook_only,"shared_concepts":shared,"instagram_variants":instagram,"facebook_variants":facebook,"warnings":warnings}


def _reserved_candidates(asset_ids, assets, usage, reservations, *, purpose=None):
    """Only existing project-scoped reservations may authorize asset selection."""
    return sorted((assets[aid] for aid in asset_ids if aid in assets and aid in reservations and (not reservations[aid].get("allowed_purposes") or purpose in reservations[aid]["allowed_purposes"])),
                  key=lambda a: (-_rank(a, usage, reservations), a["asset_id"]))


def _rank(asset: dict[str, Any], usage: dict[str, int], reservations: dict[str, dict[str, Any]]) -> float:
    return _quality(asset)*.4 + _confidence(asset)*40 + (10 if asset.get("safe_crop_assessment", {}).get("level")=="flexible" else 0) + (15 if usage[asset["asset_id"]]==0 else -15*usage[asset["asset_id"]])


def _orientation(items: list[dict[str, Any]]) -> str:
    if not items: return "Square"
    return Counter(str(a.get("orientation", "square")).title() for a in items).most_common(1)[0][0]


def _set_uniqueness(items: list[dict[str, Any]], usage: dict[str, int]) -> int:
    if not items: return 100
    diversity = _diversity(items); reuse = sum(usage[a["asset_id"]] for a in items)/len(items)
    return max(0, min(100, round(diversity - reuse*20 + 20)))


def _concept(group: dict[str, Any], assets: list[dict[str, Any]], fmt: str) -> str:
    if not assets:
        return f"Present the verified {group['title'].casefold()} opportunity as a {fmt} using factual text; visual production remains optional downstream."
    subjects = list(dict.fromkeys(str(a.get("dominant_subject", group["opportunity_type"])) for a in assets))
    return f"Present {len(assets)} approved {group['opportunity_type'].replace('_', ' ')} asset(s) as a {fmt}, emphasizing {', '.join(subjects)} and only the verified facts listed for this item."


def _graph(campaigns: list[dict[str, Any]], items: list[dict[str, Any]]) -> dict[str, Any]:
    nodes, edges, seen = [], [], set()
    def node(node_id: str, kind: str, label: str) -> None:
        if node_id not in seen: seen.add(node_id); nodes.append({"id": node_id, "type": kind, "label": label})
    for c in campaigns:
        node(c["campaign_id"], "campaign", c["campaign_name"])
    ordered = sorted(items, key=lambda i: i["sequence"])
    for index, item in enumerate(ordered):
        for nid, kind, label in ((item["pillar_id"], "pillar", item["selected_opportunity_id"]), (item["series_id"], "series", item["funnel_stage"]), (item["content_idea_id"], "content_item", item["title"]), (item["funnel_stage"], "funnel_stage", item["funnel_stage"]), (item["target_persona"], "persona", item["target_persona"])): node(nid, kind, label)
        edges += [{"from": item["pillar_id"], "to": item["campaign_id"], "relationship": "belongs_to"}, {"from": item["series_id"], "to": item["pillar_id"], "relationship": "belongs_to"}, {"from": item["content_idea_id"], "to": item["series_id"], "relationship": "belongs_to"}, {"from": item["content_idea_id"], "to": item["target_persona"], "relationship": "targets"}, {"from": item["content_idea_id"], "to": item["funnel_stage"], "relationship": "supports"}]
        for aid in item["selected_source_asset_ids"]: node(aid, "asset", aid); edges.append({"from": item["content_idea_id"], "to": aid, "relationship": "uses_asset"})
        for fact in item["selected_fact_refs"]: node(fact, "fact", fact); edges.append({"from": item["content_idea_id"], "to": fact, "relationship": "uses_fact"})
        if index: edges.append({"from": ordered[index-1]["content_idea_id"], "to": item["content_idea_id"], "relationship": "follows"})
    return {"nodes": nodes, "relationships": edges}


def _report(opps: dict[str, Any], campaigns: list[dict[str, Any]], items: list[dict[str, Any]], assets: dict[str, dict[str, Any]], usage: dict[str, int], repaired: int, prevented: int, downgraded: int) -> dict[str, Any]:
    avg = lambda key: round(sum(i[key] for i in items)/len(items), 3) if items else 0
    used = {aid for i in items for aid in i["selected_source_asset_ids"]}
    categories = Counter(_canonical_type(assets[aid]) for aid in used)
    funnel = Counter(i["funnel_stage"] for i in items); personas = Counter(i["target_persona"] for i in items)
    return {"total_opportunities": len(opps["visual_opportunity_groups"]), "total_campaigns": len(campaigns), "total_content_ideas": len(items),
        "fully_supported_ideas": sum(i["source_support_status"]=="fully_supported" for i in items), "partially_supported_ideas": sum(i["source_support_status"]=="partially_supported" for i in items),
        "text_supported_ideas": 0, "skipped_unavailable_ideas": 0, "unsupported_concepts_repaired": repaired, "hallucinated_claims_removed": repaired,
        "duplicate_concepts_removed": 0, "asset_reuse_violations_prevented": prevented, "low_confidence_items_downgraded": downgraded,
        "funnel_coverage": dict(funnel), "persona_coverage": dict(personas), "asset_category_coverage": dict(categories),
        "content_repetition_score": round(100 - avg("uniqueness_score"), 2), "average_factual_confidence": avg("factual_confidence"),
        "average_visual_confidence": avg("visual_confidence"), "average_uniqueness_score": avg("uniqueness_score"),
        "unused_high_quality_assets": sorted(aid for aid,a in assets.items() if aid not in used and _quality(a)>=75 and _confidence(a)>=.7),
        "scarce_asset_categories": sorted(k for k,v in Counter(_canonical_type(a) for a in assets.values()).items() if v<2), "warnings": opps.get("warnings", [])}
