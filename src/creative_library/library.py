"""Persistent library management, admission QA, deduplication, and version history."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timezone
import hashlib,json,re
from pathlib import Path
from typing import Any
from .schema import DENSITIES,PATTERN_STATUSES,SEVERITIES,TREND_STATUSES
from .seeds import anti_patterns,seed_patterns

SCHEMA_VERSION="1.0.0";MINIMUM_ACTIVE_QUALITY=75
FORBIDDEN_FACT_KEYS={"project_name","developer","price","roi","yield","availability","payment_terms","unit_area","location_claim","amenity_claim"}
class LibraryValidationError(ValueError):pass

class CreativeIntelligenceLibrary:
    def __init__(self,path:Path):self.path=path
    @classmethod
    def default(cls,root:Path)->"CreativeIntelligenceLibrary":return cls(root/"data"/"creative-intelligence"/"library.json")
    def initialize(self)->dict[str,Any]:
        if self.path.is_file():return self.load()
        payload=self._payload(seed_patterns(),anti_patterns(),"1.0.0")
        self._write(payload);return payload
    def load(self)->dict[str,Any]:
        try:value=json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError,ValueError) as e:raise LibraryValidationError(f"Invalid creative library: {e}") from e
        self.validate(value);return value
    def validate(self,value:dict[str,Any])->None:
        required={"library_version","schema_version","updated_at","patterns","anti_patterns","metrics"}
        if not isinstance(value,dict) or required-set(value):raise LibraryValidationError("Library schema is incomplete")
        ids=set();anti_ids={x.get("anti_pattern_id") for x in value.get("anti_patterns",[])}
        for anti in value.get("anti_patterns",[]):
            if anti.get("severity") not in SEVERITIES:raise LibraryValidationError("Invalid anti-pattern severity")
        for p in value.get("patterns",[]):
            needed={"pattern_id","pattern_version","name","category","creative_family","description","source_provenance","quality_score","applicability","visual_principles","content_principles","platform_fit","asset_fit","information_density","evidence_requirements","restrictions","anti_pattern_links","status","trend_status","quality_dimensions","pattern_influence"}
            if needed-set(p):raise LibraryValidationError(f"Pattern schema incomplete: {p.get('pattern_id')}")
            if p["pattern_id"] in ids:raise LibraryValidationError("Duplicate canonical pattern_id")
            ids.add(p["pattern_id"])
            if p["status"] not in PATTERN_STATUSES or p["trend_status"] not in TREND_STATUSES or p["information_density"] not in DENSITIES:raise LibraryValidationError(f"Invalid taxonomy: {p['pattern_id']}")
            if p["status"]=="ACTIVE" and (p["quality_score"]<MINIMUM_ACTIVE_QUALITY or not p["source_provenance"]):raise LibraryValidationError(f"Pattern fails ACTIVE admission: {p['pattern_id']}")
            if set(p["anti_pattern_links"])-anti_ids:raise LibraryValidationError(f"Unknown anti-pattern link: {p['pattern_id']}")
            serialized=json.dumps(p,ensure_ascii=False).casefold()
            if any(f'"{key}"' in serialized for key in FORBIDDEN_FACT_KEYS):raise LibraryValidationError(f"Pattern contains project-fact field: {p['pattern_id']}")
            if any(x in serialized for x in ("logo_x","logo_y","font_size","crop_coordinates")):raise LibraryValidationError(f"Pattern contains executable geometry: {p['pattern_id']}")
    def classify_similarity(self,a:dict[str,Any],b:dict[str,Any])->str:
        if a.get("pattern_id")==b.get("pattern_id"):return "duplicate"
        tokens=lambda p:set(re.findall(r"[a-z0-9]+"," ".join(map(str,[p.get("name"),p.get("category"),p.get("creative_family"),*(p.get("asset_fit") or [])])).casefold()))
        aa,bb=tokens(a),tokens(b);score=len(aa&bb)/max(1,len(aa|bb))
        if a.get("creative_family")==b.get("creative_family") and a.get("category")==b.get("category"):return "near_duplicate"
        return "variant" if score>=.35 else "distinct_pattern"
    def update_pattern(self,pattern_id:str,changes:dict[str,Any])->dict[str,Any]:
        value=self.load();patterns=value["patterns"];index=next((i for i,p in enumerate(patterns) if p["pattern_id"]==pattern_id),None)
        if index is None:raise KeyError(pattern_id)
        old=deepcopy(patterns[index]);new={**old,**deepcopy(changes),"pattern_version":int(old["pattern_version"])+1}
        next_version=_increment(value["library_version"]);candidate=self._payload([*patterns[:index],new,*patterns[index+1:]],value["anti_patterns"],next_version)
        self.validate(candidate);history=self.path.parent/"versions"/f"library-{value['library_version']}.json";history.parent.mkdir(parents=True,exist_ok=True);history.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        self._write(candidate);return candidate
    def admit_research_candidate(self,candidate:dict[str,Any],observations:list[dict[str,Any]],*,approved_by:str="library_qa")->dict[str,Any]:
        """Separate QA gate: research can propose, but only this interface can activate or merge."""
        if candidate.get("status") not in {"VALIDATED","MERGED"}:raise LibraryValidationError("Research candidate is not validated for admission")
        if int(candidate.get("cross_source_count",0))<3 or int(candidate.get("source_diversity",0))<2:raise LibraryValidationError("Admission requires multi-source corroboration")
        if int(candidate.get("quality_score",0))<MINIMUM_ACTIVE_QUALITY:raise LibraryValidationError("Candidate quality is below admission threshold")
        if any(o.get("raw_content_available_to_downstream") for o in observations):raise LibraryValidationError("Raw research cannot enter the library")
        canonical=candidate.get("canonical_pattern_id")
        observation_ids=[str(x.get("observation_id")) for x in observations]
        research={"research_observation_ids":observation_ids,"cross_source_count":candidate["cross_source_count"],"source_diversity":candidate["source_diversity"],"first_observed":candidate["first_observed"],"last_observed":candidate["last_observed"],"last_validated":candidate["last_validated"],"freshness_score":candidate["freshness_score"],"transferability_to_real_estate":candidate["transferability_to_real_estate"],"real_estate_relevance":candidate["real_estate_relevance"],"approved_by":approved_by}
        if canonical:
            current=next(p for p in self.load()["patterns"] if p["pattern_id"]==canonical)
            if set(observation_ids)<=set(current.get("source_provenance",{}).get("research_observation_ids",[])):return self.load()
            provenance={**current.get("source_provenance",{}),**research}
            return self.update_pattern(canonical,{"trend_status":candidate["trend_status"],"source_provenance":provenance,"confidence":max(float(current.get("confidence",0)),float(candidate["confidence"]))})
        value=self.load();anti_ids=[x["anti_pattern_id"] for x in value["anti_patterns"]]
        pattern={"pattern_id":"pat_research_"+hashlib.sha256(candidate["candidate_id"].encode()).hexdigest()[:12],"pattern_version":1,"name":candidate["name"],"category":candidate["category"].upper(),"creative_family":candidate["creative_family"],"description":"Research-derived abstract creative principles.","source_domain":"multi_source_research","source_type":"abstract_research_synthesis","source_reference":candidate["candidate_id"],"source_date":candidate["last_observed"],"observed_date":candidate["last_observed"],"freshness":candidate["trend_status"],"quality_score":candidate["quality_score"],"confidence":candidate["confidence"],"applicability":{"project_types":["unknown"],"campaign_roles":["standalone"]},"visual_principles":candidate["abstract_principles"],"content_principles":["adapt principles to the verified content objective"],"sales_principles":["project truth remains authoritative"],"platform_fit":sorted({o.get("platform") for o in observations if o.get("platform")}),"asset_fit":["text_only"],"audience_fit":[],"information_density":"medium","brand_behavior":"restrained","typography_behavior":["clear_hierarchy"],"image_behavior":["source_led"],"story_structure":[],"conversion_behavior":["neutral inquiry"],"strengths":["multi-source abstraction"],"weaknesses":["requires contextual adaptation"],"evidence_requirements":{"required":["authoritative project evidence"],"optional":[],"forbidden":["external project facts"]},"restrictions":["no copied execution","no source artwork","no pixel geometry","no external project facts"],"anti_pattern_links":anti_ids[:2],"tags":["research_derived"],"status":"ACTIVE","trend_status":candidate["trend_status"],"quality_dimensions":{"visual_sophistication":candidate["quality_score"],"buyer_clarity":80,"sales_utility":80,"content_strength":candidate["quality_score"],"evidence_discipline":95,"platform_fit":80,"adaptability":candidate["transferability_to_real_estate"],"trend_relevance":candidate["freshness_score"]},"compatible_with":[],"conflicts_with":[],"performance_metadata":{"status":"NOT_IMPLEMENTED"},"pattern_influence":"advisory","source_provenance":research}
        next_value=self._payload([*value["patterns"],pattern],value["anti_patterns"],_increment(value["library_version"]));self.validate(next_value);self._write(next_value);return next_value
    def fingerprint(self)->str:return hashlib.sha256(self.path.read_bytes()).hexdigest()
    def _payload(self,patterns,antis,version):
        active=[p for p in patterns if p["status"]=="ACTIVE"]
        metrics={"total_patterns":len(patterns),"active_patterns":len(active),"deprecated_patterns":sum(p["status"]=="DEPRECATED" for p in patterns),"anti_patterns":len(antis),"creative_families":len({p["creative_family"] for p in patterns}),"content_categories":len({p["category"] for p in patterns}),"platform_coverage":sorted({x for p in active for x in p["platform_fit"]}),"asset_type_coverage":sorted({x for p in active for x in p["asset_fit"]}),"average_quality":round(sum(p["quality_score"] for p in patterns)/max(1,len(patterns)),1),"patterns_by_trend_status":{x:sum(p["trend_status"]==x for p in patterns) for x in sorted(TREND_STATUSES)}}
        return {"library_version":version,"schema_version":SCHEMA_VERSION,"updated_at":datetime.now(timezone.utc).isoformat(),"pattern_count":len(patterns),"anti_pattern_count":len(antis),"source_count":len({p["source_reference"] for p in patterns}),"patterns":patterns,"anti_patterns":antis,"metrics":metrics}
    def _write(self,value):self.path.parent.mkdir(parents=True,exist_ok=True);self.validate(value);self.path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
def _increment(v:str)->str:
    parts=v.split(".");parts[-1]=str(int(parts[-1])+1);return ".".join(parts)
