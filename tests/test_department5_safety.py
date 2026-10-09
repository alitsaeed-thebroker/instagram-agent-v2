"""Final-boundary, crash and recovery tests using real production fixtures."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json, os, subprocess, sys, threading, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import tests.test_publishing as production_fixtures
from tests.test_meta_adapter import FakeGraph
from src.publishing.controlled import controlled_publish, ControlledPublishError
from src.publishing.foundation import _atomic_json, _lock, final_publish_errors, PublishingFoundation, _publication_identity, _json_hash
from src.publishing.ledger import PublicationLedger, LedgerConflict
from src.publishing.meta import MetaInstagramAdapter, MetaHttpClient, ExternalUrlMediaHost, MetaAdapterError


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=production_fixtures.PublishingFoundationTests();self.fixture.setUp()
        self.root=self.fixture.root;self.project=self.fixture.project;self.pub=self.fixture.pub
        self.pub.queue();self.pub.schedule();self.pub.preflight()
        self.original=json.loads(self.pub.queue_path.read_text());self.item=self.original['items'][0]
        self.ledger=PublicationLedger(self.root)
        config={'enabled':True,'allow_immediate_publish':True,'media_hosting_mode':'external_url','api_version':'v23.0',
                'container_poll_attempts':1,'container_poll_interval_seconds':0,'append_hashtags_to_caption':True,
                'publish_single_image':True,'publish_carousel':True,'publish_story':True}
        _atomic_json(self.root/'input/publishing/meta-config.json',config)
        self.env=patch.dict(os.environ,{'META_ACCESS_TOKEN':'fixture','META_FACEBOOK_PAGE_ID':'page-1','META_INSTAGRAM_ACCOUNT_ID':''});self.env.start()
        self.graph=FakeGraph()
        host=ExternalUrlMediaHost(verifier=lambda url:{'accessible':True,'content_type':'image/png','authentication_required':False})
        host.prepare_media=lambda path,url:'https://fixture.invalid/image.png'
        self.adapter=MetaInstagramAdapter(self.root,client=MetaHttpClient('fixture','v23.0',transport=self.graph),media_host=host,sleep=lambda _:None)
        self.host=SimpleNamespace(status=lambda:{'ready':True})
    def tearDown(self):self.env.stop();self.fixture.tearDown()
    def publish(self):
        return controlled_publish(self.root,self.project,queue_item_id=self.item['queue_item_id'],confirm=True,adapter=self.adapter,r2_host=self.host)
    def posts(self):return [x for x in self.graph.calls if x[0]=='POST']
    def test_valid_controlled_publish_commits_intent_before_every_remote_write(self):
        original=self.graph.__call__;seen=[]
        def transport(method,path,params):
            if method=='POST':seen.append(self.ledger.get(self.item['publication_identity']))
            return original(method,path,params)
        self.adapter.client._transport=transport
        self.assertEqual(self.publish()['status'],'published')
        self.assertTrue(seen);self.assertTrue(all(row and row['account_id']=='ig-1' for row in seen))
        record=self.ledger.get(self.item['publication_identity']);self.assertEqual(record['state'],'CONFIRMED_PUBLISHED')
    def test_crash_after_remote_success_queue_rollback_never_republishes(self):
        original=self.adapter._confirm_remote
        self.adapter._confirm_remote=lambda *a:(_ for _ in ()).throw(SystemExit('crash'))
        with self.assertRaises(SystemExit):self.publish()
        record=self.ledger.get(self.item['publication_identity'])
        self.assertEqual(record['remote_media_id'],'media-1');self.assertEqual(record['parent_container_id'],'child-1')
        before=len(self.posts());_atomic_json(self.pub.queue_path,self.original)
        self.assertEqual(self.publish()['status'],'reconciliation_required');self.assertEqual(len(self.posts()),before)
        self.adapter._confirm_remote=original
        result=self.ledger.reconcile_publication(self.item['publication_identity'],self.adapter)
        self.assertEqual(result['result'],'CONFIRMED_PUBLISHED')
    def test_crash_before_first_write_survives_generated_output_reset(self):
        self.adapter.publish=lambda *a:(_ for _ in ()).throw(SystemExit('crash'))
        with self.assertRaises(SystemExit):self.publish()
        self.assertIsNotNone(self.ledger.get(self.item['publication_identity']))
        _atomic_json(self.pub.queue_path,self.original)
        self.assertEqual(self.publish()['status'],'reconciliation_required');self.assertEqual(self.posts(),[])
    def test_changed_media_is_rejected_by_both_entry_points(self):
        ctx=self.pub._inputs();package=ctx['packages']['packages'][0]
        Path(package['image']['image_path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ControlledPublishError,'Final publication gate'):self.publish()
        self.adapter.publish_project(self.pub)
        self.assertEqual(self.posts(),[])
        self.assertEqual(json.loads(self.pub.queue_path.read_text())['items'][0]['status'],'blocked')
    def test_due_schedule_can_pass_final_gate(self):
        ctx=self.pub._inputs();package=ctx['packages']['packages'][0]
        item={**self.item,'scheduled_at_utc':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()}
        self.assertEqual(final_publish_errors(item,package,ctx),[])
    def test_revoked_brand_and_provenance_fail_final_gate(self):
        ctx=self.pub._inputs();package=ctx['packages']['packages'][0]
        ctx['brand']['approval']['locked']=False;ctx['provenance']['items']=[]
        errors=final_publish_errors(self.item,package,ctx)
        self.assertIn('invalid brand lock',errors);self.assertIn('invalid provenance',errors)
    def test_batch_stale_preflight_cannot_bypass_unverified_plan(self):
        ctx=self.pub._inputs();package=ctx['packages']['packages'][0]
        package['caption']['full_caption']='Type D unit layout, 5-bedroom'
        package['image']['source_asset_ids']=['unverified-plan']
        with patch.object(self.pub,'_inputs',return_value=ctx):self.adapter.publish_project(self.pub)
        self.assertEqual(self.posts(),[])
        errors=json.loads(self.pub.queue_path.read_text())['items'][0]['errors']
        self.assertTrue(any('layout' in str(x).lower() for x in errors))
    def test_os_lock_recovers_after_actual_process_death(self):
        path=self.root/'dead.lock'
        code="from pathlib import Path; import os; from src.publishing.foundation import _lock;\nwith _lock(Path("+repr(str(path))+")): os._exit(0)"
        result=subprocess.run([sys.executable,'-c',code],capture_output=True)
        self.assertEqual(result.returncode,0)
        with _lock(path,timeout=.2):self.assertTrue(path.exists())
    def test_two_concurrent_reservations_cannot_cross_projects(self):
        item=deepcopy(self.item);item['attempt_token']='attempt'
        barrier=threading.Barrier(2);accepted=[];rejected=[]
        def reserve(project):
            candidate={**item,'project_id':project,'queue_item_id':project,'publication_identity':project}
            barrier.wait()
            try:self.ledger.reserve(candidate,{},'ig-1',{});accepted.append(project)
            except LedgerConflict:rejected.append(project)
        threads=[threading.Thread(target=reserve,args=(p,)) for p in ('A','B')]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(len(accepted),1);self.assertEqual(len(rejected),1)
    def test_checkpoint_failure_prevents_remote_write(self):
        with patch.object(self.ledger.__class__,'checkpoint',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.publish()
        self.assertEqual(self.posts(),[]);self.assertIsNotNone(self.ledger.get(self.item['publication_identity']))
    def test_container_reconciliation_published_finished_and_wrong_account(self):
        item={**self.item,'attempt_token':'attempt'}
        self.ledger.reserve(item,{},'ig-1',{})
        identity=item['publication_identity']
        self.ledger.checkpoint(identity,'attempt','after_write',{'role':'parent','remote_id':'container'})
        adapter=SimpleNamespace(account={'instagram_account_id':'other'},get_container_status=lambda x:{'status':'published'})
        self.assertEqual(self.ledger.reconcile_publication(identity,adapter)['result'],'IDENTITY_MISMATCH')
        adapter.account={'instagram_account_id':'ig-1'}
        adapter.get_container_status=lambda x:{'status':'unknown','status_code':'FINISHED'}
        self.assertEqual(self.ledger.reconcile_publication(identity,adapter)['result'],'STILL_UNCERTAIN')
        adapter.get_container_status=lambda x:{'status':'published','status_code':'PUBLISHED','container_id':x}
        self.assertEqual(self.ledger.reconcile_publication(identity,adapter,dry_run=True)['result'],'CONFIRMED_PUBLISHED')
        self.assertEqual(self.ledger.get(identity)['state'],'RECONCILIATION_REQUIRED')
        self.assertEqual(self.ledger.reconcile_publication(identity,adapter)['result'],'CONFIRMED_PUBLISHED')
        self.assertIsNone(self.ledger.get(identity)['remote_media_id'])

    def test_crash_matrix_single_carousel_and_story_remote_boundaries(self):
        self.adapter.account={'instagram_account_id':'ig-1'}
        for kind,total in (('single_post',2),('carousel',4),('story',2)):
            for event in ('before_write','after_write'):
                for number in range(1,total+1):
                    with self.subTest(kind=kind,event=event,number=number):
                        ledger=PublicationLedger(self.root/f'matrix/{kind}-{event}-{number}')
                        ledger.initialize(fresh=True)
                        item={**self.item,'publication_identity':'matrix','attempt_token':'attempt','package_type':kind}
                        payload={'package_type':kind,'caption':'Exterior','media':[{'image_url':'https://fixture.invalid/1.png','provenance_id':'b'}],
                                 'api_version':'v23.0'}
                        if kind=='carousel':payload['media'].append({'image_url':'https://fixture.invalid/2.png','provenance_id':'b2'})
                        ledger.reserve(item,payload,'ig-1',{})
                        counts={'before_write':0,'after_write':0}
                        def checkpoint(actual,details):
                            ledger.checkpoint('matrix','attempt',actual,details)
                            counts[actual]+=1
                            if actual==event and counts[actual]==number:raise SystemExit('crash')
                        self.adapter.checkpoint=checkpoint
                        self.adapter.client._transport=FakeGraph()
                        with self.assertRaises(SystemExit):self.adapter.publish(payload,item)
                        self.assertIsNotNone(ledger.get('matrix'))
                        with self.assertRaises(LedgerConflict):ledger.reserve(item,payload,'ig-1',{})
                        if event=='after_write' and number==total:
                            self.assertEqual(ledger.get('matrix')['remote_media_id'],'media-1')
        self.adapter.checkpoint=None

    def test_batch_valid_publish_uses_durable_checkpoints(self):
        ctx=self.pub._inputs();package=ctx['packages']['packages'][0]
        package['image']['public_media_url']='https://fixture.invalid/1.png'
        queue=json.loads(self.pub.queue_path.read_text())
        from src.publishing.foundation import _json_hash
        queue['items'][0]['package_hash']=_json_hash(package);_atomic_json(self.pub.queue_path,queue)
        with patch.object(self.pub,'_inputs',return_value=ctx):self.adapter.publish_project(self.pub)
        row=self.ledger.get(self.item['publication_identity'])
        self.assertEqual(row['state'],'CONFIRMED_PUBLISHED');self.assertEqual(row['account_id'],'ig-1')

    def test_final_gate_rejects_stale_package_and_invalid_release(self):
        ctx=self.pub._inputs();package=deepcopy(ctx['packages']['packages'][0])
        package['caption']['full_caption']='Changed public copy'
        ctx['release']['status']='failed'
        errors=final_publish_errors(self.item,package,ctx)
        self.assertIn('current package changed during publishing preparation',errors)
        self.assertIn('release is invalid or superseded',errors)

    def test_queue_identity_and_media_cannot_be_forged_to_evade_duplicates(self):
        ctx=self.pub._inputs();package=ctx['packages']['packages'][0]
        item={**self.item,'publication_identity':'forged','idempotency_key':'forged','image_hashes':['forged']}
        errors=final_publish_errors(item,package,ctx)
        self.assertIn('publication identity does not match the current package',errors)
        self.assertIn('queue media hashes do not match the current package',errors)

    def test_container_adapter_never_treats_finished_error_expired_as_published(self):
        for code in ('FINISHED','ERROR','EXPIRED','IN_PROGRESS','PUBLISHED'):
            self.adapter.client._transport=lambda *args,code=code:{'id':'container','status_code':code}
            result=self.adapter.get_container_status('container')
            self.assertEqual(result['status'],'published' if code=='PUBLISHED' else 'unknown')

    def test_publish_intent_ledger_loss_prevents_remote_write(self):
        with patch.object(PublicationLedger,'reserve',side_effect=OSError('ledger disk unavailable')):
            with self.assertRaises(OSError):self.publish()
        self.assertEqual(self.posts(),[])

    def test_unknown_remote_response_keeps_checkpointed_ids_and_account(self):
        self.adapter._confirm_remote=lambda *args:(_ for _ in ()).throw(MetaAdapterError('lookup unavailable','transient_platform'))
        with self.assertRaises(ControlledPublishError):self.publish()
        row=self.ledger.get(self.item['publication_identity'])
        self.assertEqual(row['remote_media_id'],'media-1');self.assertEqual(row['account_id'],'ig-1')
        self.assertEqual(row['state'],'PUBLISHING_UNCERTAIN');self.assertTrue(row['media_hashes'])

    def test_crash_after_ledger_confirmation_before_manifest_save(self):
        original=_atomic_json
        def write(path,value):
            if path==self.pub.manifest_path:raise SystemExit('receipt save crash')
            return original(path,value)
        with patch('src.publishing.controlled._atomic_json',side_effect=write):
            with self.assertRaises(SystemExit):self.publish()
        self.assertEqual(self.ledger.get(self.item['publication_identity'])['state'],'CONFIRMED_PUBLISHED')
        before=len(self.posts());_atomic_json(self.pub.queue_path,self.original)
        self.assertEqual(self.publish()['status'],'already_published');self.assertEqual(len(self.posts()),before)

    def test_lost_publish_response_id_recovers_using_checkpointed_container(self):
        original=PublicationLedger.checkpoint
        def checkpoint(ledger,identity,attempt,event,details):
            if event=='after_write' and details['role']=='publish':raise SystemExit('response checkpoint crash')
            return original(ledger,identity,attempt,event,details)
        with patch.object(PublicationLedger,'checkpoint',new=checkpoint):
            with self.assertRaises(SystemExit):self.publish()
        identity=self.item['publication_identity'];row=self.ledger.get(identity)
        self.assertIsNone(row['remote_media_id']);self.assertEqual(row['parent_container_id'],'child-1')
        self.adapter.client._transport=lambda method,path,params:{'id':path,'status_code':'PUBLISHED'}
        self.assertEqual(self.ledger.reconcile_publication(identity,self.adapter)['result'],'CONFIRMED_PUBLISHED')
        self.assertIsNone(self.ledger.get(identity)['remote_media_id'])

    def test_concurrent_controlled_projects_recheck_global_cooldown(self):
        ctx=self.pub._inputs();states={}
        for project in ('Concurrent A','Concurrent B'):
            foundation=PublishingFoundation(project,self.root)
            package=deepcopy(ctx['packages']['packages'][0]);package['project_id']=project
            identity=_publication_identity(project,package,'instagram')
            item={**self.item,'project_id':project,'queue_item_id':project,'publication_identity':identity,
                  'idempotency_key':identity,'package_hash':_json_hash(package)}
            states[project]=(foundation,{'items':[item]},{package['package_id']:package},
                             {'project_id':project,'real_receipts':[],'publication_history':[]})
        barrier=threading.Barrier(2);outcomes=[]
        def publish(project):
            barrier.wait()
            try:outcomes.append(controlled_publish(self.root,project,queue_item_id=project,confirm=True,
                                                    adapter=self.adapter,r2_host=self.host)['status'])
            except ControlledPublishError:outcomes.append('blocked')
        with patch('src.publishing.controlled._state',side_effect=lambda root,project:states[project]), \
             patch.object(PublishingFoundation,'_inputs',return_value=ctx), \
             patch('src.publishing.controlled.final_publish_errors',return_value=[]):
            threads=[threading.Thread(target=publish,args=(project,)) for project in states]
            for thread in threads:thread.start()
            for thread in threads:thread.join(timeout=10)
        self.assertCountEqual(outcomes,['published','blocked'])
        self.assertEqual(sum(path.endswith('/media_publish') for _,path,_ in self.posts()),1)

if __name__=='__main__':unittest.main()
