"""Generate and summarize the canonical RECI artifact for one local project."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.creative_intelligence import RealEstateCreativeIntelligence
from src.utils.config import PROJECT_ROOT


def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument("project");args=parser.parse_args()
    output=PROJECT_ROOT/"output";project=args.project
    knowledge=output/"knowledge"/f"{project}.json"
    evaluation=output/"reports"/f"{project}-evaluation.json"
    inventory=output/"visual-inventory"/f"{project}-visual-inventory.json"
    if not inventory.is_file():inventory=output/"inventory"/f"source-image-ranking-{project.replace(' ','-')}.json"
    plan=output/"plan-intelligence"/f"{project}-plan-intelligence.json"
    if not knowledge.is_file():raise SystemExit(f"Missing authoritative knowledge: {knowledge}")
    path=RealEstateCreativeIntelligence().run(knowledge,evaluation if evaluation.is_file() else None,inventory if inventory.is_file() else None,plan if plan.is_file() else None)
    payload=json.loads(path.read_text(encoding="utf-8"));metrics=payload["metrics"]
    print(json.dumps({"artifact":str(path),**metrics},indent=2,ensure_ascii=False))
    return 0


if __name__=="__main__":raise SystemExit(main())
