"""Explicit, environment-backed Meta/Instagram publishing adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .foundation import PlatformAdapter, PublishingFoundation, _adapter_eligibility, _append_history, _atomic_json, _dedupe, _json_hash, _lock, _now, _read, _slides, _stable, final_publish_errors
from .media_hosting import file_sha256, manifest_path
from .eligibility import select_next_eligible_publication
from .ledger import PublicationLedger, record_from_receipt

logger=logging.getLogger(__name__)
AUTHENTICATION_INSTAGRAM_LOGIN="instagram_login"
AUTHENTICATION_FACEBOOK_LOGIN="facebook_login"
AUTHENTICATION_NOT_CONFIGURED="not_configured"
DEFAULT_REQUIRED_INSTAGRAM_LOGIN_PERMISSIONS={"instagram_business_basic","instagram_business_content_publish"}
DEFAULT_REQUIRED_FACEBOOK_LOGIN_PERMISSIONS={"instagram_basic","instagram_content_publish","pages_show_list","pages_read_engagement"}
SUCCESS_RECEIPT_STATUSES={"published","published_with_warnings"}


class MetaAdapterError(RuntimeError):
    def __init__(self,message:str,classification:str="unknown",*,code:str|int|None=None,retryable:bool=False,safe_details:dict[str,Any]|None=None)->None:
        super().__init__(message);self.classification,self.code,self.retryable,self.safe_details=classification,code,retryable,safe_details or {}
    def as_dict(self)->dict[str,Any]:return {"classification":self.classification,"safe_error_code":self.code,"safe_error_message":str(self),"retryable":self.retryable,**self.safe_details}


class MetaHttpClient:
    """Secret-safe Meta transport with an explicit API host; injectable in tests."""
    HOSTS={AUTHENTICATION_FACEBOOK_LOGIN:"https://graph.facebook.com",AUTHENTICATION_INSTAGRAM_LOGIN:"https://graph.instagram.com"}
    def __init__(self,token:str,api_version:str,timeout:float=30,transport:Callable[...,dict[str,Any]]|None=None,*,authentication_mode:str=AUTHENTICATION_FACEBOOK_LOGIN,audit:Callable[[str,str,bool,dict[str,Any]|None],None]|None=None)->None:
        self._token=token;self.api_version=api_version.strip("/");self.timeout=timeout;self._transport=transport;self.authentication_mode=authentication_mode;self.base_url=self.HOSTS.get(authentication_mode,"");self.audit=audit
    def request(self,method:str,path:str,params:dict[str,Any]|None=None,*,use_token:bool=True,host_mode:str|None=None)->dict[str,Any]:
        values={k:v for k,v in (params or {}).items() if v is not None};
        if use_token:values["access_token"]=self._token
        if self._transport:
            try:
                result=self._transport(method,path,values)
                if method.upper()=="POST" and self.audit:self.audit(method,path,True,result)
                return result
            except MetaAdapterError:
                if method.upper()=="POST" and self.audit:self.audit(method,path,False,None)
                raise
            except Exception as error:
                if method.upper()=="POST" and self.audit:self.audit(method,path,False,None)
                raise MetaAdapterError("Injected Meta transport failed","uncertain_remote_state" if method.upper()=="POST" else "transient_platform",retryable=method.upper()!="POST",safe_details={"request_submitted":method.upper()=="POST"}) from error
        base_url=self.HOSTS.get(host_mode) if host_mode else self.base_url
        if not base_url:raise MetaAdapterError("Meta authentication mode is not configured","configuration",retryable=False)
        url=f"{base_url}/{self.api_version}/{path.lstrip('/')}";body=None
        if method.upper()=="GET":url+=("?"+urlencode(values,doseq=True)) if values else ""
        else:body=urlencode(values,doseq=True).encode()
        request=Request(url,data=body,method=method.upper(),headers={"Accept":"application/json","Content-Type":"application/x-www-form-urlencoded"})
        try:
            with urlopen(request,timeout=self.timeout) as response:payload=json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:payload=json.loads(error.read().decode("utf-8"));meta=payload.get("error",{})
            except Exception:meta={}
            if method.upper()=="POST" and self.audit:self.audit(method,path,False,None)
            raise _normalize_meta_error(meta,error.code) from error
        except (URLError,TimeoutError,OSError) as error:
            if method.upper()=="POST" and self.audit:self.audit(method,path,False,None)
            raise MetaAdapterError("Meta transport outcome is uncertain" if method.upper()=="POST" else "Meta transport temporarily unavailable","uncertain_remote_state" if method.upper()=="POST" else "transient_platform",retryable=method.upper()!="POST",safe_details={"request_submitted":method.upper()=="POST"}) from error
        if not isinstance(payload,dict):raise MetaAdapterError("Meta returned an invalid response","transient_platform",retryable=True)
        if payload.get("error"):raise _normalize_meta_error(payload["error"])
        if method.upper()=="POST" and self.audit:self.audit(method,path,True,payload)
        return payload


class MediaHost:
    def prepare_media(self,local_path:Path,public_url:str|None)->str:raise NotImplementedError
    def get_public_url(self)->str:raise NotImplementedError
    def verify_accessibility(self,url:str)->dict[str,Any]:raise NotImplementedError
    def cleanup_if_needed(self)->None:return None


class ExternalUrlMediaHost(MediaHost):
    def __init__(self,verifier:Callable[[str],dict[str,Any]]|None=None,timeout:float=15)->None:self._url="";self.verifier=verifier;self.timeout=timeout
    def prepare_media(self,local_path:Path,public_url:str|None)->str:
        if not public_url or urlparse(public_url).scheme.casefold()!="https" or not urlparse(public_url).netloc:raise MetaAdapterError("A public HTTPS media URL is required; local paths are not reachable by Meta","media_unreachable",retryable=False,code="blocked_missing_public_media_url")
        result=self.verify_accessibility(public_url)
        if not result.get("accessible") or result.get("authentication_required"):raise MetaAdapterError("Public media URL is inaccessible or requires authentication","media_unreachable",retryable=False)
        content_type=str(result.get("content_type","")).casefold()
        if content_type and not content_type.startswith("image/"):raise MetaAdapterError("Public media URL is not an image","invalid_media",retryable=False)
        if result.get("sha256") and local_path.is_file() and result["sha256"]!=_file_sha(local_path):raise MetaAdapterError("Public media content does not match the expected local image hash","invalid_media",retryable=False)
        self._url=public_url;return public_url
    def get_public_url(self)->str:return self._url
    def verify_accessibility(self,url:str)->dict[str,Any]:
        if self.verifier:return self.verifier(url)
        request=Request(url,method="HEAD",headers={"User-Agent":"DomusPublishingPreflight/1.0"})
        try:
            with urlopen(request,timeout=self.timeout) as response:return {"accessible":200<=response.status<400,"content_type":response.headers.get("Content-Type"),"authentication_required":False}
        except HTTPError as error:return {"accessible":False,"status":error.code,"authentication_required":error.code in {401,403}}
        except (URLError,TimeoutError,OSError):return {"accessible":False,"authentication_required":False}


class MetaInstagramAdapter(PlatformAdapter):
    adapter_name="meta-instagram";platform="Instagram";supports_single_image=True;supports_carousel=True;supports_story=True;supports_alt_text=False;supports_scheduling=False;max_caption_length=2200;max_hashtags=30;supported_image_formats=("JPEG","PNG");supported_aspect_ratios=("1:1","4:5","9:16","1.91:1")
    def __init__(self,root:Path,*,client:MetaHttpClient|None=None,media_host:MediaHost|None=None,sleep:Callable[[float],None]=time.sleep)->None:
        try:
            from dotenv import load_dotenv
            load_dotenv(root/".env")
        except ImportError:pass
        self.root=root;self.config_path=root/"input"/"publishing"/"meta-config.json";self.config=_read(self.config_path);self.env={name:os.getenv(name,"") for name in ("META_ACCESS_TOKEN","META_APP_ID","META_APP_SECRET","META_FACEBOOK_PAGE_ID","META_INSTAGRAM_ACCOUNT_ID")};self.client=client or MetaHttpClient(self.env["META_ACCESS_TOKEN"],self.config["api_version"],float(self.config.get("http_timeout_seconds",30)),authentication_mode=self.authentication_mode);self.media_host=media_host or ExternalUrlMediaHost(timeout=float(self.config.get("http_timeout_seconds",30)));self.sleep=sleep;self.account:dict[str,Any]={}
    @property
    def authentication_mode(self)->str:
        if self.env.get("META_FACEBOOK_PAGE_ID"):return AUTHENTICATION_FACEBOOK_LOGIN
        if self.env.get("META_INSTAGRAM_ACCOUNT_ID"):return AUTHENTICATION_INSTAGRAM_LOGIN
        return AUTHENTICATION_NOT_CONFIGURED
    def _required_permissions(self)->set[str]:
        key="required_instagram_login_permissions" if self.authentication_mode==AUTHENTICATION_INSTAGRAM_LOGIN else "required_facebook_login_permissions"
        defaults=DEFAULT_REQUIRED_INSTAGRAM_LOGIN_PERMISSIONS if self.authentication_mode==AUTHENTICATION_INSTAGRAM_LOGIN else DEFAULT_REQUIRED_FACEBOOK_LOGIN_PERMISSIONS
        return {str(value) for value in self.config.get(key,sorted(defaults))}
    def _permission_cache_key(self)->dict[str,Any]:
        return {"token_fingerprint":hashlib.sha256(self.env["META_ACCESS_TOKEN"].encode()).hexdigest(),"account_id":self.env.get("META_INSTAGRAM_ACCOUNT_ID",""),"required_permissions":sorted(self._required_permissions()),"api_version":self.config["api_version"]}
    def _read_permission_cache(self)->dict[str,Any]|None:
        path=self.root/"output"/"publishing"/"meta-permission-cache.json"
        if not path.is_file():return None
        cache=_read(path);expected=self._permission_cache_key()
        if any(cache.get(key)!=value for key,value in expected.items()):return None
        try:validated=datetime.fromisoformat(cache["validated_at"]);ttl=float(self.config.get("permission_validation_cache_ttl_seconds",900))
        except (KeyError,TypeError,ValueError):return None
        if datetime.now(timezone.utc)-validated>timedelta(seconds=ttl):return None
        return cache
    def _write_permission_cache(self,permissions:set[str],*,persist:bool=True)->dict[str,Any]:
        now=_now();cache={**self._permission_cache_key(),"validated_permissions":sorted(permissions),"validated_at":now,"expires_at":(datetime.now(timezone.utc)+timedelta(seconds=float(self.config.get("permission_validation_cache_ttl_seconds",900)))).isoformat()}
        if persist:_atomic_json(self.root/"output"/"publishing"/"meta-permission-cache.json",cache)
        return cache
    def _permission_diagnostic(self,status:str,required:set[str],granted:set[str],*,last_success_at:str|None=None,last_error_classification:str|None=None)->dict[str,Any]:
        instagram=self.authentication_mode==AUTHENTICATION_INSTAGRAM_LOGIN
        return {"status":status,"authentication_mode":self.authentication_mode,"api_host":"graph.instagram.com" if instagram else "graph.facebook.com","validation_method":"capability_confirmation:account_access+content_publishing_limit" if instagram else "facebook_permissions_edge","endpoint":"GET /{instagram_account_id} and GET /{instagram_account_id}/content_publishing_limit" if instagram else "GET /me/permissions","required_permissions":sorted(required),"granted_permissions":sorted(granted),"missing_permissions":sorted(required-granted),"last_success_at":last_success_at,"last_error_classification":last_error_classification}
    @property
    def capabilities(self)->dict[str,Any]:return {"supports_single_image":True,"supports_carousel":True,"supports_story":True,"supports_video":False,"supports_alt_text":False,"supports_external_schedule":False}
    def validate_credentials(self,*,persist:bool=True)->dict[str,Any]:
        warnings=[]
        if self.authentication_mode==AUTHENTICATION_NOT_CONFIGURED:return self._account_status("missing_credentials",False,[],["META_INSTAGRAM_ACCOUNT_ID or META_FACEBOOK_PAGE_ID is not configured"])
        if not self.env["META_ACCESS_TOKEN"]:return self._account_status("missing_credentials",False,[],["META_ACCESS_TOKEN is not configured"])
        try:
            token_valid=False
            permission_validation=self._permission_diagnostic("not_validated",self._required_permissions(),set())
            if self.authentication_mode==AUTHENTICATION_FACEBOOK_LOGIN and self.env["META_APP_ID"] and self.env["META_APP_SECRET"]:
                debug=self.client.request("GET","debug_token",{"input_token":self.env["META_ACCESS_TOKEN"],"access_token":f"{self.env['META_APP_ID']}|{self.env['META_APP_SECRET']}"},use_token=False).get("data",{});token_valid=bool(debug.get("is_valid"));
                if not token_valid:raise MetaAdapterError("Meta access token is invalid or expired","authentication",retryable=False)
            page_id=self.env["META_FACEBOOK_PAGE_ID"];page_name="";ig_id=self.env["META_INSTAGRAM_ACCOUNT_ID"];username=""
            if self.authentication_mode==AUTHENTICATION_INSTAGRAM_LOGIN:
                account=self.client.request("GET",ig_id,{"fields":"id,user_id,username"});returned_ids={str(value) for value in (account.get("id"),account.get("user_id")) if value}
                if ig_id not in returned_ids:raise MetaAdapterError("Configured Instagram account does not match the token-accessible account","account_mismatch",retryable=False,safe_details={"account_match":False})
                username=str(account.get("username") or "");token_valid=True;account_match=True
                permissions={"instagram_business_basic"}
                try:
                    self.client.request("GET",f"{ig_id}/content_publishing_limit",{"fields":"config,quota_usage"},host_mode=AUTHENTICATION_INSTAGRAM_LOGIN)
                    permissions.add("instagram_business_content_publish");cache=self._write_permission_cache(permissions,persist=persist);permission_validation=self._permission_diagnostic("validated",self._required_permissions(),permissions,last_success_at=cache["validated_at"])
                except MetaAdapterError as lookup_error:
                    cache=self._read_permission_cache() if lookup_error.retryable else None
                    if not cache:
                        if lookup_error.classification=="permissions":raise MetaAdapterError("Instagram content publishing capability is not granted","permissions",code=lookup_error.code,retryable=False,safe_details={"missing_permissions":["instagram_business_content_publish"],"permissions_validated":True}) from lookup_error
                        raise
                    permissions=set(cache["validated_permissions"]);permission_validation=self._permission_diagnostic("validated_cached",self._required_permissions(),permissions,last_success_at=cache["validated_at"],last_error_classification=lookup_error.classification);warnings.append("Using cached permission validation after a transient Meta error")
                if not permissions:raise MetaAdapterError("Instagram token permissions could not be validated","permissions",retryable=False,safe_details={"permissions_validated":False})
            elif page_id:
                permissions_payload=self.client.request("GET","me/permissions");token_valid=True;permissions={x.get("permission") for x in permissions_payload.get("data",[]) if x.get("status")=="granted"}
                page=self.client.request("GET",page_id,{"fields":"id,name,instagram_business_account{id,username}"});page_name=page.get("name","");ig=page.get("instagram_business_account") or {};ig_id=ig_id or str(ig.get("id","") or "");username=str(ig.get("username","") or "")
                token_valid=True
            missing=sorted(self._required_permissions()-permissions)
            if missing:raise MetaAdapterError("Required Meta publishing permissions are missing","permissions",retryable=False,safe_details={"missing_permissions":missing,"permissions_validated":True})
            if self.authentication_mode==AUTHENTICATION_FACEBOOK_LOGIN and not page_id:raise MetaAdapterError("Facebook Page connection is missing","configuration",retryable=False)
            if not ig_id:raise MetaAdapterError("No Instagram professional account is connected","configuration",retryable=False)
            self.account={"facebook_page_id":page_id,"facebook_page_name":page_name,"instagram_account_id":ig_id,"instagram_username":username,"permissions":sorted(permissions),"token_valid":token_valid,"account_match":True,"permission_validation":permission_validation};status=self._account_status("ready",True,sorted(permissions),warnings);status.update(self.account)
            if persist:self._write_account(status)
            return status
        except MetaAdapterError as error:
            granted=set(locals().get("permissions",[]));diagnostic=locals().get("permission_validation") or self._permission_diagnostic("failed",self._required_permissions(),granted);diagnostic={**diagnostic,"status":"failed" if diagnostic.get("status")=="not_validated" else diagnostic.get("status"),"last_error_classification":error.classification};status=self._account_status(error.classification,bool(locals().get("token_valid",False)),sorted(granted),[str(error)]);status["account_match"]=locals().get("account_match");status["permission_validation"]=diagnostic;status.update(error.safe_details)
            if persist:self._write_account(status)
            return status
    def _account_status(self,status:str,valid:bool,permissions:list[str],warnings:list[str])->dict[str,Any]:return {"status":status,"authentication_mode":self.authentication_mode,"facebook_page_id":self.env.get("META_FACEBOOK_PAGE_ID",""),"facebook_page_name":"","instagram_account_id":self.env.get("META_INSTAGRAM_ACCOUNT_ID",""),"instagram_username":"","permissions":permissions,"missing_permissions":[],"permission_validation":self._permission_diagnostic("not_validated",self._required_permissions(),set(permissions)),"token_valid":valid,"credentials_valid":valid and status=="ready","account_match":None,"warnings":warnings,"checked_at":_now()}
    def _write_account(self,value:dict[str,Any])->None:_atomic_json(self.root/"output"/"publishing"/"meta-account-status.json",value)
    def validate_package(self,package:dict[str,Any])->list[str]:
        kind=package.get("package_type");errors=[]
        if kind not in {"single_post","carousel","story"}:errors.append(f"unsupported package type: {kind}")
        if kind=="single_post" and not self.config.get("publish_single_image"):errors.append("single-image publishing disabled")
        if kind=="carousel" and not self.config.get("publish_carousel"):errors.append("carousel publishing disabled")
        if kind=="story" and (not self.config.get("publish_story") or len(_slides(package))!=1):errors.append("Story publishing disabled or V1 Story does not contain exactly one image")
        return errors
    def prepare_payload(self,package:dict[str,Any],item:dict[str,Any])->dict[str,Any]:
        slides=_slides(package);media=[]
        for slide in slides:
            public_url=slide.get("public_media_url") or package.get("public_media_urls",{}).get(slide.get("branded_item_id"))
            if self.config.get("media_hosting_mode")=="cloudflare_r2": public_url=self._r2_url(package,item,slide)
            url=self.media_host.prepare_media(Path(str(slide.get("image_path",""))),public_url);media.append({"slide_number":slide.get("slide_number"),"image_url":url,"alt_text":slide.get("alt_text"),"provenance_id":slide.get("provenance_id")})
        caption=(package.get("master_caption") or package.get("caption") or {}).get("full_caption","")
        if self.config.get("append_hashtags_to_caption",True):
            tags=" ".join(x.get("hashtag","") for x in package.get("hashtags",[]));caption=(caption+"\n\n"+tags).strip()
        return {"platform":"Instagram","package_id":package.get("package_id"),"package_type":package.get("package_type"),"media":media,"caption":caption,"idempotency_key":item["idempotency_key"],"package_hash":item["package_hash"],"api_version":self.config["api_version"],"scheduled_at_utc":item.get("scheduled_at_utc"),"alt_text_preserved":True,"alt_text_sent":False}
    def _r2_url(self,package:dict[str,Any],item:dict[str,Any],slide:dict[str,Any])->str:
        path=manifest_path(self.root,str(item.get("project_id") or package.get("project_id") or ""))
        if not path.is_file():raise MetaAdapterError("Cloudflare R2 hosted media manifest is missing","media_unreachable",code="blocked_media_hosting")
        manifest=_read(path);local=Path(str(slide.get("image_path","")));branded=slide.get("branded_item_id") or slide.get("provenance_id") or local.stem
        try:sha=file_sha256(local)
        except OSError as error:raise MetaAdapterError("Local branded media is missing","media_unreachable",code="blocked_media_hosting") from error
        record=next((x for x in manifest.get("records",[]) if x.get("package_id")==package.get("package_id") and x.get("branded_item_id")==branded and x.get("release_id")==package.get("release_id") and x.get("local_sha256")==sha and x.get("verified_accessible") and str(x.get("public_url","")).startswith("https://")),None)
        if not record:raise MetaAdapterError("Current package has no valid Cloudflare R2 hosted-media mapping","media_unreachable",code="blocked_media_hosting")
        return str(record["public_url"])
    def publish(self,payload:dict[str,Any],item:dict[str,Any],partial:dict[str,Any]|None=None)->dict[str,Any]:
        ig_id=self.account["instagram_account_id"];child_ids=list((partial or {}).get("child_container_ids",[]));parent_id=(partial or {}).get("parent_container_id")
        story_media_ids=[]
        if payload["package_type"]=="story":
            for media in payload["media"]:
                try:created=self._write(f"{ig_id}/media",{"image_url":media["image_url"],"media_type":"STORIES"});container_id=str(created.get("id","") or "");parent_id=container_id;self._wait_ready(container_id);published=self._write(f"{ig_id}/media_publish",{"creation_id":container_id});media_id=str(published.get("id","") or "")
                except MetaAdapterError as error:error.safe_details.update(parent_container_id=parent_id,published_media_ids=story_media_ids,published_media_id=story_media_ids[-1] if story_media_ids else None,request_submitted=True);raise
                if not media_id:raise MetaAdapterError("Meta did not return a Story media ID","uncertain_remote_state",retryable=False,safe_details={"parent_container_id":parent_id,"published_media_ids":story_media_ids,"request_submitted":True})
                remote=self._confirm_remote(media_id,{"parent_container_id":parent_id,"published_media_ids":[*story_media_ids,media_id]})
                story_media_ids.append(media_id)
            media_id=story_media_ids[-1]
        elif payload["package_type"]=="carousel":
            for media in payload["media"][len(child_ids):]:
                child=self._write(f"{ig_id}/media",{"image_url":media["image_url"],"is_carousel_item":"true"});child_id=str(child.get("id","") or "")
                if not child_id:raise MetaAdapterError("Meta did not return a child container ID","transient_platform",retryable=True,safe_details={"child_container_ids":child_ids})
                child_ids.append(child_id)
                try:self._wait_ready(child_id)
                except MetaAdapterError as error:error.safe_details.update(child_container_ids=child_ids,parent_container_id=parent_id);raise
            if not parent_id:
                try:parent=self._write(f"{ig_id}/media",{"media_type":"CAROUSEL","children":",".join(child_ids),"caption":payload["caption"]})
                except MetaAdapterError as error:error.safe_details.update(child_container_ids=child_ids,parent_container_id=None);raise
                parent_id=str(parent.get("id","") or "")
            try:self._wait_ready(parent_id)
            except MetaAdapterError as error:error.safe_details.update(child_container_ids=child_ids,parent_container_id=parent_id);raise
            container_id=parent_id
        else:
            params={"image_url":payload["media"][0]["image_url"]}
            params["caption"]=payload["caption"]
            created=self._write(f"{ig_id}/media",params);container_id=str(created.get("id","") or "");parent_id=container_id
            try:self._wait_ready(container_id)
            except MetaAdapterError as error:error.safe_details.update(parent_container_id=parent_id);raise
        if payload["package_type"]!="story":
            try:published=self._write(f"{ig_id}/media_publish",{"creation_id":container_id})
            except MetaAdapterError as error:error.safe_details.update(child_container_ids=child_ids,parent_container_id=parent_id,request_submitted=True);raise
            media_id=str(published.get("id","") or "")
            if not media_id:raise MetaAdapterError("Meta did not return a published media ID","uncertain_remote_state",retryable=False,safe_details={"child_container_ids":child_ids,"parent_container_id":parent_id,"request_submitted":True})
        if payload["package_type"]!="story":remote=self._confirm_remote(media_id,{"child_container_ids":child_ids,"parent_container_id":parent_id})
        warnings=[] if self.supports_alt_text else ["Per-image alt text is preserved in the manifest but is not sent by this adapter capability."]
        return {"receipt_id":_stable("meta-receipt",item["idempotency_key"],media_id),"queue_item_id":item["queue_item_id"],"adapter":"meta-instagram","dry_run":False,"status":"published_with_warnings" if warnings else "published","platform":"Instagram","surface":item.get("surface"),"format":item.get("format") or payload["package_type"],"semantic_creative_identity":item.get("semantic_creative_identity"),"media_hashes":list(item.get("image_hashes",[])),"package_id":item["package_id"],"project_id":item.get("project_id"),"production_contract_version":item.get("production_contract_version"),"publication_identity":item.get("publication_identity") or item["idempotency_key"],"idempotency_key":item["idempotency_key"],"payload_hash":_json_hash(payload),"source_asset_order":[x.get("provenance_id") for x in payload["media"]],"facebook_page_id":self.account.get("facebook_page_id"),"instagram_account_id":ig_id,"child_container_ids":child_ids,"parent_container_id":parent_id,"published_media_id":media_id,"published_story_media_ids":story_media_ids,"published_at":_now(),"attempt_number":item.get("attempt_count",0)+1,"api_version":self.config["api_version"],"remote_status":remote,"warnings":warnings,"errors":[]}
    def _write(self,path:str,params:dict[str,Any])->dict[str,Any]:
        checkpoint=getattr(self,"checkpoint",None)
        role="publish" if path.endswith("/media_publish") else "child" if params.get("is_carousel_item") else "parent"
        details={"role":role,"container_id":params.get("creation_id")}
        if checkpoint:checkpoint("before_write",details)
        result=self.client.request("POST",path,params)
        if checkpoint:checkpoint("after_write",{**details,"remote_id":result.get("id"),"success":True})
        return result

    def get_container_status(self,container_id:str)->dict[str,Any]:
        value=self.client.request("GET",str(container_id),{"fields":"id,status_code,status"})
        if str(value.get("id",""))!=str(container_id):return {"status":"unknown"}
        # FINISHED means ready, never published. Errors/expiry are not proof of absence.
        published=str(value.get("status_code","")).upper()=="PUBLISHED"
        return {"status":"published" if published else "unknown","container_id":container_id,
                "status_code":value.get("status_code"),"checked_at":_now()}

    def _wait_ready(self,container_id:str)->None:
        attempts=int(self.config.get("container_poll_attempts",10));interval=float(self.config.get("container_poll_interval_seconds",3))
        for number in range(attempts):
            status=self.client.request("GET",container_id,{"fields":"status_code,status"});code=str(status.get("status_code","")).casefold()
            if code in {"finished","published"}:return
            if code in {"error","expired"}:raise MetaAdapterError("Meta media container failed processing","invalid_media",retryable=False,code=code)
            if number+1<attempts:self.sleep(interval)
        raise MetaAdapterError("Meta media container processing timed out","transient_platform",retryable=True,code="container_timeout")
    def _confirm_remote(self,media_id:str,details:dict[str,Any])->dict[str,Any]:
        evidence={**details,"published_media_id":media_id,"request_submitted":True}
        try:remote=self.get_status({"published_media_id":media_id})
        except MetaAdapterError as error:
            error.safe_details.update(evidence);raise
        if remote.get("status")!="published":
            raise MetaAdapterError("Meta publication could not be remotely confirmed","uncertain_remote_state",retryable=False,safe_details=evidence)
        return remote
    def get_status(self,receipt:dict[str,Any])->dict[str,Any]:
        media_id=receipt.get("published_media_id")
        if not media_id:return {"status":"unknown"}
        value=self.client.request("GET",str(media_id),{"fields":"id,media_type,permalink,timestamp"});return {"status":"published" if str(value.get("id", ""))==str(media_id) else "unknown","media_type":value.get("media_type"),"permalink":value.get("permalink"),"timestamp":value.get("timestamp"),"checked_at":_now()}
    def normalize_error(self,error:Exception)->dict[str,Any]:return error.as_dict() if isinstance(error,MetaAdapterError) else {"classification":"unknown","safe_error_code":None,"safe_error_message":str(error),"retryable":False}
    def publish_project(self,foundation:PublishingFoundation)->Path:
        with _lock(self.root/"state/publishing/.account-publish.lock"), _lock(foundation.lock_path):return self._publish_project_locked(foundation)
    def _publish_project_locked(self,foundation:PublishingFoundation)->Path:
        if not self.config.get("enabled"):self._write_account(self.validate_credentials())
        if not foundation.manifest_path.is_file():raise ValueError("Canonical publication history is missing; real publishing fails closed")
        queue=_read(foundation.queue_path);preflight={x["queue_item_id"]:x for x in _read(foundation.preflight_path).get("items",[])};ctx=foundation._inputs();packages={x["package_id"]:x for x in ctx["packages"].get("packages",[])};manifest=_read(foundation.manifest_path);receipts=manifest.get("real_receipts",[]);ledger=PublicationLedger(self.root);ledger._validate();queue=ledger.reconcile_queue(queue);ledger_receipts=[{**x,"status":"published","published_at":x.get("publication_timestamp"),"published_media_id":x.get("remote_media_id")} for x in ledger.records() if x["state"]=="CONFIRMED_PUBLISHED"];successful={x.get("publication_identity") or x.get("idempotency_key"):x for x in ledger_receipts};history=manifest.get("publication_history",[])
        if manifest.get("project_id")!=foundation.project or not isinstance(receipts,list):raise ValueError("Canonical publication history is invalid; real publishing fails closed")
        selection=select_next_eligible_publication(queue,ledger_receipts,now=datetime.now(timezone.utc),config=foundation._config());_atomic_json(foundation.directory/f"{foundation.project}-eligibility.json",selection);selected=selection.get("selected_queue_item_id")
        if not selected:return foundation.manifest_path
        for item in queue.get("items",[]):
            if item.get("queue_item_id")!=selected:continue
            eligible,reason=_adapter_eligibility(item,preflight.get(item["queue_item_id"],{}),successful)
            if not eligible:item["adapter_skipped"]=True;item["skip_reason"]=reason;continue
            identity=item.get("publication_identity") or item["idempotency_key"]
            if identity in successful:history=_append_history(history,item,"real_publication_already_recorded",self.adapter_name,successful[identity]["receipt_id"],successful[identity]["payload_hash"]);continue
            ledger_state=ledger.get(identity)
            if ledger_state: item["status"]="published" if ledger_state["state"]=="CONFIRMED_PUBLISHED" else "publishing_uncertain";_atomic_json(foundation.queue_path,queue);continue
            package=packages[item["package_id"]];errors=self.validate_package(package);now=datetime.now(timezone.utc)
            errors.extend(final_publish_errors(item,package,ctx))
            if item.get("scheduled_at_utc") and datetime.fromisoformat(item["scheduled_at_utc"])>now:item["status"]="scheduled";continue
            blockers=list(errors)
            if not self.config.get("enabled"):blockers.append("Meta adapter is disabled in meta-config.json")
            if not item.get("scheduled_at_utc") and not self.config.get("allow_immediate_publish",False):blockers.append("Immediate real publishing is disabled and no due schedule exists")
            if self.config.get("media_hosting_mode")!="cloudflare_r2" and any(not (x.get("public_media_url") or package.get("public_media_urls",{}).get(x.get("branded_item_id"))) for x in _slides(package)):blockers.append("blocked_missing_public_media_url: every image requires a public HTTPS URL")
            if blockers:
                item["status"]="blocked";item["errors"].extend({"classification":"validation","message":x,"at":_now()} for x in blockers if not any(isinstance(y,dict) and y.get("message")==x for y in item["errors"]));history=_append_history(history,item,"blocked",self.adapter_name,None,None,"; ".join(blockers));continue
            account=self.validate_credentials()
            if account.get("status")!="ready":error=MetaAdapterError("Meta account or permissions are not ready","authentication",retryable=False);self._record_failure(item,error);history=_append_history(history,item,"failed",self.adapter_name,None,None,str(error));continue
            try:payload=self.prepare_payload(package,item)
            except MetaAdapterError as error:
                self._record_failure(item,error);item["status"]="blocked" if not error.retryable else item["status"];history=_append_history(history,item,"blocked" if not error.retryable else "failed",self.adapter_name,None,None,str(error));continue
            payload_path=foundation.directory/"meta-payloads"/foundation.project/f"{item['queue_item_id']}.json";_atomic_json(payload_path,{**payload,"media":[{**x,"image_url":x["image_url"]} for x in payload["media"]]})
            partial=None  # Only durable account-bound checkpoints are recovery authority.
            current_errors=final_publish_errors(item,package,foundation._inputs())
            if current_errors:raise ValueError("Final publication gate failed: "+"; ".join(current_errors))
            item["reserved_at"]=_now();item["attempt_token"]=_stable("attempt",item["queue_item_id"],item["attempt_count"]+1,_now())
            ledger.reserve(item,payload,str(account.get("instagram_account_id") or ""),foundation._config())
            previous_checkpoint=getattr(self,"checkpoint",None)
            self.checkpoint=lambda event,details:ledger.checkpoint(identity,item["attempt_token"],event,details)
            item["status"]="publishing";_atomic_json(foundation.queue_path,queue)
            try:receipt=self.publish(payload,item,partial);receipt["caption_hash"]=item.get("caption_hash");receipt["attempt_token"]=item.get("attempt_token");ledger_record=ledger.record(record_from_receipt(receipt));receipt["ledger_record_id"]=ledger_record["ledger_record_id"];receipts.append(receipt);item["status"]=receipt["status"];item["attempt_count"]+=1;history=_append_history(history,item,receipt["status"],self.adapter_name,receipt["receipt_id"],receipt["payload_hash"]);manifest.update(real_receipts=_dedupe(receipts,"receipt_id"),publication_history=_dedupe(history,"history_id"),updated_at=_now());_atomic_json(foundation.manifest_path,manifest);_atomic_json(foundation.queue_path,queue)
            except MetaAdapterError as error:
                remote_started=bool(error.safe_details.get("request_submitted") or error.safe_details.get("child_container_ids") or error.safe_details.get("parent_container_id"));self._record_failure(item,error);item["status"]="publishing_uncertain" if remote_started else item["status"];
                ledger.capture_failure(item,error.safe_details);item["status"]="publishing_uncertain"
                entry=_append_history(history,item,item["status"],self.adapter_name,None,_json_hash(payload),str(error))[-1];entry["remote_state"]={"child_container_ids":error.safe_details.get("child_container_ids",[]),"parent_container_id":error.safe_details.get("parent_container_id"),"request_submitted":remote_started};history.append(entry);manifest.update(real_receipts=_dedupe(receipts,"receipt_id"),publication_history=_dedupe(history,"history_id"),updated_at=_now());_atomic_json(foundation.manifest_path,manifest);_atomic_json(foundation.queue_path,queue)
            finally:self.checkpoint=previous_checkpoint
            break  # At most one real publication transaction per worker run.
        manifest.update(real_receipts=_dedupe(receipts,"receipt_id"),publication_history=_dedupe(history,"history_id"),updated_at=_now());_atomic_json(foundation.manifest_path,manifest);_atomic_json(foundation.queue_path,queue);return foundation.manifest_path
    def _record_failure(self,item:dict[str,Any],error:MetaAdapterError)->None:
        item["attempt_count"]+=1;item["errors"].append({**error.as_dict(),"at":_now()});retryable=error.retryable and item["attempt_count"]<item["max_attempts"]
        if retryable:
            policy=PublishingFoundation(item["project_id"],self.root)._config()["retry_policy"];minutes=float(policy["initial_delay_minutes"])*(float(policy["backoff_multiplier"])**(item["attempt_count"]-1));item["status"]="retry_wait";item["next_retry_at"]=(datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat()
        else:item["status"]="failed";item["next_retry_at"]=None


class MetaAccountManager:
    """Report independent readiness without coupling either platform to the other."""
    def __init__(self,root:Path,instagram_adapter:MetaInstagramAdapter|None=None)->None:
        self.root=root;self.instagram_adapter=instagram_adapter or MetaInstagramAdapter(root)
    def status(self)->dict[str,Any]:
        instance=self.instagram_adapter;enabled=bool(instance.config.get("enabled"));token=bool(instance.env["META_ACCESS_TOKEN"])
        instagram=instance.validate_credentials()
        credentials_valid=instagram.get("status")=="ready";instagram_ready=enabled and credentials_valid
        page_id=instance.env.get("META_FACEBOOK_PAGE_ID");facebook_credentials_valid=credentials_valid and instance.authentication_mode==AUTHENTICATION_FACEBOOK_LOGIN;facebook_ready=enabled and facebook_credentials_valid
        facebook={"status":"ready" if facebook_credentials_valid else "not_configured" if not page_id else instagram.get("status"),"configured":bool(page_id),"authentication_mode":"facebook_login" if page_id else None,"page_id":page_id,"token_configured":token,"token_valid":instagram.get("token_valid",False) if page_id and token else False,"credentials_valid":facebook_credentials_valid,"permissions":instagram.get("permissions",[]) if page_id else [],"publishing_ready":facebook_ready}
        return {**instagram,"provider":"Meta","adapter_enabled":enabled,"token_configured":token,"media_hosting":instance.config.get("media_hosting_mode"),"ready_for_real_publishing":instagram_ready,
                "instagram":{**instagram,"configured":bool(instagram.get("instagram_account_id")),"authentication_mode":instance.authentication_mode if instance.authentication_mode!=AUTHENTICATION_NOT_CONFIGURED else None,"credentials_valid":credentials_valid,"publishing_ready":instagram_ready},"facebook":facebook,
                "combined":{"instagram_ready":instagram_ready,"facebook_ready":facebook_ready,"both_ready":instagram_ready and facebook_ready,"partial_publishing_supported":True,"status":"ready" if instagram_ready and facebook_ready else "partially_ready" if instagram_ready or facebook_ready else "not_configured"}}

def meta_status(root:Path,*,adapter:MetaInstagramAdapter|None=None)->dict[str,Any]:
    instance=adapter or MetaInstagramAdapter(root);status=MetaAccountManager(root,instance).status();instance._write_account(status);return status
def meta_health(root:Path)->dict[str,Any]:
    instance=MetaInstagramAdapter(root)
    if not instance.config.get("enabled"):return {"status":"NOT_CONFIGURED","errors":[]}
    status=meta_status(root,adapter=instance);return {"status":"PASS" if status.get("ready_for_real_publishing") else "FAIL","errors":status.get("warnings",[])}
def _normalize_meta_error(meta:dict[str,Any],http_status:int|None=None)->MetaAdapterError:
    code=meta.get("code",http_status);subcode=meta.get("error_subcode");message=str(meta.get("message") or "Meta API request failed");lower=message.casefold()
    if code in {190} or "token" in lower:classification,retryable="authentication",False
    elif code in {10,200} or "permission" in lower:classification,retryable="permissions",False
    elif code in {4,17,32,613}:classification,retryable="rate_limit",True
    elif code in {1,2,341} or (http_status and http_status>=500):classification,retryable="transient_platform",True
    elif "media" in lower or "image" in lower:classification,retryable="invalid_media",False
    elif "duplicate" in lower:classification,retryable="duplicate",False
    else:classification,retryable="permanent_platform",False
    return MetaAdapterError(message,classification,code=f"{code}:{subcode}" if subcode else code,retryable=retryable)
def _file_sha(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda:source.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()
