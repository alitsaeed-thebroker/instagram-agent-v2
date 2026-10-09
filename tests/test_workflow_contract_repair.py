import itertools
import tempfile
from pathlib import Path
import unittest

from src.knowledge.document_classifier import DocumentType
from src.knowledge.fusion import _merge_value, fuse_knowledge
from src.knowledge.schema import ProjectKnowledge, ProjectDetails, ProjectIdentity
from src.knowledge.storage import save_project_knowledge
from src.department3.planning_cutover import legacy_artifact_to_candidates, PlanningCutoverError
from src.department3.live_orchestration import LiveDepartment3Orchestrator
from src.department3.planning_cutover import _canonical_compatibility_document
from src.execution.lineage import attach_lineage, validate_lineage


class WorkflowContractRepairTests(unittest.TestCase):
    def test_conflict_is_stable_across_every_document_order(self):
        docs = [('a', 'A'), ('b', 'B'), ('c', 'B')]
        for order in itertools.permutations(docs):
            target, priorities, conflicts = {}, {}, []
            for source, value in order:
                _merge_value(target, {'project': {'name': value}}, (), DocumentType.UNKNOWN, priorities, conflicts, source)
            self.assertEqual(target['project']['name'], '')
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(len(conflicts[0]['candidates']), 3)
            self.assertEqual(conflicts[0]['status'], 'CONFLICTING')

    def test_higher_authority_stays_selected_even_when_seen_first(self):
        docs = [('high', 'C', DocumentType.CATALOGUE), ('a', 'A', DocumentType.UNKNOWN), ('b', 'B', DocumentType.UNKNOWN)]
        for order in itertools.permutations(docs):
            target, priorities, conflicts = {}, {}, []
            for source, value, kind in order:
                _merge_value(target, {'project': {'name': value}}, (), kind, priorities, conflicts, source)
            self.assertEqual(target['project']['name'], 'C')
            self.assertEqual(len(conflicts[0]['candidates']), 3)

    def test_conflicted_display_identity_can_save_without_fabricating_name(self):
        docs = [(ProjectKnowledge(project=ProjectDetails(name=value), project_identity=ProjectIdentity(project_name=value)),
                 DocumentType.UNKNOWN, Path(value+'.json')) for value in ('A', 'B')]
        merged, conflicts = fuse_knowledge(docs, project_namespace='Project Folder')
        self.assertEqual(merged.project.name, '')
        self.assertEqual(merged.project_identity.project_name, '')
        self.assertTrue(conflicts)
        self.assertEqual(merged.canonical_intelligence['project_namespace'], 'Project Folder')
        self.assertFalse(any(f['marketing_eligible'] for f in merged.canonical_intelligence['facts'] if f['fact_type']=='project.project_name'))
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(save_project_knowledge(merged, 'Project Folder', Path(td)).is_file())
        self.assertTrue(ProjectKnowledge().validate())

    def item(self):
        return {'content_idea_id': 'real-id', 'content_category': 'amenity', 'content_objective': 'Show amenity',
                'target_persona': 'Buyer', 'concept_summary': 'Use supplied image', 'selected_format': 'single_post',
                'selected_source_asset_ids': ['source-id'], 'selected_fact_refs': ['fact-id'],
                'forbidden_claims': ['No unsupported features'], 'source_support_status': 'fully_supported'}

    def test_actual_producer_contract_reaches_canonical_authority(self):
        candidates = legacy_artifact_to_candidates(project_id='P', content_document={'project_id':'P','content_ideas':[self.item()]})
        decision = LiveDepartment3Orchestrator().approve(project_id='P', candidates=candidates).approved_content_plan.decisions[0]
        self.assertEqual(decision.production_item_id, 'real-id')
        self.assertEqual(decision.approved_source_asset_ids, ('source-id',))
        self.assertEqual(decision.evidence[0].fact_id, 'fact-id')
        self.assertEqual(decision.restrictions, ('No unsupported features',))
        self.assertEqual(decision.format_intent, 'feed')

    def test_text_only_candidate_does_not_stop_supported_candidate(self):
        text = {**self.item(), 'content_idea_id':'text', 'source_support_status':'text_only','selected_source_asset_ids':[]}
        candidates = legacy_artifact_to_candidates(project_id='P', content_document={'project_id':'P','content_ideas':[text,self.item()]})
        self.assertEqual([c['production_item_id'] for c in candidates], ['real-id'])

    def test_cross_project_candidate_rejected_before_skipping(self):
        other = {**self.item(), 'project_id':'Other','source_support_status':'text_only'}
        with self.assertRaises(PlanningCutoverError):
            legacy_artifact_to_candidates(project_id='P', content_document={'project_id':'P','content_ideas':[other]})

    def test_cutover_refreshes_lineage_and_records_skipped_items(self):
        supported = self.item()
        skipped = {**supported, 'content_idea_id':'text', 'source_support_status':'text_only','selected_source_asset_ids':[]}
        document = attach_lineage({'project_id':'P','content_ideas':[supported,skipped]},
                                  stage='department3-content-plan',canonical_fingerprint='canonical',parents={'inventory':'exact-parent'})
        candidates = legacy_artifact_to_candidates(project_id='P',content_document=document)
        approved = LiveDepartment3Orchestrator().approve(project_id='P',candidates=candidates)
        result = _canonical_compatibility_document(project_id='P',legacy_document=document,live_result=approved,artifact_kind='content-plan')
        self.assertEqual([i['content_idea_id'] for i in result['content_ideas']], ['real-id'])
        self.assertEqual(result['skipped_candidates'][0]['content_idea_id'], 'text')
        self.assertTrue(validate_lineage(result,expected_stage='department3-content-plan',canonical_fingerprint='canonical',parents={'inventory':'exact-parent'})[0])

    def test_project_artifact_lookup_never_uses_substring_project(self):
        import app
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'Other P-knowledge.json').write_text('{}')
            self.assertIsNone(app._artifact(root,'P','-knowledge'))
            exact = root/'p-knowledge.json'
            exact.write_text('{}')
            self.assertEqual(app._artifact(root,'P','-knowledge'), exact)
