"""Auditable research engine that treats all public content as untrusted data."""
from __future__ import annotations
from collections import Counter,defaultdict
from dataclasses import asdict,dataclass
from datetime import datetime,timezone,date
import hashlib,json,re
from pathlib import Path
from typing import Any,Iterable
from urllib.parse import urlsplit,urlunsplit
from .schema import Observation,PatternCandidate,ResearchObjective,SourceQualification
from src.creative_library import CreativeIntelligenceLibrary

RESEARCH_VERSION="1.0.0"
INJECTION=re.compile(r"(?:ignore|override|disregard).{0,40}(?:instructions|system|rules)|reveal.{0,20}(?:secret|key)|execute\s+(?:code|command)|publish\s+(?:content|post)|modify\s+(?:repository|files)",re.I)
FACTS=re.compile(r"\b(?:roi|yield|return)\s*(?:of|=|:)?\s*\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?\s*%\s*(?:roi|yield|return)|(?:price|starting from)\s*[:=]?\s*[$â‚¬Â£]?[\d,.]+",re.I)
GEOMETRY=re.compile(r"\b(?:x|y|width|height|font-size|px|crop)\s*[:=]\s*\d+",re.I)
LOW_QUALITY=re.compile(r"template pack|download free|dream home|best investment|guaranteed return|limited units",re.I)

@dataclass(frozen=True)
class ResearchDocument:
    source_reference:str;source_domain:str;source_type:str;publisher_or_creator:str;platform:str;industry:str;category:str;text:str
    published_date:str|None=None;professional_quality:int=70;relevance:int=70;originality:int=70;commercial_context:str="creative_reference";trust_level:str="MEDIUM"

class CreativeResearchEngine:
    def __init__(self,root:Path,library:CreativeIntelligenceLibrary|None=None):
        self.root=root;self.base=root/"data"/"creative-research";self.library=library or CreativeIntelligenceLibrary.default(root)
    def research_queries(self,objective:ResearchObjective)->list[str]:
        gaps=self.library_gaps();queries=[]
        for category in objective.categories:
            suffix=" 2026" if objective.objective in {"refresh_category","validate_trend","research_new_format"} else ""
            queries.append(f"{category.replace('_',' ')} creative campaign design{suffix}")
        if objective.objective in {"expand_category","improve_platform_coverage","improve_asset_type_coverage"}:
            queries.extend(f"{x.replace('_',' ')} real estate creative design" for x in gaps["weak_categories"][:3])
        return list(dict.fromkeys(queries))[:objective.limit]
    def load_source_groups(self,config_path:Path)->dict[str,list[dict[str,Any]]]:
        value=json.loads(config_path.read_text(encoding="utf-8"));groups=value.get("source_groups")
        if not isinstance(groups,dict) or not all(isinstance(x,list) for x in groups.values()):raise ValueError("Creative research source_groups configuration is invalid")
        return groups
    def refresh_due(self,last_validated:str,trend_status:str,*,intervals:dict[str,int]|None=None)->bool:
        policy={"EVERGREEN":30,"CURRENT":14,"EMERGING":7,"EXPERIMENTAL":7,"DECLINING":30};policy.update(intervals or {})
        try:elapsed=(date.today()-date.fromisoformat(last_validated[:10])).days
        except (TypeError,ValueError):return True
        return elapsed>=policy.get(trend_status,30)
    def library_gaps(self)->dict[str,Any]:
        value=self.library.initialize();counts=Counter(p["category"] for p in value["patterns"] if p["status"]=="ACTIVE")
        desired={"REAL_ESTATE_HERO","PROJECT_DISCOVERY","LOCATION","MAP","UNIT_LAYOUT","COMPARISON","PAYMENT_PLAN","COMMERCIAL","EDUCATIONAL","LEAD_GENERATION","STORY","CAROUSEL"}
        return {"weak_categories":sorted(desired-set(counts)|{x for x,n in counts.items() if n<1}),"missing_platforms":sorted({"instagram_feed","instagram_carousel","instagram_story","facebook"}-set(value["metrics"]["platform_coverage"])),"missing_asset_types":sorted({"exterior","interior","map","unit_layout","commercial_table","text_only"}-set(value["metrics"]["asset_type_coverage"]))}
    def run(self,objective:ResearchObjective,documents:Iterable[ResearchDocument])->Path:
        docs=list(documents)[:objective.limit];batch_id="research_"+hashlib.sha256((objective.objective+datetime.now(timezone.utc).isoformat()).encode()).hexdigest()[:12]
        observations=[];qualifications=[];known_sources,known_signatures=self._history_index();source_seen=set(known_sources);signatures=set(known_signatures);rejected=[]
        for doc in docs:
            canonical=_canonical(doc.source_reference)
            if canonical in source_seen:rejected.append({"source_reference":doc.source_reference,"reason":"duplicate source"});continue
            source_seen.add(canonical);q=self.qualify(doc);qualifications.append(asdict(q))
            if not q.accepted:rejected.append({"source_reference":doc.source_reference,"reason":"; ".join(q.reasons)});continue
            obs=self.observe(doc,q)
            if obs.content_signature in signatures:obs.deduplication_status="duplicate";rejected.append({"source_reference":doc.source_reference,"reason":"duplicate observation"});continue
            signatures.add(obs.content_signature);observations.append(obs)
        candidates=self.form_candidates(observations)
        anti=self.extract_anti_patterns(observations)
        metrics=self._metrics(docs,qualifications,observations,candidates,rejected,objective)
        payload={"research_batch_id":batch_id,"research_version":RESEARCH_VERSION,"objective":asdict(objective),"queries":self.research_queries(objective),"status":"COMPLETE" if observations else "RESEARCH_INCOMPLETE","sources_examined":len(docs),"source_qualifications":qualifications,"observations":[x.to_dict() for x in observations],"pattern_candidates":[x.to_dict() for x in candidates],"anti_pattern_candidates":anti,"rejected":rejected,"metrics":metrics,"raw_web_content_exposed_to_reci":False,"external_assets_created":False,"project_knowledge_modified":False,"created_at":datetime.now(timezone.utc).isoformat()}
        self._persist(batch_id,payload,observations,candidates,rejected);return self.base/"batches"/f"{batch_id}.json"
    def qualify(self,doc:ResearchDocument)->SourceQualification:
        reasons=[];score=.3*doc.professional_quality+.3*doc.relevance+.2*doc.originality+.2*(90 if doc.trust_level=="HIGH" else 70 if doc.trust_level=="MEDIUM" else 40)
        if INJECTION.search(doc.text):reasons.append("untrusted embedded instruction removed")
        if LOW_QUALITY.search(doc.text):score-=25;reasons.append("low-quality or unsafe sales signal")
        tier="TIER_A" if score>=82 else "TIER_B" if score>=68 else "TIER_C" if score>=50 else "REJECTED"
        accepted=tier in {"TIER_A","TIER_B"};
        if not accepted:reasons.append("source below automatic observation threshold")
        return SourceQualification(doc.source_domain,doc.source_type,doc.category,doc.publisher_or_creator,doc.published_date,date.today().isoformat(),doc.professional_quality,doc.relevance,doc.originality,doc.commercial_context,doc.platform,doc.trust_level,tier,accepted,reasons)
    def observe(self,doc:ResearchDocument,q:SourceQualification)->Observation:
        clean=INJECTION.sub("[UNTRUSTED INSTRUCTION REMOVED]",doc.text);fact_count=len(FACTS.findall(clean));facts=["external numeric commercial claim removed"]*fact_count;clean=FACTS.sub("[EXTERNAL PROJECT FACT REJECTED]",clean);clean=GEOMETRY.sub("[EXECUTABLE GEOMETRY REJECTED]",clean)
        lower=clean.casefold();visual=_signals(lower,{"image dominant":"image_dominant","full bleed":"full_bleed","negative space":"negative_space_driven","split layout":"split_layout","technical":"clean_technical","data card":"data_card","editorial corner":"editorial_corner"}) or ["balanced"]
        typography=_signals(lower,{"editorial":"editorial_hierarchy","numeric":"numeric_hierarchy","uppercase":"uppercase_behavior","minimal":"minimal_hierarchy","technical typography":"technical_typography"}) or ["clear_hierarchy"]
        image=_signals(lower,{"architecture":"architecture_first","lifestyle":"lifestyle_first","complete plan":"technical_plan_preservation","full bleed":"full_bleed","detail crop":"detail_crop","negative space":"negative_space_usage"}) or ["source_led"]
        story=_signals(lower,{"hook":"hook","context":"context","proof":"proof","detail":"detail","benefit":"benefit","cta":"cta"})
        anti=[]
        for signal,name in (("oversized logo","ap_oversized_logo"),("fake urgency","ap_fake_urgency"),("stock image","ap_stock_visual"),("unreadable","ap_low_contrast"),("guaranteed return","ap_unsupported_roi")): 
            if signal in lower:anti.append(name)
        principles=[_principle(x) for x in visual+typography+image if _principle(x)][:8]
        signature=hashlib.sha256("|".join(sorted(set(visual+typography+image+story))).encode()).hexdigest()
        transfer=_transferability(doc.industry,doc.category);relevance=min(100,round((doc.relevance+transfer)/2));confidence=round((q.professional_quality+q.relevance+q.originality)/300,2)
        return Observation("obs_"+hashlib.sha256((doc.source_reference+signature).encode()).hexdigest()[:14],doc.source_reference,doc.platform,doc.source_domain,doc.published_date,date.today().isoformat(),doc.category,doc.category,doc.industry,doc.platform,visual,"low" if "minimal_hierarchy" in typography else "medium","restrained" if "negative_space_driven" in visual else "standard",typography,image,story,["neutral inquiry" if "cta" in story else "none"],["commercial behavior observed; no values retained"],principles,anti,principles,anti,confidence,confidence,round(confidence*transfer/100,2),transfer,relevance,signature,"independent_observation",list(facts),bool(INJECTION.search(doc.text)))
    def form_candidates(self,observations:list[Observation])->list[PatternCandidate]:
        groups=defaultdict(list)
        for o in observations:groups[_candidate_key(o)].append(o)
        candidates=[];library=self.library.initialize()
        for key,items in groups.items():
            sources={x.source_domain for x in items};platforms={x.platform for x in items};principles=sorted({p for x in items for p in x.transferable_principles});count=len(items)
            quality=round(sum((x.source_confidence*100+x.real_estate_relevance+x.transferability_to_real_estate)/3 for x in items)/count);confidence=min(.98,round(.35+.12*count+.08*len(sources)+.05*len(platforms),2))
            trend="CURRENT" if count>=3 and len(sources)>=2 else "EMERGING" if count>=2 else "EXPERIMENTAL";status="VALIDATED" if count>=3 and len(sources)>=2 and quality>=75 else "CANDIDATE"
            candidate=PatternCandidate("cand_"+hashlib.sha256((key+"|".join(sorted(x.observation_id for x in items))).encode()).hexdigest()[:14],key.replace("_"," ").title(),_canonical_category(items[0].category),_family(items),[x.observation_id for x in items],count,len(sources),len(platforms),quality,confidence,round(sum(x.transferability_to_real_estate for x in items)/count),round(sum(x.real_estate_relevance for x in items)/count),principles,["authoritative project evidence required for every project claim"],["no copied execution","no pixel geometry","no external project facts"],min(x.observed_date for x in items),max(x.observed_date for x in items),date.today().isoformat(),trend,90 if trend=="CURRENT" else 75 if trend=="EMERGING" else 55,status,"distinct_pattern")
            closest=self._closest(candidate,library["patterns"]);candidate.similarity_status=closest[0];candidate.canonical_pattern_id=closest[1]
            if closest[0] in {"duplicate","near_duplicate"}:candidate.status="MERGED"
            candidates.append(candidate)
        return candidates
    def extract_anti_patterns(self,observations):
        counts=Counter(x for o in observations for x in o.potential_anti_patterns)
        return [{"anti_pattern_id":x,"observation_count":n,"status":"VALIDATED" if n>=3 else "CANDIDATE","supporting_observation_ids":[o.observation_id for o in observations if x in o.potential_anti_patterns]} for x,n in counts.items()]
    def _closest(self,candidate,patterns):
        probe={"pattern_id":candidate.candidate_id,"name":candidate.name,"category":candidate.category,"creative_family":candidate.creative_family,"asset_fit":[]};rank={"duplicate":0,"near_duplicate":1,"variant":2,"distinct_pattern":3};matches=[(self.library.classify_similarity(probe,p),p["pattern_id"]) for p in patterns];return min(matches,key=lambda x:rank[x[0]]) if matches else ("distinct_pattern",None)
    def _metrics(self,docs,quals,obs,cands,rejected,obj):
        accepted=[q for q in quals if q["accepted"]];return {"sources_examined":len(docs),"sources_accepted":len(accepted),"sources_rejected":len(docs)-len(accepted),"observations_created":len(obs),"pattern_candidates":len(cands),"patterns_activated":0,"patterns_merged":sum(x.status=="MERGED" for x in cands),"patterns_rejected":sum(x.status=="REJECTED" for x in cands),"anti_patterns_created":len({a for o in obs for a in o.potential_anti_patterns}),"categories_expanded":len({o.category for o in obs}),"platforms_covered":sorted({o.platform for o in obs}),"industries_covered":sorted({o.industry for o in obs}),"average_source_quality":round(sum(q["professional_quality"] for q in accepted)/max(1,len(accepted)),1),"average_pattern_quality":round(sum(c.quality_score for c in cands)/max(1,len(cands)),1),"average_transferability":round(sum(o.transferability_to_real_estate for o in obs)/max(1,len(obs)),1),"duplicate_rate":round(len([x for x in rejected if "duplicate" in x["reason"]])/max(1,len(docs)),3),"rejection_rate":round((len(docs)-len(accepted))/max(1,len(docs)),3),"trend_coverage":dict(Counter(c.trend_status for c in cands)),"library_gap_reduction":len(set(obj.categories)&{o.category for o in obs})}
    def _persist(self,bid,payload,observations,candidates,rejected):
        targets=(("batches",bid,payload),("observations",bid,{"observations":[x.to_dict() for x in observations]}),("candidates",bid,{"candidates":[x.to_dict() for x in candidates]}),("rejected",bid,{"rejected":rejected}),("source-index",bid,{"sources":[{"source_reference":x.source_reference,"content_signature":x.content_signature,"last_examined":x.observed_date} for x in observations]}))
        for folder,name,value in targets:path=self.base/folder/f"{name}.json";path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        index_path=self.base/"source-index"/"index.json";known_sources,known_signatures=self._history_index(include_global=False)
        entries={_canonical(x.source_reference):{"canonical_url_or_reference":_canonical(x.source_reference),"content_signature":x.content_signature,"source_date":x.source_date,"last_examined":x.observed_date} for x in observations}
        try:existing=json.loads(index_path.read_text(encoding="utf-8")).get("sources",{})
        except (OSError,ValueError):existing={}
        index_path.write_text(json.dumps({"sources":{**existing,**entries}},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    def _history_index(self,*,include_global:bool=True):
        sources=set();signatures=set();folder=self.base/"source-index"
        if not folder.is_dir():return sources,signatures
        for path in folder.glob("*.json"):
            if not include_global and path.name=="index.json":continue
            try:value=json.loads(path.read_text(encoding="utf-8"))
            except (OSError,ValueError):continue
            records=value.get("sources",{});records=records.values() if isinstance(records,dict) else records
            for row in records:
                if row.get("canonical_url_or_reference"):sources.add(_canonical(row["canonical_url_or_reference"]))
                elif row.get("source_reference"):sources.add(_canonical(row["source_reference"]))
                if row.get("content_signature"):signatures.add(row["content_signature"])
        return sources,signatures

def _canonical(url):
    try:p=urlsplit(url);return urlunsplit((p.scheme.casefold(),p.netloc.casefold(),p.path.rstrip("/"),"",""))
    except ValueError:return url.strip().casefold()
def _signals(text,mapping):return [v for k,v in mapping.items() if k in text]
def _principle(signal):return {"image_dominant":"let the authenticated source image lead","full_bleed":"use immersive image behavior when source safety permits","negative_space_driven":"use authentic negative space for restrained information","editorial_hierarchy":"use a clear editorial hierarchy","minimal_hierarchy":"reduce information to the content objective","architecture_first":"keep architecture visually primary","technical_plan_preservation":"preserve the complete technical source","source_led":"let source characteristics guide composition"}.get(signal,signal.replace("_"," "))
def _transferability(industry,category):
    value=industry.casefold();return 95 if "real estate" in value or "architecture" in value else 88 if "hospitality" in value else 78 if "automotive" in value or "fashion" in value else 70 if "financial" in value else 60
def _candidate_key(o):return ("architectural_editorial_hero" if "architecture_first" in o.image_behavior else "technical_clean" if "technical_plan_preservation" in o.image_behavior else "luxury_minimal" if "minimal_hierarchy" in o.typography_character else re.sub(r"[^a-z0-9]+","_",o.category.casefold()).strip("_"))
def _family(items):return _candidate_key(items[0])
def _canonical_category(value):
    text=value.casefold()
    if "hero" in text:return "REAL_ESTATE_HERO"
    if "location" in text:return "LOCATION"
    if "layout" in text or "floor plan" in text:return "UNIT_LAYOUT"
    if "carousel" in text:return "CAROUSEL"
    if "developer" in text or "launch" in text:return "PROJECT_LAUNCH"
    return re.sub(r"[^A-Z0-9]+","_",value.upper()).strip("_")
