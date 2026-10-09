"""Deterministic source-corpus coverage and bounded knowledge recovery."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib,json,re
from pathlib import Path
from typing import Any

TAXONOMY=("identity","developer","location","project_scale","unit","plan","amenity","commercial","investment","architecture_interior","lifestyle","services","technical")
GAP_STATES={"NOT_IN_SOURCE","PRESENT_BUT_NOT_EXTRACTED","EXTRACTED_BUT_NOT_FUSED","CONFLICTED","AMBIGUOUS_RELATIONSHIP","UNREADABLE_SOURCE"}
_MARKETING=re.compile(r"\b(?:extraordinary|finest|exclusive|prestigious|luxury lifestyle|world.class|perfect|dream)\b",re.I)
_PATTERNS={
 "location":re.compile(r"(?:\b(?:located (?:on|in)|near|minutes? from|km from|airport|district|neighbou?rhood|mall|hospital|school|park)\b|\b(?:on|along)\s+[\w -]+\s(?:road|street)\b|قريب|مطار|طريق|شارع|بالقرب)",re.I),
 "commercial":re.compile(r"\b(?:price|USD|IQD|starting from|down payment|installment|payment plan|reservation|service charge|handover|completion|discount|availability)\b",re.I),
 "unit":re.compile(r"\b(?:type\s+[A-Z0-9-]+|\d+\s*(?:bedrooms?|BR)|\d+(?:\.\d+)?\s*(?:m²|m2|sqm)|apartment|villa|townhouse|office|retail|penthouse|duplex)\b",re.I),
 "amenity":re.compile(r"\b(?:pool|gym|spa|playground|garden|clubhouse|restaurant|café|cafe|nursery|security|concierge|walking|cycling|parking|EV charging)\b",re.I),
 "technical":re.compile(r"\b(?:HVAC|insulation|glazing|electrical|plumbing|fire safety|elevator|generator|solar|sustainability|construction system)\b",re.I),
 "architecture_interior":re.compile(r"\b(?:façade|facade|architecture|flooring|kitchen|cabinetry|bathroom|fixture|appliance|ceiling|window|material|finish)\b",re.I),
 "services":re.compile(r"\b(?:maintenance|property management|reception|cleaning|facility management|access control|utilities|internet|waste management)\b",re.I),
 "investment":re.compile(r"\b(?:ROI|rental yield|appreciation|occupancy|residency|visa|investment)\b",re.I),
 "developer":re.compile(r"\b(?:developer|developed by|architect|contractor|consultant|operator|managed by)\b",re.I),
 "project_scale":re.compile(r"\b(?:land area|built.up area|\d+\s+(?:buildings|towers|villas|blocks|floors|units|phases|plots)|green area|open space)\b",re.I),
 "identity":re.compile(r"\b(?:project|development|residential|commercial|mixed.use|community)\b",re.I),
 "plan":re.compile(r"\b(?:unit layout|floor plan|master plan|masterplan|site plan|technical plan)\b",re.I),
}

@dataclass(frozen=True)
class CorpusBlock:
    document:str;document_type:str;page:int|None;section:str|None;block:str;line:int|None;text:str;language:str;method:str

def recover_project(knowledge_path:Path,data:dict[str,Any], *, max_passes:int=0)->dict[str,Any]:
    """Audit source coverage without mutating or side-loading canonical knowledge.

    Recovery in this module means *candidate discovery only*. Candidates must be
    sent back through the normal typed extraction/validation/conflict/fusion
    pipeline before they can become canonical or VERIFIED knowledge.
    """
    root=_root(knowledge_path)
    project=str(data.get("project",{}).get("name") or knowledge_path.stem)
    blocks,unreadable,manifest=_corpus(root,project,knowledge_path)
    facts=_facts(blocks,project)
    structured=_structured_values(data)

    captured=[]
    missing=[]
    for fact in facts:
        if _fact_represented(fact,structured):
            captured.append(fact)
        else:
            missing.append(fact)

    requests=[]
    for fact in missing:
        priority="HIGH" if fact["category"] in {"commercial","unit","plan","identity"} else "MEDIUM"
        relationship=fact.get("relationship_status")
        status="REVIEW_REQUIRED" if relationship in {"AMBIGUOUS","CONFLICTED"} else "CANDIDATE"
        requests.append({
            "recovery_id":_id("recovery",fact["fact_id"]),
            "recovery_type":fact["category"]+"_source_fact",
            "source_document":fact["provenance"]["original_filename"],
            "page":fact["provenance"].get("page"),
            "reason":f"Source-supported {fact['category']} evidence is not represented in canonical fused knowledge.",
            "priority":priority,
            "status":status,
            "candidate_fact_id":fact["fact_id"],
            "requires_authoritative_pipeline":True,
        })

    # IMPORTANT: evaluator/source-recovery never declares facts recovered.
    recovered=[]

    by_page={}
    for block in blocks:
        key=f"{block.document}:{block.page or 0}"
        by_page.setdefault(key,{
            "source_document":block.document,"page":block.page,"categories":set(),
            "useful_facts":0,"structured_facts":0,
            "status":"NO_MEANINGFUL_FACTUAL_KNOWLEDGE"
        })
    captured_ids={x["fact_id"] for x in captured}
    for fact in facts:
        key=f"{fact['provenance']['original_filename']}:{fact['provenance'].get('page') or 0}"
        row=by_page.setdefault(key,{
            "source_document":fact["provenance"]["original_filename"],"page":fact["provenance"].get("page"),
            "categories":set(),"useful_facts":0,"structured_facts":0,
            "status":"PRESENT_BUT_NOT_EXTRACTED"
        })
        row["categories"].add(fact["category"])
        row["useful_facts"]+=1
        if fact["fact_id"] in captured_ids:
            row["structured_facts"]+=1
        row["status"]="CAPTURED" if row["useful_facts"] and row["structured_facts"]==row["useful_facts"] else "PRESENT_BUT_NOT_EXTRACTED"
    page_coverage=[{**row,"categories":sorted(row["categories"])} for row in by_page.values()]

    category_counts={name:sum(x["category"]==name for x in facts) for name in TAXONOMY}
    applicable={name for name,count in category_counts.items() if count}
    category_scores={}
    for name,count in category_counts.items():
        if not count:
            category_scores[name]=None
            continue
        represented=sum(x["category"]==name and x["fact_id"] in captured_ids for x in facts)
        category_scores[name]=round(100*represented/count,1)

    ambiguous=sum(x.get("relationship_status")=="AMBIGUOUS" for x in missing)
    conflicted=sum(x.get("relationship_status")=="CONFLICTED" for x in missing)

    unique_facts={}
    for fact in facts:
        unique_facts.setdefault((fact["category"],_norm(fact["value"])),fact)
    unique_captured={
        (fact["category"],_norm(fact["value"]))
        for fact in captured
    }
    unique_useful=len(unique_facts)
    utilized=len(unique_captured)

    completeness=(
        round(sum(category_scores[x] for x in applicable)/len(applicable),1)
        if applicable else 100.0
    )
    utilization=(
        round(100*utilized/unique_useful,1)
        if unique_useful else 100.0
    )

    return {
        "schema_version":"2.0.0",
        "project_id":project,
        "authority":"manifest-authorized-original-sources-only",
        "source_manifest":manifest,
        "recovery_policy":{
            "maximum_passes":max_passes,
            "passes_executed":0,
            "bounded":True,
            "internet_calls":0,
            "mode":"candidate_discovery_only",
            "canonical_write_allowed":False,
        },
        "atomic_facts":facts,
        "recovered_atomic_facts":recovered,
        "recovery_requests":requests,
        "page_coverage":page_coverage,
        "category_counts":category_counts,
        "category_scores":category_scores,
        "applicable_categories":sorted(applicable),
        "source_utilization_score":utilization,
        "project_completeness_score":completeness,
        "information_density":{
            "useful_source_facts_discovered":len(facts),
            "unique_useful_source_facts":unique_useful,
            "facts_structured_before_recovery":len(captured),
            "facts_fused":len(captured),
            "facts_rejected":0,
            "facts_conflicted":conflicted,
            "facts_requiring_review":ambiguous,
            "facts_recovered_by_evaluator":0,
            "recovery_candidates":sum(x["status"]=="CANDIDATE" for x in requests),
        },
        "missing_knowledge":{
            "PRESENT_BUT_NOT_EXTRACTED":sum(x["status"]=="CANDIDATE" for x in requests),
            "NOT_IN_SOURCE":sum(category_counts[x]==0 for x in TAXONOMY),
            "EXTRACTED_BUT_NOT_FUSED":0,
            "CONFLICTED":conflicted,
            "AMBIGUOUS_RELATIONSHIP":ambiguous,
            "UNREADABLE_SOURCE":len(unreadable),
        },
        "unreadable_sources":unreadable,
        "created_at":datetime.now(timezone.utc).isoformat(),
    }

def _manifest_path(root:Path,project:str)->Path:
    return root/"output"/"manifests"/f"{project}-run-manifest.json"

def _corpus(root:Path,project:str,knowledge_path:Path)->tuple[list[CorpusBlock],list[dict[str,Any]],dict[str,Any]]:
    """Load only original source files explicitly authorized by the run manifest."""
    manifest_path=_manifest_path(root,project)
    if not manifest_path.is_file():
        return [],[{
            "source_document":manifest_path.name,
            "classification":"SOURCE_MANIFEST_MISSING",
            "error":"Coverage/recovery audit requires the explicit project run manifest."
        }],{
            "path":str(manifest_path),
            "status":"MISSING",
            "authorized_sources":[],
        }

    try:
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as error:
        return [],[{
            "source_document":manifest_path.name,
            "classification":"SOURCE_MANIFEST_UNREADABLE",
            "error":str(error),
        }],{
            "path":str(manifest_path),
            "status":"UNREADABLE",
            "authorized_sources":[],
        }

    if str(manifest.get("project_id") or "") != project:
        return [],[{
            "source_document":manifest_path.name,
            "classification":"SOURCE_MANIFEST_PROJECT_MISMATCH",
            "error":f"Manifest project_id {manifest.get('project_id')!r} does not match {project!r}.",
        }],{
            "path":str(manifest_path),
            "status":"PROJECT_MISMATCH",
            "authorized_sources":[],
        }

    source_hashes=manifest.get("source_file_hashes") or {}
    if not isinstance(source_hashes,dict):
        source_hashes={}

    authorized=[]
    unreadable=[]
    blocks=[]
    seen_paths=set()

    for raw_path,expected_hash in sorted(source_hashes.items()):
        path=_resolve_manifest_source(root,raw_path)
        record={
            "manifest_path":str(raw_path),
            "resolved_path":str(path) if path else None,
            "expected_sha256":str(expected_hash or ""),
        }
        if path is None or not path.is_file():
            record["status"]="MISSING"
            authorized.append(record)
            unreadable.append({
                "source_document":Path(str(raw_path)).name,
                "classification":"MANIFEST_SOURCE_MISSING",
                "error":"Manifest-authorized source file is not present.",
            })
            continue
        resolved=path.resolve()
        project_folder=(root/"input"/project).resolve()
        input_folder=(root/"input").resolve()
        owned=resolved.is_relative_to(project_folder) if project_folder.is_dir() else resolved.parent==input_folder
        if not owned:
            record["status"]="PROJECT_SOURCE_SCOPE_MISMATCH"
            authorized.append(record)
            unreadable.append({"source_document":path.name,"classification":"PROJECT_SOURCE_SCOPE_MISMATCH","error":"Manifest source is outside the exact project input boundary."})
            continue
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        actual_hash=_sha256_file(path)
        record["actual_sha256"]=actual_hash
        if expected_hash and actual_hash.casefold()!=str(expected_hash).casefold():
            record["status"]="HASH_MISMATCH"
            authorized.append(record)
            unreadable.append({
                "source_document":path.name,
                "classification":"MANIFEST_SOURCE_HASH_MISMATCH",
                "error":"Source hash does not match the project run manifest.",
            })
            continue
        record["status"]="AUTHORIZED"
        authorized.append(record)
        try:
            blocks.extend(_read_authorized_source(path))
        except Exception as error:
            unreadable.append({
                "source_document":path.name,
                "classification":"UNREADABLE_SOURCE",
                "error":str(error),
            })

    return blocks,unreadable,{
        "path":str(manifest_path),
        "status":"LOADED",
        "authorized_sources":authorized,
    }

def _resolve_manifest_source(root:Path,raw_path:str)->Path|None:
    value=str(raw_path).replace("\\","/")
    candidate=Path(value)
    if candidate.is_file():
        return candidate
    marker="/input/"
    folded=value.casefold()
    index=folded.find(marker)
    if index>=0:
        relative=value[index+1:]
        local=root/Path(relative)
        if local.is_file():
            return local
    # Manifest paths may be root-relative on non-Windows systems.
    local=root/Path(value)
    return local if local.is_file() else None

def _read_authorized_source(path:Path)->list[CorpusBlock]:
    suffix=path.suffix.casefold()
    if suffix==".pdf":
        from pypdf import PdfReader
        out=[]
        for page_no,page in enumerate(PdfReader(str(path)).pages,1):
            out.extend(_text_blocks(path.name,"pdf",page.extract_text() or "",page_no,"pdf_text"))
        return out
    if suffix==".docx":
        from docx import Document
        document=Document(path)
        return _text_blocks(path.name,"docx","\n".join(x.text for x in document.paragraphs),None,"docx_paragraph")
    if suffix in {".md",".txt"}:
        return _text_blocks(path.name,suffix[1:],path.read_text(encoding="utf-8"),None,"markdown_block" if suffix==".md" else "text_line")
    if suffix==".json":
        value=json.loads(path.read_text(encoding="utf-8"))
        return _json_blocks(path.name,value)
    raise ValueError(f"Unsupported manifest source type: {suffix}")

def _sha256_file(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()

def _fact_represented(fact:dict[str,Any],structured:set[str])->bool:
    """Conservative canonical-coverage test.

    A source assertion is represented only when its normalized assertion exists
    in canonical structured values. This deliberately prefers under-counting to
    claiming completeness from a regex match.
    """
    normalized=_norm(str(fact.get("value") or ""))
    return bool(normalized and normalized in structured)

def _text_blocks(name:str,kind:str,text:str,page:int|None,method:str)->list[CorpusBlock]:
    out=[];section=None;lines=text.splitlines()
    if kind in {"md","txt"}:
        for index,line in enumerate(lines):
            if "|" not in line or index+2>=len(lines) or not re.search(r"\|?\s*:?-{3,}",lines[index+1]):continue
            headers=[x.strip().casefold() for x in line.strip(" |").split("|")]
            for offset,row in enumerate(lines[index+2:],index+3):
                if "|" not in row or not row.strip():break
                values=[x.strip() for x in row.strip(" |").split("|")]
                if len(values)!=len(headers):continue
                mapped=dict(zip(headers,values));unit=mapped.get("type") or mapped.get("unit type");area=mapped.get("area") or mapped.get("area sqm") or mapped.get("area_sqm");beds=mapped.get("bedrooms") or mapped.get("beds")
                if unit and area:
                    statement=f"Type {unit.removeprefix('Type ').strip()} {area} m2"+(f" {beds} bedrooms" if beds else "")
                    out.append(CorpusBlock(name,kind,page,section,f"table-row-{offset}",offset,statement,_language(statement),"markdown_table_row"))
    for line_no,line in enumerate(lines,1):
        value=re.sub(r"\s+"," ",line).strip(" |\t")
        if not value:continue
        if value.startswith("#"):section=value.lstrip("# ")
        out.append(CorpusBlock(name,kind,page,section,str(line_no),line_no,value,_language(value),method))
    return out
def _json_blocks(name:str,value:Any,page:int|None=None,path:str="")->list[CorpusBlock]:
    out=[]
    if isinstance(value,dict):
        page=int(value.get("page_number") or value.get("page") or page or 0) or None
        for key,item in value.items():out.extend(_json_blocks(name,item,page,f"{path}.{key}".strip(".")))
    elif isinstance(value,list):
        for i,item in enumerate(value):out.extend(_json_blocks(name,item,page,f"{path}[{i}]"))
    elif isinstance(value,(str,int,float)) and str(value).strip():out.append(CorpusBlock(name,"json",page,path,path,None,str(value),_language(str(value)),"structured_source"))
    return out
def _facts(blocks:list[CorpusBlock],project:str)->list[dict[str,Any]]:
    facts=[];seen=set()
    for block in blocks:
        text=block.text.strip()
        if len(text)<4 or len(text)>500 or text.casefold() in {"road","airport","project","villa","apartment"}:continue
        marketing=bool(_MARKETING.search(text));categories=[name for name,pattern in _PATTERNS.items() if pattern.search(text)]
        if marketing and not categories:categories=["lifestyle"]
        for category in categories[:2]:
            if len(re.findall(r"\w+",text,flags=re.UNICODE))<2 and category!="amenity":continue
            if "ï¿½" in text or len(re.findall(r"[ÙØÃ]",text))>3:continue
            key=(category,_norm(text),block.document,block.page,block.line)
            if key in seen:continue
            seen.add(key);fact_type="SOURCE_MARKETING_CLAIM" if marketing else "VERIFIED_FACT";relationship="AMBIGUOUS" if category in {"unit","plan"} and block.method!="markdown_table_row" and not re.search(r"type\s+[A-Z0-9-]+.*\d+(?:\.\d+)?\s*(?:m²|m2|sqm)",text,re.I) else "VERIFIED"
            facts.append({"fact_id":_id("source-fact",*map(str,key)),"project_id":project,"category":category,"fact_type":fact_type,"value":text,"normalized_value":_norm(text),"original_language":block.language,"relationship_status":relationship,"scores":{"factual_confidence":.95 if not marketing else .7,"source_authority":.9,"commercial_importance":.9 if category=="commercial" else .5,"buyer_relevance":.8 if category in {"commercial","unit","location","amenity"} else .5,"content_usefulness":.8,"specificity":.8,"freshness":.5,"relationship_confidence":.95 if relationship=="VERIFIED" else .4},"provenance":{"original_filename":block.document,"document_type":block.document_type,"page":block.page,"markdown_section":block.section,"block":block.block,"line":block.line,"table":block.block if block.method=="markdown_table_row" else None,"extraction_method":block.method,"source_text":text}})
    unit_groups={}
    for fact in facts:
        if fact["category"]!="unit":continue
        match=re.search(r"type\s+([A-Z0-9-]+).*?(\d+(?:\.\d+)?)\s*(?:m²|m2|sqm)",fact["value"],re.I)
        if match:unit_groups.setdefault(match.group(1).casefold(),{}).setdefault(match.group(2),[]).append(fact)
    for areas in unit_groups.values():
        if len(areas)>1:
            for group in areas.values():
                for fact in group:fact["relationship_status"]="CONFLICTED";fact["scores"]["relationship_confidence"]=0.0
    return facts
def _structured_values(value:Any)->set[str]:
    out=set()
    if isinstance(value,dict):
        for key,item in value.items():
            if key not in {"recovered_atomic_facts","source_recovery"}:out|=_structured_values(item)
    elif isinstance(value,list):
        for item in value:out|=_structured_values(item)
    elif isinstance(value,(str,int,float)) and str(value).strip():out.add(_norm(str(value)))
    return out
def _root(path:Path)->Path:
    for parent in path.resolve().parents:
        if parent.name=="output":return parent.parent
    return Path.cwd()
def _norm(value:str)->str:return re.sub(r"[^\w]+"," ",value.casefold(),flags=re.UNICODE).strip()
def _language(text:str)->str:
    if re.search(r"[\u0600-\u06ff]",text):return "ku" if re.search(r"[ەێۆڕڵ]",text) else "ar"
    return "en" if re.search(r"[A-Za-z]",text) else "unknown"
def _id(prefix:str,*values:str)->str:return prefix+"_"+hashlib.sha256("|".join(values).encode()).hexdigest()[:20]
