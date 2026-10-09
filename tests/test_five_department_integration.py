"""Offline contract-spine integration: real departments, synthetic source fixtures.

Model responses, visual classifications, brand approvals and scene/framing
instructions are controlled fixtures. All five departments' contract consumers
and deterministic producers run; this is not certification of live content.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import pymupdf
import app
from src.core.file_manager import find_project_inputs
from src.department1.pipeline import Department1Config, Department1Pipeline
from src.knowledge.handoff import load_department2_handoff, Department2HandoffError
from src.knowledge.schema import ProjectKnowledge
from src.knowledge.document_classifier import DocumentType
from src.knowledge.fusion import fuse_knowledge
from src.knowledge.storage import save_project_knowledge
from src.knowledge.consumer import require_canonical_graph
from src.planning.engine import PlanningEngine, VisualOpportunityEngine
from src.department3.planning_cutover import cutover_legacy_planning_products
from src.image_prompts.generator import ImagePromptGenerator
from src.production.workflow import ProductionWorkflow
from src.branding import BrandComposer
from src.creative.visual_art_director import VisualArtDirectorWorkflow
from src.hardening import HardeningPipeline
from src.post_package import PostPackagePipeline
from src.social_review import SocialContentReview
from src.publishing import PublishingFoundation
from src.content.visual_purpose import load_visual_reviews
from tests.test_brand_composer import BrandComposerTests
from tests.test_asset_first_planning import asset
from tests.test_department2_handoff import FakeClient


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


class FiveDepartmentIntegrationTests(unittest.TestCase):
    names = ('Beverly Hills', 'VELORIA', 'Cedar Residences', 'Lake Residences')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, folder in (
            ('VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY','visual-opportunities'),
            ('CAMPAIGNS_OUTPUT_DIRECTORY','campaigns'), ('CONTENT_OUTPUT_DIRECTORY','content'),
            ('ASSET_USAGE_OUTPUT_DIRECTORY','asset-usage'), ('CONTENT_MEMORY_OUTPUT_DIRECTORY','content-memory'),
            ('REPORTS_OUTPUT_DIRECTORY','reports')):
            self.stack.enter_context(patch(f'src.planning.engine.{name}',self.root/'output'/folder))
        self.stack.enter_context(patch('src.image_prompts.generator.IMAGE_PROMPTS_OUTPUT_DIRECTORY', self.root/'output/image-prompts'))
        for name, value in (
            ('PROJECT_ROOT',self.root), ('PROJECT_VISUAL_MODE','source_only'),
            ('PRODUCED_IMAGES_OUTPUT_DIRECTORY',self.root/'output/produced-images'),
            ('PRODUCTION_MANIFESTS_OUTPUT_DIRECTORY',self.root/'output/production-manifests'),
            ('IMAGE_QA_OUTPUT_DIRECTORY',self.root/'output/qa')):
            self.stack.enter_context(patch(f'src.production.workflow.{name}',value))
        self.stack.enter_context(patch('src.image_prompts.generator.PROJECT_VISUAL_MODE','source_only'))
        # Source files are real and deliberately have identical basenames.
        for index, project in enumerate(self.names):
            folder = self.root/'input'/project
            folder.mkdir(parents=True)
            (folder/'notes.txt').write_text(f'{project}\nSynthetic source fixture only.\n',encoding='utf-8')
            image = Image.new('RGB',(1080,1350),(180+index*10,180,180))
            image.paste((30,30+index*15,30),(540,0,1080,1350))
            image.save(folder/'exterior.png')
            with pymupdf.open() as document:
                page=document.new_page(width=540,height=675)
                page.insert_image(page.rect,stream=(folder/'exterior.png').read_bytes())
                document.save(folder/'catalogue.pdf')
        self.write('input/publishing/publishing-config.json', {
            'schema_version':'1.0.0','timezone':'Asia/Baghdad','default_mode':'manual',
            'minimum_spacing_minutes':60,'max_posts_per_day':3,
            'allow_same_package_multi_platform':True,'allow_duplicate_package_same_platform':False,
            'retry_policy':{'max_attempts':3,'initial_delay_minutes':5,'backoff_multiplier':2}})

    def write(self,relative,value):
        path=self.root/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        return path

    def run_project(self, project, client=None):
        folder=self.root/'input'/project
        d1=Department1Pipeline(folder,output_root=self.root/'output/department1',
            config=Department1Config(allow_external_ai=True),client=client or FakeClient())
        d1.run()
        handoff=load_department2_handoff(d1.output_dir/'department2-handoff.json',
            expected_project=project,project_root=folder)
        source=next(s for s in handoff.sources if s.filename=='notes.txt')
        image_source=next(s for s in handoff.sources if s.filename=='exterior.png')
        catalogue_source=next(s for s in handoff.sources if s.filename=='catalogue.pdf')
        # Controlled D2 extraction response, bound to actual D1 evidence.
        knowledge=ProjectKnowledge()
        knowledge.project_identity.project_name=source.blocks[0]['text']
        evidence={'evidence_id':f'e-{source.source_id}','source_project':project,
            'source_file':source.relative_path,'source_id':source.source_id,
            'source_sha256':source.sha256,'source_text':source.blocks[0]['text'],
            'line_range':[1,1],'extraction_method':'source_text','fact_value':project,'support_status':'direct'}
        knowledge.fact_provenance={'project_identity.project_name':[evidence]}
        fused,_=fuse_knowledge([(knowledge,DocumentType.UNKNOWN,folder/'notes.txt')],project_namespace=project)
        graph=require_canonical_graph(fused.to_dict(),expected_project=project)
        self.assertTrue(any(f.state=='VERIFIED' for f in graph.facts))
        # Shared approved brand fixture; all downstream project artifacts below
        # are overwritten by real producer outputs before consumption.
        brand=BrandComposerTests()
        brand.root=self.root;brand.project=project;brand._fixture()
        kp=save_project_knowledge(fused,project,self.root/'output/knowledge')
        ap=asset('asset-1')
        ap.update(project_id=project,source_path=str(folder/'exterior.png'),source_hash=image_source.sha256,
            source_document=catalogue_source.relative_path,source_document_path=str(folder/'catalogue.pdf'),
            source_document_hash=catalogue_source.sha256,source_page=1,
            text_safe_regions=[[0,0,420,1350]],protected_regions=[[540,0,1080,1350]])
        ip=self.write(f'output/visual-inventory/{project}-visual-inventory.json',{
            'project_id':project,'project':project,'inventory_type':'semantic',
            'all_source_asset_ids':['asset-1'],'available_exterior_images':[ap],'assets':[ap]})
        intel=self.write(f'output/asset-intelligence/{project}-asset-intelligence.json',{'project_id':project,'assets':[ap]})
        strategy=self.write(f'output/strategy/{project}-strategy.json',{'project_id':project,'target_audience':['Buyer']})
        opp=VisualOpportunityEngine().run(kp,ip,strategy)
        products=cutover_legacy_planning_products(project_id=project,planning_engine=PlanningEngine(),
            planning_args=(kp,strategy,ip,opp),planning_kwargs={'allowed_channels':['instagram']})
        content=read(products['content_plan'])
        self.assertTrue(content['approved_content_plan']['decisions'])
        idea=next(i for i in content['content_ideas'] if i['selected_source_asset_ids'])
        # Framing/processing fixture preserves the exact canonical content ID,
        # selected source and hash. Prompt routing and production are real.
        pp=self.write(f'output/processing/{project}.json',{'project_id':project,'image_processing_plans':[{
            'processing_plan_id':f'{project}-processing','project':project,
            'content_idea_id':idea['content_idea_id'],'source_asset_ids':['asset-1'],
            'source_asset_operations':[{'source_asset_id':'asset-1','source_path':ap['source_path'],
                'source_hash':ap['source_hash'],'crop':{'x':0,'y':0,'width':1,'height':1},
                'resize':{'mode':'contain_letterbox'},'technical_enhancements':[],
                'output_preparation':{'compression_quality':95}}],
            'export_variants':[{'platform':'Instagram Feed','width':1080,'height':1350,
                'aspect_ratio':'4:5','output_format':'PNG'}]}]})
        prompt_path,_=ImagePromptGenerator().run(project=project,processing_path=pp,
            asset_intelligence_path=intel,visual_inventory_path=ip,knowledge_path=kp,
            content_path=products['content_plan'],campaign_path=products['campaign_plan'],
            opportunities_path=opp,strategy_path=strategy)
        self.assertTrue(read(prompt_path)['prompts'])
        production=ProductionWorkflow(project)
        manifest=read(production.process(prompt_path,pp,ip,intel))
        self.assertEqual(manifest['summary']['images_produced'],1)
        qa=read(production.qa())
        self.assertIn(qa['items'][0]['status'],('passed','passed_with_warnings'))
        VisualArtDirectorWorkflow(project,self.root).run()
        composer=BrandComposer(project,self.root)
        composer.compose();composer.output_qa(force=True);composer.qa(force=True)
        hard=HardeningPipeline(project,self.root)
        hard.creative_qa(force=True);hard.self_correct();hard.provenance_audit();hard.quality_report()
        release=read(hard.release())
        self.assertEqual(release['status'],'completed')
        reviews_path=self.root/'input/visual-review/project-overview-reviews.json'
        reviews=read(reviews_path)['reviews'] if reviews_path.exists() else []
        review={k:ap[k] for k in ('asset_id','project_id','source_hash','source_document_hash','source_page')}
        review.update(purpose='project_overview',scope='whole_development',status='APPROVED',
            reviewer='synthetic_integration_fixture')
        reviews.append(review)
        self.write('input/visual-review/project-overview-reviews.json',{'reviews':reviews})
        packages=PostPackagePipeline(project,self.root)
        packages.groups();packages.captions();packages.hashtags();packages.alt_text();packages.build();packages.qa()
        SocialContentReview(project,self.root).render()
        pub=PublishingFoundation(project,self.root)
        queue=read(pub.queue())
        self.assertEqual(len(queue['items']),1)
        pub.schedule()
        preflight=read(pub.preflight())
        self.assertEqual(preflight['items'][0]['status'],'ready',preflight)
        result=read(pub.mock_publish())
        self.assertEqual(len(result['mock_receipts']),1)
        self.assertTrue(result['mock_receipts'][0]['dry_run'])
        return pub,handoff

    def test_four_projects_traverse_five_departments_and_restart_independently(self):
        projects=find_project_inputs(self.root/'input')
        self.assertEqual({p.name for p in projects},set(self.names))
        outputs={}
        for project in self.names:
            outputs[project]=self.run_project(project)
        identities=set()
        for project,(pub,_) in outputs.items():
            queue=read(pub.queue())
            self.assertTrue(all(i['project_id']==project for i in queue['items']))
            identities.update(i['publication_identity'] for i in queue['items'])
            self.assertEqual(len(read(pub.mock_publish())['mock_receipts']),1)
            assets=load_visual_reviews(self.root,read(self.root/f'output/asset-intelligence/{project}-asset-intelligence.json')['assets'])
            self.assertEqual(assets[0]['visual_purpose_review']['project_id'],project)
        self.assertEqual(len(identities),4)
        self.assertEqual({p.name for p in find_project_inputs(self.root/'input')},set(self.names))

    def test_project_exception_does_not_stop_remaining_projects(self):
        projects=find_project_inputs(self.root/'input')
        visited=[]
        def process(project,args):
            visited.append(project.name)
            if project.name=='Beverly Hills':raise RuntimeError('injected project failure')
            return True
        with patch.object(app,'_process_staged_planning',side_effect=process):
            failed=app._process_independent_projects(projects,None,True)
        self.assertEqual(failed,['Beverly Hills'])
        self.assertEqual(len(visited),4)

    def test_failed_d1_project_isolated_and_recovers_through_all_five(self):
        class BrokenResponses:
            def create(self, **kwargs):
                response=FakeClient().responses.create(**kwargs)
                value=json.loads(response.output_text)
                if value['stage']=='ANALYZE':value['summary']=[]
                response.output_text=json.dumps(value)
                return response
        class BrokenClient:
            responses=BrokenResponses()
        completed=[]
        def process(project,args):
            self.run_project(project.name, BrokenClient() if project.name=='VELORIA' else None)
            completed.append(project.name)
            return True
        with patch.object(app,'_process_staged_planning',side_effect=process):
            failed=app._process_independent_projects(find_project_inputs(self.root/'input'),None,True)
        self.assertEqual(failed,['VELORIA'])
        self.assertEqual(set(completed),set(self.names)-{'VELORIA'})
        self.assertFalse((self.root/'output/publishing/VELORIA-publishing-queue.json').exists())
        before={p:(self.root/f'output/publishing/{p}-publishing-queue.json').read_bytes() for p in completed}
        self.run_project('VELORIA')
        for project,data in before.items():
            self.assertEqual((self.root/f'output/publishing/{project}-publishing-queue.json').read_bytes(),data)

    def test_source_drift_and_unproven_unit_plan_cannot_cross_handoffs(self):
        project='Beverly Hills'
        pub,handoff=self.run_project(project)
        notes=self.root/'input'/project/'notes.txt'
        notes.write_text('Changed original source',encoding='utf-8')
        with self.assertRaises(Department2HandoffError):
            load_department2_handoff(handoff.path,expected_project=project,project_root=notes.parent)
        intel=read(self.root/f'output/asset-intelligence/{project}-asset-intelligence.json')
        prompt_path=self.root/f'output/image-prompts/{project}-image-prompts.json'
        prompt=read(prompt_path)['prompts'][0]
        plan=read(self.root/f'output/processing/{project}.json')['image_processing_plans'][0]
        intel['assets'][0].update(asset_type='unit_layout',marketing_eligible=True)
        from src.production.workflow import ValidationError
        with self.assertRaisesRegex(ValidationError,'unit plan is REVIEW_REQUIRED'):
            ProductionWorkflow(project)._validate(prompt,plan,{'asset-1'},{'asset-1':intel['assets'][0]})

    def test_d5_rejects_foreign_graph_release_and_missing_owner(self):
        pub,_=self.run_project('Beverly Hills')
        path=self.root/'output/knowledge/Beverly Hills.json'
        original=path.read_bytes();value=read(path)
        value['canonical_intelligence']['project_namespace']='Other'
        for entity in value['canonical_intelligence']['entities']:entity['project_namespace']='Other'
        path.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'project mismatch'):pub._inputs()
        path.write_bytes(original)
        path=self.root/'output/provenance/Beverly Hills-provenance-audit.json'
        original=path.read_bytes();value=read(path);value.pop('project_id')
        path.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'ownership'):pub._inputs()
        path.write_bytes(original)
        path=next((self.root/'output/releases/Beverly Hills').glob('release-*/manifest.json'))
        value=read(path);value['project_id']='VELORIA';path.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'release ownership'):pub._inputs()

    def test_foreign_persisted_queue_and_production_inputs_block_without_mutation(self):
        project='Beverly Hills'
        pub,_=self.run_project(project)
        original=pub.queue_path.read_bytes();value=read(pub.queue_path)
        value['project_id']='VELORIA';pub.queue_path.write_text(json.dumps(value),encoding='utf-8')
        foreign=pub.queue_path.read_bytes()
        with self.assertRaisesRegex(ValueError,'ownership'):pub.schedule()
        with self.assertRaisesRegex(ValueError,'ownership'):pub.queue()
        self.assertEqual(pub.queue_path.read_bytes(),foreign)
        pub.queue_path.write_bytes(original)
        production=ProductionWorkflow(project)
        before=production.manifest_path.read_bytes()
        intel=self.root/f'output/asset-intelligence/{project}-asset-intelligence.json'
        payload=read(intel);payload['project_id']='VELORIA';intel.write_text(json.dumps(payload),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'ownership'):
            production.process(self.root/f'output/image-prompts/{project}-image-prompts.json',
                self.root/f'output/processing/{project}.json',
                self.root/f'output/visual-inventory/{project}-visual-inventory.json',intel)
        self.assertEqual(production.manifest_path.read_bytes(),before)

    def test_d1_punctuation_distinct_projects_never_overwrite_each_other(self):
        paths=[]
        for project in ('Project A','Project-A'):
            folder=self.root/'input'/project;folder.mkdir()
            (folder/'notes.txt').write_text('Identical file content',encoding='utf-8')
            pipeline=Department1Pipeline(folder,output_root=self.root/'output/department1',
                config=Department1Config(allow_external_ai=True),client=FakeClient())
            pipeline.run();paths.append(pipeline.output_dir/'department2-handoff.json')
        self.assertNotEqual(paths[0],paths[1])
        for project,path in zip(('Project A','Project-A'),paths):
            self.assertEqual(load_department2_handoff(path,expected_project=project,
                project_root=self.root/'input'/project).project,project)

    def test_certification_reports_are_project_scoped_and_missing_evidence_blocks(self):
        from src.department3.phase5_freeze_certification import _artifact_paths, certify, write_report, Phase5FreezeError
        snapshots=[]
        for project in self.names:
            paths=_artifact_paths(self.root,project)
            self.assertIn(project.lower().replace(' ','-'),paths['phase4f_report'].name)
            with self.assertRaises(Phase5FreezeError):certify(self.root,project)
            report={'project':project,'decision':'DEPARTMENT 3 — FAIL','phase4f_status':'NOT_RUN',
                'fingerprint':project,'checks':[],'certified_at':'fixture','critical_file_hashes':{},
                'certified_artifacts':{},'freeze_policy':{}}
            written=write_report(self.root,report)
            snapshots.append((written[2],written[2].read_bytes()))
        self.assertEqual(len({p for p,_ in snapshots}),4)
        for path,original in snapshots:self.assertEqual(path.read_bytes(),original)
