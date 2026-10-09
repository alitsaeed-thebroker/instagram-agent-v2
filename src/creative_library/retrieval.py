"""Context-first deterministic retrieval; patterns never supply project claims."""
from __future__ import annotations
from dataclasses import asdict
import hashlib,json,re
from pathlib import Path
from typing import Any
from .library import CreativeIntelligenceLibrary
from .schema import RetrievalContext

OPPORTUNITY_CATEGORY={"project_hero":"REAL_ESTATE_HERO","project_overview":"PROJECT_DISCOVERY","location_advantage":"LOCATION","location_map":"MAP","architecture_hero":"REAL_ESTATE_HERO","unit_layout":"UNIT_LAYOUT","layout_explainer":"UNIT_LAYOUT","unit_features":"UNIT","unit_comparison":"COMPARISON","interior_hero":"INTERIOR","amenity_overview":"AMENITY","payment_plan":"PAYMENT_PLAN","commercial_breakdown":"COMMERCIAL","investment_positioning":"INVESTMENT","project_faq":"FAQ","request_availability":"LEAD_GENERATION"}
TECHNICAL={"unit_layout","floor_plan","floorplan","masterplan","site_plan","technical_visual"}
COMMERCIAL={"PAYMENT_PLAN","PRICE","COMMERCIAL","INVESTMENT"}
RETRIEVAL_VERSION="1.0.0"

class PatternRetriever:
    def __init__(self,library:CreativeIntelligenceLibrary,cache_directory:Path|None=None):self.library=library;self.cache_directory=cache_directory
    def retrieve(self,context:RetrievalContext,*,limit:int=3)->dict[str,Any]:
        lib=self.library.load();key=self.cache_key(context,f"{lib['library_version']}:{self.library.fingerprint()}");cached=self._cached(key)
        if cached:return cached
        category=OPPORTUNITY_CATEGORY.get(context.opportunity_type,context.opportunity_type.upper());rows=[]
        for p in lib["patterns"]:
            if p["status"]!="ACTIVE":continue
            score,reasons=self._score(p,context,category)
            if score<45:continue
            rows.append({"pattern_id":p["pattern_id"],"pattern_version":p["pattern_version"],"name":p["name"],"category":p["category"],"creative_family":p["creative_family"],"applicability_score":score,"reason":reasons,"restrictions":p["restrictions"],"anti_patterns_to_avoid":p["anti_pattern_links"],"information_density":p["information_density"],"visual_principles":p["visual_principles"],"content_principles":p["content_principles"],"story_structure":p["story_structure"],"pattern_influence":p["pattern_influence"],"project_fact_contribution":[]})
        rows.sort(key=lambda x:(-x["applicability_score"],x["pattern_id"]));selected=rows[:max(0,limit)]
        anti_index={x["anti_pattern_id"]:x for x in lib["anti_patterns"]};anti=[]
        for pid in dict.fromkeys(x for row in selected for x in row["anti_patterns_to_avoid"]):
            if pid in anti_index:anti.append(anti_index[pid])
        result={"project_id":context.project_id,"library_version":lib["library_version"],"schema_version":lib["schema_version"],"retrieval_version":RETRIEVAL_VERSION,"retrieval_cache_key":key,"pattern_influence":"advisory","top_relevant_patterns":selected,"relevant_anti_patterns":anti,"pattern_ids_considered":[x["pattern_id"] for x in rows],"pattern_ids_selected":[x["pattern_id"] for x in selected],"pattern_ids_rejected":[x["pattern_id"] for x in rows[limit:]],"rejection_reason":"lower contextual applicability","factual_authority":"NONE","context":asdict(context)}
        self._store(key,result);return result
    def cache_key(self,c:RetrievalContext,version:str)->str:return hashlib.sha256(json.dumps({"library_version":version,"retrieval_version":RETRIEVAL_VERSION,"context":asdict(c)},sort_keys=True,separators=(",",":")).encode()).hexdigest()
    def _score(self,p,c,category):
        score=0;reasons=[];asset=_norm(c.asset_type);fits={_norm(x) for x in p["asset_fit"]}
        if p["category"]==category:score+=32;reasons.append("content objective match")
        elif category=="REAL_ESTATE_HERO" and p["category"] in {"PROJECT_LAUNCH","PROJECT_DISCOVERY"}:score+=18
        if asset in fits:score+=28;reasons.append("asset compatibility")
        elif c.asset_type=="text_only" and "text_only" in p["asset_fit"]:score+=25
        else:score-=30
        if c.platform in p["platform_fit"]:score+=15;reasons.append("platform fit")
        if c.brand_character and _norm(c.brand_character) in {_norm(p["creative_family"]),*map(_norm,p["tags"])}:score+=8;reasons.append("brand fit")
        if c.information_density and c.information_density==p["information_density"]:score+=7
        if c.audience_hypothesis and c.audience_hypothesis in p["audience_fit"]:score+=5
        score+=round(p["quality_score"]*.05);score+=3 if p["trend_status"] in {"EVERGREEN","CURRENT"} else 0
        if asset in TECHNICAL and p["category"] not in {"UNIT_LAYOUT","UNIT","COMPARISON","EDUCATIONAL","MAP"}:score-=45
        if p["category"] in COMMERCIAL and (c.evidence_strength<75 or c.commercial_freshness in {"STALE","EXPIRED"}):score-=60;reasons.append("commercial evidence gate")
        if p["category"]=="UNIT_LAYOUT" and c.relationship_status!="VERIFIED":score-=15;reasons.append("pattern may guide preservation but content remains blocked by plan relationship gate")
        if c.visual_strength<35 and "text_only" not in p["asset_fit"]:score-=25;reasons.append("weak visual support")
        return max(0,min(100,score)),reasons
    def _cached(self,key):
        if not self.cache_directory:return None
        p=self.cache_directory/f"{key}.json"
        try:return json.loads(p.read_text(encoding="utf-8"))
        except (OSError,ValueError):return None
    def _store(self,key,value):
        if not self.cache_directory:return
        self.cache_directory.mkdir(parents=True,exist_ok=True);(self.cache_directory/f"{key}.json").write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
def _norm(v):return re.sub(r"[^a-z0-9]+","_",str(v or "").casefold()).strip("_")
