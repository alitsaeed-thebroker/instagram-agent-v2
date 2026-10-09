import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.department3.planning_cutover import cutover_legacy_planning_products, PlanningCutoverError
from src.knowledge.relational import CanonicalIntelligence, EntityRecord, FactRecord


class CutoverSourceIntegrityTests(unittest.TestCase):
    def replay(self, *, owner='P', fact_id='fact-id', digest=None, plan=False):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root/'source.png'
            source.write_bytes(b'authentic source fixture')
            evidence = {'evidence_id':'e1','source_project':owner,'source_file':'source.pdf','source_id':'doc1',
                        'source_sha256':'document-hash','source_text':'source fact','extraction_method':'source_text','page':1}
            graph = CanonicalIntelligence(project_namespace='P',entities=[EntityRecord('entity','project','P')],
                facts=[FactRecord('fact-id','entity','amenity.name',value='Park',state='VERIFIED',marketing_eligible=True,provenance=[evidence])])
            knowledge = root/'knowledge.json'
            knowledge.write_text(json.dumps({'canonical_intelligence':graph.to_dict()}))
            visual = root/'visual.json'
            asset = {'asset_id':'asset-id','project_id':'P','source_path':str(source),
                     'source_hash':digest or hashlib.sha256(source.read_bytes()).hexdigest(),'asset_type':'unit_layout' if plan else 'exterior'}
            visual.write_text(json.dumps({'available_assets':[asset]}))
            content = root/'content.json'
            item = {'content_idea_id':'item-id','content_category':'unit_layout' if plan else 'amenity',
                    'content_objective':'Show source','target_persona':'Buyer','concept_summary':'Source image',
                    'selected_format':'single_post','selected_source_asset_ids':['asset-id'],'selected_fact_refs':[fact_id]}
            content.write_text(json.dumps({'project_id':'P','content_ideas':[item]}))
            planner = SimpleNamespace(run=lambda *args,**kwargs: {'content_plan':content})
            result = cutover_legacy_planning_products(project_id='P',planning_engine=planner,planning_args=(knowledge,root/'strategy.json',visual))
            return json.loads(result['content_plan'].read_text())

    def test_exact_source_and_fact_are_approved_with_original_ids(self):
        result = self.replay()
        decision = result['approved_content_plan']['decisions'][0]
        self.assertEqual(decision['production_item_id'],'item-id')
        self.assertEqual(decision['evidence'][0]['source_id'],'doc1')
        self.assertEqual(decision['approved_source_asset_ids'],['asset-id'])

    def test_foreign_fact_evidence_rejected(self):
        with self.assertRaisesRegex(PlanningCutoverError,'foreign fact'):
            self.replay(owner='Other Project')

    def test_unknown_fact_id_rejected(self):
        with self.assertRaisesRegex(PlanningCutoverError,'fact reference'):
            self.replay(fact_id='invented')

    def test_source_hash_drift_rejected(self):
        with self.assertRaisesRegex(PlanningCutoverError,'hash mismatch'):
            self.replay(digest='stale')

    def test_unit_plan_without_relationship_proof_rejected(self):
        with self.assertRaisesRegex(PlanningCutoverError,'Unit plan requires validation'):
            self.replay(plan=True)
