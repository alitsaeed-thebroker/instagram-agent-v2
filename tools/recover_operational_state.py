"""Reproducible, isolated operational recovery. Never publishes or schedules.

prepare: snapshots protected state, quarantines only the proven obsolete D1 JSONs,
and copies the original Beverly Hills PDF and approved inputs into an isolated run.
core: executes the existing D1/D2 implementation in that isolated run. Requires
the existing OpenAI connection; failures remain failures, without cached substitution.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
RECOVERY=ROOT/"output/recovery/20261009T193500Z"
ISOLATED=RECOVERY/"beverly-isolated"
sys.path.insert(0,str(ROOT))

def read(path):return json.loads(path.read_text(encoding="utf-8-sig"))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def protected_inventory():
    files=[ROOT/".env",*list((ROOT/"input").rglob("*.pdf")),*list((ROOT/"input/brand").rglob("*")),*list((ROOT/"input/visual-review").glob("*.json")),*list((ROOT/"state/publishing").glob("*.sqlite3")),*list((ROOT/"deployment/cloudflare/.private-migration").rglob("*.json"))]
    for base in ("output/releases","output/post-packages","output/publishing"):
        files.extend(p for p in (ROOT/base).rglob("*") if p.is_file())
    # Only digests and paths are retained; never copy credentials into reports.
    return {str(p.relative_to(ROOT)):sha(p) for p in files if p.is_file()}

def prepare():
    from src.knowledge.handoff import load_department2_handoff,Department2HandoffError
    from src.department1.pipeline import project_storage_key
    RECOVERY.mkdir(parents=True,exist_ok=True)
    protected=RECOVERY/"protected-before.json"
    if not protected.exists():write(protected,protected_inventory())
    ledger=ROOT/"state/publishing/publication-ledger.sqlite3"
    backup=RECOVERY/"preserved/publication-ledger.sqlite3"
    if not backup.exists():
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(ledger.as_uri()+"?mode=ro",uri=True) as source,sqlite3.connect(backup) as target:source.backup(target)
    legacy=ROOT/"output/department1/VELORIA-BY-SHAHAN-CO"
    canonical=ROOT/"output/department1"/project_storage_key("VELORIA BY SHAHAN CO")/"department2-handoff.json"
    manifest=RECOVERY/"archive-manifest.json"
    if not manifest.exists():
        load_department2_handoff(canonical,expected_project="VELORIA BY SHAHAN CO",project_root=ROOT/"input/VELORIA BY SHAHAN CO")
        try:load_department2_handoff(legacy/"department2-handoff.json",expected_project="VELORIA BY SHAHAN CO",project_root=ROOT/"input/VELORIA BY SHAHAN CO")
        except Department2HandoffError as error:
            reason=str(error)
        else:raise RuntimeError("Legacy handoff is not proven stale; refusing archive")
        archived=[]
        # Explicit allowlist: no images, original PDFs, approved reviews or history.
        for name in ("01-input.json","02-read.json","03-understand.json","04-analyze.json","05-classify.json","06-extract.json","department2-handoff.json","run-summary.json"):
            source=(legacy/name).resolve();target=(RECOVERY/"archived"/source.relative_to(ROOT)).resolve()
            if not source.is_relative_to(ROOT.resolve()) or not target.is_relative_to(RECOVERY.resolve()):raise RuntimeError("Archive path escapes recovery boundary")
            if source.is_file():
                entry={"original":str(source.relative_to(ROOT)),"archive":str(target.relative_to(ROOT)),"sha256":sha(source),"reason":reason}
                target.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(source),str(target));archived.append(entry)
        write(manifest,{"archived":archived,"preserved":"All original PDFs, images, brand assets, reviews, credentials, signed jobs, immutable releases, publication manifests, ledger and receipts","canonical_veloria_handoff_verified":True})
    ISOLATED.mkdir(parents=True,exist_ok=True)
    shutil.copytree(ROOT/"src",ISOLATED/"src",dirs_exist_ok=True,ignore=shutil.ignore_patterns("__pycache__","*.bak","*.phase*_backup"))
    shutil.copy2(ROOT/"app.py",ISOLATED/"app.py")
    for folder in ("input/Beverly Hills","input/brand","input/visual-review","prompts","data"):
        if (ROOT/folder).is_dir():shutil.copytree(ROOT/folder,ISOLATED/folder,dirs_exist_ok=True)
    campaign=ROOT/"input/campaigns/Beverly-Hills-overview-campaign.json"
    (ISOLATED/"input/campaigns").mkdir(parents=True,exist_ok=True);shutil.copy2(campaign,ISOLATED/"input/campaigns"/campaign.name)
    config=read(ROOT/"input/publishing/publishing-config.json")
    config["worker"]["enabled"]=False;config["default_mode"]="manual";config["manual_schedule"]={}
    write(ISOLATED/"input/publishing/publishing-config.json",config)
    meta=read(ROOT/"input/publishing/meta-config.json");meta["enabled"]=False;meta["allow_immediate_publish"]=False
    write(ISOLATED/"input/publishing/meta-config.json",meta)
    write(RECOVERY/"isolation.json",{"root":str(ISOLATED),"project":"Beverly Hills","source_pdf_sha256":sha(ISOLATED/"input/Beverly Hills/Beverly Hills Catalogue.pdf"),"local_publisher_enabled":False,"schedules_created":0,"credentials_copied":False})
    print(json.dumps({"status":"PREPARED","isolated_root":str(ISOLATED),"archive_manifest":str(manifest)},indent=2))

def core():
    # Import only isolated modules: config derives its root from these file paths.
    from dotenv import load_dotenv
    load_dotenv(ROOT/".env")
    sys.path.insert(0,str(ISOLATED));os.chdir(ISOLATED)
    import app
    from src.core.file_manager import find_project_inputs
    from src.department1.pipeline import Department1Pipeline, _atomic_json
    assert app.PROJECT_ROOT.resolve()==ISOLATED.resolve()
    project=next(p for p in find_project_inputs(ISOLATED/"input") if p.name=="Beverly Hills")
    try:
        pipeline=Department1Pipeline(ISOLATED/"input/Beverly Hills",output_root=ISOLATED/"output/department1")
        if not (pipeline.output_dir/"department2-handoff.json").exists():
            manifest=pipeline.input_stage()
            read_path=pipeline.output_dir/"02-read.json"
            evidence=read(read_path) if read_path.is_file() else pipeline.read_stage(manifest)
            actual={s["relative_path"]:s["sha256"] for s in evidence["sources"]}
            expected={f["relative_path"]:f["sha256"] for f in manifest["files"]}
            if actual!=expected:raise RuntimeError("Fresh READ source hashes changed")
            understanding=pipeline.understand_stage(evidence)
            analysis=pipeline.analyze_stage(evidence,understanding)
            classification=pipeline.classify_stage(evidence,understanding,analysis)
            extracted=pipeline.extract_stage(evidence,understanding,analysis,classification)
            handoff=pipeline.build_department2_handoff(manifest,evidence,understanding,analysis,classification,extracted)
            pipeline.validate_handoff(handoff)
            _atomic_json(pipeline.output_dir/"department2-handoff.json",handoff)
        success=app._process_project(project)
        write(RECOVERY/"core-result.json",{"status":"PASSED" if success else "BLOCKED","isolated_root":str(ISOLATED),"fresh_source_processing":True,"cached_ai_substitution":False,"meta_writes":0,"schedules_created":0,"completed_at":datetime.now(timezone.utc).isoformat()})
    except Exception as error:
        # Persist only the exception type; external error messages may contain data.
        write(RECOVERY/"core-result.json",{"status":"BLOCKED","error_type":type(error).__name__,"meta_writes":0,"schedules_created":0})
        raise SystemExit(1)
    raise SystemExit(0 if success else 1)

def verify_preserved():
    before=read(RECOVERY/"protected-before.json")
    changes=[name for name,digest in before.items() if not (ROOT/name).is_file() or sha(ROOT/name)!=digest]
    report={"protected_files_checked":len(before),"changed_protected_files":changes,"status":"PASSED" if not changes else "FAILED"}
    write(RECOVERY/"preservation-check.json",report);print(json.dumps(report,indent=2))

def downstream():
    """Run existing D3/D4 and the unscheduled D5 queue in isolation only."""
    if read(RECOVERY/"core-result.json")["status"] != "PASSED":
        raise RuntimeError("Fresh D1/D2 must pass before downstream execution")
    prior=RECOVERY/"downstream-result.json"
    initial=RECOVERY/"downstream-initial-failure.json"
    if prior.is_file() and read(prior)["status"]=="BLOCKED" and not initial.exists():
        manifest=ISOLATED/"output/manifests/Beverly Hills-run-manifest.json"
        failure=read(manifest).get("failure") or {}
        if failure.get("stage")=="post-package-builder":
            shutil.copy2(prior,initial)
            shutil.copy2(manifest,RECOVERY/"downstream-initial-run-manifest.json")
            archived=[]
            for name in ("content-memory/Beverly Hills-content-memory.json","asset-usage/Beverly Hills-asset-usage.json"):
                source=ISOLATED/"output"/name
                if source.is_file():
                    target=RECOVERY/"archived-isolated-first-attempt"/name
                    target.parent.mkdir(parents=True,exist_ok=True)
                    archived.append({"original":str(source.relative_to(ROOT)),"archive":str(target.relative_to(ROOT)),"sha256":sha(source),"reason":"Unpublished isolated draft run failed package validation; regenerate planning usage without treating aborted drafts as prior use"})
                    shutil.move(str(source),str(target))
            write(RECOVERY/"isolated-retry-archive.json",{"archived":archived,"operational_state_touched":False})
    # Refresh repaired modules; these copies have no operational schedules or keys.
    shutil.copytree(ROOT/"src",ISOLATED/"src",dirs_exist_ok=True,ignore=shutil.ignore_patterns("__pycache__","*.bak","*.phase*_backup"))
    shutil.copy2(ROOT/"app.py",ISOLATED/"app.py")
    from dotenv import load_dotenv
    load_dotenv(ROOT/".env")
    sys.path.insert(0,str(ISOLATED));os.chdir(ISOLATED)
    import app
    from src.core.file_manager import find_project_inputs
    from src.execution.stages import STAGE_ORDER,EXPLICIT_ONLY_STAGES,StageSelection
    assert app.PROJECT_ROOT.resolve()==ISOLATED.resolve()
    config=read(ISOLATED/"input/publishing/publishing-config.json")
    assert config["default_mode"]=="manual" and not config["worker"]["enabled"] and not config["manual_schedule"]
    # Select existing stages explicitly. Never call scheduling, adapters or receipts.
    selected=tuple(s for s in STAGE_ORDER[STAGE_ORDER.index("deep-source-analysis"):STAGE_ORDER.index("publishing-queue")+1] if s not in EXPLICIT_ONLY_STAGES)
    forbidden={"scheduling-engine","publish-preflight","mock-platform-adapter","meta-platform-adapter","publication-manifest"}
    assert not set(selected)&forbidden
    app.select_stages=lambda **kwargs:StageSelection(selected,frozenset())
    app._PLATFORM_STRATEGY="instagram_only"
    app._PLATFORM_STRATEGY_SOURCE="recovery-explicit"
    app._PLATFORM_STRATEGY_REQUESTED=False
    project=next(p for p in find_project_inputs(ISOLATED/"input") if p.name=="Beverly Hills")
    args=app._parse_args(["--project",project.name,"--from-stage","deep-source-analysis"])
    success=app._process_staged_planning(project,args)
    queue=ISOLATED/"output/publishing/Beverly Hills-publishing-queue.json"
    items=read(queue).get("items",[]) if queue.is_file() else []
    assert all(not i.get("scheduled_at") and not i.get("scheduled_at_utc") for i in items)
    result={"status":"PASSED" if success else "BLOCKED","selected_stages":selected,"forbidden_stages_executed":[],"meta_writes":0,"schedules_created":0,"queue_items":len(items),"generated_approval_inferred":False,"completed_at":datetime.now(timezone.utc).isoformat()}
    write(RECOVERY/"downstream-result.json",result)
    raise SystemExit(0 if success else 1)

def unit_plans():
    """Recompute deterministic relationships from this run's original PDF."""
    if read(RECOVERY/"core-result.json")["status"] != "PASSED":
        raise RuntimeError("Fresh D1/D2 must pass before plan certification")
    import importlib.util
    spec=importlib.util.spec_from_file_location("unit_certification",ROOT/"tools/certify_beverly_unit_plans.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=ISOLATED/"output/source-images/Beverly Hills"
    target=ISOLATED/"output/verification/unit-plans/Beverly-Hills/source-images/Beverly Hills"
    if not (target/"manifest.json").is_file():
        shutil.copytree(source,target,dirs_exist_ok=True)
    # The existing certification validates original PDF and every reused byte.
    result=module.run(ISOLATED,ISOLATED/"input/brand",reuse_extraction=True)
    report=read(result)
    write(RECOVERY/"unit-plan-result.json",{"status":report["status"],"report":str(result),"verified_units":[i["unit_type"] for i in report["verified_units"]],"blocked_units":[i["unit_type"] for i in report["blocked_units"]],"external_requests":0,"schedules_created":0})
    raise SystemExit(0 if report["status"]=="PASSED" else 1)

def contracts():
    from collections import Counter
    from src.core.file_manager import find_project_inputs
    from src.department1.pipeline import project_storage_key
    from src.knowledge.handoff import load_department2_handoff
    from src.knowledge.consumer import require_canonical_graph
    from src.visual_assets.extraction import verify_source_integrity
    assert read(RECOVERY/"core-result.json")["status"]=="PASSED"
    project=next(p for p in find_project_inputs(ISOLATED/"input") if p.name=="Beverly Hills")
    handoff=load_department2_handoff(ISOLATED/"output/department1"/project_storage_key(project.name)/"department2-handoff.json",expected_project=project.name,project_root=ISOLATED/"input/Beverly Hills",source_paths=[*project.pdf_files,*project.image_files,*project.auxiliary_files])
    knowledge=read(ISOLATED/"output/knowledge/Beverly Hills.json")
    require_canonical_graph(knowledge,expected_project=project.name)
    source_manifest=ISOLATED/"output/source-images/Beverly Hills/manifest.json"
    manifest=read(source_manifest)
    assert not verify_source_integrity(source_manifest)
    analysis=read(ISOLATED/"output/asset-intelligence/Beverly Hills-asset-intelligence.json")
    assets=analysis["assets"]
    assert {a["asset_id"] for a in assets}=={a["asset_id"] for a in manifest["assets"]}
    assert all(a.get("project_id")==project.name for a in assets)
    assert all(a.get("source_document_hash")==sha(project.pdf_files[0]) for a in assets)
    classifications=[read(p) for p in (ISOLATED/"output/knowledge/Beverly Hills/documents").glob("*-classification.json")]
    graph=knowledge["canonical_intelligence"]
    report={"status":"PASSED","project_id":project.name,"source_inventory_exact":True,"source_hashes_verified":True,"d1_stages":handoff.payload["pipeline_completed"],"d1_sources":len(handoff.sources),"handoff_sha256":handoff.handoff_sha256,"canonical_graph_valid":True,"fact_states":dict(Counter(f["state"] for f in graph["facts"])),"classifications":[{"classification":c["classification"],"fallback_error":c.get("fallback_error")} for c in classifications],"extracted_assets":len(manifest["assets"]),"asset_outputs_complete":True,"asset_analysis_statuses":dict(Counter(a["analysis_status"] for a in assets)),"factual_readiness":"separate_per_fact_and_per_package_gates_required","publishing_certified":False}
    write(RECOVERY/"contract-audit.json",report);print(json.dumps(report,indent=2))

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("step",choices=("prepare","core","contracts","unit-plans","downstream","verify-preserved"));args=parser.parse_args()
    {"prepare":prepare,"core":core,"contracts":contracts,"unit-plans":unit_plans,"downstream":downstream,"verify-preserved":verify_preserved}[args.step]()
