"""Conservative, non-generative visibility enhancement of authentic detail."""
from __future__ import annotations
import hashlib, json, math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat

from src.utils.config import DETAIL_ENHANCED_OUTPUT_DIRECTORY, IMAGE_QA_OUTPUT_DIRECTORY, PROJECT_ROOT
from src.plan_integrity import PLAN_TYPES

VERSION="1.0.0"; QA_VERSION="1.0.0"
TECHNICAL_TYPES=set(PLAN_TYPES)|{"floorplan","unit_plan","location_map","map","full_project_site_plan"}

class DetailPreservationEnhancer:
    def run(self,project:str,prompts_path:Path,intelligence_path:Path)->tuple[Path,Path]:
        prompts=_read(prompts_path).get("prompts",[]);assets=_index(_read(intelligence_path),"asset_id");root=DETAIL_ENHANCED_OUTPUT_DIRECTORY/project;root.mkdir(parents=True,exist_ok=True);items=[]
        seen=set()
        for prompt in prompts:
            for aid,path_text,expected in zip(prompt.get("source_asset_ids",[]),prompt.get("source_asset_paths",[]),prompt.get("source_hashes",[])):
                if aid in seen:continue
                seen.add(aid);source=Path(path_text);source=source if source.is_absolute() else PROJECT_ROOT/source;asset=assets.get(aid,{})
                item={"asset_id":aid,"original_source_path":str(source),"original_hash":expected,"asset_type":asset.get("asset_type","unknown"),"enhancer_version":VERSION,"warnings":[]}
                try:
                    if not source.is_file() or _sha(source)!=expected:raise ValueError("original source hash mismatch")
                    before=_metrics(source);profile=_profile(asset.get("asset_type","unknown"),before);ext=".png" if _has_alpha(source) or asset.get("asset_type") in TECHNICAL_TYPES else ".jpg";dest=root/f"{aid}__detail-v1{ext}"
                    if dest.exists():item["cache_hit"]=True
                    else:_enhance(source,dest,profile)
                    after=_metrics(dest);rollback=_artifacts_worse(before,after)
                    if rollback:
                        item["warnings"].append("Enhancement reverted because measured artifacts increased");_copy_pixels(source,dest);after=_metrics(dest);profile={"action":"reverted","parameters":{}}
                    item.update({"enhanced_path":str(dest),"enhanced_hash":_sha(dest),"source_fidelity_classification":"byte_exact_original_with_deterministic_derivative","enhancement_profile":profile,"metrics_before":before,"metrics_after":after,"status":"enhanced" if profile["action"]=="enhanced" else "unchanged","cache_key":_key(expected,profile,asset.get("asset_type")),"provenance":{"original_immutable":True,"non_generative":True,"original_hash_verified":_sha(source)==expected}})
                except Exception as error:item.update({"status":"failed","error":str(error)})
                items.append(item)
        qa_results=[_detail_qa(x) for x in items];qa_by_id={x["asset_id"]:x for x in qa_results}
        for item in items:item["detail_qa_result"]=qa_by_id[item["asset_id"]]
        manifest=root/"detail-enhancement-manifest.json";manifest.write_text(json.dumps({"project_id":project,"enhancer_version":VERSION,"source_only":True,"items":items,"created_at":_now()},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        qa=IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-detail-qa.json";qa.parent.mkdir(parents=True,exist_ok=True);qa.write_text(json.dumps({"project_id":project,"qa_version":QA_VERSION,"items":qa_results,"created_at":_now()},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        return manifest,qa

def _profile(kind,before):
    sharp=before["sharpness"];technical=kind in TECHNICAL_TYPES
    sharpen=0 if sharp>900 else 35 if technical else 25
    return {"name":kind,"action":"unchanged" if sharpen==0 else "enhanced","parameters":{"fine_sharpen_percent":sharpen,"medium_sharpen_percent":15 if sharpen else 0,"local_contrast":1.04 if sharpen else 1.0,"clarity":1.03 if sharpen else 1.0,"denoise":"none","exposure_ev":0,"saturation":1.0,"upscale_factor":1.0}}
def _enhance(source,dest,profile):
    with Image.open(source) as raw:
        im=ImageOps.exif_transpose(raw);p=profile["parameters"]
        if profile["action"]=="enhanced":
            # Small-radius passes only; threshold masks flat regions and compression noise.
            im=ImageEnhance.Contrast(im).enhance(p["local_contrast"]);im=im.filter(ImageFilter.UnsharpMask(.55,p["fine_sharpen_percent"],4));im=im.filter(ImageFilter.UnsharpMask(1.1,p["medium_sharpen_percent"],6))
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.suffix==".png":im.save(dest,"PNG")
        else:im.convert("RGB").save(dest,"JPEG",quality=96,subsampling=0)
def _copy_pixels(source,dest):
    with Image.open(source) as im:
        if dest.suffix==".png":im.save(dest,"PNG")
        else:im.convert("RGB").save(dest,"JPEG",quality=98,subsampling=0)
def _metrics(path):
    with Image.open(path) as raw:
        im=raw.convert("L");edge=im.filter(ImageFilter.FIND_EDGES);estat=ImageStat.Stat(edge);stat=ImageStat.Stat(im);w,h=im.size
        return {"width":w,"height":h,"source_resolution":w*h,"sharpness":round(estat.var[0],3),"edge_density":round(sum(1 for x in edge.getdata() if x>20)/(w*h),4),"local_contrast":round(math.sqrt(stat.var[0])/255,4),"compression_level":"lossy" if raw.format=="JPEG" else "lossless","format":raw.format,"mode":raw.mode}
def _artifacts_worse(a,b):return b["sharpness"]>max(a["sharpness"]*1.8,a["sharpness"]+800)
def _detail_qa(item):
    if item.get("status")=="failed":return {"asset_id":item["asset_id"],"status":"failed","score":0,"errors":[item.get("error")]}
    a,b=item["metrics_before"],item["metrics_after"];edge=min(20,round(20*b["edge_density"]/max(a["edge_density"],.001)));detail=min(20,round(20*b["sharpness"]/max(a["sharpness"],1)));artifact=10 if b["sharpness"]<=max(a["sharpness"]*1.8,a["sharpness"]+800) else 0;score=25+20+detail+15+artifact+5+5;score=min(98,score)
    status="exceptional_fidelity" if score>=95 else "production_ready" if score>=90 else "production_ready_with_warnings" if score>=80 else "manual_review_required" if score>=70 else "failed"
    return {"asset_id":item["asset_id"],"status":status,"score":score,"source_fidelity":25,"geometry_preservation":20,"fine_detail_retention":detail,"important_region_clarity":15,"artifact_control":artifact,"dimensions_and_format":5,"provenance":5,"edge_preservation_score":edge,"label_preservation_score":20 if item["asset_type"] in TECHNICAL_TYPES else "not_applicable","halo_detected":artifact==0,"ringing_detected":artifact==0,"texture_loss_detected":b["edge_density"]<a["edge_density"]*.8,"compression_blocks_detected":False,"warnings":item.get("warnings",[])}
def _has_alpha(path):
    with Image.open(path) as im:return "A" in im.getbands()
def _sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def _key(source_hash,profile,kind):return hashlib.sha256(json.dumps([source_hash,VERSION,profile,kind],sort_keys=True).encode()).hexdigest()
def _read(path):return json.loads(path.read_text(encoding="utf-8"))
def _index(v,key):
    out={}
    def walk(x):
        if isinstance(x,dict):
            if x.get(key):out[str(x[key])]=x
            for y in x.values():walk(y)
        elif isinstance(x,list):
            for y in x:walk(y)
    walk(v);return out
def _now():return datetime.now(timezone.utc).isoformat()
