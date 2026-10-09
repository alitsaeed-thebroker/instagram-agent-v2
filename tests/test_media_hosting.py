import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.publishing.media_hosting import (CloudflareR2MediaHost, MediaHostingError,
    deterministic_object_key, file_sha256, run_media_hosting)


class FakeS3:
    def __init__(self): self.uploads=[];self.heads=0
    def head_bucket(self,**kwargs): self.heads+=1;return {}
    def upload_file(self,*args,**kwargs): self.uploads.append((args,kwargs))


class MediaHostingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.s3=FakeS3()
        self.env={"R2_ACCESS_KEY_ID":"access","R2_SECRET_ACCESS_KEY":"secret","R2_BUCKET_NAME":"bucket","R2_ENDPOINT_URL":"https://account.r2.cloudflarestorage.com","R2_PUBLIC_BASE_URL":"https://pub-test.r2.dev"}
        self.verify=lambda url:{"accessible":True,"content_type":"image/png"}
    def tearDown(self):self.temp.cleanup()
    def host(self):return CloudflareR2MediaHost(self.root,env=self.env,client=self.s3,verifier=self.verify)
    def test_configuration_and_read_only_status(self):
        status=self.host().status();self.assertTrue(status["ready"]);self.assertEqual(self.s3.heads,1);self.assertEqual(self.s3.uploads,[]);self.assertTrue(status["warnings"])
    def test_missing_credentials(self):
        host=CloudflareR2MediaHost(self.root,env={name:"" for name in self.env},client=None);self.assertFalse(host.configured)
        with self.assertRaises(MediaHostingError) as raised:host._s3()
        self.assertEqual(raised.exception.classification,"missing_credentials")
    def test_deterministic_safe_key(self):
        one=deterministic_object_key("A Project!","release 1","Instagram","pkg/1","item?","a"*64,".PNG")
        self.assertEqual(one,"projects/a-project/release-1/instagram/pkg-1/item-aaaaaaaaaaaaaaaa.png");self.assertEqual(one,deterministic_object_key("A Project!","release 1","Instagram","pkg/1","item?","a"*64,".PNG"))
    def test_upload_content_type_and_https_url(self):
        image=self.root/"exact.png";image.write_bytes(b"png bytes")
        record=self.host().upload(image,project_id="p",release_id="r",platform="Instagram",package_id="pkg",branded_item_id="item")
        self.assertEqual(record["local_sha256"],file_sha256(image));self.assertTrue(record["public_url"].startswith("https://"));self.assertEqual(self.s3.uploads[0][1]["ExtraArgs"],{"ContentType":"image/png"})
    def test_inaccessible_url_fails(self):
        image=self.root/"x.png";image.write_bytes(b"x");host=CloudflareR2MediaHost(self.root,env=self.env,client=self.s3,verifier=lambda _: {"accessible":False})
        with self.assertRaises(MediaHostingError) as raised:host.upload(image,project_id="p",release_id="r",platform="i",package_id="pkg",branded_item_id="item")
        self.assertEqual(raised.exception.classification,"public_url_unreachable")
    def test_stage_reuses_same_hash_and_mapping(self):
        image=self.root/"x.png";image.write_bytes(b"x");out=self.root/"output/post-packages";out.mkdir(parents=True)
        package={"packages":[{"package_id":"pkg","release_id":"r","platform":"Instagram","image":{"branded_item_id":"item","image_path":str(image)}}]}
        (out/"project-post-packages.json").write_text(json.dumps(package),encoding="utf-8");host=self.host()
        _,first=run_media_hosting(self.root,"project",host=host);_,second=run_media_hosting(self.root,"project",host=host)
        self.assertEqual(first["uploaded"],1);self.assertEqual(second["reused"],1);self.assertEqual(len(self.s3.uploads),1);self.assertEqual(second["meta_write_requests"],0)
    def test_secrets_not_in_errors(self):
        class BadS3:
            def upload_file(self,*a,**k):raise RuntimeError("provider rejected request")
        image=self.root/"x.png";image.write_bytes(b"x");host=CloudflareR2MediaHost(self.root,env=self.env,client=BadS3(),verifier=self.verify)
        with self.assertRaises(MediaHostingError) as raised:host.upload(image,project_id="p",release_id="r",platform="i",package_id="pkg",branded_item_id="item")
        self.assertNotIn("secret",str(raised.exception));self.assertNotIn("access",str(raised.exception))

if __name__ == "__main__": unittest.main()
