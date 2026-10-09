import copy, hashlib, tempfile, unittest
from pathlib import Path
from src.content.visual_purpose import assess_visual_purpose, load_visual_reviews
from src.department3.phase5_freeze_certification import _artifact_paths

class IllustratedLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        image=self.root/'source.jpg';image.write_bytes(b'exact reviewed image')
        self.asset=dict(asset_id='layout',project_id='P',source_hash=hashlib.sha256(image.read_bytes()).hexdigest(),source_document_hash='pdfhash',source_page=4,source_path=str(image),asset_type='site_plan')
        review={k:self.asset[k] for k in ('asset_id','project_id','source_hash','source_document_hash','source_page')}
        review.update(status='APPROVED',purpose='project_site_plan',scope='project_layout',representation='architectural_illustration')
        self.asset['project_layout_review']=review
    def tearDown(self):self.tmp.cleanup()
    def test_illustration_requires_disclosure_and_never_certifies_dimensions(self):
        result=assess_visual_purpose(self.asset,'site_plan','P')
        self.assertEqual(result['status'],'MATCH')
        self.assertTrue(result['preserve_full_image'])
        self.assertFalse(result['technical_dimensions_verified'])
        self.assertIn('not a measured',result['required_disclosure'])
    def test_missing_stale_or_wrong_project_blocks(self):
        for key in ('source_hash','source_document_hash','source_page'):
            a=copy.deepcopy(self.asset);a.pop(key)
            self.assertEqual(assess_visual_purpose(a,'site_plan','P')['status'],'REVIEW_REQUIRED')
        Path(self.asset['source_path']).write_bytes(b'replaced')
        self.assertEqual(assess_visual_purpose(self.asset,'site_plan','P')['status'],'REVIEW_REQUIRED')
        self.assertEqual(assess_visual_purpose(self.asset,'site_plan','Other')['status'],'REJECTED')
    def test_unit_map_and_interior_substitution_blocked(self):
        for kind in ('unit_layout','villa_layout','floor_plan','location_map','interior'):
            a=copy.deepcopy(self.asset);a['asset_type']=kind
            self.assertEqual(assess_visual_purpose(a,'site_plan','P')['status'],'REJECTED')
    def test_llm_label_is_insufficient(self):
        self.asset.pop('project_layout_review')
        self.assertEqual(assess_visual_purpose(self.asset,'site_plan','P')['status'],'REVIEW_REQUIRED')
    def test_artifact_handoff_prefers_current_flat_output(self):
        p=self.root/'output/asset-intelligence/P-asset-intelligence.json';p.parent.mkdir(parents=True);p.write_text('{}')
        self.assertEqual(_artifact_paths(self.root,'P')['asset_intelligence'],p)
        p.unlink()
        self.assertEqual(_artifact_paths(self.root,'P')['asset_intelligence'],self.root/'output/asset-intelligence/P/P-asset-intelligence.json')
