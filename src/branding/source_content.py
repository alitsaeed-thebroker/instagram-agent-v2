"""Premium, deterministic branding of ranked authentic source images."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat
from src.branding.design_system import TOKENS, layout_family, render_showcase

MODULE_VERSION="7.0.0";SCHEMA_VERSION="7.0.0";WIDTH=TOKENS.canvas_width;HEIGHT=TOKENS.canvas_height;SAFE_MARGIN=TOKENS.margin_x;INSTAGRAM_CAROUSEL_LIMIT=10
PROJECT_OVERVIEW_LAYOUT="PROJECT_OVERVIEW_EDITORIAL";DOMUS_BURGUNDY=(120,24,16,255)
ELIGIBLE_PRIORITIES={"HIGH","MEDIUM"};REJECTED_TYPES={"floor_plan","map","logo","text_heavy","brochure_graphic"}


def generate_branded_content(root:Path,project:str,*,limit:int=INSTAGRAM_CAROUSEL_LIMIT)->tuple[Path,dict[str,Any]]:
    """Evaluate every planned post and render all compatible source-backed posts."""
    slug=_slug(project);inventory=root/"output"/"inventory";ranking=inventory/f"source-image-ranking-{slug}.json";plan_path=root/"output"/"content"/f"{project}-content-plan.json";knowledge_path=root/"output"/"knowledge"/f"{project}.json";config_path=root/"input"/"brand"/"brand-config.json"
    if not ranking.is_file():raise ValueError(f"Branded Content requires ranking inventory: {ranking}")
    if not plan_path.is_file():raise ValueError(f"Branded Content requires machine-readable content plan: {plan_path}")
    if not config_path.is_file():raise ValueError("Branded Content requires input/brand/brand-config.json")
    ranked=json.loads(ranking.read_text(encoding="utf-8"));plan=json.loads(plan_path.read_text(encoding="utf-8"));config=json.loads(config_path.read_text(encoding="utf-8"));knowledge=_read_optional(knowledge_path);deep_knowledge=_read_optional(root/"output/knowledge"/slug/"project-knowledge.json");project_brand=_project_brand(root,slug)
    if plan.get("contract_role")!="compatibility_content_plan" or plan.get("derived_from_canonical_inventory") is not True or not plan.get("canonical_inventory_path"):
        raise ValueError("Branded Content requires a content plan derived from canonical inventory")
    canonical_path=Path(str(plan["canonical_inventory_path"]));canonical_path=canonical_path if canonical_path.is_absolute() else root/canonical_path
    try:canonical=json.loads(canonical_path.read_text(encoding="utf-8"))
    except (OSError,ValueError) as error:raise ValueError(f"Branded Content canonical inventory is missing or invalid: {error}") from error
    if canonical.get("contract_role")!="authoritative_content_opportunity_inventory" or canonical.get("project_id")!=project:
        raise ValueError("Branded Content canonical inventory has wrong authority or project")
    if canonical.get("inventory_version")!=plan.get("canonical_inventory_version") or hashlib.sha256(canonical_path.read_bytes()).hexdigest()!=plan.get("canonical_inventory_sha256"):
        raise ValueError("Branded Content canonical inventory version or hash mismatch")
    logo=_approved_logo(root,config);identity=knowledge.get("project_identity",{}) if isinstance(knowledge,dict) else {};project_name=str(identity.get("project_name") or "").strip()
    if not project_name:raise ValueError("Branded Content requires verified project_identity.project_name")
    project_plan=next((x for x in plan.get("projects",[]) if x.get("project")==project),None);planned_posts=list(project_plan.get("posts",[])) if project_plan else _posts_from_canonical_plan(plan,ranked)
    if not planned_posts:raise ValueError("Branded Content requires at least one planned post")
    rank_by_path={x.get("path"):x for x in ranked.get("images",[])};facts=_safe_facts(identity,knowledge);posts=[];all_items=[];omissions=[]
    output_root=root/"output"/"branded-content"/slug;output_root.mkdir(parents=True,exist_ok=True);rendered_directories=set()
    for plan_index,planned_post in enumerate(planned_posts,1):
        post_number=int(planned_post.get("post_number") or plan_index);topic=str(planned_post.get("content_topic") or "unknown");planned_slide_count=int(planned_post.get("slide_count") or len(planned_post.get("slides",[])));source_assets=list(planned_post.get("source_assets") or [x.get("source_image") for x in planned_post.get("slides",[]) if x.get("source_image")])
        post_format=planned_post.get("post_format");slides=list(planned_post.get("slides",[]))[:min(INSTAGRAM_CAROUSEL_LIMIT,max(0,limit))]
        renderer,reason=_renderer_for_post(planned_post,slides)
        base={"post_number":post_number,"post_id":planned_post.get("post_id") or f"post-{post_number:03d}","post_group_id":planned_post.get("post_group_id"),"title":planned_post.get("title"),"content_topic":topic,"post_format":post_format,"planned_slide_count":planned_slide_count,"source_assets":source_assets}
        if reason:
            posts.append({**base,"slide_count":0,"render_status":"planned_not_renderable","rendered_asset_count":0,"renderer":None,"layout_family":None,"reason":reason,"outputs":[]});continue
        output_dir=output_root/f"post-{post_number:03d}";output_dir.mkdir(parents=True,exist_ok=True);rendered_directories.add(output_dir.name)
        rendered_items=[]
        for slide_index,slide in enumerate(slides,1):
            item=rank_by_path.get(slide.get("source_image"))
            if not item or not (item.get("selected") or item.get("post_selected")) or item.get("selection_priority") not in ELIGIBLE_PRIORITIES or item.get("source_image_type") in REJECTED_TYPES or item.get("rejection_reason"):
                omissions.append({"post_number":post_number,"slide_number":slide_index,"source_image":slide.get("source_image"),"reason":"planned asset is missing, rejected, or not selected"});continue
            try:source=_source_path(root,item)
            except ValueError as error:omissions.append({"post_number":post_number,"slide_number":slide_index,"source_image":slide.get("source_image"),"reason":str(error)});continue
            overview_asset=_is_project_overview(item.get("source_image_type"),topic,slide.get("story_role"));before=_sha(source);output=output_dir/("post.jpg" if post_format=="single" else f"slide-{slide_index:02d}.jpg");supporting=facts[0] if overview_asset else None;overview_copy=_overview_copy(planned_post.get("title"),identity,deep_knowledge) if overview_asset else {}
            rendered,decision=_render(source,logo["path"],project_name,supporting,slide_index,item.get("source_image_type"),project_brand,content_topic=planned_post.get("content_topic"),story_role=slide.get("story_role"),headline=overview_copy.get("headline"),kicker=planned_post.get("title"),supporting_line=overview_copy.get("supporting_line"),headline_source=overview_copy.get("source"),website=config.get("company",{}).get("website"));rendered.save(output,"JPEG",quality=95,optimize=False,progressive=False,subsampling=0)
            if _sha(source)!=before:raise ValueError(f"Selected source was modified: {source}")
            validation=_validate(output,source,logo["path"],decision,item)
            if validation:output.unlink(missing_ok=True);raise ValueError("Branded output validation failed: "+"; ".join(validation))
            rendered_item={"post_number":post_number,"slide_number":slide_index,"output_path":str(output.relative_to(root)),"output_sha256":_sha(output),"source_image":str(source.relative_to(root)),"source_sha256":before,"source_image_type":item.get("source_image_type"),"story_role":slide.get("story_role"),"content_topic":topic,"format":"instagram_feed_4_5","width":WIDTH,"height":HEIGHT,"renderer":renderer,"layout_strategy":decision["layout_strategy"],"logo_used":str(logo["path"].relative_to(root)),"logo_sha256":logo["sha256"],"logo_box":decision["logo_box"],"logo_aspect_ratio":decision["logo_aspect_ratio"],"project_name_rendering":decision["project_name_rendering"],"project_identity_box":decision.get("project_identity_box"),"project_identity_aspect_ratio":decision.get("project_identity_aspect_ratio"),"project_identity_sha256":project_brand.get("sha256"),"project_identity_rendering":decision.get("project_identity_rendering"),"developer_identity_box":decision.get("developer_identity_box"),"project_brand_identity_unavailable":not project_brand.get("available"),"safe_margins":{"top":SAFE_MARGIN,"right":SAFE_MARGIN,"bottom":SAFE_MARGIN,"left":SAFE_MARGIN},"source_render_box":decision["source_render_box"],"source_aspect_ratio":decision["source_aspect_ratio"],"rendered_source_aspect_ratio":decision["rendered_source_aspect_ratio"],"full_source_visible":decision["full_source_visible"],"project_name_added":True,"supporting_text_added":bool(supporting),"supporting_text":supporting["text"] if supporting else None,"knowledge_sources":["project_identity.project_name",*supporting["sources"]] if supporting else ["project_identity.project_name"]}
            rendered_items.append(rendered_item);all_items.append(rendered_item)
        expected_names={Path(x["output_path"]).name for x in rendered_items}
        for stale in output_dir.glob("*.jpg"):
            if stale.name not in expected_names:stale.unlink()
        status="rendered" if len(rendered_items)==len(slides) else "rendered_partial" if rendered_items else "planned_not_renderable";post_reason=None if status=="rendered" else "invalid_or_unavailable_source_asset"
        if not rendered_items:rendered_directories.discard(output_dir.name)
        posts.append({**base,"slide_count":len(rendered_items),"render_status":status,"rendered_asset_count":len(rendered_items),"renderer":renderer if rendered_items else None,"layout_family":renderer if rendered_items else None,"reason":post_reason,"outputs":rendered_items})
    _reconcile_post_directories(output_root,rendered_directories)
    rendered_posts=sum(x["render_status"] in {"rendered","rendered_partial"} for x in posts);deferred_posts=len(posts)-rendered_posts;manifest=inventory/f"branded-content-{slug}.json";payload={"schema_version":SCHEMA_VERSION,"module_version":MODULE_VERSION,"project":project,"contract_role":"legacy_non_authoritative_preview","authoritative_for_creative_production":False,"publication_eligible":False,"superseded_by":"production-manifest -> brand-composer -> creative QA -> release-manager -> post-package QA","content_plan":str(plan_path.relative_to(root)),"posts":posts,"summary":{"planned_posts":len(posts),"renderable_posts":rendered_posts,"rendered_posts":rendered_posts,"deferred_posts":deferred_posts,"rendered_assets":len(all_items)},"outputs_created":len(all_items),"complete":len(posts)==len(planned_posts),"omissions":omissions,"api_calls":{"ai":0,"image_generation":0,"meta":0},"publishing_writes":0,"items":all_items,"created_at":datetime.now(timezone.utc).isoformat()};manifest.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");return manifest,payload


def _renderer_for_post(post:dict[str,Any],slides:list[dict[str,Any]])->tuple[str|None,str|None]:
    if not slides:return None,"no_approved_source_visual"
    post_format=post.get("post_format")
    if post_format not in {"single","carousel"}:return None,"no_approved_renderer"
    if post_format=="single" and len(slides)!=1:return None,"invalid_post_structure"
    if any(str(x.get("source_image_type") or "") in REJECTED_TYPES for x in slides):return None,"no_approved_renderer"
    first=slides[0];overview=_is_project_overview(first.get("source_image_type"),post.get("content_topic"),first.get("story_role"))
    if overview and (post_format!="single" or len(slides)!=1):return None,"no_approved_renderer"
    return (PROJECT_OVERVIEW_LAYOUT if overview else layout_family(str(post.get("content_topic") or ""))),None


def _posts_from_canonical_plan(plan:dict[str,Any],ranked:dict[str,Any])->list[dict[str,Any]]:
    """Adapt canonical-derived planner ideas to the historical renderer shape."""
    by_id={str(x.get("asset_id")):x for x in ranked.get("images",[]) if x.get("asset_id")}
    posts=[]
    for number,idea in enumerate(plan.get("content_ideas",[]),1):
        slides=[]
        for aid in idea.get("selected_source_asset_ids",[]):
            asset=by_id.get(str(aid))
            if not asset:continue
            slides.append({"slide_number":len(slides)+1,"source_image":asset.get("path"),"source_image_type":asset.get("source_image_type"),"story_role":idea.get("content_objective") or idea.get("title"),"selection_priority":asset.get("selection_priority"),"rejection_reason":asset.get("rejection_reason")})
        if not slides:continue
        posts.append({"post_number":number,"post_id":idea.get("content_idea_id"),"post_group_id":idea.get("campaign_id"),"title":idea.get("title"),"content_topic":idea.get("selected_opportunity_id") or idea.get("title"),"post_format":"carousel" if len(slides)>1 else "single","slide_count":len(slides),"slides":slides})
    return posts


def _reconcile_post_directories(output_root:Path,keep:set[str])->None:
    resolved_root=output_root.resolve()
    for directory in output_root.glob("post-[0-9][0-9][0-9]"):
        if not directory.is_dir() or directory.name in keep:continue
        resolved=directory.resolve()
        if resolved.parent!=resolved_root:raise ValueError(f"Unsafe branded-content reconciliation target: {resolved}")
        shutil.rmtree(resolved)


def _render(source:Path,logo_path:Path,project_name:str,supporting:dict[str,Any]|None,index:int,source_type:str|None=None,project_brand:dict[str,Any]|None=None,*,content_topic:str|None=None,story_role:str|None=None,headline:str|None=None,kicker:str|None=None,supporting_line:str|None=None,headline_source:dict[str,Any]|None=None,website:str|None=None)->tuple[Image.Image,dict[str,Any]]:
    if _is_project_overview(source_type,content_topic,story_role):return _render_project_overview(source,logo_path,project_name,supporting,project_brand or {},headline,kicker,supporting_line,headline_source,website)
    brand=project_brand or {};identity_treatment=None
    if brand.get("available"):
        with Image.open(brand["path"]) as raw_mark:mark=ImageOps.exif_transpose(raw_mark).convert("RGBA")
        identity_treatment=_identity_background(mark,brand.get("colors") or [])
    return render_showcase(source,logo_path,project_name,brand,content_topic=content_topic,title=kicker,website=website,identity_treatment=identity_treatment)


def _is_project_overview(source_type:str|None,content_topic:str|None=None,story_role:str|None=None)->bool:
    return source_type in {"full_project_site_plan","masterplan"} or (source_type=="exterior_render" and content_topic=="project_overview" and story_role in {"project_overview","aerial_overview"})
def _overview_copy(planned_title:Any,identity:dict[str,Any],knowledge:dict[str,Any])->dict[str,Any]:
    name=str(identity.get("project_name") or "").strip();facts=knowledge.get("canonical_facts",[]) if isinstance(knowledge,dict) else []
    for fact in facts:
        value=str(fact.get("value") or "").strip()
        if name and re.search(r"\bthe vision of\b",value,re.I) and name.casefold() in value.casefold():
            support=next((str(x.get("value") or "").strip().capitalize() for x in facts if re.fullmatch(r"architecture meets timeless luxury\.?",str(x.get("value") or "").strip(),re.I)),None)
            return {"headline":f"The Vision of {name}","supporting_line":support,"source":{"value":value,"sources":fact.get("sources",[])}}
    project_type=str(identity.get("project_type") or "").strip();return {"headline":project_type.title() if project_type else str(planned_title or name).strip(),"supporting_line":None,"source":{"value":project_type,"sources":[]}}
def _wrap(draw:ImageDraw.ImageDraw,text:str,font:ImageFont.ImageFont,max_width:int,max_lines:int)->list[str]:
    words=text.split();lines=[];current=""
    for word in words:
        candidate=f"{current} {word}".strip()
        if current and draw.textbbox((0,0),candidate,font=font)[2]>max_width:lines.append(current);current=word
        else:current=candidate
    if current:lines.append(current)
    if len(lines)>max_lines:lines=lines[:max_lines];lines[-1]+="…"
    return lines or [text]
def _overview_card_side(image:Image.Image)->str:
    sample=image.convert("L").resize((400,240));left=sample.crop((0,0,150,95));right=sample.crop((250,0,400,95))
    def score(region:Image.Image)->float:return ImageStat.Stat(region.filter(ImageFilter.FIND_EDGES)).mean[0]+ImageStat.Stat(region).stddev[0]*.25
    return "upper_right" if score(right)<=score(left)*1.2 else "upper_left"
def _overview_hero(image:Image.Image,size:tuple[int,int])->tuple[Image.Image,float]:
    target_ratio=size[0]/size[1];source_ratio=image.width/image.height;crop_fraction=abs(1-target_ratio/source_ratio) if source_ratio>target_ratio else abs(1-source_ratio/target_ratio)
    if crop_fraction<=.18:return ImageOps.fit(image,size,method=Image.Resampling.LANCZOS,centering=(.5,.5)),crop_fraction
    return ImageOps.contain(image,size,method=Image.Resampling.LANCZOS),0.0
def _lower_right_mask(size:tuple[int,int],radius:int)->Image.Image:
    mask=Image.new("L",size,0);draw=ImageDraw.Draw(mask);draw.rounded_rectangle((0,0,size[0],size[1]),radius=radius,fill=255);draw.rectangle((0,0,size[0],size[1]-radius),fill=255);draw.rectangle((0,0,size[0]-radius,size[1]),fill=255);return mask
def _draw_location_icon(draw:ImageDraw.ImageDraw,center:tuple[int,int])->None:
    x,y=center;draw.ellipse((x-18,y-18,x+18,y+18),fill=DOMUS_BURGUNDY);draw.ellipse((x-7,y-10,x+7,y+4),outline=(255,255,255,255),width=3);draw.polygon(((x-6,y+1),(x+6,y+1),(x,y+12)),fill=(255,255,255,255));draw.ellipse((x-2,y-5,x+2,y-1),fill=DOMUS_BURGUNDY)
def _draw_web_icon(draw:ImageDraw.ImageDraw,center:tuple[int,int])->None:
    x,y=center;draw.ellipse((x-18,y-18,x+18,y+18),fill=DOMUS_BURGUNDY);draw.ellipse((x-10,y-10,x+10,y+10),outline=(255,255,255,255),width=2);draw.arc((x-5,y-10,x+5,y+10),90,270,fill=(255,255,255,255),width=2);draw.arc((x-5,y-10,x+5,y+10),270,90,fill=(255,255,255,255),width=2);draw.line((x-9,y,x+9,y),fill=(255,255,255,255),width=2)


def _render_project_overview(source:Path,logo_path:Path,project_name:str,supporting:dict[str,Any]|None,project_brand:dict[str,Any],headline:str|None,kicker:str|None,supporting_line:str|None,headline_source:dict[str,Any]|None,website:str|None)->tuple[Image.Image,dict[str,Any]]:
    """White editorial overview composition; isolated from approved villa geometry."""
    with Image.open(source) as raw:image=ImageOps.exif_transpose(raw).convert("RGB")
    source_ratio=image.width/image.height;canvas=Image.new("RGBA",(WIDTH,HEIGHT),(255,255,255,255));draw=ImageDraw.Draw(canvas);header_bottom=330;footer_top=HEIGHT-180;hero_zone_h=footer_top-header_bottom;hero,crop_fraction=_overview_hero(image,(WIDTH,hero_zone_h));hero_w,hero_h=hero.size;hero_x=(WIDTH-hero_w)//2;hero_y=header_bottom+(hero_zone_h-hero_h)//2;hero_mask=_lower_right_mask(hero.size,20);canvas.paste(hero.convert("RGBA"),(hero_x,hero_y),hero_mask);source_box=[hero_x,hero_y,hero_x+hero_w,hero_y+hero_h]
    draw.rectangle((SAFE_MARGIN,SAFE_MARGIN,SAFE_MARGIN+8,header_bottom-54),fill=DOMUS_BURGUNDY)
    with Image.open(logo_path) as raw_logo:logo=ImageOps.exif_transpose(raw_logo).convert("RGBA")
    logo_ratio=logo.width/logo.height;logo_w=120;logo_h=round(logo_w/logo_ratio);logo=logo.resize((logo_w,logo_h),Image.Resampling.LANCZOS);logo_x=SAFE_MARGIN+28;logo_y=SAFE_MARGIN;canvas.alpha_composite(logo,(logo_x,logo_y));logo_box=[logo_x,logo_y,logo_x+logo_w,logo_y+logo_h]
    text_x=logo_x+logo_w+38;kicker_text=str(kicker or "").strip().upper();headline_text=str(headline or project_name).strip();draw.text((text_x,SAFE_MARGIN+3),kicker_text,font=_font(17),fill=DOMUS_BURGUNDY);headline_font=_font(46);headline_lines=_wrap(draw,headline_text,headline_font,405,2);headline_y=SAFE_MARGIN+34
    for line in headline_lines:draw.text((text_x,headline_y),line,font=headline_font,fill=(17,17,17,255));headline_y+=52
    if supporting_line:draw.text((text_x,headline_y+4),str(supporting_line),font=_font(21),fill=(75,75,75,255))
    authentic=bool(project_brand.get("available"));project_box=None;project_ratio=None;card_w=350;card_h=158;card_side=_overview_card_side(image);card_x=WIDTH-SAFE_MARGIN-card_w if card_side=="upper_right" else SAFE_MARGIN;card_y=header_bottom-74;shadow=Image.new("RGBA",canvas.size,(0,0,0,0));ImageDraw.Draw(shadow).rounded_rectangle((card_x+5,card_y+8,card_x+card_w+5,card_y+card_h+8),radius=14,fill=(0,0,0,70));shadow=shadow.filter(ImageFilter.GaussianBlur(8));canvas=Image.alpha_composite(canvas,shadow);draw=ImageDraw.Draw(canvas)
    identity_manifest=None
    if authentic:
        with Image.open(project_brand["path"]) as raw_mark:mark=ImageOps.exif_transpose(raw_mark).convert("RGBA")
        identity_treatment=_identity_background(mark,project_brand.get("colors") or []);identity_manifest=identity_treatment["manifest"];draw.rounded_rectangle((card_x,card_y,card_x+card_w,card_y+card_h),radius=14,fill=identity_treatment["rgba"]);identity_x=card_x+28;identity_y=card_y+22
        project_ratio=mark.width/mark.height;mark_h=63;mark_w=min(card_w-56,round(mark_h*project_ratio));mark_h=round(mark_w/project_ratio);mark=mark.resize((mark_w,mark_h),Image.Resampling.LANCZOS);canvas.alpha_composite(mark,(identity_x,identity_y));project_box=[identity_x,identity_y,identity_x+mark_w,identity_y+mark_h]
        developer_path=project_brand.get("developer_wordmark_path")
        if developer_path:
            with Image.open(developer_path) as raw_dev:developer=ImageOps.exif_transpose(raw_dev).convert("RGBA")
            dev_h=29;dev_w=min(card_w-100,round(dev_h*developer.width/developer.height));dev_h=round(dev_w*developer.height/developer.width);developer=developer.resize((dev_w,dev_h),Image.Resampling.LANCZOS);canvas.alpha_composite(developer,(identity_x,identity_y+mark_h+13))
    else:
        draw.rounded_rectangle((card_x,card_y,card_x+card_w,card_y+card_h),radius=14,fill=(255,255,255,245));draw.text((card_x+24,card_y+52),project_name,font=_font(32),fill=(17,17,17,255))
    draw.rectangle((0,footer_top,WIDTH,HEIGHT),fill=(255,255,255,255));footer_mid=footer_top+(HEIGHT-footer_top)//2;draw.line((WIDTH//2,footer_top+52,WIDTH//2,HEIGHT-52),fill=(220,220,220,255),width=2)
    location=str(supporting.get("text") if supporting else "").strip();_draw_location_icon(draw,(SAFE_MARGIN+18,footer_mid))
    if location:draw.text((SAFE_MARGIN+50,footer_mid-15),location,font=_font(24),fill=(55,55,55,255))
    if website:_draw_web_icon(draw,(WIDTH//2+68,footer_mid));draw.text((WIDTH//2+100,footer_mid-15),str(website),font=_font(24),fill=(17,17,17,255))
    decision={"layout_strategy":PROJECT_OVERVIEW_LAYOUT,"logo_box":logo_box,"logo_aspect_ratio":round(logo_ratio,6),"panel_box":[0,0,WIDTH,header_bottom],"footer_box":[0,footer_top,WIDTH,HEIGHT],"supporting_font_size":24,"overview_kicker":kicker_text,"overview_headline":"\n".join(headline_lines),"overview_headline_source":headline_source,"overview_supporting_line":supporting_line,"project_name_rendering":"wordmark" if authentic else "generic_fallback","project_identity_box":project_box,"project_identity_card_box":[card_x,card_y,card_x+card_w,card_y+card_h],"project_identity_card_placement":card_side,"project_identity_overlaps_header_image":card_y<header_bottom<card_y+card_h,"project_identity_aspect_ratio":round(project_ratio,6) if project_ratio else None,"project_identity_rendering":identity_manifest,"developer_identity_used":bool(project_brand.get("developer_wordmark_path")),"source_render_box":source_box,"source_aspect_ratio":round(source_ratio,6),"rendered_source_aspect_ratio":round(source_ratio,6),"source_crop_fraction":round(crop_fraction,4),"full_source_visible":crop_fraction==0,"editorial_background":"#FFFFFF","accent_color":"#781810","content_topic":"project_overview","location_icon":"vector_pin","website_icon":"vector_globe","footer_divider":True,"location_rendered":bool(location),"website_rendered":bool(website),"design_tokens":TOKENS.__dict__};return canvas.convert("RGB"),decision


def _layout(image:Image.Image,index:int)->tuple[str,str]:
    gray=image.convert("L");candidates=[("MINIMAL_CORNER","top_left",(0,0,430,300)),("CLEAN_TOP","top_right",(650,0,1080,300)),("EDITORIAL_BOTTOM","bottom_left",(0,1000,560,1350)),("IMAGE_ONLY_BRAND","bottom_right",(650,1020,1080,1350))];scores=[]
    for name,anchor,box in candidates:
        region=gray.crop(box);edge=ImageStat.Stat(region.filter(ImageFilter.FIND_EDGES)).mean[0];contrast=ImageStat.Stat(region).stddev[0];scores.append((edge+contrast*.35+(index%4)*.001 if anchor==candidates[index%4][1] else edge+contrast*.35,name,anchor))
    _,name,anchor=min(scores);return name,anchor
def _position(anchor:str,w:int,h:int)->tuple[int,int]:
    return {"top_left":(SAFE_MARGIN,SAFE_MARGIN),"top_right":(WIDTH-SAFE_MARGIN-w,SAFE_MARGIN),"bottom_left":(SAFE_MARGIN,HEIGHT-SAFE_MARGIN-h),"bottom_right":(WIDTH-SAFE_MARGIN-w,HEIGHT-SAFE_MARGIN-h)}[anchor]
def _font(size:int)->ImageFont.FreeTypeFont|ImageFont.ImageFont:
    for path in (Path("C:/Windows/Fonts/segoeui.ttf"),Path("C:/Windows/Fonts/arial.ttf")):
        if path.is_file():return ImageFont.truetype(str(path),size)
    return ImageFont.load_default()
def _safe_facts(identity:dict[str,Any],knowledge:dict[str,Any])->list[dict[str,Any]]:
    provenance=knowledge.get("fact_provenance",{});result=[]
    for field in ("location","project_type"):
        text=str(identity.get(field) or "").strip();sources=provenance.get(f"project_identity.{field}",[])
        if field=="location":text=_concise_location(text)
        if text and sources:result.append({"text":text,"sources":[f"project_identity.{field}",*[f"{x.get('source_document')}#page={x.get('source_page')}" for x in sources]]})
    return result
def _concise_location(text:str)->str:
    road=re.search(r"\b(\d+\s*m\s+Road)\b",text,re.IGNORECASE);city=re.search(r"\b(Erbil)\b",text,re.IGNORECASE)
    if road and city:return f"{re.sub(r'\s+', '', road.group(1).split('m')[0])}m Road, {city.group(1)}"
    return text if len(text)<=42 else ""
def _approved_logo(root:Path,config:dict[str,Any])->dict[str,Any]:
    approval=config.get("approval",{});policy=config.get("visual_identity",{}).get("logo_policy",{})
    if approval.get("status")!="approved" or not approval.get("locked") or policy.get("status")!="available":raise ValueError("No approved and locked Domus Erbil logo is available")
    candidates=sorted((root/"input"/"brand"/"logos").glob("*"));expected=approval.get("approved_logo_hash")
    path=next((x for x in candidates if x.is_file() and _sha(x)==expected),None)
    if not path:raise ValueError("Approved Domus Erbil logo is missing or its hash changed")
    try:
        with Image.open(path) as image:image.verify()
    except Exception as error:raise ValueError(f"Approved Domus Erbil logo is unreadable: {error}") from error
    return {"path":path,"sha256":expected}
def _source_path(root:Path,item:dict[str,Any])->Path:
    selected=item.get("selected_path");path=root/"output"/"selected-images"/selected if selected else root/"output"/"source-images"/item["path"]
    if not path.is_file():raise ValueError(f"Selected source image is missing: {path}")
    if _sha(path)!=item.get("sha256"):raise ValueError(f"Selected source image hash mismatch: {path}")
    return path
def _validate(output:Path,source:Path,logo:Path,decision:dict[str,Any],item:dict[str,Any])->list[str]:
    errors=[]
    with Image.open(output) as image:
        if image.size!=(WIDTH,HEIGHT):errors.append("output dimensions are not 1080x1350")
    x1,y1,x2,y2=decision["logo_box"]
    if min(x1,y1,WIDTH-x2,HEIGHT-y2)<SAFE_MARGIN:errors.append("logo violates safe margins")
    with Image.open(logo) as image:actual=image.width/image.height
    if abs(actual-decision["logo_aspect_ratio"])>.001:errors.append("logo aspect ratio changed")
    if abs(decision["source_aspect_ratio"]-decision["rendered_source_aspect_ratio"])>.01:errors.append("source image was stretched")
    if item.get("selection_priority") not in ELIGIBLE_PRIORITIES or item.get("rejection_reason"):errors.append("rejected ranking item was used")
    if not source.is_file():errors.append("source image is missing")
    return errors
def _project_brand(root:Path,slug:str)->dict[str,Any]:
    manifest=_read_optional(root/"output/inventory"/f"project-brand-{slug}.json");wordmark=manifest.get("project_wordmark",{})
    if not wordmark.get("available"):return {"available":False,"rendering":"generic_fallback"}
    path=root/str(wordmark.get("path") or "")
    if not path.is_file() or _sha(path)!=wordmark.get("output_sha256"):return {"available":False,"rendering":"generic_fallback"}
    result={"available":True,"rendering":"wordmark","path":path,"sha256":wordmark["output_sha256"],"colors":manifest.get("brand_colors",[])};developer=manifest.get("developer_identity",{});developer_path=root/str(developer.get("wordmark_path") or "")
    if developer.get("available") and developer_path.is_file() and _sha(developer_path)==developer.get("wordmark_sha256"):result["developer_wordmark_path"]=developer_path;result["developer_wordmark_sha256"]=developer["wordmark_sha256"]
    return result
def _hex_rgba(value:str)->tuple[int,int,int,int]:
    match=re.fullmatch(r"#([0-9a-fA-F]{6})",str(value))
    if not match:return DOMUS_BURGUNDY
    raw=match.group(1);return (int(raw[0:2],16),int(raw[2:4],16),int(raw[4:6],16),255)
def _relative_luminance(rgb:tuple[int,int,int])->float:
    values=[]
    for channel in rgb:
        value=channel/255;values.append(value/12.92 if value<=.04045 else ((value+.055)/1.055)**2.4)
    return .2126*values[0]+.7152*values[1]+.0722*values[2]
def _foreground_luminance(artwork:Image.Image)->float:
    rgba=artwork.convert("RGBA").resize((min(320,artwork.width),min(160,artwork.height)),Image.Resampling.LANCZOS);visible=[(r,g,b) for r,g,b,a in rgba.getdata() if a>=64]
    if not visible:return 0.5
    return sum(_relative_luminance(pixel) for pixel in visible)/len(visible)
def _contrast_ratio(left:float,right:float)->float:
    lighter=max(left,right);darker=min(left,right);return (lighter+.05)/(darker+.05)
def _identity_background(artwork:Image.Image,palette:list[Any])->dict[str,Any]:
    foreground=_foreground_luminance(artwork);brand=[]
    for value in palette:
        rgba=_hex_rgba(str(value))
        if re.fullmatch(r"#[0-9a-fA-F]{6}",str(value)):brand.append((str(value).upper(),rgba,_contrast_ratio(foreground,_relative_luminance(rgba[:3]))))
    candidates=brand or [("#151515",(21,21,21,255),_contrast_ratio(foreground,_relative_luminance((21,21,21)))),("#FAFAFA",(250,250,250,255),_contrast_ratio(foreground,_relative_luminance((250,250,250))))]
    color,rgba,contrast=max(candidates,key=lambda item:item[2])
    if contrast<3 and brand:
        neutral=[("#151515",(21,21,21,255),_contrast_ratio(foreground,_relative_luminance((21,21,21)))),("#FAFAFA",(250,250,250,255),_contrast_ratio(foreground,_relative_luminance((250,250,250))))];color,rgba,contrast=max(neutral,key=lambda item:item[2]);mode="solid_neutral"
    else:mode="solid_brand_color" if brand else "solid_neutral"
    return {"rgba":rgba,"manifest":{"background_mode":mode,"background_color":color,"contrast_checked":True,"contrast_ratio":round(contrast,3),"contrast_status":"pass" if contrast>=3 else "review_required","wordmark_recolored":False,"texture_used":False}}
def _read_optional(path:Path)->dict[str,Any]:
    try:return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):return {}
def _slug(value:str)->str:return re.sub(r"[^\w.-]+","-",value,flags=re.UNICODE).strip("-.") or "project"
def _sha(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()
