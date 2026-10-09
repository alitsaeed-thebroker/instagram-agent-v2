"""Run read-only-input performance learning; this command never publishes."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from src.performance import PerformanceLearningEngine

def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument("project");parser.add_argument("--input",type=Path);parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args();payload={"publications":[]}
    if args.input and args.input.is_file():payload=json.loads(args.input.read_text(encoding="utf-8"))
    review,profile=PerformanceLearningEngine(args.root).write(payload.get("publications",[]),args.project)
    print(json.dumps({"status":"COLD_START" if not payload.get("publications") else "ANALYZED","review":str(review),"profile":str(profile),"published":False},indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
