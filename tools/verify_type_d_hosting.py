from pathlib import Path
import sys,json,hashlib,shutil
from urllib.request import urlopen,Request
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from dotenv import load_dotenv
load_dotenv(BASE/'.env')
from src.publishing.media_hosting import CloudflareR2MediaHost,run_media_hosting
from src.publishing.meta import MetaInstagramAdapter
from src.publishing.controlled import controlled_publish
ROOT=BASE/'output/verification/operational-readiness/type-d-dry-run'
shutil.copy2(BASE/'input/publishing/meta-config.json',ROOT/'input/publishing/meta-config.json')
host=CloudflareR2MediaHost(ROOT)
path,stats=run_media_hosting(ROOT,'Beverly Hills',host=host)
manifest=json.loads(path.read_text())
checks=[]
for row in manifest['records']:
    with urlopen(Request(row['public_url'],headers={'User-Agent':'InstagramAgentMediaHost/1.0'}),timeout=30) as response:
        data=response.read()
    actual=hashlib.sha256(data).hexdigest()
    checks.append({'local_path':row['local_path'],'public_url':row['public_url'],'sha256_matches':actual==row['local_sha256'],'bytes':len(data)})
if len(checks)!=2 or not all(r['sha256_matches'] for r in checks):
    raise RuntimeError('Hosted images do not exactly match both approved local slides')
adapter=MetaInstagramAdapter(ROOT)
queue=json.loads((ROOT/'output/publishing/Beverly Hills-publishing-queue.json').read_text())
queue['items']=[r for r in queue['items'] if r.get('status') not in {'superseded','cancelled'}]
if len(queue['items'])!=1:raise RuntimeError('Approval package must contain exactly one job')
result=controlled_publish(ROOT,'Beverly Hills',queue_item_id=queue['items'][0]['queue_item_id'],confirm=False,adapter=adapter,r2_host=host)
report={'hosting':stats,'images':checks,'controlled_preview':result,'meta_writes':0}
target=BASE/'output/verification/operational-readiness/type-d-final-readiness.json'
target.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'status':result['status'],'preview':result.get('preview'),'images':checks,'caption':result['package']['master_caption']['full_caption'],'report':str(target)},indent=2))
