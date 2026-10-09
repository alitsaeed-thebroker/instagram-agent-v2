"""Department 3 canonical, knowledge-first content opportunity regressions."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.content.inventory import ContentOpportunityInventoryEngine, load_content_opportunity_inventory
from src.planning.engine import PlanningEngine, VisualOpportunityEngine


def evidence(document: str, *, page=None, line=None, paragraph=None, project="Rich Project"):
    import hashlib
    locator = page if page is not None else line if line is not None else paragraph
    evidence_id = "ev_" + hashlib.sha256(
        f"{project}|{document}|{locator}".encode("utf-8")
    ).hexdigest()[:20]
    return {
        "evidence_id": evidence_id,
        "source_document": document,
        "source_file": document,
        "source_page": page,
        "page": page,
        "line_range": line,
        "paragraph": paragraph,
        "source_project": project,
        "status": "verified",
        "support_status": "direct",
        "source_text": "verified source text",
        "extraction_method": "test_authoritative_fixture",
        "source_id": "src_fixture",
        "source_sha256": "fixture_hash",
    }


def visual(asset_id: str, kind: str, subject: str):
    return {"asset_id":asset_id,"asset_type":kind,"asset_subtype":kind,"dominant_subject":subject,
            "analysis_status":"analyzed","marketing_suitability":"hero_ready","confidence":.9,
            "quality_score":85,"image_quality":{"score":85},"recommended_platforms":["Instagram"],
            "orientation":"portrait","safe_crop_assessment":{"level":"flexible"},"project_id":"Rich Project",
            "source_document":"Catalogue.pdf","source_page":6,
            **({"contains_diagram":True,"plan_completeness_status":"COMPLETE","plan_legibility_status":"READABLE"} if kind in {"masterplan","site_plan"} else {})}


def rich_knowledge():
    commercial_evidence=evidence("Price List V03.pdf",page=3)
    return {
        "project_identity":{"project_name":"Rich Project","project_type":"Mixed-use community","location":"Erbil"},
        "project":{"name":"Rich Project","location":"Erbil"},
        "fact_provenance":{
            "project_identity.project_name":[evidence("Catalogue.pdf",page=1)],
            "project_identity.project_type":[evidence("Catalogue.pdf",page=2)],
            "project_identity.location":[evidence("project-notes.txt",line="2-3")],
        },
        "location":{"facts":[
            {"value":"Located on 120m Road","sources":[evidence("Catalogue.pdf",page=4)]},
            {"value":"Near Rashkin Park","sources":[evidence("pricing.docx",paragraph=7)]},
            {"value":"10 minutes from Erbil International Airport","sources":[evidence("Catalogue.pdf",page=5)]},
            {"value":"Located on 120m Road","sources":[evidence("Brochure.pdf",page=2)]},
        ]},
        "amenities":["Swimming pool","Fitness center","Children's area","Landscaped gardens"],
        "units":[{"name":"1-bedroom apartment"},{"name":"2-bedroom apartment"},{"name":"Office layout"}],
        "architecture":{"style":"Contemporary exterior","design_features":["Natural-light interiors"]},
        "commercial_intelligence":{
            "contract_role":"authoritative_project_intelligence",
            "project":"Rich Project",
            "pricing":{"status":"complete","facts":[
                {"fact_type":"price_per_sqm","value":850,"currency":"USD","qualifier":"per_sqm","status":"verified","source_project":"Rich Project","relationship_status":"project_scope","evidence":[commercial_evidence]},
                {"fact_type":"starting_price","value":144900,"currency":"USD","qualifier":"starting_from","status":"verified","source_project":"Rich Project","relationship_status":"scoped","relationship_context":{"unit_type":"apartment"},"evidence":[commercial_evidence]}
            ]},
            "payment_plan":{"status":"not_supported","installments":[],"reason":"payment_plan_intelligence_disabled_by_policy"},
            "payment_plans":[],
            "commercial_terms":[],
            "sources":[{"source_file":"Price List V03.pdf","document_type":"Price List","authority":94}],
        },
    }


def rich_visuals():
    assets=[visual("map","location_map","project access map"),visual("master","masterplan","full project masterplan"),
            visual("ext","exterior","tower exterior"),visual("int","interior","apartment living room"),
            visual("pool","amenity","swimming pool"),visual("gym","amenity","fitness center"),
            visual("one","floorplan","1-bedroom layout"),visual("two","floorplan","2-bedroom layout")]
    inventory={"project":"Rich Project","inventory_type":"semantic","all_source_asset_ids":[x["asset_id"] for x in assets],"available_text_facts":[]}
    fields={"location_map":"available_location_maps","masterplan":"available_masterplans","exterior":"available_exterior_images",
            "interior":"available_interior_images","amenity":"available_amenity_images","floorplan":"available_floorplans"}
    for asset in assets:inventory.setdefault(fields[asset["asset_type"]],[]).append(asset)
    return inventory


def canonicalize_test_knowledge(data:dict)->dict:
    """Migrate historical test fixtures to the production canonical contract."""
    import hashlib
    result=json.loads(json.dumps(data))
    identity=result.get("project_identity",{})
    project=str(identity.get("project_name") or result.get("project",{}).get("name") or "Rich Project")
    entity_id="project_"+hashlib.sha256(project.encode()).hexdigest()[:12]
    entities=[{"entity_id":entity_id,"entity_type":"project","project_namespace":project,"label":project,"parent_entity_id":None,"attributes":{}}]
    facts=[]

    def add(path,value,sources,*,currency=None,unit=None,commercial=False,relationship=None):
        if value in (None,"",[],{}):return
        direct=[]
        for source in sources if isinstance(sources,list) else []:
            if not isinstance(source,dict):continue
            status=str(source.get("support_status") or source.get("status") or "").casefold()
            if status in {"unsupported","rejected","conflicting","uncertain","inferred"}:continue
            if str(source.get("source_project") or project).casefold()!=project.casefold():continue
            if source.get("source_url"):
                if not (
                    source.get("domain")
                    and source.get("retrieval_timestamp")
                    and source.get("source_type")
                    and source.get("project_match") is True
                    and str(source.get("conflict_state") or "").casefold()=="resolved"
                ):
                    continue
            ev=dict(source)
            ev.setdefault("evidence_id","ev_"+hashlib.sha256(f"{project}|{path}|{value}|{len(direct)}".encode()).hexdigest()[:20])
            ev.setdefault("source_project",project);ev.setdefault("source_file",ev.get("source_document") or "fixture.pdf")
            ev.setdefault("source_document",ev.get("source_file"));ev.setdefault("source_id","src_fixture");ev.setdefault("source_sha256","hash_fixture");ev.setdefault("source_text",str(value));ev.setdefault("extraction_method","test_authoritative_fixture")
            if not any(ev.get(k) is not None for k in ("page","source_page","line_range","paragraph")):ev["page"]=1
            direct.append(ev)
        if not direct:return
        canonical_path={
            "project_identity.project_name":"project.project_name",
            "project_identity.project_type":"project.project_type",
            "project_identity.location":"project.location",
            "project_identity.developer_name":"project.developer_name",
        }.get(path,path)
        fid="fact_"+hashlib.sha256(f"{project}|{canonical_path}|{value}|{relationship}".encode()).hexdigest()[:16]
        facts.append({"fact_id":fid,"entity_id":entity_id,"fact_type":canonical_path,"value":value,"unit":unit,"currency":currency,
                      "state":"VERIFIED","confidence":1.0,"authority":90,"marketing_eligible":True,"provenance":direct,
                      "relationship_context":{"project_namespace":project,**(relationship or {})},"effective_date":None,"conflicts":[]})

    provenance=result.get("fact_provenance",{})
    for field in ("project_name","project_type","location","developer_name"):
        value=identity.get(field)
        add(f"project_identity.{field}",value,provenance.get(f"project_identity.{field}",[]))

    for idx,item in enumerate(result.get("location",{}).get("facts",[]) if isinstance(result.get("location"),dict) else []):
        add(f"location.facts[{idx}]",item.get("value"),item.get("sources",[]))

    default=evidence("Catalogue.pdf",page=6,project=project)
    for idx,value in enumerate(result.get("amenities",[]) or []):
        add("amenity.name",value,[default])
    for idx,unit_data in enumerate(result.get("units",[]) or []):
        label=unit_data.get("name")
        unit_sources=provenance.get(f"units[{idx}]",[])
        if label and unit_sources:add("unit.name",label,unit_sources,relationship={"unit_label":label})
    architecture=result.get("architecture",{})
    if architecture.get("style"):add("architecture.style",architecture["style"],[default])
    for value in architecture.get("design_features",[]) or []:add("architecture.design_features",value,[default])

    ci=result.get("commercial_intelligence",{})
    unresolved={str(x.get("fact_type")) for x in ci.get("conflicts",[]) if str(x.get("status") or "").casefold()!="resolved"}
    for fact in ci.get("pricing",{}).get("facts",[]) or []:
        kind=str(fact.get("fact_type") or "")
        if kind not in {"price_per_sqm","total_unit_price","starting_price"} or kind in unresolved:continue
        if str(fact.get("status") or "").casefold()!="verified":continue
        add(f"commercial.{kind}",fact.get("value"),fact.get("evidence",[]),currency=fact.get("currency"),unit=fact.get("unit"),commercial=True,relationship=fact.get("relationship_context") or {})

    result["canonical_intelligence"]={"project_namespace":project,"schema_version":"2.0.0","contract_role":"authoritative_department2_relational_intelligence",
        "entities":entities,"facts":facts,"conflicts":[],"unknowns":[],"metadata":{"fixture_migrated_for_phase7":True}}
    return result


class ContentOpportunityInventoryTests(unittest.TestCase):
    def test_reviewed_overview_cover_survives_advisory_review_required_and_support_cannot_stand_alone(self):
        import hashlib
        from src.planning.engine import _reserved_candidates
        root=Path(self.temp.name);out=root/"output"
        k=out/"knowledge/Rich Project.json";v=out/"visual-inventory/Rich Project.json";s=out/"strategy/Rich Project.json"
        for p in (k,v,s):p.parent.mkdir(parents=True,exist_ok=True)
        k.write_text(json.dumps(canonicalize_test_knowledge(rich_knowledge())),encoding="utf-8");s.write_text("{}")
        assets=[];reviews=[]
        for i in range(1,5):
            p=root/f"source-{i}.jpg";p.write_bytes(f"distinct fixture source {i}".encode())
            a={**visual(f"source-{i}","aerial_view","reviewed project rendering"),"project_id":"Rich Project","source_path":str(p),"source_hash":hashlib.sha256(p.read_bytes()).hexdigest(),"source_document_hash":"d"*64,"source_page":i,"analysis_status":"review_required" if i<4 else "analyzed"}
            assets.append(a)
            reviews.append({**{key:a[key] for key in ("asset_id","project_id","source_hash","source_document_hash","source_page")},"purpose":"project_overview","status":"APPROVED","scope":"whole_development" if i<3 else "project_context","sequence":i})
        review_path=root/"input/visual-review/project-overview-reviews.json";review_path.parent.mkdir(parents=True);review_path.write_text(json.dumps({"reviews":reviews}))
        v.write_text(json.dumps({"project_id":"Rich Project","available_exterior_images":assets}),encoding="utf-8")
        names=("VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY","CAMPAIGNS_OUTPUT_DIRECTORY","CONTENT_OUTPUT_DIRECTORY","ASSET_USAGE_OUTPUT_DIRECTORY","CONTENT_MEMORY_OUTPUT_DIRECTORY","REPORTS_OUTPUT_DIRECTORY")
        patches=[patch(f"src.planning.engine.{name}",out/name.lower()) for name in names]
        for entry in patches:entry.start()
        try:
            opp=VisualOpportunityEngine().run(k,v,s);payload=json.loads(opp.read_text(encoding="utf-8"))
            reservations={r["asset_id"]:r for r in payload["asset_reservations"]}
            self.assertEqual(reservations["source-1"]["allowed_purposes"],["project_overview"])
            self.assertEqual(_reserved_candidates(["source-1"],{"source-1":assets[0]},{},reservations,purpose="exterior"),[])
            result=PlanningEngine().run(k,s,v,opp);content=json.loads(result["content_plan"].read_text(encoding="utf-8"))
            intro=next(i for i in content["content_ideas"] if i["content_category"]=="project_overview")
            self.assertEqual(intro["selected_source_asset_ids"],[f"source-{i}" for i in range(1,5)])
            self.assertEqual(intro["selected_format"],"carousel")
            from src.visual_assets.selection import plan_asset_selection
            with patch("src.visual_assets.selection.REPORTS_OUTPUT_DIRECTORY",out/"reports"):
                reviewed_plan=out/"creative-reviews/approved/Rich Project-content-plan.json"
                reviewed_plan.parent.mkdir(parents=True);reviewed_plan.write_text(json.dumps(content))
                selected_path=plan_asset_selection(reviewed_plan,v,out/"asset-selections",review_root=root)
            selected=next(x for x in json.loads(selected_path.read_text())["selections"] if x["content_idea_id"]==intro["content_idea_id"])
            self.assertEqual(selected["selected_asset_ids"],intro["selected_source_asset_ids"])
            self.assertTrue(selected["canonical_ordered_selection"])
            self.assertEqual(selected["publication_type"],"carousel")
            for a in assets[:2]:Path(a["source_path"]).write_bytes(b"changed cover")
            opp=VisualOpportunityEngine().run(k,v,s);result=PlanningEngine().run(k,s,v,opp)
            content=json.loads(result["content_plan"].read_text(encoding="utf-8"))
            self.assertFalse(any(i["content_category"]=="project_overview" for i in content["content_ideas"]))
        finally:
            for entry in reversed(patches):entry.stop()

    def generate(self, knowledge=None, visuals=None):
        root=Path(self.temp.name);k=root/"knowledge.json";v=root/"visuals.json";out=root/"content-inventory"
        payload=canonicalize_test_knowledge(knowledge or rich_knowledge())
        k.write_text(json.dumps(payload),encoding="utf-8");v.write_text(json.dumps(visuals if visuals is not None else rich_visuals()),encoding="utf-8")
        path=ContentOpportunityInventoryEngine().run(k,v,output_directory=out)
        return path,load_content_opportunity_inventory(path)

    def setUp(self):self.temp=tempfile.TemporaryDirectory()
    def tearDown(self):self.temp.cleanup()

    def test_canonical_schema_serialization_path_and_stable_ids(self):
        first_path,first=self.generate();second_path,second=self.generate()
        self.assertEqual(first_path,second_path)
        self.assertEqual(first.contract_role,"authoritative_content_opportunity_inventory")
        self.assertEqual([x.opportunity_id for x in first.opportunities],[x.opportunity_id for x in second.opportunities])
        self.assertTrue(first_path.name.endswith("-content-opportunity-inventory.json"))

    def test_text_location_is_high_priority_without_map_or_renderer(self):
        visuals={"project":"Rich Project","inventory_type":"semantic","all_source_asset_ids":[],"available_text_facts":[]}
        _,inventory=self.generate(visuals=visuals);locations=[x for x in inventory.opportunities if x.category=="location"]
        self.assertGreaterEqual(len(locations),3);self.assertTrue(all(x.priority=="HIGH" for x in locations))
        self.assertTrue(all(not x.related_visual_asset_ids for x in locations))
        self.assertTrue(all(x.renderer_readiness=="not_assessed" and x.readiness=="strategy_ready" for x in locations))

    def test_map_location_and_multiple_distinct_deduplicated_topics(self):
        _,inventory=self.generate();locations=[x for x in inventory.opportunities if x.category=="location"]
        self.assertTrue(all("map" in x.related_visual_asset_ids for x in locations))
        self.assertEqual(len({x.subcategory for x in locations}),len(locations))
        connectivity=next(x for x in locations if x.subcategory=="connectivity")
        self.assertEqual(connectivity.supporting_facts.count("Located on 120m Road"),1)

    def test_location_provenance_preserves_pdf_txt_and_docx_locations(self):
        _,inventory=self.generate();provenance=[p for x in inventory.opportunities if x.category=="location" for p in x.provenance]
        self.assertTrue(any(p.page==4 for p in provenance));self.assertTrue(any(p.line_range=="2-3" for p in provenance));self.assertTrue(any(p.paragraph==7 for p in provenance))

    def test_unsupported_location_claim_is_rejected(self):
        knowledge=rich_knowledge();knowledge["location"]["facts"].append({"value":"Five minutes from an imaginary marina","sources":[{"source_document":"draft.txt","status":"unsupported"}]})
        _,inventory=self.generate(knowledge);serialized=json.dumps(inventory.to_dict()).casefold()
        self.assertNotIn("imaginary marina",serialized)

    def test_required_categories_and_masterplan_priority(self):
        _,inventory=self.generate();categories={x.category for x in inventory.opportunities}
        self.assertTrue({"introduction","location","masterplan","exterior","interior","amenity","layout","commercial","carousel","story_sequence","cta"}<=categories)
        self.assertTrue(all(x.priority=="HIGH" for x in inventory.opportunities if x.category=="masterplan"))

    def test_verified_commercial_facts_only_and_no_roi_guarantee(self):
        _,inventory=self.generate();commercial=[x for x in inventory.opportunities if x.category=="commercial"]
        self.assertEqual({x.subcategory for x in commercial},{"starting_price","price_per_sqm"})
        serialized=json.dumps([x.supporting_facts for x in commercial]).casefold()
        self.assertNotIn("guaranteed return",serialized);self.assertNotIn("roi",serialized)

    def test_safe_ctas_and_forbidden_scarcity_guarantees(self):
        _,inventory=self.generate();ctas=[x for x in inventory.opportunities if x.category=="cta"]
        self.assertIn("Contact us for details",{x.title for x in ctas});self.assertIn("Ask about current pricing",{x.title for x in ctas})
        titles=" ".join(x.title for x in ctas).casefold();self.assertNotIn("selling fast",titles);self.assertNotIn("guaranteed",titles)
        self.assertTrue(all(any("Guaranteed return" in claim for claim in x.forbidden_claims) for x in ctas))

    def test_story_sequence_is_ordered_evidenced_and_ends_with_cta(self):
        _,inventory=self.generate();sequence=next(x for x in inventory.story_sequences if "Introduction" in x.title)
        self.assertEqual([x.order for x in sequence.frames],list(range(1,len(sequence.frames)+1)))
        self.assertTrue(any(x.supporting_fact_ids for x in sequence.frames[:-1]))
        self.assertEqual(sequence.frames[-1].role,"cta")

    def test_insufficient_evidence_shortens_sequence(self):
        knowledge={"project_identity":{"project_name":"Minimal","location":"Erbil"},"fact_provenance":{"project_identity.project_name":[evidence("one.pdf",page=1,project="Minimal")],"project_identity.location":[evidence("one.pdf",page=1,project="Minimal")]}}
        visuals={"project":"Minimal","inventory_type":"semantic","all_source_asset_ids":[],"available_text_facts":[]}
        _,inventory=self.generate(knowledge,visuals);sequence=inventory.story_sequences[0]
        self.assertLessEqual(len(sequence.frames),3)

    def test_rich_inventory_scales_beyond_minimal_without_quota(self):
        _,rich=self.generate();minimal_k={"project_identity":{"project_name":"Minimal","location":"Erbil"},"fact_provenance":{"project_identity.project_name":[evidence("one.pdf",page=1,project="Minimal")],"project_identity.location":[evidence("one.pdf",page=1,project="Minimal")]}}
        minimal_v={"project":"Minimal","inventory_type":"semantic","all_source_asset_ids":[],"available_text_facts":[]}
        _,minimal=self.generate(minimal_k,minimal_v)
        self.assertGreater(len(rich.opportunities),len(minimal.opportunities)+8)
        self.rich_count=len(rich.opportunities);self.minimal_count=len(minimal.opportunities)

    def test_legacy_visual_output_is_compatibility_not_authority(self):
        root=Path(self.temp.name);k=root/"knowledge.json";v=root/"visuals.json";s=root/"strategy.json"
        k.write_text(json.dumps(canonicalize_test_knowledge(rich_knowledge())),encoding="utf-8");v.write_text(json.dumps(rich_visuals()),encoding="utf-8");s.write_text("{}",encoding="utf-8")
        with patch("src.planning.engine.VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY",root/"visual-opportunities"):
            compatibility=VisualOpportunityEngine().run(k,v,s)
        payload=json.loads(compatibility.read_text(encoding="utf-8"));canonical=Path(payload["canonical_inventory_path"])
        self.assertEqual(payload["contract_role"],"compatibility_visual_opportunities")
        self.assertTrue(canonical.is_file());self.assertEqual(load_content_opportunity_inventory(canonical).contract_role,"authoritative_content_opportunity_inventory")

    def test_text_only_opportunity_survives_complete_planning_adapter(self):
        root=Path(self.temp.name);k=root/"knowledge.json";v=root/"visuals.json";s=root/"strategy.json"
        knowledge={"project_identity":{"project_name":"Text Project","location":"On Verified Road"},"fact_provenance":{"project_identity.project_name":[evidence("one.pdf",page=1,project="Text Project")],"project_identity.location":[evidence("one.pdf",page=2,project="Text Project")]}}
        visuals={"project":"Text Project","inventory_type":"semantic","all_source_asset_ids":[],"available_text_facts":[]}
        k.write_text(json.dumps(canonicalize_test_knowledge(knowledge)),encoding="utf-8");v.write_text(json.dumps(visuals),encoding="utf-8");s.write_text(json.dumps({"target_audience":["Buyer"]}),encoding="utf-8")
        names=("VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY","CAMPAIGNS_OUTPUT_DIRECTORY","CONTENT_OUTPUT_DIRECTORY","ASSET_USAGE_OUTPUT_DIRECTORY","CONTENT_MEMORY_OUTPUT_DIRECTORY","REPORTS_OUTPUT_DIRECTORY")
        patches=[patch(f"src.planning.engine.{name}",root/name.casefold()) for name in names]
        for item in patches:item.start()
        try:
            opportunities=VisualOpportunityEngine().run(k,v,s);outputs=PlanningEngine().run(k,s,v,opportunities)
            content=json.loads(outputs["content_plan"].read_text(encoding="utf-8"));location=next(x for x in content["content_ideas"] if x["title"]=="Road Connectivity")
            self.assertEqual(location["selected_source_asset_ids"],[]);self.assertEqual(location["source_support_status"],"text_only")
        finally:
            for item in reversed(patches):item.stop()

    def test_foreign_facts_and_assets_are_rejected_before_discovery(self):
        knowledge=rich_knowledge()
        knowledge["location"]["facts"].append({"value":"Foreign District","sources":[evidence("foreign.txt",project="Project B")]})
        knowledge["commercial_intelligence"]["pricing"]["facts"].append({"fact_type":"total_unit_price","value":999,"currency":"USD","status":"verified","source_project":"Project B","evidence":[evidence("foreign.pdf",project="Project B")]})
        visuals=rich_visuals()
        foreign_map=visual("foreign-map","location_map","foreign map");foreign_map["project_id"]="Project B"
        foreign_ext=visual("foreign-ext","exterior","foreign exterior");foreign_ext["project_id"]="Project B"
        visuals["available_location_maps"].append(foreign_map);visuals["available_exterior_images"].append(foreign_ext)
        _,inventory=self.generate(knowledge,visuals);payload=json.dumps(inventory.to_dict())
        self.assertNotIn("Foreign District",payload);self.assertNotIn("999",payload)
        self.assertNotIn("foreign-map",payload);self.assertNotIn("foreign-ext",payload)
        self.assertIn("Located on 120m Road",payload);self.assertIn("144900",payload)

    def test_commercial_gate_rejects_conflict_and_accepts_resolved_winner(self):
        knowledge=rich_knowledge();ci=knowledge["commercial_intelligence"]
        ci["conflicts"]=[{"fact_type":"starting_price","status":"conflicting","selected_value":None}]
        _,inventory=self.generate(knowledge);self.assertNotIn("starting_price",{x.subcategory for x in inventory.opportunities if x.category=="commercial"})
        ci["conflicts"][0]["status"]="resolved";ci["conflicts"][0]["selected_value"]=144900
        _,inventory=self.generate(knowledge);self.assertIn("starting_price",{x.subcategory for x in inventory.opportunities if x.category=="commercial"})

    def test_narrow_fact_matching_and_visual_only_policy(self):
        knowledge=rich_knowledge()
        knowledge["fact_provenance"].update({
            "architecture.style":[evidence("architecture.pdf",page=2)],
            "architecture.design_features":[evidence("interiors.pdf",page=4)],
            "units[0]":[evidence("plans.pdf",page=1)],"units[1]":[evidence("plans.pdf",page=2)],"units[2]":[evidence("plans.pdf",page=3)]})
        _,inventory=self.generate(knowledge)
        interior=next(x for x in inventory.opportunities if x.category=="interior")
        one=next(x for x in inventory.opportunities if x.category=="layout" and x.subcategory.startswith("1"))
        master=next(x for x in inventory.opportunities if x.category=="masterplan")
        self.assertNotIn("Contemporary exterior",interior.supporting_facts)
        self.assertEqual(one.supporting_facts,["1-bedroom apartment"])
        self.assertEqual(master.evidence_mode,"visual_only");self.assertTrue(master.provenance)

    def test_story_round_trip_preserves_frame_and_sequence_provenance(self):
        path,inventory=self.generate();loaded=load_content_opportunity_inventory(path)
        sequence=loaded.story_sequences[0];story=next(x for x in loaded.opportunities if x.subcategory==sequence.sequence_id)
        self.assertTrue(story.provenance);self.assertTrue(any(frame.provenance for frame in sequence.frames))
        self.assertTrue(all(p.project=="Rich Project" for p in story.provenance))

    def test_multilingual_location_and_mixed_relations(self):
        knowledge=rich_knowledge();knowledge["location"]["facts"] += [
            {"value":"10 دقائق من مطار أربيل الدولي عبر شارع المطار","sources":[evidence("ar.txt",line="1")]},
            {"value":"١٠ خولەک لە فڕۆکەخانە، لەسەر شەقامی سەرەکی","sources":[evidence("ku.txt",line="1")]},]
        _,inventory=self.generate(knowledge, {"project":"Rich Project","available_text_facts":[]})
        buckets={x.subcategory:x.supporting_facts for x in inventory.opportunities if x.category=="location"}
        self.assertTrue(any("مطار" in x for x in buckets["destinations"]));self.assertTrue(any("شارع" in x for x in buckets["connectivity"]))
        self.assertTrue(any("شەقام" in x for x in buckets["connectivity"]))

    def test_missing_canonical_never_falls_back_to_compatibility(self):
        root=Path(self.temp.name);k=root/"knowledge.json";v=root/"visuals.json";s=root/"strategy.json"
        k.write_text(json.dumps(canonicalize_test_knowledge(rich_knowledge())),encoding="utf-8");v.write_text(json.dumps(rich_visuals()),encoding="utf-8");s.write_text("{}",encoding="utf-8")
        names=("VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY","CAMPAIGNS_OUTPUT_DIRECTORY","CONTENT_OUTPUT_DIRECTORY","ASSET_USAGE_OUTPUT_DIRECTORY","CONTENT_MEMORY_OUTPUT_DIRECTORY","REPORTS_OUTPUT_DIRECTORY")
        patches=[patch(f"src.planning.engine.{name}",root/name.casefold()) for name in names]
        for item in patches:item.start()
        try:
            compatibility=VisualOpportunityEngine().run(k,v,s);payload=json.loads(compatibility.read_text());Path(payload["canonical_inventory_path"]).unlink()
            with self.assertRaisesRegex(ValueError,"Canonical content opportunity inventory is missing"):PlanningEngine().run(k,s,v,compatibility)
        finally:
            for item in reversed(patches):item.stop()

    def test_diagnostics_separate_subjects_from_wrappers(self):
        _,inventory=self.generate();d=inventory.diagnostics
        self.assertEqual(d["total_strategy_objects"],len(inventory.opportunities))
        self.assertEqual(d["content_subjects"],sum(x.category not in {"cta","carousel","story_sequence"} for x in inventory.opportunities))
        self.assertEqual(d["cta_opportunities"],sum(x.category=="cta" for x in inventory.opportunities))

    def test_corrupt_wrong_project_and_stale_canonical_fail_closed(self):
        root=Path(self.temp.name);k=root/"knowledge.json";v=root/"visuals.json";s=root/"strategy.json"
        k.write_text(json.dumps(canonicalize_test_knowledge(rich_knowledge())),encoding="utf-8");v.write_text(json.dumps(rich_visuals()),encoding="utf-8");s.write_text("{}",encoding="utf-8")
        names=("VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY","CAMPAIGNS_OUTPUT_DIRECTORY","CONTENT_OUTPUT_DIRECTORY","ASSET_USAGE_OUTPUT_DIRECTORY","CONTENT_MEMORY_OUTPUT_DIRECTORY","REPORTS_OUTPUT_DIRECTORY")
        patches=[patch(f"src.planning.engine.{name}",root/name.casefold()) for name in names]
        for item in patches:item.start()
        try:
            compatibility=VisualOpportunityEngine().run(k,v,s);meta=json.loads(compatibility.read_text());canonical=Path(meta["canonical_inventory_path"]);original=canonical.read_text()
            canonical.write_text("{broken",encoding="utf-8")
            with self.assertRaises((ValueError,json.JSONDecodeError)):PlanningEngine().run(k,s,v,compatibility)
            canonical.write_text(original.replace('"project_id": "Rich Project"','"project_id": "Project B"'),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"fingerprint|project|hash"):PlanningEngine().run(k,s,v,compatibility)
            canonical.write_text(original.replace('"inventory_version": "1.0.0"','"inventory_version": "0.9.0"'),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"fingerprint|version"):PlanningEngine().run(k,s,v,compatibility)
        finally:
            for item in reversed(patches):item.stop()

    def test_compatibility_excludes_every_foreign_asset_surface(self):
        root=Path(self.temp.name);k=root/"knowledge.json";v=root/"visuals.json";s=root/"strategy.json";visuals=rich_visuals()
        for aid,kind in (("foreign-map","location_map"),("foreign-ext","exterior"),("foreign-int","interior"),("foreign-master","masterplan")):
            item=visual(aid,kind,aid);item["project_id"]="Project B";field={"location_map":"available_location_maps","exterior":"available_exterior_images","interior":"available_interior_images","masterplan":"available_masterplans"}[kind];visuals[field].append(item)
        k.write_text(json.dumps(canonicalize_test_knowledge(rich_knowledge())),encoding="utf-8");v.write_text(json.dumps(visuals),encoding="utf-8");s.write_text("{}",encoding="utf-8")
        with patch("src.planning.engine.VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY",root/"visual-opportunities"):
            output=VisualOpportunityEngine().run(k,v,s)
        payload=json.loads(output.read_text());encoded=json.dumps(payload);self.assertNotIn("foreign-",encoded)
        self.assertEqual(payload["inventory_summary"]["total_authentic_assets"],8)

    def test_carousel_evidence_modes_are_conservative(self):
        _,inventory=self.generate();by={x.subcategory:x for x in inventory.opportunities if x.category=="carousel"}
        self.assertEqual(by["amenity"].evidence_mode,"mixed");self.assertTrue(by["amenity"].supporting_facts);self.assertLessEqual(by["amenity"].confidence,.9)
        self.assertEqual(by["commercial"].evidence_mode,"fact_supported");self.assertTrue(by["commercial"].supporting_fact_ids)
        knowledge=rich_knowledge();knowledge["fact_provenance"]["units[0]"]=[evidence("plans.pdf",page=1)]
        _,mixed=self.generate(knowledge);layout=next(x for x in mixed.opportunities if x.category=="carousel" and x.subcategory=="layout")
        self.assertEqual(layout.evidence_mode,"mixed");self.assertEqual(layout.supporting_facts,["1-bedroom apartment"]);self.assertLessEqual(layout.confidence,.72)

    def test_visual_ranking_contract_cannot_replace_canonical_strategy(self):
        root=Path(self.temp.name);visual_artifact=root/"visual-editorial-inventory.json";visual_artifact.write_text(json.dumps({"role":"visual_intelligence","authoritative_strategy":False,"pre_strategy":True,"may_not_drive_branded_content":True}),encoding="utf-8")
        k=root/"k.json";v=root/"v.json";s=root/"s.json";k.write_text(json.dumps(rich_knowledge()));v.write_text(json.dumps(rich_visuals()));s.write_text("{}")
        with self.assertRaises((KeyError,ValueError)):PlanningEngine().run(k,s,v,visual_artifact)

    def test_external_supplementary_evidence_requires_full_approval_contract(self):
        knowledge=rich_knowledge();base={"value":"Near an official public landmark","sources":[{"source_document":"web","source_file":"web","source_project":"Rich Project","status":"verified","source_url":"https://gov.example/landmark","domain":"gov.example","retrieval_timestamp":"2026-08-12T00:00:00Z","source_type":"government","project_match":True,"conflict_state":"resolved"}]}
        knowledge["location"]["facts"].append(base);_,inventory=self.generate(knowledge);self.assertIn("Near an official public landmark",json.dumps(inventory.to_dict()))
        base["sources"][0]["project_match"]=False;_,inventory=self.generate(knowledge);self.assertNotIn("official public landmark",json.dumps(inventory.to_dict()))


if __name__=="__main__":unittest.main()
