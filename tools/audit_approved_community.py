"""Read-only certification audit of the exact previously approved community carousel."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,hmac,json,sys
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.publishing.foundation import PublishingFoundation,final_publish_errors,_json_hash,_slides

def read(path):return json.loads(path.read_text(encoding="utf-8"))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run():
    recovery=ROOT/"output/recovery/20261009T193500Z"
    keys=read(ROOT/"deployment/cloudflare/.private-migration/cloud-keys.json")
    envelope=read(ROOT/"deployment/cloudflare/.private-migration/jobs/2026-10-09.json")
    signature=hmac.new(keys['PACKAGE_SIGNING_KEY'].encode(),envelope['payload'].encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature,envelope['signature']):raise ValueError("SIGNATURE_INVALID")
    job=json.loads(envelope['payload'])
    root=ROOT/"output/restarts/2026-10-08"
    foundation=PublishingFoundation("Beverly Hills",root)
    ctx=foundation._inputs()
    item=next(x for x in read(foundation.queue_path)['items'] if x.get('publication_identity')==job['publication_identity'])
    package=next(x for x in ctx['packages']['packages'] if x['package_id']==item['package_id'])
    errors=final_publish_errors(item,package,ctx)
    if _json_hash(package)!=job['certification']['package_hash']:errors.append("APPROVED_PACKAGE_HASH_MISMATCH")
    caption=package.get('master_caption') or package.get('caption')
    if caption['full_caption']!=job['caption']:errors.append("CAPTION_MISMATCH")
    assets={x['asset_id']:x for x in ctx['visual_assets']}
    evidence=[]
    for index,(slide,media,proof) in enumerate(zip(_slides(package),job['media'],job['certification']['source_evidence']),1):
        source=assets[media['source_asset_id']]
        local=sha(slide['image_path'])
        if local!=slide['image_hash'] or local!=media['sha256']:errors.append("MEDIA_HASH_MISMATCH")
        if slide['source_asset_ids']!=[source['asset_id']]:errors.append("SOURCE_ORDER_MISMATCH")
        for key in ('asset_id','project_id','source_hash','source_document_hash','source_page'):
            if source.get(key)!=proof.get(key):errors.append("SOURCE_CERTIFICATION_MISMATCH")
        if sha(source['source_path'])!=proof['source_hash'] or sha(source['source_document_path'])!=proof['source_document_hash']:errors.append("SOURCE_BYTES_CHANGED")
        with urlopen(Request(media['url'],headers={'User-Agent':'InstagramAgentRecoveryAudit/1.0'}),timeout=25) as response:
            remote=hashlib.sha256(response.read()).hexdigest()
            if not response.headers.get('Content-Type','').startswith('image/') or remote!=local:errors.append("HOSTED_MEDIA_CHANGED")
        evidence.append({'slide':index,'source_asset_id':source['asset_id'],'source_page':source['source_page'],'output_sha256':local,'hosted_sha256':remote,'source_hash_verified':True,'document_hash_verified':True})
    if len(evidence)!=3 or len(job['media'])!=3 or len(package['slides'])!=3:errors.append("WRONG_CAROUSEL_COUNT")
    base='https://instagram-agent-publisher.instagram-agent-cloud.workers.dev'
    def cloud(path,body):
        request=Request(base+path,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+keys['ADMIN_KEY'],'Content-Type':'application/json','User-Agent':'InstagramAgentRecoveryAudit/1.0','Accept':'application/json'},method='POST')
        with urlopen(request,timeout=25) as response:return json.load(response)
    before=cloud('/publication-status',{})
    preview=cloud('/preview',{'day':'2026-10-09'})
    after=cloud('/publication-status',{})
    if before!=after:errors.append("CLOUD_LEDGER_CHANGED_DURING_DRY_RUN")
    if preview.get('status')!='DRY_RUN_PASSED' or preview.get('meta_writes')!=0:errors.append("CLOUD_DRY_RUN_FAILED")
    proof=preview.get('validated_job')
    expected_proof={'signature_verified':True,'publication_identity':job['publication_identity'],'project_id':job['project_id'],'campaign_id':job['campaign_id'],'scheduled_at':job['scheduled_at'],'package_sha256':job['certification']['package_hash'],'caption_sha256':hashlib.sha256(job['caption'].encode()).hexdigest(),'ordered_media_sha256':[m['sha256'] for m in job['media']],'ordered_source_asset_ids':[m['source_asset_id'] for m in job['media']]}
    identity_verified=proof==expected_proof
    if proof is not None and not identity_verified:errors.append("REMOTE_JOB_IDENTITY_MISMATCH")
    report={'status':'PASSED' if not errors else 'BLOCKED','publication_identity':job['publication_identity'],'package_id':package['package_id'],'approved_package_sha256':job['certification']['package_hash'],'caption_sha256':hashlib.sha256(job['caption'].encode()).hexdigest(),'slide_count':len(evidence),'evidence':evidence,'final_gate_errors':errors,'cloud_dry_run':preview,'cloud_ledger_unchanged':before==after,'cloud_receipt_present':any(r['publication_identity']==job['publication_identity'] for r in after['records']),'meta_writes':0,'schedules_created':0,'publication_certified':False,'checked_at':datetime.now(timezone.utc).isoformat()}
    report.update({'validation_scope':'local signed approved package, source bytes and hosted media; cloud day-level preview','remote_cloud_job_identity_verified':identity_verified,'remaining_cloud_blockers':[] if identity_verified else ['Remote preview does not attest the exact private job; management access or the repaired preview endpoint is required']})
    path=recovery/'exact-community-dry-run.json';path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if not errors else 1

if __name__=='__main__':raise SystemExit(run())
