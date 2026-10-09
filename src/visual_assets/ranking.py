"""Deterministic ranking and non-destructive selection of authentic source images."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

from PIL import Image, ImageFilter, ImageStat
from src.visual_assets.topic_linking import SUPPORTED_TOPICS, link_visual_topics

MODULE_VERSION = "5.0.0"
INSTAGRAM_CAROUSEL_LIMIT = 10
SCHEMA_VERSION = "2.0.0"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
TYPE_MAP = {
    "exterior":"exterior_render", "villa_exterior":"exterior_render", "building_exterior":"exterior_render",
    "interior":"interior_render", "residential_space":"interior_render", "villa_interior":"interior_render", "building_interior":"interior_render",
    "aerial_view":"aerial_render", "project_hero":"aerial_render", "amenity":"amenity", "amenities":"amenity",
    "clubhouse":"amenity", "swimming_pool":"amenity", "garden_landscape":"landscape", "greenery_landscape":"landscape",
    "lifestyle":"lifestyle", "floorplan":"floor_plan", "floor_plan":"floor_plan", "villa_layout":"floor_plan",
    "site_plan":"full_project_site_plan", "full_project_site_plan":"full_project_site_plan", "masterplan":"masterplan",
    "unit_plan":"unit_plan", "technical_plan":"technical_drawing", "technical_drawing":"technical_drawing",
    "location_map":"map", "map":"map", "logo":"logo", "branding_graphic":"brochure_graphic",
    "decorative_graphic":"brochure_graphic", "text_heavy_page":"text_heavy", "technical_plan":"brochure_graphic",
}
REJECT_TYPES = {"map", "logo", "text_heavy", "technical_drawing"}


def rank_source_images(source_root: Path, inventory_root: Path, selected_root: Path, *, project: str | None = None,
                       max_selected: int = 10, intelligence_path: Path | None = None,
                       knowledge_path: Path | None = None) -> tuple[Path, Path, dict[str, Any]]:
    """Rank all usable images and copy only genuinely strong selections."""
    projects = _project_directories(source_root, project);knowledge=_read_json(knowledge_path);deep_visuals={str(x.get("asset_id")):x for x in knowledge.get("source_visuals",[]) if x.get("asset_id")}
    intelligence = _intelligence_index(intelligence_path)
    records: list[dict[str, Any]] = []
    for project_name, folder in projects:
        manifest = _manifest_index(folder / "manifest.json")
        discovered = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.casefold() in IMAGE_SUFFIXES)
        project_records = [_inspect(path, project_name, source_root, manifest.get(path.resolve()), intelligence,deep_visuals) for path in discovered]
        _mark_duplicates(project_records)
        project_records.sort(key=lambda x: (x["content_priority"], -x["overall_score"], x["path"].casefold()))
        selected = _select_editorial(project_records,max(0,max_selected))
        _assign_story(selected)
        destination = selected_root / _safe_folder(project_name)
        destination.mkdir(parents=True, exist_ok=True)
        # This folder is owned by this stage. Reconcile only image copies inside
        # the exact project directory so reruns cannot leave more than the limit.
        for stale in destination.iterdir():
            if stale.is_file() and stale.suffix.casefold() in IMAGE_SUFFIXES:stale.unlink()
        for rank, record in enumerate(selected, 1):
            source = source_root / Path(record["path"])
            target = destination / source.name
            if target.exists() and _sha(target) != record["sha256"]:
                target = destination / f"{source.stem}-{record['sha256'][:8]}{source.suffix.lower()}"
            shutil.copy2(source, target)
            if _sha(source) != record["sha256"] or _sha(target) != record["sha256"]:
                raise ValueError(f"Source integrity changed while selecting {source}")
            record.update(selected=True, selection_rank=rank, selected_path=str(target.relative_to(selected_root)))
        for record in project_records:
            record.setdefault("selected", False);record.setdefault("selection_rank", None);record.setdefault("selected_path", None)
        records.extend(project_records)
    payload = {"schema_version":SCHEMA_VERSION,"module_version":MODULE_VERSION,"generated_at":datetime.now(timezone.utc).isoformat(),
        "source_root":str(source_root),"selected_root":str(selected_root),"max_selected_per_project":max_selected,
        "projects":sorted({x["project"] for x in records}),"images":records,
        "summary":{"images_discovered":len(records),"images_selected":sum(x["selected"] for x in records),
            "images_rejected":sum(x["selection_priority"]=="REJECT" for x in records),"corrupted_or_unreadable":sum(x["rejection_reason"]=="corrupted or unreadable image" for x in records)}}
    inventory_root.mkdir(parents=True, exist_ok=True)
    suffix=f"-{_safe_folder(project)}" if project else ""
    json_path=inventory_root/f"source-image-ranking{suffix}.json";summary_path=inventory_root/f"source-image-selection-summary{suffix}.md";content_plan_path=inventory_root/f"visual-editorial-inventory{suffix}.md";content_plan_json_path=inventory_root/f"visual-editorial-inventory{suffix}.json"
    content_plan_payload=_content_plan_payload(payload,knowledge)
    visual_editorial_payload=_visual_editorial_payload(content_plan_payload)
    json_path.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    summary_path.write_text(_summary(payload),encoding="utf-8")
    content_plan_path.write_text("# NON-AUTHORITATIVE VISUAL EDITORIAL INVENTORY\n\nThis pre-strategy artifact may not drive content strategy or branded content.\n\n"+_content_plan_markdown(content_plan_payload).replace("POST ","VISUAL GROUP "),encoding="utf-8")
    content_plan_json_path.write_text(json.dumps(visual_editorial_payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    reports_root=inventory_root.parent/"reports";reports_root.mkdir(parents=True,exist_ok=True);coverage=_content_coverage(content_plan_payload,knowledge)
    coverage_json=reports_root/f"content-coverage{suffix}.json";coverage_md=reports_root/f"content-coverage{suffix}.md"
    coverage_json.write_text(json.dumps(coverage,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");coverage_md.write_text(_content_coverage_md(coverage),encoding="utf-8")
    visual_coverage=content_plan_payload.get("visual_topic_coverage",{});visual_coverage_path=reports_root/f"visual-topic-coverage{suffix}.md";visual_coverage_path.write_text(_visual_topic_coverage_md(visual_coverage),encoding="utf-8")
    payload["artifacts"]={"visual_editorial_inventory_json":str(content_plan_json_path),"visual_editorial_inventory_markdown":str(content_plan_path),"content_coverage_json":str(coverage_json),"content_coverage_markdown":str(coverage_md),"visual_topic_coverage":str(visual_coverage_path)}
    return json_path, summary_path, payload


def _inspect(path: Path, project: str, root: Path, manifest: dict[str, Any] | None, intelligence: dict[str, dict[str, Any]],deep_visuals:dict[str,dict[str,Any]]|None=None) -> dict[str, Any]:
    raw_hash=_sha(path);asset_id=str((manifest or {}).get("asset_id") or "");semantic=intelligence.get(asset_id,{});deep=(deep_visuals or {}).get(asset_id,{});record={"project":project,"path":str(path.relative_to(root)),"asset_id":(manifest or {}).get("asset_id"),"sha256":raw_hash,
        "width":0,"height":0,"aspect_ratio":0.0,"source_image_type":"unknown","visual_quality_score":0,"marketing_value_score":0,
        "brand_content_suitability_score":0,"social_media_suitability_score":0,"overall_score":0,"text_heavy":False,
        "likely_duplicate":False,"duplicate_group":None,"recommended_use":"reject","selection_priority":"REJECT","rejection_reason":None}
    record.update(content_priority=99,story_role="reference_only",content_group="reference",content_topic="reference",post_format="single",post_group_id=None,carousel_compatibility=[],source_page=deep.get("page_number") or (manifest or {}).get("source_page"),source_document=deep.get("source_document"),source_section=deep.get("section"),page_title=deep.get("page_title") or deep.get("section"),nearby_text=" ".join(str(x) for x in deep.get("related_text",[]) if x),caption=deep.get("caption"),deep_image_type=deep.get("image_type"),deep_description=deep.get("description"),related_property_type=deep.get("related_property_type") or deep.get("related_unit_type") or deep.get("related_villa_type"),deep_marketing_topic=deep.get("marketing_topic"),source_confidence=deep.get("confidence"),post_selected=False,post_selection_rationale=None)
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width,height=image.size;gray=image.convert("L").resize((128,128));edges=gray.filter(ImageFilter.FIND_EDGES)
            sharpness=float(ImageStat.Stat(edges).var[0]);mean=float(ImageStat.Stat(gray).mean[0]);contrast=float(ImageStat.Stat(gray).stddev[0]);dhash=_dhash(gray)
    except Exception:
        record["rejection_reason"]="corrupted or unreadable image";return record
    pixels=width*height;ratio=width/max(1,height);kind=_source_type(semantic);contains_text=bool(semantic.get("contains_text"));text_heavy=kind=="text_heavy" or (contains_text and semantic.get("marketing_suitability") in {"limited_use","review_required","unsuitable"})
    resolution=min(100,round(100*pixels/2_000_000));sharp=min(100,round(sharpness/8));clarity=max(0,min(100,round(45+contrast-abs(mean-128)/3)));compression=max(20,min(100,round(path.stat().st_size/max(1,pixels)*180)))
    visual=round(.45*resolution+.30*sharp+.15*clarity+.10*compression)
    market_base={"full_project_site_plan":90,"masterplan":90,"exterior_render":92,"interior_render":88,"aerial_render":90,"amenity":82,"landscape":78,"lifestyle":78,"brochure_graphic":35,"floor_plan":45,"unit_plan":45,"technical_drawing":25,"map":15,"logo":5,"text_heavy":10,"unknown":48}[kind]
    confidence=float(semantic.get("confidence") or 0);marketing=max(0,min(100,round(market_base*(.8+.2*confidence))))
    crop=semantic.get("safe_crop_assessment",{}).get("level");brand=75 if crop in {"flexible","moderately_flexible"} else 58 if crop=="limited" else 42
    if text_heavy:brand-=35
    social=88 if .75<=ratio<=1.35 else 80 if .55<=ratio<=1.9 else 55
    if pixels<300_000:social-=25
    overall=round(.32*marketing+.28*visual+.20*brand+.20*social)
    rejection=None
    if width<400 or height<300 or pixels<120_000:rejection="very low resolution"
    elif kind in REJECT_TYPES:rejection=kind.replace("_"," ")
    elif text_heavy:rejection="mostly text"
    editorial_types={"full_project_site_plan","masterplan","exterior_render","interior_render","aerial_render","amenity","landscape","lifestyle"}
    priority="REJECT" if rejection else "HIGH" if overall>=72 and kind in editorial_types else "MEDIUM" if overall>=60 and kind in editorial_types else "LOW"
    use="reject" if priority=="REJECT" else "carousel" if kind in {"full_project_site_plan","masterplan"} else "feed_hero" if priority=="HIGH" and kind in {"exterior_render","aerial_render"} else "feed_feature" if priority=="HIGH" else "carousel" if priority=="MEDIUM" else "reference_only"
    record.update(width=width,height=height,aspect_ratio=round(ratio,4),source_image_type=kind,visual_quality_score=visual,
        marketing_value_score=marketing,brand_content_suitability_score=max(0,brand),social_media_suitability_score=max(0,social),
        overall_score=max(0,min(100,overall)),text_heavy=text_heavy,recommended_use=use,selection_priority=priority,rejection_reason=rejection,
        content_priority=_content_priority(kind),story_role=_story_role(kind,False),content_group=_content_group(kind),content_topic=_content_topic(kind,semantic),post_format="single" if kind in {"full_project_site_plan","masterplan"} else "carousel",post_group_id=None,carousel_compatibility=[],
        technical_metrics={"sharpness":round(sharpness,2),"contrast":round(contrast,2),"file_size_bytes":path.stat().st_size,"dhash":dhash})
    return record


def _mark_duplicates(records: list[dict[str, Any]]) -> None:
    groups: dict[str,list[dict[str,Any]]]=defaultdict(list)
    for record in records:
        key=record["sha256"] if record["width"] else f"broken:{record['path']}";groups[key].append(record)
    number=0
    for values in groups.values():
        if len(values)<2:continue
        number+=1;group=f"duplicate-{number:03d}"
        for index,record in enumerate(values):
            record["duplicate_group"]=group;record["likely_duplicate"]=index>0
            if index>0:record.update(selection_priority="REJECT",recommended_use="reject",rejection_reason="duplicate image")
    # Conservative perceptual pass: only almost-identical hashes with matching
    # dimensions are grouped, avoiding rejection of legitimate alternate views.
    canonical=[x for x in records if x["width"] and not x["likely_duplicate"]]
    for index,record in enumerate(canonical):
        if record["duplicate_group"]:continue
        for prior in canonical[:index]:
            if abs(record["width"]-prior["width"])>2 or abs(record["height"]-prior["height"])>2:continue
            left=int(record["technical_metrics"]["dhash"],16);right=int(prior["technical_metrics"]["dhash"],16)
            if (left^right).bit_count()>2:continue
            if not prior["duplicate_group"]:
                number+=1;prior["duplicate_group"]=f"duplicate-{number:03d}"
            record.update(duplicate_group=prior["duplicate_group"],likely_duplicate=True,selection_priority="REJECT",recommended_use="reject",rejection_reason="near-duplicate image")
            break


def _source_type(semantic: dict[str, Any]) -> str:
    key=str(semantic.get("visual_category") or semantic.get("asset_type") or "unknown").casefold();kind=TYPE_MAP.get(key,"unknown");subject=" ".join(str(semantic.get(x) or "") for x in ("asset_subtype","dominant_subject","visible_text_summary")).casefold()
    if key=="site_plan" and not any(term in subject for term in ("urban landscape","urban development","complete development","full project","community layout","multiple buildings","multiple villas","project boundaries")):return "unit_plan"
    if kind=="floor_plan" and any(x in subject for x in ("unit","villa","apartment","office")):return "unit_plan"
    return kind
def _content_priority(kind:str)->int:return {"full_project_site_plan":1,"masterplan":1,"exterior_render":2,"aerial_render":2,"interior_render":3,"amenity":4,"landscape":4,"lifestyle":4,"floor_plan":5,"unit_plan":5}.get(kind,9)
def _content_group(kind:str)->str:
    if kind in {"full_project_site_plan","masterplan"}:return "project_overview"
    if kind in {"exterior_render","aerial_render"}:return "architecture"
    if kind=="interior_render":return "interior_experience"
    if kind in {"amenity","landscape","lifestyle"}:return "amenities_lifestyle"
    if kind in {"floor_plan","unit_plan"}:return "unit_information"
    return "reference"
def _content_topic(kind:str,semantic:dict[str,Any])->str:
    if kind in {"full_project_site_plan","masterplan"}:return "project_overview"
    subject=" ".join(str(semantic.get(x) or "") for x in ("dominant_subject","asset_subtype","visible_text_summary")).casefold()
    if kind in {"exterior_render","aerial_render"}:return "villas" if "villa" in subject else "architecture"
    if kind=="interior_render":return "villas" if "villa" in subject else "interiors"
    if kind in {"amenity","landscape","lifestyle"}:return "villas" if "villa" in subject else "amenities"
    if kind in {"floor_plan","unit_plan"}:return "unit_information"
    return "reference"
def _story_role(kind:str,detail:bool)->str:
    if kind in {"full_project_site_plan","masterplan"}:return "project_overview"
    if kind in {"exterior_render","aerial_render"}:return "exterior_detail" if detail else "exterior_overview"
    if kind=="interior_render":return "interior_experience"
    if kind=="amenity":return "amenity_feature"
    if kind in {"landscape","lifestyle"}:return "lifestyle_feature"
    if kind in {"floor_plan","unit_plan"}:return "unit_information"
    return "reference_only"
def _assign_story(selected:list[dict[str,Any]])->None:
    by_group:dict[str,list[dict[str,Any]]]=defaultdict(list)
    for item in selected:by_group[item["content_group"]].append(item)
    for group,items in by_group.items():
        ids=[str(x.get("asset_id") or x["path"]) for x in items]
        for index,item in enumerate(items):item["story_role"]=_story_role(item["source_image_type"],index>0);item["carousel_compatibility"]=[x for x in ids if x!=str(item.get("asset_id") or item["path"])]
    overview=by_group.get("project_overview",[])[:1];architecture=by_group.get("architecture",[])[:2]
    if overview:
        combined=[*overview,*architecture];ids=[str(x.get("asset_id") or x["path"]) for x in combined]
        for item in combined:item["carousel_compatibility"]=list(dict.fromkeys([*item["carousel_compatibility"],*[x for x in ids if x!=str(item.get("asset_id") or item["path"])]]))
def _select_editorial(records:list[dict[str,Any]],limit:int)->list[dict[str,Any]]:
    eligible=[x for x in records if x["selection_priority"] in {"HIGH","MEDIUM"} and not x["likely_duplicate"]];by_group=defaultdict(list)
    for item in eligible:by_group[item["content_group"]].append(item)
    caps=(('project_overview',2),('architecture',3),('interior_experience',3),('amenities_lifestyle',2));selected=[]
    for group,cap in caps:selected.extend(by_group[group][:min(cap,max(0,limit-len(selected)))])
    if len(selected)<limit:
        chosen={id(x) for x in selected};selected.extend(x for x in eligible if id(x) not in chosen and x["content_group"]!="reference")
    return selected[:limit]
def _dhash(image: Image.Image) -> str:
    sample=image.resize((9,8));pixels=list(sample.getdata());bits=[pixels[y*9+x]>pixels[y*9+x+1] for y in range(8) for x in range(8)];return f"{sum(1<<i for i,v in enumerate(bits) if v):016x}"
def _sha(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()
def _safe_folder(value: str | None) -> str:return re.sub(r"[^\w.-]+","-",str(value or "all"),flags=re.UNICODE).strip("-.") or "project"
def _project_directories(root: Path, project: str | None) -> list[tuple[str,Path]]:
    if project:
        folder=root/project
        return [(project,folder)] if folder.is_dir() else []
    children=[p for p in root.iterdir() if p.is_dir()] if root.is_dir() else []
    return [(p.name,p) for p in sorted(children)] or ([(root.name,root)] if root.is_dir() else [])
def _manifest_index(path: Path) -> dict[Path,dict[str,Any]]:
    try:data=json.loads(path.read_text(encoding="utf-8"));return {(path.parent/item["filename"]).resolve():item for item in data.get("assets",[]) if item.get("filename")}
    except (OSError,ValueError,TypeError):return {}
def _intelligence_index(path: Path | None) -> dict[str,dict[str,Any]]:
    try:return {str(x["asset_id"]):x for x in json.loads(path.read_text(encoding="utf-8")).get("assets",[]) if x.get("asset_id")} if path else {}
    except (OSError,ValueError,TypeError):return {}
def _summary(payload: dict[str,Any]) -> str:
    lines=["# Source Image Selection Summary",""]
    for project in payload["projects"]:
        items=[x for x in payload["images"] if x["project"]==project];lines += [f"## PROJECT: {project}",""]
        selected=[x for x in items if x["selected"]]
        for item in selected:lines += [f"{item['selection_rank']}. `{Path(item['path']).name}`",f"   - Overall score: {item['overall_score']}/100",f"   - Type: {item['source_image_type']}",f"   - Content priority: {item['content_priority']}",f"   - Story role: {item['story_role']}",f"   - Priority: {item['selection_priority']}",f"   - Recommended use: {item['recommended_use']}",""]
        lines += ["### Rejected",""]+[f"- `{Path(x['path']).name}` — {x['rejection_reason'] or 'low selection value'}" for x in items if x["selection_priority"]=="REJECT"]+[""]
    return "\n".join(lines)
def _content_plan(payload:dict[str,Any])->str:
    lines=["# PROJECT CONTENT PLAN",""]
    for project in payload["projects"]:
        selected=sorted((x for x in payload["images"] if x["project"]==project and x["selected"]),key=lambda x:int(x.get("selection_rank") or 999))
        lines += [f"## PROJECT: {project}",""]
        plan=_planned_posts(selected)
        for post in plan:
            items=post["items"];lines += [f"### POST {post['post_number']:02d} — {post['title'].upper()}","",f"Post group: `{post['post_group_id']}`",f"Content topic: `{post['content_topic']}`",f"Format: {post['post_format']}","","Assets:"]
            for slide,item in enumerate(items,1):lines.append(f"{slide}. `{Path(item['path']).name}` — {item['story_role']} — score {item['overall_score']}/100")
            lines.append("")
        if not plan:lines += ["No editorially eligible selected assets.",""]
    return "\n".join(lines)


def _content_plan_payload(payload:dict[str,Any],knowledge:dict[str,Any]|None=None)->dict[str,Any]:
    """Build the machine-readable editorial plan consumed by render stages."""
    projects=[];linking={"linker_version":None,"visuals_evaluated":0,"topics":{}}
    for project in payload["projects"]:
        project_images=[x for x in payload["images"] if x["project"]==project];selected=sorted((x for x in project_images if x["selected"]),key=lambda x:int(x.get("selection_rank") or 999))
        posts=[]
        planned,linking=_planned_posts(selected,knowledge or {},project_images,return_linking=True)
        for definition in planned:
            items=definition.pop("items");post_number=definition["post_number"];posts.append({**definition,"source_assets":[item["path"] for item in items],"slides":[_slide_payload(item,number,enriched=post_number>=6) for number,item in enumerate(items,1)]})
        projects.append({"project":project,"posts":posts})
    return {"schema_version":"3.0.0","module_version":MODULE_VERSION,"generated_at":payload["generated_at"],"projects":projects,"visual_topic_coverage":linking}


def _visual_editorial_payload(plan:dict[str,Any])->dict[str,Any]:
    projects=[]
    for project in plan.get("projects",[]):
        groups=[]
        for post in project.get("posts",[]):
            assets=[]
            for slide in post.get("slides",[]):
                asset={key:value for key,value in slide.items() if key not in {"content_topic","story_role"}}
                asset["editorial_visual_role"]=slide.get("content_topic");asset["visual_story_role"]=slide.get("story_role");assets.append(asset)
            groups.append({"visual_group_id":post.get("post_group_id"),"editorial_visual_role":post.get("content_topic"),
                "visual_format_suggestion":post.get("post_format"),"source_asset_ids":[x.get("asset_id") for x in post.get("slides",[]) if x.get("asset_id")],
                "visual_assets":assets,"render_ready":post.get("render_ready",False)})
        projects.append({"project":project.get("project"),"visual_groups":groups})
    return {"schema_version":"1.0.0","module_version":plan.get("module_version"),"generated_at":plan.get("generated_at"),
        "role":"visual_intelligence","authoritative_strategy":False,"pre_strategy":True,"may_not_drive_branded_content":True,
        "projects":projects,"visual_topic_coverage":plan.get("visual_topic_coverage",{})}

def _slide_payload(item:dict[str,Any],number:int,*,enriched:bool)->dict[str,Any]:
    slide={"slide_number":number,"asset_id":item.get("asset_id"),"source_image":item["path"],"selected_path":item.get("selected_path"),"source_sha256":item["sha256"],"source_image_type":item["source_image_type"],"deep_image_type":item.get("deep_image_type"),"story_role":item["story_role"],"content_topic":item["content_topic"],"source_page":item.get("source_page"),"source_section":item.get("source_section"),"ranking_score":item["overall_score"],"selection_priority":item.get("topic_selection_priority") or item["selection_priority"],"selection_rationale":item.get("post_selection_rationale"),"rejection_reason":item.get("topic_rejection_reason")}
    if enriched:slide.update(source_filename=Path(item["path"]).name,source_pdf=item.get("source_pdf") or item.get("source_document"),image_classification=item.get("deep_image_type") or item.get("source_image_type"),semantic_topic_score=item.get("semantic_topic_score"),visual_quality_score=item.get("visual_quality_score"),duplicate_status="canonical" if not item.get("likely_duplicate") else "duplicate",verified_knowledge_linkage=item.get("verified_knowledge_linkage",[]))
    return slide


def _planned_posts(selected:list[dict[str,Any]],knowledge:dict[str,Any]|None=None,all_records:list[dict[str,Any]]|None=None,*,return_linking:bool=False)->Any:
    topics:dict[str,list[dict[str,Any]]]=defaultdict(list)
    for item in selected:topics[item.get("content_topic") or "reference"].append(item)
    villas=_villa_candidates(all_records or selected)
    definitions=[("project_overview","Project Overview",topics.get("project_overview",[])[:1]),("villas","Villas",villas),("architecture","Architecture",topics.get("architecture",[])[:INSTAGRAM_CAROUSEL_LIMIT]),("interiors","Interiors",topics.get("interiors",[])[:INSTAGRAM_CAROUSEL_LIMIT]),("amenities","Amenities",topics.get("amenities",[])[:INSTAGRAM_CAROUSEL_LIMIT])]
    protected={item["path"] for _,_,items in definitions for item in items};linking=link_visual_topics(all_records or selected,knowledge or {},protected_paths=protected,limit=INSTAGRAM_CAROUSEL_LIMIT);available=_knowledge_topics(knowledge or {})
    titles={"unit_information":"Unit Information","location":"Location","features":"Features","property_types":"Property Types","lifestyle":"Lifestyle","investment_facts":"Project Facts"}
    for topic in SUPPORTED_TOPICS:
        linked=linking["topics"][topic];items=[]
        for candidate in linked["selected"]:
            item=dict(candidate);item.update(content_topic=topic,story_role=_linked_story_role(topic,item),post_selected=True,post_selection_rationale=item["selection_rationale"],topic_selection_priority="HIGH" if item["semantic_topic_score"]>=.8 else "MEDIUM",topic_rejection_reason=None)
            evidence=item.get("verified_knowledge_linkage") or [];sources=[source for fact in evidence for source in fact.get("sources",[]) if isinstance(source,dict)];item["source_pdf"]=next((source.get("source_document") for source in sources if source.get("source_document")),item.get("source_document"));items.append(item)
        definitions.append((topic,titles[topic],items))
    posts=[]
    for topic,title,items in definitions:
        if not items and topic not in available:continue
        number=len(posts)+1;post_format="single" if topic=="project_overview" or len(items)<=1 else "carousel";group_id=f"post-{number:03d}-{topic}"
        for item in items:item["post_format"]=post_format;item["post_group_id"]=group_id
        facts=_topic_facts(knowledge or {},topic);linked=linking["topics"].get(topic);source_reason=None if items else (linked or {}).get("reason") or "no_source_visual_found";approved_layout=topic not in SUPPORTED_TOPICS;reason=None if approved_layout and items else "no_approved_renderer" if items else source_reason
        if linked is not None:linked.update(canonical_renderability="renderable" if approved_layout and items else "planned_not_renderable",canonical_renderability_reason=reason)
        posts.append({"post_number":number,"post_id":f"post-{number:03d}","post_group_id":group_id,"title":title,"story":topic,"story_role":items[0]["story_role"] if len(items)==1 else "topic_sequence","content_topic":topic,"post_format":post_format,"format":post_format,"slide_count":len(items),"priority":number,"rationale":_rationale(topic,items,facts) if items else f"Deferred: {reason}.","source_facts":facts,"render_ready":bool(items) and approved_layout,"visual_eligibility":"renderable" if items else "planned_not_renderable","visual_eligibility_reason":source_reason,"renderability_status":"renderable" if approved_layout and items else "planned_not_renderable","renderability_reason":reason,"approved_renderer_compatible":approved_layout,"items":items})
    return (posts,linking) if return_linking else posts

def _linked_story_role(topic:str,item:dict[str,Any])->str:
    return {"unit_information":"unit_information","location":"location_context","features":"feature_evidence","property_types":"property_type_evidence","lifestyle":"lifestyle_experience","investment_facts":"investment_evidence"}[topic]


def _villa_order(item:dict[str,Any])->int:
    kind=item.get("source_image_type");role=item.get("story_role")
    if kind in {"exterior_render","aerial_render"}:return 0 if role=="exterior_overview" else 1
    if kind=="interior_render":return 2
    if kind in {"amenity","landscape","lifestyle"}:return 3
    return 4

def _villa_candidates(records:list[dict[str,Any]])->list[dict[str,Any]]:
    """Build the villa story from the full source inventory, not a stale global shortlist."""
    eligible=[]
    allowed={"exterior_render","aerial_render","interior_render","amenity","landscape","lifestyle"}
    for item in records:
        context=" ".join(str(item.get(key) or "") for key in ("content_topic","deep_image_type","deep_description","source_section","related_property_type","deep_marketing_topic")).casefold()
        semantic_villa="villa" in context or str(item.get("deep_image_type") or "").casefold() in {"villa_exterior","villa_interior"}
        if not semantic_villa or item.get("source_image_type") not in allowed:continue
        if item.get("selection_priority")!="HIGH" or int(item.get("overall_score") or 0)<78:continue
        if item.get("likely_duplicate") or item.get("rejection_reason"):continue
        eligible.append(item)
    def candidate_key(item:dict[str,Any])->tuple[int,int,int,str]:
        kind=item.get("source_image_type");deep=item.get("deep_image_type")
        family=0 if kind in {"exterior_render","aerial_render"} else 1 if kind=="interior_render" else 2
        specificity=0 if deep in {"villa_exterior","villa_interior"} else 1
        return family,specificity,-int(item.get("overall_score") or 0),f"{int(item.get('source_page') or 9999):04d}:{item.get('path')}"
    eligible.sort(key=candidate_key)
    exteriors=[x for x in eligible if x.get("source_image_type") in {"exterior_render","aerial_render"}][:8]
    interiors=[x for x in eligible if x.get("source_image_type")=="interior_render"][:2]
    supporting=[x for x in eligible if x.get("source_image_type") in {"amenity","landscape","lifestyle"}]
    chosen=[*exteriors,*interiors];chosen.extend(x for x in supporting if len(chosen)<INSTAGRAM_CAROUSEL_LIMIT)
    exterior_index=0
    for item in chosen:
        kind=item.get("source_image_type")
        if kind in {"exterior_render","aerial_render"}:
            item["story_role"]="exterior_overview" if exterior_index==0 else "exterior_detail";exterior_index+=1
        else:item["story_role"]=_story_role(kind,True)
        item["content_topic"]="villas";item["post_selected"]=True;item["post_selection_rationale"]=_villa_selection_rationale(item)
    return chosen

def _villa_selection_rationale(item:dict[str,Any])->str:
    relationship=item.get("related_property_type") or item.get("source_section") or item.get("deep_marketing_topic") or "villa source context"
    return f"High-scoring authentic {item.get('deep_image_type') or item.get('source_image_type')} linked to {relationship}; adds {item.get('story_role','villa storytelling')} variety."

def _read_json(path:Path|None)->dict[str,Any]:
    try:return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else {}
    except (OSError,ValueError,TypeError):return {}

def _knowledge_topics(knowledge:dict[str,Any])->set[str]:
    topics=set()
    if (knowledge.get("project_overview") or {}).get("facts"):topics.add("project_overview")
    if (knowledge.get("location") or {}).get("facts"):topics.add("location")
    if knowledge.get("features"):topics.add("features")
    if knowledge.get("amenities"):topics.add("amenities")
    if knowledge.get("lifestyle"):topics.add("lifestyle")
    if knowledge.get("unit_types") or knowledge.get("property_types") or knowledge.get("villa_types"):topics.add("property_types")
    if knowledge.get("plans_and_layouts"):topics.add("unit_information")
    identity=knowledge.get("developer_identity") or {}
    if identity.get("name") or identity.get("logos"):topics.add("developer_identity")
    technical=[x for x in knowledge.get("canonical_facts",[]) if x.get("category")=="technical_specification"]
    if technical:topics.add("investment_facts")
    return topics

def _topic_facts(knowledge:dict[str,Any],topic:str)->list[dict[str,Any]]:
    mapping={"project_overview":(knowledge.get("project_overview") or {}).get("facts",[]),"location":(knowledge.get("location") or {}).get("facts",[]),"features":knowledge.get("features",[]),"amenities":knowledge.get("amenities",[]),"lifestyle":knowledge.get("lifestyle",[]),"property_types":knowledge.get("unit_types") or knowledge.get("property_types") or knowledge.get("villa_types",[]),"unit_information":knowledge.get("plans_and_layouts",[]),"developer_identity":[knowledge.get("developer_identity",{})],"investment_facts":[x for x in knowledge.get("canonical_facts",[]) if x.get("category")=="technical_specification"]}
    return [x for x in mapping.get(topic,[]) if x][:12]

def _rationale(topic:str,items:list[dict[str,Any]],facts:list[dict[str,Any]])->str:
    if items:return f"Groups {len(items)} strong, non-duplicate approved source asset(s) around the {topic.replace('_',' ')} story."
    return f"Deep-source knowledge supports the {topic.replace('_',' ')} topic, but no approved source visual is assigned; keep as planning-only."

def _content_plan_markdown(payload:dict[str,Any])->str:
    lines=["# PROJECT CONTENT PLAN",""]
    for project in payload["projects"]:
        lines += [f"## PROJECT: {project['project']}",""]
        for post in project["posts"]:
            lines += [f"### POST {post['post_number']:02d} — {post['title'].upper()}","",f"Content topic: `{post['content_topic']}`",f"Format: `{post['post_format']}`",f"Slide count: {post['slide_count']}",f"Priority: {post['priority']}",f"Render ready: {'yes' if post['render_ready'] else 'no'}",f"Rationale: {post['rationale']}","","Source assets:"]
            lines += [f"- `{Path(slide['source_image']).name}` — {slide['story_role']}" for slide in post["slides"]] or ["- None assigned (planning-only)"]
            lines.append("")
    return "\n".join(lines)

def _content_coverage(plan:dict[str,Any],knowledge:dict[str,Any])->dict[str,Any]:
    available=sorted(_knowledge_topics(knowledge));projects=[]
    for project in plan["projects"]:
        planned=list(dict.fromkeys(x["content_topic"] for x in project["posts"]));unused=[x for x in available if x not in planned]
        projects.append({"project":project["project"],"knowledge_topics_available":len(available),"topics_planned":len(planned),"topics_unused":len(unused),"available_topics":available,"planned_topics":planned,"unused_topics":unused,"render_ready_topics":[x["content_topic"] for x in project["posts"] if x["render_ready"]],"planning_only_topics":[x["content_topic"] for x in project["posts"] if not x["render_ready"]]})
    return {"schema_version":"1.0.0","module_version":MODULE_VERSION,"projects":projects,"api_calls":{"ai":0,"image_generation":0,"meta":0}}

def _content_coverage_md(coverage:dict[str,Any])->str:
    lines=["# Content Coverage Report",""]
    for item in coverage["projects"]:lines += [f"## {item['project']}","",f"- Knowledge topics available: {item['knowledge_topics_available']}",f"- Topics planned: {item['topics_planned']}",f"- Topics unused: {item['topics_unused']}",f"- Unused topics: {', '.join(item['unused_topics']) or 'none'}",f"- Planning-only topics: {', '.join(item['planning_only_topics']) or 'none'}",""]
    return "\n".join(lines)

def _visual_topic_coverage_md(coverage:dict[str,Any])->str:
    lines=["# Visual Topic Coverage Report","",f"- Full canonical source visuals evaluated: {coverage.get('visuals_evaluated',0)}",f"- Linker version: {coverage.get('linker_version') or 'unknown'}",""]
    for topic in SUPPORTED_TOPICS:
        item=(coverage.get("topics") or {}).get(topic,{}) ;candidates=item.get("candidates",[]);selected=item.get("selected",[])
        lines += [f"## {topic.replace('_',' ').title()}","",f"- Planned topic: `{topic}`",f"- Candidate visuals found: {len(candidates)}",f"- Approved visuals linked: {len(selected)}",f"- Source-link status: `{item.get('status','planned_not_renderable')}`",f"- Source-link reason: `{item.get('reason') or 'approved_source_visuals_linked'}`",f"- Canonical renderability: `{item.get('canonical_renderability','planned_not_renderable')}`",f"- Canonical renderability reason: `{item.get('canonical_renderability_reason') or 'none'}`","","### Linked visuals",""]
        lines += [f"- `{Path(x['path']).name}` — page {x.get('source_page') or 'unknown'} — semantic {x.get('semantic_topic_score')} — quality {x.get('visual_quality_score')} — {x.get('selection_rationale')}" for x in selected] or ["- None"]
        rejected=[x for x in candidates if x.get("link_status")=="rejected"]
        lines += ["","### Rejected candidates",""]+[f"- `{Path(x['path']).name}` — `{x.get('link_rejection_reason')}`" for x in rejected] or ["- None"]
        lines.append("")
    lines += ["## Side Effects","","- AI/image-generation calls: 0","- Meta writes: 0","- Publishing writes: 0",""]
    return "\n".join(lines)
