"""Finite Baghdad morning schedule. Existing Department 5 owns publication truth."""
import json,os,time,sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.publishing.worker import run_worker

def due(now,dates,completed):
    local=now.astimezone(ZoneInfo("Asia/Baghdad"))
    day=local.date().isoformat()
    return day in dates and day not in completed and local.hour==9 and local.minute<10

def cycle(root,now,dates,enabled,publisher=run_worker):
    if not enabled:return {"classification":"CLOUD_PAUSED"}
    stamp=root/"state/publishing/cloud-schedule-runs.json"
    completed=json.loads(stamp.read_text()).get("completed_dates",[]) if stamp.exists() else []
    if not due(now,dates,completed):return {"classification":"NOT_DUE"}
    # Never create a fresh ledger on deployment: migration must preserve live truth.
    if not (root/"state/publishing/publication-ledger.sqlite3").is_file():
        return {"classification":"LIVE_LEDGER_MIGRATION_REQUIRED"}
    result=publisher(root)
    if result.get("published"):
        completed.append(now.astimezone(ZoneInfo("Asia/Baghdad")).date().isoformat())
        stamp.parent.mkdir(parents=True,exist_ok=True)
        temp=stamp.with_suffix(".tmp");temp.write_text(json.dumps({"completed_dates":completed}));temp.replace(stamp)
    return result

def main():
    root=Path(os.environ.get("AGENT_ROOT","/data"))
    dates=set(filter(None,os.environ.get("AGENT_PUBLISH_DATES","").split(",")))
    if not dates:raise SystemExit("AGENT_PUBLISH_DATES is required; no default live schedule")
    last=None
    while True:
        now=datetime.now(ZoneInfo("Asia/Baghdad"))
        if now.date().isoformat()>max(dates):return
        result=cycle(root,now,dates,os.environ.get("AGENT_LIVE_ENABLED","").lower()=="true")
        # Publish only safe worker fields, never raw credentials or API responses.
        summary={k:result[k] for k in ("classification","published","exit_code") if k in result}
        if summary!=last:print(json.dumps(summary),flush=True);last=summary
        time.sleep(30)

if __name__=="__main__":main()
