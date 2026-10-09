"""Exact-layout factual integrity for plan-based visual assets.

Plan assets are structured evidence, not interchangeable project imagery.  This
module deliberately fails closed when a displayed fact cannot be traced to the
exact asset used by a post.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from src.unit_plan_relationship import verify_unit_plan_relationship, relationship_errors

PLAN_TYPES=frozenset({"unit_layout","apartment_layout","office_layout","villa_layout","commercial_unit_layout","floor_plan","typical_floor_plan","master_floor_plan","technical_plan","site_plan","masterplan"})
UNIT_TYPES=frozenset({"unit_layout","apartment_layout","office_layout","villa_layout","commercial_unit_layout"})
RELATIONSHIP_STATES=frozenset({"VERIFIED","PROBABLE","AMBIGUOUS","UNVERIFIED","CONFLICTED"})
MARKETING_PLAN_STATES=frozenset({"VERIFIED"})
PLAN_COMPLETENESS_STATES=frozenset({"COMPLETE","INCOMPLETE","UNCERTAIN","NOT_APPLICABLE"})
PLAN_LEGIBILITY_STATES=frozenset({"READABLE","PARTIALLY_READABLE","UNREADABLE","UNCERTAIN","NOT_APPLICABLE"})
NON_UNIT_PLAN_TYPES=PLAN_TYPES-UNIT_TYPES
FACT_FIELDS=("unit_type","area_sqm","bedrooms","bathrooms","floor","unit_number","building","tower","context","orientation","balcony","terrace","commercial_residential_classification","dimensions")
_ALIASES={"floorplan":"floor_plan","unit_plan":"unit_layout","technical_drawing":"technical_plan","full_project_site_plan":"site_plan"}
_AREA=re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:m²|m2|sqm|sq\.?\s*m)\b",re.I)
_BED=re.compile(r"\b(\d+)\s*[- ]?bed(?:room)?s?\b",re.I)
_BATH=re.compile(r"\b(\d+)\s*[- ]?bath(?:room)?s?\b",re.I)
_TYPE=re.compile(r"\btype\s+([A-Z0-9-]+)\b",re.I)
_UNIT_NUMBER=re.compile(r"\bunit\s*(?:(?:no\.?|number)\s*[:#-]?|[#:-])\s*([A-Z0-9][A-Z0-9-]{0,15})\b",re.I)
_DIMENSION=re.compile(r"\b(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:m|metres?|meters?)?\b",re.I)

def normalize_plan_type(value:Any, *, subtype:Any="", subject:Any="", confidence:float=1.0)->tuple[str,str]:
    kind=_ALIASES.get(str(value or "").strip().casefold().replace(" ","_"),str(value or "").strip().casefold().replace(" ","_"))
    text=" ".join((str(subtype or ""),str(subject or ""))).casefold()
    if kind=="floor_plan":
        if any(token in text for token in ("unit","apartment","office","villa","typical","master")):return "floor_plan","REVIEW_REQUIRED"
    return kind,("CLASSIFIED" if kind in PLAN_TYPES else "NOT_PLAN")

def make_plan_record(asset:dict[str,Any])->dict[str,Any]|None:
    raw_confidence=asset.get("confidence")
    classification_confidence=(
        float(raw_confidence or 0)
        if isinstance(raw_confidence,(int,float,str)) and not isinstance(raw_confidence,dict)
        else float(asset.get("classification_confidence") or 0)
    )
    kind,status=normalize_plan_type(
        asset.get("asset_type") or asset.get("visual_category"),
        subtype=asset.get("asset_subtype"),
        subject=asset.get("dominant_subject"),
        confidence=classification_confidence,
    )
    if kind not in PLAN_TYPES:return None
    supplied=asset.get("unit_identity") if isinstance(asset.get("unit_identity"),dict) else {}
    evidence=asset.get("evidence") if isinstance(asset.get("evidence"),dict) else {}
    confidence=(
        asset.get("relationship_confidence")
        if isinstance(asset.get("relationship_confidence"),dict)
        else asset.get("confidence") if isinstance(asset.get("confidence"),dict) else {}
    )
    identity={field:_clean(supplied.get(field)) for field in FACT_FIELDS}
    state=str(asset.get("relationship_status") or asset.get("verification_status") or "UNVERIFIED").upper()
    if state not in RELATIONSHIP_STATES:state="UNVERIFIED"

    project_id=_clean(asset.get("project_id"))
    source_document=_clean(asset.get("source_document"))
    source_page=asset.get("source_page")
    source_path=_clean(asset.get("source_path"))
    source_hash=_clean(asset.get("source_hash") or asset.get("sha256"))
    source_document_hash=_clean(asset.get("source_document_hash") or asset.get("source_document_sha256"))
    asset_id=_clean(asset.get("asset_id"))
    protected_regions=asset.get("protected_regions")
    if not isinstance(protected_regions,list):
        protected_regions=(asset.get("preservation") or {}).get("protected_regions",[])
    if not isinstance(protected_regions,list):protected_regions=[]

    has_identity=any(value is not None for value in identity.values())
    completeness=_plan_state(asset.get("plan_completeness_status"),PLAN_COMPLETENESS_STATES,"UNCERTAIN")
    legibility=_plan_state(asset.get("plan_legibility_status"),PLAN_LEGIBILITY_STATES,"UNCERTAIN")
    if asset.get("source_kind")=="pdf_embedded_image" and not asset.get("contains_entire_page"):
        completeness="INCOMPLETE"

    canonical_input = {**asset, "asset_type": kind, "source_hash": source_hash,
                       "source_document_hash": source_document_hash}
    relationship = verify_unit_plan_relationship(canonical_input)
    canonical_errors = list(relationship["reasons"])
    if asset.get("unit_plan_relationship") is not None:
        if asset["unit_plan_relationship"] != relationship:
            canonical_errors.append("canonical relationship changed or was altered")
        if asset.get("evidence") != relationship["evidence"]:
            canonical_errors.append("canonical field evidence changed or was altered")
    if relationship["status"] == "VERIFIED" and not canonical_errors:
        identity = {field: relationship["unit_identity"].get(field) for field in FACT_FIELDS}
        evidence = relationship["evidence"]
        has_identity = True
        state = "VERIFIED"
    else:
        state = state if state in {"AMBIGUOUS", "CONFLICTED", "PROBABLE"} else "UNVERIFIED"

    # VERIFIED is a cryptographic/evidentiary trust state, not a classifier
    # confidence label. Every asserted unit fact must point back to this exact
    # asset/source page/hash and project.
    unsupported=[]
    mismatched=[]
    for field,value in identity.items():
        if value is None:continue
        items=_evidence_items(evidence.get(field))
        if not items:
            unsupported.append(field);continue
        if not any(_evidence_matches_asset(
            item,
            project_id=project_id,
            source_document=source_document,
            source_page=source_page,
            source_hash=source_hash,
            asset_id=asset_id,
        ) for item in items):
            mismatched.append(field)
    review_reasons=list(canonical_errors)
    if unsupported:review_reasons.append("unit facts without exact evidence: "+", ".join(unsupported))
    if mismatched:review_reasons.append("unit facts linked to a different source: "+", ".join(mismatched))
    if not has_identity:review_reasons.append("no source-visible unit identity was verified")
    if completeness!="COMPLETE":review_reasons.append(f"plan completeness is {completeness}")
    if legibility!="READABLE":review_reasons.append(f"plan legibility is {legibility}")
    if not all((project_id,source_document,source_page is not None,source_hash,asset_id)):
        review_reasons.append("exact project/document/page/hash/asset provenance is incomplete")
    if (review_reasons or unsupported or mismatched) and state=="VERIFIED":
        state="UNVERIFIED"

    # A floor/site/master/technical plan can never become an individual unit
    # identity source merely because unit-looking labels were extracted from it.
    if kind not in UNIT_TYPES and any(value is not None for value in identity.values()):
        state="CONFLICTED"

    return {
        "asset_id":asset_id,
        "asset_type":kind,
        "classification_status":status,
        "project_id":project_id,
        "source_document":source_document,
        "source_page":source_page,
        "source_path":source_path,
        "source_hash":source_hash,
        "source_document_hash":source_document_hash,
        "source_document_path":asset.get("source_document_path"),
        "source_kind":asset.get("source_kind"),
        "contains_entire_page":asset.get("contains_entire_page"),
        "contains_complete_plan_leaf":asset.get("contains_complete_plan_leaf"),
        "source_region":asset.get("source_region"),
        "render_dpi":asset.get("render_dpi"),
        "unit_plan_relationship":relationship,
        "unit_identity":identity,
        "evidence":evidence,
        "confidence":{field:float(confidence.get(field,0) or 0) for field in FACT_FIELDS},
        "relationship_status":state,
        "verification_status":state,
        "plan_completeness_status":completeness,
        "plan_legibility_status":legibility,
        "visible_unit_numbers":list(asset.get("visible_unit_numbers") or []),
        "visible_dimension_labels":list(asset.get("visible_dimension_labels") or []),
        "review_reasons":list(dict.fromkeys(review_reasons)),
        "review_status":"CLEARED" if kind in UNIT_TYPES and status=="CLASSIFIED" and state in MARKETING_PLAN_STATES and has_identity and completeness=="COMPLETE" and legibility=="READABLE" else "REVIEW_REQUIRED",
        "marketing_eligible":bool(kind in UNIT_TYPES and status=="CLASSIFIED" and state in MARKETING_PLAN_STATES and has_identity and completeness=="COMPLETE" and legibility=="READABLE"),
        "trust_boundary":{
            "exact_asset_required":True,
            "same_project_required":True,
            "same_source_document_required":True,
            "same_source_page_required":True,
            "source_hash_required":True,
            "cross_asset_fact_join_forbidden":True,
            "cross_page_fact_join_forbidden":relationship.get("authority")!="deterministic_catalogue_villa_relationship",
            "cross_page_join_policy":"recomputed unique type section, contiguous floors, identical area tables, numbered legends",
            "non_unit_plan_as_unit_forbidden":True,
        },
        "preservation":{
            "crop_mode":"fit",
            "complete_plan_required":True,
            "protected_regions":protected_regions,
            "labels_and_dimensions_must_remain_visible":True,
            "unit_numbers_must_remain_visible":True,
        },
    }


def write_plan_inventory(project:str,root:Path,assets:list[dict[str,Any]])->Path:
    records=[record for asset in assets if (record:=make_plan_record(asset))]
    if any(record.get("project_id") not in {None,"",project} for record in records):raise ValueError("Plan inventory blocked cross-project asset")
    base=root/"output"/"source-images"/project/"plans"
    for name in ("unit-layouts","floor-plans","master-floor-plans","site-plans","technical"):(base/name).mkdir(parents=True,exist_ok=True)
    path=root/"output"/"plan-intelligence"/f"{project}-plan-intelligence.json";path.parent.mkdir(parents=True,exist_ok=True)
    payload={"project_id":project,"schema_version":"2.0.0","authority":"canonical-unit-plan-relationship","assets":records,"summary":{"plan_assets":len(records),"verified_unit_layouts":sum(x["asset_type"] in UNIT_TYPES and x["marketing_eligible"] for x in records),"review_required":sum(x["classification_status"]=="REVIEW_REQUIRED" or (x["asset_type"] in UNIT_TYPES and not x["marketing_eligible"]) for x in records)},"created_at":datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");return path

def validate_layout_claims(record:dict[str,Any],claims:dict[str,Any], *, expected_project:str, require_verified:bool=True)->list[str]:
    errors=[]
    if record.get("asset_type") in UNIT_TYPES:
        errors.extend(relationship_errors(record, expected_project=expected_project))
    if record.get("project_id")!=expected_project:errors.append("plan project mismatch")
    if record.get("asset_type") not in PLAN_TYPES:errors.append("asset is not classified as a plan")
    if record.get("classification_status")=="REVIEW_REQUIRED":errors.append("plan classification requires review")
    meaningful={field:_clean(claims.get(field)) for field in FACT_FIELDS if _clean(claims.get(field)) is not None}
    if meaningful and require_verified and record.get("relationship_status")!="VERIFIED":
        errors.append("exact layout-to-fact relationship is not VERIFIED")
    if meaningful and record.get("asset_type") not in UNIT_TYPES:
        errors.append("floor/master/site plan cannot be marketed as an individual unit layout")
    if record.get("asset_type") in UNIT_TYPES and record.get("plan_completeness_status")!="COMPLETE":
        errors.append("unit plan is incomplete or its completeness is unverified")
    if record.get("asset_type") in UNIT_TYPES and record.get("plan_legibility_status")!="READABLE":
        errors.append("unit plan labels, numbers, or dimensions are not verified as readable")

    verified=record.get("unit_identity",{})
    for field,value in meaningful.items():
        expected=_clean(verified.get(field))
        items=_evidence_items(record.get("evidence",{}).get(field))
        if expected is None:
            errors.append(f"unsupported layout claim: {field}")
        elif _comparable(value)!=_comparable(expected):
            errors.append(f"layout {field} mismatch: claimed {value}, verified {expected}")
        elif not items:
            errors.append(f"layout {field} lacks exact-asset evidence")
        elif not any(_evidence_matches_asset(
            item,
            project_id=_clean(record.get("project_id")),
            source_document=_clean(record.get("source_document")),
            source_page=record.get("source_page"),
            source_hash=_clean(record.get("source_hash")),
            asset_id=_clean(record.get("asset_id")),
        ) for item in items):
            errors.append(f"layout {field} evidence does not belong to exact asset/page")

    if meaningful and require_verified and not record.get("marketing_eligible", record.get("relationship_status")=="VERIFIED"):
        errors.append("layout is not marketing eligible")
    return list(dict.fromkeys(errors))


def claims_from_text(text:str)->dict[str,Any]:
    result={};area=_AREA.search(text or "");beds=_BED.search(text or "");baths=_BATH.search(text or "");unit=_TYPE.search(text or "");unit_number=_UNIT_NUMBER.search(text or "");dimensions=_DIMENSION.findall(text or "")
    if area:result["area_sqm"]=float(area.group(1))
    if beds:result["bedrooms"]=int(beds.group(1))
    if baths:result["bathrooms"]=int(baths.group(1))
    if unit:result["unit_type"]=f"Type {unit.group(1).upper()}"
    if unit_number:result["unit_number"]=unit_number.group(1).upper()
    if dimensions:result["dimensions"]=[f"{left} x {right} m" for left,right in dimensions]
    return result

def validate_package_layouts(package:dict[str,Any],inventory:dict[str,Any], *, expected_project:str)->list[str]:
    records={str(x.get("asset_id")):x for x in inventory.get("assets",[]) if x.get("project_id")==expected_project}
    slides=package.get("slides") or [{**package.get("image",{}),"source_asset_ids":package.get("source_asset_ids",[])}]
    caption=package.get("master_caption") or package.get("caption") or {}
    caption_text=str(caption.get("full_caption") or "")
    caption_claims=claims_from_text(caption_text)
    caption_declares_plan=any(
        token in caption_text.casefold()
        for token in ("floorplan","floor plan","unit layout","apartment layout","villa layout","office layout")
    )
    errors=[];plan_records=[]
    for slide in slides:
        ids=[str(x) for x in slide.get("source_asset_ids",[]) if x not in (None,"")]
        linked=[records.get(asset_id) for asset_id in ids if records.get(asset_id)]
        unknown=[asset_id for asset_id in ids if asset_id not in records]
        slide_text=" ".join(str(slide.get(k) or "") for k in ("headline","title","alt_text"))
        slide_claims={**caption_claims,**claims_from_text(slide_text)}
        declares_plan=caption_declares_plan or any(
            token in slide_text.casefold()
            for token in ("floorplan","floor plan","unit layout","apartment layout","villa layout","office layout")
        )
        # Plan inventory is authoritative only for plan/layout semantics. A normal
        # exterior/interior/amenity asset is expected to be absent from it.
        if unknown and (slide_claims or declares_plan):
            errors.append("package references plan asset outside verified project inventory")
        plan_records.extend(linked)
        if (slide_claims or declares_plan) and not linked:
            errors.append("layout-specific claim has no exact source plan asset")
        for record in linked:
            errors.extend(validate_layout_claims(record,slide_claims,expected_project=expected_project))

    # A partial villa floor must never stand in for the complete unit. The
    # canonical scope enumerates every mandatory printed plan leaf.
    linked_ids={str(record.get("asset_id")) for record in plan_records}
    for record in plan_records:
        scope=(record.get("unit_plan_relationship") or {}).get("catalogue_relationship") or {}
        if scope and not set(scope.get("required_plan_asset_ids", [])) <= linked_ids:
            errors.append("complete villa unit requires all canonical floor plan assets")
    scopes={(record.get("unit_plan_relationship") or {}).get("catalogue_relationship", {}).get("unit_scope_id")
            for record in plan_records}
    one_canonical_villa=bool(plan_records and None not in scopes and len(scopes)==1)
    if caption_claims and plan_records and not one_canonical_villa:
        identities={_identity_signature(x) for x in plan_records}
        if len(identities)>1:
            errors.append("carousel/layout mismatch: caption specifications do not identify one exact layout")
        asset_ids={str(x.get("asset_id")) for x in plan_records}
        if len(asset_ids)>1 and any(
            key in caption_claims for key in ("area_sqm","bedrooms","bathrooms","unit_type","unit_number")
        ):
            errors.append("master caption cannot bind one unit specification across multiple plan assets")
    return list(dict.fromkeys(errors))


def validate_plan_contract(contract:dict[str,Any])->list[str]:
    record=contract.get("plan_integrity")
    if not isinstance(record,dict):
        return ["unit plan is missing canonical integrity record"] if contract.get("source_image",{}).get("asset_type") in UNIT_TYPES else []
    errors=[];source=contract.get("source_image",{})
    display_text = " ".join(str((contract.get(name) or {}).get("text") or "")
                            for name in ("headline", "subheadline", "supporting_copy", "cta")
                            if (contract.get(name) or {}).get("visible"))
    errors.extend(validate_layout_claims(record, claims_from_text(display_text),
                                         expected_project=contract.get("project_id", record.get("project_id"))))
    if record.get("asset_type") in UNIT_TYPES or source.get("asset_type") in UNIT_TYPES:
        errors.extend(relationship_errors(record, expected_project=contract.get("project_id"),
                                         asset_id=contract.get("asset_id"), source_path=source.get("path", "")))
        if not contract.get("project_id") or not contract.get("asset_id"):
            errors.append("plan contract requires project and exact asset identity")
        if source.get("asset_type") != record.get("asset_type"):
            errors.append("plan type substitution")
        if source.get("rotation", 0) != 0 or source.get("perspective_transform") or source.get("generative_edit"):
            errors.append("technical plan geometry cannot be transformed or regenerated")
    if source.get("crop_mode")!="fit":errors.append("plan cropped: complete plan FIT is required")
    placement=source.get("placement",[]);overlay=contract.get("graphics",{}).get("overlay_geometry",[])
    if len(placement)!=4 or placement[2]<=0 or placement[3]<=0:errors.append("plan placement is incomplete")
    if len(placement)==4 and len(overlay)==4 and _rect_intersection(_xywh_to_box(placement),overlay)>0:errors.append("branding obstruction covers meaningful plan information")
    if len(placement)==4:
        scope=(record.get("unit_plan_relationship") or {}).get("catalogue_relationship") or {}
        if scope:
            region=scope.get("source_region") or []
            if len(region)!=4:
                errors.append("canonical printed plan leaf bounds are missing")
            else:
                scale=min(placement[2]/(region[2]-region[0]), placement[3]/(region[3]-region[1]))
                # The source uses 10pt room/area labels and 8pt plan numbers.
                # Superscript square-meter exponents are smaller by design.
                for row in scope.get("protected_source_rows", []):
                    for size in row.get("font_sizes", []):
                        minimum=5 if size<7 else 8
                        if size*scale<minimum:
                            errors.append("technical plan labels or dimensions become unreadable at output size")
                            break
                    if errors and errors[-1].startswith("technical plan labels"):
                        break
        for name in ("project_identity", "location", "developer_identity", "headline", "subheadline", "supporting_copy", "cta", "brand_logo"):
            element = contract.get(name) or {}
            if name != "brand_logo" and not element.get("visible"):
                continue
            if all(key in element for key in ("x", "y", "width", "height")):
                box = [element[key] for key in ("x", "y", "width", "height")]
                if _rect_intersection(_xywh_to_box(placement), _xywh_to_box(box)) > 0:
                    errors.append(f"{name} obscures protected plan geometry or labels")
        canvas = contract.get("canvas") or {}
        if canvas and (placement[0] < 0 or placement[1] < 0 or placement[0]+placement[2] > canvas.get("width", 0) or placement[1]+placement[3] > canvas.get("height", 0)):
            errors.append("complete plan placement extends outside canvas")
    if not record.get("preservation",{}).get("complete_plan_required"):errors.append("plan completeness protection is missing")
    if record.get("asset_type") in UNIT_TYPES and not record.get("marketing_eligible"):
        errors.append("unit plan is not eligible for production: exact identity, completeness, legibility, and evidence are required")
    if record.get("asset_type") in UNIT_TYPES and record.get("plan_completeness_status")!="COMPLETE":errors.append("unit plan completeness is not verified")
    if record.get("asset_type") in UNIT_TYPES and record.get("plan_legibility_status")!="READABLE":errors.append("unit plan labels and dimensions are not verified as readable")
    return errors

def _evidence_matches_asset(
    item:Any,
    *,
    project_id:Any,
    source_document:Any,
    source_page:Any,
    source_hash:Any,
    asset_id:Any,
)->bool:
    if not isinstance(item,dict):return False
    item_project=_clean(item.get("source_project") or item.get("project_id"))
    item_doc=_clean(item.get("source_document") or item.get("source_file"))
    page=item.get("source_page",item.get("page"))
    item_hash=_clean(item.get("source_hash") or item.get("source_sha256"))
    item_asset=_clean(item.get("asset_id") or item.get("source_asset_id"))
    if not all((item_project,item_doc,page is not None,item_hash,item_asset,project_id,source_document,source_page is not None,source_hash,asset_id)):
        return False
    return all((
        _comparable(item_project)==_comparable(project_id),
        _comparable(item_doc)==_comparable(source_document),
        _comparable(page)==_comparable(source_page),
        _comparable(item_hash)==_comparable(source_hash),
        _comparable(item_asset)==_comparable(asset_id),
    ))


def _identity_signature(record:dict[str,Any])->str:
    identity={
        key:_clean(value)
        for key,value in (record.get("unit_identity") or {}).items()
        if _clean(value) is not None
    }
    return json.dumps(identity,sort_keys=True,default=str)


def _clean(value:Any)->Any:
    if value in (None,"","UNKNOWN","UNVERIFIED"):return None
    return value.strip() if isinstance(value,str) else value
def _plan_state(value:Any,allowed:frozenset[str],default:str)->str:
    normalized=str(value or "").strip().upper()
    return normalized if normalized in allowed else default
def _comparable(value:Any)->str:
    if isinstance(value,(int,float)):return f"{float(value):g}"
    return re.sub(r"\s+"," ",str(value).strip().casefold())
def _evidence_items(value:Any)->list[Any]:return list(value) if isinstance(value,list) else []
def _xywh_to_box(value:list[Any])->list[float]:return [float(value[0]),float(value[1]),float(value[0])+float(value[2]),float(value[1])+float(value[3])]
def _rect_intersection(a:list[Any],b:list[Any])->float:return max(0,min(float(a[2]),float(b[2]))-max(float(a[0]),float(b[0])))*max(0,min(float(a[3]),float(b[3]))-max(float(a[1]),float(b[1])))
