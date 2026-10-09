from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.publishing.meta import ExternalUrlMediaHost, MetaAdapterError, MetaHttpClient, MetaInstagramAdapter, _normalize_meta_error, meta_status
from src.execution.stages import select_stages


class FakeGraph:
    def __init__(self)->None:self.calls=[];self.children=0
    def __call__(self,method,path,params):
        self.calls.append((method,path,dict(params)))
        if path=="debug_token":return {"data":{"is_valid":True}}
        if path=="me/permissions":return {"data":[{"permission":x,"status":"granted"} for x in ("instagram_basic","instagram_content_publish","pages_show_list","pages_read_engagement")]}
        if path=="page-1":return {"id":"page-1","name":"Domus Page","instagram_business_account":{"id":"ig-1","username":"domus"}}
        if path=="ig-1/media":
            if params.get("media_type")=="CAROUSEL":return {"id":"parent-1"}
            self.children+=1;return {"id":f"child-{self.children}"}
        if path=="ig-1/media_publish":return {"id":"media-1"}
        if path=="media-1":return {"id":"media-1","media_type":"CAROUSEL","permalink":"https://instagram.example/p/1","timestamp":"2026-01-01T00:00:00+0000"}
        if path.startswith("child-") or path=="parent-1":return {"status_code":"FINISHED"}
        raise AssertionError((method,path,params))


class MetaAdapterTests(unittest.TestCase):
    def setUp(self)->None:
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/"input/publishing").mkdir(parents=True)
        self.config={"schema_version":"1.0.0","enabled":True,"allow_immediate_publish":True,"media_hosting_mode":"external_url","api_version":"v23.0","http_timeout_seconds":2,"container_poll_attempts":2,"container_poll_interval_seconds":0,"append_hashtags_to_caption":True,"publish_single_image":True,"publish_carousel":True,"publish_story":False,"publish_video":False}
        (self.root/"input/publishing/meta-config.json").write_text(json.dumps(self.config));self.graph=FakeGraph();self.client=MetaHttpClient("secret-token","v23.0",transport=self.graph);self.host=ExternalUrlMediaHost(verifier=lambda url:{"accessible":True,"content_type":"image/png","authentication_required":False})
        self.env=patch.dict(os.environ,{"META_ACCESS_TOKEN":"secret-token","META_APP_ID":"app-1","META_APP_SECRET":"app-secret","META_FACEBOOK_PAGE_ID":"page-1","META_INSTAGRAM_ACCOUNT_ID":""},clear=False);self.env.start();self.adapter=MetaInstagramAdapter(self.root,client=self.client,media_host=self.host,sleep=lambda _:None)
    def tearDown(self)->None:self.env.stop();self.temp.cleanup()

    def test_credentials_and_account_discovery_store_no_secret(self)->None:
        status=self.adapter.validate_credentials();self.assertEqual(status["status"],"ready");self.assertEqual(status["instagram_account_id"],"ig-1");self.assertTrue(status["token_valid"]);serialized=(self.root/"output/publishing/meta-account-status.json").read_text();self.assertNotIn("secret-token",serialized);self.assertNotIn("app-secret",serialized)

    def test_read_only_credential_validation_persists_nothing(self)->None:
        status=self.adapter.validate_credentials(persist=False);self.assertEqual(status["status"],"ready")
        self.assertFalse((self.root/"output/publishing/meta-account-status.json").exists());self.assertFalse((self.root/"output/publishing/meta-permission-cache.json").exists())

    def instagram_adapter(self,transport,*,enabled=True):
        self.config["enabled"]=enabled;(self.root/"input/publishing/meta-config.json").write_text(json.dumps(self.config))
        environment={"META_ACCESS_TOKEN":"secret-token","META_APP_ID":"app-1","META_APP_SECRET":"app-secret","META_FACEBOOK_PAGE_ID":"","META_INSTAGRAM_ACCOUNT_ID":"ig-direct"}
        context=patch.dict(os.environ,environment,clear=False);context.start();self.addCleanup(context.stop)
        return MetaInstagramAdapter(self.root,client=MetaHttpClient("secret-token","v23.0",transport=transport,authentication_mode="instagram_login"),media_host=self.host,sleep=lambda _:None)

    def test_instagram_login_validates_direct_account_without_page_discovery_or_writes(self)->None:
        calls=[]
        def direct(method,path,params):
            calls.append((method,path,params))
            if path=="ig-direct":return {"id":"ig-direct","username":"direct_account"}
            if path=="ig-direct/content_publishing_limit":return {"data":[{"config":{"quota_total":100},"quota_usage":0}]}
            raise AssertionError(path)
        adapter=self.instagram_adapter(direct);status=adapter.validate_credentials()
        self.assertEqual(status["status"],"ready");self.assertEqual(status["authentication_mode"],"instagram_login");self.assertEqual(status["instagram_account_id"],"ig-direct");self.assertTrue(status["token_valid"]);self.assertTrue(status["account_match"])
        self.assertNotIn("me/accounts",[path for _,path,_ in calls]);self.assertNotIn("me/permissions",[path for _,path,_ in calls]);self.assertTrue(all(method=="GET" for method,_,_ in calls))

    def test_authentication_modes_select_distinct_graph_hosts(self)->None:
        instagram=MetaHttpClient("token","v23.0",authentication_mode="instagram_login");facebook=MetaHttpClient("token","v23.0",authentication_mode="facebook_login")
        self.assertEqual(instagram.base_url,"https://graph.instagram.com");self.assertEqual(facebook.base_url,"https://graph.facebook.com")

    def test_instagram_capability_validation_never_selects_facebook_host(self)->None:
        calls=[]
        def direct(method,path,params):
            if path=="ig-direct":return {"id":"ig-direct"}
            return {"data":{"is_valid":True,"scopes":["instagram_business_basic","instagram_business_content_publish"]}}
        adapter=self.instagram_adapter(direct);original=adapter.client.request
        def recording(method,path,params=None,**kwargs):calls.append((path,kwargs.get("host_mode")));return original(method,path,params,**kwargs)
        adapter.client.request=recording;self.assertEqual(adapter.validate_credentials()["status"],"ready");self.assertIn(("ig-direct/content_publishing_limit","instagram_login"),calls);self.assertFalse(any(path=="debug_token" for path,_ in calls));self.assertFalse(any(mode=="facebook_login" for _,mode in calls))

    def test_instagram_login_preserves_configured_id_when_token_is_invalid(self)->None:
        def invalid(method,path,params):raise MetaAdapterError("Invalid OAuth access token","authentication",code=190)
        status=self.instagram_adapter(invalid).validate_credentials();self.assertEqual(status["instagram_account_id"],"ig-direct");self.assertTrue(bool(status["instagram_account_id"]));self.assertFalse(status["token_valid"])

    def test_instagram_login_detects_account_mismatch(self)->None:
        def mismatch(method,path,params):return {"id":"different-account","username":"wrong"}
        status=self.instagram_adapter(mismatch).validate_credentials();self.assertEqual(status["status"],"account_mismatch");self.assertFalse(status["account_match"]);self.assertEqual(status["instagram_account_id"],"ig-direct")

    def test_instagram_login_matches_public_user_id_when_object_id_is_app_scoped(self)->None:
        def scoped(method,path,params):
            if path=="ig-direct":return {"id":"app-scoped-id","user_id":"ig-direct","username":"direct_account"}
            return {"data":{"is_valid":True,"scopes":["instagram_business_basic","instagram_business_content_publish"]}}
        status=self.instagram_adapter(scoped).validate_credentials();self.assertEqual(status["status"],"ready");self.assertTrue(status["account_match"])

    def test_instagram_login_reports_missing_publish_permission(self)->None:
        def missing(method,path,params):
            if path=="ig-direct":return {"id":"ig-direct","username":"direct_account"}
            raise MetaAdapterError("Application does not have permission for this action","permissions",code=10)
        status=self.instagram_adapter(missing).validate_credentials();self.assertEqual(status["status"],"permissions");self.assertTrue(status["token_valid"]);self.assertIn("instagram_business_content_publish",status["missing_permissions"])

    def test_adapter_enabled_is_independent_from_valid_credentials(self)->None:
        def direct(method,path,params):
            if path=="ig-direct":return {"id":"ig-direct","username":"direct_account"}
            return {"data":{"is_valid":True,"scopes":["instagram_business_basic","instagram_business_content_publish"]}}
        status=meta_status(self.root,adapter=self.instagram_adapter(direct,enabled=False));self.assertTrue(status["instagram"]["credentials_valid"]);self.assertFalse(status["adapter_enabled"]);self.assertFalse(status["instagram"]["publishing_ready"]);self.assertFalse(status["facebook"]["publishing_ready"])

    def test_transient_permission_failure_uses_matching_success_cache(self)->None:
        adapter=self.instagram_adapter(lambda method,path,params: {"id":"ig-direct","username":"direct"} if path=="ig-direct" else {"data":{"is_valid":True,"scopes":["instagram_business_basic","instagram_business_content_publish"]}});self.assertEqual(adapter.validate_credentials()["status"],"ready")
        def transient(method,path,params):
            if path=="ig-direct":return {"id":"ig-direct","username":"direct"}
            raise MetaAdapterError("temporary","transient_platform",retryable=True)
        cached=self.instagram_adapter(transient).validate_credentials();self.assertEqual(cached["status"],"ready");self.assertEqual(cached["permission_validation"]["status"],"validated_cached");self.assertEqual(cached["permission_validation"]["last_error_classification"],"transient_platform")

    def test_permission_cache_invalidates_when_token_changes(self)->None:
        adapter=self.instagram_adapter(lambda method,path,params: {"id":"ig-direct"} if path=="ig-direct" else {"data":{"is_valid":True,"scopes":["instagram_business_basic","instagram_business_content_publish"]}});self.assertEqual(adapter.validate_credentials()["status"],"ready")
        with patch.dict(os.environ,{"META_ACCESS_TOKEN":"different-token","META_FACEBOOK_PAGE_ID":"","META_INSTAGRAM_ACCOUNT_ID":"ig-direct"},clear=False):
            def transient(method,path,params):
                if path=="ig-direct":return {"id":"ig-direct"}
                raise MetaAdapterError("temporary","transient_platform",retryable=True)
            status=MetaInstagramAdapter(self.root,client=MetaHttpClient("different-token","v23.0",transport=transient,authentication_mode="instagram_login"),media_host=self.host).validate_credentials();self.assertEqual(status["status"],"transient_platform");self.assertTrue(status["token_valid"]);self.assertTrue(status["account_match"])

    def test_carousel_preserves_order_builds_parent_publishes_and_checks_remote_status(self)->None:
        self.adapter.account={"facebook_page_id":"page-1","instagram_account_id":"ig-1"};package={"package_id":"pkg","package_type":"carousel","master_caption":{"full_caption":"Caption"},"hashtags":[{"hashtag":"#DomusErbil"}],"slides":[{"slide_number":1,"image_path":"one.png","public_media_url":"https://cdn.example/one.png","alt_text":"First slide","provenance_id":"p1"},{"slide_number":2,"image_path":"two.png","public_media_url":"https://cdn.example/two.png","alt_text":"Second slide","provenance_id":"p2"}]};item={"queue_item_id":"q1","idempotency_key":"key","package_hash":"hash","package_id":"pkg","attempt_count":0};payload=self.adapter.prepare_payload(package,item);self.assertEqual([x["slide_number"] for x in payload["media"]],[1,2]);receipt=self.adapter.publish(payload,item);self.assertEqual(receipt["child_container_ids"],["child-1","child-2"]);self.assertEqual(receipt["parent_container_id"],"parent-1");self.assertEqual(receipt["published_media_id"],"media-1");self.assertFalse(receipt["dry_run"]);self.assertEqual(receipt["remote_status"]["status"],"published");parent=next(x for x in self.graph.calls if x[1]=="ig-1/media" and x[2].get("media_type")=="CAROUSEL");self.assertEqual(parent[2]["children"],"child-1,child-2")

    def test_story_uses_stories_container_and_requires_remote_confirmation(self)->None:
        self.adapter.account={"instagram_account_id":"ig-1"};payload={"package_type":"story","media":[{"image_url":"https://cdn.example/story.png","provenance_id":"p1"}],"caption":""}
        item={"queue_item_id":"story-q","idempotency_key":"story-key","package_id":"story-package","project_id":"A","surface":"story","format":"story_sequence","attempt_count":0,"image_hashes":["story-hash"]}
        receipt=self.adapter.publish(payload,item);self.assertEqual(receipt["published_story_media_ids"],["media-1"]);self.assertEqual(receipt["remote_status"]["status"],"published")
        creation=next(call for call in self.graph.calls if call[0]=="POST" and call[1]=="ig-1/media");self.assertEqual(creation[2]["media_type"],"STORIES")

    def test_missing_or_inaccessible_public_url_blocks_before_graph_request(self)->None:
        package={"package_id":"pkg","package_type":"single_post","caption":{"full_caption":"Caption"},"hashtags":[],"image":{"image_path":"C:\\local.png"},"branded_item_id":"b","alt_text":"Alt"};item={"idempotency_key":"key","package_hash":"hash"}
        before=len(self.graph.calls)
        with self.assertRaises(MetaAdapterError) as raised:self.adapter.prepare_payload(package,item)
        self.assertEqual(raised.exception.code,"blocked_missing_public_media_url");self.assertEqual(len(self.graph.calls),before)
        bad=MetaInstagramAdapter(self.root,client=self.client,media_host=ExternalUrlMediaHost(verifier=lambda _: {"accessible":False}),sleep=lambda _:None);package["image"]["public_media_url"]="https://cdn.example/missing.png"
        with self.assertRaises(MetaAdapterError) as inaccessible:bad.prepare_payload(package,item)
        self.assertEqual(inaccessible.exception.classification,"media_unreachable")

    def test_error_normalization_distinguishes_retryable_and_permanent(self)->None:
        rate=_normalize_meta_error({"code":4,"message":"Application request limit reached"});self.assertEqual(rate.classification,"rate_limit");self.assertTrue(rate.retryable)
        token=_normalize_meta_error({"code":190,"message":"Invalid OAuth access token"});self.assertEqual(token.classification,"authentication");self.assertFalse(token.retryable)
        permission=_normalize_meta_error({"code":200,"message":"Permissions error"});self.assertEqual(permission.classification,"permissions");self.assertFalse(permission.retryable)
        self.assertNotIn("meta-platform-adapter",select_stages(from_stage="publishing-queue").requested)

    def test_parent_transient_failure_preserves_created_children_for_retry(self)->None:
        calls=[]
        def failing(method,path,params):
            calls.append((path,dict(params)))
            if path=="ig-1/media" and not params.get("media_type"):return {"id":f"child-{sum(1 for p,_ in calls if p=='ig-1/media')}"}
            if path.startswith("child-"):return {"status_code":"FINISHED"}
            if path=="ig-1/media":raise MetaAdapterError("temporary parent failure","transient_platform",retryable=True)
            raise AssertionError(path)
        adapter=MetaInstagramAdapter(self.root,client=MetaHttpClient("secret-token","v23.0",transport=failing),media_host=self.host,sleep=lambda _:None);adapter.account={"facebook_page_id":"page-1","instagram_account_id":"ig-1"};payload={"package_type":"carousel","media":[{"image_url":"https://cdn.example/1.png"},{"image_url":"https://cdn.example/2.png"}],"caption":"Caption"};item={"idempotency_key":"key","package_id":"pkg","queue_item_id":"q","attempt_count":0}
        with self.assertRaises(MetaAdapterError) as raised:adapter.publish(payload,item)
        self.assertTrue(raised.exception.retryable);self.assertEqual(raised.exception.safe_details["child_container_ids"],["child-1","child-2"])

    def test_media_publish_without_remote_confirmation_is_uncertain(self)->None:
        def unknown(method,path,params):
            if method=="POST" and path=="ig-1/media":return {"id":"container-1"}
            if method=="GET" and path=="container-1":return {"status_code":"FINISHED"}
            if method=="POST" and path=="ig-1/media_publish":return {"id":"media-1"}
            if method=="GET" and path=="media-1":return {}
            raise AssertionError((method,path))
        adapter=MetaInstagramAdapter(self.root,client=MetaHttpClient("secret-token","v23.0",transport=unknown),media_host=self.host,sleep=lambda _:None);adapter.account={"instagram_account_id":"ig-1"}
        payload={"package_type":"single_post","media":[{"image_url":"https://cdn.example/1.png"}],"caption":"Caption"};item={"idempotency_key":"key","package_id":"pkg","queue_item_id":"q","attempt_count":0}
        with self.assertRaises(MetaAdapterError) as raised:adapter.publish(payload,item)
        self.assertEqual(raised.exception.classification,"uncertain_remote_state");self.assertEqual(raised.exception.safe_details["published_media_id"],"media-1");self.assertTrue(raised.exception.safe_details["request_submitted"])

    def test_remote_confirmation_transport_failure_is_uncertain(self)->None:
        def unavailable(method,path,params):
            if method=="POST" and path=="ig-1/media":return {"id":"container-1"}
            if method=="GET" and path=="container-1":return {"status_code":"FINISHED"}
            if method=="POST" and path=="ig-1/media_publish":return {"id":"media-1"}
            raise MetaAdapterError("offline","network",retryable=True)
        adapter=MetaInstagramAdapter(self.root,client=MetaHttpClient("secret-token","v23.0",transport=unavailable),media_host=self.host,sleep=lambda _:None);adapter.account={"instagram_account_id":"ig-1"}
        with self.assertRaises(MetaAdapterError) as raised:adapter.publish({"package_type":"single_post","media":[{"image_url":"https://cdn.example/1.png"}],"caption":"Caption"},{"idempotency_key":"key","package_id":"pkg","queue_item_id":"q","attempt_count":0})
        self.assertEqual(raised.exception.safe_details["published_media_id"],"media-1");self.assertTrue(raised.exception.safe_details["request_submitted"])


if __name__=="__main__":unittest.main()
