"""Typed persistent contracts for research data isolated from project outputs."""
from __future__ import annotations
from dataclasses import asdict,dataclass,field
from typing import Any

SOURCE_TIERS={"TIER_A","TIER_B","TIER_C","REJECTED"};LIFECYCLE={"OBSERVED","CANDIDATE","VALIDATED","ACTIVE","REJECTED","DEPRECATED","MERGED"}
@dataclass(frozen=True)
class ResearchObjective:
    objective:str;categories:list[str];platforms:list[str]=field(default_factory=list);industries:list[str]=field(default_factory=list);limit:int=20
@dataclass
class SourceQualification:
    source_domain:str;source_type:str;source_category:str;publisher_or_creator:str;published_date:str|None;observed_date:str
    professional_quality:int;relevance:int;originality:int;commercial_context:str;platform:str;trust_level:str;quality_class:str;accepted:bool;reasons:list[str]
@dataclass
class Observation:
    observation_id:str;source_reference:str;source_platform:str;source_domain:str;source_date:str|None;observed_date:str;category:str;content_type:str;industry:str;platform:str
    visual_structure:list[str];information_density:str;brand_presence:str;typography_character:list[str];image_behavior:list[str];story_structure:list[str]
    cta_behavior:list[str];sales_behavior:list[str];notable_strengths:list[str];notable_weaknesses:list[str];transferable_principles:list[str];potential_anti_patterns:list[str]
    source_confidence:float;observation_confidence:float;pattern_relevance_confidence:float;transferability_to_real_estate:int;real_estate_relevance:int
    content_signature:str;deduplication_status:str;external_facts_rejected:list[str];prompt_injection_detected:bool;raw_content_available_to_downstream:bool=False
    def to_dict(self)->dict[str,Any]:return asdict(self)
@dataclass
class PatternCandidate:
    candidate_id:str;name:str;category:str;creative_family:str;supporting_observation_ids:list[str];cross_source_count:int;source_diversity:int;platform_diversity:int
    quality_score:int;confidence:float;transferability_to_real_estate:int;real_estate_relevance:int;abstract_principles:list[str];evidence_requirements:list[str];restrictions:list[str]
    first_observed:str;last_observed:str;last_validated:str;trend_status:str;freshness_score:int;status:str;similarity_status:str;canonical_pattern_id:str|None=None
    def to_dict(self)->dict[str,Any]:return asdict(self)
