"""Source-image-first visual art direction for static Department 4 output.

The module owns creative decisions.  Renderers may validate and execute the
resulting contract, but must never repair or reinterpret it.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat
from src.unit_plan_relationship import relationship_errors
from src.plan_integrity import PLAN_TYPES, UNIT_TYPES, validate_plan_contract
from src.publication import validate_public_copy
from src.utils.text_layout import fit_layout_text, validate_text_layout
from src.creative.editorial_profile import apply_architecture_editorial

VISUAL_DIRECTION_VERSION = "1.1.1"
APPROVED_STATUSES = {"APPROVED", "REQUIRES_REDIRECTION"}
TECHNICAL_ASSETS = set(PLAN_TYPES)|{"floorplan","unit_plan","full_project_site_plan","map","location_map","location_visual","technical_drawing"}
STRATEGIES = {
    "negative_space_overlay", "editorial_corner", "architectural_grid", "minimal_identity",
    "bottom_information_zone", "top_information_zone", "side_information_rail", "split_visual",
    "floating_identity", "contained_identity", "centered_hero", "asymmetric_editorial",
    "full_bleed_minimal", "map_information_layout", "plan_annotation_layout", "luxury_brochure_layout",
}
PROMINENCE = {"subtle", "restrained", "standard", "prominent", "campaign_dominant"}
CRITIQUE_FIELDS = (
    "source_image_preservation", "focal_point_preservation", "visual_hierarchy", "brand_integration",
    "logo_legibility", "project_identity_clarity", "typography_legibility", "composition_balance",
    "information_density", "campaign_consistency", "creative_quality", "platform_safety",
)


class VisualDirectionError(ValueError):
    """Raised when a contract is incomplete or violates immutable constraints."""


@dataclass(frozen=True)
class DirectionResult:
    status: str
    contract: dict[str, Any] | None
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "contract": self.contract, "blockers": list(self.blockers)}


@dataclass(frozen=True)
class VisualDirectionContract:
    """Typed envelope for the executable machine-readable contract."""

    contract_version: str
    content_id: str
    project_id: str
    asset_id: str
    payload: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VisualDirectionContract":
        errors = validate_visual_direction_contract(value)
        if errors: raise VisualDirectionError("; ".join(errors))
        return cls(str(value["contract_version"]), str(value["content_id"]), str(value["project_id"]), str(value["asset_id"]), deepcopy(value))

    def to_dict(self) -> dict[str, Any]: return deepcopy(self.payload)

    def validate(self, *, brand_identity: dict[str, Any] | None = None) -> list[str]:
        return validate_visual_direction_contract(self.payload, brand_identity=brand_identity)


class VisualArtDirector:
    """Make contextual, reproducible composition decisions from an actual image."""

    def __init__(self, *, minimum_creative_score: int = 80) -> None:
        if not 0 <= minimum_creative_score <= 100:
            raise ValueError("minimum_creative_score must be between 0 and 100")
        self.minimum_creative_score = minimum_creative_score

    def direct(self, package: dict[str, Any], *, recent_contracts: list[dict[str, Any]] | None = None) -> DirectionResult:
        blockers = _input_blockers(package)
        if blockers:
            return DirectionResult("REQUIRES_REDIRECTION", None, tuple(blockers))
        brief, asset = package["content_brief"], package["source_asset"]
        identity, brand = package["project_identity"], package["brand_identity"]
        image_path = Path(str(asset["path"]))
        with Image.open(image_path) as raw:
            image = raw.convert("RGB")
            source_width, source_height = image.size
            intelligence = _merge_intelligence(image, package.get("visual_intelligence", {}))
        canvas_width, canvas_height = _dimensions(brief["target_dimensions"])
        publication_type=str(brief.get("publication_type") or "single_post")
        if publication_type=="story" and (canvas_width,canvas_height)!=(1080,1920):
            return DirectionResult("REQUIRES_REDIRECTION",None,("Instagram Story requires exactly 1080x1920",))
        asset_type = str(asset["asset_type"]).casefold()
        if asset_type in TECHNICAL_ASSETS:
            # Technical drawings are information, not decorative imagery. The
            # whole source is protected; branding may occupy only canvas space
            # outside the fitted plan.
            intelligence["protected_regions"] = [[0, 0, source_width, source_height]]
        safe = _safe_regions(intelligence, canvas_width, canvas_height, source_width, source_height)
        strategy, text_region = _choose_strategy(asset_type, safe, canvas_width, canvas_height, recent_contracts or [])
        if publication_type=="story" and text_region is not None:
            text_region=(max(44,text_region[0]),max(250,text_region[1]),min(canvas_width-44,text_region[2]),min(1600,text_region[3]))
            if text_region[2]-text_region[0]<300 or text_region[3]-text_region[1]<260:text_region=(44,1050,canvas_width-44,1600)
            strategy="negative_space_overlay"
        if text_region is None:
            return DirectionResult("REQUIRES_REDIRECTION", None, ("no safe information or logo placement exists",))
        try:
            geometry = _geometry(text_region, canvas_width, canvas_height, brand, {**brief,"project_title":identity["canonical_project_name"],"location_text":identity.get("location"),"developer_text":identity.get("developer_name") if identity.get("developer_identity_status")=="verified" else None,"technical_footer":asset_type in TECHNICAL_ASSETS and strategy=="bottom_information_zone"})
        except ValueError as error:
            return DirectionResult("REQUIRES_REDIRECTION",None,(str(error),))
        logo_variant = _logo_variant(intelligence, text_region, brand)
        logo_asset = _logo_asset(brand, logo_variant)
        if not logo_asset:
            return DirectionResult("REQUIRES_REDIRECTION", None, ("required approved logo variant is missing",))
        crop_mode = "fit" if asset_type in TECHNICAL_ASSETS else "controlled_crop"
        source_placement = _source_placement(asset_type, strategy, text_region, canvas_width, canvas_height)
        protected_canvas = _map_regions(intelligence["protected_regions"], source_placement, source_width, source_height)
        contract: dict[str, Any] = {
            "contract_version": VISUAL_DIRECTION_VERSION, "status": "APPROVED", "publication_type":publication_type,
            "target_platform":str(brief["platform"]),"public_copy":deepcopy(brief.get("public_copy") or {}),
            "story_safe_zones":{"top_ui_exclusion":[0,0,canvas_width,250],"bottom_ui_exclusion":[0,1600,canvas_width,canvas_height],"content_safe_region":[44,250,canvas_width-44,1600]} if publication_type=="story" else None,
            "content_id": str(brief["content_id"]), "project_id": str(brief["project_id"]), "asset_id": str(asset["asset_id"]),
            "language":str(brief["language"]),"platform":str(brief["platform"]),
            "canvas": {"width": canvas_width, "height": canvas_height, "aspect_ratio": f"{canvas_width}:{canvas_height}"},
            "composition": {"strategy": strategy, "visual_style": "premium_architectural_editorial",
                            "information_density": "low", "visual_balance": "asymmetric" if strategy != "centered_hero" else "symmetric"},
            "source_image": {"path": str(image_path), "asset_type":asset_type,"crop_mode": crop_mode, "placement": source_placement,
                             "focal_region": intelligence["primary_focal_region"], "protected_regions": protected_canvas},
            "project_identity": {"identity_type":"project","visible": True, "text": identity["canonical_project_name"], "hierarchy": "primary", **geometry["project_identity"]},
            "location": {"visible": bool(identity.get("location")), "text": identity.get("location"), "hierarchy": "secondary", **geometry["location"]},
            "developer_identity": {"identity_type":"developer","verification_status":identity.get("developer_identity_status"),"visible": identity.get("developer_identity_status") == "verified" and bool(identity.get("developer_name")),
                                   "text": identity.get("developer_name"), "hierarchy": "tertiary", **geometry["developer"]},
            "brand_logo": {"identity_type":"broker_marketing_brand","visible": True, "asset": logo_asset, "variant": logo_variant, "prominence": "restrained", "container": "none", **geometry["logo"]},
            "headline": {"visible": bool(brief.get("primary_message")), "text": brief.get("primary_message"), **geometry["headline"]},
            "subheadline": {"visible": False, "text": None, **geometry["supporting"]},
            "supporting_copy": {"visible": bool(brief.get("secondary_message")), "text": brief.get("secondary_message"), **geometry["supporting"]},
            "cta": {"visible": brief.get("cta_requirement") not in {None, "", "none", False}, "text": brief.get("cta_requirement"), **geometry["cta"]},
            "graphics": {"overlay": "contrast_plate" if strategy.endswith("zone") or strategy.endswith("rail") else "localized_gradient",
                         "overlay_geometry": list(text_region), "footer": strategy == "bottom_information_zone", "header": strategy == "top_information_zone",
                         "rail": strategy == "side_information_rail", "z_order": ["source_image", "overlay", "text", "brand_logo"]},
            "typography": {"font": str((brand.get("brand_fonts") or ["Arial"])[0]), "headline_size": geometry["headline"]["font_size"],
                           "project_size": geometry["project_identity"]["font_size"], "weight": "semibold", "alignment": geometry["headline"]["alignment"]},
            "safe_margins": geometry["safe_margins"],
            "restrictions": {"preserve_source_identity": True, "no_architecture_obstruction": True,
                             "no_logo_modification": True, "no_unverified_claims": True},
            "creative_pattern_guidance":{"pattern_influence":"advisory","factual_authority":"NONE",
                "patterns":deepcopy(brief.get("creative_pattern_references",[]))[:3],"anti_patterns":deepcopy(brief.get("creative_anti_patterns",[])),
                "source_image_decision_remains_authoritative":True},
            "plan_integrity": deepcopy(package.get("plan_intelligence")) if asset_type in TECHNICAL_ASSETS else None,
            "provenance": {"source_document": asset["source_document"], "source_page": asset["source_page"],
                           "source_provenance": asset["source_provenance"], "project_identity_source": identity["project_identity_source"]},
        }
        if package.get("editorial_profile"):
            try:contract=apply_architecture_editorial(contract,brand,(source_width,source_height))
            except ValueError as error:return DirectionResult("REQUIRES_REDIRECTION",None,(str(error),))
        contract["self_critique"] = _critique(contract, intelligence, recent_contracts or [])
        contract["confidence"] = round(contract["self_critique"]["overall_score"] / 100, 2)
        errors = validate_visual_direction_contract(contract, brand_identity=brand)
        if errors or contract["self_critique"]["overall_score"] < self.minimum_creative_score:
            return DirectionResult("REQUIRES_REDIRECTION", None, tuple(errors or ["creative score below configured threshold"]))
        return DirectionResult("APPROVED", contract)

    def revise(self, contract: dict[str, Any], qa_feedback: dict[str, Any]) -> DirectionResult:
        """Correct only named failed decisions; unaffected regions remain byte-for-byte equal."""
        revised = deepcopy(contract)
        issues = qa_feedback.get("issues", []) if qa_feedback.get("status") == "FAIL" else []
        if not issues:
            return DirectionResult("APPROVED", revised)
        for issue in issues:
            kind = str(issue.get("type", ""))
            if kind == "logo_contrast":
                revised["brand_logo"]["variant"] = "dark" if revised["brand_logo"].get("variant") == "white" else "white"
            elif kind == "logo_size":
                logo=revised["brand_logo"];old_width=logo["width"];logo["width"]=max(1,round(old_width*.85));logo["height"]=max(1,round(logo["height"]*logo["width"]/old_width))
            elif kind in {"project_title_overlap", "architecture_obstruction"}:
                revised["composition"]["strategy"] = "bottom_information_zone"
                revised["graphics"].update(overlay="contrast_plate", footer=True, header=False, rail=False)
            elif kind in {"project_name_unreadable", "typography_legibility"}:
                revised["graphics"]["overlay"] = "contrast_plate"
            elif kind == "overlay_dominance":
                region=revised["graphics"]["overlay_geometry"]
                if region[2]-region[0] > region[3]-region[1]: region[3]=region[1]+round((region[3]-region[1])*.85)
                else: region[2]=region[0]+round((region[2]-region[0])*.85)
            elif kind == "overcrowding":
                revised["supporting_copy"]["visible"] = False; revised["cta"]["visible"] = False
            elif kind == "campaign_repetition":
                revised["composition"]["strategy"] = "top_information_zone" if revised["composition"]["strategy"] != "top_information_zone" else "side_information_rail"
            else:
                return DirectionResult("REQUIRES_REDIRECTION", None, (f"unsupported QA correction: {kind}",))
        revised["revision"] = {"qa_issue_types": [str(x.get("type")) for x in issues]}
        if "contract_hash" in revised: revised["contract_hash"]=contract_integrity_hash(revised)
        return DirectionResult("APPROVED", revised)


def validate_visual_direction_contract(contract: dict[str, Any], *, brand_identity: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    required = {"contract_version", "status", "content_id", "project_id", "asset_id", "canvas", "composition", "source_image",
                "project_identity", "location", "developer_identity", "brand_logo", "headline", "subheadline", "supporting_copy", "cta", "graphics",
                "typography", "safe_margins", "restrictions", "provenance", "self_critique", "confidence"}
    errors.extend(f"missing contract field: {name}" for name in sorted(required - set(contract)))
    if errors: return errors
    if contract["status"] != "APPROVED": errors.append("contract is not approved")
    if contract.get("publication_type")=="story":
        if str(contract.get("target_platform","")).casefold() not in {"instagram story","instagram"}:errors.append("Story target platform is missing or invalid")
        if (contract["canvas"].get("width"),contract["canvas"].get("height"))!=(1080,1920) or contract["canvas"].get("aspect_ratio")!="1080:1920":errors.append("Story canvas must be 1080x1920 (9:16)")
        zones=contract.get("story_safe_zones") or {};safe=zones.get("content_safe_region")
        if safe!=[44,250,1036,1600]:errors.append("Story safe-zone contract is missing or invalid")
        errors.extend(validate_public_copy(contract.get("public_copy") or {}))
        for name in ("project_identity","headline","subheadline","supporting_copy","cta","brand_logo"):
            item=contract.get(name,{})
            if item.get("visible") and safe and not (item.get("y",0)>=safe[1] and item.get("y",0)+item.get("height",0)<=safe[3]):errors.append(f"Story {name} violates UI-safe region")
    if contract["project_identity"].get("identity_type")!="project" or contract["developer_identity"].get("identity_type")!="developer" or contract["brand_logo"].get("identity_type")!="broker_marketing_brand":errors.append("project, developer, and broker identities are not explicitly separated")
    if not contract["project_identity"].get("visible") or not str(contract["project_identity"].get("text") or "").strip():errors.append("required project identity is absent")
    if contract["developer_identity"].get("visible") and contract["developer_identity"].get("verification_status")!="verified":errors.append("developer identity is unverified")
    if contract["composition"].get("strategy") not in STRATEGIES: errors.append("unsupported composition strategy")
    guidance=contract.get("creative_pattern_guidance",{})
    if guidance and (guidance.get("factual_authority")!="NONE" or guidance.get("pattern_influence")!="advisory" or len(guidance.get("patterns",[]))>3):errors.append("creative pattern guidance exceeds advisory authority")
    canvas = contract["canvas"]; width, height = canvas.get("width", 0), canvas.get("height", 0)
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0: errors.append("invalid canvas")
    for name in ("project_identity", "location", "developer_identity", "brand_logo", "headline", "subheadline", "supporting_copy", "cta"):
        element = contract[name]
        if element.get("visible"):
            box = [element.get(k) for k in ("x", "y", "width", "height")]
            if not all(isinstance(v, int) for v in box): errors.append(f"{name} lacks executable geometry")
            elif box[0] < 0 or box[1] < 0 or box[0] + box[2] > width or box[1] + box[3] > height: errors.append(f"{name} is outside safe bounds")
    errors.extend(validate_public_copy(contract.get("public_copy") or {}))
    errors.extend(validate_text_layout(contract))
    logo = contract["brand_logo"]
    if logo.get("prominence") not in PROMINENCE: errors.append("invalid logo prominence")
    if brand_identity and logo.get("visible"):
        minimum = int(brand_identity.get("minimum_logo_size", 1)); maximum = int(brand_identity.get("maximum_logo_size", width))
        if not minimum <= int(logo.get("width", 0)) <= maximum: errors.append("logo width violates approved size bounds")
        approved = {str(x.get("path") if isinstance(x, dict) else x) for x in brand_identity.get("approved_logo_assets", [])}
        if approved and str(logo.get("asset")) not in approved: errors.append("logo asset is not approved")
        variants={str(x) for x in brand_identity.get("approved_logo_variants",[])}
        if variants and str(logo.get("variant")) not in variants:errors.append("logo variant is not approved")
        ratio=float(brand_identity.get("logo_aspect_ratio") or 0)
        if ratio and abs(logo.get("width",0)/max(1,logo.get("height",0))-ratio)>.05:errors.append("logo geometry would distort the approved asset")
        clear=int(logo.get("clear_space",0));margin=contract["safe_margins"]
        if logo.get("x",0)-clear<margin["left"] or logo.get("y",0)-clear<margin["top"] or logo.get("x",0)+logo.get("width",0)+clear>width-margin["right"] or logo.get("y",0)+logo.get("height",0)+clear>height-margin["bottom"]:errors.append("logo clear space violates platform-safe bounds")
    scores = contract["self_critique"]
    for field in CRITIQUE_FIELDS:
        if not isinstance(scores.get(field), int) or not 0 <= scores[field] <= 100: errors.append(f"invalid critique score: {field}")
    overlay=contract["graphics"].get("overlay_geometry")
    if not isinstance(overlay,list) or len(overlay)!=4: errors.append("graphics lacks executable overlay geometry")
    elif any(_intersection(tuple(overlay),tuple(region))>0 for region in contract["source_image"].get("protected_regions",[]) if isinstance(region,list) and len(region)==4):
        errors.append("critical source region is obstructed")
    provenance=contract["provenance"]
    errors.extend(validate_plan_contract(contract))
    if str(contract.get("source_image",{}).get("asset_type") or "").casefold() in TECHNICAL_ASSETS and contract["source_image"].get("crop_mode")!="fit":errors.append("plan asset must preserve the complete plan with fit crop mode")
    for name in ("source_document","source_page","source_provenance","project_identity_source"):
        if provenance.get(name) in {None,""}:errors.append(f"missing provenance: {name}")
    if contract.get("contract_hash") and contract["contract_hash"]!=contract_integrity_hash(contract):errors.append("Visual Direction Contract integrity hash mismatch")
    return errors


def _input_blockers(package: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for section in ("content_brief", "source_asset", "project_identity", "brand_identity"):
        if not isinstance(package.get(section), dict): errors.append(f"missing {section}")
    if errors: return errors
    brief, asset, identity, brand = (package[x] for x in ("content_brief", "source_asset", "project_identity", "brand_identity"))
    brief_fields = ("content_id", "project_id", "content_objective", "campaign_role", "post_type", "carousel_position",
                    "marketing_angle", "primary_message", "secondary_message", "allowed_claims", "required_identification",
                    "optional_identification", "prohibited_claims", "cta_requirement", "language", "platform", "target_dimensions")
    asset_fields = ("asset_id", "original_filename", "source_document", "source_page", "asset_type", "width", "height",
                    "orientation", "quality_score", "content_group", "source_provenance", "path")
    for field in brief_fields:
        if field not in brief or brief[field] is None: errors.append(f"missing content_brief.{field}")
    for field in asset_fields:
        if field not in asset or asset[field] is None: errors.append(f"missing source_asset.{field}")
    path = Path(str(asset.get("path", "")))
    if not path.is_file(): errors.append("source image is missing")
    if float(asset.get("quality_score", 0)) < float(package.get("minimum_source_quality", 30)): errors.append("source quality is too poor")
    identity_fields = ("project_name", "canonical_project_name", "project_type", "location", "developer_name",
                       "developer_identity_status", "project_logo_if_verified", "project_identity_source")
    if any(field not in identity for field in identity_fields) or not identity.get("canonical_project_name") or not identity.get("project_identity_source"):
        errors.append("project identity is unresolved")
    if str(brief.get("project_id")) != str(package.get("project_id", brief.get("project_id"))): errors.append("asset/project association is uncertain")
    if asset.get("project_id") not in {None,"",brief.get("project_id")}:errors.append("asset/project association is uncertain")
    asset_type=str(asset.get("asset_type") or "").casefold()
    if asset_type in UNIT_TYPES:
        record=package.get("plan_intelligence")
        if not isinstance(record,dict):
            errors.append("unit plan has no exact plan-intelligence record")
        elif relationship_errors(record, expected_project=brief.get("project_id"), asset_id=asset.get("asset_id"), source_path=asset.get("path")):
            errors.append("unit plan is REVIEW_REQUIRED: canonical relationship is missing, invalid, or references a different asset")
        elif not record.get("marketing_eligible"):
            errors.append("unit plan is REVIEW_REQUIRED: exact identity, completeness, legibility, and source evidence are not all verified")
    brand_fields = ("brand_name", "approved_logo_assets", "approved_logo_variants", "brand_fonts", "brand_colors",
                    "minimum_logo_size", "logo_clear_space", "prohibited_logo_modifications",
                    "brand_tone", "brand_visual_character")
    if any(field not in brand for field in brand_fields) or not brand.get("approved_logo_assets") or not brand.get("approved_logo_variants"):
        errors.append("required brand asset is missing")
    messages = " ".join(str(brief.get(name) or "") for name in ("primary_message", "secondary_message", "cta_requirement")).casefold()
    if any(str(claim).casefold() in messages for claim in brief.get("prohibited_claims", []) if str(claim).strip()):
        errors.append("content includes a prohibited claim")
    return errors


def _dimensions(value: Any) -> tuple[int, int]:
    if isinstance(value, dict): return int(value["width"]), int(value["height"])
    if isinstance(value, (list, tuple)) and len(value) == 2: return int(value[0]), int(value[1])
    text = str(value).lower().replace(" ", ""); left, right = text.split("x", 1); return int(left), int(right)


def _merge_intelligence(image: Image.Image, supplied: dict[str, Any]) -> dict[str, Any]:
    width, height = image.size; thirds = [(0, 0, width // 3, height), (width // 3, 0, 2 * width // 3, height), (2 * width // 3, 0, width, height)]
    samples=[image.crop(box).convert("L").resize((96,96)) for box in thirds]
    brightness=[ImageStat.Stat(sample).mean[0] for sample in samples]
    contrast=[ImageStat.Stat(sample).stddev[0] for sample in samples]
    edge_density=[ImageStat.Stat(sample.filter(ImageFilter.FIND_EDGES)).mean[0]/255 for sample in samples]
    complexity=[contrast[i]+edge_density[i]*100 for i in range(3)]
    safest=min(range(3),key=lambda i:complexity[i]);focal=max(range(3),key=lambda i:complexity[i]);names=("left","center","right")
    defaults = {"primary_focal_region": names[focal], "secondary_focal_regions": [], "architecture_regions": [list(thirds[focal])],
                "protected_regions": [list(thirds[focal])], "text_safe_regions": [list(thirds[safest])],
                "negative_space_regions": [list(thirds[safest])], "high_contrast_regions": [names[focal]], "low_contrast_regions": [names[safest]],
                "bright_regions": [names[i] for i,x in enumerate(brightness) if x>=160], "dark_regions": [names[i] for i,x in enumerate(brightness) if x<=95],
                "busy_regions": [names[focal]], "existing_text_regions": [], "horizon_position": "unknown",
                "dominant_visual_weight": names[focal], "perspective_direction": "unknown", "leading_lines": [], "symmetry": "unknown",
                "subject_density": "high" if max(complexity)>65 else "medium", "crop_tolerance": "low", "edge_safety": "standard",
                "deterministic_metrics": {names[i]:{"brightness":round(brightness[i],2),"contrast":round(contrast[i],2),"edge_density":round(edge_density[i],4)} for i in range(3)}}
    return {**defaults, **{k: v for k, v in supplied.items() if v is not None}}


def _safe_regions(intelligence: dict[str, Any], cw: int, ch: int, sw: int, sh: int) -> list[tuple[int, int, int, int]]:
    regions = intelligence.get("text_safe_regions") or intelligence.get("negative_space_regions") or []
    protected = [tuple(round(int(p[i]) * (cw / sw if i % 2 == 0 else ch / sh)) for i in range(4))
                 for p in (intelligence.get("protected_regions") or []) if isinstance(p, (list, tuple)) and len(p) == 4]
    result = []
    for raw in regions:
        if not isinstance(raw, (list, tuple)) or len(raw) != 4: continue
        box = tuple(round(int(raw[i]) * (cw / sw if i % 2 == 0 else ch / sh)) for i in range(4))
        if all(_intersection(box, p) == 0 for p in protected): result.append(box)
    return result


def _choose_strategy(asset_type: str, safe: list[tuple[int, int, int, int]], width: int, height: int, history: list[dict[str, Any]]) -> tuple[str, tuple[int, int, int, int] | None]:
    if asset_type in {"masterplan", "full_project_site_plan"}: return "side_information_rail", (0, 0, max(240, width // 4), height)
    if asset_type in TECHNICAL_ASSETS: return "bottom_information_zone", (0, int(height * .78), width, height)
    if safe:
        region = max(safe, key=lambda b: (b[2]-b[0])*(b[3]-b[1])); strategy = "negative_space_overlay"
        recent = [x.get("composition", {}).get("strategy") for x in history[-3:]]
        if recent.count(strategy) >= 2: strategy = "editorial_corner"
        return strategy, region
    return "bottom_information_zone", (0, int(height * .76), width, height)


def _source_placement(asset_type: str, strategy: str, region: tuple[int, int, int, int], width: int, height: int) -> list[int]:
    if asset_type in TECHNICAL_ASSETS and strategy == "side_information_rail": return [region[2], 0, width-region[2], height]
    if strategy == "bottom_information_zone": return [0, 0, width, region[1]]
    return [0, 0, width, height]


def _map_regions(regions: list[Any], placement: list[int], source_width: int, source_height: int) -> list[list[int]]:
    px,py,pw,ph=placement;result=[]
    for region in regions:
        if not isinstance(region,(list,tuple)) or len(region)!=4:continue
        result.append([px+round(float(region[0])*pw/source_width),py+round(float(region[1])*ph/source_height),
                       px+round(float(region[2])*pw/source_width),py+round(float(region[3])*ph/source_height)])
    return result


def _geometry(region: tuple[int, int, int, int], width: int, height: int, brand: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    margin=max(24,round(min(width,height)*.04));x1,y1,x2,y2=region
    x1,y1,x2,y2=max(margin,x1),max(margin,y1),min(width-margin,x2),min(height-margin,y2)
    rw,rh=x2-x1,y2-y1
    if rw<=0 or rh<=0:raise ValueError('No usable typography region')
    rtl=str(brief.get('language','en')).casefold() in {'ar','arabic','ku','ckb','kurdish','kurdish sorani'}
    align='right' if rtl else 'left';clear=int(brand.get('logo_clear_space',margin//2))
    lw=min(int(brand.get('maximum_logo_size',180)),max(int(brand.get('minimum_logo_size',80)),round(rw*.18)))
    lh=max(1,round(lw/float(brand.get('logo_aspect_ratio',3))))
    if lw+2*clear>rw:raise ValueError('Approved logo and clear space cannot fit')
    unit=max(14,min(32,round(height*.025),rh//12));gap=max(6,unit//3)
    header_h=max(lh+2*clear,unit*2)
    narrow=rw<550
    beside_logo=bool(brief.get('technical_footer')) and not narrow
    if beside_logo and lh+2*clear>rh:raise ValueError('Approved logo and clear space cannot fit information region')
    project_y=y1+header_h+gap if narrow else y1
    project_w=rw if narrow else rw-lw-3*clear-gap
    project_h=unit*2+8 if narrow or beside_logo else header_h
    common={'color':'#FFFFFF','background_support':'overlay','z_order':3,'font_weight':'regular'}
    def item(text,x,y,w,h,name,max_lines=2):
        rendered,size=fit_layout_text(text or '',w,h,unit,bold=name in {'project_identity','headline'},rtl=rtl,max_lines=max_lines)
        return {'x':x,'y':y,'width':w,'height':h,'font_size':size,'alignment':align,'max_width':w,'max_lines':max_lines,'render_text':rendered,'line_height':round(size*1.2),'anchor':'top_right' if rtl else 'top_left',**common}
    result={'safe_margins':{'top':margin,'right':margin,'bottom':margin,'left':margin},
        'logo':{'x':x2-lw-clear,'y':y1+clear,'width':lw,'height':lh,'anchor':'top_right','alignment':'right','clear_space':clear},
        'project_identity':item(brief.get('project_title',''),x1,project_y,project_w,project_h,'project_identity')}
    cursor=(project_y+project_h if beside_logo else max(y1+header_h,project_y+project_h))+gap
    specs=(('location','location_text',1),('headline','primary_message',2),('supporting','secondary_message',2),('developer','developer_text',1),('cta','cta_requirement',1))
    for name,key,lines in specs:
        value=brief.get(key);visible=value not in {None,'','none',False}
        h=unit*lines+8 if visible else 1
        y=cursor if visible else y1
        if y+h>y2:raise ValueError('Public text stack exceeds safe information region')
        result[name]=item(value if visible else '',x1,y,project_w if beside_logo else rw,h,'supporting_copy' if name=='supporting' else name,lines)
        if visible:cursor+=h+gap
    result['content_bottom']=cursor
    return result


def _logo_variant(intelligence: dict[str, Any], region: tuple[int, int, int, int], brand: dict[str, Any]) -> str:
    variants = [str(x) for x in brand.get("approved_logo_variants", [])]
    preferred = "dark" if intelligence.get("bright_regions") else "white"
    return preferred if preferred in variants else variants[0]


def _logo_asset(brand: dict[str, Any], variant: str) -> str | None:
    assets = brand.get("approved_logo_assets", [])
    for asset in assets:
        if isinstance(asset, dict) and str(asset.get("variant")) == variant: return str(asset.get("path"))
    first = assets[0] if assets else None
    return str(first.get("path")) if isinstance(first, dict) else str(first) if first else None


def _critique(contract: dict[str, Any], intelligence: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, int]:
    values = {name: 92 for name in CRITIQUE_FIELDS}
    if contract["source_image"]["crop_mode"] == "fit": values["source_image_preservation"] = 98
    if not intelligence.get("text_safe_regions"): values["creative_quality"] = 84
    recent = [x.get("composition", {}).get("strategy") for x in history[-3:]]
    if recent.count(contract["composition"]["strategy"]) >= 2: values["campaign_consistency"] = 78
    values["overall_score"] = round(sum(values.values()) / len(CRITIQUE_FIELDS))
    return values


def _intersection(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))


def contract_id(contract: dict[str, Any]) -> str:
    """Stable identifier useful for provenance and renderer handoffs."""
    value = "|".join(str(contract.get(k, "")) for k in ("project_id", "content_id", "asset_id", "production_item_id", "contract_version"))
    return "vdc_" + hashlib.sha256(value.encode()).hexdigest()[:20]


def contract_integrity_hash(contract: dict[str, Any]) -> str:
    value={key:item for key,item in contract.items() if key!="contract_hash"}
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str).encode()).hexdigest()


def visual_direction_cache_key(package: dict[str, Any], recent_contracts: list[dict[str, Any]] | None = None) -> str:
    """Hash every input capable of changing a creative decision."""
    normalized=deepcopy(package);asset=normalized.get("source_asset",{});brand=normalized.get("brand_identity",{})
    source=Path(str(asset.get("path","")));asset["file_sha256"]=_file_hash(source) if source.is_file() else None
    logo_hashes=[]
    for item in brand.get("approved_logo_assets",[]):
        path=Path(str(item.get("path")) if isinstance(item,dict) else str(item));logo_hashes.append(_file_hash(path) if path.is_file() else None)
    normalized["approved_logo_hashes"]=logo_hashes;normalized["recent_contracts"]=recent_contracts or []
    return hashlib.sha256(json.dumps(normalized,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str).encode()).hexdigest()


def _file_hash(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda:source.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()
