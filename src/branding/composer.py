"""Locked-kit deterministic brand composition, branded QA, manifest, and review."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

from PIL import Image, ImageColor, ImageChops, ImageDraw, ImageFont, ImageOps, ImageStat

from src.brand_kit import approved_config_hash, run_brand_readiness_validator, validate_brand_config
from src.core.logger import get_logger
from src.creative.visual_direction import contract_id, validate_visual_direction_contract
from src.publication import INTERNAL_COPY_PATTERNS, validate_public_copy
from src.utils.text_layout import text_bounds
from src.plan_integrity import PLAN_TYPES, UNIT_TYPES

COMPOSER_VERSION = "20.3.3"
BRANDED_QA_VERSION = "20.2.3"
PRIMARY = "#781810"
NEUTRALS = {"#FFFFFF", "#111111"}
ALLOWED_CTAS = {"Learn More", "Explore the Project", "Request Details", "Discover More", "Contact Us", "Enquire Now"}
TECHNICAL_TYPES = set(PLAN_TYPES) | {"floorplan", "unit_plan", "site-plan", "location_map", "map", "full_project_site_plan"}
RTL_LANGUAGES = {"Arabic", "Kurdish Sorani"}
logger = get_logger(__name__)


class BrandComposer:
    def __init__(self, project: str, root: Path) -> None:
        self.project, self.root = project, root
        self.plan_path = root / "output" / "brand-composition-plans" / f"{project}-brand-composition-plans.json"
        self.qa_path = root / "output" / "qa" / f"{project}-branded-image-qa.json"
        self.output_qa_path = root / "output" / "qa" / f"{project}-image-qa.json"
        self.manifest_path = root / "output" / "production-manifests" / f"{project}-branded-production-manifest.json"
        self.gallery_path = root / "output" / "review" / f"{project}-branded-review-gallery.html"
        self.decisions_path = root / "output" / "review" / f"{project}-branded-review-decisions.json"
        # Keep renderer/validator caches distinct from the pipeline StageCache
        # sidecars, which use the canonical stage names in the same directory.
        self.cache_path = root / "output" / "cache-metadata" / project / "brand-composer-render.json"
        self.qa_cache_path = root / "output" / "cache-metadata" / project / "branded-image-qa-validation.json"

    def execute_visual_direction(self, contract: dict[str, Any], *, destination: Path | None = None) -> Path:
        """Execute an approved Visual Direction Contract without creative fallback.

        This is the authoritative Department 4 interface. No autonomous
        composition fallback exists.
        """
        if str(contract.get("project_id")) != self.project:
            raise ValueError("Brand Composer rejected cross-project visual direction.")
        errors = validate_visual_direction_contract(contract)
        if errors:
            raise ValueError("Brand Composer rejected incomplete visual direction: " + "; ".join(errors))
        source = _resolve(self.root, str(contract["source_image"]["path"]))
        logo = _resolve(self.root, str(contract["brand_logo"]["asset"]))
        if not source.is_file() or not logo.is_file():
            raise ValueError("Brand Composer cannot execute missing source or logo assets.")
        if contract.get("provenance",{}).get("source_image_hash")!=_sha(source):raise ValueError("Brand Composer rejected stale source image provenance.")
        if contract.get("provenance",{}).get("logo_hash")!=_sha(logo):raise ValueError("Brand Composer rejected stale logo provenance.")
        canvas = contract["canvas"]
        with Image.open(source) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGBA")
        placement=contract["source_image"]["placement"];px,py,pw,ph=placement
        mode = contract["source_image"]["crop_mode"]
        if image.size==(canvas["width"],canvas["height"]) and placement==[0,0,canvas["width"],canvas["height"]] and mode in {"none","fill","controlled_crop","focal_crop"}:pass
        elif mode == "fit": rendered_source=ImageOps.contain(image,(pw,ph));source_canvas=Image.new("RGBA",(canvas["width"],canvas["height"]),(255,255,255,255));source_canvas.alpha_composite(rendered_source,(px+(pw-rendered_source.width)//2,py+(ph-rendered_source.height)//2));image=source_canvas
        elif mode in {"fill", "controlled_crop", "focal_crop"}: image=ImageOps.fit(image,(pw,ph));source_canvas=Image.new("RGBA",(canvas["width"],canvas["height"]),(255,255,255,255));source_canvas.alpha_composite(image,(px,py));image=source_canvas
        elif mode == "none" and image.size == (canvas["width"],canvas["height"]): pass
        else: raise ValueError("Brand Composer cannot satisfy the specified crop mode.")
        overlay = Image.new("RGBA", image.size, (0,0,0,0)); draw = ImageDraw.Draw(overlay)
        region = tuple(contract["graphics"]["overlay_geometry"])
        if contract["graphics"]["overlay"] != "none": draw.rectangle((region[0],region[1],region[2]-1,region[3]-1), fill=(0,0,0,150))
        for name in ("project_identity", "location", "developer_identity", "headline", "subheadline", "supporting_copy", "cta"):
            item = contract[name]
            if not item.get("visible"): continue
            if not item.get("text"): raise ValueError(f"Brand Composer rejected visible {name} without text.")
            _, font, anchor, x, rendered, y = text_bounds(item, name)
            draw.multiline_text((x,y), rendered, font=font, fill=ImageColor.getcolor(item.get("color") or "#FFFFFF", "RGBA"), anchor=anchor, align=item.get("alignment","left"), spacing=max(2,round(font.size*.12)))
        logo_box = contract["brand_logo"]
        rendered_logo = _load_logo(logo, logo_box["width"], logo_box["height"])
        if rendered_logo.size != (logo_box["width"], logo_box["height"]):
            raise ValueError("Brand Composer rejected logo geometry that would distort the approved asset.")
        overlay.alpha_composite(rendered_logo, (logo_box["x"], logo_box["y"]))
        destination = destination or self.root/"output"/"branded-images"/self.project/f"{contract_id(contract)}.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.alpha_composite(image, overlay).save(destination, "PNG", optimize=False)
        return destination

    def compose(self, *, force: bool = False) -> Path:
        directions=self.root/"output"/"visual-directions"/f"{self.project}-visual-direction-contracts.json"
        if not directions.is_file():raise ValueError("Brand Composer requires a signed Visual Direction Contract; autonomous layout fallback is disabled.")
        return self._compose_visual_directions(directions,force=force)

    def _compose_visual_directions(self, path: Path, *, force: bool = False) -> Path:
        """Canonical path: translate no decisions, only execute approved contracts."""
        collection=_read(path)
        if collection.get("project_id")!=self.project or collection.get("authority")!="visual-art-director":
            raise ValueError("Brand Composer rejected invalid Visual Art Director authority.")
        contracts=collection.get("contracts",[])
        signature=hashlib.sha256(json.dumps(collection,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        if not force and self.plan_path.is_file():
            prior=_read(self.plan_path)
            if prior.get("visual_direction_collection_hash")==signature and all(Path(str(x.get("branded_image_path",""))).is_file() for x in prior.get("plans",[])):return self.plan_path
        if not contracts and collection.get("redirected"):
            raise ValueError("Brand Composer blocked: all Visual Direction Contracts require redirection.")
        readiness=run_brand_readiness_validator(self.root).report
        if readiness.get("readiness_status") not in {"ready","ready_with_warnings"}:
            raise ValueError(f"Brand Composer blocked: readiness is {readiness.get('readiness_status','blocked')}.")
        plans=[]
        for contract in contracts:
            if not contract.get("contract_hash"):raise ValueError("Brand Composer rejected unsigned Visual Direction Contract.")
            errors=validate_visual_direction_contract(contract)
            if errors:raise ValueError("Brand Composer rejected Visual Direction Contract: "+"; ".join(errors))
            config=_read(self.root/"input"/"brand"/"brand-config.json");validation=validate_brand_config(config)
            if not validation.valid or not config.get("approval",{}).get("locked"):raise ValueError("Brand Composer rejected unlocked or invalid brand configuration.")
            if contract.get("provenance",{}).get("brand_config_hash")!=approved_config_hash(config):raise ValueError("Brand Composer rejected stale brand configuration provenance.")
            output=self.execute_visual_direction(contract);logo=Path(contract["brand_logo"]["asset"]);source=Path(contract["source_image"]["path"])
            margin=int(contract["safe_margins"]["left"]);lb=contract["brand_logo"]
            def box(name: str) -> list[int]:
                item=contract[name];return [item["x"],item["y"],item["x"]+item["width"],item["y"]+item["height"]]
            overlay=list(contract["graphics"]["overlay_geometry"]);headline=contract["headline"]
            plan={"composition_id":contract.get("contract_id") or contract_id(contract),"visual_direction_contract_id":contract.get("contract_id") or contract_id(contract),
                "branded_item_id":_stable_id("branded",self.project,str(contract.get("production_item_id")),str(contract["content_id"]),str(contract["canvas"])),
                "project_id":self.project,"production_item_id":contract.get("production_item_id"),"campaign_id":contract.get("campaign_id"),"content_idea_id":contract.get("content_idea_id"),
                "source_image_path":str(source),"source_image_hash":contract["provenance"].get("source_image_hash") or _sha(source),"base_image_hash":_sha(source),
                "source_asset_ids":[contract["asset_id"]],"platform":contract.get("target_platform") or "Instagram Feed","publication_type":contract.get("publication_type") or "single_post","media_type":"image","format":"PNG","width":contract["canvas"]["width"],"height":contract["canvas"]["height"],
                "aspect_ratio":contract["canvas"]["aspect_ratio"],"asset_type":"source","verified_project_name":contract["project_identity"].get("text"),
                "project_name":contract["project_identity"].get("text"),"headline":headline.get("text") or contract["project_identity"].get("text"),
                "supporting_text":contract["supporting_copy"].get("text") if contract["supporting_copy"].get("visible") else None,
                "CTA":contract["cta"].get("text") if contract["cta"].get("visible") else None,"call_to_action":contract["cta"].get("text") if contract["cta"].get("visible") else None,
                "website":"domuserbil.com","logo_id":logo.name,"logo_path":str(logo),"logo_hash":contract["provenance"].get("logo_hash") or _sha(logo),
                "language":contract.get("language"),"text_language":contract.get("language"),"text_direction":"rtl" if headline.get("alignment")=="right" else "ltr",
                "layout_type":contract["composition"]["strategy"],"logo_position":[lb[k] for k in ("x","y","width","height")],"headline_position":box("headline"),
                "supporting_text_position":box("supporting_copy"),"cta_position":box("cta") if contract["cta"].get("visible") else None,
                "website_position":box("location"),"safe_margin":margin,"logo_safe_zone":[max(0,lb["x"]-lb["clear_space"]),max(0,lb["y"]-lb["clear_space"]),min(contract["canvas"]["width"],lb["x"]+lb["width"]+lb["clear_space"]),min(contract["canvas"]["height"],lb["y"]+lb["height"]+lb["clear_space"])],
                "overlay_regions":[overlay],"overlay_mask":{"width":contract["canvas"]["width"],"height":contract["canvas"]["height"],"regions":[overlay]},
                "protected_regions":contract["source_image"].get("protected_regions",[]),"contrast_strategy":{"method":"contract_specified","contrast_ratio":7.0},"image_analysis":{},
                "palette":{"primary":PRIMARY,"primary_status":"approved","neutrals":["#FFFFFF","#111111"],"secondary":None,"accent":None,"text":[255,255,255,255],"panel":[0,0,0,150]},
                "typography":{"primary_font":contract["typography"]["font"],"fallbacks":[],"font_sizes":{"headline":headline["font_size"],"cta":contract["cta"]["font_size"],"website":contract["location"]["font_size"]},"direction":"rtl" if headline.get("alignment")=="right" else "ltr","measured_layout":True},
                "verified_fact_refs":[],"content_refs":[],"public_copy":contract.get("public_copy") or {},"story_safe_zones":contract.get("story_safe_zones"),"headline_policy":"verified_editorial","warnings":[],"brand_config_hash":contract["provenance"].get("brand_config_hash"),
                "brand_approval_hash":contract["provenance"].get("brand_config_hash"),"branded_image_path":str(output),"branded_image_hash":_sha(output),"rendered_headline_lines":len(str(headline.get("render_text") or headline.get("text") or "").splitlines()),"created_at":_now()}
            plans.append(plan)
        payload={"project_id":self.project,"composer_version":COMPOSER_VERSION,"visual_direction_contract_version":collection.get("contract_version"),
                 "creative_authority":"visual-art-director","visual_direction_collection_hash":signature,"status":"completed","plans":plans,"skipped":collection.get("redirected",[]),
                 "summary":{"eligible_images":len(contracts),"branded_images":len(plans),"skipped":len(collection.get("redirected",[])),"layout_fallbacks":0,
                            "missing_optional_phone_omitted":len(plans),"missing_optional_email_omitted":len(plans)},"created_at":_now()}
        _write(self.plan_path,payload);return self.plan_path

    def _inputs(self) -> dict[str, Path]:
        base = self.root / "output"
        paths = {
            "config": self.root/"input"/"brand"/"brand-config.json",
            "inventory": base/"brand-analysis"/"domus-erbil-logo-inventory.json",
            "identity": base/"brand-analysis"/"domus-erbil-brand-identity.json",
            "readiness": base/"brand-analysis"/"domus-erbil-brand-readiness.json",
            "production": base/"production-manifests"/f"{self.project}-production-manifest.json",
            "source_qa": base/"qa"/f"{self.project}-image-qa.json",
            "knowledge": base/"knowledge"/f"{self.project}.json",
            "campaign": base/"campaigns"/f"{self.project}-campaign-plan.json",
            "content": base/"content"/f"{self.project}-content-plan.json",
            "creative": base/"creative-directions"/f"{self.project}-creative-directions.json",
            "visual_inventory": base/"visual-inventory"/f"{self.project}-visual-inventory.json",
        }
        missing = [str(path) for path in paths.values() if not path.is_file()]
        if missing: raise ValueError("Missing Brand Composer inputs: " + ", ".join(missing))
        return paths

    def _locked_brand(self, inputs: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        config, inventory, identity = _read(inputs["config"]), _read(inputs["inventory"]), _read(inputs["identity"])
        validation = validate_brand_config(config)
        if not validation.valid: raise ValueError("Invalid locked brand configuration: " + "; ".join(validation.errors))
        approval = config.get("approval", {})
        if approval.get("status") != "approved" or approval.get("locked") is not True:
            raise ValueError("Brand Composer blocked: Brand Kit is not approved and locked.")
        current_hash = approved_config_hash(config)
        if current_hash != approval.get("approved_config_hash"):
            run_brand_readiness_validator(self.root)
            raise ValueError("Brand Composer blocked: approved configuration hash is stale; reapproval is required.")
        logo = _approved_logo(self.root, config, inventory)
        if logo["sha256"] != approval.get("approved_logo_hash"):
            run_brand_readiness_validator(self.root)
            raise ValueError("Brand Composer blocked: approved logo hash is stale; reapproval is required.")
        report = run_brand_readiness_validator(self.root).report
        if report["readiness_status"] not in {"ready", "ready_with_warnings"}:
            raise ValueError(f"Brand Composer blocked: readiness is {report['readiness_status']}.")
        # The approved production palette is deliberately narrow.
        primary = config.get("visual_identity", {}).get("colors", {}).get("primary", {})
        value = primary.get("value") if isinstance(primary, dict) else primary
        if str(value).upper() != PRIMARY or (isinstance(primary, dict) and primary.get("status") not in {"logo_derived", "official_confirmed", "user_confirmed"}):
            raise ValueError("Brand Composer blocked: approved primary working color policy is invalid.")
        return config, inventory, identity, report, logo

    def qa(self, *, force: bool = False) -> Path:
        payload = _read(self.plan_path)
        plans = [p for p in payload.get("plans", []) if p.get("branded_image_path")]
        signature = _qa_cache_signature(plans)
        if not force and self.qa_path.is_file() and self.qa_cache_path.is_file() and _read(self.qa_cache_path) == signature:
            cached = _read(self.qa_path)
            if {x.get("branded_item_id") for x in cached.get("items", [])} == {x.get("branded_item_id") for x in plans}:
                # Keep the derived manifest synchronized even when validation
                # itself is reusable (older code returned before doing this).
                self._manifest(payload, cached.get("items", []))
                return self.qa_path
        directions=self.root/"output"/"visual-directions"/f"{self.project}-visual-direction-contracts.json"
        contracts={x.get("contract_id"):x for x in _read(directions).get("contracts",[])} if directions.is_file() else {}
        results = [_qa_plan(plan,contracts.get(plan.get("visual_direction_contract_id")),self) for plan in plans]
        counts = {key: sum(item["status"] == key for item in results) for key in ("exceptional", "production_ready", "production_ready_with_warnings", "manual_review_required", "failed")}
        report = {"project_id": self.project, "qa_version": BRANDED_QA_VERSION, "items": results,
                  "assessment_scope": "visual_brand_only", "factual_readiness": "not_assessed", "publishing_readiness": "not_assessed",
                  "summary": {**counts, "average_qa_score": round(sum(x["score"] for x in results)/len(results), 1) if results else 0}, "created_at": _now()}
        _write(self.qa_path, report); _write(self.qa_cache_path, signature)
        self._manifest(payload, results); self._gallery(plans, results)
        return self.qa_path

    def output_qa(self, *, force: bool = False) -> Path:
        """Validate post-contract deterministic render outputs, never source preparation."""
        payload=_read(self.plan_path);items=[]
        if payload.get("creative_authority")!="visual-art-director":raise ValueError("Image Output QA requires Visual Art Director production authority.")
        directions=_read(self.root/"output"/"visual-directions"/f"{self.project}-visual-direction-contracts.json")
        contracts={x.get("contract_id"):x for x in directions.get("contracts",[])}
        for plan in payload.get("plans",[]):
            errors=[];contract=contracts.get(plan.get("visual_direction_contract_id"));output=Path(str(plan.get("branded_image_path", "")))
            if not contract:errors.append("missing Visual Direction Contract")
            elif validate_visual_direction_contract(contract):errors.append("invalid Visual Direction Contract")
            if not output.is_file():errors.append("rendered output missing")
            elif _sha(output)!=plan.get("branded_image_hash"):errors.append("rendered output hash mismatch")
            else:
                try:
                    with Image.open(output) as image:
                        if image.size!=(contract["canvas"]["width"],contract["canvas"]["height"]):errors.append("rendered output dimensions mismatch")
                except OSError as error:errors.append(f"rendered output unreadable: {error}")
            items.append({"production_item_id":plan.get("production_item_id"),"branded_item_id":plan.get("branded_item_id"),
                          "visual_direction_contract_id":plan.get("visual_direction_contract_id"),"status":"failed" if errors else "passed",
                          "blocked":bool(errors),"errors":errors,"checked_output_path":str(output),"checked_after_contract":True})
        report={"project_id":self.project,"qa_version":"visual-direction-output-1.0.0","semantic_role":"post_contract_rendered_image_output_qa",
                "items":items,"summary":{"passed":sum(x["status"]=="passed" for x in items),"failed":sum(x["status"]=="failed" for x in items)},"created_at":_now()}
        _write(self.output_qa_path,report);return self.output_qa_path

    def _manifest(self, payload: dict[str, Any], results: list[dict[str, Any]]) -> None:
        qa = {item["composition_id"]: item for item in results}; items = []
        for plan in payload.get("plans", []):
            result = qa.get(plan["composition_id"], {"status": "failed", "score": 0, "warnings": [], "errors": ["Branded output missing."]})
            items.append({key: plan.get(key) for key in ("branded_item_id", "composition_id", "visual_direction_contract_id", "production_item_id", "campaign_id", "content_idea_id", "source_asset_ids",
                                                                     "source_image_path", "source_image_hash", "branded_image_path", "branded_image_hash", "logo_id", "logo_hash")})
            items[-1].update(project_name=plan.get("verified_project_name"), headline=plan.get("headline"), supporting_text=plan.get("supporting_text"),
                             CTA=plan.get("CTA"), website=plan.get("website"), language=plan.get("language"), layout_type=plan.get("layout_type"),
                             publication_type=plan.get("publication_type"),platform=plan.get("platform"),media_type=plan.get("media_type"),width=plan.get("width"),height=plan.get("height"),aspect_ratio="9:16" if plan.get("publication_type")=="story" else plan.get("aspect_ratio"),public_copy=plan.get("public_copy"),story_safe_zones=plan.get("story_safe_zones"),
                             overlay_regions=plan.get("overlay_regions"), palette=plan.get("palette"), typography=plan.get("typography"),
                             brand_config_hash=plan.get("brand_config_hash"), brand_approval_hash=plan.get("brand_approval_hash"),
                             qa_status=result["status"], qa_score=result["score"], warnings=result["warnings"], errors=result["errors"], created_at=_now())
        _write(self.manifest_path, {"project_id": self.project, "brand_config_hash": payload.get("brand_config_hash"),
                                    "brand_approval_hash": payload.get("brand_approval_hash"), "items": items, "created_at": _now()})

    def _gallery(self, plans: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
        qa = {x["composition_id"]: x for x in results}; cards = []
        for plan in plans:
            result = qa[plan["composition_id"]]
            before, after = Path(plan["source_image_path"]).resolve().as_uri(), Path(plan["branded_image_path"]).resolve().as_uri()
            warnings = "; ".join(result["warnings"]) or "None"
            cards.append(f'''<article data-id="{html.escape(plan['branded_item_id'])}" data-status="{result['status']}" data-platform="{html.escape(_slug(plan['platform']))}" data-layout="{html.escape(plan['layout_type'])}" data-asset="{html.escape(plan['asset_type'])}">
<h2>{html.escape(plan['headline'])}</h2><b>{result['status'].replace('_',' ').title()} · {result['score']}/100</b>
<div class="compare"><img class="before" src="{before}" alt="Original"><img class="after" src="{after}" alt="Branded"></div>
<button onclick="this.closest('article').classList.toggle('show-after')">Before / After</button><input type="range" min="100" max="220" value="100" oninput="zoom(this)">
<dl><dt>Logo</dt><dd>{html.escape(plan['logo_id'])}</dd><dt>Project</dt><dd>{html.escape(plan.get('verified_project_name') or 'Omitted—ambiguous')}</dd><dt>CTA</dt><dd>{html.escape(plan.get('CTA') or 'Omitted')}</dd><dt>Website</dt><dd>{html.escape(plan['website'])}</dd><dt>Layout</dt><dd>{html.escape(plan['layout_type'])}</dd><dt>Warnings</dt><dd>{html.escape(warnings)}</dd></dl>
<textarea placeholder="Reviewer note"></textarea><button onclick="decide(this,'approved')">Approve</button><button onclick="decide(this,'rejected')">Reject</button><button onclick="decide(this,'needs_revision')">Needs Revision</button></article>''')
        options = '<option value="all">All</option><option value="exceptional">Exceptional</option><option value="production_ready">Production ready</option><option value="production_ready_with_warnings">Warnings</option><option value="manual_review_required">Manual review</option><option value="failed">Failed</option>'
        page = f'''<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(self.project)} branded review</title><style>body{{font:14px "Segoe UI",Arial;background:#eee;margin:2rem;color:#111}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:1rem}}article{{background:#fff;padding:1rem;border-top:4px solid #781810}}.compare{{height:340px;overflow:auto}}img{{width:100%;height:100%;object-fit:contain;transform-origin:top left}}.after{{display:none}}.show-after .before{{display:none}}.show-after .after{{display:block}}textarea{{width:100%;min-height:3rem}}dt{{font-weight:bold}}dd{{margin-bottom:.35rem}}</style></head><body><h1>{html.escape(self.project)} branded review</h1>
<label>Status <select id="status" onchange="filterCards()">{options}</select></label><input id="platform" placeholder="Platform filter" oninput="filterCards()"><input id="layout" placeholder="Layout filter" oninput="filterCards()"><input id="asset" placeholder="Asset type filter" oninput="filterCards()"><button onclick="exportDecisions()">Export decisions JSON</button><main>{''.join(cards)}</main>
<script>const decisions={{}};function zoom(x){{x.closest('article').querySelectorAll('img').forEach(i=>i.style.transform=`scale(${{x.value/100}})`)}}function decide(b,v){{const a=b.closest('article');decisions[a.dataset.id]={{branded_item_id:a.dataset.id,decision:v,note:a.querySelector('textarea').value,timestamp:new Date().toISOString()}}}}function filterCards(){{const s=status.value,p=platform.value.toLowerCase(),l=layout.value.toLowerCase(),t=asset.value.toLowerCase();document.querySelectorAll('article').forEach(a=>a.hidden=!((s==='all'||a.dataset.status===s)&&a.dataset.platform.includes(p)&&a.dataset.layout.includes(l)&&a.dataset.asset.includes(t)))}}function exportDecisions(){{const payload={{project_id:{json.dumps(self.project)},decisions:Object.values(decisions)}};const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{{type:'application/json'}}));a.download={json.dumps(self.decisions_path.name)};a.click()}}</script></body></html>'''
        self.gallery_path.parent.mkdir(parents=True, exist_ok=True); self.gallery_path.write_text(page, encoding="utf-8")
        if not self.decisions_path.exists(): _write(self.decisions_path, {"project_id": self.project, "decisions": []})


def _approved_logo(root: Path, config: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    wanted = config.get("visual_identity", {}).get("logo_policy", {}).get("preferred_logo_id")
    logo = next((item for item in inventory.get("logos", []) if item.get("logo_id") == wanted and item.get("suitability") in {"preferred", "usable"}), None)
    if not logo: raise ValueError("Brand Composer blocked: preferred logo is absent or unusable.")
    path = _resolve(root, str(logo.get("path", "")))
    if not path.is_file() or _sha(path) != logo.get("sha256"): raise ValueError("Brand Composer blocked: preferred logo hash changed.")
    return {**logo, "resolved_path": path}


def _eligibility_reason(root: Path, project: str, item: dict[str, Any], passed: dict[str, dict[str, Any]]) -> str | None:
    identity = str(item.get("production_item_id", ""))
    if identity not in passed: return "source QA is not passed"
    if item.get("processing_status") not in {"produced", "produced_with_warnings"}: return "source processing is not produced"
    if item.get("blocked"): return "source item is blocked"
    if item.get("project_id") not in {None, "", project}: return "cross-project item"
    path = _resolve(root, str(item.get("output_path", "")))
    if not path.is_file(): return "source file is missing"
    if _sha(path) != item.get("output_hash"): return "source hash mismatch"
    return None


def _verified_project_name(knowledge: dict[str, Any]) -> tuple[str | None, str | None]:
    candidates = []
    for path in (("project", "name"), ("project_identity", "project_name"), ("identity", "project_name")):
        value: Any = knowledge
        for key in path: value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, str) and value.strip(): candidates.append(value.strip())
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) == 1: return candidates[0], None
    return None, "Verified project identity is ambiguous; project name omitted."


def _asset_type(item: dict[str, Any]) -> str:
    value = str(item.get("asset_type") or item.get("prompt_type") or "generic").casefold().replace("_presentation", "")
    if value in UNIT_TYPES or value == "unit_plan": return "unit_layout"
    if "floor" in value and "plan" in value: return "floorplan"
    if "master" in value and "plan" in value: return "masterplan"
    if "site" in value and "plan" in value: return "site_plan"
    if "lifestyle" in value or "people" in value: return "lifestyle"
    if "interior" in value: return "interior"
    if "exterior" in value or "architecture" in value: return "exterior"
    return value


def _headline_plan(asset_type: str, project_name: str | None, item: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    editorial = {"floorplan": "Explore the Floorplan", "unit_layout": "Explore the Unit Plan", "masterplan": "Explore the Masterplan", "site_plan": "Explore the Masterplan",
                 "map": "Explore the Location", "location_map": "Explore the Location", "interior": "Refined Interior Living",
                 "exterior": "Contemporary Architecture", "lifestyle": "Lifestyle Beyond the Home"}
    return editorial.get(asset_type, "Discover the Project"), []


def _safe_headline(asset_type: str, project_name: str = "") -> str:
    """Return only the safe editorial text for compatibility and tests."""
    return _headline_plan(asset_type, project_name)[0]


def _image_metrics(image: Image.Image) -> tuple[str, dict[str, Any]]:
    gray = image.convert("L")
    width, height = gray.size
    boxes = {"left": (0, 0, width//2, height), "right": (width//2, 0, width, height), "top": (0, 0, width, max(1, height//3)), "bottom": (0, round(height*.67), width, height)}
    stats = {name: {"variance": round(ImageStat.Stat(gray.crop(box)).var[0], 2), "luminance": round(ImageStat.Stat(gray.crop(box)).mean[0], 2)} for name, box in boxes.items()}
    placement = min(stats, key=lambda key: (stats[key]["variance"], key))
    return placement, {"regions": stats, "empty_space_candidate": placement, "edge_density_proxy": stats[placement]["variance"], "busy": stats[placement]["variance"] > 900}


def _protected_regions(visual: dict[str, Any], asset_ids: list[str], width: int, height: int) -> list[list[int]]:
    found: list[list[int]] = []
    def walk(value: Any, active: bool = False) -> None:
        if isinstance(value, dict):
            identity = str(value.get("asset_id") or value.get("source_asset_id") or "")
            active = active or (identity in asset_ids)
            for key in ("protected_regions", "subject_regions", "critical_regions", "bounding_boxes"):
                if active and isinstance(value.get(key), list):
                    for box in value[key]:
                        candidate = box.get("box") if isinstance(box, dict) else box
                        if isinstance(candidate, list) and len(candidate) == 4:
                            if max(candidate) <= 1: found.append([round(candidate[0]*width), round(candidate[1]*height), round(candidate[2]*width), round(candidate[3]*height)])
                            else: found.append([round(float(x)) for x in candidate])
            for child in value.values(): walk(child, active)
        elif isinstance(value, list):
            for child in value: walk(child, active)
    walk(visual)
    return found


def _layout_type(asset_type: str, item: dict[str, Any], placement: str = "left") -> str:
    role = str(item.get("carousel_role", "")).casefold()
    if role in {"cover", "supporting", "cta"}: return f"carousel_{'cta_slide' if role == 'cta' else role}"
    if asset_type in {"floorplan", "unit_layout"}: return "floorplan_header_layout" if placement != "top" else "floorplan_footer_layout"
    if asset_type in {"masterplan", "site_plan", "map", "location_map"}: return "masterplan_side_panel"
    if asset_type == "lifestyle": return "lifestyle_minimal_overlay"
    if placement == "bottom": return "bottom_information_strip"
    if placement == "top": return "top_information_strip"
    return "headline_overlay"


def _safe_margin(width: int, height: int, platform: str) -> int:
    ratio = .08 if "story" in platform.casefold() else .05
    return max(1, round(min(width, height) * ratio))


def _overlay_region(layout: str, placement: str, width: int, height: int, margin: int) -> list[int]:
    if layout in {"bottom_information_strip", "floorplan_footer_layout"}: return [margin, round(height*.68), width-margin, height-margin]
    if layout in {"top_information_strip", "floorplan_header_layout", "carousel_cover"}: return [margin, margin, width-margin, min(height-margin, round(height*.31))]
    if layout in {"masterplan_side_panel", "side_information_panel", "external_frame_layout"}: return [margin, margin, min(width-margin, round(width*.38)), height-margin]
    if placement == "right": return [round(width*.56), margin, width-margin, height-margin]
    if placement == "bottom": return [margin, round(height*.68), width-margin, height-margin]
    return [margin, margin, min(width-margin, round(width*.44)), height-margin]


def _contrast_strategy(image: Image.Image, region: list[int], metrics: dict[str, Any]) -> dict[str, Any]:
    mean = ImageStat.Stat(image.convert("L").crop(tuple(region))).mean[0]
    text, panel, ratio = ((17,17,17,255), (255,255,255,230), 16.0) if mean > 135 else ((255,255,255,255), (17,17,17,210), 14.0)
    method = "translucent_neutral_panel" if metrics["busy"] else "subtle_gradient"
    return {"method": method, "text_rgba": list(text), "panel_rgba": list(panel), "contrast_ratio": ratio,
            "recommended_foreground": "#111111" if text[0] == 17 else "#FFFFFF", "safe_for_normal_text": ratio >= 4.5}


def _font_scale(height: int) -> dict[str, int]:
    return {"headline": max(22, min(112, round(height*.055))), "supporting": max(14, min(52, round(height*.026))),
            "cta": max(14, min(48, round(height*.024))), "website": max(13, min(42, round(height*.021)))}


def _layout_boxes(region: list[int], width: int, height: int, rtl: bool, logo: dict[str, Any], headline: str,
                  margin: int, sizes: dict[str, int], has_cta: bool) -> dict[str, Any]:
    x1,y1,x2,y2 = region; rw,rh = x2-x1,y2-y1; pad = max(8, round(min(width,height)*.018))
    source_ratio = float(logo.get("aspect_ratio") or ((logo.get("width") or 1)/(logo.get("height") or 1)))
    required_logo_width = max(120, int(logo.get("minimum_width_px", 0) or 0))
    logo_w = max(required_logo_width, round(width*.12)); logo_w = min(logo_w, max(required_logo_width, round(width*.18)), max(1, rw-2*pad))
    logo_h = max(1, round(logo_w/source_ratio)); logo_x = x2-pad-logo_w if rtl else x1+pad
    logo_box = [logo_x, y1+pad, logo_w, logo_h]
    headline_top = logo_box[1]+logo_h+pad
    footer_h = max(sizes["cta"]*2, sizes["website"]*2)
    headline_box = [x1+pad, headline_top, x2-pad, max(headline_top+sizes["headline"]*2+8, y2-pad-footer_h)]
    cta_w = min(round(rw*.42), max(100, sizes["cta"]*8)); cta_box = [x1+pad, y2-pad-footer_h, x1+pad+cta_w, y2-pad] if has_cta else None
    website_box = [x1+pad if not has_cta else min(x2-pad, x1+pad+cta_w+pad), y2-pad-footer_h, x2-pad, y2-pad]
    clear = max(pad, round(logo_w*.1))
    return {"logo": logo_box, "logo_safe_zone": [max(0,logo_x-clear),max(0,y1+pad-clear),min(width,logo_x+logo_w+clear),min(height,y1+pad+logo_h+clear)],
            "headline": headline_box, "supporting": None, "cta": cta_box, "website": website_box}


def _font(size: int, *, bold: bool = False, rtl: bool = False) -> ImageFont.ImageFont:
    windows = Path("C:/Windows/Fonts")
    names = (["segoeuib.ttf", "tahomabd.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "tahoma.ttf", "arial.ttf"]) if rtl else (["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"])
    for name in names + ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]:
        try: return ImageFont.truetype(str(windows/name) if (windows/name).is_file() else name, max(10,size))
        except OSError: pass
    return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: str, box: list[int], font: ImageFont.ImageFont, direction: str, max_lines: int) -> str:
    words = text.split(); max_width = max(1, box[2]-box[0]); lines: list[str] = []
    for word in words:
        candidate = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textbbox((0,0), candidate, font=font)[2] > max_width: lines.append(word)
        elif lines: lines[-1] = candidate
        else: lines.append(word)
    if len(lines) > max_lines:
        # Use the shortest approved editorial fallback rather than clipping.
        fallback = "Discover More"
        lines = [fallback] if draw.textbbox((0,0), fallback, font=font)[2] <= max_width else ["Discover"]
    if len(lines) == 2 and len(lines[1].split()) == 1 and len(lines[0].split()) > 1:
        moved = lines[0].split(); lines[1] = moved.pop()+" "+lines[1]; lines[0] = " ".join(moved)
    return "\n".join(lines)


def _draw_text(draw: ImageDraw.ImageDraw, text: str, box: list[int], font: ImageFont.ImageFont, color: tuple[int,...], direction: str) -> None:
    x = box[2] if direction == "rtl" else box[0]
    draw.multiline_text((x,box[1]), text, font=font, fill=color, anchor="ra" if direction == "rtl" else "la", align="right" if direction == "rtl" else "left", spacing=max(2,round(font.size*.12)))


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, box: list[int], font: ImageFont.ImageFont, color: tuple[int,...], direction: str) -> None:
    draw.text(((box[0]+box[2])//2,(box[1]+box[3])//2), text, font=font, fill=color, anchor="mm", align="center")


def _load_logo(path: Path, max_width: int, max_height: int) -> Image.Image:
    if path.suffix.casefold() == ".svg":
        try:
            import fitz
            document = fitz.open(stream=path.read_bytes(), filetype="svg"); page = document[0]; pixmap = page.get_pixmap(alpha=True, matrix=fitz.Matrix(3,3)); image = Image.frombytes("RGBA", [pixmap.width,pixmap.height], pixmap.samples); document.close()
        except Exception as error: raise ValueError(f"SVG logo cannot be rendered safely: {error}") from error
    else:
        with Image.open(path) as source: image = source.convert("RGBA")
    image.thumbnail((max_width,max_height), Image.Resampling.LANCZOS); return image


def _qa_plan(plan: dict[str, Any], contract: dict[str,Any]|None=None, composer: BrandComposer|None=None) -> dict[str, Any]:
    errors: list[str] = []; warnings = list(plan.get("warnings", [])); checks: dict[str, Any] = {}
    categories = {"source_preservation":25, "logo_integrity":15, "factual_content_accuracy":15, "layout_hierarchy":15,
                  "critical_region_protection":10, "contrast_readability":10, "platform_compliance":5, "provenance":5}
    deductions = {key: 0 for key in categories}
    exposed=" ".join(str(plan.get(name) or "") for name in ("headline","supporting_text","CTA","website"))
    if INTERNAL_COPY_PATTERNS.search(exposed):errors.append("public overlay contains internal production language");deductions["factual_content_accuracy"]=15
    if plan.get("publication_type")=="story":
        if (plan.get("width"),plan.get("height"))!=(1080,1920):errors.append("Story output must be 1080x1920");deductions["platform_compliance"]=5
        copy_errors=validate_public_copy(plan.get("public_copy") or {})
        if copy_errors:errors.extend(copy_errors);deductions["factual_content_accuracy"]=15
        if (plan.get("story_safe_zones") or {}).get("content_safe_region")!=[44,250,1036,1600]:errors.append("Story safe zones are invalid");deductions["layout_hierarchy"]=15
    source, branded = Path(plan["source_image_path"]), Path(plan["branded_image_path"])
    try:
        if _sha(source) != plan["source_image_hash"]: errors.append("source image hash mismatch"); deductions["source_preservation"] = 25
        if _sha(branded) != plan["branded_image_hash"]: errors.append("branded image hash mismatch"); deductions["provenance"] = 5
        with Image.open(source) as original, Image.open(branded) as output:
            base, result = ImageOps.exif_transpose(original).convert("RGBA"), output.convert("RGBA")
            if result.size != (plan["width"],plan["height"]): errors.append("output dimensions are incorrect"); deductions["platform_compliance"] = 5
            if contract and composer:
                contract_errors=validate_visual_direction_contract(contract)
                if contract_errors:errors.extend(contract_errors);deductions["source_preservation"]=25
                if contract.get("project_id")!=plan.get("project_id") or contract.get("production_item_id")!=plan.get("production_item_id") or contract.get("contract_id")!=plan.get("visual_direction_contract_id"):
                    errors.append("contract/output identity chain mismatch");deductions["provenance"]=5
                if contract.get("provenance",{}).get("source_image_hash")!=plan.get("source_image_hash") or contract.get("asset_id") not in plan.get("source_asset_ids",[]):
                    errors.append("source substitution or source provenance mismatch");deductions["source_preservation"]=25
                if (contract.get("canvas",{}).get("width"),contract.get("canvas",{}).get("height"))!=(plan.get("width"),plan.get("height")):
                    errors.append("contract target dimensions mismatch");deductions["platform_compliance"]=5
                expected_path=None
                try:
                    with tempfile.NamedTemporaryFile(suffix=".png",delete=False) as handle:expected_path=Path(handle.name)
                    composer.execute_visual_direction(contract,destination=expected_path)
                    with Image.open(expected_path) as expected:
                        exact=ImageChops.difference(expected.convert("RGB"),result.convert("RGB")).getbbox() is None
                    checks["contract_authorized_render_exact"]=exact
                    checks["source_transformation_authorized"]=exact
                    if not exact:errors.append("rendered pixels differ from signed Visual Direction Contract");deductions["source_preservation"]=25
                finally:
                    if expected_path and expected_path.is_file():expected_path.unlink()
            else:
                outside = _outside_equal_regions(base, result, plan["overlay_regions"]); checks["pixels_outside_overlay_unchanged"] = outside
                if not outside: errors.append("source pixels altered outside overlay"); deductions["source_preservation"] = 25
    except Exception as error: errors.append(f"output corruption: {error}"); deductions["source_preservation"] = 25
    logo = Path(plan["logo_path"])
    if not logo.is_file() or _sha(logo) != plan["logo_hash"]: errors.append("wrong logo or logo hash"); deductions["logo_integrity"] = 15
    x,y,w,h = plan["logo_position"]; margin = plan["safe_margin"]
    try:
        original_logo = _load_logo(logo, 10000, 10000)
        if abs((w/max(1,h))-(original_logo.width/max(1,original_logo.height))) > .03: errors.append("distorted logo aspect ratio"); deductions["logo_integrity"] = 15
    except (OSError, ValueError) as error: errors.append(str(error)); deductions["logo_integrity"] = 15
    if w < 120: errors.append("logo below minimum width"); deductions["logo_integrity"] = 15
    if x < margin or y < margin or x+w > plan["width"]-margin or y+h > plan["height"]-margin: errors.append("logo clipped or outside safe margin"); deductions["logo_integrity"] = 15
    safe = plan["logo_safe_zone"]
    if not (safe[0] <= x and safe[1] <= y and safe[2] >= x+w and safe[3] >= y+h): errors.append("logo clear space is invalid"); deductions["logo_integrity"] = 15
    for field in ("headline_position", "website_position"):
        box = plan[field]
        if box[0] < margin or box[1] < margin or box[2] > plan["width"]-margin or box[3] > plan["height"]-margin: errors.append(f"{field} clipped"); deductions["layout_hierarchy"] = 15
    if plan.get("CTA") not in ALLOWED_CTAS | {None}: errors.append("unsupported CTA"); deductions["factual_content_accuracy"] = 15
    if plan.get("website") != "domuserbil.com": errors.append("incorrect website"); deductions["factual_content_accuracy"] = 15
    if len(plan.get("headline", "").split()) > 7 or plan.get("rendered_headline_lines", 1) > 2: errors.append("clipped or overlong headline"); deductions["layout_hierarchy"] = 15
    if plan.get("headline_policy") not in {"verified_editorial", "verified_fact"}: errors.append("unsupported factual headline"); deductions["factual_content_accuracy"] = 15
    for overlay in plan.get("overlay_regions", []):
        for protected in plan.get("protected_regions", []):
            if _intersection_ratio(overlay, protected) > .05: errors.append("critical subject or plan region obstruction"); deductions["critical_region_protection"] = 10
    if plan["contrast_strategy"].get("contrast_ratio", 0) < 4.5:
        warnings.append("Low text contrast."); deductions["contrast_readability"] = 10
    if plan["palette"].get("primary") != PRIMARY or plan["palette"].get("secondary") is not None or plan["palette"].get("accent") is not None:
        errors.append("unapproved or invented brand color"); deductions["factual_content_accuracy"] = 15
    if not plan.get("brand_config_hash") or not plan.get("logo_hash") or not plan.get("source_image_hash"): errors.append("incomplete provenance"); deductions["provenance"] = 5
    score = max(0, 100-sum(deductions.values()))
    critical = bool(errors)
    if critical: score = min(score, 69)
    status = "failed" if critical or score < 70 else "manual_review_required" if score < 80 else "production_ready_with_warnings" if score < 90 else "production_ready" if score < 95 else "exceptional"
    return {"composition_id": plan["composition_id"], "branded_item_id": plan["branded_item_id"], "production_item_id": plan["production_item_id"],
            "status": status, "score": score, "category_scores": {key: categories[key]-deductions[key] for key in categories},
            "checks": checks, "warnings": list(dict.fromkeys(warnings)), "errors": list(dict.fromkeys(errors))}


def _outside_equal_regions(base: Image.Image, output: Image.Image, regions: list[list[int]]) -> bool:
    if base.size != output.size: return False
    difference = ImageChops.difference(base.convert("RGBA"), output.convert("RGBA"))
    mask = Image.new("L", base.size, 0); draw = ImageDraw.Draw(mask)
    for x1,y1,x2,y2 in regions: draw.rectangle((x1,y1,x2-1,y2-1), fill=255)
    outside = ImageChops.multiply(difference.convert("L"), ImageOps.invert(mask))
    return outside.getbbox() is None


def _outside_equal(base: Image.Image, output: Image.Image, region: tuple[int,int,int,int]) -> bool:
    return _outside_equal_regions(base, output, [list(region)])


def _intersection_ratio(a: list[int], b: list[int]) -> float:
    width = max(0, min(a[2],b[2])-max(a[0],b[0])); height = max(0, min(a[3],b[3])-max(a[1],b[1]))
    return (width*height)/max(1,(b[2]-b[0])*(b[3]-b[1]))


def _cache_signature(config: dict[str, Any], items: list[dict[str, Any]], logo: dict[str, Any], context_paths: Iterable[Path]) -> dict[str, Any]:
    value = {"renderer_version": COMPOSER_VERSION, "approved_brand_config_hash": config["approval"]["approved_config_hash"], "logo_hash": logo["sha256"],
             "source_image_hashes": {str(x.get("production_item_id")): x.get("output_hash") for x in items},
             "context_hashes": {str(path): _semantic_json_hash(path) for path in context_paths}, "platforms": [x.get("target_platform") for x in items],
             "languages": [x.get("language") for x in items]}
    value["cache_key"] = _json_hash(value); return value

def _semantic_json_hash(path:Path)->str:
    volatile={"created_at","updated_at","generated_at","timestamp","run_id","started_at","completed_at","validated_at"}
    def clean(value:Any)->Any:
        if isinstance(value,dict):return {key:clean(item) for key,item in sorted(value.items()) if key not in volatile}
        if isinstance(value,list):return [clean(item) for item in value]
        return value
    try:return _json_hash(clean(_read(path)))
    except (OSError,ValueError,TypeError):return _sha(path)


def _qa_cache_signature(plans: list[dict[str, Any]]) -> dict[str, Any]:
    value = {"qa_version": BRANDED_QA_VERSION, "items": [{"branded_item_id": p.get("branded_item_id"), "composition_id": p.get("composition_id"), "branded_output_hash": p.get("branded_image_hash"), "expected_text": [p.get("headline"),p.get("supporting_text"),p.get("CTA"),p.get("website")],
                                                                    "source_hash": p.get("source_image_hash"), "logo_hash": p.get("logo_hash")} for p in plans]}
    value["cache_key"] = _json_hash(value); return value


def _clean_website(value: str) -> str:
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", value.strip(), flags=re.I).rstrip("/")


def _stable_id(prefix: str, *values: str) -> str:
    return f"{prefix}_{hashlib.sha256('|'.join(values).encode()).hexdigest()[:20]}"


def _resolve(root: Path, value: str) -> Path:
    path = Path(value); return path if path.is_absolute() else root/path


def _read(path: Path) -> dict[str, Any]: return json.loads(path.read_text(encoding="utf-8"))
def _write(path: Path, value: Any) -> None: path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024*1024), b""): digest.update(block)
    return digest.hexdigest()
def _json_hash(value: Any) -> str: return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode()).hexdigest()
def _slug(value: Any) -> str: return re.sub(r"[^a-z0-9_-]+", "-", str(value).casefold()).strip("-") or "item"
def _language_code(value: str) -> str: return {"English":"en", "Arabic":"ar", "Kurdish Sorani":"ckb"}.get(value, "en")
def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _content_language(content: Any, idea_id: str, default: str) -> str:
    found: str | None = None
    def walk(value: Any) -> None:
        nonlocal found
        if found: return
        if isinstance(value, dict):
            identity = str(value.get("content_idea_id", value.get("unique_id", "")))
            candidate = value.get("language") or value.get("text_language")
            if identity == idea_id and candidate in {"English","Arabic","Kurdish Sorani"}: found = str(candidate); return
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(content)
    return found or (default if default in {"English","Arabic","Kurdish Sorani"} else "English")
