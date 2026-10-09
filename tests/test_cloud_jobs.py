import copy
import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from src.publishing.cloud_jobs import signed_job


class Response:
    headers = {"Content-Type": "image/png"}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return b"production"


class CloudJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for name, data in [("source",b"source"),("document",b"document"),("production",b"production")]:
            (self.root/name).write_bytes(data)
        digest=lambda name: hashlib.sha256((self.root/name).read_bytes()).hexdigest()
        source=dict(asset_id="a",project_id="P",source_hash=digest("source"),source_document_hash=digest("document"),source_page=4,source_path=str(self.root/'source'),source_document_path=str(self.root/'document'))
        self.ctx={"visual_assets":[source]}
        self.item=dict(package_hash="certified",publication_identity="publication",semantic_creative_identity="creative")
        self.package=dict(package_id="p",project_id="P",package_type="single_post",campaign_scope={"campaign_id":"C"},project_sequence={"role":"community_lifestyle"},source_asset_ids=["a"],image={"image_path":str(self.root/'production'),"image_hash":digest("production")},caption={"full_caption":"Brochure illustration"})
        self.host={"records":[dict(package_id="p",local_sha256=digest("production"),verified_accessible=True,public_url="https://example.com/image.png")]}
        self.gates=patch('src.publishing.cloud_jobs.final_publish_errors',return_value=[]);self.gates.start()
        self.download=patch('src.publishing.cloud_jobs.urlopen',return_value=Response());self.download.start()
    def tearDown(self):
        self.gates.stop();self.download.stop();self.tmp.cleanup()
    def export(self):return signed_job(self.item,self.package,self.ctx,self.host,account_id="A",day="2026-10-09",signing_key="s"*64)
    def test_exact_signature_and_baghdad_schedule(self):
        envelope=self.export();job=json.loads(envelope['payload'])
        self.assertEqual(job['scheduled_at'],'2026-10-09T09:00:00+03:00')
        self.assertEqual(envelope['signature'],hmac.new(('s'*64).encode(),envelope['payload'].encode(),hashlib.sha256).hexdigest())
        self.assertEqual(job['certification']['source_evidence'][0]['asset_id'],'a')
    def test_failed_final_gate_rejects_export(self):
        with patch('src.publishing.cloud_jobs.final_publish_errors',return_value=['brand changed']):
            with self.assertRaises(ValueError):self.export()
    def test_source_document_and_production_tampering_rejected(self):
        for name in ('source','document','production'):
            original=(self.root/name).read_bytes();(self.root/name).write_bytes(b'changed')
            with self.assertRaises(ValueError):self.export()
            (self.root/name).write_bytes(original)
    def test_wrong_project_and_missing_page_rejected(self):
        self.ctx['visual_assets'][0]['project_id']='Other'
        with self.assertRaises(ValueError):self.export()
        self.ctx['visual_assets'][0]['project_id']='P';self.ctx['visual_assets'][0].pop('source_page')
        with self.assertRaises(ValueError):self.export()
    def test_hosted_bytes_changed_rejected(self):
        with patch.object(Response,'read',return_value=b'changed'):
            with self.assertRaises(ValueError):self.export()
    def test_llm_only_unit_evidence_rejected(self):
        self.package['project_sequence']['role']='unit_layouts'
        with self.assertRaises(ValueError):self.export()

    def test_reviewed_entrance_support_exports_only_after_approved_whole_development_cover(self):
        from copy import deepcopy
        a=self.ctx['visual_assets'][0]
        a['visual_purpose_review']={k:a[k] for k in ('asset_id','project_id','source_hash','source_document_hash','source_page')}
        a['visual_purpose_review'].update(purpose='project_overview',status='APPROVED',scope='whole_development',sequence=1)
        (self.root/'source-b').write_bytes(b'entrance');(self.root/'production-b').write_bytes(b'production-b')
        b={**deepcopy(a),'asset_id':'b','source_path':str(self.root/'source-b'),'source_hash':hashlib.sha256(b'entrance').hexdigest()}
        b['visual_purpose_review'].update(asset_id='b',source_hash=b['source_hash'],scope='project_context',sequence=2)
        self.ctx['visual_assets'].append(b)
        self.package.update(package_type='carousel',project_sequence={'role':'project_overview'},slides=[
            {'source_asset_ids':['a'],'image_path':str(self.root/'production'),'image_hash':hashlib.sha256(b'production').hexdigest()},
            {'source_asset_ids':['b'],'image_path':str(self.root/'production-b'),'image_hash':hashlib.sha256(b'production-b').hexdigest()}])
        self.host['records'].append(dict(package_id='p',local_sha256=hashlib.sha256(b'production-b').hexdigest(),verified_accessible=True,public_url='https://example.com/b.png'))
        def download(request,**kwargs):
            response=Response()
            if request.full_url.endswith('/b.png'):response.read=lambda:b'production-b'
            return response
        with patch('src.publishing.cloud_jobs.urlopen',side_effect=download):
            self.assertTrue(json.loads(self.export()['payload'])['certification']['overview_source_approved'])
            self.package['slides'].reverse()
            with self.assertRaises(ValueError):self.export()
