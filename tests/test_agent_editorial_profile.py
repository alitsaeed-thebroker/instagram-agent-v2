from pathlib import Path
from copy import deepcopy
import json,tempfile,unittest
from PIL import Image,ImageChops,ImageOps
import tests.test_visual_art_director as fixtures
from src.creative.editorial_profile import load_editorial_profile,profile_path
from src.creative.visual_direction import VisualArtDirector,validate_visual_direction_contract
from src.image_processing.canonical_exports import align_canonical_exports
from src.image_processing.schema import ImageProcessingPlanCollection

class EditorialProfileTests(unittest.TestCase):
    def setUp(self):self.fixture=fixtures.VisualArtDirectorTests();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()
    def test_profile_keeps_complete_source_and_identity_separate(self):
        package=self.fixture.package();package['editorial_profile']={'profile':'architecture_first_editorial'}
        result=VisualArtDirector().direct(package);self.assertIsNotNone(result.contract,result.blockers)
        contract=result.contract;self.assertFalse(validate_visual_direction_contract(contract))
        self.assertEqual(contract['source_image']['crop_mode'],'fit');self.assertEqual(contract['graphics']['overlay'],'none')
        x,y,w,h=contract['source_image']['placement'];self.assertAlmostEqual(w/h,1200/900,places=2)
        self.assertGreater(contract['project_identity']['y'],y+h)
        self.assertFalse(contract['headline']['visible'])
    def test_other_project_gets_no_profile(self):
        path=profile_path(self.fixture.root,'p1');path.parent.mkdir(parents=True);path.write_text(json.dumps({'version':'1.0.0','project_id':'p1','profile':'architecture_first_editorial'}))
        self.assertIsNone(load_editorial_profile(self.fixture.root,'p2'))
        self.assertEqual(load_editorial_profile(self.fixture.root,'p1')['project_id'],'p1')
    def test_cross_project_profile_is_rejected(self):
        path=profile_path(self.fixture.root,'p1');path.parent.mkdir(parents=True);path.write_text(json.dumps({'version':'1.0.0','project_id':'p2','profile':'architecture_first_editorial'}))
        with self.assertRaises(ValueError):load_editorial_profile(self.fixture.root,'p1')
    def test_missing_unit_plan_record_still_blocks_editorial(self):
        package=self.fixture.package('unit_layout');package['editorial_profile']={'profile':'architecture_first_editorial'}
        self.assertEqual(VisualArtDirector().direct(package).status,'REQUIRES_REDIRECTION')

class ReviewedLineageTests(unittest.TestCase):
    def setUp(self):
        from src.execution.lineage import attach_lineage,canonical_graph_fingerprint
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.knowledge={'canonical_intelligence':{'project_id':'p1','facts':[]}}
        fp=canonical_graph_fingerprint(self.knowledge)
        self.parent=attach_lineage({'project_id':'p1','content_ideas':[{'content_idea_id':'i1','selected_source_asset_ids':['a1']}]},stage='department3-content-plan',canonical_fingerprint=fp)
        path=self.root/'output/content/p1-content-plan.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(self.parent))
        reviewed=deepcopy(self.parent);reviewed['content_ideas'][0]['creative_review']={'decision':'approve'}
        self.reviewed=attach_lineage(reviewed,stage='creative-reviewed-content-plan',canonical_fingerprint=fp,parents={'canonical_content_plan':self.parent['artifact_fingerprint']})
    def tearDown(self):self.temp.cleanup()
    def test_reviewed_subset_preserves_parent(self):
        from src.execution.lineage import require_content_plan_lineage
        require_content_plan_lineage(self.reviewed,self.knowledge,self.root,'p1')
    def test_changed_parent_is_rejected(self):
        from src.execution.lineage import require_content_plan_lineage
        self.reviewed['lineage']['parent_artifact_fingerprints']['canonical_content_plan']='wrong'
        with self.assertRaises(ValueError):require_content_plan_lineage(self.reviewed,self.knowledge,self.root,'p1')
    def test_resigned_changed_source_is_rejected(self):
        from src.execution.lineage import require_content_plan_lineage,attach_lineage,canonical_graph_fingerprint
        value=deepcopy(self.reviewed);value['content_ideas'][0]['selected_source_asset_ids']=['foreign']
        value=attach_lineage(value,stage='creative-reviewed-content-plan',canonical_fingerprint=canonical_graph_fingerprint(self.knowledge),parents={'canonical_content_plan':self.parent['artifact_fingerprint']})
        with self.assertRaises(ValueError):require_content_plan_lineage(value,self.knowledge,self.root,'p1')
