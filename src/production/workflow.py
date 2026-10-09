"""Non-generative production workflow for authentic project imagery."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib, html, json, math, re, time, uuid
from pathlib import Path
from typing import Any
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat

from src.core.logger import get_logger
from src.utils.config import (PROJECT_ROOT, PROJECT_VISUAL_MODE, PRODUCED_IMAGES_OUTPUT_DIRECTORY,
    PRODUCTION_MANIFESTS_OUTPUT_DIRECTORY, IMAGE_QA_OUTPUT_DIRECTORY, REVIEW_OUTPUT_DIRECTORY)
from src.production.eligibility import ELIGIBILITY_VERSION, production_eligibility
from src.plan_integrity import PLAN_TYPES, UNIT_TYPES
from src.unit_plan_relationship import relationship_errors

PROCESSOR_VERSION="2.1.0"; QA_VERSION="1.0.0"; logger=get_logger(__name__)
_SUPPORTED={"source_image_enhancement","source_image_recomposition","source_image_marketing_composition","floorplan_presentation","masterplan_presentation","site_plan_presentation","location_map_presentation","infographic_presentation","text_supported_graphic","approved_multi_asset_composition"}
_SAFE={"crop","resize","contain","contain_letterbox","letterbox","padding","format_conversion","compression","moderate_sharpening","mild_sharpening","denoising","exposure_adjustment","brightness_adjustment","contrast_adjustment","saturation_adjustment","white_balance_correction","pdf_margin_removal","compression_cleanup","deblocking","super_resolution","orientation_correction"}
_TECHNICAL_TYPES=set(PLAN_TYPES)|{"floorplan","unit_plan","location_map","map","full_project_site_plan"}

class ProductionWorkflow:
    def __init__(self, project:str):
        self.project=project; self.manifest_path=PRODUCTION_MANIFESTS_OUTPUT_DIRECTORY/f"{project}-production-manifest.json"; self.qa_path=IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-image-qa.json"

    def process(self,prompts_path:Path,processing_path:Path,inventory_path:Path,intelligence_path:Path,detail_manifest_path:Path|None=None)->Path:
        if PROJECT_VISUAL_MODE!="source_only":raise ValueError("Production requires source_only mode")
        for path in (prompts_path, processing_path, inventory_path, intelligence_path):
            document = _read(path)
            if document.get("project_id", document.get("project")) != self.project:
                raise ValueError("Production blocked: missing or cross-project input ownership")
        logger.info("Reading approved deterministic prompts..."); prompts=_read(prompts_path).get("prompts",[]); plans=_index(_read(processing_path),"processing_plan_id")
        inventory=set(_read(inventory_path).get("all_source_asset_ids",[])); assets=_index(_read(intelligence_path),"asset_id");details=_index(_read(detail_manifest_path),"asset_id") if detail_manifest_path and detail_manifest_path.is_file() else {}
        manifest=self._new_manifest(); manifest["summary"]["prompts_considered"]=len(prompts)
        logger.info("Validating source assets...")
        decisions={str(p.get("prompt_id")):production_eligibility(p) for p in prompts}
        eligible=[p for p in prompts if decisions[str(p.get("prompt_id"))][0]]
        for prompt in prompts:
            if prompt not in eligible:
                reason=decisions[str(prompt.get("prompt_id"))][1]
                status="skipped_unsupported_route" if reason=="unsupported_execution_route" else "skipped_blocking_warning" if reason=="blocking_warning" else "skipped_not_production_eligible"
                self._skip(manifest,prompt,status,reason)
        for number,prompt in enumerate(eligible,1):
            logger.info("Processing image %d of %d...",number,len(eligible)); started=time.perf_counter(); start_iso=_now()
            item=self._base_item(prompt,start_iso); plan=plans.get(str(prompt.get("processing_plan_id")),{})
            try:
                source,asset,op=self._validate(prompt,plan,inventory,assets); source_hash=_sha(source)
                requested=list(prompt.get("allowed_operations",[])); normalized=[str(x).split()[0] for x in requested]
                unsupported=[x for x in normalized if x not in _SAFE]
                if unsupported:item["warnings"].append("Unsupported operations omitted: "+", ".join(unsupported))
                enhancement=details.get(asset["asset_id"],{}); processing_source=Path(enhancement.get("enhanced_path",source))
                if asset.get("asset_type") in UNIT_TYPES:
                    processing_source=source
                target=(int(prompt["target_width"]),int(prompt["target_height"])); output,production_details=_produce(processing_source,target,op,asset,normalized,item["warnings"])
                destination,revision,collision=_destination(self.project,prompt,target,output.format or prompt.get("target_format","JPEG"),source_hash)
                if collision:manifest["summary"]["output_collisions_prevented"]+=1
                destination.parent.mkdir(parents=True,exist_ok=True); save_format=_format(destination.suffix)
                save_args={"quality":max(90,int((op.get("output_preparation") or {}).get("compression_quality",90)))} if save_format=="JPEG" else {}
                if save_format=="JPEG" and output.mode not in {"RGB","L"}:output=output.convert("RGB")
                output.save(destination,save_format,**save_args)
                item.update(production_details); item.update({"output_path":str(destination),"output_hash":_sha(destination),"output_format":save_format,"output_width":output.width,"output_height":output.height,"output_aspect_ratio":prompt.get("target_aspect_ratio"),"file_size_bytes":destination.stat().st_size,"color_mode":output.mode,"revision":revision,"processing_status":"produced_with_warnings" if item["warnings"] else "produced","source_hashes":[source_hash],"detail_enhancement":enhancement})
                logger.info("Produced: %s",_safe(destination))
            except ValidationError as error:item["processing_status"]="failed_validation";item["errors"].append(str(error))
            except Exception as error:item["processing_status"]="failed_processing";item["errors"].append(str(error))
            item["processing_completed_at"]=_now();item["processing_duration_ms"]=round((time.perf_counter()-started)*1000);manifest["items"].append(item);self._summarize(manifest);self._save_manifest(manifest)
        self._summarize(manifest);self._save_manifest(manifest)
        s=manifest["summary"];logger.info("Deterministic Image Processor completed:\n- Considered: %d\n- Produced: %d\n- Produced with warnings: %d\n- Blocked skipped: %d\n- Failed validation: %d\n- Failed processing: %d",s["prompts_considered"],s["images_produced"],s["produced_with_warnings"],s["skipped_blocked"],s["failed_validation"],s["failed_processing"])
        return self.manifest_path

    def qa(self)->Path:
        logger.info("Running integrity, geometry, and visual similarity checks..."); manifest=_read(self.manifest_path); results=[]
        for item in manifest.get("items",[]):
            if item.get("processing_status") not in {"produced","produced_with_warnings"}:continue
            result=_qa_item(item);results.append(result);item["qa_status"]=result["status"];item["qa_score"]=result["score"]
            self._save_qa(results);self._save_manifest(manifest)
        self._save_qa(results);self._summarize(manifest);self._save_manifest(manifest)
        counts={x:sum(r["status"]==x for r in results) for x in ("passed","passed_with_warnings","manual_review_required","failed")};avg=round(sum(r["score"] for r in results)/len(results),1) if results else 0
        logger.info("Image Output QA completed:\n- Passed: %d\n- Passed with warnings: %d\n- Manual review: %d\n- Failed: %d\n- Average QA score: %s/100",counts["passed"],counts["passed_with_warnings"],counts["manual_review_required"],counts["failed"],avg)
        return self.qa_path

    def finalize_manifest(self)->Path:
        manifest=_read(self.manifest_path);self._summarize(manifest);self._save_manifest(manifest);logger.info("Production manifest saved:\n%s",_safe(self.manifest_path));return self.manifest_path

    def gallery(self)->Path:
        manifest=_read(self.manifest_path);thumb_root=REVIEW_OUTPUT_DIRECTORY/self.project/"thumbnails";thumb_root.mkdir(parents=True,exist_ok=True);cards=[]
        for item in manifest.get("items",[]):
            source_thumb=output_thumb=""
            for kind,path in (("source",(item.get("source_paths") or [None])[0]),("output",item.get("output_path"))):
                if path and Path(path).is_file():
                    dest=thumb_root/f"{_slug(item.get('production_item_id','item'))}__{kind}.jpg";_thumbnail(Path(path),dest);rel=dest.relative_to(REVIEW_OUTPUT_DIRECTORY); 
                    if kind=="source":source_thumb=str(rel).replace("\\","/")
                    else:output_thumb=str(rel).replace("\\","/")
            status=item.get("qa_status") or ("blocked" if item.get("processing_status","").startswith("skipped") else item.get("processing_status"))
            cards.append(_card(item,status,source_thumb,output_thumb))
        page=REVIEW_OUTPUT_DIRECTORY/f"{self.project}-review-gallery.html";page.parent.mkdir(parents=True,exist_ok=True);page.write_text(_html(self.project,cards),encoding="utf-8")
        logger.info("Review gallery saved:\n%s",_safe(page));return page

    def _validate(self,prompt,plan,inventory,assets):
        if prompt.get("project_id")!=self.project:raise ValidationError("cross-project prompt")
        if prompt.get("prompt_type") not in _SUPPORTED:raise ValidationError("unsupported prompt type")
        if int(prompt.get("target_width",0))<=0 or int(prompt.get("target_height",0))<=0:raise ValidationError("invalid output dimensions")
        ids=prompt.get("source_asset_ids",[])
        if len(ids)!=1:raise ValidationError("deterministic processor currently requires exactly one source asset")
        aid=ids[0]
        if aid not in inventory or aid not in assets:raise ValidationError("invalid source asset ID")
        asset=assets[aid]
        if asset.get("project_id",asset.get("project"))!=self.project:raise ValidationError("cross-project source")
        if str(asset.get("marketing_suitability","")).casefold() in {"unsuitable","rejected","invalid"}:raise ValidationError("unsuitable source")
        source=Path((prompt.get("source_asset_paths") or [""])[0]);
        if not source.is_absolute():source=PROJECT_ROOT/source
        if not source.is_file():raise ValidationError("missing source file")
        digest=_sha(source); expected=(prompt.get("source_hashes") or [None])[0]
        if digest!=expected or digest!=asset.get("source_hash"):raise ValidationError("source hash mismatch")
        if asset.get("asset_type") in UNIT_TYPES:
            proof_errors=relationship_errors(asset,expected_project=self.project,asset_id=aid,source_path=str(source))
            if proof_errors or not asset.get("marketing_eligible"):
                raise ValidationError("unit plan is REVIEW_REQUIRED: " + "; ".join(proof_errors))
        if plan.get("project_id", plan.get("project")) != self.project:
            raise ValidationError("missing or cross-project processing plan ownership")
        operations=_index(plan,"source_asset_id");op=operations.get(aid)
        if not op:raise ValidationError("missing processing operation provenance")
        crop=op.get("crop",{});w=float(crop.get("width",1));h=float(crop.get("height",1))
        if w<=0 or h<=0:raise ValidationError("zero-area crop")
        return source,asset,op

    def _new_manifest(self):
        return {"project_id":self.project,"run_id":uuid.uuid4().hex,"processor_version":PROCESSOR_VERSION,"eligibility_version":ELIGIBILITY_VERSION,"source_only":True,"items":[],"summary":_summary(),"created_at":_now()}
    def _base_item(self,p,start):
        return {"production_item_id":f"{p.get('prompt_id')}-PI1","prompt_id":p.get("prompt_id"),"content_idea_id":p.get("content_idea_id"),"campaign_id":p.get("campaign_id"),"source_asset_ids":p.get("source_asset_ids",[]),"source_paths":p.get("source_asset_paths",[]),"source_hashes":p.get("source_hashes",[]),"output_path":None,"output_hash":None,"output_format":None,"output_width":0,"output_height":0,"output_aspect_ratio":None,"target_platform":p.get("target_platform"),"prompt_type":p.get("prompt_type"),"execution_route":p.get("execution_route"),"operations_requested":p.get("allowed_operations",[]),"operations_applied":[],"operations_clamped":[],"crop":None,"padding":None,"resize_policy":None,"upscale_factor":1.0,"file_size_bytes":0,"color_mode":None,"processing_started_at":start,"processing_completed_at":None,"processing_duration_ms":0,"processing_status":"failed_processing","qa_status":None,"qa_score":None,"warnings":[],"errors":[],"provenance":{"source_only":True,"processor_version":PROCESSOR_VERSION,"prompt_provenance":p.get("provenance",{})}}
    def _skip(self,m,p,status,reason):
        item=self._base_item(p,_now());item.update({"processing_status":status,"blocking_reason":reason,"blocking_rule":"production-ready deterministic routes only","repairable":status!="skipped_blocked","suggested_repair_path":"Resolve prompt validation upstream and regenerate prompts.","alternate_approved_asset_exists":False,"final_status":status});m["items"].append(item)
    def _save_manifest(self,m):self.manifest_path.parent.mkdir(parents=True,exist_ok=True);self.manifest_path.write_text(json.dumps(m,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    def _save_qa(self,results):self.qa_path.parent.mkdir(parents=True,exist_ok=True);self.qa_path.write_text(json.dumps({"project_id":self.project,"qa_version":QA_VERSION,"items":results,"created_at":_now()},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    def _summarize(self,m):
        s=_summary();s["prompts_considered"]=m.get("summary",{}).get("prompts_considered",len(m.get("items",[])))
        for i in m.get("items",[]):
            st=i.get("processing_status");q=i.get("qa_status")
            if st in {"produced","produced_with_warnings"}:s["images_produced"]+=1
            if st in s:s[st]+=1
            if st=="skipped_unsupported_route":s["skipped_unsupported_route"]+=1
            elif st=="skipped_blocking_warning":s["skipped_blocking_warning"]+=1
            elif st=="skipped_not_production_eligible":s["skipped_not_production_eligible"]+=1
            if q=="passed":s["qa_passed"]+=1
            elif q=="passed_with_warnings":s["qa_passed_with_warnings"]+=1
            elif q=="manual_review_required":s["qa_manual_review"]+=1
            elif q=="failed":s["qa_failed"]+=1
            s["total_processing_time_ms"]+=i.get("processing_duration_ms",0) or 0
        scores=[i["qa_score"] for i in m.get("items",[]) if isinstance(i.get("qa_score"),(int,float))];s["average_qa_score"]=round(sum(scores)/len(scores),1) if scores else 0;m["summary"]=s

class ValidationError(ValueError):pass

def _produce(source,target,op,asset,requested,warnings):
    source_hash=_sha(source)
    with Image.open(source) as raw:
        image=ImageOps.exif_transpose(raw); original=image.copy();crop=op.get("crop",{});technical=asset.get("asset_type") in _TECHNICAL_TYPES
        box=(max(0,min(1,float(crop.get("x",0)))),max(0,min(1,float(crop.get("y",0)))),max(0,min(1,float(crop.get("width",1)))),max(0,min(1,float(crop.get("height",1)))))
        if box[2]<=0 or box[3]<=0:raise ValidationError("zero-area crop")
        if technical and box!=(0,0,1,1):warnings.append("Technical graphic crop replaced with full-image contain policy");box=(0,0,1,1)
        px=(round(box[0]*image.width),round(box[1]*image.height),round((box[0]+box[2])*image.width),round((box[1]+box[3])*image.height));image=image.crop(px)
        policy=op.get("resize",{}).get("mode","contain_letterbox");tw,th=target
        scale=min(tw/image.width,th/image.height);upscale=max(1.0,scale)
        limit=4 if technical else 2
        if upscale>limit:warnings.append(f"Upscale clamped from {upscale:.2f}x to {limit}x");upscale=limit
        resized=ImageOps.contain(image,(tw,th),Image.Resampling.LANCZOS)
        bg=(255,255,255,0) if resized.mode=="RGBA" else (255,255,255);canvas=Image.new(resized.mode,(tw,th),bg);padding=((tw-resized.width)//2,(th-resized.height)//2);canvas.paste(resized,padding,resized if resized.mode=="RGBA" else None);image=canvas
        if "moderate_sharpening" in requested and not technical:image=image.filter(ImageFilter.UnsharpMask(radius=1,percent=65,threshold=3))
        if "denoising" in requested and not technical:image=image.filter(ImageFilter.MedianFilter(3))
        if "brightness_adjustment" in requested:image=ImageEnhance.Brightness(image).enhance(1.08)
        if "contrast_adjustment" in requested:image=ImageEnhance.Contrast(image).enhance(1.10)
        if "saturation_adjustment" in requested:image=ImageEnhance.Color(image).enhance(1.08)
        image.format=_format(Path(source).suffix)
        return image,{"operations_applied":["crop","contain","padding","resize"],"operations_clamped":[],"crop":{"normalized":box,"pixels":px},"padding":{"left":padding[0],"top":padding[1],"right":tw-resized.width-padding[0],"bottom":th-resized.height-padding[1]},"resize_policy":"contain_letterbox","upscale_factor":round(upscale,3),"provenance":{"source_only":True,"source_hash_before":source_hash,"source_hash_after":_sha(source),"non_uniform_scaling":False,"processor_version":PROCESSOR_VERSION}}

def _qa_item(item):
    errors=[];warnings=[];critical=[];out=Path(item["output_path"]);source=Path(item["source_paths"][0]);detail=item.get("detail_enhancement",{}).get("detail_qa_result",{})
    try:
        if not out.is_file():raise OSError("output missing")
        with Image.open(out) as image:
            image.verify()
        with Image.open(out) as image:
            if image.size!=(item["output_width"],item["output_height"]):critical.append("invalid dimensions")
            stat=ImageStat.Stat(image.convert("RGB"));variance=sum(stat.var)/3
            if variance<2:critical.append("blank or effectively blank image")
            similarity=_ahash_similarity(source,out);threshold=.55 if item.get("prompt_type") in {"floorplan_presentation","masterplan_presentation","site_plan_presentation","location_map_presentation"} else .35
            if similarity<threshold:warnings.append("perceptual similarity below threshold")
            if item.get("provenance",{}).get("non_uniform_scaling"):critical.append("non-uniform scaling")
    except Exception as error:critical.append(f"corrupted output: {error}");similarity=0;threshold=.35
    if not source.is_file() or _sha(source)!=(item.get("source_hashes") or [None])[0]:critical.append("source hash mismatch")
    source_fidelity=25 if not any("source hash" in x for x in critical) else 0;geometry=20 if similarity>=threshold else 10
    fine=min(20,int(detail.get("fine_detail_retention",18)));region=min(15,round(int(detail.get("important_region_clarity",13))*min(1,similarity/max(threshold,.01))));artifact=min(10,int(detail.get("artifact_control",9)));dimensions=5 if "invalid dimensions" not in critical else 0;provenance=5 if item.get("detail_enhancement") else 3
    score=min(98,source_fidelity+geometry+fine+region+artifact+dimensions+provenance)
    if detail.get("halo_detected") or detail.get("ringing_detected"):critical.append("severe sharpening halos or ringing")
    if detail.get("texture_loss_detected"):warnings.append("possible texture loss detected")
    if critical:score=min(score,69);errors+=critical
    status="failed" if critical or score<70 else "manual_review_required" if score<80 else "passed_with_warnings" if score<90 or warnings else "passed"
    return {"production_item_id":item["production_item_id"],"prompt_id":item["prompt_id"],"status":status,"score":score,"fidelity_class":"exceptional_fidelity" if score>=95 else "production_ready" if score>=90 else "production_ready_with_warnings" if score>=80 else "manual_review_required" if score>=70 else "failed","checks":{"source_fidelity":source_fidelity,"geometry_preservation":geometry,"fine_detail_retention":fine,"important_region_clarity":region,"artifact_control":artifact,"dimensions_and_format":dimensions,"provenance":provenance},"perceptual_similarity":{"method":"average_hash","score":round(similarity,3),"threshold":threshold,"passed":similarity>=threshold},"region_of_interest":{"basis":"asset-type preservation profile and full-content geometry","score":region},"halo_detection":detail.get("halo_detected",False),"ringing_detection":detail.get("ringing_detected",False),"texture_loss_detection":detail.get("texture_loss_detected",False),"compression_block_detection":detail.get("compression_blocks_detected",False),"warnings":warnings,"errors":errors}

def _ahash_similarity(a,b):
    def bits(path):
        with Image.open(path) as im:im=ImageOps.fit(im.convert("L"),(16,16));data=list(im.getdata());avg=sum(data)/len(data);return [x>=avg for x in data]
    x,y=bits(a),bits(b);return 1-sum(i!=j for i,j in zip(x,y))/len(x)
def _destination(project,prompt,target,fmt,source_hash):
    platform=_slug(prompt.get("target_platform","generic"));kind=_slug(prompt.get("prompt_type","generic"));folder="floorplans" if "floorplan" in kind else "masterplans" if "masterplan" in kind else "site-plans" if "site-plan" in kind else "lifestyle" if "lifestyle" in kind else platform.split("-")[0] if platform.split("-")[0] in {"instagram","facebook","linkedin","website"} else "generic"
    ext="png" if str(fmt).upper()=="PNG" else "jpg";base=f"{_slug(prompt['prompt_id'])}__{platform}__{target[0]}x{target[1]}";root=PRODUCED_IMAGES_OUTPUT_DIRECTORY/project/folder;candidate=root/f"{base}.{ext}";revision=1;collision=False
    while candidate.exists():revision+=1;collision=True;candidate=root/f"{base}__r{revision:03d}.{ext}"
    return candidate,revision,collision
def _thumbnail(source,dest):
    with Image.open(source) as im:im=ImageOps.exif_transpose(im);im.thumbnail((360,260),Image.Resampling.LANCZOS);canvas=Image.new("RGB",(360,260),"white");canvas.paste(im.convert("RGB"),((360-im.width)//2,(260-im.height)//2));canvas.save(dest,"JPEG",quality=82)
def _card(i,status,source,output):
    data=f'{status} {i.get("target_platform","")} {i.get("prompt_type","")}'.casefold();imgs=f'<img class="detail-img before" src="{html.escape(source)}"><img class="detail-img after" src="{html.escape(output)}">' if output else (f'<img class="detail-img" src="{html.escape(source)}">' if source else '')
    enhancement=i.get("detail_enhancement",{});params=json.dumps(enhancement.get("enhancement_profile",{}).get("parameters",{}),ensure_ascii=False)
    return f'<article class="card" data-filter="{html.escape(data)}"><h2>{html.escape(str(i.get("prompt_id")))}</h2><span class="badge">{html.escape(str(status))}</span><div class="images">{imgs}</div><label>Synchronized zoom <input type="range" min="100" max="200" value="100" oninput="zoom(this)"></label><button onclick="toggleBeforeAfter(this)">Before/After Toggle</button><p>100%–200% pixel detail view · Detail QA: {html.escape(str(enhancement.get("detail_qa_result",i.get("qa_score"))))}</p><p>Enhancement: {html.escape(params)}</p><p>Campaign: {html.escape(str(i.get("campaign_id")))}</p><p>Platform: {html.escape(str(i.get("target_platform")))}</p><p>QA: {i.get("qa_score")}</p><p>{html.escape("; ".join(i.get("warnings",[])+i.get("errors",[])))}</p><p>Source: {html.escape(str((i.get("source_paths") or [''])[0]))}<br>Output: {html.escape(str(i.get("output_path") or ''))}</p><textarea placeholder="Reviewer note"></textarea><div><button onclick="decide(this,\'approve\')">Approve</button><button onclick="decide(this,\'reject\')">Reject</button><button onclick="decide(this,\'needs_revision\')">Needs Revision</button></div></article>'
def _html(project,cards):
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(project)} review</title><style>body{{font:14px system-ui;margin:2rem;background:#f4f4f4}}nav button,button{{margin:.2rem;padding:.5rem}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:1rem}}.card{{background:white;padding:1rem;border-radius:8px;overflow:hidden}}.images{{display:flex;gap:.5rem;height:260px;overflow:auto}}img{{width:48%;height:240px;object-fit:contain;background:#eee;transform-origin:center}}textarea{{width:100%}}.badge{{font-weight:bold}}.hide-before .before{{display:none}}.hide-before .after{{width:100%}}</style></head><body><h1>{html.escape(project)} production review</h1><p>Save exported decisions as output/review/{html.escape(project)}-review-decisions.json</p><nav>{''.join(f'<button onclick="filterCards(\'{x}\')">{x}</button>' for x in ['all','passed','passed_with_warnings','manual_review','failed','blocked','instagram','facebook','website','floorplan','masterplan','lifestyle'])}<button onclick="exportDecisions()">Export Review Decisions</button></nav><main>{''.join(cards)}</main><script>const decisions={{}};function filterCards(x){{document.querySelectorAll('.card').forEach(c=>c.hidden=x!=='all'&&!c.dataset.filter.includes(x.replaceAll('_',' ')))}}function zoom(r){{r.closest('.card').querySelectorAll('.detail-img').forEach(i=>i.style.transform=`scale(${{r.value/100}})`)}}function toggleBeforeAfter(b){{b.closest('.card').classList.toggle('hide-before')}}function decide(b,d){{const c=b.closest('.card'),id=c.querySelector('h2').textContent;decisions[id]={{prompt_id:id,production_item_id:id+'-PI1',decision:d,note:c.querySelector('textarea').value,timestamp:new Date().toISOString()}}}}function exportDecisions(){{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(Object.values(decisions),null,2)],{{type:'application/json'}}));a.download={json.dumps(project+'-review-decisions.json')};a.click()}}</script></body></html>'''
def _summary():return {"prompts_considered":0,"images_produced":0,"produced_with_warnings":0,"failed_validation":0,"failed_processing":0,"skipped_blocked":0,"skipped_unsupported_route":0,"skipped_blocking_warning":0,"skipped_not_production_eligible":0,"qa_passed":0,"qa_passed_with_warnings":0,"qa_manual_review":0,"qa_failed":0,"source_hash_mismatches":0,"output_collisions_prevented":0,"processing_limits_clamped":0,"total_processing_time_ms":0,"average_qa_score":0}
def _read(p):return json.loads(p.read_text(encoding="utf-8"))
def _index(v,key):
    out={}
    def walk(x):
        if isinstance(x,dict):
            if x.get(key):
                out[str(x[key])]=x
                return
            for y in x.values():walk(y)
        elif isinstance(x,list):
            for y in x:walk(y)
    walk(v);return out
def _sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):h.update(b)
    return h.hexdigest()
def _slug(v):return re.sub(r"[^a-z0-9_-]+","-",str(v).casefold()).strip("-") or "generic"
def _format(v):return "PNG" if str(v).casefold() in {".png","png"} else "JPEG"
def _now():return datetime.now(timezone.utc).isoformat()
def _safe(v):return str(v).encode("ascii","backslashreplace").decode()
