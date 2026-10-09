"""Purpose-specific image selection; attractive imagery is not proof of fit."""
from pathlib import Path
import hashlib,json
from src.project_sequence import role
VERSION="visual-purpose-v3"
def assess_visual_purpose(asset,purpose,project=None,allow_support=False):
    kind=str(asset.get("asset_type") or asset.get("visual_category") or "").casefold()
    required=role(purpose)
    result={"asset_id":asset.get("asset_id"),"purpose":required,"version":VERSION,"status":"MATCH","score":0,"reasons":[],"preserve_full_image":False}
    def reject(reason,status="REJECTED"):
        return {**result,"status":status,"reasons":[reason]}
    if project and asset.get("project_id")!=project:return reject("wrong project")
    if required=="project_overview":
        review=asset.get("visual_purpose_review") or {}
        if review.get("purpose")=="project_overview":
            bound=all(review.get(k)==asset.get(k) for k in ("asset_id","project_id","source_hash","source_document_hash","source_page"))
            try:bound=bound and hashlib.sha256(Path(asset["source_path"]).read_bytes()).hexdigest()==asset.get("source_hash")
            except (OSError,KeyError):bound=False
            if not bound:return reject("overview review is stale or not bound to this exact source","REVIEW_REQUIRED")
            if review.get("status")=="APPROVED" and (review.get("scope")=="whole_development" or (allow_support and review.get("scope")=="project_context")):
                return {**result,"score":100,"preserve_full_image":True,"reasons":["source-bound reviewed overview rendering"]}
        if kind in {"logo","exterior","building_exterior","villa_exterior","interior","villa_layout","unit_layout","location_map","map","architectural_detail"}:
            return reject("overview requires the whole development; logo, individual building, room or location map is insufficient")
        if kind in {"aerial_view","project_overview","masterplan","site_plan"}:
            return reject("whole-development scope needs source-bound visual review","REVIEW_REQUIRED")
        return reject("unknown overview suitability","REVIEW_REQUIRED")
    if required=="project_site_plan":
        review=asset.get("project_layout_review") or {}
        if review:
            keys=("asset_id","project_id","source_hash","source_document_hash","source_page")
            bound=all(asset.get(k) and review.get(k)==asset.get(k) for k in keys)
            try:bound=bound and hashlib.sha256(Path(asset["source_path"]).read_bytes()).hexdigest()==asset.get("source_hash")
            except (OSError,KeyError):bound=False
            if not bound:return reject("project-layout review has missing or stale provenance","REVIEW_REQUIRED")
            if kind in {"unit_layout","villa_layout","apartment_layout","floor_plan","location_map","map","interior","logo"}:
                return reject("individual unit or location imagery cannot represent the project layout")
            if review.get("status")=="APPROVED" and review.get("purpose")=="project_site_plan" and review.get("scope")=="project_layout" and review.get("representation")=="architectural_illustration":
                return {**result,"score":100,"preserve_full_image":True,"representation":"architectural_illustration","required_disclosure":"Project brochure illustration; not a measured site drawing","technical_dimensions_verified":False,"reasons":["exact-source reviewed illustrated project layout"]}
            return reject("project-layout review is incomplete","REVIEW_REQUIRED")
        if asset.get("visual_purpose_review",{}).get("purpose")=="project_overview":
            return reject("perspective overview rendering cannot substitute for a technical site plan")
        if kind not in {"site_plan","masterplan"}:return reject("site plan requires a project-wide plan, not a location map or unit layout")
        if asset.get("contains_diagram") is not True and asset.get("contains_masterplan") is not True:
            return reject("site-plan label alone does not prove a complete readable drawing","REVIEW_REQUIRED")
        if str(asset.get("plan_completeness_status","")).upper()!="COMPLETE" or str(asset.get("plan_legibility_status","")).upper()!="READABLE":
            return reject("site plan completeness or legibility unresolved","REVIEW_REQUIRED")
        return {**result,"score":100,"preserve_full_image":True}
    return result

def load_visual_reviews(root,assets):
    path=Path(root)/"input/visual-review/project-overview-reviews.json"
    reviews=json.loads(path.read_text(encoding="utf-8")).get("reviews",[]) if path.is_file() else []
    by_id={(r.get("project_id"),r["asset_id"]):r for r in reviews}
    layout_path=Path(root)/"input/visual-review/project-layout-reviews.json"
    layout_reviews=json.loads(layout_path.read_text(encoding="utf-8")).get("reviews",[]) if layout_path.is_file() else []
    layouts={(r.get("project_id"),r["asset_id"]):r for r in layout_reviews}
    assets=[{**a,**({"project_layout_review":layouts[(a.get("project_id",a.get("project")),a["asset_id"])]} if (a.get("project_id",a.get("project")),a.get("asset_id")) in layouts else {})} for a in assets]
    return [{**a,**({"visual_purpose_review":by_id[(a.get("project_id",a.get("project")),a["asset_id"])]} if (a.get("project_id",a.get("project")),a.get("asset_id")) in by_id else {})} for a in assets]

def select_purpose_assets(assets,purpose,project=None):
    decisions=[assess_visual_purpose(a,purpose,project,allow_support=role(purpose)=="project_overview") for a in assets]
    allowed={d["asset_id"]:d for d in decisions if d["status"]=="MATCH"}
    selected=sorted([a for a in assets if a.get("asset_id") in allowed],key=lambda a:(a.get("visual_purpose_review",{}).get("sequence",999),-allowed[a["asset_id"]]["score"],str(a.get("asset_id"))))
    if role(purpose)=="project_overview" and selected:
        if validate_overview_slides(selected,project):selected=[]
    return selected,decisions

def validate_overview_slides(assets,project=None):
    """Ordered exact-source evidence: whole-project cover, distinct reviewed support."""
    errors=[]
    if not assets:return ["overview has no slides"]
    ids=[a.get("asset_id") for a in assets]
    hashes=[a.get("source_hash") for a in assets]
    if len(set(ids))!=len(ids) or len(set(hashes))!=len(hashes):errors.append("duplicate overview image")
    if len(assets)>1 and any(not a.get("source_hash") or not a.get("source_document_hash") or not a.get("source_page") for a in assets):errors.append("missing overview source provenance")
    for i,a in enumerate(assets):
        d=assess_visual_purpose(a,"project_overview",project,allow_support=i>0)
        if d["status"]!="MATCH":errors.append("overview slide requires review: "+str(a.get("asset_id")))
    ranks=[a.get("visual_purpose_review",{}).get("sequence") for a in assets]
    if len(assets)>1 and (any(x is None for x in ranks) or ranks!=sorted(ranks)):errors.append("overview slide sequence is missing or out of order")
    return errors
