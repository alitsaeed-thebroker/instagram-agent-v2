"""Deterministic, carousel-aware social content packages with source provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from src.content.visual_purpose import assess_visual_purpose, load_visual_reviews, validate_overview_slides
from src.project_sequence import contract, role
from src.brand_kit import approved_config_hash, run_brand_readiness_validator
from src.content.quality import assess_marketing_comprehension, duplicate_copy_fields
from src.creative.production_contract import CONTRACT_VERSION, validate_project_context, validate_publication_package
from src.post_package.grounding import GROUNDING_VERSION, authoritative_facts, make_claim, validate_claims, canonical_unit_facts
from src.plan_integrity import validate_package_layouts, UNIT_TYPES
from src.knowledge.consumer import canonical_project_identity, require_canonical_graph
from src.execution.lineage import attach_lineage, artifact_fingerprint, canonical_graph_fingerprint, require_lineage

GROUPING_VERSION="1.2.0";CAPTION_VERSION="3.1.0";HASHTAG_VERSION="1.1.1";ALT_VERSION="1.1.1";BUILDER_VERSION="3.0.0";PACKAGE_QA_VERSION="3.0.0"
LANGUAGES={"en":"English","ar":"Arabic","ku":"Kurdish Sorani"}
ALLOWED_CTAS={"Learn more at domuserbil.com","Explore the project","Request details","Contact Domus Erbil","Discover more"}
CLAIM_TERMS=re.compile(r"\b(?:ROI|rental yield|payment plan|discount|limited time|guaranteed return|price|availability|completion date)\b",re.I)
INTERNAL_LANGUAGE=re.compile(r"without adding unverified claims|based on approved source material|this image has been validated|no unsupported room claims|according to the source file|verified asset|source-supported visual",re.I)
ALT_MARKETING=re.compile(r"dream|best investment|luxury opportunity|learn more|discover more|contact us|request details",re.I)


class PostPackagePipeline:
    def __init__(self,project:str,root:Path,languages:tuple[str,...]=("en",))->None:
        self.project,self.root,self.languages=project,root,tuple(dict.fromkeys(languages or ("en",)))
        if any(code not in LANGUAGES for code in self.languages):raise ValueError("Unsupported language code. Use en, ar, or ku.")
        out=root/"output";self.output=out;self.group_path=out/"content-groups"/f"{project}-content-groups.json";self.caption_path=out/"captions"/f"{project}-captions.json";self.hashtag_path=out/"hashtags"/f"{project}-hashtags.json";self.alt_path=out/"alt-text"/f"{project}-alt-text.json";self.package_path=out/"post-packages"/f"{project}-post-packages.json";self.qa_path=out/"qa"/f"{project}-post-package-qa.json"

    def _context(self)->dict[str,Any]:
        paths={"manifest":self.output/"production-manifests"/f"{self.project}-branded-production-manifest.json","branded_qa":self.output/"qa"/f"{self.project}-branded-image-qa.json","creative_qa":self.output/"qa"/f"{self.project}-creative-visual-qa.json","knowledge":self.output/"knowledge"/f"{self.project}.json","strategy":self.output/"strategy"/f"{self.project}-strategy.json","campaign":self.output/"campaigns"/f"{self.project}-campaign-plan.json","content":self.output/"content"/f"{self.project}-content-plan.json","opportunities":self.output/"visual-opportunities"/f"{self.project}-visual-opportunities.json","provenance":self.output/"provenance"/f"{self.project}-provenance-audit.json","assets":self.output/"asset-intelligence"/f"{self.project}-asset-intelligence.json","config":self.root/"input"/"brand"/"brand-config.json","plans":self.output/"brand-composition-plans"/f"{self.project}-brand-composition-plans.json"}
        missing=[str(p) for p in paths.values() if not p.is_file()]
        # Older fixtures predate asset intelligence; visual fallbacks remain deterministic.
        if paths["assets"] in [Path(x) for x in missing]:missing.remove(str(paths["assets"]));data_assets={"assets":[]}
        else:data_assets=None
        if missing:raise ValueError("Post-package inputs missing: "+", ".join(missing))
        data={key:(_read(path) if path.is_file() else data_assets) for key,path in paths.items()};validate_project_context(self.project,{key:value for key,value in data.items() if key!="config"});require_canonical_graph(data["knowledge"],expected_project=self.project);d2_fingerprint=canonical_graph_fingerprint(data["knowledge"]);require_lineage(data["content"],expected_stage="department3-content-plan",canonical_fingerprint=d2_fingerprint);data["d2_fingerprint"]=d2_fingerprint;data["content_fingerprint"]=str(data["content"].get("artifact_fingerprint") or artifact_fingerprint(data["content"]));config=data["config"];approval=config.get("approval",{})
        plan_path=self.output/"plan-intelligence"/f"{self.project}-plan-intelligence.json";data["plan_intelligence"]=_read(plan_path) if plan_path.is_file() else {"project_id":self.project,"assets":[]}
        data["assets"]["assets"]=load_visual_reviews(self.root,data["assets"].get("assets",[]))
        if approval.get("status")!="approved" or not approval.get("locked") or approved_config_hash(config)!=approval.get("approved_config_hash"):raise ValueError("Post-package layer blocked: brand lock is stale.")
        if run_brand_readiness_validator(self.root).report["readiness_status"] not in {"ready","ready_with_warnings"}:raise ValueError("Post-package layer blocked: brand readiness invalid.")
        releases=sorted((self.output/"releases"/self.project).glob("release-*/manifest.json"),reverse=True)
        if not releases:raise ValueError("Post-package layer requires a current eligible release.")
        current_ids={x.get("branded_item_id") for x in data["manifest"].get("items",[])}
        release=next((_read(path) for path in releases if _read(path).get("status") in {"completed","completed_with_warnings"} and
                      {_x.get("branded_item_id") for _x in _read(path).get("released_items",[])} <= current_ids and _read(path).get("released_items")),None)
        if not release:raise ValueError("Post-package layer requires a successful release linked to current branded outputs.")
        validate_project_context(self.project,{"release":release});data["release"]=release;return data

    def _eligibility(self,ctx:dict[str,Any])->tuple[list[dict[str,Any]],list[dict[str,Any]]]:
        bqa={x["branded_item_id"]:x for x in ctx["branded_qa"].get("items",[])};cqa={x["branded_item_id"]:x for x in ctx["creative_qa"].get("items",[])};prov={x["branded_item_id"]:x for x in ctx["provenance"].get("items",[])};released={x["branded_item_id"]:x for x in ctx["release"].get("released_items",[])};plans={x["branded_item_id"]:x for x in ctx["plans"].get("plans",[])}
        result=[];excluded=[]
        for item in ctx["manifest"].get("items",[]):
            identity=item.get("branded_item_id");image=Path(str(item.get("branded_image_path","")));trace=prov.get(identity,{});qa=bqa.get(identity,{});creative=cqa.get(identity,{})
            reasons=[]
            if identity not in released:reasons.append("not a member of the current successful release")
            if qa.get("status") not in {"production_ready","exceptional"}:reasons.append("branded QA is not eligible")
            if creative.get("status") not in {"good_minor_improvements","production_ready","exceptional"}:reasons.append("creative QA is not eligible or is linked to another identity")
            if trace.get("integrity_status") not in {"complete","complete_with_warnings"}:reasons.append("provenance is incomplete or linked to another identity")
            if identity not in plans:reasons.append("composition plan is linked to another identity")
            if not item.get("campaign_id") or not item.get("content_idea_id"):reasons.append("campaign/content identity is missing")
            if not image.is_file():reasons.append("branded image is missing")
            elif _sha(image)!=item.get("branded_image_hash"):reasons.append("branded image hash mismatch")
            if reasons:excluded.append({"branded_item_id":identity,"excluded":True,"reason":"; ".join(reasons),"responsible_stage":"content-grouping-analyzer"})
            else:result.append({**item,"plan":plans[identity],"provenance":trace,"release_item":released[identity],"release_id":ctx["release"]["release_id"]})
        return result,excluded

    def _eligible(self,ctx:dict[str,Any])->list[dict[str,Any]]:return self._eligibility(ctx)[0]

    def _stamp(self,ctx:dict[str,Any],stage:str,payload:dict[str,Any],parents:dict[str,str]|None=None)->dict[str,Any]:
        base={"content_plan":ctx["content_fingerprint"],**(parents or {})}
        return attach_lineage(payload,stage=stage,canonical_fingerprint=ctx["d2_fingerprint"],parents=base)


    def groups(self)->Path:
        ctx=self._context();eligible,excluded=self._eligibility(ctx);content={x.get("content_idea_id"):x for x in ctx["content"].get("content_ideas",[])};buckets:dict[tuple[str,...],list[dict[str,Any]]]={}
        allowed={str(x).casefold() for x in ctx["content"].get("allowed_channels",["instagram","facebook"])}
        for item in eligible:
            plan=item.get("plan",{});platform=str(item.get("platform") or plan.get("platform") or "Instagram Feed");key=(str(item.get("campaign_id") or ""),str(item.get("content_idea_id") or ""),platform.casefold(),item["release_id"])
            channel="facebook" if "facebook" in platform.casefold() else "website" if "website" in platform.casefold() or "banner" in platform.casefold() else "instagram"
            if channel not in allowed:
                excluded.append({"branded_item_id":item["branded_item_id"],"excluded":True,"reason":f"destination channel '{channel}' is not allowed","responsible_stage":"content-grouping-analyzer"});continue
            buckets.setdefault(key,[]).append(item)
        groups=[];prevented=0
        for key,members in buckets.items():
            idea=content.get(members[0].get("content_idea_id"),{});platform=str(members[0].get("platform") or members[0].get("plan",{}).get("platform") or "Instagram Feed");formats={str(x.get("plan",{}).get("format") or platform).casefold() for x in members}
            intent=str(members[0].get("publication_type") or idea.get("selected_format") or (idea.get("planned_publication") or {}).get("publication_type") or "")
            story=intent=="story" or "story" in platform.casefold()
            carousel=not story and len(members)>=2 and (intent=="carousel" or "carousel" in platform.casefold() or any("carousel" in x for x in formats))
            if story and len(members)!=1:
                excluded.extend({"branded_item_id":x["branded_item_id"],"excluded":True,"reason":"V1 Story requires exactly one certified image","responsible_stage":"content-grouping-analyzer"} for x in members);continue
            group_type="story_sequence" if story else "carousel" if carousel else "single_post" if len(members)==1 else "campaign_sequence"
            ordered=sorted(members,key=lambda x:_order_key(x,idea));prevented+=len(members)-1 if group_type=="carousel" else 0
            for code in self.languages:
                groups.append({"content_group_id":_stable("group",*key,code),"group_type":group_type,"campaign_id":members[0].get("campaign_id"),"master_concept_id":idea.get("master_concept_id") or members[0].get("campaign_id"),"variant_id":_stable("variant",idea.get("master_concept_id") or members[0].get("campaign_id"),platform),"content_idea_id":members[0].get("content_idea_id"),"release_id":members[0]["release_id"],"platform":platform,"language":LANGUAGES[code],"language_code":code,"branded_item_ids":[x["branded_item_id"] for x in ordered],"ordered_slide_ids":[x["branded_item_id"] for x in ordered],"master_caption_required":group_type=="carousel","slide_specific_text_allowed":group_type in {"carousel","story_sequence"},"shared_hashtag_set":group_type=="carousel","shared_cta":group_type=="carousel","content_purpose":idea.get("content_objective") or idea.get("title") or "Present the visible project subject.","warnings":[]})
        grouped_ids={identity for group in groups for identity in group["branded_item_ids"]};considered=len(ctx["manifest"].get("items",[]));excluded_ids={x["branded_item_id"] for x in excluded}
        if considered!=len(grouped_ids)+len(excluded_ids):raise ValueError("Content grouping accounting invariant failed: every branded input must be grouped or excluded exactly once.")
        if eligible and not groups:raise ValueError(f"{len(eligible)} eligible branded outputs exist but none could be linked into content groups.")
        counts={kind:sum(x["group_type"]==kind for x in groups if x["language_code"]==self.languages[0]) for kind in ("single_post","carousel","story_sequence","campaign_sequence")}
        reasons={reason:sum(x["reason"]==reason for x in excluded) for reason in sorted({x["reason"] for x in excluded})}
        _write(self.group_path,self._stamp(ctx,"post-package-groups",{"project_id":self.project,"grouping_version":GROUPING_VERSION,"status":"completed" if groups else "no_content","languages":list(self.languages),"groups":groups,"branded_inputs_considered":considered,"grouped_items":len(grouped_ids),"excluded_items":excluded,"exclusions_by_reason":reasons,"summary":{**counts,"branded_inputs_considered":considered,"grouped_items":len(grouped_ids),"excluded_items":len(excluded),"exclusions_by_reason":reasons,"duplicate_packages_prevented":prevented},"created_at":_now()}));return self.group_path

    def captions(self)->Path:
        ctx=self._context();groups=_read(self.group_path) if self.group_path.is_file() else _read(self.groups());eligible={x["branded_item_id"]:x for x in self._eligible(ctx)};items=[]
        for group in groups.get("groups",[]):
            members=[eligible[x] for x in group["ordered_slide_ids"] if x in eligible];facts=_retrieve_facts(group,members,ctx);items.append(_caption_record(self.project,group,members,facts,ctx))
        if groups.get("groups") and not items:raise ValueError(f"{len(groups['groups'])} content groups exist but Caption Generator produced no captions.")
        for caption in items:
            idea=next((i for i in ctx["content"].get("content_ideas",[]) if i.get("content_idea_id")==caption.get("content_idea_id")),{})
            if role(idea.get("content_category"))!="project_site_plan":continue
            ids={a for member in eligible.values() if member.get("branded_item_id") in caption.get("branded_item_ids",[]) for a in member.get("source_asset_ids",[])}
            decisions=[assess_visual_purpose(a,"project_site_plan",self.project) for a in ctx["assets"].get("assets",[]) if a.get("asset_id") in ids]
            if any(d.get("representation")=="architectural_illustration" for d in decisions):
                if caption.get("language_code")!="en":raise ValueError("Illustrated project layout requires reviewed translation")
                disclosure="Project brochure illustration; not a measured site drawing"
                caption["full_caption"]=f"Explore the project layout of {self.project}.\n\nThis aerial illustration introduces the arrangement of the development.\n\n{disclosure}.\n\nLearn more at domuserbil.com"
        _differentiate_captions(items)
        from src.post_package.editorial_copy import apply_copy
        apply_copy(self.root,self.project,items,eligible,ctx)
        grounded=sum(bool(x["verified_fact_refs"]) for x in items);carousel=sum(x["package_type"]=="carousel" for x in items)
        groups_payload=_read(self.group_path)
        _write(self.caption_path,self._stamp(ctx,"post-package-captions",{"project_id":self.project,"caption_version":CAPTION_VERSION,"languages":list(self.languages),"items":items,"summary":{"captions_created":len(items),"carousel_master_captions":carousel,"visual_only_captions":len(items)-grounded,"fact_grounded_captions":grounded,"unsupported_claims_removed":0},"created_at":_now()},parents={"groups":str(groups_payload.get("artifact_fingerprint") or artifact_fingerprint(groups_payload))}));return self.caption_path

    def hashtags(self)->Path:
        ctx=self._context();items=[];location=_verified_location(ctx["knowledge"]);project_name=_project_name(ctx["knowledge"])
        for caption in _read(self.caption_path).get("items",[]):
            platform=str(caption.get("platform") or "instagram feed").casefold();minimum,maximum=(5,10) if "instagram" in platform and "story" not in platform else (0,2) if "story" in platform else (3,5) if "linkedin" in platform else (0,4)
            asset_types=set(caption.get("asset_types",[]));candidates=[("#DomusErbil","brand"),(_safe_tag(project_name,project=True),"project")]
            if location and "erbil" in location.casefold():candidates += [("#Erbil","location"),("#ErbilRealEstate","location")]
            candidates += [("#RealEstate","property_type")]
            if "floorplan" in asset_types:candidates += [("#FloorPlan","content_theme"),("#PropertyLayout","content_theme")]
            elif "exterior" in asset_types:candidates += [("#Architecture","content_theme"),("#FacadeDesign","content_theme")]
            elif "interior" in asset_types:candidates += [("#InteriorDesign","content_theme")]
            clean=[];removed=0
            for tag,kind in candidates:
                if not tag or not _valid_tag(tag,project_name):removed+=1;continue
                if tag.casefold() not in {x["hashtag"].casefold() for x in clean}:clean.append({"hashtag":tag,"group":kind})
            chosen=clean[:maximum] if len(clean)>=minimum else clean
            items.append({"hashtag_set_id":_stable("hashtags",caption["caption_id"]),"caption_id":caption["caption_id"],"content_group_id":caption["content_group_id"],"language":caption["language"],"platform":caption["platform"],"hashtags":chosen,"count":len(chosen),"malformed_hashtags_removed":removed,"unsupported_hashtags_removed":0,"warnings":[]})
        captions_payload=_read(self.caption_path)
        _write(self.hashtag_path,self._stamp(ctx,"post-package-hashtags",{"project_id":self.project,"hashtag_version":HASHTAG_VERSION,"items":items,"summary":{"sets_created":len(items),"malformed_hashtags_removed":sum(x["malformed_hashtags_removed"] for x in items),"unsupported_hashtags_removed":sum(x["unsupported_hashtags_removed"] for x in items)},"created_at":_now()},parents={"captions":str(captions_payload.get("artifact_fingerprint") or artifact_fingerprint(captions_payload))}));return self.hashtag_path

    def alt_text(self)->Path:
        ctx=self._context();assets={x.get("asset_id"):x for x in ctx["assets"].get("assets",[])};items=[];seen:dict[tuple[str,str],int]={}
        for creative in self._eligible(ctx):
            source_ids=creative.get("source_asset_ids",[]);semantic=next((assets[x] for x in source_ids if x in assets),{});asset_type=str(semantic.get("asset_type") or creative.get("plan",{}).get("asset_type") or "project image")
            for code in self.languages:
                text=_semantic_alt(asset_type,semantic,code,creative);key=(code,_normalize(text));occurrence=seen.get(key,0);seen[key]=occurrence+1
                if occurrence:text=_differentiate_alt(text,semantic,creative,occurrence)
                items.append({"alt_text_id":_stable("alt",creative["branded_item_id"],code),"branded_item_id":creative["branded_item_id"],"language":LANGUAGES[code],"language_code":code,"asset_type":asset_type,"alt_text":text[:300],"character_count":len(text[:300]),"visual_evidence_refs":source_ids,"semantic_context":_semantic_summary(semantic),"warnings":[]})
        from src.post_package.editorial_copy import apply_copy
        apply_copy(self.root,self.project,items,{x["branded_item_id"]:x for x in self._eligible(ctx)},ctx,alt=True)
        _write(self.alt_path,self._stamp(ctx,"post-package-alt-text",{"project_id":self.project,"alt_text_version":ALT_VERSION,"items":items,"summary":{"items_created":len(items),"asset_specific_descriptions":len(items),"duplicate_descriptions_repaired":sum(v-1 for v in seen.values() if v>1)},"created_at":_now()}));return self.alt_path

    def build(self)->Path:
        ctx=self._context();eligible={x["branded_item_id"]:x for x in self._eligible(ctx)};captions=_read(self.caption_path).get("items",[]);hashtags={x["caption_id"]:x for x in _read(self.hashtag_path).get("items",[])};alts={(x["branded_item_id"],x["language_code"]):x for x in _read(self.alt_path).get("items",[])};packages=[]
        for caption in captions:
            members=[eligible[x] for x in caption["branded_item_ids"] if x in eligible];tagset=hashtags.get(caption["caption_id"],{});common={"package_id":_stable("package",caption["caption_id"],caption["release_id"]),"package_type":caption["package_type"],"project_id":self.project,"release_id":caption["release_id"],"content_group_id":caption["content_group_id"],"platform":caption["platform"],"destination":caption["platform"],"master_concept_id":caption.get("master_concept_id") or caption.get("campaign_id"),"variant_id":caption.get("variant_id"),"language":caption["language"],"language_code":caption["language_code"],"campaign_id":caption.get("campaign_id"),"content_idea_id":caption.get("content_idea_id"),"hashtags":tagset.get("hashtags",[]),"CTA":caption["CTA"],"verified_fact_refs":caption["verified_fact_refs"],"selected_facts":caption["selected_facts"],"brand_config_hash":members[0].get("brand_config_hash") if members else None,"public_copy":members[0].get("public_copy") if members else {},"media_type":"image","media_count":len(members),"creative_production_contract_version":CONTRACT_VERSION,"creative_production_authority":"production-manifest -> brand-composer -> creative QA -> release-manager -> post-package QA","created_at":_now()}
            idea=next((i for i in ctx["content"].get("content_ideas",[]) if i.get("content_idea_id")==caption.get("content_idea_id")),{})
            category=caption.get("editorial_publication_role") or idea.get("content_category") or idea.get("canonical_category") or idea.get("category")
            asset_ids={a for m in members for a in m.get("source_asset_ids",[])}
            kinds={r.get("asset_type") for r in ctx.get("assets",{}).get("assets",[]) if r.get("asset_id") in asset_ids}
            if not category:
                category="unit_layout" if any(r.get("asset_id") in asset_ids for r in ctx.get("plan_intelligence",{}).get("assets",[]) if r.get("marketing_eligible")) else "site_plan" if kinds and kinds<={"site_plan","masterplan"} else "other"
            if role(category)=="project_site_plan" and (not kinds or not kinds<={"site_plan","masterplan"}):
                raise ValueError("Project site plan requires actual site/masterplan assets, not location or unit plans")
            if role(category)=="project_overview" and kinds & {"unit_layout","villa_layout","apartment_layout"}:
                raise ValueError("A unit layout cannot substitute for the project overview")
            purpose_decisions=[]
            if role(category) in {"project_overview","project_site_plan"}:
                records=[a for a in ctx.get("assets",{}).get("assets",[]) if a.get("asset_id") in asset_ids]
                if {a.get("asset_id") for a in records}!=asset_ids:raise ValueError("Missing exact source assets for opening post")
                if role(category)=="project_overview":
                    by_id={a["asset_id"]:a for a in records}
                    ordered=[by_id[a] for m in members for a in m.get("source_asset_ids",[])]
                    failures=validate_overview_slides(ordered,self.project)
                    if failures:raise ValueError(str(failures))
                purpose_decisions=[assess_visual_purpose(a,category,self.project,allow_support=role(category)=="project_overview") for a in records]
                if any(d["status"]!="MATCH" for d in purpose_decisions):raise ValueError("Visual purpose mismatch or review required: "+str(purpose_decisions))
            common["visual_selection_decisions"]=purpose_decisions
            common["project_sequence"]=contract(category)
            from src.project_sequence import campaign_scope
            scope=campaign_scope(self.root,self.project)
            if scope:common["campaign_scope"]=scope
            if caption["package_type"] in {"carousel","story"}:
                slides=[_slide(x,i+1,alts.get((x["branded_item_id"],caption["language_code"]),{}),caption) for i,x in enumerate(members)];package={**common,"master_caption":caption,"slides":slides,"status":"ready_with_warnings" if any(x["provenance"].get("warnings") for x in members) else "ready"}
            else:
                x=members[0];alt=alts.get((x["branded_item_id"],caption["language_code"]),{});prov=_provenance_fields(x);package={**common,"branded_item_id":x["branded_item_id"],"caption":caption,"alt_text":alt.get("alt_text"),"image":{"branded_item_id":x["branded_item_id"],"image_path":x["branded_image_path"],"image_hash":x["branded_image_hash"]},**prov,"visual_evidence_refs":caption["visual_evidence_refs"],"status":"ready_with_warnings" if x["provenance"].get("warnings") else "ready"}
            _write(self.output/"post-packages"/self.project/f"{package['package_id']}.json",package);packages.append(package)
        groups=_read(self.group_path).get("groups",[])
        if (groups or captions) and not packages:raise ValueError(f"{len(groups)} content groups and {len(captions)} captions exist but Post Package Builder produced no packages.")
        status="completed" if packages else "intentionally_empty" if _read(self.group_path).get("intentional_empty") is True else "no_content_unexpected"
        captions_payload=_read(self.caption_path);hashtags_payload=_read(self.hashtag_path);alt_payload=_read(self.alt_path)
        parents={"captions":str(captions_payload.get("artifact_fingerprint") or artifact_fingerprint(captions_payload)),"hashtags":str(hashtags_payload.get("artifact_fingerprint") or artifact_fingerprint(hashtags_payload)),"alt_text":str(alt_payload.get("artifact_fingerprint") or artifact_fingerprint(alt_payload))}
        payload=self._stamp(ctx,"post-package-manifest",{"project_id":self.project,"builder_version":BUILDER_VERSION,"status":status,"semantic_manifest_valid":status in {"completed","intentionally_empty"},"intentional_empty":status=="intentionally_empty","languages":list(self.languages),"packages":packages,"summary":{"packages_created":len(packages),"single_posts":sum(x["package_type"]=="single_post" for x in packages),"carousels":sum(x["package_type"]=="carousel" for x in packages),"stories":sum(x["package_type"]=="story" for x in packages),"total_images_represented":sum(len(x.get("slides",[])) or 1 for x in packages)},"created_at":_now()},parents=parents)
        _write(self.package_path,payload);return self.package_path

    def qa(self)->Path:
        ctx=self._context();package_payload=_read(self.package_path);require_lineage(package_payload,expected_stage="post-package-manifest",canonical_fingerprint=ctx["d2_fingerprint"]);packages=package_payload.get("packages",[]);results=[];corrections=[]
        for package in packages:
            result=_qa_package(package,ctx);results.append(result)
            if result["status"]=="blocked":
                route=_route_errors(result["errors"]);corrections.append({"correction_id":_stable("text-correction",package["package_id"],"1"),"package_id":package["package_id"],"responsible_stage":route,"attempt":1,"maximum_attempts":2,"image_production_touched":False,"created_at":_now()})
        counts={s:sum(x["status"]==s for x in results) for s in ("exceptional","ready","ready_with_warnings","blocked")}
        status="completed" if results else "no_content"
        _write(self.qa_path,self._stamp(ctx,"post-package-qa",{"project_id":self.project,"package_qa_version":PACKAGE_QA_VERSION,"status":status,"items":results,"corrections":corrections,"summary":{**counts,"status":status,"average_score":round(sum(x["score"] for x in results)/len(results),1) if results else None},"created_at":_now()},parents={"post_packages":str(package_payload.get("artifact_fingerprint") or artifact_fingerprint(package_payload))}));return self.qa_path


def _caption_record(project:str,group:dict[str,Any],members:list[dict[str,Any]],facts:dict[str,Any],ctx:dict[str,Any])->dict[str,Any]:
    code=group["language_code"];asset_types=[str(x.get("plan",{}).get("asset_type") or "project image") for x in members];carousel=group["group_type"]=="carousel";story=group["group_type"]=="story_sequence";subject=_subject(asset_types,carousel);identity=canonical_project_identity(ctx["knowledge"],expected_project=project);project_name=str(identity.get("project_name") or project);developer=str(identity.get("developer_name") or "");headline=_headline(subject,code,carousel);body=_caption_body(subject,code,carousel,len(members),facts["selected_facts"]);context=" — ".join(x for x in (project_name, f"developed by {developer}" if developer else "") if x) if code=="en" else project_name;body=f"{context}. {body}" if context else body;cta=_cta(code);full=f"{headline}\n\n{body}\n\n{cta}".strip()
    unit_values=[f["value"] for f in facts["selected_facts"] if f.get("category")=="unit_plan"]
    if unit_values:
        if code!="en":raise ValueError("Canonical unit caption translation requires a tested language adapter")
        headline=f"{project_name} — {unit_values[0]} villa layout"
        body=" · ".join(unit_values[1:])+".\nSwipe through the complete ground-floor and first-floor plans.\nSource: project brochure. Figures reflect the brochure."
        full=f"{headline}\n\n{body}\n\n{cta}"
        asset_types=["floorplan"]*len(members)
    idea=next((i for i in ctx["content"].get("content_ideas",[]) if i.get("content_idea_id")==group.get("content_idea_id")),{})
    if code=="en" and carousel and role(idea.get("content_category"))=="project_overview":
        headline=f"Introducing {project_name}."
        body="Swipe through the project overview: daylight and night perspectives, followed by a closer aerial view and the entrance with its central landscape.\nThese illustrations come from the project brochure."
        full=f"{headline}\n\n{body}\n\n{cta}"
    if code=="en" and carousel and role(idea.get("content_category"))=="community_lifestyle":
        headline=f"Community and everyday life — {project_name}"
        body="Explore the community and lifestyle themes presented in the project brochure. Swipe through its outdoor-space and recreation imagery.\nBrochure lifestyle imagery; these images do not confirm completed facilities."
        full=f"{headline}\n\n{body}\n\n{cta}"
    registry=_caption_registry(ctx,project,{a for m in members for a in m.get("source_asset_ids",[])});claims=[];identity_fact=next((x for x in registry.values() if x.get("path")=="project_identity.project_name" and str(x.get("value"))==project_name),None)
    if project_name and identity_fact:claims.append(make_claim(project_name,"project_identity",[identity_fact["fact_id"]]))
    for selected in facts["selected_facts"]:claims.append(make_claim(str(selected["value"]),str(selected.get("category") or "project_fact"),[selected["fact_ref"]]))
    refs=list(dict.fromkeys(y for x in claims for y in x["supporting_fact_ids"]))
    if story: full="";body="";cta="" # Story copy is rendered under the signed public-copy contract, never fabricated as a feed caption.
    return {"caption_id":_stable("caption",group["content_group_id"],CAPTION_VERSION),"content_group_id":group["content_group_id"],"package_type":"carousel" if carousel else "story" if story else "single_post","project_id":project,"release_id":group["release_id"],"branded_item_ids":group["branded_item_ids"],"campaign_id":group.get("campaign_id"),"content_idea_id":group.get("content_idea_id"),"language":LANGUAGES[code],"language_code":code,"text_direction":"rtl" if code in {"ar","ku"} else "ltr","platform":"instagram" if story else group["platform"],"headline":headline,"body":body,"CTA":cta,"full_caption":full,"verified_fact_refs":refs,"selected_facts":facts["selected_facts"],"claims":claims,"grounding_version":GROUNDING_VERSION,"fact_relevance_scores":facts["fact_relevance_scores"],"excluded_facts":facts["excluded_facts"],"exclusion_reasons":facts["exclusion_reasons"],"visual_evidence_refs":[a for x in members for a in x.get("source_asset_ids",[])],"asset_types":asset_types,"tone":["professional","premium","clear","natural"],"word_count":len(full.split()),"character_count":len(full),"confidence":.94,"warnings":[]}

def _retrieve_facts(group:dict[str,Any],members:list[dict[str,Any]],ctx:dict[str,Any])->dict[str,Any]:
    idea=next((x for x in ctx["content"].get("content_ideas",[]) if x.get("content_idea_id")==group.get("content_idea_id")),{});refs=list(dict.fromkeys([*idea.get("selected_fact_refs",[]),*idea.get("factual_evidence",[]),*(r for m in members for r in m.get("plan",{}).get("verified_fact_refs",[]))]));selected=[];excluded=[];reasons={};scores={};asset_types={str(x.get("plan",{}).get("asset_type","")).casefold() for x in members}
    source_ids={str(asset_id) for member in members for asset_id in member.get("source_asset_ids",[])};layout_records=[x for x in ctx.get("plan_intelligence",{}).get("assets",[]) if str(x.get("asset_id")) in source_ids and x.get("asset_type") in UNIT_TYPES]
    if layout_records:
        allowed={str(e.get("fact_id") or e.get("fact_ref")) for record in layout_records if record.get("relationship_status")=="VERIFIED" for values in record.get("evidence",{}).values() for e in values if isinstance(e,dict) and (e.get("fact_id") or e.get("fact_ref"))}
        rejected=[ref for ref in refs if str(ref) not in allowed];excluded.extend(rejected);reasons.update({str(ref):"project-level fact is not linked to this exact layout" for ref in rejected});refs=[ref for ref in refs if str(ref) in allowed]
    project=str(ctx["manifest"].get("project_id"));unit_facts=canonical_unit_facts(ctx.get("plan_intelligence",{}),project,source_ids);registry=authoritative_facts(ctx["knowledge"],project);by_path={x["path"]:x for x in registry.values()}
    for ref in refs:
        fact=registry.get(ref) or by_path.get(ref);value=fact.get("value") if fact else None
        if value is None:excluded.append(ref);reasons[ref]="fact reference does not resolve to authoritative current-project intelligence";continue
        text=_fact_text(value)
        if not text:excluded.append(ref);reasons[ref]="fact is not suitable customer-facing text";continue
        conflict="conflict" in str(value).casefold() or "unverified" in str(value).casefold();fact_words=set(re.findall(r"[a-z0-9]+",text.casefold()));relevant=bool(fact_words & _relevance_words(asset_types,idea))
        if conflict:excluded.append(ref);reasons[ref]="conflicting or unverified fact";continue
        if CLAIM_TERMS.search(text):excluded.append(ref);reasons[ref]="restricted fact class requires explicit claim verification";continue
        if not relevant:excluded.append(ref);reasons[ref]="not directly relevant to the selected visual";continue
        fact_id=fact["fact_id"];scores[fact_id]=.9;selected.append({"fact_ref":fact_id,"value":text,"category":fact["category"],"evidence":fact["evidence"],"relevance_score":.9})
    selected.extend({"fact_ref":f["fact_id"],"value":f["value"],"category":f["category"],"evidence":f["evidence"],"relevance_score":1.0} for f in unit_facts.values());
    return {"verified_fact_refs":[x["fact_ref"] for x in selected[:4]],"selected_facts":selected[:4],"fact_relevance_scores":scores,"excluded_facts":excluded,"exclusion_reasons":reasons}

def _provenance_fields(item:dict[str,Any])->dict[str,Any]:
    trace=item["provenance"];pid=trace.get("provenance_id") or _stable("provenance",item["branded_item_id"],trace.get("final_output_hash",""))
    return {"provenance_id":pid,"final_output_hash":trace.get("final_output_hash"),"source_asset_ids":trace.get("source_assets",[]),"source_document_refs":trace.get("source_documents",[]),"source_pages":trace.get("source_pages",[]),"provenance_verified_fact_refs":trace.get("verified_fact_refs",[]),"brand_config_hash":item.get("brand_config_hash"),"release_id":item["release_id"]}

def _slide(item:dict[str,Any],number:int,alt:dict[str,Any],caption:dict[str,Any])->dict[str,Any]:
    return {"slide_number":number,"slide_role":"cover" if number==1 else "supporting","branded_item_id":item["branded_item_id"],"image_path":item["branded_image_path"],"image_hash":item["branded_image_hash"],"alt_text":alt.get("alt_text"),"visual_evidence_refs":item.get("source_asset_ids",[]),"verified_fact_refs":caption["verified_fact_refs"],**_provenance_fields(item)}

def _qa_package(package:dict[str,Any],ctx:dict[str,Any])->dict[str,Any]:
    errors=validate_publication_package(package,expected_project=str(ctx["manifest"].get("project_id")));warnings=[];caption=package.get("master_caption") or package.get("caption") or {};tags=package.get("hashtags",[]);records=package.get("slides") or [{**package.get("image",{}),**{k:package.get(k) for k in ("branded_item_id","provenance_id","final_output_hash","source_asset_ids","source_document_refs","source_pages","release_id")},"alt_text":package.get("alt_text")}];provenance={x.get("branded_item_id"):x for x in ctx["provenance"].get("items",[])}
    errors.extend(validate_package_layouts(package,ctx.get("plan_intelligence",{}),expected_project=str(ctx["manifest"].get("project_id"))))
    if package.get("project_id")!=ctx["manifest"].get("project_id"):errors.append("wrong project or cross-project source trace")
    if INTERNAL_LANGUAGE.search(caption.get("full_caption","")):errors.append("compliance language exposed in caption")
    if CLAIM_TERMS.search(caption.get("full_caption","")):errors.append("unsupported factual claim in caption")
    grounding=validate_claims(caption,_caption_registry(ctx,str(ctx["manifest"].get("project_id")),{a for r in records for a in r.get("source_asset_ids",[])}),str(ctx["manifest"].get("project_id")));errors.extend(x["reason"] for x in grounding["diagnostics"])
    identity=canonical_project_identity(ctx["knowledge"],expected_project=str(ctx["manifest"].get("project_id")));comprehension=assess_marketing_comprehension(text=caption.get("full_caption",""),project_name=str(identity.get("project_name") or ctx["manifest"].get("project_id") or ""),developer_name=str(identity.get("developer_name") or ""),visual_category=str((caption.get("asset_types") or ["unknown"])[0]),verified_facts=caption.get("selected_facts",[]))
    warnings.extend(comprehension["warnings"])
    errors.extend(duplicate_copy_fields(caption.get("headline",""),caption.get("subtitle",""),caption.get("body","")))
    if comprehension["status"]=="fail" and package.get("package_type")!="story":errors.append("marketing comprehension failure")
    if package.get("language_code")=="en" and package.get("package_type")!="story" and package.get("CTA") not in ALLOWED_CTAS:errors.append("unsupported CTA")
    if package.get("package_type")=="story":
        from src.publication import validate_public_copy
        errors.extend(validate_public_copy(package.get("public_copy") or {}))
        if len(records)!=1:errors.append("V1 Story package must contain exactly one image")
    values=[x.get("hashtag","") for x in tags]
    if len({x.casefold() for x in values})!=len(values):errors.append("duplicate hashtags")
    if any(not _valid_tag(x,_project_name(ctx["knowledge"])) for x in values):errors.append("sentence-style malformed hashtag")
    alts=[]
    for record in records:
        identity=record.get("branded_item_id");trace=provenance.get(identity,{});image=Path(str(record.get("image_path","")));alts.append(str(record.get("alt_text") or ""))
        expected_id=trace.get("provenance_id") or _stable("provenance",identity,trace.get("final_output_hash",""))
        if not identity or not trace or record.get("provenance_id")!=expected_id:errors.append(f"invalid provenance for {identity}");continue
        if str(record.get("provenance_id"))==str(record.get("image_path")):errors.append("image path used as provenance reference")
        if not image.is_file() or _sha(image)!=record.get("image_hash") or record.get("final_output_hash")!=trace.get("final_output_hash"):errors.append(f"wrong output hash for {identity}")
        if set(record.get("source_asset_ids",[]))!=set(trace.get("source_assets",[])):errors.append(f"source asset mismatch for {identity}")
        if package.get("release_id")!=record.get("release_id"):errors.append(f"release mismatch for {identity}")
    if package.get("package_type")=="carousel" and len(records)<2:errors.append("carousel grouping invalid")
    if any(len(x)<40 or len(x)>300 or ALT_MARKETING.search(x) for x in alts):errors.append("alt text invalid or contains marketing language")
    if len(alts)>1 and len({_normalize(x) for x in alts})!=len(alts):errors.append("duplicate alt text")
    if package.get("brand_config_hash")!=approved_config_hash(ctx["config"]):errors.append("stale brand hash")
    weights={"factual_accuracy":20,"visual_copy_alignment":15,"caption_quality":15,"carousel_grouping_correctness":10,"hashtag_quality":10,"alt_text_quality":10,"provenance_integrity":15,"brand_platform_consistency":5};score=97 if not errors else max(0,79-10*(len(errors)-1));status="exceptional" if score>=95 else "ready" if score>=90 else "ready_with_warnings" if score>=80 else "blocked"
    return {"package_id":package.get("package_id"),"package_type":package.get("package_type"),"score":score,"status":status,"category_weights":weights,"marketing_comprehension":comprehension,"grounding":grounding,"warnings":list(dict.fromkeys(warnings)),"errors":list(dict.fromkeys(errors))}

def _semantic_alt(asset_type:str,semantic:dict[str,Any],code:str,item:dict[str,Any])->str:
    if code!="en":return ("صورة للمشروع تعرض المحتوى المعماري الظاهر مع شعار ونص بسيط." if code=="ar" else "وێنەی پرۆژە کە ناوەڕۆکی بینراوی تەلارسازی لەگەڵ لۆگۆ و دەقێکی سادە پیشان دەدات.")
    subject=str(semantic.get("dominant_subject") or "").strip();spaces=_strings(semantic.get("visible_spaces"));features=_strings(semantic.get("visible_project_features"));subtype=str(semantic.get("asset_subtype") or "").strip();details=[x for x in [subject,subtype,", ".join((spaces+features)[:3])] if x and x.casefold() not in {asset_type.casefold(),"unknown","none"}]
    kind={"floorplan":"floorplan graphic","masterplan":"masterplan graphic","exterior":"exterior architectural image","interior":"interior image","lifestyle":"lifestyle image"}.get(asset_type,"project image");extra=f" showing {', '.join(details)}" if details else " showing its visible composition and details";return f"Branded {kind}{extra}, with the Domus Erbil logo and restrained text overlay."

def _differentiate_alt(text:str,semantic:dict[str,Any],item:dict[str,Any],occurrence:int)->str:
    page=item.get("provenance",{}).get("source_pages",[]);detail=f" Source view {occurrence+1}"+(f" from page {page[0]}" if page else "")+".";return text.rstrip(".")+"."+detail
def _semantic_summary(value:dict[str,Any])->dict[str,Any]:return {k:value.get(k) for k in ("asset_type","asset_subtype","dominant_subject","visible_spaces","visible_project_features","visible_text_summary") if value.get(k)}
def _differentiate_captions(items:list[dict[str,Any]])->None:
    for i,item in enumerate(items):
        if item["package_type"]!="single_post":continue
        for prior in items[:i]:
            if prior["package_type"]=="single_post" and prior["language_code"]==item["language_code"] and SequenceMatcher(None,_normalize(prior["full_caption"]),_normalize(item["full_caption"])).ratio()>.80:
                base=re.sub(r"(?:\s+—\s+View\s+\d+)+$","",item["headline"]);item["headline"]=f"{base} — View {i+1}";item["full_caption"]=f"{item['headline']}\n\n{item['body']}\n\n{item['CTA']}";item["warnings"].append("caption diversified from another independent post");break

def _caption_body(subject:str,code:str,carousel:bool,count:int,facts:list[dict[str,Any]])->str:
    if code=="ar":return "يقدّم هذا العرض تفاصيل التصميم الظاهرة بوضوح عبر الصور." if carousel else "نظرة واضحة على تفاصيل التصميم الظاهرة في هذه الصورة."
    if code=="ku":return "ئەم زنجیرە وێنەیە وردەکارییە بینراوەکانی دیزاین بە ڕوونی پیشان دەدات." if carousel else "ڕوانینێکی ڕوون بۆ وردەکارییە بینراوەکانی دیزاین لەم وێنەیەدا."
    if carousel:base={"floorplan":f"This {count}-slide carousel presents the available plans together, offering a clearer view of their visible layouts and organization.","exterior":f"Explore {count} views of the architecture, with each slide focusing on visible form, materials, and facade character."}.get(subject,f"Explore the project across {count} coordinated views, each focused on visible design details.")
    else:base={"floorplan":"A closer look at the visible layout, plan organization, and circulation shown in this floorplan.","exterior":"A focused view of the architecture, facade composition, and relationship with its setting.","interior":"A closer look at the visible room arrangement, materials, and spatial character.","lifestyle":"A focused look at the visible activity and surrounding environment."}.get(subject,"A focused look at the visible design and architectural character.")
    if facts:base+=f" {facts[0]['value'].rstrip('.')}."
    return base
def _headline(subject:str,code:str,carousel:bool)->str:
    if code=="ar":return "اكتشف التفاصيل"; 
    if code=="ku":return "وردەکارییەکان ببینە"
    if carousel:return {"floorplan":"Explore the Plans in Detail","exterior":"Architecture from Every Angle"}.get(subject,"Explore the Details")
    return {"floorplan":"A Closer Look at the Layout","masterplan":"Explore the Site Plan","interior":"Inside the Design","exterior":"Architectural Character","lifestyle":"Life in the Setting"}.get(subject,"Discover the Design")
def _subject(types:list[str],carousel:bool)->str:return types[0].casefold() if len(set(x.casefold() for x in types))==1 else "project"
def _cta(code:str)->str:return {"ar":"اكتشف المزيد","ku":"زیاتر بدۆزەرەوە"}.get(code,"Learn more at domuserbil.com")
def _order_key(item:dict[str,Any],idea:dict[str,Any])->tuple[int,str]:
    selected=idea.get("selected_source_asset_ids",[]);source=next(iter(item.get("source_asset_ids",[])),"");return (selected.index(source) if source in selected else 999,item.get("branded_item_id",""))
def _resolve_ref(data:Any,ref:str)->Any:
    value=data
    for name,index in re.findall(r"([^.\[\]]+)(?:\[(\d+)\])?",str(ref)):
        if not isinstance(value,dict) or name not in value:return None
        value=value[name]
        if index:
            if not isinstance(value,list) or int(index)>=len(value):return None
            value=value[int(index)]
    return value
def _fact_text(value:Any)->str:
    if isinstance(value,str):return value.strip()
    if isinstance(value,(int,float)):return str(value)
    if isinstance(value,dict):
        for key in ("name","title","value","description","feature","claim"):
            if isinstance(value.get(key),str):return value[key].strip()
    return ""
def _relevance_words(asset_types:set[str],idea:dict[str,Any])->set[str]:
    words=set(asset_types)|set(re.findall(r"[a-z]{4,}",str(idea.get("title","")).casefold()))
    if "floorplan" in asset_types:words|={"layout","plan","floorplan","bedroom","room","space","circulation"}
    if "exterior" in asset_types:words|={"architecture","facade","exterior","design"}
    return words
def _strings(value:Any)->list[str]:
    if isinstance(value,str):return [value] if value.strip() else []
    if isinstance(value,list):return [str(x).strip() for x in value if str(x).strip()]
    return []
def _safe_tag(value:str,project:bool=False)->str|None:
    tag="#"+re.sub(r"[^A-Za-z0-9]+","",value)
    return tag if _valid_tag(tag,value if project else "") else None
def _valid_tag(tag:str,project_name:str)->bool:
    if not re.fullmatch(r"#[A-Za-z0-9]+",str(tag)):return False
    body=tag[1:];approved_project=re.sub(r"[^A-Za-z0-9]+","",project_name).casefold()==body.casefold()
    return len(body)<=30 or approved_project
def _route_errors(errors:list[str])->str:
    joined=" ".join(errors);return "content-grouping-analyzer" if "carousel" in joined or "grouping" in joined else "caption-generator" if "caption" in joined or "claim" in joined else "hashtag-generator" if "hashtag" in joined else "alt-text-generator" if "alt text" in joined else "post-package-builder"
def _project_name(knowledge:dict[str,Any])->str:
    return str(canonical_project_identity(knowledge).get("project_name") or "").strip()
def _verified_location(knowledge:dict[str,Any])->str|None:
    value=canonical_project_identity(knowledge).get("location");return str(value).strip() if value else None
def _normalize(value:str)->str:return re.sub(r"\s+"," ",re.sub(r"[^\w\s]"," ",str(value).casefold())).strip()
def _stable(prefix:str,*values:str)->str:return prefix+"_"+hashlib.sha256("|".join(str(x) for x in values).encode()).hexdigest()[:20]
def _sha(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda:source.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()
def _read(path:Path)->dict[str,Any]:return json.loads(path.read_text(encoding="utf-8"))
def _write(path:Path,value:Any)->None:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
def _now()->str:return datetime.now(timezone.utc).isoformat()


def _caption_registry(ctx,project,source_ids):
    registry=authoritative_facts(ctx["knowledge"],project)
    registry.update(canonical_unit_facts(ctx.get("plan_intelligence",{}),project,source_ids))
    return registry
