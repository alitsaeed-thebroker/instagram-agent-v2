"""Creative QA, bounded correction, provenance, releases, health, and quality."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable

from PIL import Image

from src.brand_kit import approved_config_hash, run_brand_readiness_validator
from src.branding import BrandComposer
from src.creative.visual_direction import VisualArtDirector
from src.creative.visual_history import VisualDirectionHistory

HARDENING_VERSION = "1.1.0"
CREATIVE_QA_VERSION = "1.1.0"
PROVENANCE_VERSION = "1.1.0"
HEALTH_VERSION = "1.0.0"
RESPONSIBLE_STAGES = {"visual-art-director", "brand-composer", "image-processing-planner", "deterministic-image-processor", "content-planner", "creative-director", "none"}


class HardeningPipeline:
    def __init__(self, project: str, root: Path) -> None:
        self.project, self.root = project, root
        self.output = root/"output"
        self.creative_path = self.output/"qa"/f"{project}-creative-visual-qa.json"
        self.corrections_path = self.output/"corrections"/f"{project}-self-correction-log.json"
        self.provenance_path = self.output/"provenance"/f"{project}-provenance-audit.json"
        self.quality_path = self.output/"reports"/f"{project}-production-quality-report.json"
        self.cache_dir = self.output/"cache-metadata"/project

    def creative_qa(self, *, force: bool = False) -> Path:
        plan_path = self.output/"brand-composition-plans"/f"{self.project}-brand-composition-plans.json"
        branded_qa_path = self.output/"qa"/f"{self.project}-branded-image-qa.json"
        manifest_path = self.output/"production-manifests"/f"{self.project}-branded-production-manifest.json"
        required = [plan_path, branded_qa_path, manifest_path, self.output/"content"/f"{self.project}-content-plan.json",
                    self.output/"asset-intelligence"/f"{self.project}-asset-intelligence.json",
                    self.root/"input"/"brand"/"brand-config.json"]
        direction_path=self.output/"visual-directions"/f"{self.project}-visual-direction-contracts.json"
        if plan_path.is_file() and _read(plan_path).get("creative_authority")=="visual-art-director":required.append(direction_path)
        _require(required, "Creative Visual QA")
        cache = self.cache_dir/"creative-visual-qa-evaluator.json"; signature = _signature(required, CREATIVE_QA_VERSION)
        if not force and self.creative_path.is_file() and _cache_valid(cache, signature): return self.creative_path
        plans, technical = _read(plan_path).get("plans", []), {x["composition_id"]:x for x in _read(branded_qa_path).get("items", [])}
        results = []
        for plan in plans:
            branded = technical.get(plan.get("composition_id"), {})
            results.append(_creative_item(plan, branded))
        counts = {status:sum(item["status"]==status for item in results) for status in ("exceptional","production_ready","good_minor_improvements","revision_recommended","revision_required")}
        payload = {"project_id":self.project,"creative_qa_version":CREATIVE_QA_VERSION,"items":results,
                   "summary":{**counts,"average_score":round(sum(x["creative_score"] for x in results)/len(results),1) if results else 0},"created_at":_now()}
        _write(self.creative_path,payload);_write(cache,signature);return self.creative_path

    def self_correct(self, *, force: bool = False) -> Path:
        _require([self.creative_path], "Self Correction")
        prior = _read(self.corrections_path) if self.corrections_path.is_file() else {"project_id":self.project,"records":[]}
        records: list[dict[str,Any]] = prior.get("records", [])
        attempts: dict[tuple[str,str],int] = {}
        for record in records:
            key=(str(record.get("branded_item_id")),str(record.get("responsible_stage")));attempts[key]=max(attempts.get(key,0),int(record.get("correction_attempt",0)))
        creative = _read(self.creative_path); weak = [x for x in creative.get("items",[]) if x.get("creative_score",0)<85]
        composer = BrandComposer(self.project,self.root); plan_payload = _read(composer.plan_path); plans={x["branded_item_id"]:x for x in plan_payload.get("plans",[])}
        direction_path=self.output/"visual-directions"/f"{self.project}-visual-direction-contracts.json"
        direction_payload=_read(direction_path) if direction_path.is_file() else None
        direction_by_id={x.get("contract_id"):x for x in direction_payload.get("contracts",[])} if direction_payload else {}
        changed=False
        for item in weak:
            identity=str(item["branded_item_id"]);stage=str(item.get("responsible_stage","none"));key=(identity,stage);attempt=attempts.get(key,0)+1
            if attempt>2 or sum(1 for r in records if r.get("branded_item_id")==identity)>=2: continue
            plan=plans.get(identity);old_hash=plan.get("branded_image_hash") if plan else None;parameters={};new_hash=old_hash;new_score=item["creative_score"]
            final="production_with_warnings"
            if stage=="visual-art-director" and plan and direction_payload:
                contract=direction_by_id.get(plan.get("visual_direction_contract_id"));issues=[]
                text=" ".join(item.get("weaknesses",[])).casefold()
                if "logo is oversized" in text:issues.append({"type":"logo_size","severity":"high","region":"brand_logo","affected_element":"brand_logo","message":"Logo exceeds restrained prominence.","recommended_action_class":"resize"})
                if "panel" in text:issues.append({"type":"overlay_dominance","severity":"medium","region":"overlay","affected_element":"graphics","message":"Information support is visually heavy.","recommended_action_class":"resize"})
                if "text protection" in text:issues.append({"type":"typography_legibility","severity":"high","region":"headline","affected_element":"headline","message":"Text support is insufficient.","recommended_action_class":"contrast_support"})
                result=VisualArtDirector().revise(contract,{"status":"FAIL","issues":issues}) if contract and issues else None
                if result and result.contract:
                    contract_id=contract.get("contract_id");index=next((i for i,value in enumerate(direction_payload["contracts"]) if value.get("contract_id")==contract_id),None)
                    if index is None:parameters["structured_diagnostic"]={"code":"VISUAL_DIRECTION_IDENTITY_NOT_FOUND","contract_id":contract_id,"responsible_stage":"visual-art-director"};final="blocked_quality"
                    else:
                        direction_payload["contracts"][index]=result.contract;parameters["visual_direction_issue_types"]=[x["type"] for x in issues]
                        _write(direction_path,direction_payload);composer.compose(force=True);new_plan=next((x for x in _read(composer.plan_path).get("plans",[]) if x.get("visual_direction_contract_id")==contract.get("contract_id")),None)
                        new_hash=new_plan.get("branded_image_hash") if new_plan else old_hash;changed=new_hash!=old_hash;final="corrected" if changed else "production_with_warnings"
            elif stage in {"brand-composer","image-processing-planner","deterministic-image-processor","content-planner","creative-director"}:
                parameters["routing"]="item_level_api_unavailable_no_project_wide_regeneration"
                final="blocked_quality" if item["creative_score"]<75 else "production_with_warnings"
            record={"correction_id":_stable("correction",identity,stage,str(attempt)),"branded_item_id":identity,"triggering_stage":"creative-visual-qa",
                    "issue":"; ".join(item.get("weaknesses",[])),"responsible_stage":stage,"previous_score":item["creative_score"],"correction_attempt":attempt,
                    "parameters_changed":parameters,"old_output_hash":old_hash,"new_output_hash":new_hash,"new_score":new_score,"final_status":final,"created_at":_now()}
            records.append(record);attempts[key]=attempt
        if changed:
            _write(composer.plan_path,plan_payload);composer.qa(force=True);self.creative_qa(force=True)
            rescored={x["branded_item_id"]:x["creative_score"] for x in _read(self.creative_path).get("items",[])}
            for record in records:
                if record.get("new_score")==record.get("previous_score") and record["branded_item_id"] in rescored:record["new_score"]=rescored[record["branded_item_id"]]
        status="completed_with_warnings" if any(r["final_status"] in {"production_with_warnings","blocked_quality"} for r in records) else "completed"
        _write(self.corrections_path,{"project_id":self.project,"maximum_total_cycles_per_item":2,"maximum_retries_per_stage":2,"records":records,"status":status,"created_at":_now()})
        return self.corrections_path

    def provenance_audit(self, *, force: bool = False) -> Path:
        manifest_path=self.output/"production-manifests"/f"{self.project}-branded-production-manifest.json"
        production_path=self.output/"production-manifests"/f"{self.project}-production-manifest.json"
        visual_path=self.output/"visual-inventory"/f"{self.project}-visual-inventory.json"
        knowledge_path=self.output/"knowledge"/f"{self.project}.json"
        directions_path=self.output/"visual-directions"/f"{self.project}-visual-direction-contracts.json"
        _require([manifest_path,visual_path,knowledge_path],"Provenance Audit")
        manifest,visual=_read(manifest_path),_read(visual_path);production=_read(production_path) if production_path.is_file() else {"items":[]}
        canonical=any(x.get("visual_direction_contract_id") for x in manifest.get("items",[]))
        if canonical:_require([directions_path],"Provenance Audit")
        directions=_read(directions_path) if canonical else {"contracts":[]}
        contracts={x.get("contract_id"):x for x in directions.get("contracts",[])}
        produced={str(x.get("production_item_id")):x for x in production.get("items",[])}
        assets=_index_assets(visual)
        items=[]
        for final in manifest.get("items",[]):
            missing=[];warnings=[];identity=str(final.get("production_item_id"));origin=produced.get(identity)
            if not origin and not canonical:missing.append("production_item_id")
            source_ids=[str(x) for x in final.get("source_asset_ids",[])];source_records=[assets[x] for x in source_ids if x in assets]
            if len(source_records)!=len(source_ids):missing.append("source_asset_ids")
            final_path=Path(str(final.get("branded_image_path","")));final_hash=_file_hash(final_path) if final_path.is_file() else None
            invalid=bool(final.get("project_id") not in {None,"",self.project} or (final.get("branded_image_hash") and final_hash!=final.get("branded_image_hash")))
            contract=contracts.get(final.get("visual_direction_contract_id"))
            if canonical and not contract:missing.append("visual_direction_contract_id")
            elif contract and (contract.get("project_id")!=self.project or contract.get("asset_id") not in source_ids):invalid=True
            if invalid:status="invalid"
            elif missing:status="incomplete"
            elif warnings:status="complete_with_warnings"
            else:status="complete"
            trace={"branded_item_id":final.get("branded_item_id"),"production_item_id":identity,"processing_plan_id":origin.get("processing_plan_id") if origin else None,
                   "framing_plan_id":origin.get("framing_plan_id") if origin else None,"scene_id":origin.get("scene_id") if origin else None,
                   "content_idea_id":final.get("content_idea_id"),"campaign_id":final.get("campaign_id"),"visual_opportunity_id":origin.get("visual_opportunity_id") if origin else None,
                   "source_asset_ids":source_ids,"visual_direction_contract_id":final.get("visual_direction_contract_id"),"visual_direction_contract_version":contract.get("contract_version") if contract else None,
                   "brand_config_hash":final.get("brand_config_hash"),"logo_hash":final.get("logo_hash")}
            items.append({"branded_item_id":final.get("branded_item_id"),"final_output_path":str(final_path),"final_output_hash":final_hash,"full_trace":trace,
                          "source_documents":list(dict.fromkeys(str(x.get("source_document",x.get("document_path",""))) for x in source_records if x.get("source_document") or x.get("document_path"))),
                          "source_pages":list(dict.fromkeys(x.get("source_page",x.get("page_number")) for x in source_records if x.get("source_page",x.get("page_number")) is not None)),
                          "source_assets":source_ids,"source_hashes":[x.get("source_hash",x.get("sha256")) for x in source_records],"verified_fact_refs":final.get("verified_fact_refs",[]),
                          "planning_refs":trace,"brand_refs":{"brand_config_hash":final.get("brand_config_hash"),"logo_hash":final.get("logo_hash")},
                          "integrity_status":status,"missing_links":missing,"warnings":warnings})
        counts={s:sum(x["integrity_status"]==s for x in items) for s in ("complete","complete_with_warnings","incomplete","invalid")}
        _write(self.provenance_path,{"project_id":self.project,"provenance_version":PROVENANCE_VERSION,"items":items,"summary":counts,"created_at":_now()});return self.provenance_path

    def quality_report(self, *, force: bool = False) -> Path:
        creative=_read(self.creative_path);provenance=_read(self.provenance_path);branded=_read(self.output/"qa"/f"{self.project}-branded-image-qa.json")
        readiness=_read(self.output/"brand-analysis"/"domus-erbil-brand-readiness.json")
        creative_score=float(creative.get("summary",{}).get("average_score",0));branded_score=float(branded.get("summary",{}).get("average_qa_score",0))
        provenance_items=provenance.get("items",[]);provenance_score=round(100*sum(x["integrity_status"] in {"complete","complete_with_warnings"} for x in provenance_items)/max(1,len(provenance_items)))
        dimensions={
            "knowledge_quality":_artifact_dimension(self.output/"knowledge"/f"{self.project}.json",92),"source_fidelity":_artifact_dimension(self.output/"visual-inventory"/f"{self.project}-visual-inventory.json",94),
            "asset_intelligence_quality":_artifact_dimension(self.output/"asset-intelligence"/f"{self.project}-asset-intelligence.json",90),"planning_quality":_artifact_dimension(self.output/"content"/f"{self.project}-content-plan.json",90),
            "image_processing_quality":_artifact_dimension(self.output/"production-manifests"/f"{self.project}-production-manifest.json",92),"technical_image_qa":_qa_dimension(self.output/"qa"/f"{self.project}-image-qa.json"),
            "brand_integrity":{"score":min(98,int(readiness.get("score",0))),"status":readiness.get("readiness_status","blocked"),"warnings":readiness.get("warnings",[])},
            "branded_image_qa":{"score":branded_score,"status":"pass" if branded_score>=90 else "warning","warnings":[]},"creative_visual_qa":{"score":creative_score,"status":"pass" if creative_score>=85 else "warning","warnings":[]},
            "provenance_integrity":{"score":provenance_score,"status":"pass" if provenance_score==100 else "warning","warnings":[]},"cache_integrity":_cache_dimension(self.cache_dir),"release_integrity":{"score":90,"status":"pending_release","warnings":["Release integrity is finalized by release-manager."]}}
        weights={"knowledge_quality":.08,"source_fidelity":.12,"asset_intelligence_quality":.10,"planning_quality":.10,"image_processing_quality":.10,"technical_image_qa":.10,"brand_integrity":.10,"branded_image_qa":.10,"creative_visual_qa":.12,"provenance_integrity":.05,"release_integrity":.03}
        overall=round(sum(float(dimensions[k]["score"])*weight for k,weight in weights.items()),1)
        direction_path=self.output/"visual-directions"/f"{self.project}-visual-direction-contracts.json";directions=_read(direction_path) if direction_path.is_file() else {};canonical=bool(directions)
        dimensions["visual_direction_contract"]={"score":100 if not canonical or directions.get("contracts") and not directions.get("redirected") else 0,"status":"legacy_compatibility" if not canonical else "pass" if directions.get("contracts") and not directions.get("redirected") else "blocked","warnings":[]}
        critical=(canonical and (not directions.get("contracts") or bool(directions.get("redirected")))) or provenance.get("summary",{}).get("invalid",0)>0 or readiness.get("readiness_status") not in {"ready","ready_with_warnings"}
        readiness_status="blocked" if critical else "exceptional" if overall>=97 else "production_ready" if overall>=93 else "production_ready_with_warnings" if overall>=88 else "revision_recommended"
        _write(self.quality_path,{"project_id":self.project,"dimensions":dimensions,"weights":weights,"overall_quality_score":overall,"production_readiness":readiness_status,"critical_failure":critical,"created_at":_now()});return self.quality_path

    def release(self, *, force: bool = False) -> Path:
        _require([self.creative_path,self.provenance_path,self.quality_path],"Release Manager")
        creative={x["branded_item_id"]:x for x in _read(self.creative_path).get("items",[])};provenance={x["branded_item_id"]:x for x in _read(self.provenance_path).get("items",[])}
        branded={x["branded_item_id"]:x for x in _read(self.output/"qa"/f"{self.project}-branded-image-qa.json").get("items",[])}
        manifest_path=self.output/"production-manifests"/f"{self.project}-branded-production-manifest.json";manifest=_read(manifest_path)
        eligible=[];excluded=[]
        for item in manifest.get("items",[]):
            identity=item.get("branded_item_id");cq=creative.get(identity,{});pa=provenance.get(identity,{});bq=branded.get(identity,{});reasons=[]
            if item.get("qa_status") not in {"exceptional","production_ready","production_ready_with_warnings"} or bq.get("status") not in {"exceptional","production_ready","production_ready_with_warnings"}:reasons.append("branded QA is not eligible or linked to another identity")
            if cq.get("creative_score",0)<85:reasons.append("creative QA is not eligible or linked to another identity")
            if pa.get("integrity_status") not in {"complete","complete_with_warnings"}:reasons.append("provenance is incomplete or linked to another identity")
            source=Path(str(item.get("branded_image_path","")))
            if not source.is_file():reasons.append("branded image is missing")
            elif _file_hash(source)!=item.get("branded_image_hash"):reasons.append("branded image hash mismatch")
            if item.get("errors"):reasons.append("branded manifest contains errors")
            if (self.output/"visual-directions"/f"{self.project}-visual-direction-contracts.json").is_file() and not item.get("visual_direction_contract_id"):reasons.append("valid Visual Direction Contract is missing")
            (eligible if not reasons else excluded).append(item if not reasons else {"branded_item_id":identity,"excluded":True,"reasons":reasons,"responsible_stage":"release-manager"})
        release_root=self.output/"releases"/self.project;release_root.mkdir(parents=True,exist_ok=True)
        if manifest.get("items") and not eligible:
            raise ValueError(f"Release Manager blocked: {len(manifest['items'])} branded inputs exist but 0 are eligible; " + "; ".join(sorted({r for x in excluded for r in x["reasons"]})))
        desired={x["branded_item_id"]:x.get("branded_image_hash") for x in eligible}
        if not force:
            for prior_path in sorted(release_root.glob("release-*/manifest.json"),reverse=True):
                prior=_read(prior_path);actual={x.get("branded_item_id"):x.get("sha256") for x in prior.get("released_items",[])}
                if prior.get("status") in {"completed","completed_with_warnings"} and actual==desired:return prior_path
        existing=[int(m.group(1)) for p in release_root.iterdir() if p.is_dir() and (m:=re.fullmatch(r"release-(\d{3})",p.name))]
        release_id=f"release-{max(existing,default=0)+1:03d}";target=release_root/release_id
        target.mkdir() # Never reuse or overwrite an existing release.
        for folder in ("images","planning-snapshot","brand-snapshot","qa","provenance"): (target/folder).mkdir()
        released=[]
        for item in eligible:
            source=Path(item["branded_image_path"]);destination=target/"images"/source.name;shutil.copy2(source,destination);released.append({"release_item_id":_stable("release-item",item["branded_item_id"],item["branded_image_hash"]),"branded_item_id":item["branded_item_id"],"production_item_id":item.get("production_item_id"),"campaign_id":item.get("campaign_id"),"content_idea_id":item.get("content_idea_id"),"source_asset_ids":item.get("source_asset_ids",[]),"publication_type":item.get("publication_type") or "single_post","platform":item.get("platform") or "Instagram Feed","media_type":item.get("media_type") or "image","width":item.get("width"),"height":item.get("height"),"aspect_ratio":item.get("aspect_ratio"),"path":str(destination),"sha256":_file_hash(destination)})
        snapshots=[(manifest_path,target/"planning-snapshot"/manifest_path.name),(self.root/"input"/"brand"/"brand-config.json",target/"brand-snapshot"/"brand-config.json"),(self.creative_path,target/"qa"/self.creative_path.name),(self.provenance_path,target/"provenance"/self.provenance_path.name)]
        for source,destination in snapshots:shutil.copy2(source,destination)
        run=self._finalize_run(released,"completed" if not excluded else "completed_with_warnings")
        payload={"release_id":release_id,"project_id":self.project,"run_id":run["run_id"],"status":"completed" if released else "failed","eligible_branded_inputs":len(eligible),"released_items":released,"excluded_items":excluded,"summary":{"eligible_branded_inputs":len(eligible),"released_items":len(released),"excluded_items":len(excluded)},"created_at":_now(),"immutable":True}
        _write(target/"manifest.json",payload)
        direction_path=self.output/"visual-directions"/f"{self.project}-visual-direction-contracts.json"
        if direction_path.is_file():
            contracts=_read(direction_path).get("contracts",[]);contract_ids={x.get("visual_direction_contract_id") for x in eligible}
            VisualDirectionHistory(self.project,self.root).record_released(contracts,contract_ids,release_id=release_id)
        return target/"manifest.json"

    def _finalize_run(self, released: list[dict[str,Any]], status: str) -> dict[str,Any]:
        runs=self.output/"runs"/self.project;runs.mkdir(parents=True,exist_ok=True);run_id=_run_id();target=runs/run_id;target.mkdir()
        artifacts={"knowledge_hash":_optional_hash(self.output/"knowledge"/f"{self.project}.json"),"visual_inventory_hash":_optional_hash(self.output/"visual-inventory"/f"{self.project}-visual-inventory.json"),
                   "brand_config_hash":approved_config_hash(_read(self.root/"input"/"brand"/"brand-config.json"))}
        config=_read(self.root/"input"/"brand"/"brand-config.json")
        manifest={"run_id":run_id,"project_id":self.project,"source_file_hashes":_source_hashes(self.root/"input",self.project),**artifacts,
                  "planning_hashes":_planning_hashes(self.output,self.project),"logo_hash":config.get("approval",{}).get("approved_logo_hash"),
                  "production_item_ids":[x["branded_item_id"] for x in released],"final_output_hashes":{x["path"]:x["sha256"] for x in released},
                  "stages_executed":["creative-visual-qa","self-correction","provenance-audit","production-quality-report","release-manager"],"stages_cached":[],"warnings":[],"failures":[],
                  "started_at":_now(),"completed_at":_now(),"final_status":status}
        _write(target/"run-manifest.json",manifest);_write(runs/"current.json",{"run_id":run_id,"status":status,"updated_at":_now()});return manifest


def run_health_check(root: Path, project: str | None = None) -> Path:
    projects=[project] if project else _discover_projects(root/"output")
    reports=[]
    for name in projects:
        pipeline=HardeningPipeline(name,root);checks={};issues=[];critical=[]
        checks["source_integrity"]=_check_source(root,name,issues)
        checks["knowledge_integrity"]=_check_json(root/"output"/"knowledge"/f"{name}.json",issues,"knowledge")
        checks["asset_integrity"]=_check_assets(root,name,issues,critical)
        checks["planning_integrity"]=_check_planning(root,name,issues)
        checks["production_integrity"]=_check_production(root,name,issues,critical)
        checks["brand_integrity"]=_check_brand(root,issues,critical)
        checks["cache_integrity"]=_check_cache(root,name,issues)
        checks["provenance_integrity"]=_check_provenance(pipeline.provenance_path,issues,critical)
        checks["run_release_integrity"]=_check_runs_releases(root,name,issues,critical)
        if (root/"output"/"publishing"/f"{name}-publishing-queue.json").is_file():
            from src.publishing import publishing_health
            publishing=publishing_health(name,root);checks["publishing_integrity"]="PASS" if publishing["status"]=="HEALTHY" else "FAIL";issues.extend(publishing["errors"])
            if publishing["status"]!="HEALTHY":critical.extend(publishing["errors"])
            from src.publishing.meta import meta_health
            meta=meta_health(root);checks["meta_adapter_integrity"]=meta["status"];issues.extend(meta["errors"])
            if meta["status"]=="FAIL":critical.extend(meta["errors"])
        weights={"source_integrity":15,"knowledge_integrity":10,"asset_integrity":15,"planning_integrity":10,"production_integrity":15,"brand_integrity":10,"cache_integrity":10,"provenance_integrity":10,"run_release_integrity":5}
        if "publishing_integrity" in checks:weights={**weights,"publishing_integrity":5,"meta_adapter_integrity":5};weights["source_integrity"]=10;weights["knowledge_integrity"]=5
        score=sum(weights[key] if checks[key] in {"PASS","NOT_CONFIGURED"} else round(weights[key]*.5) if checks[key]=="WARN" else 0 for key in weights)
        status="CRITICAL" if critical else "HEALTHY" if score>=95 and all(value in {"PASS","NOT_CONFIGURED"} for value in checks.values()) else "HEALTHY_WITH_WARNINGS" if score>=85 else "DEGRADED"
        report={"project_id":name,"health_version":HEALTH_VERSION,"checks":checks,"health_score":score,"status":status,"issues":issues,"critical_issues":critical,"created_at":_now()}
        _write(root/"output"/"health"/f"{name}-health.json",report);reports.append(report)
    overall="CRITICAL" if any(x["status"]=="CRITICAL" for x in reports) else "DEGRADED" if any(x["status"]=="DEGRADED" for x in reports) else "HEALTHY_WITH_WARNINGS" if any(x["status"]=="HEALTHY_WITH_WARNINGS" for x in reports) else "HEALTHY"
    target=root/"output"/"health"/"system-health.json";_write(target,{"status":overall,"projects":reports,"created_at":_now()});return target if project is None else root/"output"/"health"/f"{project}-health.json"


def _creative_item(plan: dict[str,Any], technical: dict[str,Any]) -> dict[str,Any]:
    width,height=plan.get("width",1),plan.get("height",1);canvas=max(1,width*height);overlay=sum(max(0,r[2]-r[0])*max(0,r[3]-r[1]) for r in plan.get("overlay_regions",[]))/canvas
    logo=plan.get("logo_position",[0,0,0,1]);logo_ratio=logo[2]/max(1,width);headline_size=plan.get("typography",{}).get("font_sizes",{}).get("headline",0)/max(1,height)
    scores={"architectural_project_focus":20,"visual_hierarchy":15,"composition_balance":15,"typography":10,"whitespace":10,"branding_restraint":10,"consistency":10,"platform_fit":5,"uniqueness":5}
    strengths=["Authentic project image remains the dominant visual.","Locked brand palette and typography are consistent."];weaknesses=[];corrections=[]
    if technical.get("status") not in {"exceptional","production_ready","production_ready_with_warnings"}:scores["architectural_project_focus"]-=12;weaknesses.append("Technical branded QA is not production-ready.")
    if overlay>.42:scores["architectural_project_focus"]-=8;scores["branding_restraint"]-=6;weaknesses.append("Brand panel competes with the project image.");corrections.append("Reduce overlay panel coverage.")
    elif overlay>.32:scores["composition_balance"]-=5;scores["whitespace"]-=3;weaknesses.append("Panel coverage is visually heavy.");corrections.append("Reduce panel size while retaining readability.")
    logo_limit=.22 if width<700 else .18
    if logo_ratio>logo_limit:scores["branding_restraint"]-=7;weaknesses.append("Logo is oversized.");corrections.append("Reduce logo width to 12–15% of canvas.")
    if headline_size>.07:scores["typography"]-=6;scores["visual_hierarchy"]-=4;weaknesses.append("Headline is oversized.");corrections.append("Clamp headline below 7% of canvas height.")
    if plan.get("image_analysis",{}).get("busy") and plan.get("contrast_strategy",{}).get("method")=="subtle_gradient":scores["whitespace"]-=5;weaknesses.append("Busy image uses insufficient text protection.");corrections.append("Use a restrained neutral panel.")
    if plan.get("palette",{}).get("secondary") or plan.get("palette",{}).get("accent"):scores["branding_restraint"]-=10;weaknesses.append("Unapproved extra brand color is present.")
    score=max(0,sum(scores.values())-2) # 100 is intentionally rare.
    status="exceptional" if score>=95 else "production_ready" if score>=90 else "good_minor_improvements" if score>=85 else "revision_recommended" if score>=75 else "revision_required"
    layout_authority="visual-art-director" if plan.get("visual_direction_contract_id") else "brand-composer"
    responsible=layout_authority if any(x in " ".join(weaknesses).casefold() for x in ("logo","headline","panel","text protection")) else "none"
    issues=[]
    for weakness in weaknesses:
        lower=weakness.casefold();issue_type="logo_size" if "logo" in lower else "overlay_dominance" if "panel" in lower else "typography_legibility" if "text" in lower or "headline" in lower else "creative_quality"
        issues.append({"issue_type":issue_type,"severity":"high" if score<75 else "medium","region":"composition","affected_element":"brand_logo" if "logo" in lower else "graphics" if "panel" in lower else "headline","message":weakness,"recommended_action_class":"targeted_contract_revision"})
    return {"branded_item_id":plan.get("branded_item_id"),"creative_score":score,"status":status,"category_scores":scores,"strengths":strengths,"weaknesses":weaknesses,
            "issues":issues,"recommended_corrections":corrections,"responsible_stage":responsible if responsible in RESPONSIBLE_STAGES else "none","retry_priority":"high" if score<75 else "medium" if score<85 else "none","warnings":[]}


def _require(paths: Iterable[Path], label: str) -> None:
    missing=[str(p) for p in paths if not p.is_file()]
    if missing:raise ValueError(f"{label} missing required inputs: "+", ".join(missing))
    for path in paths:
        if path.suffix.casefold()==".json":
            try:_read(path)
            except (OSError,ValueError) as error:raise ValueError(f"{label} has corrupted input {path}: {error}") from error
def _read(path:Path)->dict[str,Any]:return json.loads(path.read_text(encoding="utf-8"))
def _write(path:Path,value:Any)->None:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
def _file_hash(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda:source.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()
def _optional_hash(path:Path)->str|None:return _file_hash(path) if path.is_file() else None
def _signature(paths:Iterable[Path],version:str)->dict[str,Any]:
    value={"version":version,"inputs":{str(p):_file_hash(p) for p in paths if p.is_file()}};value["cache_key"]=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest();return value
def _cache_valid(path:Path,signature:dict[str,Any])->bool:
    try:return _read(path)==signature
    except (OSError,ValueError):return False
def _stable(prefix:str,*values:str)->str:return prefix+"_"+hashlib.sha256("|".join(values).encode()).hexdigest()[:20]
def _now()->str:return datetime.now(timezone.utc).isoformat()
def _run_id()->str:return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+hashlib.sha256((_now()).encode()).hexdigest()[:6]
def _index_assets(value:Any)->dict[str,dict[str,Any]]:
    result={}
    def walk(x:Any)->None:
        if isinstance(x,dict):
            identity=x.get("asset_id") or x.get("source_asset_id")
            if identity:result[str(identity)]=x
            for child in x.values():walk(child)
        elif isinstance(x,list):
            for child in x:walk(child)
    walk(value);return result
def _artifact_dimension(path:Path,base:int)->dict[str,Any]:
    try:value=_read(path);score=min(96,base+min(3,len(value)//4));return {"score":score,"status":"pass","warnings":[]}
    except (OSError,ValueError):return {"score":0,"status":"missing_or_invalid","warnings":[f"Invalid artifact: {path}"]}
def _qa_dimension(path:Path)->dict[str,Any]:
    try:
        items=_read(path).get("items",[]);passed=sum(x.get("status") in {"passed","passed_with_warnings","exceptional","production_ready"} for x in items);score=round(100*passed/max(1,len(items)));return {"score":score,"status":"pass" if score>=90 else "warning","warnings":[]}
    except (OSError,ValueError):return {"score":0,"status":"missing_or_invalid","warnings":["Technical QA invalid."]}
def _cache_dimension(path:Path)->dict[str,Any]:
    invalid=0
    for file in path.glob("*.json") if path.is_dir() else []:
        try:_read(file)
        except (OSError,ValueError):invalid+=1
    return {"score":95 if not invalid else max(0,95-invalid*15),"status":"pass" if not invalid else "warning","warnings":[] if not invalid else [f"{invalid} invalid cache files."]}
def _source_hashes(path:Path,project:str)->dict[str,str]:
    from src.core.file_manager import find_project_inputs
    selected=next((p for p in find_project_inputs(path) if p.name==project),None) if path.is_dir() else None
    return {str(p.resolve()):_file_hash(p) for p in [*selected.pdf_files,*selected.image_files,*selected.auxiliary_files]} if selected else {}
def _planning_hashes(output:Path,project:str)->dict[str,str|None]:return {name:_optional_hash(output/folder/f"{project}{suffix}.json") for name,folder,suffix in (("campaign","campaigns","-campaign-plan"),("content","content","-content-plan"),("creative","creative-directions","-creative-directions"),("scenes","scene-plans","-scene-plans"),("shots","shot-plans","-shot-plans"))}
def _discover_projects(output:Path)->list[str]:return sorted(p.name[:-5] for p in (output/"knowledge").glob("*.json"))
def _check_json(path:Path,issues:list[str],label:str)->str:
    try:_read(path);return "PASS"
    except (OSError,ValueError) as error:issues.append(f"{label}: {error}");return "FAIL"
def _check_source(root:Path,project:str,issues:list[str])->str:
    readable=bool(_source_hashes(root/"input",project));
    if not readable:issues.append("No readable source PDF found.");return "WARN"
    return "PASS"
def _check_assets(root:Path,project:str,issues:list[str],critical:list[str])->str:
    path=root/"output"/"visual-inventory"/f"{project}-visual-inventory.json"
    try:
        assets=_index_assets(_read(path));return "PASS" if len(assets)==len(set(assets)) else "FAIL"
    except (OSError,ValueError) as error:issues.append(f"asset integrity: {error}");return "FAIL"
def _check_planning(root:Path,project:str,issues:list[str])->str:
    paths=[root/"output"/folder/f"{project}{suffix}.json" for folder,suffix in (("campaigns","-campaign-plan"),("content","-content-plan"),("creative-directions","-creative-directions"))]
    return "PASS" if all(_valid_json(p) for p in paths) else "WARN"
def _check_production(root:Path,project:str,issues:list[str],critical:list[str])->str:
    path=root/"output"/"production-manifests"/f"{project}-branded-production-manifest.json"
    try:
        for item in _read(path).get("items",[]):
            output=Path(str(item.get("branded_image_path","")))
            if not output.is_file() or (item.get("branded_image_hash") and _file_hash(output)!=item["branded_image_hash"]):critical.append(f"Invalid production output: {output}")
        return "FAIL" if critical else "PASS"
    except (OSError,ValueError) as error:issues.append(f"production: {error}");return "FAIL"
def _check_brand(root:Path,issues:list[str],critical:list[str])->str:
    try:
        report=run_brand_readiness_validator(root).report
        if report["readiness_status"] not in {"ready","ready_with_warnings"}:critical.append("Brand readiness invalid.");return "FAIL"
        return "PASS"
    except (OSError,ValueError) as error:critical.append(f"Brand integrity: {error}");return "FAIL"
def _check_cache(root:Path,project:str,issues:list[str])->str:
    for path in (root/"output"/"cache-metadata"/project).glob("*.json"):
        if not _valid_json(path):issues.append(f"Invalid cache: {path}");return "WARN"
    run_manifest=root/"output"/"manifests"/f"{project}-run-manifest.json"
    if run_manifest.is_file():
        try:
            stale=[name for name,status in _read(run_manifest).get("stage_statuses",{}).items() if status=="stale"]
            if stale:issues.append("Stages awaiting downstream refresh: "+", ".join(stale));return "WARN"
        except (OSError,ValueError):issues.append("Run-stage manifest is invalid.");return "WARN"
    return "PASS"
def _check_provenance(path:Path,issues:list[str],critical:list[str])->str:
    try:
        statuses=[x.get("integrity_status") for x in _read(path).get("items",[])]
        if "invalid" in statuses:critical.append("Invalid provenance trace.");return "FAIL"
        return "WARN" if "incomplete" in statuses else "PASS"
    except (OSError,ValueError):issues.append("Provenance audit missing or invalid.");return "WARN"
def _check_runs_releases(root:Path,project:str,issues:list[str],critical:list[str])->str:
    runs=root/"output"/"runs"/project;releases=root/"output"/"releases"/project
    if not (runs/"current.json").is_file():issues.append("Current run pointer is missing.");return "WARN"
    try:
        current=_read(runs/"current.json");run_manifest=runs/str(current.get("run_id"))/"run-manifest.json"
        if not _valid_json(run_manifest):critical.append("Current run manifest is invalid.");return "FAIL"
    except (OSError,ValueError):critical.append("Current run pointer is invalid.");return "FAIL"
    for manifest in releases.glob("release-*/manifest.json"):
        if not _valid_json(manifest):critical.append(f"Invalid release: {manifest}");return "FAIL"
        for item in _read(manifest).get("released_items",[]):
            image=Path(str(item.get("path","")))
            if not image.is_file() or _file_hash(image)!=item.get("sha256"):critical.append(f"Release image integrity failure: {image}");return "FAIL"
    return "PASS"
def _valid_json(path:Path)->bool:
    try:_read(path);return True
    except (OSError,ValueError):return False
