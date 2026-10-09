"""Durable, project-isolated history of eligible visual directions."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


class VisualDirectionHistory:
    def __init__(self, project: str, root: Path) -> None:
        self.project,self.root=project,root
        self.path=root/"output"/"visual-history"/f"{project}-visual-direction-history.json"

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():return {"project_id":self.project,"history_version":"1.0.0","records":[]}
        payload=json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("project_id")!=self.project:raise ValueError("Cross-project visual history is forbidden")
        return payload

    def recent_context(self, *, limit: int = 12) -> list[dict[str, Any]]:
        records=self.load().get("records",[])[-limit:]
        return [{"composition":{"strategy":x.get("composition_strategy"),"visual_balance":x.get("visual_balance")},
                 "brand_logo":{"region":x.get("logo_region"),"prominence":x.get("logo_prominence")},
                 "project_identity":{"region":x.get("project_identity_region")},"headline":{"region":x.get("headline_region")},
                 "source_image":{"crop_mode":x.get("crop_mode")},"graphics":{"overlay":x.get("overlay_type")}}
                for x in records if x.get("approval_status") in {"approved","released"}]

    def record_released(self, contracts: list[dict[str, Any]], released_contract_ids: set[str], *, release_id: str) -> Path:
        payload=self.load();records=payload.get("records",[]);known={x.get("contract_hash") for x in records}
        for contract in contracts:
            if contract.get("contract_id") not in released_contract_ids or contract.get("contract_hash") in known:continue
            logo=contract["brand_logo"];project=contract["project_identity"];headline=contract["headline"]
            records.append({"project_id":self.project,"content_id":contract["content_id"],"asset_id":contract["asset_id"],
                "contract_id":contract["contract_id"],"contract_hash":contract["contract_hash"],"composition_strategy":contract["composition"]["strategy"],
                "logo_region":_region(logo),"logo_prominence":logo["prominence"],"project_identity_region":_region(project),"headline_region":_region(headline),
                "crop_mode":contract["source_image"]["crop_mode"],"information_zone_type":_information_zone(contract),"overlay_type":contract["graphics"]["overlay"],
                "visual_balance":contract["composition"]["visual_balance"],"approval_status":"released","release_id":release_id,"recorded_at":_now()})
        payload.update(records=records,updated_at=_now());self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");return self.path


def _region(item: dict[str, Any]) -> str:
    x,y=item.get("x",0),item.get("y",0);return ("left" if x<540 else "right")+"_"+("upper" if y<675 else "lower")
def _information_zone(contract: dict[str, Any]) -> str:
    for name in ("rail","header","footer"):
        if contract["graphics"].get(name):return name
    return "overlay"
def _now() -> str:return datetime.now(timezone.utc).isoformat()
