"""Read-only cloud access probes; no credentials or payload text in reports."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,hmac,json,os,sys
from urllib.request import Request,urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError

def run():
    load_dotenv(ROOT/".env")
    keys=json.loads((ROOT/"deployment/cloudflare/.private-migration/cloud-keys.json").read_text())
    report={"checked_at":datetime.now(timezone.utc).isoformat(),"management_token_present":bool(os.getenv("CLOUDFLARE_API_TOKEN")),"private_objects":[],"diagnostics_endpoint":None,"writes":0}
    client=boto3.client("s3",endpoint_url=os.environ["R2_ENDPOINT_URL"],aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],region_name="auto")
    for day in ("2026-10-09","2026-10-10","2026-10-11"):
        entry={"key":"jobs/"+day+".json"}
        try:
            raw=client.get_object(Bucket="instagram-agent-private-packages",Key=entry["key"])["Body"].read()
            envelope=json.loads(raw)
            signature=hmac.new(keys["PACKAGE_SIGNING_KEY"].encode(),envelope["payload"].encode(),hashlib.sha256).hexdigest()
            valid=hmac.compare_digest(signature,envelope["signature"])
            entry.update(status="READ",object_sha256=hashlib.sha256(raw).hexdigest(),signature_valid=valid)
            if valid:
                job=json.loads(envelope["payload"])
                entry.update({name:job.get(name) for name in ("project_id","campaign_id","publication_identity","scheduled_at","valid_until")})
        except ClientError as exc:entry["status"]=exc.response.get("Error",{}).get("Code","CLIENT_ERROR")
        except Exception as exc:entry["status"]=type(exc).__name__
        report["private_objects"].append(entry)
    request=Request("https://instagram-agent-publisher.instagram-agent-cloud.workers.dev/schedule-status",data=b"{}",headers={"Authorization":"Bearer "+keys["ADMIN_KEY"],"Content-Type":"application/json","User-Agent":"InstagramAgentRecoveryAudit/1.0","Accept":"application/json"},method="POST")
    try:
        with urlopen(request,timeout=25) as response:report["diagnostics_endpoint"]={"http_status":response.status,"result":json.load(response)}
    except HTTPError as exc:report["diagnostics_endpoint"]={"http_status":exc.code}
    path=ROOT/"output/recovery/20261009T193500Z/cloud-access.json"
    path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))

if __name__=="__main__":run()
