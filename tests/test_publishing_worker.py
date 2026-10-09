from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.publishing.foundation import PublishingFoundation, _lock
from src.publishing.ledger import PublicationLedger
from src.publishing.worker import (EXIT_CONFIGURATION, EXIT_LEDGER, EXIT_OK, WorkerError,
    WorkerState, discover_projects, ledger_precheck, run_worker, worker_config)
from src.publishing.windows_scheduler import (TaskDefinition, WindowsTaskSchedulerAdapter,
    desired_task, install_worker, scheduler_status, task_xml)


POLICY={"schema_version":"1.0.0","timezone":"Asia/Baghdad","retry_policy":{"max_attempts":3,"initial_delay_minutes":5,"backoff_multiplier":2},
        "scheduling_policy":{"minimum_global_interval_minutes":0,"minimum_feed_interval_minutes":0,"minimum_story_interval_minutes":0,"minimum_project_interval_minutes":0,"cross_surface_reuse_cooldown_minutes":0,"allow_same_surface_recycling":False,"simultaneous_cross_surface_allowed":False},
        "worker":{"enabled":True,"task_name":"InstagramAgent-PublishingWorker","poll_interval_minutes":15,"log_retention":3}}


class FakeRunner:
    def __init__(self, code=0, stdout="", stderr=""):self.calls=[];self.code=code;self.stdout=stdout;self.stderr=stderr
    def __call__(self,args,**kwargs):self.calls.append((args,kwargs));return subprocess.CompletedProcess(args,self.code,self.stdout,self.stderr)


class PublishingWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.write("input/publishing/publishing-config.json",POLICY);(self.root/"app.py").write_text("",encoding="utf-8");PublicationLedger(self.root).initialize(fresh=True)
    def tearDown(self):self.temp.cleanup()
    def write(self,path,value):
        target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(value),encoding="utf-8");return target
    def queue(self,project="A",items=None):
        return self.write(f"output/publishing/{project}-publishing-queue.json",{"project_id":project,"items":items or []})
    def item(self,qid="q",project="A",priority=100):
        return {"queue_item_id":qid,"project_id":project,"publication_identity":"pub-"+qid,"idempotency_key":"pub-"+qid,"package_id":"pkg-"+qid,"package_type":"single_post","platform":"instagram","surface":"feed","format":"single_image","image_hashes":["hash-"+qid],"semantic_creative_identity":"creative-"+qid,"priority":priority,"status":"preflight_ready","created_at":"2026-08-01T00:00:00+00:00"}
    def cycle(self,**kwargs):
        with patch.object(PublishingFoundation,"_inputs",return_value={}):return run_worker(self.root,now=datetime(2026,8,12,tzinfo=timezone.utc),**kwargs)

    def test_no_queue_is_success(self):self.assertEqual(self.cycle()["classification"],"NO_ELIGIBLE_PUBLICATION")
    def test_no_eligible_is_success(self):self.queue(items=[{**self.item(),"status":"published"}]);self.assertEqual(self.cycle()["exit_code"],EXIT_OK)
    def test_worker_dry_run_selects_without_publish(self):self.queue(items=[self.item()]);called=[];result=self.cycle(dry_run=True,publisher=lambda *a,**k:called.append(1));self.assertEqual(result["classification"],"DRY_RUN_ELIGIBLE");self.assertFalse(called)
    def test_at_most_one_publication(self):
        self.queue(items=[self.item("a"),self.item("b")]);calls=[]
        result=self.cycle(publisher=lambda *a,**k:(calls.append((a,k)) or {"status":"published"}));self.assertEqual(len(calls),1);self.assertTrue(result["published"])
    def test_priority_cross_project(self):
        self.queue("A",[self.item("a","A",1)]);self.queue("B",[self.item("b","B",9)]);calls=[]
        self.cycle(publisher=lambda *a,**k:(calls.append((a,k)) or {"status":"published"}));self.assertEqual(calls[0][0][1],"B")
    def test_tie_break_cross_project(self):
        self.queue("B",[self.item("b","B")]);self.queue("A",[self.item("a","A")]);calls=[]
        self.cycle(publisher=lambda *a,**k:(calls.append((a,k)) or {"status":"published"}));self.assertEqual(calls[0][1]["queue_item_id"],"q" if False else "a")
    def test_pause_zero_publication(self):WorkerState(self.root).set_enabled(False);self.queue(items=[self.item()]);calls=[];self.cycle(publisher=lambda *a,**k:calls.append(1));self.assertFalse(calls)
    def test_resume_evaluates(self):WorkerState(self.root).set_enabled(False);WorkerState(self.root).set_enabled(True);self.assertEqual(self.cycle()["classification"],"NO_ELIGIBLE_PUBLICATION")
    def test_pause_survives_restart(self):WorkerState(self.root).set_enabled(False);self.assertFalse(WorkerState(self.root).enabled())
    def test_corrupt_pause_fails_closed(self):WorkerState(self.root).control_path.parent.mkdir(parents=True,exist_ok=True);WorkerState(self.root).control_path.write_text("bad");self.assertFalse(WorkerState(self.root).enabled())
    def test_corrupt_health_is_non_authoritative(self):WorkerState(self.root).status_path.parent.mkdir(parents=True,exist_ok=True);WorkerState(self.root).status_path.write_text("bad");self.assertEqual(self.cycle()["exit_code"],0)
    def test_dry_run_mutates_no_status(self):self.queue(items=[self.item()]);self.cycle(dry_run=True);self.assertFalse(WorkerState(self.root).status_path.exists())
    def test_no_eligible_dry_run_mutates_no_status(self):self.cycle(dry_run=True);self.assertFalse(WorkerState(self.root).status_path.exists())
    def test_missing_established_ledger_fails_closed(self):PublicationLedger(self.root).path.unlink();self.queue();result=self.cycle();self.assertEqual(result["exit_code"],EXIT_LEDGER)
    def test_fresh_worker_initializes_ledger(self):ledger=PublicationLedger(self.root);ledger.path.unlink();ledger.established_marker.unlink();self.assertEqual(self.cycle()["exit_code"],EXIT_OK);self.assertTrue(ledger.path.exists())
    def test_fresh_worker_dry_run_does_not_initialize(self):ledger=PublicationLedger(self.root);ledger.path.unlink();ledger.established_marker.unlink();self.assertEqual(self.cycle(dry_run=True)["exit_code"],EXIT_OK);self.assertFalse(ledger.path.exists())
    def test_marker_prevents_false_fresh_after_ledger_loss(self):PublicationLedger(self.root).path.unlink();self.assertEqual(self.cycle()["exit_code"],EXIT_LEDGER)
    def test_corrupt_ledger_fails_closed(self):PublicationLedger(self.root).path.write_bytes(b"bad");self.assertEqual(self.cycle()["exit_code"],EXIT_LEDGER)
    def test_uncertain_ledger_blocks_all(self):
        PublicationLedger(self.root).record({**self.item(),"state":"PUBLISHING_UNCERTAIN"});self.assertEqual(self.cycle()["classification"],"RECONCILIATION_REQUIRED")
    def test_project_mismatch_fails(self):self.write("output/publishing/A-publishing-queue.json",{"project_id":"B","items":[]});self.assertEqual(self.cycle()["exit_code"],EXIT_CONFIGURATION)
    def test_d4_contract_is_checked(self):
        self.queue(items=[self.item()])
        with patch.object(PublishingFoundation,"_inputs",side_effect=ValueError("contract")):result=run_worker(self.root)
        self.assertEqual(result["classification"],"SAFETY_FAILURE")
    def test_global_lock_blocks_overlap(self):
        lock=self.root/"state/publishing/.worker.lock"
        with _lock(lock):self.assertEqual(self.cycle()["classification"],"WORKER_LOCK_UNAVAILABLE")
    def test_worker_has_no_retry_loop(self):
        self.queue(items=[self.item()]);calls=[];result=self.cycle(publisher=lambda *a,**k:(calls.append(1) or (_ for _ in ()).throw(OSError("network"))));self.assertEqual(len(calls),1);self.assertNotEqual(result["exit_code"],0)
    def test_logs_are_bounded(self):
        for _ in range(5):self.cycle()
        self.assertLessEqual(len(list(WorkerState(self.root).logs.glob("*.json"))),3)
    def test_logs_are_secret_safe(self):
        previous=os.environ.get("META_ACCESS_TOKEN");os.environ["META_ACCESS_TOKEN"]="super-secret-test"
        try:self.cycle();data="".join(x.read_text() for x in WorkerState(self.root).logs.glob("*.json"));self.assertNotIn("super-secret-test",data)
        finally:
            if previous is None:os.environ.pop("META_ACCESS_TOKEN",None)
            else:os.environ["META_ACCESS_TOKEN"]=previous
    def test_status_is_non_authoritative(self):self.cycle();self.assertFalse(json.loads(WorkerState(self.root).status_path.read_text())["authoritative"])
    def test_discovery_is_deterministic(self):self.queue("Z");self.queue("A");self.assertEqual(discover_projects(self.root),["A","Z"])
    def test_default_worker_config(self):POLICY2={k:v for k,v in POLICY.items() if k!="worker"};self.write("input/publishing/publishing-config.json",POLICY2);self.assertEqual(worker_config(self.root)["poll_interval_minutes"],15)
    def test_invalid_low_interval(self):value={**POLICY,"worker":{**POLICY["worker"],"poll_interval_minutes":0}};self.write("input/publishing/publishing-config.json",value);self.assertRaises(WorkerError,worker_config,self.root)
    def test_invalid_high_interval(self):value={**POLICY,"worker":{**POLICY["worker"],"poll_interval_minutes":1441}};self.write("input/publishing/publishing-config.json",value);self.assertRaises(WorkerError,worker_config,self.root)
    def test_invalid_interval_type(self):value={**POLICY,"worker":{**POLICY["worker"],"poll_interval_minutes":"15"}};self.write("input/publishing/publishing-config.json",value);self.assertRaises(WorkerError,worker_config,self.root)
    def test_invalid_retention(self):value={**POLICY,"worker":{**POLICY["worker"],"log_retention":0}};self.write("input/publishing/publishing-config.json",value);self.assertRaises(WorkerError,worker_config,self.root)

    def definition(self):return TaskDefinition("InstagramAgent-PublishingWorker",r"C:\Program Files\Python\python.exe",r'"C:\Work Space\app.py" --publishing-worker',r"C:\Work Space",15)
    def test_stable_task_name(self):self.assertEqual(self.definition().task_name,"InstagramAgent-PublishingWorker")
    def test_xml_non_overlap(self):self.assertIn("IgnoreNew",task_xml(self.definition()))
    def test_xml_start_when_available(self):self.assertIn("StartWhenAvailable>true",task_xml(self.definition()))
    def test_xml_interval(self):self.assertIn("PT15M",task_xml(self.definition()))
    def test_xml_working_directory(self):self.assertIn("C:\\Work Space",task_xml(self.definition()))
    def test_xml_absolute_interpreter(self):self.assertIn("C:\\Program Files\\Python\\python.exe",task_xml(self.definition()))
    def test_xml_worker_argument(self):self.assertIn("--publishing-worker",task_xml(self.definition()))
    def test_xml_least_privilege(self):self.assertIn("LeastPrivilege",task_xml(self.definition()))
    def test_xml_interactive_user(self):self.assertIn("InteractiveToken",task_xml(self.definition()))
    def test_xml_has_no_token(self):self.assertNotIn("META_ACCESS_TOKEN",task_xml(self.definition()))
    def test_xml_has_no_app_secret(self):self.assertNotIn("META_APP_SECRET",task_xml(self.definition()))
    def test_install_uses_force_update(self):runner=FakeRunner();WindowsTaskSchedulerAdapter(runner).install(self.definition());self.assertIn("/F",runner.calls[0][0])
    def test_install_idempotent_command(self):runner=FakeRunner();adapter=WindowsTaskSchedulerAdapter(runner);adapter.install(self.definition());adapter.install(self.definition());self.assertEqual(runner.calls[0][0][3],runner.calls[1][0][3]);self.assertEqual(runner.calls[0][0][-1],"/F")
    def test_uninstall_owned_name_only(self):runner=FakeRunner();WindowsTaskSchedulerAdapter(runner).uninstall("Owned");self.assertEqual(runner.calls[0][0][3],"Owned")
    def test_uninstall_missing_is_safe(self):runner=FakeRunner(1,stderr="ERROR: cannot find");self.assertFalse(WindowsTaskSchedulerAdapter(runner).uninstall("Owned")["installed"])
    def test_pause_scheduler_command(self):runner=FakeRunner();WindowsTaskSchedulerAdapter(runner).set_enabled("Owned",False);self.assertIn("/DISABLE",runner.calls[0][0])
    def test_resume_scheduler_command(self):runner=FakeRunner();WindowsTaskSchedulerAdapter(runner).set_enabled("Owned",True);self.assertIn("/ENABLE",runner.calls[0][0])
    def test_status_not_installed(self):self.assertFalse(WindowsTaskSchedulerAdapter(FakeRunner(1)).status("Owned")["installed"])
    def test_status_installed(self):self.assertTrue(WindowsTaskSchedulerAdapter(FakeRunner(stdout="Status: Ready\nNext Run Time: tomorrow")).status("Owned")["installed"])
    def test_install_dry_run_mutates_nothing(self):result=install_worker(self.root,dry_run=True);self.assertFalse(result["mutated"])
    def test_install_dry_run_absolute_paths(self):result=install_worker(self.root,dry_run=True);self.assertTrue(Path(result["executable"]).is_absolute());self.assertTrue(Path(result["working_directory"]).is_absolute())
    def test_install_dry_run_no_secrets(self):self.assertFalse(install_worker(self.root,dry_run=True)["secrets_present"])
    def test_install_dry_run_reports_fresh_ledger(self):ledger=PublicationLedger(self.root);ledger.path.unlink();ledger.established_marker.unlink();self.assertTrue(install_worker(self.root,dry_run=True)["installation_ready"])
    def test_real_install_rejects_missing_established_ledger(self):PublicationLedger(self.root).path.unlink();self.queue();self.assertRaises(Exception,install_worker,self.root,adapter=WindowsTaskSchedulerAdapter(FakeRunner()))
    def test_invalid_repository_detected(self):self.assertRaises(WorkerError,desired_task,self.root/"missing")
    def test_invalid_python_detected(self):self.write("app.py",{});self.assertRaises(WorkerError,desired_task,self.root,self.root/"missing.exe")
    def test_spaces_are_preserved(self):self.write("app.py",{});definition=desired_task(self.root);self.assertIn('"',definition.arguments)
    def test_uninstall_preserves_ledger(self):before=PublicationLedger(self.root).path.read_bytes();WindowsTaskSchedulerAdapter(FakeRunner()).uninstall("Owned");self.assertEqual(PublicationLedger(self.root).path.read_bytes(),before)
    def test_status_reports_pause(self):WorkerState(self.root).set_enabled(False);self.write("app.py",{});self.assertFalse(scheduler_status(self.root,FakeScheduler())["worker_enabled"])
    def test_configuration_reload_keeps_identity(self):self.write("app.py",{});self.assertEqual(desired_task(self.root).task_name,desired_task(self.root).task_name)


class FakeScheduler:
    def status(self,name):return {"installed":False,"task_name":name}


if __name__=="__main__":unittest.main()
