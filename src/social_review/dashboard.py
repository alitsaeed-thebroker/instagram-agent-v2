"""Read-only renderer for final social packages."""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import html
import json
from pathlib import Path
import re
from typing import Any

from PIL import Image

from src.knowledge.consumer import canonical_project_identity, require_canonical_graph
from src.execution.lineage import attach_lineage, artifact_fingerprint, canonical_graph_fingerprint, require_lineage

REVIEW_VERSION = "3.0.0"
DUPLICATE_DETECTION_VERSION = "2.1.0"
TECHNICAL_TYPES = {"floorplan", "masterplan", "site_plan", "technical_plan"}


class SocialContentReview:
    def __init__(self, project: str, root: Path) -> None:
        self.project, self.root = project, root
        self.output = root / "output"
        self.html_path = self.output / "social-review" / f"{project}-social-review.html"
        self.json_path = self.output / "social-review" / f"{project}-social-review.json"

    def render(self) -> tuple[Path, Path]:
        data = self._aggregate()
        data.update(social_review_version=REVIEW_VERSION,duplicate_detection_version=DUPLICATE_DETECTION_VERSION,duplicate_analysis=_duplicate_analysis(data.get("packages",[]))[1])
        lineage=dict(data.get("lineage") or {})
        data=attach_lineage(
            data,
            stage="social-review",
            canonical_fingerprint=str(lineage.get("canonical_department2_fingerprint") or ""),
            parents=dict(lineage.get("parent_artifact_fingerprints") or {}),
            inputs=dict(lineage.get("input_artifact_fingerprints") or {}),
        )
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self.json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.html_path.write_text(_html(data), encoding="utf-8")
        return self.html_path, self.json_path

    def _aggregate(self) -> dict[str, Any]:
        paths = {
            "packages": self.output / "post-packages" / f"{self.project}-post-packages.json",
            "package_qa": self.output / "qa" / f"{self.project}-post-package-qa.json",
            "branded_qa": self.output / "qa" / f"{self.project}-branded-image-qa.json",
            "creative_qa": self.output / "qa" / f"{self.project}-creative-visual-qa.json",
            "provenance": self.output / "provenance" / f"{self.project}-provenance-audit.json",
            "assets": self.output / "asset-intelligence" / f"{self.project}-asset-intelligence.json",
            "groups": self.output / "content-groups" / f"{self.project}-content-groups.json",
            "knowledge": self.output / "knowledge" / f"{self.project}.json",
        }
        missing = [str(path) for key, path in paths.items() if key not in {"groups"} and not path.is_file()]
        if missing: raise ValueError("Social review inputs missing: " + ", ".join(missing))
        raw = {key: _read(path) if path.is_file() else {} for key, path in paths.items()}
        require_canonical_graph(raw["knowledge"],expected_project=self.project)
        d2_fingerprint=canonical_graph_fingerprint(raw["knowledge"])
        require_lineage(raw["packages"],expected_stage="post-package-manifest",canonical_fingerprint=d2_fingerprint)
        require_lineage(raw["package_qa"],expected_stage="post-package-qa",canonical_fingerprint=d2_fingerprint,parents={"post_packages":str(raw["packages"].get("artifact_fingerprint") or artifact_fingerprint(raw["packages"]))})
        raw["d2_fingerprint"]=d2_fingerprint
        if raw["packages"].get("project_id") != self.project or raw["provenance"].get("project_id") != self.project:
            raise ValueError("Social review blocked: cross-project package or provenance input.")
        pq = {x.get("package_id"): x for x in raw["package_qa"].get("items", [])}
        bq = {x.get("branded_item_id"): x for x in raw["branded_qa"].get("items", [])}
        cq = {x.get("branded_item_id"): x for x in raw["creative_qa"].get("items", [])}
        provenance = {x.get("branded_item_id"): x for x in raw["provenance"].get("items", [])}
        assets = {x.get("asset_id"): x for x in raw["assets"].get("assets", [])}
        packages=[];semantic_warnings=[];duplicate_warnings=[];complete=0;slide_count=0;comparisons=0
        for package in raw["packages"].get("packages", []):
            review = _package_review(package, pq.get(package.get("package_id"), {}), bq, cq, provenance, assets, raw.get("knowledge", {}))
            packages.append(review);slide_count += len(review["slides"]);comparisons += sum(bool(x.get("source_image_uri")) for x in review["slides"]);complete += sum(x["provenance_complete"] for x in review["slides"])
            semantic_warnings.extend(review["semantic_warnings"]);duplicate_warnings.extend(review["duplication_warnings"])
        independent_warnings,duplicate_analysis=_duplicate_analysis(packages);duplicate_warnings.extend(independent_warnings)
        blocked=any(x["readiness"]=="BLOCKED" for x in packages);warned=bool(semantic_warnings or duplicate_warnings) or any(x["readiness"]=="READY WITH WARNINGS" for x in packages)
        overall="NO_PUBLISHABLE_CONTENT" if not packages else "BLOCKED" if blocked else "READY WITH WARNINGS" if warned else "READY FOR PUBLISHING LAYER"
        release_ids=list(dict.fromkeys(x.get("release_id") for x in packages if x.get("release_id")))
        return attach_lineage(
            {"review_version":REVIEW_VERSION,"project_id":self.project,"release_id":release_ids[0] if len(release_ids)==1 else release_ids,"generated_at":datetime.now(timezone.utc).isoformat(),"package_count":len(packages),"packages":packages,"slide_count":slide_count,"qa_summaries":raw["package_qa"].get("summary",{}),"semantic_warnings":semantic_warnings,"duplication_warnings":duplicate_warnings,"provenance_completeness":{"complete":complete,"total":slide_count},"source_comparisons_available":comparisons,"overall_readiness":overall},
            stage="social-review",
            canonical_fingerprint=raw["d2_fingerprint"],
            parents={
                "post_packages":str(raw["packages"].get("artifact_fingerprint") or artifact_fingerprint(raw["packages"])),
                "post_package_qa":str(raw["package_qa"].get("artifact_fingerprint") or artifact_fingerprint(raw["package_qa"])),
            },
        )


def _package_review(package:dict[str,Any],package_qa:dict[str,Any],bq:dict[str,Any],cq:dict[str,Any],provenance:dict[str,Any],assets:dict[str,Any],knowledge:dict[str,Any]|None=None)->dict[str,Any]:
    caption=package.get("master_caption") or package.get("caption") or {};source_slides=package.get("slides") or [_single_slide(package)];slides=[];semantic=[]
    for source in source_slides:
        identity=source.get("branded_item_id");asset_id=next(iter(source.get("source_asset_ids",[])),None);asset=assets.get(asset_id,{})
        image_path=Path(str(source.get("image_path", package.get("image",{}).get("image_path",""))));source_path=Path(str(asset.get("source_path",""))) if asset.get("source_path") else None
        width=height=0
        if image_path.is_file():
            with Image.open(image_path) as image:width,height=image.size
        asset_type=re.sub(r"[-\s]+","_",str(asset.get("asset_type") or caption.get("asset_types",[""])[min(len(slides),max(0,len(caption.get("asset_types",[]))-1))] or "unknown").casefold());asset_subtype=str(asset.get("asset_subtype") or "")
        warning=_semantic_warning(asset_type,asset_subtype,str(source.get("alt_text") or ""),identity)
        if warning:semantic.append(warning)
        trace=provenance.get(identity,{});expected_id=trace.get("provenance_id") or _stable("provenance",identity,trace.get("final_output_hash",""));provenance_complete=bool(trace and source.get("provenance_id")==expected_id and source.get("final_output_hash")==trace.get("final_output_hash"))
        slides.append({"slide_number":source.get("slide_number",1),"slide_role":source.get("slide_role","primary"),"branded_item_id":identity,"image_path":str(image_path),"image_uri":image_path.resolve().as_uri() if image_path.is_file() else "","image_hash":source.get("image_hash"),"width":width,"height":height,"aspect_ratio":f"{width}:{height}" if width and height else "unknown","asset_type":asset_type,"visual_category":asset.get("visual_category") or asset_type,"visual_category_confidence":asset.get("confidence"),"asset_subtype":asset_subtype,"technical_visual":asset_type in TECHNICAL_TYPES,"alt_text":source.get("alt_text"),"source_asset_ids":source.get("source_asset_ids",[]),"source_image_path":str(source_path) if source_path else None,"source_image_uri":source_path.resolve().as_uri() if source_path and source_path.is_file() else "","source_hash":asset.get("source_hash"),"source_document_refs":source.get("source_document_refs",[]),"source_pages":source.get("source_pages",[]),"provenance_id":source.get("provenance_id"),"final_output_hash":source.get("final_output_hash"),"release_id":source.get("release_id") or package.get("release_id"),"brand_config_hash":source.get("brand_config_hash") or package.get("brand_config_hash"),"verified_fact_refs":source.get("verified_fact_refs",[]),"provenance_complete":provenance_complete,"qa":{"branded":_qa_summary(bq.get(identity,{}),"Branded Image QA"),"creative":_qa_summary(cq.get(identity,{}),"Creative Visual QA")}})
    duplicates=_slide_duplicate_warnings(slides)
    grounding=package_qa.get("grounding") or {"status":"blocked","diagnostics":[{"claim_id":"unknown","claim_text_summary":"grounding contract missing","grounding_status":"blocked","expected_fact_category":None,"resolved_fact_ids":[],"missing_fact_ids":[],"reason":"missing_grounding_contract"}]}
    semantic.extend({"package_id":package.get("package_id"),"type":"factual_grounding",**x,"message":x["reason"]} for x in grounding.get("diagnostics",[]))
    status=str(package_qa.get("status") or "blocked");readiness="BLOCKED" if status=="blocked" or grounding.get("status")!="grounded" else "READY WITH WARNINGS" if status=="ready_with_warnings" or semantic or duplicates else "READY FOR PUBLISHING LAYER"
    identity=canonical_project_identity(knowledge,expected_project=str(package.get("project_id"))) if knowledge else {"project_name":str(package.get("project_id") or ""),"developer_name":""}
    return {"package_id":package.get("package_id"),"package_type":package.get("package_type"),"project_id":package.get("project_id"),"project_name":identity.get("project_name"),"developer_name":identity.get("developer_name") or None,"content_category":slides[0].get("visual_category") if slides else "unknown","key_facts_used":caption.get("selected_facts",[]),"source_grounding_status":"grounded" if caption.get("verified_fact_refs") else "visual_only","visual_category_confidence":min((x.get("visual_category_confidence") for x in slides if isinstance(x.get("visual_category_confidence"),(int,float))),default=None),"marketing_comprehension":package_qa.get("marketing_comprehension",{}),"release_id":package.get("release_id"),"platform":package.get("platform"),"destination":package.get("destination") or package.get("platform"),"variant_id":package.get("variant_id"),"master_concept_id":package.get("master_concept_id") or package.get("campaign_id"),"language":package.get("language"),"language_code":package.get("language_code"),"campaign_id":package.get("campaign_id"),"content_idea_id":package.get("content_idea_id"),"content_group_id":package.get("content_group_id"),"content_group":{"type":package.get("package_type"),"slide_count":len(slides),"master_caption":"shared" if package.get("package_type")=="carousel" else "per-post","alt_text":"per-slide","hashtags":"shared"},"caption":caption,"hashtags":package.get("hashtags",[]),"slides":slides,"qa":{"post_package":_qa_summary(package_qa,"Post Package QA")},"semantic_warnings":semantic,"duplication_warnings":duplicates,"readiness":readiness}


def _single_slide(package:dict[str,Any])->dict[str,Any]:
    image=package.get("image",{});return {**image,"slide_number":1,"slide_role":"primary","branded_item_id":package.get("branded_item_id"),"alt_text":package.get("alt_text"),**{key:package.get(key) for key in ("provenance_id","final_output_hash","source_asset_ids","source_document_refs","source_pages","verified_fact_refs","brand_config_hash","release_id")}}
def _qa_summary(value:dict[str,Any],label:str)->dict[str,Any]:
    raw=str(value.get("status") or value.get("fidelity_class") or "unavailable");names={"exceptional":"Exceptional","production_ready":"Production Ready","ready":"Production Ready","good_minor_improvements":"Ready With Warnings","ready_with_warnings":"Ready With Warnings","blocked":"Blocked"};return {"label":label,"status":names.get(raw,raw.replace("_"," ").title()),"score":value.get("score",value.get("qa_score"))}
def _semantic_warning(asset_type:str,subtype:str,alt:str,identity:str)->dict[str,Any]|None:
    text=(subtype+" "+alt).casefold();described="masterplan" if "masterplan" in text else "site_plan" if "site plan" in text else "floorplan" if "floorplan" in text else None
    if asset_type in TECHNICAL_TYPES and described and described!=asset_type:return {"branded_item_id":identity,"type":"semantic_classification","message":f"Metadata classifies this as {asset_type}, while its description suggests {described}."}
    return None
def _slide_duplicate_warnings(slides:list[dict[str,Any]])->list[dict[str,Any]]:
    warnings=[]
    for field,label in (("image_hash","identical image hash"),("source_asset_ids","same source asset"),("alt_text","duplicate alt text")):
        seen={}
        for slide in slides:
            value=tuple(slide[field]) if isinstance(slide.get(field),list) else str(slide.get(field) or "").casefold()
            if value and value in seen:warnings.append({"type":"visual_duplication","slides":[seen[value],slide["slide_number"]],"message":label})
            elif value:seen[value]=slide["slide_number"]
    return warnings
def _independent_caption_warnings(packages:list[dict[str,Any]])->list[dict[str,Any]]:
    return _duplicate_analysis(packages)[0]
def _duplicate_analysis(packages:list[dict[str,Any]])->tuple[list[dict[str,Any]],dict[str,Any]]:
    warnings=[];relationships=[]
    singles=[x for x in packages if x["package_type"]!="carousel"]
    for index,item in enumerate(singles):
        text=_normalize(item.get("caption",{}).get("full_caption",""))
        for prior in singles[:index]:
            similarity=SequenceMatcher(None,text,_normalize(prior.get("caption",{}).get("full_caption",""))).ratio() if text else 0
            if similarity<=.8:continue
            same_master=bool(item.get("master_concept_id")) and item.get("master_concept_id")==prior.get("master_concept_id");same_idea=bool(item.get("content_idea_id")) and item.get("content_idea_id")==prior.get("content_idea_id");different_platform=str(item.get("destination")).casefold()!=str(prior.get("destination")).casefold();assets_a={a for slide in prior.get("slides",[]) for a in slide.get("source_asset_ids",[])};assets_b={a for slide in item.get("slides",[]) for a in slide.get("source_asset_ids",[])};shared_assets=bool(assets_a&assets_b)
            if same_master and different_platform:classification="intentional_cross_platform_variant"
            elif same_master and not different_platform:classification="same_platform_variant_collision"
            elif item.get("content_idea_id") and prior.get("content_idea_id") and assets_a and assets_b and not same_idea and not shared_assets:classification="semantic_similarity_only"
            else:classification="true_unintended_duplicate"
            record={"classification":classification,"item_a":prior["package_id"],"item_b":item["package_id"],"platform_a":prior.get("platform"),"platform_b":item.get("platform"),"master_concept_id_a":prior.get("master_concept_id"),"master_concept_id_b":item.get("master_concept_id"),"content_idea_id_a":prior.get("content_idea_id"),"content_idea_id_b":item.get("content_idea_id"),"asset_ids_a":sorted(assets_a),"asset_ids_b":sorted(assets_b),"package_type_a":prior.get("package_type"),"package_type_b":item.get("package_type"),"caption_similarity":round(similarity,4),"reason":"Caption wording is similar; classification also considers platform, master concept, content idea, package type, and source assets."}
            relationships.append(record)
            if classification in {"true_unintended_duplicate","same_platform_variant_collision"}:warnings.append({"warning_type":classification,"item_a":prior["package_id"],"item_b":item["package_id"],"reason":record["reason"],"intentional_variant":False,"type":"content_duplication","package_ids":[prior["package_id"],item["package_id"]],"message":"Genuine duplicate package relationship detected."})
    counts={name:sum(x["classification"]==name for x in relationships) for name in ("true_unintended_duplicate","same_platform_variant_collision","intentional_cross_platform_variant","intentional_carousel_relationship","semantic_similarity_only")}
    return warnings,{"records":relationships,"counts":counts,"genuine_warnings":counts["true_unintended_duplicate"]+counts["same_platform_variant_collision"]}
def _stable(prefix:str,*values:Any)->str:return prefix+"_"+hashlib.sha256("|".join(str(x) for x in values).encode()).hexdigest()[:20]
def _normalize(value:str)->str:return re.sub(r"\s+"," ",re.sub(r"[^\w\s]"," ",value.casefold())).strip()
def _read(path:Path)->dict[str,Any]:return json.loads(path.read_text(encoding="utf-8"))


def _html(data:dict[str,Any])->str:
    payload=json.dumps(data,ensure_ascii=False).replace("</","<\\/")
    title=html.escape(str(data["project_id"]));readiness=html.escape(data["overall_readiness"])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Social Content Review</title><style>
:root{{--ink:#17212b;--muted:#66717d;--line:#dce2e8;--paper:#fff;--ground:#f3f5f7;--accent:#255b4b;--warn:#946200;--bad:#a22}}*{{box-sizing:border-box}}body{{margin:0;background:var(--ground);color:var(--ink);font:14px/1.5 system-ui,"Segoe UI",sans-serif}}header{{background:#14251f;color:#fff;padding:22px 28px;display:flex;justify-content:space-between;gap:20px;align-items:center}}h1{{font-size:21px;margin:0}}.sub{{opacity:.74}}.ready{{padding:8px 12px;border:1px solid #88a89c;border-radius:999px;font-size:12px;font-weight:700}}main{{max-width:1440px;margin:auto;padding:24px}}.toolbar,.card{{background:var(--paper);border:1px solid var(--line);border-radius:12px;box-shadow:0 4px 16px #15202b0a}}.toolbar{{padding:12px 16px;display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}}button{{border:1px solid #bcc6cf;background:#fff;border-radius:7px;padding:7px 11px;cursor:pointer}}button:hover{{background:#eef3f1}}.grid{{display:grid;grid-template-columns:minmax(430px,1.2fr) minmax(330px,.8fr);gap:18px}}.card{{padding:17px;margin-bottom:16px}}.viewer{{min-height:690px}}.image-stage{{height:575px;background:#e8ecef;display:flex;align-items:center;justify-content:center;overflow:auto;border-radius:8px}}.image-stage img{{display:block;max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;transform-origin:center}}.compare{{display:grid;grid-template-columns:1fr 1fr;gap:8px;height:575px}}.compare .image-stage{{height:575px}}.compare-label{{position:absolute;background:#17212bdd;color:white;padding:3px 7px;border-radius:4px;margin:8px}}.slidebar,.zoom,.modes{{display:flex;gap:8px;align-items:center;justify-content:center;margin-top:12px;flex-wrap:wrap}}.dot{{width:10px;height:10px;border-radius:50%;padding:0;background:#ccd3d9}}.dot.active{{background:var(--accent)}}h2{{font-size:16px;margin:0 0 12px}}.caption{{white-space:pre-wrap;font-size:15px}}.tags{{display:flex;flex-wrap:wrap;gap:7px}}.tag,.badge{{background:#eaf1ee;color:#194b3b;padding:4px 8px;border-radius:6px}}.badge.tech{{background:#fff1cf;color:#754d00;font-weight:700}}.meta{{display:grid;grid-template-columns:140px 1fr;gap:6px 10px}}.meta dt{{color:var(--muted)}}.meta dd{{margin:0;word-break:break-word}}details summary{{cursor:pointer;font-weight:650}}.qa{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}.qa div{{border:1px solid var(--line);padding:9px;border-radius:7px}}.warning{{border-left:3px solid #d39624;padding:7px 10px;background:#fff8e8;margin:6px 0}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}.image-stage,.compare,.compare .image-stage{{height:460px}}}}@media(max-width:560px){{header{{align-items:flex-start;flex-direction:column}}main{{padding:12px}}.compare{{grid-template-columns:1fr;height:auto}}.qa{{grid-template-columns:1fr}}}}
</style></head><body><header><div><h1>{title}</h1><div class="sub">Offline Social Content Review · Release <span id="release"></span></div></div><div class="ready" id="overall">{readiness}</div></header>
<main><div class="toolbar"><button id="prevPackage">← Previous package</button><strong id="packagePosition"></strong><button id="nextPackage">Next package →</button></div><div class="grid"><section><div class="card viewer"><div id="packageHeader"></div><div id="visual"></div><div class="slidebar"><button id="prevSlide">← Previous</button><span id="slidePosition"></span><span id="indicators"></span><button id="nextSlide">Next →</button></div><div class="modes"><button data-mode="final">Final branded</button><button data-mode="source">Source asset</button><button data-mode="compare">Side by side</button></div><div class="zoom">Zoom <button data-zoom="1">100%</button><button data-zoom="1.5">150%</button><button data-zoom="2">200%</button></div></div><div class="card"><h2>Active slide alt text</h2><p id="alt"></p></div><div class="card"><details><summary>Image metadata</summary><dl class="meta" id="metadata"></dl></details></div></section><aside><div class="card"><h2>Caption</h2><div class="caption" id="caption"></div><div class="sub" id="captionMeta"></div></div><div class="card"><h2>Hashtags</h2><div class="tags" id="hashtags"></div><br><button id="copyTags">Copy Hashtags</button></div><div class="card"><h2>Quality assurance</h2><div class="qa" id="qa"></div></div><div class="card"><h2>Diagnostics</h2><div id="warnings"></div></div><div class="card"><details><summary>Source &amp; Provenance</summary><dl class="meta" id="provenance"></dl></details></div></aside></div></main>
<script>const DATA={payload};let pi=0,si=0,mode='final',zoom=1;const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));function rows(o){{return Object.entries(o).map(([k,v])=>`<dt>${{esc(k.replaceAll('_',' '))}}</dt><dd>${{esc(Array.isArray(v)?v.join(', '):v)}}</dd>`).join('')}}function packageNow(){{return DATA.packages[pi]}}function slideNow(){{return packageNow().slides[si]}}function renderVisual(){{let s=slideNow(),final=`<div class="image-stage"><span class="compare-label">FINAL BRANDED</span><img src="${{esc(s.image_uri)}}" alt="${{esc(s.alt_text)}}" style="transform:scale(${{zoom}})"></div>`,source=s.source_image_uri?`<div class="image-stage"><span class="compare-label">SOURCE ASSET</span><img src="${{esc(s.source_image_uri)}}" alt="Original source visual" style="transform:scale(${{zoom}})"></div>`:`<div class="image-stage"><p>Source comparison unavailable</p></div>`;$('visual').innerHTML=mode==='compare'?`<div class="compare">${{final}}${{source}}</div>`:mode==='source'?source:final}}function render(){{let p=packageNow(),s=slideNow();$('release').textContent=p.release_id;$('packagePosition').textContent=`Package ${{pi+1}} of ${{DATA.packages.length}}`;$('packageHeader').innerHTML=`<h2>${{esc(p.package_type.replaceAll('_',' ').toUpperCase())}} · ${{esc(p.platform)}} · ${{esc(p.language)}}</h2><p class="sub">Content Group: ${{esc(p.content_group_id)}} · ${{p.slides.length}} slides · Master caption: ${{esc(p.content_group.master_caption)}} · Alt text: per-slide · Hashtags: shared</p>${{s.technical_visual?'<span class="badge tech">TECHNICAL VISUAL — DETAIL PRESERVATION REQUIRED</span>':''}}`;renderVisual();$('slidePosition').textContent=`Slide ${{si+1}} of ${{p.slides.length}}`;$('indicators').innerHTML=p.slides.map((_,i)=>`<button class="dot ${{i===si?'active':''}}" data-slide="${{i}}" aria-label="Slide ${{i+1}}"></button>`).join('');$('alt').textContent=s.alt_text;$('metadata').innerHTML=rows({{slide_number:s.slide_number,slide_role:s.slide_role,dimensions:`${{s.width}} × ${{s.height}}`,aspect_ratio:s.aspect_ratio,branded_item_id:s.branded_item_id,image_hash:s.image_hash,source_asset_id:s.source_asset_ids,source_page:s.source_pages}});let c=p.caption;$('caption').textContent=c.full_caption||[c.headline,c.body,c.CTA].filter(Boolean).join('\n\n');$('captionMeta').textContent=`${{c.character_count??''}} characters · ${{c.word_count??''}} words · ${{p.language}}`;$('hashtags').innerHTML=p.hashtags.map(x=>`<span class="tag">${{esc(x.hashtag)}}</span>`).join('');let q=[s.qa.branded,s.qa.creative,p.qa.post_package];$('qa').innerHTML=q.map(x=>`<div><strong>${{esc(x.label)}}</strong><br>${{esc(x.status)}}${{x.score!=null?` · ${{x.score}}/100`:''}}</div>`).join('');let ws=[...p.semantic_warnings,...p.duplication_warnings];$('warnings').innerHTML=ws.length?ws.map(x=>`<div class="warning"><strong>${{esc(x.type.replaceAll('_',' '))}}</strong><br>${{esc(x.message)}}</div>`).join(''):'<span class="sub">No diagnostic warnings.</span>';$('provenance').innerHTML=rows({{provenance_id:s.provenance_id,source_document:s.source_document_refs,source_page:s.source_pages,source_asset_id:s.source_asset_ids,source_hash:s.source_hash,final_output_hash:s.final_output_hash,release_id:s.release_id,brand_config_hash:s.brand_config_hash,verified_fact_refs:s.verified_fact_refs,complete:s.provenance_complete}});document.querySelectorAll('[data-slide]').forEach(b=>b.onclick=()=>{{si=+b.dataset.slide;render()}})}}function movePackage(d){{pi=(pi+d+DATA.packages.length)%DATA.packages.length;si=0;render()}}function moveSlide(d){{let n=packageNow().slides.length;si=(si+d+n)%n;render()}}$('prevPackage').onclick=()=>movePackage(-1);$('nextPackage').onclick=()=>movePackage(1);$('prevSlide').onclick=()=>moveSlide(-1);$('nextSlide').onclick=()=>moveSlide(1);document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{{mode=b.dataset.mode;renderVisual()}});document.querySelectorAll('[data-zoom]').forEach(b=>b.onclick=()=>{{zoom=+b.dataset.zoom;renderVisual()}});$('copyTags').onclick=()=>navigator.clipboard?navigator.clipboard.writeText(packageNow().hashtags.map(x=>x.hashtag).join(' ')):null;render();</script></body></html>'''
