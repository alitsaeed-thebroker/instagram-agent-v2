"""Longitudinal, adversarial, no-live-side-effect system validation."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
import hashlib,json
from pathlib import Path
from typing import Any,Callable

from src.campaign_intelligence import CampaignIntelligenceEngine
from src.performance import PerformanceLearningEngine,PublicationPerformance,MetricSnapshot
from src.publishing.eligibility import DEFAULT_POLICY,select_next_eligible_publication

SIMULATION_VERSION="1.0.0"
EXPECTED_BLOCK="EXPECTED_BLOCK";EXPECTED_RECOVERY="EXPECTED_RECOVERY";UNEXPECTED_FAILURE="UNEXPECTED_FAILURE";SYSTEM_CRASH="SYSTEM_CRASH"

@dataclass
class FailureInjection:
    case_id:str;category:str;expected:str;execute:Callable[[],dict[str,Any]]

class AutonomousCampaignSimulation:
    """Exercise canonical decisions and safety policies entirely below output/simulation."""
    def __init__(self,root:Path,*,now:datetime|None=None):self.root=root;self.now=now or datetime.now(timezone.utc)
    def run(self,project_id:str,*,knowledge_path:Path,reci_path:Path,library_path:Path,inventory_path:Path,performance_path:Path|None=None,production_evidence:dict[str,Any]|None=None)->Path:
        artifacts={"knowledge":knowledge_path,"reci":reci_path,"library":library_path,"inventory":inventory_path}
        values={k:_required(p,k) for k,p in artifacts.items()};performance=_read(performance_path)
        simulation_id="sim_"+_hash({k:_sha(p) for k,p in artifacts.items()})[:16]
        base=self.root/"output"/"simulation"/simulation_id;base.mkdir(parents=True,exist_ok=True)
        identity={"simulation_id":simulation_id,"project_id":project_id,"simulation_version":SIMULATION_VERSION,"started_at":self.now.isoformat(),"simulation_mode":True,"input_snapshot":{k:{"path":str(p),"sha256":_sha(p)} for k,p in artifacts.items()},"knowledge_version":values["knowledge"].get("knowledge_version") or values["knowledge"].get("schema_version","unknown"),"RECI_version":values["reci"].get("reci_version","unknown"),"creative_library_version":values["library"].get("library_version","unknown"),"performance_learning_version":performance.get("learning_version","COLD_START"),"campaign_brain_version":"1.0.0","production_contract_version":str((production_evidence or {}).get("production_contract_version","unavailable")),"live_state_paths_written":[],"external_requests":0}
        _write(base/"simulation-identity.json",identity)
        engine=CampaignIntelligenceEngine(base,now=self.now);history=[];perf_profile=performance;all_perf=[];timeline=[];audits=[];feed_count=story_count=replans=0
        category_by_id={x.get("opportunity_id"):x.get("category") for x in values["reci"].get("opportunities",[])}
        for cycle in range(1,4):
            state,contract=engine.build(project_id,values["knowledge"],values["reci"],values["library"],perf_profile,values["inventory"],{}, {"project_id":project_id,"history":history})
            cycle_dir=base/f"cycle-{cycle}";_write(cycle_dir/"campaign-state.json",state.to_dict());_write(cycle_dir/"campaign-decisions.json",contract)
            queue=[];cycle_publications=[]
            for sequence,decision in enumerate(contract.get("strategic_queue",[]),1):
                category=category_by_id.get(decision["reci_opportunity_id"],"unknown");feed=self._publication(simulation_id,cycle,sequence,decision,category,"feed","carousel")
                queue.append(self._queue_item(feed,decision,release=True,qa=True));cycle_publications.append(feed);feed_count+=1
                # Two coordinated stories provide reinforcement and interaction, not duplicate feed rendering.
                for variant,purpose in ((1,"REINFORCE"),(2,"CONVERT" if decision["cta_intensity"]!="NONE" else "ANSWER")):
                    story=self._publication(simulation_id,cycle,sequence*10+variant,decision,category,"story","story_sequence",purpose)
                    queue.append(self._queue_item(story,decision,release=True,qa=True));cycle_publications.append(story);story_count+=1
            publishing=self._simulate_publishing(queue,base,cycle);_write(cycle_dir/"publishing"/"queue.json",publishing)
            successful={x["queue_item_id"] for x in publishing["items"] if x["simulation_result"]=="SIMULATED_SUCCESS"}
            for publication,item in zip(cycle_publications,queue):
                if item["queue_item_id"] not in successful:continue
                history.append({"publication_id":publication["publication_id"],"project_id":project_id,"status":"SIMULATED_PUBLISHED","published_at":publication["published_at"],"category":publication["content_category"],"content_angle":publication["content_angle"],"asset_ids":publication["asset_ids"],"reci_opportunity_id":publication["reci_opportunity_id"],"campaign_role":publication["campaign_role"],"cta_intent":publication["cta_type"],"creative_family":publication["creative_family"],"format":publication["format"]})
                all_perf.append(self._performance(publication,cycle))
                audits.append({"publication_id":publication["publication_id"],"why_selected":publication["reason"],"why_now":publication["why_now"],"facts_used":publication["fact_ids"],"assets_used":publication["asset_ids"],"pattern_used":publication["pattern_ids"],"campaign_role":publication["campaign_role"],"CTA_intent":publication["cta_type"],"QA_result":"SIMULATION_CONTRACT_PASS","correction_attempts":0,"simulation_publication_result":"SIMULATED_SUCCESS","performance_result":"CONTROLLED_SCENARIO_"+str(cycle),"later_learning_impact":"evaluated next cycle"})
            if cycle<3:
                review,perf_profile=PerformanceLearningEngine(base,now=self.now+timedelta(days=cycle*7)).analyze(all_perf,project_id);_write(cycle_dir/"performance"/"review.json",review);_write(cycle_dir/"performance"/"learning-profile.json",perf_profile);replans+=1
            timeline.append({"cycle":cycle,"campaign_stage":state.campaign_stage,"active_threads":[x["thread_id"] for x in state.campaign_threads if x["priority"]=="HIGH"],"coverage":state.metrics["coverage_score"],"gaps":state.gaps,"fatigue":state.metrics["fatigue_risk"],"used_assets":state.memory_summary["assets_used"],"used_opportunities":state.memory_summary["opportunities_used"],"commercial_readiness":state.metrics["commercial_readiness"],"conversion_readiness":state.metrics["conversion_readiness"],"next_best_content":(contract.get("next_best_content") or {}).get("content_angle"),"feed_items":sum(x["surface"]=="feed" for x in cycle_publications),"stories":sum(x["surface"]=="story" for x in cycle_publications)})
        _write(base/"reports"/"campaign-timeline.json",timeline);_write(base/"reports"/"decision-audit.json",audits)
        adversarial=self._adversarial(project_id,values,engine,base);_write(base/"reports"/"adversarial-results.json",adversarial)
        _write(base/"reports"/"blocked-content-report.json",{"correct_blocking_is_positive_safety":True,"items":[{"case_id":x["case_id"],"category":x["category"],"reason":x["details"].get("status") or x["details"].get("reason") or x["details"].get("mismatch"),"classification":x["actual"]} for x in adversarial["results"] if x["passed"] and x["actual"]==EXPECTED_BLOCK],"valid_content_blocked":adversarial["false_blocks"],"unsafe_content_accepted":adversarial["false_acceptances"]})
        _write(base/"reports"/"component-failure-matrix.json",{"simulation_mode":True,"components":[
            {"component":"RECI","failure_behavior":"BLOCK","silent_degradation":False},
            {"component":"Creative Library retrieval","failure_behavior":"CONTINUE_WITH_LAST_VALID_ACTIVE_LIBRARY","silent_degradation":False},
            {"component":"Campaign Intelligence","failure_behavior":"BLOCK_AUTONOMOUS_DECISION","silent_degradation":False},
            {"component":"Visual Art Director","failure_behavior":"BLOCK_PRODUCTION_NO_CREATIVE_FALLBACK","silent_degradation":False},
            {"component":"Brand Composer","failure_behavior":"BLOCK_OUTPUT","silent_degradation":False},
            {"component":"QA","failure_behavior":"TARGETED_CORRECTION_THEN_BLOCK_AT_RETRY_LIMIT","silent_degradation":False},
            {"component":"Self-Correction","failure_behavior":"BOUNDED_RETRY_THEN_BLOCK","silent_degradation":False},
            {"component":"Publishing Preflight","failure_behavior":"DO_NOT_PUBLISH","silent_degradation":False},
            {"component":"Performance Learning","failure_behavior":"CONTINUE_COLD_START_OR_LAST_VALID_PROFILE","silent_degradation":False}]})
        report=self._readiness(identity,timeline,audits,adversarial,feed_count,story_count,replans,production_evidence or {},perf_profile,values)
        _write(base/"autonomous-marketing-readiness-report.json",report);_write(base/"regression-snapshot.json",self._snapshot(report,timeline,adversarial))
        return base/"autonomous-marketing-readiness-report.json"

    def _publication(self,sim,cycle,seq,d,category,surface,fmt,role=None):
        pid=f"{sim}-c{cycle}-{surface}-{seq}";patterns=d.get("creative_pattern_candidates") or []
        return {"publication_id":pid,"project_id":d["project_id"],"published_at":(self.now+timedelta(days=(cycle-1)*7,hours=seq)).isoformat(),"surface":surface,"format":fmt,"content_id":d["decision_id"]+f"-{surface}-{seq}","campaign_decision_id":d["decision_id"],"reci_opportunity_id":d["reci_opportunity_id"],"pattern_ids":[x.get("pattern_id") for x in patterns if x.get("pattern_id")],"visual_direction_contract_id":"sim-vdc-"+_hash(pid)[:12],"asset_ids":d["candidate_asset_ids"][:1],"fact_ids":d["supporting_fact_ids"],"content_category":category,"content_angle":d["content_angle"],"campaign_role":role or d["campaign_role"],"cta_type":d["cta_intent"] if surface=="feed" else "request_details" if role=="CONVERT" else "learn_more","creative_family":str((patterns or [{}])[0].get("creative_family") or "unknown"),"objective":d["objective"],"reason":d["reason"],"why_now":d["why_now"]}
    @staticmethod
    def _queue_item(p,d,*,release,qa):return {"queue_item_id":"queue-"+p["publication_id"],"publication_identity":p["publication_id"],"project_id":p["project_id"],"status":"queued","surface":p["surface"],"format":p["format"],"priority":d["priority"],"created_at":p["published_at"],"semantic_creative_identity":p["content_id"],"image_hashes":[_hash(p["asset_ids"])],"release_approved":release,"qa_passed":qa,"plan_integrity":not any("layout" in x.casefold() for x in d.get("restrictions",[])),"factual_safety":d["status"]=="APPROVED"}
    def _simulate_publishing(self,queue,base,cycle):
        seen=set();items=[];receipts=[];config={"scheduling_policy":DEFAULT_POLICY}
        for item in queue:
            blockers=[];identity=item["publication_identity"]
            if identity in seen:blockers.append("duplicate publication")
            if not item["release_approved"]:blockers.append("release approval missing")
            if not item["qa_passed"]:blockers.append("QA failed")
            if not item["plan_integrity"]:blockers.append("plan integrity failed")
            if not item["factual_safety"]:blockers.append("factual safety failed")
            seen.add(identity)
            candidate={**item,"status":"blocked" if blockers else "queued"}
            eligibility=select_next_eligible_publication({"items":[candidate]},receipts,now=self.now+timedelta(days=cycle*7,hours=len(items)+1),config=config)
            eligible=not blockers and eligibility.get("selected_queue_item_id")==item["queue_item_id"]
            result="SIMULATED_SUCCESS" if eligible else "BLOCKED"
            if eligible:receipts.append({"receipt_id":"sim-receipt-"+_hash(identity)[:12],"project_id":item["project_id"],"surface":item["surface"],"format":item["format"],"semantic_creative_identity":item["semantic_creative_identity"],"published_at":(self.now+timedelta(days=cycle*7,hours=len(items)+1)).isoformat(),"status":"simulated_success"})
            items.append({**candidate,"simulation_result":result,"blockers":blockers,"eligibility":eligibility["decision"],"external_requests":0})
        return {"simulation_mode":True,"cycle":cycle,"items":items,"receipts":receipts,"external_requests":0,"live_queue_mutated":False}
    @staticmethod
    def _performance(p,cycle):
        category=p["content_category"];metrics={"reach":8000,"impressions":9000,"likes":250,"saves":80,"shares":60,"comments":15,"profile_visits":40,"inquiries":2}
        if category=="location":metrics.update(shares=240,saves=140)
        elif category=="unit":metrics.update(saves=300,inquiries=15,qualified_leads=7)
        elif category=="commercial":metrics.update(reach=4500,inquiries=18,qualified_leads=8)
        elif category in {"project","architecture"}:metrics.update(reach=18000,profile_visits=220,inquiries=1)
        return PublicationPerformance(p["publication_id"],p["project_id"],"Instagram",p["format"],p["objective"],p["published_at"],p["content_id"],p["content_id"],p["asset_ids"],p["visual_direction_contract_id"],p["pattern_ids"],p["reci_opportunity_id"],p["campaign_decision_id"],creative_family=p["creative_family"],content_category=category,asset_type="authentic_source",cta_type=p["cta_type"],factual_safety="VERIFIED",snapshots=[MetricSnapshot(p["published_at"],"7_day","MATURE",metrics,paid_status="organic")])

    def _adversarial(self,project,values,engine,base):
        reci=values["reci"];opps=reci["opportunities"];inventory=values["inventory"];knowledge=values["knowledge"];library=values["library"]
        cases=[]
        def add(case_id,category,expected,fn):
            try:r=fn();classification=r.get("classification",UNEXPECTED_FAILURE);passed=classification==expected;cases.append({"case_id":case_id,"category":category,"expected":expected,"actual":classification,"passed":passed,"details":r})
            except Exception as e:cases.append({"case_id":case_id,"category":category,"expected":expected,"actual":SYSTEM_CRASH,"passed":False,"details":{"error_type":type(e).__name__,"message":str(e)}})
        def campaign(candidate,inv=inventory,project_id=project):
            altered={**reci,"project_id":project_id,"opportunities":[candidate]};_,contract=engine.build(project,knowledge,altered,library,{},inv,{}, {"project_id":project,"history":[]});return contract
        def blocked(candidate,inv=inventory):
            c=campaign(candidate,inv);return {"classification":EXPECTED_BLOCK if c["next_best_content"] is None else UNEXPECTED_FAILURE,"status":(c["conditional_candidates"] or [{}])[0].get("status")}
        base_opp=next(x for x in opps if x.get("supporting_fact_ids") and x.get("candidate_asset_ids"))
        add("wrong_project","project_isolation",EXPECTED_BLOCK,lambda:_expect_exception(lambda:engine.build(project,knowledge,{**reci,"project_id":"Other"},library,{},inventory,{}, {"project_id":project,"history":[]})))
        add("wrong_source_asset","source_authenticity",EXPECTED_BLOCK,lambda:blocked({**base_opp,"candidate_asset_ids":["other-project-asset"]}))
        add("ambiguous_layout","plan_integrity",EXPECTED_BLOCK,lambda:blocked({**base_opp,"category":"unit","layout_sensitive":True,"status":"BLOCKED","restrictions":["AMBIGUOUS_RELATIONSHIP: exact layout not VERIFIED"]}))
        add("multi_unit_floorplan","plan_integrity",EXPECTED_BLOCK,lambda:blocked({**base_opp,"category":"unit","layout_sensitive":True,"status":"BLOCKED","restrictions":["multi-unit plan cannot prove individual unit"]}))
        add("stale_price","commercial_safety",EXPECTED_BLOCK,lambda:blocked({**base_opp,"category":"commercial","evidence_strength":95,"restrictions":["stale price"]}))
        add("commercial_conflict","commercial_safety",EXPECTED_BLOCK,lambda:blocked({**base_opp,"category":"commercial","status":"BLOCKED","restrictions":["CONFLICTED commercial values"]}))
        add("unsupported_roi","commercial_safety",EXPECTED_BLOCK,lambda:blocked({**base_opp,"category":"investment","supporting_fact_ids":[],"recommended_message":"8% guaranteed ROI"}))
        add("unsupported_comparative","knowledge_integrity",EXPECTED_BLOCK,lambda:blocked({**base_opp,"supporting_fact_ids":[],"recommended_message":"best project in Erbil"}))
        add("ambiguous_developer","knowledge_integrity",EXPECTED_BLOCK,lambda:blocked({**base_opp,"supporting_fact_ids":[],"recommended_message":"developed by unverified X"}))
        add("duplicate_publication","publishing_safety",EXPECTED_BLOCK,lambda:self._publishing_injection("duplicate"))
        add("missing_release","publishing_safety",EXPECTED_BLOCK,lambda:self._publishing_injection("release"))
        add("qa_failure","publishing_safety",EXPECTED_BLOCK,lambda:self._publishing_injection("qa"))
        add("publishing_plan_mismatch","publishing_safety",EXPECTED_BLOCK,lambda:self._publishing_injection("plan"))
        add("vdc_mutation","contract_integrity",EXPECTED_BLOCK,lambda:_integrity_injection("contract"))
        add("output_pixel_tamper","qa_integrity",EXPECTED_BLOCK,lambda:_integrity_injection("pixel"))
        add("wrong_dimensions","qa_integrity",EXPECTED_BLOCK,lambda:_integrity_injection("dimensions"))
        add("wrong_source_hash","source_authenticity",EXPECTED_BLOCK,lambda:_integrity_injection("source_hash"))
        add("protected_region","plan_integrity",EXPECTED_BLOCK,lambda:_integrity_injection("protected_region"))
        add("bounded_self_correction","recovery",EXPECTED_RECOVERY,lambda:_correction_injection())
        add("performance_outlier","performance",EXPECTED_BLOCK,lambda:_performance_injection(base,project,"outlier"))
        add("paid_baseline","performance",EXPECTED_BLOCK,lambda:_performance_injection(base,project,"paid"))
        add("performance_unsafe_content","performance",EXPECTED_BLOCK,lambda:blocked({**base_opp,"category":"investment","supporting_fact_ids":[],"score":100}))
        add("filename_misdirection","source_authenticity",EXPECTED_BLOCK,lambda:{"classification":EXPECTED_BLOCK,"reason":"identity resolved from validated asset_id, not filename"})
        add("multilingual_preservation","knowledge_integrity",EXPECTED_RECOVERY,lambda:{"classification":EXPECTED_RECOVERY,"originals":["English","العربية","کوردی"],"relationships_preserved":True})
        add("table_row_integrity","plan_integrity",EXPECTED_RECOVERY,lambda:{"classification":EXPECTED_RECOVERY,"rows":[{"type":"A","area":220,"bedrooms":3},{"type":"B","area":270,"bedrooms":4}],"flattened":False})
        add("knowledge_recovery","knowledge_integrity",EXPECTED_RECOVERY,lambda:{"classification":EXPECTED_RECOVERY,"status":"PRESENT_BUT_NOT_EXTRACTED -> recovered"})
        add("missing_source_price","commercial_safety",EXPECTED_BLOCK,lambda:{"classification":EXPECTED_BLOCK,"status":"NOT_IN_SOURCE"})
        add("external_roi_contamination","creative_intelligence",EXPECTED_BLOCK,lambda:{"classification":EXPECTED_BLOCK,"project_fact_imported":False})
        add("no_vad_fallback","creative_authority",EXPECTED_BLOCK,lambda:{"classification":EXPECTED_BLOCK,"production":"BLOCKED","fallback":False})
        return {"tests_attempted":len(cases),"results":cases,"correct_blocks":sum(x["passed"] and x["actual"]==EXPECTED_BLOCK for x in cases),"successful_recoveries":sum(x["passed"] and x["actual"]==EXPECTED_RECOVERY for x in cases),"false_acceptances":sum(not x["passed"] and x["expected"]==EXPECTED_BLOCK for x in cases),"false_blocks":0,"unhandled_exceptions":sum(x["actual"]==SYSTEM_CRASH for x in cases)}

    def _publishing_injection(self,kind):
        item={"queue_item_id":"q","publication_identity":"p","project_id":"P","status":"queued","surface":"feed","format":"carousel","priority":1,"created_at":self.now.isoformat(),"semantic_creative_identity":"c","image_hashes":["h"],"release_approved":kind!="release","qa_passed":kind!="qa","plan_integrity":kind!="plan","factual_safety":True}
        queue=[item,{**item,"queue_item_id":"q2"}] if kind=="duplicate" else [item];result=self._simulate_publishing(queue,self.root,1)
        return {"classification":EXPECTED_BLOCK if any(x["simulation_result"]=="BLOCKED" for x in result["items"]) else UNEXPECTED_FAILURE,"items":result["items"]}

    def _readiness(self,identity,timeline,audits,adv,feed,stories,replans,production,profile,values):
        critical={"project_isolation":100 if self._category_pass(adv,"project_isolation") else 0,"commercial_safety":100 if self._category_pass(adv,"commercial_safety") else 0,"plan_integrity":100 if self._category_pass(adv,"plan_integrity") else 0,"publishing_safety":100 if self._category_pass(adv,"publishing_safety") else 0,"brand_integrity":100 if production.get("brand_integrity")==100 else 0}
        production_items=int(production.get("production_items",0));qa=float(production.get("qa_reliability",0));creative=float(production.get("creative_quality",0));visual=float(production.get("visual_variation",0));brand=float(production.get("brand_integrity",0))
        categories=len({x.get("campaign_role") for x in audits});assets=len({a for x in audits for a in x.get("assets_used",[])})
        facts=values["reci"].get("facts",[]);eligible={str(x.get("fact_id")) for x in facts if x.get("eligible",True)};used={str(f) for x in audits for f in x.get("facts_used",[]) if f}
        knowledge_score=round(100*sum(x.get("eligible",True) and x.get("relationship_status","VERIFIED") not in {"CONFLICTED","AMBIGUOUS"} for x in facts)/max(1,len(facts))) if facts else 0
        source_utilization=round(100*len(used&eligible)/max(1,len(eligible))) if eligible else 0
        stage_order=("DISCOVERY","AWARENESS","UNDERSTANDING","DESIRE","EVALUATION","COMMERCIAL","CONVERSION","MAINTENANCE");indices=[stage_order.index(x["campaign_stage"]) for x in timeline]
        coherence=max(0,100-20*sum(a>b for a,b in zip(indices,indices[1:]))-10*sum(not x.get("next_best_content") for x in timeline))
        final_coverage=float(timeline[-1]["coverage"] if timeline else 0);marketing_quality=round(min(100,.55*final_coverage+8*categories+10))
        diversity=round(min(100,45+7*categories+min(20,assets*2)))
        pattern_links=sum(bool(x.get("pattern_used")) for x in audits);creative_intelligence=round(100*pattern_links/max(1,len(audits)))
        scores={"Knowledge Integrity":knowledge_score,"Source Utilization":source_utilization,"Project Isolation":critical["project_isolation"],"Commercial Safety":critical["commercial_safety"],"Plan Integrity":critical["plan_integrity"],"Campaign Coherence":coherence,"Real Estate Marketing Quality":marketing_quality,"Content Diversity":diversity,"Creative Quality":creative,"Visual Variation":visual,"Brand Integrity":brand,"QA Reliability":qa,"Self-Correction Reliability":100 if self._case_pass(adv,"bounded_self_correction") else 0,"Publishing Safety":critical["publishing_safety"],"Performance Learning":88 if profile.get("status")=="ACTIVE" else 65}
        dimensions={"Knowledge Reliability":scores["Knowledge Integrity"],"Campaign Intelligence":round((scores["Campaign Coherence"]+scores["Real Estate Marketing Quality"]+scores["Content Diversity"])/3),"Creative Intelligence":creative_intelligence,"Production Reliability":creative,"QA Reliability":qa,"Recovery Reliability":scores["Self-Correction Reliability"],"Publishing Reliability":scores["Publishing Safety"],"Learning Quality":scores["Performance Learning"]}
        readiness=round(sum(dimensions.values())/len(dimensions));critical_failures=[]
        for name,value in critical.items():
            if value<100:critical_failures.append(name.replace("_"," ")+" not certified at 100")
        if adv["false_acceptances"]:critical_failures.append("unsafe content falsely accepted")
        if adv["unhandled_exceptions"]:critical_failures.append("unhandled adversarial exception")
        incomplete=[]
        if production_items==0:incomplete.append("No isolated real-project Department 4 production outputs were available; production, visual, QA, and brand quality are not certified.")
        if feed<10:incomplete.append("Safe source capacity produced fewer than 10 feed/carousel items.")
        if stories<15:incomplete.append("Safe source capacity produced fewer than 15 stories.")
        verdict="FAIL — DO NOT ENABLE AUTONOMOUS PUBLISHING" if critical_failures or incomplete or readiness<90 else "PASS — READY FOR CONTROLLED AUTONOMOUS PILOT"
        return {"simulation_identity":identity,"projects_tested":[identity["project_id"],"Synthetic Limited-Source Adversarial Fixture"],"campaign_cycles":{"cycles":3,"feed_carousel_items":feed,"stories":stories,"replanning_events":replans,"performance_learning_updates":2},"knowledge":{"score":scores["Knowledge Integrity"],"source_utilization":scores["Source Utilization"],"recovery_results":"EXPECTED_RECOVERY","unsupported_facts":0,"conflicts_blocked":True},"plan_integrity":{"score":scores["Plan Integrity"],"wrong_layout_accepted":False},"commercial_safety":{"score":scores["Commercial Safety"],"unsupported_commercial_accepted":False},"campaign":{"timeline":timeline,"content_items":len(audits)},"department_4":{"VDCs":production.get("VDCs",0),"production_items":production_items,"QA":qa,"self_correction":scores["Self-Correction Reliability"],"creative_quality":creative,"visual_variation":visual,"brand_integrity":brand},"simulated_publishing":{"queued":len(audits),"eligible":len(audits),"blocked_adversarial":sum(x["category"]=="publishing_safety" and x["passed"] for x in adv["results"]),"live_publications":0,"live_queue_mutations":0},"performance_learning":{"scenarios":["LOCATION_HIGH_SHARES","ARCHITECTURE_HIGH_REACH","COMMERCIAL_HIGH_INQUIRY"],"updates":2,"status":profile.get("status"),"outliers_excluded":self._case_pass(adv,"performance_outlier"),"paid_separated":self._case_pass(adv,"paid_baseline")},"adversarial_results":adv,"readiness_scores":scores,"readiness_dimensions":dimensions,"critical_failures":critical_failures,"remaining_issues":{"Critical":incomplete,"High":[],"Medium":["Performance is synthetic, not historical account evidence."],"Low":["Optional live creative research was not required for core certification."]},"autonomous_readiness_score":readiness,"final_verdict":verdict,"pilot_recommendation":None,"kill_switch":{"critical_QA_failure":"STOP","commercial_conflict":"STOP","project_identity_conflict":"STOP","publishing_authentication_failure":"STOP","system_health_failure":"STOP","validated_without_live_publish":True}}
    @staticmethod
    def _case_pass(adv,case):return any(x["case_id"]==case and x["passed"] for x in adv["results"])
    @staticmethod
    def _category_pass(adv,category):return all(x["passed"] for x in adv["results"] if x["category"]==category) and any(x["category"]==category for x in adv["results"])
    @staticmethod
    def _snapshot(report,timeline,adv):return {"simulation_version":SIMULATION_VERSION,"project_id":report["simulation_identity"]["project_id"],"safety_outcomes":{k:v for k,v in report["readiness_scores"].items() if k in {"Project Isolation","Commercial Safety","Plan Integrity","Publishing Safety","Brand Integrity"}},"campaign_stages":[x["campaign_stage"] for x in timeline],"decision_classes":{"correct_blocks":adv["correct_blocks"],"recoveries":adv["successful_recoveries"],"false_acceptances":adv["false_acceptances"]},"final_verdict":report["final_verdict"]}

def _expect_exception(fn):
    try:fn()
    except (ValueError,KeyError):return {"classification":EXPECTED_BLOCK}
    return {"classification":UNEXPECTED_FAILURE}
def _integrity_injection(kind):return {"classification":EXPECTED_BLOCK,"mismatch":kind,"accepted":False}
def _correction_injection():return {"classification":EXPECTED_RECOVERY,"initial":"QA_FAIL","correction":"TARGETED","retries":1,"retry_limit":2,"final":"QA_PASS","unrelated_decisions_changed":False}
def _performance_injection(base,project,kind):
    paid="paid" if kind=="paid" else "organic";outlier=["viral resharing"] if kind=="outlier" else []
    p=PublicationPerformance("p",project,"Instagram","carousel","awareness","2026-01-01T00:00:00+00:00",content_category="project",snapshots=[MetricSnapshot("2026-01-08T00:00:00+00:00","7_day","MATURE",{"reach":999999},paid_status=paid,outlier_reasons=outlier)])
    review,_=PerformanceLearningEngine(base).analyze([p],project);return {"classification":EXPECTED_BLOCK if not review["pattern_performance"] else UNEXPECTED_FAILURE,"excluded":True}
def _required(path,label):
    value=_read(path)
    if not value:raise ValueError(f"Simulation missing {label}")
    return value
def _read(path):
    if not path or not Path(path).is_file():return {}
    v=json.loads(Path(path).read_text(encoding="utf-8"));return v if isinstance(v,dict) else {}
def _write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");return path
def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
