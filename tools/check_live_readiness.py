"""Restore approved inputs and check live services without publishing."""
from pathlib import Path
from datetime import datetime,timezone
import json,shutil,sys,sqlite3
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.brand_kit import approved_config_hash,run_brand_readiness_validator,ensure_brand_analysis
from src.publishing.ledger import PublicationLedger
from src.publishing.meta import MetaInstagramAdapter
from src.publishing.media_hosting import CloudflareR2MediaHost
from src.publishing.windows_scheduler import scheduler_status
from src.publishing.worker import WorkerState
from src.publishing.controlled import controlled_publish
from src.publishing.foundation import final_publish_errors,PublishingFoundation

def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')

def run():
    old=Path('C:/Users/alits/instagram-agent')
    report_root=ROOT/'output/verification/operational-readiness'
    report_root.mkdir(parents=True,exist_ok=True)
    cert=read(ROOT/'output/verification/unit-plans/Beverly-Hills/certification-report.json')
    config=read(old/'input/brand/brand-config.json')
    if approved_config_hash(config)!=cert['brand_snapshot']['approved_config_hash']:
        raise ValueError('Original brand configuration no longer matches approved certification')
    shutil.copytree(old/'input/brand',ROOT/'input/brand',dirs_exist_ok=True)
    # Stop local recurrence before restoring any publishing jobs/configuration.
    WorkerState(ROOT).set_enabled(False)
    restored=[]
    for name in ('publishing-config.json','meta-config.json'):
        source=old/'input/publishing'/name;destination=ROOT/'input/publishing'/name
        value=read(source)
        if name=='publishing-config.json':value.setdefault('worker',{})['enabled']=False
        else:value['enabled']=False;value['allow_immediate_publish']=False
        write(destination,value);restored.append(str(destination))
    ledger=PublicationLedger(ROOT);ledger._validate()
    source=old/'output/publishing/Beverly Hills-publication-manifest.json'
    history=read(source)
    if history.get('project_id')!='Beverly Hills':raise ValueError('Publication history project mismatch')
    ledger.migrate_receipts(history.get('real_receipts',[]))
    destination=ROOT/'output/publishing/Beverly Hills-publication-manifest.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    if not destination.exists():shutil.copy2(source,destination)
    ensure_brand_analysis(ROOT)
    brand=run_brand_readiness_validator(ROOT).report
    adapter=MetaInstagramAdapter(ROOT);adapter.client.timeout=10
    account=adapter.validate_credentials(persist=False)
    safe_account={key:account.get(key) for key in ('status','authentication_mode','instagram_account_id','instagram_username',
        'credentials_valid','token_valid','account_match','missing_permissions','permissions')}
    host=CloudflareR2MediaHost(ROOT)
    if host.configured:
        try:
            import boto3
            from botocore.config import Config
            host._client=boto3.client('s3',endpoint_url=host.endpoint,aws_access_key_id=host.env['R2_ACCESS_KEY_ID'],
                aws_secret_access_key=host.env['R2_SECRET_ACCESS_KEY'],region_name='auto',
                config=Config(connect_timeout=8,read_timeout=8,retries={'max_attempts':1}))
        except ImportError:pass
    r2=host.status()
    try:
        schedule=scheduler_status(ROOT)
        schedule['configured_for_this_repository']=bool(schedule.get('installed') and str(ROOT/'app.py').casefold() in str(schedule.get('configured_command','')).casefold())
        schedule.pop('configured_command',None)
    except Exception as error:schedule={'status':'unavailable','error_type':type(error).__name__}
    readiness={'project_id':'Beverly Hills','created_at':datetime.now(timezone.utc).isoformat(),
        'restored_configs':restored,'brand_status':brand.get('readiness_status'),'brand_report':brand,
        'ledger':ledger.status(),'account':safe_account,'r2':r2,'scheduler':schedule,
        'unattended_publishing_enabled':False,'real_publications':0}
    write(report_root/'live-readiness.json',readiness)
    print(json.dumps({k:readiness[k] for k in ('brand_status','account','r2','scheduler')},indent=2))
    return readiness

if __name__=='__main__':run()
