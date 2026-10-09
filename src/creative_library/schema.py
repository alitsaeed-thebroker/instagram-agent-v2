"""Typed contracts for reusable creative principles, never project facts."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

PATTERN_STATUSES={"DRAFT","REVIEW_REQUIRED","ACTIVE","DEPRECATED","REJECTED"}
TREND_STATUSES={"EVERGREEN","CURRENT","EMERGING","DECLINING","EXPERIMENTAL"}
DENSITIES={"very_low","low","medium","high","technical"}
SEVERITIES={"LOW","MEDIUM","HIGH","CRITICAL"}

@dataclass
class Pattern:
    pattern_id:str;pattern_version:int;name:str;category:str;creative_family:str;description:str
    source_domain:str;source_type:str;source_reference:str;source_date:str|None;observed_date:str
    freshness:str;quality_score:int;confidence:float;applicability:dict[str,list[str]]
    visual_principles:list[str];content_principles:list[str];sales_principles:list[str]
    platform_fit:list[str];asset_fit:list[str];audience_fit:list[str];information_density:str
    brand_behavior:str;typography_behavior:list[str];image_behavior:list[str]
    story_structure:list[str];conversion_behavior:list[str];strengths:list[str];weaknesses:list[str]
    evidence_requirements:dict[str,list[str]];restrictions:list[str];anti_pattern_links:list[str]
    tags:list[str];status:str;trend_status:str;quality_dimensions:dict[str,int]
    compatible_with:list[str]=field(default_factory=list);conflicts_with:list[str]=field(default_factory=list)
    performance_metadata:dict[str,Any]=field(default_factory=lambda:{"status":"NOT_IMPLEMENTED"})
    pattern_influence:str="advisory";source_provenance:dict[str,Any]=field(default_factory=dict)
    def to_dict(self)->dict[str,Any]:return asdict(self)

@dataclass
class AntiPattern:
    anti_pattern_id:str;name:str;description:str;risk_type:str;severity:str
    detection_signals:list[str];affected_content_types:list[str];corrective_principle:str
    examples_as_abstract_rules:list[str]
    def to_dict(self)->dict[str,Any]:return asdict(self)

@dataclass(frozen=True)
class RetrievalContext:
    project_id:str;opportunity_type:str;project_type:str="unknown";asset_type:str="text_only"
    platform:str="instagram_feed";audience_hypothesis:str="";information_density:str=""
    campaign_role:str="standalone";brand_character:str="";visual_strength:int=0
    commercial_strength:int=0;evidence_strength:int=0;relationship_status:str="VERIFIED"
    commercial_freshness:str="CURRENT_OR_NOT_TIME_SENSITIVE"
