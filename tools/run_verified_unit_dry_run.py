"""Run real render, QA, release, package and publishing gates without Meta writes."""
from pathlib import Path
import json,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.brand_kit import ensure_brand_analysis
from tools.prepare_verified_unit_drafts import content_idea
from src.branding import BrandComposer
from src.hardening import HardeningPipeline
from src.post_package import PostPackagePipeline
from src.social_review import SocialContentReview
from src.publishing.foundation import PublishingFoundation,final_publish_errors
from src.publishing.eligibility import select_next_eligible_publication
from src.publishing.ledger import PublicationLedger
from src.creative.visual_direction import contract_id,contract_integrity_hash
from src.execution.lineage import attach_lineage,canonical_graph_fingerprint
from src.simulation.production_certification import Department4ProductionCertification
from datetime import datetime,timezone

PROJECT='Beverly Hills'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def copy(source,target):target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)

def run():
    root=ROOT/'output/verification/operational-readiness/type-d-dry-run'
    root.mkdir(parents=True,exist_ok=True)
    shutil.copytree(ROOT/'input/brand',root/'input/brand',dirs_exist_ok=True)
    ensure_brand_analysis(root)
    for name in ('knowledge/Beverly Hills.json','plan-intelligence/Beverly Hills-plan-intelligence.json',
                 'asset-intelligence/Beverly Hills-asset-intelligence.json','visual-inventory/Beverly Hills-visual-inventory.json'):
        copy(ROOT/'output'/name,root/'output'/name)
    copy(ROOT/'input/publishing/publishing-config.json',root/'input/publishing/publishing-config.json')
    knowledge=read(root/'output/knowledge/Beverly Hills.json');fp=canonical_graph_fingerprint(knowledge)
    records=read(root/'output/plan-intelligence/Beverly Hills-plan-intelligence.json')['assets']
    records=[r for r in records if r.get('unit_identity',{}).get('unit_type')=='Type D' and r.get('marketing_eligible')]
    if len(records)!=2:raise ValueError('Exactly two canonical verified Type D floor plans are required')
    contracts=read(ROOT/'output/production/unit-plans/Beverly-Hills/contracts/Type-D.json')
    for c in contracts:
        c.update(production_item_id='verified-'+c['asset_id'],campaign_id='verified-Type-D',content_idea_id='verified-Type-D')
        c['brand_logo']['asset']=str(root/'input/brand/logos/domus logo.png')
        c['publication_type']='carousel';c['contract_id']=contract_id(c);c['contract_hash']=contract_integrity_hash(c)
    write(root/'output/visual-directions/Beverly Hills-visual-direction-contracts.json',
          {'project_id':PROJECT,'authority':'visual-art-director','contract_version':contracts[0]['contract_version'],'contracts':contracts})
    idea={'content_idea_id':'verified-Type-D','title':'Type D complete villa layout',
          'selected_source_asset_ids':[r['asset_id'] for r in records],'source_support_status':'fully_supported',
          'selected_format':'carousel','planned_publication':{'publication_type':'carousel'}}
    idea.update(public_copy=content_idea(records).public_copy, canonical_relationship_ids=[r['unit_plan_relationship']['relationship_id'] for r in records])
    content=attach_lineage({'project_id':PROJECT,'content_ideas':[idea],'allowed_channels':['instagram']},
                           stage='department3-content-plan',canonical_fingerprint=fp)
    write(root/'output/content/Beverly Hills-content-plan.json',content)
    write(root/'output/strategy/Beverly Hills-strategy.json',{'project_id':PROJECT})
    write(root/'output/campaigns/Beverly Hills-campaign-plan.json',{'project_id':PROJECT,'campaigns':[{'campaign_id':'verified-Type-D'}]})
    write(root/'output/visual-opportunities/Beverly Hills-visual-opportunities.json',{'project_id':PROJECT,'opportunities':[]})
    Department4ProductionCertification(ROOT)._execute_unbranded(PROJECT,root,contracts)
    composer=BrandComposer(PROJECT,root);composer.compose(force=True);composer.output_qa(force=True);composer.qa(force=True)
    hard=HardeningPipeline(PROJECT,root);hard.creative_qa(force=True);hard.provenance_audit(force=True);hard.quality_report(force=True)
    release=hard.release(force=False)
    pipeline=PostPackagePipeline(PROJECT,root,languages=('en',))
    for method in ('groups','captions','hashtags','alt_text','build','qa'):getattr(pipeline,method)()
    SocialContentReview(PROJECT,root).render()
    history=read(ROOT/'output/publishing/Beverly Hills-publication-manifest.json')
    ledger=PublicationLedger(root);ledger.initialize(fresh=False,confirmed_receipts=history.get('real_receipts',[]))
    write(root/'output/publishing/Beverly Hills-publication-manifest.json',history)
    publication=PublishingFoundation(PROJECT,root)
    publication.queue();publication.schedule();publication.preflight()
    ctx=publication._inputs();queue=read(publication.queue_path)
    packages={p['package_id']:p for p in ctx['packages']['packages']}
    checks=[]
    for item in queue['items']:
        if item.get('status') in {'superseded','cancelled'}:continue
        package=packages[item['package_id']]
        checks.append({'queue_item_id':item['queue_item_id'],'package_id':item['package_id'],'package_type':package['package_type'],
                       'slide_count':len(package.get('slides',[])), 'errors':final_publish_errors(item,package,ctx),
                       'caption':(package.get('master_caption') or package.get('caption'))['full_caption']})
    receipts=[{**row,'status':'published','published_at':row.get('publication_timestamp')} for row in ledger.records() if row['state']=='CONFIRMED_PUBLISHED']
    eligibility=select_next_eligible_publication(queue,receipts,now=datetime.now(timezone.utc),config=publication._config())
    passed=len(checks)==1 and checks[0]['package_type']=='carousel' and checks[0]['slide_count']==2 and not checks[0]['errors']
    report={'project_id':PROJECT,'unit_type':'Type D','status':'PASSED' if passed else 'BLOCKED','root':str(root),
            'release':str(release),'checks':checks,'eligibility':eligibility,'live_ledger_modified':False,'meta_writes':0,
            'scope':'Actual local render/QA/release/package/social-review/queue/preflight/final gate; live credential and hosted-media readiness remain separate.'}
    write(ROOT/'output/verification/operational-readiness/type-d-dry-run-report.json',report)
    print(json.dumps(report,indent=2));return report

if __name__=='__main__':run()
