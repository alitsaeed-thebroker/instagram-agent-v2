"""Deterministic next-best-content decisions with durable, project-scoped memory."""
from __future__ import annotations
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib,json,re
from pathlib import Path
from typing import Any
from .schema import CampaignDecision,CampaignState

BRAIN_VERSION="1.0.0";STATE_VERSION="1.0.0";DECISION_VERSION="1.0.0"
THREADS={"project":"PROJECT_DISCOVERY","location":"LOCATION","architecture":"PROJECT_DISCOVERY","interior":"LIFESTYLE","unit":"UNIT_EDUCATION","amenity":"LIFESTYLE","lifestyle":"LIFESTYLE","commercial":"COMMERCIAL","investment":"INVESTMENT","conversion":"CONVERSION","educational":"UNIT_EDUCATION"}
ROLE={"project":"DISCOVER","location":"EDUCATE","architecture":"INSPIRE","interior":"INSPIRE","unit":"EXPLAIN","amenity":"PROVE","lifestyle":"INSPIRE","commercial":"SELL","investment":"EXPLAIN","conversion":"CONVERT","educational":"ANSWER"}
STAGE={"project":"DISCOVERY","location":"UNDERSTANDING","architecture":"AWARENESS","interior":"DESIRE","unit":"EVALUATION","amenity":"DESIRE","lifestyle":"DESIRE","commercial":"COMMERCIAL","investment":"EVALUATION","conversion":"CONVERSION","educational":"UNDERSTANDING"}
CTA={"DISCOVER":("NONE","no_cta"),"EDUCATE":("SOFT","learn_more"),"INSPIRE":("NONE","no_cta"),"PROVE":("SOFT","learn_more"),"EXPLAIN":("MODERATE","request_details"),"COMPARE":("MODERATE","request_details"),"ANSWER":("SOFT","learn_more"),"SELL":("MODERATE","request_price"),"CONVERT":("DIRECT","request_availability"),"REINFORCE":("SOFT","learn_more")}

class CampaignIntelligenceEngine:
    def __init__(self,root:Path,*,now:datetime|None=None,weights:dict[str,int]|None=None):
        self.root=root;self.now=now or datetime.now(timezone.utc);self.weights=weights or {"campaign_need":20,"buyer_relevance":15,"reci_strength":15,"narrative_continuity":10,"visual_support":10,"commercial_value":10,"historical_performance":10,"content_diversity":5,"lead_potential":5}

    def run(self,*,project_id:str,knowledge_path:Path,reci_path:Path,library_path:Path,performance_path:Path|None=None,inventory_path:Path|None=None,plan_path:Path|None=None,publication_history:list[dict[str,Any]]|None=None,simulation:bool=True)->tuple[Path,Path]:
        knowledge=_read_required(knowledge_path,"verified project knowledge");reci=_read_required(reci_path,"Creative Opportunity Map");library=_read_required(library_path,"Creative Intelligence Library")
        if not _same(project_id,reci.get("project_id")):raise ValueError("Campaign Intelligence blocked cross-project RECI input")
        inventory=_read(inventory_path);plans=_read(plan_path);performance=_read(performance_path)
        memory=self._memory(project_id,publication_history or [],performance)
        self._assert_isolation(project_id,inventory,plans,memory)
        state,candidates=self.build(project_id,knowledge,reci,library,performance,inventory,plans,memory)
        directory=self.root/"output"/"campaign-intelligence";directory.mkdir(parents=True,exist_ok=True)
        state_path=directory/f"{project_id}-campaign-state.json";decision_path=directory/f"{project_id}-campaign-decisions.json"
        _write(state_path,state.to_dict());_write(decision_path,candidates)
        memory_path=directory/f"{project_id}-campaign-memory.json";_write(memory_path,memory)
        versions=directory/"versions";versions.mkdir(parents=True,exist_ok=True)
        stamp=self.now.strftime("%Y%m%dT%H%M%SZ");_write(versions/f"{project_id}-decisions-{stamp}.json",candidates)
        return state_path,decision_path

    def build(self,project_id:str,knowledge:dict[str,Any],reci:dict[str,Any],library:dict[str,Any],performance:dict[str,Any]|None=None,inventory:dict[str,Any]|None=None,plans:dict[str,Any]|None=None,memory:dict[str,Any]|None=None)->tuple[CampaignState,dict[str,Any]]:
        performance,inventory,plans,memory=performance or {},inventory or {},plans or {},memory or self._empty_memory(project_id)
        if not knowledge or not library or not inventory:raise ValueError("Missing critical upstream artifact; autonomous campaign authorization denied")
        if not _same(project_id,reci.get("project_id")):raise ValueError("Campaign Intelligence blocked cross-project Creative Opportunity Map")
        self._assert_isolation(project_id,inventory,plans,memory)
        opportunities=list(reci.get("opportunities") or [])
        if not opportunities:raise ValueError("No canonical RECI opportunities; autonomous authorization denied")
        authentic_ids=_asset_ids(inventory)
        if not authentic_ids:raise ValueError("Authentic visual inventory contains no traceable asset identities")
        history=self._history(memory);coverage=self._coverage(opportunities,history,performance);stage=self._campaign_stage(coverage,history)
        fatigue=self._fatigue(history,performance);rows=[]
        for opp in opportunities:
            row=self._candidate(project_id,opp,stage,history,coverage,fatigue,performance,reci,library,plans)
            unknown=set(row["candidate_asset_ids"])-authentic_ids
            if unknown:row.update(status="BLOCKED",reason="Candidate references assets absent from the authentic visual inventory.",priority=0);row["restrictions"].append("Unknown or cross-project asset identity: "+", ".join(sorted(unknown)))
            row["input_versions"]["asset_inventory_version"]=inventory.get("inventory_version") or inventory.get("schema_version") or "unknown"
            rows.append(row)
        ranked=sorted(rows,key=lambda x:(x["status"]!="APPROVED",-x["priority"],-x["confidence"],x["reci_opportunity_id"]))
        approved=[x for x in ranked if x["status"]=="APPROVED"]
        selected=self._balanced_horizon(approved)
        rejected=[{"reci_opportunity_id":x["reci_opportunity_id"],"status":x["status"],"score":x["priority"],"reason":x["reason"]} for x in ranked if x not in selected]
        for index,item in enumerate(selected):
            item["planning_horizon"]="immediate_next" if index==0 else "short_horizon" if index<3 else "future_candidates"
            item["alternatives_considered"]=rejected[:8]
            item["contract_hash"]=_hash({k:v for k,v in item.items() if k!="contract_hash"})
        matrix=self._coverage(opportunities,history,performance);gaps=self._gaps(matrix,ranked)
        threads=self._threads(opportunities,history,fatigue)
        metrics=self._metrics(stage,matrix,selected,ranked,fatigue)
        fingerprint=_hash({"knowledge":knowledge.get("knowledge_version") or knowledge.get("schema_version"),"reci":reci.get("input_fingerprint"),"library":library.get("library_version"),"performance":performance.get("learning_version"),"history":history})
        state=CampaignState(project_id,STATE_VERSION,stage,self.now.isoformat(),threads,matrix,gaps,self._memory_summary(memory),metrics,fingerprint)
        contract={"contract_role":"canonical_campaign_decision_contract","campaign_brain_version":BRAIN_VERSION,"campaign_state_version":STATE_VERSION,"decision_version":DECISION_VERSION,"project_id":project_id,"created_at":self.now.isoformat(),"simulation":True,"publishing_authority":"NONE","scheduling_authority":"DEPARTMENT_5","next_best_content":selected[0] if selected else None,"strategic_queue":selected,"conditional_candidates":[x for x in ranked if x["status"] in {"BLOCKED","REVIEW_REQUIRED"}],"rejected_alternatives":rejected,"self_critique":self._critique(selected,ranked),"input_fingerprint":fingerprint}
        contract["contract_hash"]=_hash({k:v for k,v in contract.items() if k!="contract_hash"})
        return state,contract

    def _candidate(self,project,opp,current_stage,history,coverage,fatigue,performance,reci,library,plans):
        category=str(opp.get("category") or "educational");role=ROLE.get(category,"EDUCATE");desired=STAGE.get(category,"UNDERSTANDING")
        restrictions=list(opp.get("restrictions") or []);blocked=list(opp.get("blocked_claims") or [])
        unsafe=opp.get("status") in {"BLOCKED","REVIEW_REQUIRED"} or not opp.get("supporting_fact_ids")
        if category in {"commercial","investment"} and (opp.get("evidence_strength",0)<60 or any(x in " ".join(restrictions).casefold() for x in ("stale","no authoritative","require provenance"))):unsafe=True
        if opp.get("layout_sensitive") and (opp.get("status")!="STRONG" or any("not verified" in x.casefold() for x in restrictions)):unsafe=True
        recent=[x for x in history[-5:] if x.get("category")==category or _semantic(x.get("content_angle"))==_semantic(opp.get("recommended_message"))]
        usage=sum(x.get("reci_opportunity_id")==opp.get("opportunity_id") for x in history);asset_usage=Counter(a for x in history for a in x.get("asset_ids",[]))
        assets=list(opp.get("candidate_asset_ids") or opp.get("supporting_asset_ids") or []);fresh_assets=sum(asset_usage[a]==0 for a in assets)
        coverage_row=next((x for x in coverage if x["category"]==category),{})
        perf=self._performance(category,performance)
        campaign_need=max(0,min(100,100-int(coverage_row.get("coverage",0))*20 - len(recent)*18))
        continuity=max(20,100-abs(_stage_index(desired)-_stage_index(current_stage))*18)
        diversity=max(0,100-len(recent)*25-(20 if category in fatigue.get("topics",[]) else 0))
        breakdown={"campaign_need":campaign_need,"buyer_relevance":int(opp.get("buyer_relevance",50)),"reci_strength":int(opp.get("score",0)),"narrative_continuity":continuity,"visual_support":int(opp.get("visual_strength",0)),"commercial_value":int(opp.get("commercial_strength",opp.get("commercial_value",50)) or 50),"historical_performance":perf[0],"content_diversity":diversity,"lead_potential":int(opp.get("lead_generation_potential",50))}
        score=round(sum(breakdown[k]*self.weights[k] for k in self.weights)/sum(self.weights.values()))
        stage_distance=max(0,_stage_index(desired)-_stage_index(current_stage)-1)
        score=max(0,score-8*len(recent)-5*max(0,usage-1)-8*stage_distance+min(10,fresh_assets*3))
        status="BLOCKED" if unsafe else "EXHAUSTED" if usage>=3 and len(recent)>=2 else "APPROVED" if score>=55 else "DEFERRED"
        confidence=round(.55*int(opp.get("evidence_strength",0))+.3*int(opp.get("visual_strength",0))+.15*int(opp.get("confidence",.5)*100 if float(opp.get("confidence",0))<=1 else opp.get("confidence",50)))
        patterns=list(opp.get("recommended_patterns") or [])[:3];platforms=list(opp.get("recommended_platforms") or ["Instagram Feed"]);formats=list(opp.get("recommended_formats") or ["Instagram Carousel"])
        why_now=f"{category.title()} coverage is {coverage_row.get('coverage',0)}; recent related items={len(recent)}; unused supporting assets={fresh_assets}."
        reason=("Blocked by hard factual/commercial/plan-integrity constraints." if unsafe else f"Selected from verified RECI evidence for {desired.lower()} with campaign-need {campaign_need}/100 and narrative-fit {continuity}/100.")
        versions={"knowledge_version":reci.get("knowledge_version","unknown"),"reci_version":reci.get("reci_version","unknown"),"creative_opportunity_map_fingerprint":reci.get("input_fingerprint"),"creative_library_version":reci.get("creative_library_version") or library.get("library_version"),"performance_learning_version":performance.get("learning_version","unavailable"),"campaign_state_version":STATE_VERSION,"asset_inventory_version":inventory_version(opp),"commercial_intelligence_version":reci.get("knowledge_version","unknown"),"plan_intelligence_version":plans.get("schema_version","unavailable")}
        decision=CampaignDecision(_stable("decision",project,opp.get("opportunity_id"),self.now.isoformat()),project,_stable("campaign",project,THREADS.get(category,category)),desired,role,str(opp.get("objective") or desired.lower()),reason,str(opp.get("opportunity_id")),list(opp.get("supporting_fact_ids") or []),assets,str(platforms[0]),str(formats[0]),self._audience(opp),list(opp.get("buyer_value") or []),str(opp.get("recommended_message") or opp.get("title") or category),"VERIFIED_ONLY" if category in {"commercial","investment"} else "NONE",CTA[role][1],CTA[role][0],patterns,restrictions,blocked,{"opportunity_usage_count":usage,"recent_related_count":len(recent),"asset_usage":{a:asset_usage[a] for a in assets}}, {"category_score":perf[0],"confidence":perf[1],"scope":perf[2],"association_only":True},score,confidence,status,self.now.isoformat(),versions,why_now=why_now,sequence_dependency="RECOMMENDED" if desired in {"EVALUATION","COMMERCIAL","CONVERSION"} and current_stage in {"DISCOVERY","AWARENESS"} else "NONE",exploration_mode="PROVEN" if perf[1] in {"MODERATE_CONFIDENCE","STRONG_SIGNAL"} else "BALANCED",score_breakdown=breakdown)
        return decision.to_dict()

    def _balanced_horizon(self,approved):
        result=[];conversion=0;families=Counter()
        for x in approved:
            if x["campaign_role"] in {"SELL","CONVERT"} and conversion>=1:continue
            family=str((x.get("creative_pattern_candidates") or [{}])[0].get("creative_family") or "unknown")
            if families[family]>=2 and family!="unknown":continue
            result.append(x);families[family]+=1;conversion+=x["campaign_role"] in {"SELL","CONVERT"}
            if len(result)==5:break
        return result

    def _memory(self,project,publications,performance):
        path=self.root/"output"/"campaign-intelligence"/f"{project}-campaign-memory.json";existing=_read(path) or self._empty_memory(project)
        by_id={x.get("publication_id") or x.get("decision_id"):x for x in existing.get("history",[]) if x.get("publication_id") or x.get("decision_id")}
        for x in publications:
            if x.get("project_id") and not _same(x.get("project_id"),project):continue
            pid=x.get("publication_identity") or x.get("publication_id");by_id[pid]={"publication_id":pid,"project_id":project,"status":x.get("state") or x.get("status"),"published_at":x.get("publication_timestamp") or x.get("published_at"),"format":x.get("format"),"platform":x.get("platform"),"asset_ids":x.get("provenance_ids") or x.get("asset_ids") or [],"category":x.get("content_category","unknown"),"campaign_role":x.get("campaign_role","unknown"),"reci_opportunity_id":x.get("reci_opportunity_id"),"content_angle":x.get("content_angle",""),"cta_intent":x.get("cta_intent","unknown"),"creative_family":x.get("creative_family","unknown")}
        existing.update(campaign_brain_version=BRAIN_VERSION,campaign_state_version=STATE_VERSION,project_id=project,updated_at=self.now.isoformat(),history=sorted(by_id.values(),key=lambda x:str(x.get("published_at") or "")),performance_learning_version=performance.get("learning_version","unavailable"));return existing
    @staticmethod
    def _empty_memory(project):return {"project_id":project,"history":[],"scheduled":[],"blocked_opportunities":[],"unresolved_knowledge_gaps":[]}
    @staticmethod
    def _history(memory):return [x for x in memory.get("history",[]) if x.get("status") not in {"FAILED","CANCELLED","rejected"}]
    def _coverage(self,opps,history,performance):
        cats=sorted({str(x.get("category") or "educational") for x in opps});result=[]
        for cat in cats:
            group=[x for x in opps if x.get("category")==cat];used=[x for x in history if x.get("category")==cat]
            evidence=round(sum(x.get("evidence_strength",0) for x in group)/len(group));visual=round(sum(x.get("visual_strength",0) for x in group)/len(group))
            def safe(x):
                category=x.get("category");restrictions=" ".join(x.get("restrictions") or []).casefold()
                return x.get("status") not in {"BLOCKED","REVIEW_REQUIRED"} and not (category in {"commercial","investment"} and (x.get("evidence_strength",0)<60 or "stale" in restrictions or "no authoritative" in restrictions)) and not (x.get("layout_sensitive") and (x.get("status")!="STRONG" or "not verified" in restrictions))
            eligible=sum(safe(x) for x in group)
            perf=self._performance(cat,performance)
            result.append({"category":cat,"evidence_strength":evidence,"visual_support":visual,"published":len(used),"coverage":min(5,len(used)),"performance_score":perf[0] if perf[1]!="INSUFFICIENT_DATA" else None,"performance_confidence":perf[1],"remaining_opportunities":max(0,eligible-len({x.get('reci_opportunity_id') for x in used})),"blocked_opportunities":sum(not safe(x) for x in group)})
        return result
    @staticmethod
    def _campaign_stage(coverage,history):
        if not history:return "DISCOVERY"
        project=sum(x["published"] for x in coverage if x["category"] in {"project","architecture"})
        understood=sum(x["published"] for x in coverage if x["category"] in {"location","unit","amenity","interior"})
        commercial=sum(x["published"] for x in coverage if x["category"] in {"commercial","investment","conversion"})
        if project<2:return "AWARENESS"
        if understood<3:return "UNDERSTANDING"
        if commercial==0:return "EVALUATION"
        return "MAINTENANCE" if len(history)>=10 else "COMMERCIAL"
    @staticmethod
    def _performance(category,performance):
        project=(performance.get("project_effectiveness") or {});rows=[];scope="PROJECT"
        for value in project.values():rows.extend(value.get("category_performance",[]))
        match=next((x for x in rows if x.get("content_category")==category),None)
        if not match:match=next((x for x in (performance.get("account_effectiveness") or {}).get("category_performance",[]) if x.get("content_category")==category),None);scope="ACCOUNT"
        return (int(match.get("average_performance_score",50)),match.get("performance_confidence","INSUFFICIENT_DATA"),scope) if match else (50,"INSUFFICIENT_DATA","NONE")
    @staticmethod
    def _fatigue(history,performance):
        recent=history[-6:];topics=Counter(x.get("category") for x in recent);assets=Counter(a for x in recent for a in x.get("asset_ids",[]));families=Counter(x.get("creative_family") for x in recent);ctas=Counter(x.get("cta_intent") for x in recent);formats=Counter(x.get("format") for x in recent)
        learned=(performance.get("planning_advice") or {}).get("fatigue",[])
        return {"topics":[k for k,v in topics.items() if k and v>=3],"assets":[k for k,v in assets.items() if v>=3],"creative_families":[k for k,v in families.items() if k not in {None,"unknown"} and v>=3],"ctas":[k for k,v in ctas.items() if k not in {None,"unknown"} and v>=3],"formats":[k for k,v in formats.items() if k and v>=4],"performance_signals":learned}
    @staticmethod
    def _gaps(matrix,ranked):return [{"category":x["category"],"gap":"UNUSED_STRONG_OPPORTUNITY" if x["published"]==0 and x["remaining_opportunities"] else "LOW_COVERAGE","priority":"HIGH" if x["evidence_strength"]>=75 and x["visual_support"]>=60 else "MEDIUM"} for x in matrix if x["coverage"]<2 and x["remaining_opportunities"]]
    @staticmethod
    def _threads(opps,history,fatigue):
        result=[]
        for thread in sorted(set(THREADS.values())):
            cats={k for k,v in THREADS.items() if v==thread};used=[x for x in history if x.get("category") in cats];remaining=[x for x in opps if x.get("category") in cats and x.get("status") not in {"BLOCKED","REVIEW_REQUIRED"}]
            dates=[x.get("published_at") for x in used if x.get("published_at")]
            result.append({"thread_id":thread,"coverage":len(used),"last_publication":max(dates,default=None),"remaining_opportunities":len(remaining),"blocked_opportunities":sum(x.get("category") in cats and x.get("status") in {"BLOCKED","REVIEW_REQUIRED"} for x in opps),"fatigue":bool(cats&set(fatigue["topics"])),"priority":"HIGH" if remaining and not used else "MEDIUM"})
        return result
    @staticmethod
    def _audience(opp):
        values=opp.get("audience_hypotheses") or []
        return {"truth_layer":"AUDIENCE_HYPOTHESIS","value":values[0] if values else "supported project buyer","confidence":opp.get("confidence",0)}
    @staticmethod
    def _memory_summary(memory):
        h=memory.get("history",[]);return {"published_or_recorded":len(h),"scheduled":len(memory.get("scheduled",[])),"assets_used":len({a for x in h for a in x.get("asset_ids",[])}),"opportunities_used":len({x.get("reci_opportunity_id") for x in h if x.get("reci_opportunity_id")}),"project_truth_mutated":False}
    @staticmethod
    def _metrics(stage,matrix,selected,ranked,fatigue):
        return {"campaign_stage":stage,"coverage_score":round(100*sum(x["coverage"]>0 for x in matrix)/max(1,len(matrix))),"narrative_balance":len({x["campaign_role"] for x in selected})*20,"content_diversity":min(100,len({x["content_angle"] for x in selected})*20),"asset_diversity":min(100,len({a for x in selected for a in x["candidate_asset_ids"]})*10),"commercial_readiness":max((x["evidence_strength"] for x in matrix if x["category"]=="commercial"),default=0),"conversion_readiness":max((x["priority"] for x in selected if x["campaign_role"]=="CONVERT"),default=0),"fatigue_risk":sum(len(v) for k,v in fatigue.items() if isinstance(v,list)),"remaining_strong_opportunities":sum(x["status"]=="APPROVED" for x in ranked),"blocked_opportunities":sum(x["status"]=="BLOCKED" for x in ranked)}
    @staticmethod
    def _critique(selected,ranked):
        return {"approved_decisions_explainable":all(x.get("reason") and x.get("why_now") and x.get("supporting_fact_ids") and x.get("alternatives_considered") is not None for x in selected),"no_five_consecutive_conversion_posts":sum(x["campaign_role"] in {"SELL","CONVERT"} for x in selected)<=1,"performance_overrides_block":False,"project_truth_authority":"NONE","scheduling_authority":"NONE","blocked_count":sum(x["status"]=="BLOCKED" for x in ranked)}
    @staticmethod
    def _assert_isolation(project,*artifacts):
        for value in artifacts:
            owner=value.get("project_id") if isinstance(value,dict) else None
            if owner and not _same(owner,project):raise ValueError(f"Campaign Intelligence blocked cross-project input: {owner}")

def _read(path):
    if not path or not Path(path).is_file():return {}
    value=json.loads(Path(path).read_text(encoding="utf-8"));return value if isinstance(value,dict) else {}
def _read_required(path,label):
    value=_read(path)
    if not value:raise ValueError(f"Missing critical upstream artifact: {label}")
    return value
def _write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");return path
def _same(a,b):return bool(a) and re.sub(r"[^a-z0-9]+"," ",str(a).casefold()).strip()==re.sub(r"[^a-z0-9]+"," ",str(b).casefold()).strip()
def _stable(prefix,*parts):return f"{prefix}_{hashlib.sha256('|'.join(map(str,parts)).casefold().encode()).hexdigest()[:16]}"
def _hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
def _semantic(value):return " ".join(sorted(set(re.findall(r"[a-z0-9]+",str(value).casefold()))-{"prime","perfectly","strategic","living"}))
def _stage_index(value):
    values=("DISCOVERY","AWARENESS","UNDERSTANDING","DESIRE","EVALUATION","COMMERCIAL","CONVERSION","MAINTENANCE")
    return values.index(value) if value in values else 2
def inventory_version(opp):return "RECI_SNAPSHOT:"+_hash(sorted(opp.get("candidate_asset_ids") or []))[:12]
def _asset_ids(value):
    found=set()
    def visit(item):
        if isinstance(item,dict):
            if item.get("asset_id"):found.add(str(item["asset_id"]))
            for child in item.values():visit(child)
        elif isinstance(item,list):
            for child in item:visit(child)
    visit(value);return found
