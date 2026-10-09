"""Read-only Campaign Intelligence simulation. Never schedules or publishes."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from src.campaign_intelligence import CampaignIntelligenceEngine
from src.publishing.ledger import PublicationLedger,LedgerUnavailable

def main()->int:
    p=argparse.ArgumentParser();p.add_argument("project");p.add_argument("--root",type=Path,default=Path(__file__).resolve().parent);a=p.parse_args();root=a.root
    history=[]
    try:
        ledger=PublicationLedger(root);ledger._validate();history=ledger.records()
    except (LedgerUnavailable,OSError):pass
    engine=CampaignIntelligenceEngine(root)
    inventory=root/"output"/"visual-inventory"/f"{a.project}-visual-inventory.json"
    if not inventory.is_file():inventory=root/"output"/"inventory"/f"source-image-ranking-{a.project.replace(' ','-')}.json"
    state,decisions=engine.run(project_id=a.project,knowledge_path=root/"output"/"knowledge"/f"{a.project}.json",reci_path=root/"output"/"creative-intelligence"/f"{a.project}-creative-opportunity-map.json",library_path=root/"data"/"creative-intelligence"/"library.json",performance_path=root/"data"/"performance-learning"/"creative-learning-profile.json",inventory_path=inventory,publication_history=history,simulation=True)
    contract=json.loads(decisions.read_text(encoding="utf-8"));print(json.dumps({"status":"SIMULATION_COMPLETE","state":str(state),"decisions":str(decisions),"next_best_content":(contract.get("next_best_content") or {}).get("content_angle"),"published":False,"scheduled":False},indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
