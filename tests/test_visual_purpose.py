import unittest,tempfile,hashlib
from pathlib import Path
from src.content.visual_purpose import assess_visual_purpose,select_purpose_assets

class VisualPurposeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/"aerial.jpg";self.path.write_bytes(b"source fixture")
        self.asset={"asset_id":"aerial","project_id":"A","asset_type":"masterplan","source_path":str(self.path),"source_hash":hashlib.sha256(self.path.read_bytes()).hexdigest(),"source_document_hash":"pdf-source-hash","source_page":5,"confidence":.1}
        review={k:self.asset[k] for k in ("asset_id","project_id","source_hash","source_document_hash","source_page")}
        review.update(purpose="project_overview",scope="whole_development",status="APPROVED")
        self.asset["visual_purpose_review"]=review
    def tearDown(self):self.temp.cleanup()
    def test_correct_whole_development_beats_pretty_exterior(self):
        exterior={"asset_id":"pretty","asset_type":"exterior","confidence":1,"marketing_suitability":"hero_ready"}
        chosen,decisions=select_purpose_assets([exterior,self.asset],"introduction")
        self.assertEqual([a["asset_id"] for a in chosen],["aerial"])
        self.assertTrue(decisions[1]["preserve_full_image"])
    def test_logo_villa_room_and_location_map_do_not_become_overviews(self):
        for kind in ("logo","exterior","interior","villa_layout","location_map","architectural_detail"):
            self.assertEqual(assess_visual_purpose({"asset_type":kind,"confidence":1},"overview")["status"],"REJECTED")
    def test_high_confidence_masterplan_label_requires_review(self):
        self.assertEqual(assess_visual_purpose({"asset_type":"masterplan","confidence":1},"overview")["status"],"REVIEW_REQUIRED")
    def test_wrong_project_stale_hash_and_source_page_reject(self):
        self.assertEqual(assess_visual_purpose(self.asset,"overview","B")["status"],"REJECTED")
        self.asset["source_page"]=99
        self.assertEqual(assess_visual_purpose(self.asset,"overview","A")["status"],"REVIEW_REQUIRED")
        self.asset["source_page"]=5;self.path.write_bytes(b"replacement")
        self.assertEqual(assess_visual_purpose(self.asset,"overview","A")["status"],"REVIEW_REQUIRED")
    def test_overview_cannot_substitute_for_site_plan(self):
        self.assertEqual(assess_visual_purpose(self.asset,"site_plan")["status"],"REJECTED")
    def test_complete_readable_site_drawing_passes(self):
        asset={"asset_type":"site_plan","contains_diagram":True,"plan_completeness_status":"COMPLETE","plan_legibility_status":"READABLE"}
        self.assertEqual(assess_visual_purpose(asset,"site_plan")["status"],"MATCH")
        asset["plan_legibility_status"]="UNCERTAIN"
        self.assertEqual(assess_visual_purpose(asset,"site_plan")["status"],"REVIEW_REQUIRED")
    def test_no_suitable_candidate_returns_empty_not_fallback(self):
        self.assertEqual(select_purpose_assets([{"asset_type":"exterior"}],"overview")[0],[])

class OverviewCarouselTests(VisualPurposeTests):
    def slides(self):
        import copy
        from src.content.visual_purpose import validate_overview_slides
        cover=copy.deepcopy(self.asset);cover['visual_purpose_review']['sequence']=1
        support=copy.deepcopy(cover);support['asset_id']='support'
        path=Path(self.temp.name)/'support.jpg';path.write_bytes(b'different source')
        support.update(source_path=str(path),source_hash=hashlib.sha256(path.read_bytes()).hexdigest())
        support['visual_purpose_review'].update(asset_id='support',source_hash=support['source_hash'],scope='project_context',sequence=2)
        return cover,support
    def test_reviewed_support_requires_whole_project_cover(self):
        from src.content.visual_purpose import validate_overview_slides
        cover,support=self.slides()
        self.assertEqual(validate_overview_slides([cover,support],'A'),[])
        self.assertTrue(validate_overview_slides([support,cover],'A'))
        self.assertTrue(validate_overview_slides([support],'A'))
    def test_duplicates_and_wrong_order_are_blocked(self):
        from src.content.visual_purpose import validate_overview_slides
        cover,support=self.slides()
        self.assertTrue(validate_overview_slides([cover,cover],'A'))
        support['visual_purpose_review']['sequence']=0
        self.assertTrue(validate_overview_slides([cover,support],'A'))
    def test_missing_provenance_is_blocked(self):
        from src.content.visual_purpose import validate_overview_slides
        cover,support=self.slides();support.pop('source_document_hash')
        self.assertTrue(validate_overview_slides([cover,support],'A'))
