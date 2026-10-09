"""Tests for non-distorting deterministic production and QA helpers."""
import tempfile, unittest
from pathlib import Path
from PIL import Image

from src.production.workflow import _ahash_similarity, _destination, _produce, _qa_item, ValidationError
from src.production.eligibility import production_eligibility, warning

class ProductionWorkflowTests(unittest.TestCase):
    def prompt(self,status="production_ready",details=None,route="deterministic_processor"):
        details=[] if details is None else details
        return {"execution_route":route,"ai_prompt_required":False,"confidence":{"status":status},
                "warnings":[x["message"] for x in details],"warning_details":details}

    def test_canonical_production_eligibility(self):
        self.assertEqual(production_eligibility(self.prompt()),(True,"production_eligible"))
        advisory=warning("missing_verified_fact_reference","Factual objective has no verified fact references")
        self.assertEqual(production_eligibility(self.prompt("production_ready_with_warnings",[advisory])),(True,"production_eligible"))

    def test_blocking_and_unknown_warning_semantics_fail_closed(self):
        blocking=warning("manual_safety_review","unsafe")
        self.assertEqual(production_eligibility(self.prompt("production_ready_with_warnings",[blocking]))[1],"blocking_warning")
        malformed=self.prompt("production_ready_with_warnings");malformed["warnings"]=["legacy warning"]
        self.assertEqual(production_eligibility(malformed)[1],"unknown_warning_semantics")

    def test_unsupported_route_is_distinct_from_readiness(self):
        self.assertEqual(production_eligibility(self.prompt(route="ai_image_editor")),(False,"unsupported_execution_route"))

    def test_contain_has_exact_dimensions_and_no_distortion(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"source.jpg";Image.new("RGB",(400,200),(20,40,80)).save(source)
            image,details=_produce(source,(1080,1350),{"crop":{"x":0,"y":0,"width":1,"height":1},"resize":{"mode":"contain_letterbox"}},{"asset_type":"exterior"},["crop","resize"],[])
            self.assertEqual(image.size,(1080,1350));self.assertEqual(details["resize_policy"],"contain_letterbox");self.assertFalse(details["provenance"]["non_uniform_scaling"])
            self.assertGreater(details["padding"]["top"],0)

    def test_floorplan_forces_full_image_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"plan.png";Image.new("RGB",(300,500),"white").save(source);warnings=[]
            _,details=_produce(source,(1080,1350),{"crop":{"x":.1,"y":.1,"width":.8,"height":.8},"resize":{"mode":"contain"}},{"asset_type":"floorplan"},["crop"],warnings)
            self.assertEqual(details["crop"]["normalized"],(0,0,1,1));self.assertTrue(warnings)

    def test_blank_output_is_critical_qa_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/"s.png";out=root/"o.png";Image.new("RGB",(40,40),"white").save(source);Image.new("RGB",(40,40),"white").save(out)
            import hashlib
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            result=_qa_item({"production_item_id":"i","prompt_id":"p","output_path":str(out),"source_paths":[str(source)],"source_hashes":[digest],"output_width":40,"output_height":40,"prompt_type":"floorplan_presentation","provenance":{"non_uniform_scaling":False}})
            self.assertEqual(result["status"],"failed");self.assertLess(result["score"],70)

    def test_perceptual_similarity_and_revision_naming(self):
        with tempfile.TemporaryDirectory() as tmp:
            image=Path(tmp)/"a.jpg";Image.new("RGB",(30,20),(1,2,3)).save(image)
            self.assertEqual(_ahash_similarity(image,image),1)
        path,revision,_=_destination("p",{"prompt_id":"A:B","target_platform":"Instagram Feed","prompt_type":"source_image_enhancement"},(1080,1350),"JPEG","hash")
        self.assertNotIn(":",path.name);self.assertEqual(revision,1)

if __name__=="__main__":unittest.main()
