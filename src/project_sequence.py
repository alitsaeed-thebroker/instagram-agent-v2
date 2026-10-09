"""Project overview first, site plan second; receipt-backed prerequisites."""
from datetime import datetime,timezone
VERSION="project-sequence-v1"
def role(category):
    c=str(category or "").strip().casefold().replace(" ","_")
    if c in {"introduction","project_overview","project_introduction","overview"}:return "project_overview"
    if c in {"masterplan","site_plan","project_site_plan","project_sitemap","sitemap","siteplan"}:return "project_site_plan"
    if c in {"unit_layout","villa_layout","apartment_layout","office_layout","unit_plan","unit_types","unit_layouts","floorplan","floor_plan"}:return "unit_layouts"
    if c in {"community","lifestyle","amenity","amenities","community_lifestyle"}:return "community_lifestyle"
    return "other"
def rank(category):return {"project_overview":1,"project_site_plan":2,"community_lifestyle":3,"unit_layouts":4}.get(role(category),5)
def contract(category):
    r=role(category)
    return {"version":VERSION,"role":r,"preferred_order":rank(category),"required_predecessors":[] if r=="project_overview" else ["project_overview"] if r=="project_site_plan" else ["project_overview","project_site_plan"]}
def platform_family(value):return "facebook" if "facebook" in str(value).casefold() else "instagram"
def sequence_error(item,receipts):
    sequence=item.get("project_sequence")
    if sequence is None:return None  # Legacy pure policy inputs; execution requires a bound contract.
    if not isinstance(sequence,dict) or sequence!=contract(sequence.get("role")):return "Invalid project sequence contract"
    history=sorted([r for r in receipts if r.get("project_id")==item.get("project_id") and platform_family(r.get("platform"))==platform_family(item.get("platform")) and (r.get("status") in {"published","published_with_warnings"} or r.get("state")=="CONFIRMED_PUBLISHED")],key=lambda r:datetime.fromisoformat(str(r.get("published_at") or r.get("publication_timestamp") or "1970-01-01T00:00:00+00:00").replace("Z","+00:00")).astimezone(timezone.utc))
    scope=item.get("campaign_scope")
    if scope:
        if not isinstance(scope,dict) or scope.get("project_id")!=item.get("project_id") or not scope.get("campaign_id") or scope.get("authorization")!="start new campaign":return "Invalid campaign scope"
        excluded=set(scope.get("legacy_publication_identities",[]))
        history=[r for r in history if r.get("publication_identity") not in excluded]
        if any(r.get("campaign_scope") and r["campaign_scope"].get("campaign_id")!=scope["campaign_id"] for r in history):return "Unresolved publication from another campaign"
    proven=[(r.get("project_sequence") or {}).get("role") for r in history]
    if history and any(not r.get("project_sequence") for r in history):return "Historical publications require verified sequence classification before continuing"
    if sequence["role"]=="project_overview" and history:return "Project overview must be the first publication"
    if sequence["role"]=="project_site_plan" and proven!=["project_overview"]:return "Project site plan must be the second publication, after the confirmed overview"
    required=sequence["required_predecessors"]
    if required and proven[:len(required)]!=required:return "Waiting for confirmed project overview and project site plan in order"
    return None

def campaign_scope(root,project):
    import json
    from pathlib import Path
    paths=list((Path(root)/"input/campaigns").glob("*.json"))
    configs=[json.loads(p.read_text(encoding="utf-8")) for p in paths]
    configs=[c for c in configs if c.get("project_id")==project and c.get("status") in {"PREPARING","ACTIVE"} and c.get("authorization")=="start new campaign"]
    if len(configs)>1:raise ValueError("Multiple active project campaigns require review")
    if not configs:return None
    c=configs[0]
    return {"campaign_id":c["campaign_id"],"project_id":project,"authorization":c["authorization"],"legacy_publication_identities":[x["publication_identity"] for x in c.get("prior_publications",[])]}
