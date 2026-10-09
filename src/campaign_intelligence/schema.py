"""Machine-readable Campaign Intelligence contracts."""
from __future__ import annotations
from dataclasses import asdict,dataclass,field
from typing import Any

CAMPAIGN_STAGES=("DISCOVERY","AWARENESS","UNDERSTANDING","DESIRE","EVALUATION","COMMERCIAL","CONVERSION","MAINTENANCE")
DECISION_STATUSES={"APPROVED","DEFERRED","BLOCKED","REVIEW_REQUIRED","EXHAUSTED"}
CAMPAIGN_ROLES={"DISCOVER","EDUCATE","INSPIRE","PROVE","EXPLAIN","COMPARE","ANSWER","SELL","CONVERT","REINFORCE"}

@dataclass
class CampaignState:
    project_id:str;campaign_state_version:str;campaign_stage:str;updated_at:str
    campaign_threads:list[dict[str,Any]]=field(default_factory=list)
    coverage_matrix:list[dict[str,Any]]=field(default_factory=list)
    gaps:list[dict[str,Any]]=field(default_factory=list)
    memory_summary:dict[str,Any]=field(default_factory=dict)
    metrics:dict[str,Any]=field(default_factory=dict)
    input_fingerprint:str=""
    def to_dict(self)->dict[str,Any]:return asdict(self)

@dataclass
class CampaignDecision:
    decision_id:str;project_id:str;campaign_id:str;campaign_stage:str;campaign_role:str;objective:str;reason:str
    reci_opportunity_id:str;supporting_fact_ids:list[str];candidate_asset_ids:list[str];recommended_platform:str
    recommended_format:str;audience_hypothesis:dict[str,Any];buyer_value:list[str];content_angle:str
    commercial_intent:str;cta_intent:str;cta_intensity:str;creative_pattern_candidates:list[dict[str,Any]]
    restrictions:list[str];blocked_claims:list[str];history_context:dict[str,Any];performance_context:dict[str,Any]
    priority:int;confidence:int;status:str;decision_timestamp:str;input_versions:dict[str,Any]
    why_now:str="";alternatives_considered:list[dict[str,Any]]=field(default_factory=list)
    sequence_dependency:str="NONE";planning_horizon:str="future_candidates";exploration_mode:str="BALANCED"
    score_breakdown:dict[str,int]=field(default_factory=dict);contract_hash:str=""
    def to_dict(self)->dict[str,Any]:return asdict(self)
