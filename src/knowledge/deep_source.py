"""Page-native, source-grounded PDF understanding and coverage auditing."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime,timezone
import hashlib,json,re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

MODULE_VERSION="3.0.0";SCHEMA_VERSION="3.0.0"
VISUAL_TYPES={"site_plan":"full_project_site_plan","masterplan":"masterplan","project_aerial":"project_aerial","project_overview":"project_overview","aerial_view":"project_aerial","exterior":"exterior_render","villa_exterior":"villa_exterior","apartment_exterior":"apartment_exterior","tower_exterior":"tower_exterior","office_exterior":"office_exterior","retail_exterior":"retail_exterior","architectural_detail":"architectural_detail","interior":"generic_interior","residential_space":"generic_interior","villa_interior":"villa_interior","apartment_interior":"apartment_interior","office_interior":"office_interior","commercial_interior":"commercial_interior","amenity":"amenity","pool":"pool","clubhouse":"clubhouse","gym":"gym","sports":"sports","garden_landscape":"landscape","greenery_landscape":"landscape","landscape":"landscape","park":"park","children_area":"children_area","wellness":"wellness","retail_amenity":"retail_amenity","lifestyle":"lifestyle","location_map":"location_map","map":"map","floorplan":"floor_plan","floor_plan":"floor_plan","villa_layout":"unit_plan","unit_plan":"unit_plan","masterplan_drawing":"masterplan_drawing","technical_plan":"technical_drawing","technical_drawing":"technical_drawing","diagram":"diagram","logo":"project_logo","project_logo":"project_logo","project_wordmark":"project_wordmark","developer_logo":"developer_logo","developer_wordmark":"developer_wordmark","branding_graphic":"project_wordmark","decorative_graphic":"decorative","text_heavy_page":"text_heavy"}


def analyze_deep_source(root:Path,project:str,pdfs:list[Path])->tuple[Path,Path,dict[str,Any]]:
    if not pdfs:raise ValueError("Deep Source Analysis requires at least one source PDF")
    slug=_slug(project);manifest=_read(root/"output/source-images"/project/"manifest.json");intelligence=_read(root/"output/asset-intelligence"/f"{project}-asset-intelligence.json");intel={str(x.get("asset_id")):x for x in intelligence.get("assets",[])};assets_by_doc_page:dict[tuple[str,int],list[dict[str,Any]]]=defaultdict(list)
    for asset in manifest.get("assets",[]):assets_by_doc_page[(str(asset.get("source_document")),int(asset.get("source_page") or 0))].append(asset)
    pages=[];current_section="unclassified";extraction_errors=[]
    for pdf in pdfs:
        try:reader=PdfReader(str(pdf))
        except Exception as error:extraction_errors.append({"document":pdf.name,"error":str(error)});continue
        for number,page in enumerate(reader.pages,1):
            try:raw=page.extract_text() or "";error=None
            except Exception as exc:raw="";error=str(exc)
            if error:extraction_errors.append({"document":pdf.name,"page":number,"error":error})
            blocks=_blocks(raw);title=_title(blocks)
            if title:current_section=_section_id(title)
            page_assets=[]
            for source_asset in assets_by_doc_page.get((pdf.name,number),[]):
                semantic=intel.get(str(source_asset.get("asset_id")),{});kind=_visual_type(semantic);unit_label=_unit_label(raw);page_assets.append({"asset_id":source_asset.get("asset_id"),"asset_path":str((root/"output/source-images"/project/str(source_asset.get("filename"))).relative_to(root)),"page_number":number,"image_type":kind,"description":semantic.get("dominant_subject") or semantic.get("description") or "","section":current_section,"related_text":[title] if title else [],"related_facts":[],"marketing_topic":_topic(kind,current_section),"related_property_type":unit_label,"related_unit_type":unit_label,"related_villa_type":_villa_label(raw),"related_amenity":None,"related_floor":_floor(raw),"duplicate_group":source_asset.get("sha256"),"confidence":float(semantic.get("confidence") or .5),"source_dimensions":{"width":source_asset.get("width"),"height":source_asset.get("height")}})
            languages=_languages(raw);facts=_facts(raw,pdf.name,number);bullets=[x for x in blocks if _is_bullet(x)];contacts=_contacts(raw,pdf.name,number);technical=[x for x in facts if x["category"]=="technical_specification"];claims=[x for x in facts if x["category"] in {"marketing_claim","brand_message","slogan"}]
            for visual in page_assets:
                visual["related_facts"]=[x["value"] for x in facts]
                visual["areas"]=_areas(raw) if visual["image_type"] in {"floor_plan","unit_plan","technical_drawing"} else []
                visual["rooms"]=_rooms(raw) if visual["image_type"] in {"floor_plan","unit_plan","technical_drawing"} else []
            unresolved=[]
            if not raw.strip() and not page_assets:unresolved.append("no text or extracted visual")
            if any(x["image_type"]=="unknown" for x in page_assets):unresolved.append("unclassified visual")
            pages.append({"document":pdf.name,"page_number":number,"section":current_section,"title":title,"page_title":title,"languages":languages,"multilingual_text":_language_text(blocks),"raw_text":raw,"text_blocks":[{"block_number":i+1,"text":text,"languages":_languages(text),"confidence":.95 if text.strip() else 0.0} for i,text in enumerate(blocks)],"headings":[title] if title else [],"subheadings":[],"paragraphs":[x for x in blocks if not _is_bullet(x) and x!=title],"bullet_lists":bullets,"tables":[],"measurements":_areas(raw),"facts":facts,"marketing_claims":claims,"technical_data":technical,"images":page_assets,"visual_assets":page_assets,"diagrams":[x for x in page_assets if x["image_type"] in {"full_project_site_plan","masterplan","floor_plan","unit_plan","technical_drawing"}],"logos":[x for x in page_assets if x["image_type"] in {"project_logo","project_wordmark","developer_logo","developer_wordmark"}],"developer_identity":[x for x in page_assets if x["image_type"] in {"developer_logo","developer_wordmark"}],"maps":[x for x in page_assets if x["image_type"] in {"map","location_map"}],"plans":[x for x in page_assets if x["image_type"] in {"full_project_site_plan","masterplan","floor_plan","unit_plan","technical_drawing"}],"contacts":contacts,"relationships":[{"relationship":"same_page_context","section":current_section,"visual_asset_id":x["asset_id"],"text_block_numbers":list(range(1,len(blocks)+1))} for x in page_assets],"text_extraction_status":"complete" if raw.strip() and not error else "partial" if page_assets else "failed","unresolved":unresolved,"needs_manual_review":bool(unresolved or error)})
    canonical=_canonical_facts(pages);sections=[]
    for page in pages:
        if page["section"] not in sections and page["section"]!="unclassified":sections.append(page["section"])
    visuals=[x for p in pages for x in p["images"]];unit_types=_unit_types(pages);villa_types=[x for x in unit_types if x.get("category")=="villa"];features=_category_items(pages,"features");amenities=_category_items(pages,"amenities");contacts=_dedupe([x for p in pages for x in p["contacts"]],"value");unresolved=[{"document":p["document"],"page_number":p["page_number"],"issues":p["unresolved"]} for p in pages if p["needs_manual_review"]]
    total=len(pages);analyzed=sum(bool(p["text_extraction_status"]!="failed" or p["images"]) for p in pages);classified=sum(x["image_type"]!="unknown" for x in visuals);structural=sum(bool(p["page_title"] or p["text_blocks"] or p["images"]) for p in pages);score=round(100*(.45*(analyzed/max(1,total))+.25*(structural/max(1,total))+.20*(classified/max(1,len(visuals)))+.10*(1-len(unresolved)/max(1,total))),1);status="complete" if analyzed==total and not unresolved and score>=95 else "partial"
    offering_facts=[x for x in canonical if re.search(r"villa|apartment|office|commercial|retail|penthouse|duplex|townhouse|plot|hotel|hospitality|unit",x["value"],re.I)]
    payload={"schema_version":SCHEMA_VERSION,"module_version":MODULE_VERSION,"generated_at":datetime.now(timezone.utc).isoformat(),"project":project,"knowledge_status":status,"knowledge_completeness_score":score,"source_documents":[{"path":str(p.relative_to(root)),"sha256":_sha(p)} for p in pdfs],"project_identity":_identity(canonical),"developer_identity":{"name":None,"logos":[x for x in visuals if x["image_type"] in {"developer_logo","developer_wordmark"}],"confidence":0.0},"project_positioning":{"messages":[x for x in canonical if x["category"] in {"marketing_claim","brand_message"}]},"location":{"facts":[x for x in canonical if x["category"]=="location"]},"project_overview":{"facts":[x for x in canonical if x["category"]=="fact"]},"property_offering":{"facts":offering_facts},"property_types":unit_types,"unit_types":unit_types,"villa_offering":{"facts":[x for x in offering_facts if "villa" in x["value"].casefold()]},"villa_types":villa_types,"features":features,"amenities":amenities,"lifestyle":[x for x in canonical if x["category"]=="marketing_claim"],"plans_and_layouts":[x for x in visuals if x["image_type"] in {"floor_plan","unit_plan","masterplan_drawing","technical_drawing","diagram"}],"contact_information":contacts,"brand_identity":{"project_assets":[x for x in visuals if x["image_type"] in {"project_logo","project_wordmark"}],"developer_assets":[x for x in visuals if x["image_type"] in {"developer_logo","developer_wordmark"}],"font_identified":False},"source_sections":sections,"source_visuals":visuals,"canonical_facts":canonical,"unresolved_pages":unresolved,"unresolved_items":unresolved,"quality_gates":{"all_pages_analyzed":analyzed==total,"all_major_headings_linked":all(p["section"]!="unclassified" for p in pages if p["page_title"]),"visual_classification_rate":round(classified/max(1,len(visuals)),3),"unresolved_page_count":len(unresolved),"passed":status=="complete"},"api_calls":{"ai":0,"image_generation":0,"meta":0}}
    knowledge_dir=root/"output/knowledge"/slug;pages_dir=knowledge_dir/"pages";pages_dir.mkdir(parents=True,exist_ok=True)
    for page in pages:(pages_dir/f"page-{page['page_number']:03d}.json").write_text(json.dumps(page,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    knowledge_path=knowledge_dir/"project-knowledge.json";summary_path=knowledge_dir/"project-knowledge-summary.md";knowledge_path.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");summary_path.write_text(_summary(payload),encoding="utf-8")
    coverage=_coverage(payload,pages,extraction_errors);reports=root/"output/reports";reports.mkdir(parents=True,exist_ok=True);coverage_json=reports/f"source-coverage-{slug}.json";coverage_md=reports/f"source-coverage-{slug}.md";audit_json=reports/f"page-audit-{slug}.json";audit_md=reports/f"page-audit-{slug}.md";coverage_json.write_text(json.dumps(coverage,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");coverage_md.write_text(_coverage_md(coverage),encoding="utf-8");audit_json.write_text(json.dumps({"project":project,"pages":pages},indent=2,ensure_ascii=False)+"\n",encoding="utf-8");audit_md.write_text(_page_audit(pages),encoding="utf-8");payload["artifacts"]={"coverage_json":str(coverage_json),"coverage_markdown":str(coverage_md),"page_audit_json":str(audit_json),"page_audit_markdown":str(audit_md),"knowledge_json":str(knowledge_path),"summary_markdown":str(summary_path)};return knowledge_path,coverage_json,payload


def _blocks(text:str)->list[str]:return [re.sub(r"[ \t]+"," ",x).strip() for x in text.splitlines() if x.strip()]
def _title(blocks:list[str])->str|None:
    """Find a display heading, including headings placed after translated lists."""
    candidates=[]
    for index,block in enumerate(blocks):
        line=block.strip();words=line.split()
        if _is_bullet(line) or not (3<=len(line)<=80) or not (1<=len(words)<=10):continue
        if re.fullmatch(r"[\d\W]+",line) or re.search(r"[.!?]$",line):continue
        if len(re.findall(r"[A-Za-z]",line))<3:continue
        titled=sum(bool(re.match(r"^[A-Z]",word)) for word in words if re.search(r"[A-Za-z]",word))
        score=titled/max(1,len(words))+(0.35 if "&" in line or "-" in line else 0)-index*.001
        if score>=.55:candidates.append((score,line))
    return max(candidates,key=lambda item:item[0])[1] if candidates else None
def _section_id(title:str)->str:return re.sub(r"[^a-z0-9]+","_",title.casefold()).strip("_") or "unclassified"
def _languages(text:str)->list[str]:
    result=[]
    if re.search(r"[A-Za-z]",text):result.append("en")
    if re.search(r"[\u0600-\u06ff]|[ØÙ]",text):result.append("ar")
    if re.search(r"[ێەۆڵڕÛ]",text):result.append("ku")
    return result or ["unknown"]
def _language_text(blocks:list[str])->dict[str,dict[str,Any]]:
    grouped={"english":[],"arabic":[],"kurdish":[]}
    for block in blocks:
        langs=_languages(block)
        if "en" in langs:grouped["english"].append(block)
        if "ar" in langs:grouped["arabic"].append(block)
        if "ku" in langs:grouped["kurdish"].append(block)
    return {name:{"text":"\n".join(values),"confidence":.9 if values else 0.0} for name,values in grouped.items()}
def _visual_type(semantic:dict[str,Any])->str:
    key=str(semantic.get("visual_category") or semantic.get("asset_type") or "unknown").casefold();kind=VISUAL_TYPES.get(key,"unknown");subject=" ".join(str(semantic.get(x) or "") for x in ("dominant_subject","visible_text_summary","asset_subtype")).casefold()
    if "developer_logo" in subject or (kind=="project_logo" and "developer" in subject):return "developer_logo"
    if "project_wordmark" in subject:return "project_wordmark"
    if kind=="exterior_render" and "villa" in subject:return "villa_exterior"
    if kind=="interior_render" and "villa" in subject:return "villa_interior"
    return kind
def _topic(kind:str,section:str)->str:return "villas" if "villa" in kind or "villa" in section else "amenities" if kind in {"amenity","lifestyle"} else "project_overview" if kind in {"full_project_site_plan","masterplan"} else section
def _facts(text:str,document:str,page:int)->list[dict[str,Any]]:
    facts=[]
    for value in _blocks(text):
        if len(value)<4:continue
        category="technical_specification" if re.search(r"\b\d+(?:\.\d+)?\s*(?:m²|m2|sqm|M2|vehicles?|mins?|minutes?)\b",value,re.I) else "location" if re.search(r"road|airport|park|mall|citadel|location",value,re.I) else "marketing_claim" if re.search(r"luxury|exclusive|prestige|lifestyle|finest|perfect|world.class",value,re.I) else "fact"
        facts.append({"value":value,"category":category,"confidence":.95,"sources":[{"source_document":document,"source_page":page,"source_text":value}]})
    return facts
def _contacts(text:str,document:str,page:int)->list[dict[str,Any]]:
    patterns=[("email",r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),("website",r"(?:https?://|www\.)[^\s]+"),("phone",r"(?:\+?\d[\d\s()\-]{7,}\d)")];out=[]
    for kind,pattern in patterns:
        for value in re.findall(pattern,text):
            value=value.strip();digits=re.sub(r"\D","",value)
            if kind=="phone" and not (9<=len(digits)<=15):continue
            out.append({"type":kind,"value":value,"confidence":.95,"sources":[{"source_document":document,"source_page":page}]})
    for line in _blocks(text):
        if re.search(r"sales\s+cent(?:er|re)|address",line,re.I):out.append({"type":"address","value":line,"confidence":.95,"sources":[{"source_document":document,"source_page":page}]})
    return out
def _is_bullet(text:str)->bool:return bool(re.match(r"^(?:[•\-–]|â€¢|â€“)",text))
def _areas(text:str)->list[str]:return list(dict.fromkeys(re.findall(r"\b\d+(?:\.\d+)?\s*(?:m²|m2|M2|sqm)\b",text,re.I)))
def _rooms(text:str)->list[dict[str,Any]]:
    result=[];blocks=_blocks(text)
    for index,line in enumerate(blocks):
        match=re.match(r"([^\d]{2,40}?)\s+(\d+(?:\.\d+)?)\s*(?:m²|m2|M2|sqm)\b",line,re.I)
        if match:result.append({"name":match.group(1).strip(" :-"),"area":match.group(2),"unit":"m2","confidence":.9})
        room=re.match(r"\d+\s*\|\s*(.+)$",line)
        if room and index+1<len(blocks):
            area=re.match(r"(\d+(?:\.\d+)?)\s*(?:m²|m2|M2|sqm)\b",blocks[index+1],re.I)
            if area:result.append({"name":room.group(1).strip(),"area":area.group(1),"unit":"m2","confidence":.95})
    return result
def _villa_label(text:str)->str|None:
    match=re.search(r"(?:villa\s*)?type\s*([A-Z])\b",text,re.I);return f"Type {match.group(1).upper()}" if match else None
def _unit_label(text:str)->str|None:
    patterns=[(r"(?:villa\s*)?type\s*([A-Z])\b",lambda m:f"Type {m.group(1).upper()}"),(r"\b([1-9])\s*(?:BR|bed(?:room)?s?)\b",lambda m:f"{m.group(1)}BR"),(r"\b(penthouse|duplex|townhouse|office|commercial unit|retail unit|plot|hotel suite)\b",lambda m:m.group(1).title())]
    for pattern,label in patterns:
        match=re.search(pattern,text,re.I)
        if match:return label(match)
    return None
def _floor(text:str)->str|None:
    match=re.search(r"\b(ground floor|first floor|second floor|penthouse|basement)\b",text,re.I);return match.group(1).casefold() if match else None
def _canonical_facts(pages:list[dict[str,Any]])->list[dict[str,Any]]:
    merged={}
    for page in pages:
        for fact in page["facts"]:
            key=re.sub(r"\W+"," ",fact["value"].casefold()).strip();existing=merged.setdefault(key,{**fact,"sources":[]});existing["sources"].extend(fact["sources"])
    return list(merged.values())
def _villa_types(pages:list[dict[str,Any]])->list[dict[str,Any]]:
    found={};current=None
    for page in pages:
        text=page["raw_text"]
        match=re.search(r"(?:villa\s*)?type\s*([A-Z])\b",text,re.I)
        if match:current=f"Type {match.group(1).upper()}"
        if not current or not (match or page["plans"] or re.search(r"\b(?:ground|first|second|penthouse)\s+floor\b",text,re.I)):continue
        obj=found.setdefault(current,{"type":current[-1],"label":current,"plot_area":None,"ground_floor_area":None,"first_floor_area":None,"upper_floor_area":None,"buildup_area":None,"floor_count":0,"areas":[],"floors":[],"rooms":[],"special_spaces":[],"source_pages":[]});source_ref={"document":page["document"],"page":page["page_number"]}
        if source_ref not in obj["source_pages"]:obj["source_pages"].append(source_ref)
        obj["areas"].extend(_areas(text));obj["areas"]=list(dict.fromkeys(obj["areas"]));obj["rooms"].extend(_rooms(text))
        for field,pattern in (("ground_floor_area",r"Ground\s+F\.?\s*Area:\s*(\d+(?:\.\d+)?)"),("first_floor_area",r"First\s+F\.?\s*Area:\s*(\d+(?:\.\d+)?)"),("upper_floor_area",r"(?:Penthouse|Second)\s+F\.?\s*Area:\s*(\d+(?:\.\d+)?)"),("buildup_area",r"Buildup\s+Area:\s*(\d+(?:\.\d+)?)")):
            value=re.search(pattern,text,re.I)
            if value:obj[field]=float(value.group(1))
        if match:
            candidates=[float(x) for x in re.findall(r"(?m)^\s*(\d+(?:\.\d+)?)\s*(?:M2|m2)\s*$",text)]
            if candidates:obj["plot_area"]=max(candidates)
        obj["floors"].extend(x for x in ("ground floor","first floor","second floor","penthouse","basement") if x in text.casefold() and x not in obj["floors"]);obj["floor_count"]=len(obj["floors"]);names=[x["name"].casefold() for x in obj["rooms"]];obj["special_spaces"]=sorted(set(x for x in ("pool","garden","parking","gym","sauna","turkish bath","cinema","maid room","dressing","balcony","kitchen","reception") if any(x in name or (x=="pool" and "swimming pool" in name) for name in names)))
    return list(found.values())
def _unit_types(pages:list[dict[str,Any]])->list[dict[str,Any]]:
    """Extract reusable property/unit records while retaining legacy villa detail."""
    villas=_villa_types(pages);result=[]
    for item in villas:result.append({**item,"source_name":item["label"],"category":"villa","related_plans":[],"related_images":[]})
    seen={(x["category"],x["source_name"].casefold()) for x in result}
    categories=(("apartment",r"\b([1-9])\s*(?:BR|bed(?:room)?s?)\b"),("penthouse",r"\b(penthouse)\b"),("duplex",r"\b(duplex)\b"),("townhouse",r"\b(townhouse)\b"),("office",r"\b(office(?:\s+unit)?)\b"),("commercial",r"\b(commercial(?:\s+unit)?)\b"),("retail",r"\b(retail(?:\s+unit)?)\b"),("plot",r"\b(plot)\b"),("hospitality",r"\b(hotel suite|hotel room|hospitality unit)\b"))
    for page in pages:
        text=page["raw_text"]
        for category,pattern in categories:
            for match in re.finditer(pattern,text,re.I):
                source_name=f"{match.group(1)}BR" if category=="apartment" else match.group(0).strip().title();key=(category,source_name.casefold())
                if key in seen:continue
                seen.add(key);related=[x for x in page["images"] if x["image_type"] in {"floor_plan","unit_plan","technical_drawing","villa_exterior","villa_interior","apartment_exterior","apartment_interior","office_exterior","office_interior","commercial_interior"}]
                result.append({"type":source_name,"label":source_name,"source_name":source_name,"category":category,"plot_area":None,"ground_floor_area":None,"first_floor_area":None,"upper_floor_area":None,"buildup_area":None,"floor_count":len(set(filter(None,(_floor(text),)))),"areas":_areas(text),"floors":list(filter(None,(_floor(text),))),"rooms":_rooms(text),"special_spaces":[],"technical_data":[x for x in page["technical_data"]],"related_plans":[x["asset_id"] for x in related if x["image_type"] in {"floor_plan","unit_plan","technical_drawing"}],"related_images":[x["asset_id"] for x in related],"source_pages":[{"document":page["document"],"page":page["page_number"]}]})
    return result
def _category_items(pages:list[dict[str,Any]],category:str)->list[dict[str,Any]]:
    out=[]
    for page in pages:
        if category[:-1] not in page["section"] and category not in page["section"]:continue
        for bullet in page["bullet_lists"]:out.append({"name":re.sub(r"^(?:[•\-–]|â€¢|â€“)\s*","",bullet),"confidence":.95,"sources":[{"document":page["document"],"page":page["page_number"]}]})
    return _dedupe(out,"name")
def _dedupe(items:list[dict[str,Any]],field:str)->list[dict[str,Any]]:
    seen={}
    for item in items:
        key=str(item.get(field)).casefold();existing=seen.setdefault(key,item)
        if existing is not item:existing.setdefault("sources",[]).extend(item.get("sources",[]))
    return list(seen.values())
def _identity(facts:list[dict[str,Any]])->dict[str,Any]:return {"facts":[x for x in facts if re.search(r"project|development|residential|commercial|mixed.use|community",x["value"],re.I)]}
def _coverage(payload:dict[str,Any],pages:list[dict[str,Any]],errors:list[dict[str,Any]])->dict[str,Any]:
    visuals=payload["source_visuals"];return {"project":payload["project"],"knowledge_status":payload["knowledge_status"],"knowledge_completeness_score":payload["knowledge_completeness_score"],"pages_total":len(pages),"pages_analyzed":sum(bool(p["text_extraction_status"]!="failed" or p["images"]) for p in pages),"text_blocks_extracted":sum(len(p["text_blocks"]) for p in pages),"images_discovered":len(visuals),"visuals_discovered":len(visuals),"images_semantically_classified":sum(x["image_type"]!="unknown" for x in visuals),"visuals_classified":sum(x["image_type"]!="unknown" for x in visuals),"sections_identified":len(payload["source_sections"]),"facts_extracted":len(payload["canonical_facts"]),"amenities_extracted":len(payload["amenities"]),"features_extracted":len(payload["features"]),"villa_types_extracted":len(payload["villa_types"]),"floor_plans_extracted":sum(x["image_type"] in {"floor_plan","unit_plan"} for x in visuals),"plans_extracted":sum(x["image_type"] in {"floor_plan","unit_plan","technical_drawing"} for x in visuals),"logos_wordmarks_extracted":sum(x["image_type"] in {"project_logo","project_wordmark","developer_logo","developer_wordmark"} for x in visuals),"project_brand_assets_found":sum(x["image_type"] in {"project_logo","project_wordmark"} for x in visuals),"developer_brand_assets_found":sum(x["image_type"] in {"developer_logo","developer_wordmark"} for x in visuals),"contact_details_found":len(payload["contact_information"]),"unresolved_page_count":len(payload["unresolved_pages"]),"unresolved_pages":payload["unresolved_pages"],"extraction_errors":errors,"api_calls":payload["api_calls"]}
def _summary(p:dict[str,Any])->str:return "\n".join([f"# Source-Grounded Project Knowledge: {p['project']}","",f"Status: **{p['knowledge_status']}**",f"Completeness score: **{p['knowledge_completeness_score']}**",f"Sections: {', '.join(p['source_sections'])}",f"Property/unit types: {len(p['unit_types'])}",f"Features: {len(p['features'])}",f"Amenities: {len(p['amenities'])}",f"Plans/layouts: {len(p['plans_and_layouts'])}",f"Contacts: {len(p['contact_information'])}",f"Unresolved pages: {len(p['unresolved_pages'])}","","This is a source-grounded extraction summary, not marketing copy.",""])
def _coverage_md(c:dict[str,Any])->str:return "\n".join(["# Source Coverage Report",""]+[f"- {k.replace('_',' ').title()}: {v}" for k,v in c.items() if not isinstance(v,(list,dict))]+[""])
def _page_audit(pages:list[dict[str,Any]])->str:
    lines=["# Page-by-Page Source Audit",""]
    for p in pages:lines += [f"## PAGE {p['page_number']}",f"- Document: {p['document']}",f"- Section: {p['section']}",f"- Text extraction: {p['text_extraction_status'].upper()}",f"- Text blocks: {len(p['text_blocks'])}",f"- Visuals found: {len(p['images'])}",f"- Facts: {len(p['facts'])}",f"- Technical data: {len(p['technical_data'])}",f"- Plans: {len(p['plans'])}",f"- Brand assets: {len(p['logos'])}",f"- Needs manual review: {'YES' if p['needs_manual_review'] else 'NO'}",f"- Unresolved: {', '.join(p['unresolved']) or '0'}",""]
    return "\n".join(lines)
def _read(path:Path)->dict[str,Any]:
    try:return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):return {}
def _slug(value:str)->str:return re.sub(r"[^\w.-]+","-",value,flags=re.UNICODE).strip("-.") or "project"
def _sha(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()
