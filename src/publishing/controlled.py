"""Explicitly selected, single-item Instagram publication workflow."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .foundation import PublishingFoundation, _atomic_json, _json_hash, _lock, _now, _read, _slides, _stable, final_publish_errors
from .media_hosting import CloudflareR2MediaHost
from .meta import ExternalUrlMediaHost, MetaAdapterError, MetaInstagramAdapter, SUCCESS_RECEIPT_STATUSES
from .ledger import PublicationLedger, record_from_receipt
from .eligibility import select_next_eligible_publication
from src.plan_integrity import validate_package_layouts

INACTIVE={"cancelled","superseded","published","published_with_warnings","publishing","publishing_uncertain"}

class ControlledPublishError(RuntimeError): pass

def _state(root:Path,project:str)->tuple[PublishingFoundation,dict[str,Any],dict[str,Any],dict[str,Any]]:
    foundation=PublishingFoundation(project,root);queue=_read(foundation.queue_path);ctx=foundation._inputs();packages={x["package_id"]:x for x in ctx["packages"].get("packages",[])}
    if not foundation.manifest_path.is_file():raise ControlledPublishError("Canonical publication history is missing; real publishing fails closed")
    try:manifest=_read(foundation.manifest_path)
    except (OSError,ValueError,json.JSONDecodeError) as error:raise ControlledPublishError("Canonical publication history is corrupt; real publishing fails closed") from error
    if manifest.get("project_id")!=project or not isinstance(manifest.get("real_receipts",[]),list):raise ControlledPublishError("Canonical publication history has invalid authority")
    return foundation,queue,packages,manifest

def list_publishable(root:Path,project:str)->list[dict[str,Any]]:
    _,queue,packages,manifest=_state(root,project);real={x.get("idempotency_key") for x in manifest.get("real_receipts",[]) if x.get("status") in SUCCESS_RECEIPT_STATUSES};rows=[]
    for item in queue.get("items",[]):
        if item.get("status") in INACTIVE:continue
        package=packages.get(item.get("package_id"),{});caption=" ".join(str((package.get("master_caption") or package.get("caption") or {}).get("full_caption","")).split());slides=_slides(package)
        rows.append({"queue_item_id":item.get("queue_item_id"),"package_id":item.get("package_id"),"platform":item.get("platform"),"package_type":package.get("package_type"),"image_count":len(slides),"status":item.get("status"),"caption_summary":caption[:77]+("..." if len(caption)>77 else ""),"real_publication_status":"published" if item.get("idempotency_key") in real else "not_published"})
    return rows

def resolve_item(queue:dict[str,Any],*,queue_item_id:str|None=None,package_id:str|None=None)->dict[str,Any]:
    if bool(queue_item_id)==bool(package_id):raise ControlledPublishError("Select exactly one queue_item_id or package_id")
    active=[x for x in queue.get("items",[]) if x.get("status") not in INACTIVE]
    matches=[x for x in active if x.get("queue_item_id")==queue_item_id] if queue_item_id else [x for x in active if x.get("package_id")==package_id]
    if not matches:raise ControlledPublishError("Selected active publication item was not found")
    if len(matches)!=1:raise ControlledPublishError("Package ID resolves to more than one active platform job; select queue_item_id")
    return matches[0]

def controlled_publish(root:Path,project:str,*,queue_item_id:str|None=None,package_id:str|None=None,confirm:bool=False,adapter:MetaInstagramAdapter|None=None,r2_host:CloudflareR2MediaHost|None=None,operational_root:Path|None=None)->dict[str,Any]:
    foundation=PublishingFoundation(project,root)
    with _lock((operational_root or root)/"state/publishing/.account-publish.lock"), _lock(foundation.lock_path):
        return _controlled_publish_locked(root,project,queue_item_id=queue_item_id,package_id=package_id,confirm=confirm,adapter=adapter,r2_host=r2_host,operational_root=operational_root)

def _controlled_publish_locked(root:Path,project:str,*,queue_item_id:str|None=None,package_id:str|None=None,confirm:bool=False,adapter:MetaInstagramAdapter|None=None,r2_host:CloudflareR2MediaHost|None=None,operational_root:Path|None=None)->dict[str,Any]:
    foundation,queue,packages,manifest=_state(root,project);item=resolve_item(queue,queue_item_id=queue_item_id,package_id=package_id);package=packages.get(item.get("package_id"))
    authority_root=operational_root or root
    if operational_root:
        live=PublishingFoundation(project,authority_root)
        if not live.manifest_path.is_file():raise ControlledPublishError("Live publication history is missing")
        manifest=_read(live.manifest_path)
        if manifest.get("project_id")!=project or not isinstance(manifest.get("real_receipts"),list):raise ControlledPublishError("Live publication history is invalid")
        from src.project_sequence import campaign_scope
        if package.get("campaign_scope")!=campaign_scope(authority_root,project):raise ControlledPublishError("Live campaign scope differs from approved package")
        manifest_path=live.manifest_path
    else:manifest_path=foundation.manifest_path
    ledger=PublicationLedger(authority_root);ledger._validate();ledger_state=ledger.get(item.get("publication_identity") or item.get("idempotency_key"))
    if ledger_state:return {"status":"already_published" if ledger_state["state"]=="CONFIRMED_PUBLISHED" else "reconciliation_required","item":item,"package":package,"receipt":ledger_state,"meta_write_requests":0}
    if not package:raise ControlledPublishError("Current package is missing")
    plan_path=foundation.output/"plan-intelligence"/f"{project}-plan-intelligence.json"
    plan_inventory=_read(plan_path) if plan_path.is_file() else {"project_id":project,"assets":[]}
    plan_errors=validate_package_layouts(package,plan_inventory,expected_project=project)
    if plan_errors:raise ControlledPublishError("Canonical plan integrity failed: " + "; ".join(plan_errors))
    errors=final_publish_errors(item,package,foundation._inputs())
    if errors:raise ControlledPublishError("Final publication gate failed: "+"; ".join(errors))
    ledger_receipts=[{**row,"status":"published","published_at":row.get("publication_timestamp")} for row in ledger.records() if row["state"]=="CONFIRMED_PUBLISHED"]
    eligibility=select_next_eligible_publication({"items":[item]},ledger_receipts,now=datetime.now(timezone.utc),config=foundation._config())
    if eligibility.get("selected_queue_item_id")!=item.get("queue_item_id"):raise ControlledPublishError("Selected item is not currently eligible under canonical Department 5 scheduling policy")
    if str(item.get("platform","")).casefold()!="instagram":raise ControlledPublishError("Controlled real publishing currently allows Instagram items only")
    if item.get("status") in {"blocked","cancelled","superseded"}:raise ControlledPublishError(f"Selected item is {item.get('status')}")
    if not item.get("idempotency_key") or item.get("package_hash")!=_json_hash(package):raise ControlledPublishError("Selected item has stale or invalid idempotency/package identity")
    existing=next((x for x in manifest.get("real_receipts",[]) if x.get("idempotency_key")==item["idempotency_key"] and x.get("status") in SUCCESS_RECEIPT_STATUSES),None)
    if existing:return {"status":"already_published","item":item,"package":package,"receipt":existing,"meta_write_requests":0}
    r2=r2_host or CloudflareR2MediaHost(root);r2_status=r2.status()
    if not r2_status.get("ready"):raise ControlledPublishError("Cloudflare R2 provider is not ready")
    instance=adapter or MetaInstagramAdapter(root,media_host=ExternalUrlMediaHost(timeout=30));account=instance.validate_credentials()
    if account.get("status")!="ready":raise ControlledPublishError("Meta credentials or required Instagram permissions are not ready")
    try:payload=instance.prepare_payload(package,item)
    except MetaAdapterError as error:raise ControlledPublishError(str(error)) from error
    preview={"project":project,"queue_item_id":item["queue_item_id"],"package_id":item["package_id"],"platform":"Instagram","package_type":package.get("package_type"),"image_count":len(payload["media"]),"caption_length":len(payload.get("caption","")),"hashtag_count":len(package.get("hashtags",[])),"hosted_media_urls_verified":len(payload["media"]),"r2_provider_ready":True,"meta_credentials_ready":True,"existing_real_receipt":False,"idempotency_key_present":True,"immediate_publish_override":"controlled-single-item","meta_write_requests":0}
    if not confirm:return {"status":"preview","preview":preview,"item":item,"package":package,"meta_write_requests":0}
    errors=final_publish_errors(item,package,foundation._inputs())
    if errors:raise ControlledPublishError("Final publication gate failed: "+"; ".join(errors))
    audit_path=authority_root/"output"/"publishing"/"live-write-audit.json"
    def audit(method:str,path:str,success:bool,response:dict[str,Any]|None)->None:
        value=_read(audit_path) if audit_path.is_file() else {"provider":"Meta","writes":[]}
        remote_id=str((response or {}).get("id","") or "")
        category="media_publish" if path.endswith("/media_publish") else "container_create" if path.endswith("/media") else "other_write"
        value["writes"].append({"endpoint_category":category,"timestamp":_now(),"queue_item_id":item["queue_item_id"],"package_id":item["package_id"],"attempt_number":item.get("attempt_count",0)+1,"success":success,"remote_id":remote_id or None});_atomic_json(audit_path,value)
    instance.client.audit=audit
    before={x["queue_item_id"]:json.dumps(x,sort_keys=True) for x in queue.get("items",[]) if x["queue_item_id"]!=item["queue_item_id"]}
    # New attempts never reuse unbound container IDs from generated history.
    partial=None
    item["reserved_at"]=_now();item["attempt_token"]=_stable("attempt",item["queue_item_id"],item["attempt_count"]+1,_now())
    ledger.reserve(item,payload,str(account.get("instagram_account_id") or ""),foundation._config())
    identity=item.get("publication_identity") or item["idempotency_key"]
    previous_checkpoint=getattr(instance,"checkpoint",None)
    instance.checkpoint=lambda event,details:ledger.checkpoint(identity,item["attempt_token"],event,details)
    item["status"]="publishing";_atomic_json(foundation.queue_path,queue)
    try:receipt=instance.publish(payload,item,partial)
    except MetaAdapterError as error:
        remote_started=bool(error.safe_details.get("request_submitted") or error.safe_details.get("child_container_ids") or error.safe_details.get("parent_container_id"));item["attempt_count"]=item.get("attempt_count",0)+1;item["status"]="publishing_uncertain" if remote_started else "retry_wait" if error.retryable else "failed";item.setdefault("errors",[]).append({**error.as_dict(),"at":_now()});
        ledger.capture_failure(item,error.safe_details);item["status"]="publishing_uncertain"
        manifest.setdefault("publication_history",[]).append({"history_id":_stable("controlled-failure",item["queue_item_id"],_now()),"queue_item_id":item["queue_item_id"],"package_id":item["package_id"],"publication_identity":item.get("publication_identity") or item.get("idempotency_key"),"status":item["status"],"adapter":"meta-instagram","timestamp":_now(),"remote_state":{"child_container_ids":error.safe_details.get("child_container_ids",[]),"parent_container_id":error.safe_details.get("parent_container_id"),"request_submitted":remote_started}});_atomic_json(manifest_path,manifest);_atomic_json(foundation.queue_path,queue);raise ControlledPublishError(str(error)) from error
    finally:instance.checkpoint=previous_checkpoint
    item["attempt_count"]=item.get("attempt_count",0)+1;item["status"]=receipt["status"];item["updated_at"]=_now();receipt["publication_identity"]=item.get("publication_identity") or item.get("idempotency_key");receipt["caption_hash"]=item.get("caption_hash");receipt["attempt_token"]=item.get("attempt_token");record=ledger.record(record_from_receipt(receipt));receipt["ledger_record_id"]=record["ledger_record_id"];manifest.setdefault("real_receipts",[]).append(receipt);manifest["updated_at"]=_now();_atomic_json(manifest_path,manifest);_atomic_json(foundation.queue_path,queue)
    if any(json.dumps(x,sort_keys=True)!=before[x["queue_item_id"]] for x in queue["items"] if x["queue_item_id"]!=item["queue_item_id"]):raise RuntimeError("Controlled publish invariant violated: another queue item changed")
    return {"status":"published","preview":preview,"receipt":receipt,"other_queue_items_modified":0,"meta_write_requests":"recorded_in_live_write_audit"}
