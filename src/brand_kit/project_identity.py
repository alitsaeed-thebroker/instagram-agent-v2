"""Deterministic extraction of authentic, background-independent project identity artwork."""

from __future__ import annotations

from datetime import datetime,timezone
import hashlib,json,re
from pathlib import Path
from typing import Any
from PIL import Image,ImageOps,ImageStat

MODULE_VERSION="2.0.0";SCHEMA_VERSION="2.0.0"


def extract_project_brand_identity(root:Path,project:str)->tuple[Path,dict[str,Any]]:
    slug=_slug(project);source=root/"output/source-images"/project;manifest_path=source/"manifest.json";knowledge_path=root/"output/knowledge"/f"{project}.json"
    if not manifest_path.is_file():raise ValueError("Project Brand Identity requires visual-extraction manifest")
    knowledge=_read(knowledge_path);verified=str(knowledge.get("project_identity",{}).get("project_name") or "").strip()
    if not verified:raise ValueError("Project Brand Identity requires verified project_identity.project_name")
    candidates=[]
    for asset in _read(manifest_path).get("assets",[]):
        if int(asset.get("source_page") or 999)>3:continue
        path=source/str(asset.get("filename") or "")
        if path.is_file():
            detected=_detect_identity(path)
            if detected:candidates.append((int(asset.get("source_page") or 999),-detected["confidence"],str(path),path,asset,detected))
    out_dir=root/"output/project-brand"/slug;out_dir.mkdir(parents=True,exist_ok=True)
    for name in ("project-wordmark.png","developer-logo.png","developer-wordmark.png"):(out_dir/name).unlink(missing_ok=True)
    wordmark=_unavailable();developer={"available":False,"developer_name":None,"logo_path":None,"wordmark_path":None,"colors":[],"confidence":0.0,"source_document":None,"source_page":None,"colors_preserved":True,"reason":"developer identity not independently isolated"};colors=[]
    if candidates:
        _,_,_,path,asset,detected=min(candidates);outputs=_extract_background_independent(path,out_dir,detected["bounding_box"]);colors=outputs["colors"]
        target=outputs["project_wordmark"]
        wordmark={"available":True,"path":str(target.relative_to(root)),"asset_type":"project_wordmark","project_name":verified,"confidence":detected["confidence"],"source_asset":str(path.relative_to(root)),"source_sha256":_sha(path),"output_sha256":_sha(target),"source_document":asset.get("source_document"),"source_page":asset.get("source_page"),"bounding_box":detected["bounding_box"],"transparent_background":True,"background_included":False,"usable_for_branding":True,"aspect_ratio":_ratio(target),"colors":colors,"extraction_method":"source_pixel_mask_and_geometric_identity_partition"}
        if outputs.get("developer_wordmark"):
            dev_word=outputs["developer_wordmark"];dev_logo=outputs.get("developer_logo")
            developer={"available":True,"developer_name":str(knowledge.get("project_identity",{}).get("developer_name") or "").strip() or None,"logo_path":str(dev_logo.relative_to(root)) if dev_logo else None,"logo_sha256":_sha(dev_logo) if dev_logo else None,"wordmark_path":str(dev_word.relative_to(root)),"wordmark_sha256":_sha(dev_word),"colors":colors,"confidence":round(max(.7,detected["confidence"]-.04),3),"source_document":asset.get("source_document"),"source_page":asset.get("source_page"),"colors_preserved":True,"background_included":False,"extraction_method":"source_pixel_mask_and_geometric_identity_partition"}
    project_identity={"wordmark_available":wordmark["available"],"wordmark_path":wordmark.get("path"),"colors":colors,"confidence":wordmark.get("confidence",0.0),"source_document":wordmark.get("source_document"),"source_page":wordmark.get("source_page")}
    payload={"schema_version":SCHEMA_VERSION,"module_version":MODULE_VERSION,"project":project,"project_name":verified,"project_name_verified":True,"project_identity":project_identity,"project_logo":_unavailable(),"project_wordmark":wordmark,"project_font":{"available":False,"font_family":None,"font_source":None,"font_confidence":0.0,"confidence":0.0,"source":None},"developer_identity":developer,"brand_colors":colors,"background_included":False,"preferred_project_name_rendering":"wordmark" if wordmark["available"] else "generic_fallback","fallback_required":not wordmark["available"],"project_brand_identity_unavailable":not wordmark["available"],"api_calls":{"ai":0,"image_generation":0,"meta":0},"generated_at":datetime.now(timezone.utc).isoformat()}
    local=out_dir/"brand-identity.json";inventory=root/"output/inventory"/f"project-brand-{slug}.json";inventory.parent.mkdir(parents=True,exist_ok=True);encoded=json.dumps(payload,indent=2,ensure_ascii=False)+"\n";local.write_text(encoded,encoding="utf-8");inventory.write_text(encoded,encoding="utf-8");_update_coverage(root,slug,payload);return inventory,payload


def _detect_identity(path:Path)->dict[str,Any]|None:
    try:
        with Image.open(path) as raw:image=ImageOps.exif_transpose(raw).convert("RGB")
    except Exception:return None
    scale=min(1.0,1600/max(image.size));sample=image.resize((round(image.width*scale),round(image.height*scale)),Image.Resampling.LANCZOS) if scale<1 else image;y0=sample.height//2;mask=_foreground_mask(sample);box=_mask_box(mask,(0,y0,sample.width,sample.height))
    if not box or box[2]-box[0]<sample.width*.1:return None
    pad=max(8,sample.width//150);box=[max(0,box[0]-pad),max(0,box[1]-pad),min(sample.width,box[2]+pad),min(sample.height,box[3]+pad)];inverse=1/scale;full=[round(v*inverse) for v in box];return {"bounding_box":full,"confidence":round(min(.96,.74+(box[2]-box[0])/sample.width),3)}


def _extract_background_independent(source:Path,out_dir:Path,box:list[int])->dict[str,Any]:
    with Image.open(source) as raw:crop=ImageOps.exif_transpose(raw).convert("RGB").crop(tuple(box))
    mask=_foreground_mask(crop);bounds=_mask_box(mask,(0,0,crop.width,crop.height)) or (0,0,crop.width,crop.height);crop=crop.crop(bounds);mask=mask.crop(bounds);rgba=crop.convert("RGBA");rgba.putalpha(mask)
    colors=_palette(crop,mask);left_probe=_mask_box(mask,(0,0,mask.width//5,mask.height));text_start=mask.width//5 if left_probe and left_probe[3]-left_probe[1]>=mask.height*.7 else 0;project=rgba;developer=None;developer_logo=None
    text_mask=mask.crop((text_start,0,mask.width,mask.height));row_runs=_occupied_runs(text_mask,"row");row_counts=_projection(text_mask,"row");search=range(max(1,int(mask.height*.42)),max(2,int(mask.height*.82)));split_y=row_runs[-1][0] if len(row_runs)>=2 else min(search,key=lambda y:row_counts[y]) if row_counts and search else mask.height//2;top_end=row_runs[-2][1] if len(row_runs)>=2 else split_y;lower_box=_content_box(mask,(text_start,split_y,rgba.width,rgba.height))
    if lower_box:
        lower=(text_start,lower_box[1],rgba.width,lower_box[3]);runs=_occupied_runs(mask.crop(lower),"column");runs=[(a+text_start,b+text_start) for a,b in runs]
        if len(runs)>=2:
            gaps=[(runs[i+1][0]-runs[i][1],i) for i in range(len(runs)-1)];gap,index=max(gaps)
            if gap>=max(12,rgba.width*.04):
                split=(runs[index][1]+runs[index+1][0])//2;dev_box=_content_box(mask,(text_start,lower[1],split,lower[3]));suffix_box=_content_box(mask,(split,lower[1],rgba.width,lower[3]));top_box=_content_box(mask,(text_start,0,rgba.width,top_end));project=_compose_regions(rgba,[top_box,suffix_box]);developer=_clean_lower_band(rgba.crop(dev_box)) if dev_box else None
                if developer:
                    dev_mask=developer.getchannel("A");parts=_occupied_runs(dev_mask,"column");square=[run for run in parts if .35<((run[1]-run[0])/max(1,developer.height))<1.8]
                    if square:
                        run=max(square,key=lambda x:x[1]-x[0]);logo_box=_content_box(dev_mask,(run[0],0,run[1],developer.height));developer_logo=developer.crop(logo_box) if logo_box else None
    project_path=out_dir/"project-wordmark.png";_trim(project).save(project_path,"PNG",optimize=False);result={"project_wordmark":project_path,"colors":colors}
    if developer:
        path=out_dir/"developer-wordmark.png";_trim(developer).save(path,"PNG",optimize=False);result["developer_wordmark"]=path
    if developer_logo:
        path=out_dir/"developer-logo.png";_trim(developer_logo).save(path,"PNG",optimize=False);result["developer_logo"]=path
    return result


def _foreground_mask(image:Image.Image)->Image.Image:
    rgb=image.convert("RGB");pixels=[]
    for r,g,b in rgb.getdata():
        light=min(r,g,b);neutral=max(r,g,b)-min(r,g,b);alpha=max(0,min(255,round((light-185)*10))) if neutral<=55 else 0
        pixels.append(alpha)
    mask=Image.new("L",rgb.size);mask.putdata(pixels);return mask
def _occupied_runs(mask:Image.Image,axis:str)->list[tuple[int,int]]:
    threshold=max(1,(mask.width if axis=="row" else mask.height)//250);counts=_projection(mask,axis)
    active=[i for i,v in enumerate(counts) if v>=threshold];runs=[]
    for i in active:
        if not runs or i-runs[-1][1]>max(2,len(counts)//300):runs.append([i,i+1])
        else:runs[-1][1]=i+1
    return [tuple(x) for x in runs if x[1]-x[0]>=2]
def _projection(mask:Image.Image,axis:str)->list[int]:
    if axis=="row":return [sum(1 for x in range(mask.width) if mask.getpixel((x,y))>32) for y in range(mask.height)]
    return [sum(1 for y in range(mask.height) if mask.getpixel((x,y))>32) for x in range(mask.width)]
def _mask_box(mask:Image.Image,region:tuple[int,int,int,int])->tuple[int,int,int,int]|None:
    local=mask.crop(region);box=local.point(lambda x:255 if x>32 else 0).getbbox();return (box[0]+region[0],box[1]+region[1],box[2]+region[0],box[3]+region[1]) if box else None
def _content_box(mask:Image.Image,region:tuple[int,int,int,int])->tuple[int,int,int,int]|None:return _mask_box(mask,region)
def _compose_regions(image:Image.Image,regions:list[tuple[int,int,int,int]|None])->Image.Image:
    valid=[r for r in regions if r]
    if not valid:return image
    left=min(r[0] for r in valid);top=min(r[1] for r in valid);right=max(r[2] for r in valid);bottom=max(r[3] for r in valid);canvas=Image.new("RGBA",(right-left,bottom-top),(0,0,0,0))
    for r in valid:canvas.alpha_composite(image.crop(r),(r[0]-left,r[1]-top))
    return canvas
def _trim(image:Image.Image)->Image.Image:
    box=image.getchannel("A").getbbox();return image.crop(box) if box else image
def _clean_lower_band(image:Image.Image)->Image.Image:
    counts=_projection(image.getchannel("A"),"row")
    if not counts:return image
    threshold=max(counts)*.15;start=next((i for i,value in enumerate(counts) if value>=threshold),0);return image.crop((0,start,image.width,image.height))
def _palette(image:Image.Image,mask:Image.Image)->list[str]:
    fg=[p for p,a in zip(image.getdata(),mask.getdata()) if a>180];bg=[p for p,a in zip(image.getdata(),mask.getdata()) if a<16]
    def color(values:list[tuple[int,int,int]])->str:
        if not values:return "#000000"
        step=max(1,len(values)//50000);values=values[::step];return "#%02X%02X%02X"%tuple(round(x) for x in ImageStat.Stat(Image.new("RGB",(len(values),1))).mean) if False else "#%02X%02X%02X"%tuple(sorted(p[i] for p in values)[len(values)//2] for i in range(3))
    return list(dict.fromkeys([color(fg),color(bg)]))
def _unavailable()->dict[str,Any]:return {"available":False,"path":None,"confidence":0.0,"source_document":None,"source_page":None}
def _update_coverage(root:Path,slug:str,payload:dict[str,Any])->None:
    path=root/"output/reports"/f"source-coverage-{slug}.json"
    report=_read(path)
    if not report:return
    report["project_brand_assets_found"]=int(payload["project_wordmark"]["available"])+int(payload["project_logo"]["available"]);developer=payload["developer_identity"];report["developer_brand_assets_found"]=int(bool(developer.get("logo_path")))+int(bool(developer.get("wordmark_path")));path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    markdown=path.with_suffix(".md");markdown.write_text("# Source Coverage Report\n\n"+"\n".join(f"- {key.replace('_',' ').title()}: {value}" for key,value in report.items() if not isinstance(value,(list,dict)))+"\n",encoding="utf-8")
def _ratio(path:Path)->float:
    with Image.open(path) as image:return round(image.width/image.height,6)
def _read(path:Path)->dict[str,Any]:
    try:return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):return {}
def _slug(value:str)->str:return re.sub(r"[^\w.-]+","-",value,flags=re.UNICODE).strip("-.") or "project"
def _sha(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()
