"""Run the isolated Phase 6 certification harness."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from src.simulation import AutonomousCampaignSimulation

def main()->int:
    p=argparse.ArgumentParser();p.add_argument("project");p.add_argument("--root",type=Path,default=Path(__file__).resolve().parent);a=p.parse_args();root=a.root;slug=a.project.replace(" ","-")
    inventory=root/"output"/"visual-inventory"/f"{a.project}-visual-inventory.json"
    if not inventory.is_file():inventory=root/"output"/"inventory"/f"source-image-ranking-{slug}.json"
    report=AutonomousCampaignSimulation(root).run(a.project,knowledge_path=root/"output"/"knowledge"/f"{a.project}.json",reci_path=root/"output"/"creative-intelligence"/f"{a.project}-creative-opportunity-map.json",library_path=root/"data"/"creative-intelligence"/"library.json",inventory_path=inventory,performance_path=root/"data"/"performance-learning"/"creative-learning-profile.json")
    value=json.loads(report.read_text(encoding="utf-8"));print(json.dumps({"report":str(report),"simulation_id":value["simulation_identity"]["simulation_id"],"readiness":value["autonomous_readiness_score"],"verdict":value["final_verdict"],"live_publications":0},indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
