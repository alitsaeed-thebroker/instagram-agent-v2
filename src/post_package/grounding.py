"""Fail-closed factual claim lineage for publication copy."""
from __future__ import annotations
import hashlib, re
from typing import Any
from src.knowledge.consumer import canonical_verified_facts

GROUNDING_VERSION="1.0.0"
COMMERCIAL=re.compile(r"\b(?:price|discount|payment plan|return|yield|availability|handover|financing|guarantee)\b",re.I)
NUMERIC=re.compile(r"\b\d+(?:[.,]\d+)?(?:\s*(?:%|m(?:2|²)?|sqm|minutes?|hours?|vehicles?|bedrooms?|bathrooms?))?",re.I)
LOCATION=re.compile(r"\b(?:located|location|road|near|from (?:the )?airport|airport)\b",re.I)

def authoritative_facts(knowledge:dict[str,Any],project:str)->dict[str,dict[str,Any]]:
    """Publication grounding registry derived only from canonical Department 2."""
    result={}
    for fact in canonical_verified_facts(knowledge,project,include_commercial=True).values():
        result[fact.fact_id]={
            "fact_id":fact.fact_id,
            "path":fact.path,
            "canonical_path":fact.canonical_path,
            "value":fact.value,
            "project_id":fact.project_id,
            "category":fact.category,
            "status":"verified",
            "commercial":fact.commercial,
            "evidence":fact.evidence,
            "authority":fact.authority,
            "relationship_context":fact.relationship_context,
        }
    return result


def make_claim(text:str,category:str,fact_ids:list[str],*,factual:bool=True)->dict[str,Any]:
    return {"claim_id":"claim_"+hashlib.sha256(text.encode()).hexdigest()[:16],"claim_text":text,"category":category,"factual":factual,"supporting_fact_ids":list(dict.fromkeys(fact_ids))}

def validate_claims(caption:dict[str,Any],facts:dict[str,dict[str,Any]],project:str)->dict[str,Any]:
    claims=caption.get("claims");diagnostics=[]
    if not isinstance(claims,list):
        claims=[]
        if detects_factual_claim(str(caption.get("full_caption") or "")):diagnostics.append(_diag("unclassified",caption.get("full_caption"),"missing_fact_reference"))
    referenced=set()
    for claim in claims:
        if not claim.get("factual"):continue
        ids=list(claim.get("supporting_fact_ids") or []);referenced.update(ids);resolved=[facts[x] for x in ids if x in facts];reason=None;text=str(claim.get("claim_text") or "")
        if not ids:reason="missing_fact_reference"
        elif len(resolved)!=len(ids):reason="fact_not_authoritative"
        elif any(x.get("project_id")!=project for x in resolved):reason="fact_project_mismatch"
        elif any(x.get("status")!="verified" for x in resolved):reason="fact_stale_or_conflicted"
        elif COMMERCIAL.search(text) and not any(x.get("commercial") for x in resolved):reason="unsupported_commercial_claim"
        elif not any(_supports(text,x.get("value")) for x in resolved):reason="unsupported_numeric_claim" if NUMERIC.search(text) else "unrelated_fact_reference"
        if reason:diagnostics.append(_diag(claim.get("claim_id"),text,reason,ids,[x["fact_id"] for x in resolved],claim.get("category")))
    declared=set(caption.get("verified_fact_refs") or [])
    if declared!=referenced:diagnostics.append(_diag("caption_refs","caption verified_fact_refs","fact_reference_set_mismatch",list(declared),list(referenced)))
    factual=sum(bool(x.get("factual")) for x in claims)
    return {"version":GROUNDING_VERSION,"status":"blocked" if diagnostics else "grounded","factual_claim_count":factual,"grounded_claim_count":factual-sum(x["claim_id"] not in {"caption_refs","unclassified"} for x in diagnostics),"diagnostics":diagnostics}

def remove_unsupported_claims(caption:dict[str,Any],validation:dict[str,Any])->dict[str,Any]:
    bad={x.get("claim_id") for x in validation.get("diagnostics",[])};claims=[x for x in caption.get("claims",[]) if x.get("claim_id") not in bad];removed=[x for x in caption.get("claims",[]) if x.get("claim_id") in bad];value=dict(caption);value["claims"]=claims;value["verified_fact_refs"]=list(dict.fromkeys(y for x in claims for y in x.get("supporting_fact_ids",[])));text=str(value.get("full_caption") or "")
    for claim in removed:text=text.replace(str(claim.get("claim_text") or ""),"")
    value["full_caption"]=re.sub(r"\n{3,}","\n\n",text).strip();value["grounding_recovery"]={"attempts":1,"removed_claim_ids":[x.get("claim_id") for x in removed],"invented_facts":False};return value

def detects_factual_claim(text:str)->bool:return bool(NUMERIC.search(text) or LOCATION.search(text) or COMMERCIAL.search(text))
def resolve_path(data:Any,path:str)->Any:
    value=data
    for name,index in re.findall(r"([^.[\]]+)(?:\[(\d+)\])?",str(path)):
        if not isinstance(value,dict) or name not in value:return None
        value=value[name]
        if index:
            if not isinstance(value,list) or int(index)>=len(value):return None
            value=value[int(index)]
    return value
def _supports(claim:str,value:Any)->bool:
    text=str(value);nums=re.findall(r"\d+(?:[.,]\d+)?",claim)
    if nums:return all(x.replace(",","") in text.replace(",","") for x in nums)
    words={x for x in re.findall(r"[a-z0-9]+",text.casefold()) if len(x)>2};return bool(words and words<=set(re.findall(r"[a-z0-9]+",claim.casefold()))) or text.casefold() in claim.casefold()
def _diag(cid:Any,text:Any,reason:str,missing=None,resolved=None,category=None)->dict[str,Any]:return {"claim_id":cid,"claim_text_summary":str(text)[:160],"grounding_status":"blocked","expected_fact_category":category,"resolved_fact_ids":resolved or [],"missing_fact_ids":missing or [],"reason":reason}
def _id(project:str,path:Any,value:Any)->str:return "fact_"+hashlib.sha256(f"{project}|{path}|{value}".encode()).hexdigest()[:20]


def canonical_unit_facts(inventory:dict, project:str, source_ids:set[str])->dict:
    """Exact displayed unit facts; recompute provenance and complete floor membership."""
    from src.unit_plan_relationship import relationship_errors
    from src.plan_integrity import UNIT_TYPES
    records=[r for r in inventory.get("assets",[]) if r.get("asset_id") in source_ids and r.get("asset_type") in UNIT_TYPES]
    if not records:return {}
    if len(records)!=len(source_ids):raise ValueError("Unit caption source membership is incomplete")
    for record in records:
        errors=relationship_errors(record,expected_project=project)
        if errors or not record.get("marketing_eligible"):
            raise ValueError("Unit caption requires canonical verified relationships: "+"; ".join(errors))
    scopes=[r["unit_plan_relationship"].get("catalogue_relationship") for r in records]
    if not all(scopes):return {}  # Area basis requires a supported source adapter.
    if len({s["unit_scope_id"] for s in scopes})!=1:
        raise ValueError("Unit caption cannot combine different units")
    if source_ids!=set(scopes[0]["required_plan_asset_ids"]):
        raise ValueError("Unit caption requires the complete canonical floor set")
    identity=records[0]["unit_identity"]
    if any(r["unit_identity"][k]!=identity[k] for r in records for k in ("unit_type","bedrooms","area_sqm")):
        raise ValueError("Unit caption facts conflict")
    proof_ids=sorted(r["unit_plan_relationship"]["relationship_id"] for r in records)
    values={"unit_type":identity["unit_type"],"bedrooms":f"{identity['bedrooms']}-bedroom villa",
            "area_sqm":f"{identity['area_sqm']:g} m² built-up area"}
    result={}
    for key,value in values.items():
        fid=_id(project,"|".join(proof_ids)+"|"+key,value)
        result[fid]={"fact_id":fid,"path":"unit_relationship."+key,"value":value,
            "project_id":project,"category":"unit_plan","status":"verified","commercial":False,
            "evidence":[r["unit_plan_relationship"]["provenance"] for r in records],
            "authority":"canonical_unit_plan_relationship","relationship_ids":proof_ids}
    return result
