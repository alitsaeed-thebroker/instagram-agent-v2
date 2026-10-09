import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.content.quality import assess_marketing_comprehension, duplicate_copy_fields, semantic_match
from src.knowledge.audit import audit_project
from src.knowledge.schema import ProjectKnowledge


class Phase26QualityTests(unittest.TestCase):
    def test_identity_is_exact_and_missing_values_are_allowed(self):
        data=ProjectKnowledge().to_dict()
        self.assertEqual(set(data["project_identity"]), {"project_name","developer_name","project_type","location"})
        self.assertEqual(data["project_identity"]["developer_name"], "")

    def test_legacy_identity_migrates_without_broker_substitution(self):
        data=ProjectKnowledge().to_dict();data.pop("project_identity");data.pop("fact_provenance")
        data["project"].update(name="Vision",developer="Actual Developer",location="Erbil")
        value=ProjectKnowledge.from_dict(data)
        self.assertEqual(value.project_identity.developer_name,"Actual Developer")

    def test_semantic_matching_rejects_wrong_visual(self):
        self.assertFalse(semantic_match("Villa Exterior","villa_interior"))
        self.assertTrue(semantic_match("Site Plan","site_plan"))
        self.assertFalse(semantic_match("Floor Plan","project_hero"))

    def test_generic_and_duplicate_copy_are_detected(self):
        result=assess_marketing_comprehension(text="Discover the Project. Learn More.",project_name="Vision",visual_category="unknown",verified_facts=[])
        self.assertEqual(result["status"],"fail")
        self.assertTrue(duplicate_copy_fields("View 4","View 4"))

    def test_grounded_creative_passes(self):
        result=assess_marketing_comprehension(text="Vision — Villa Exterior. A verified view of the entrance and facade.",project_name="Vision",developer_name="Developer",visual_category="villa_exterior",verified_facts=[{"value":"Entrance"}])
        self.assertEqual(result["status"],"pass")

    def test_audit_uses_measured_counts_and_writes_both_formats(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);(root/"output/reports").mkdir(parents=True);(root/"output/knowledge").mkdir(parents=True);(root/"output/asset-intelligence").mkdir(parents=True);(root/"output/markdown/P").mkdir(parents=True)
            knowledge=ProjectKnowledge();knowledge.project_identity.project_name="P";knowledge.project.name="P"
            (root/"output/knowledge/P.json").write_text(knowledge.to_json(),encoding="utf-8")
            (root/"output/reports/P-document-analysis.json").write_text(json.dumps({"documents":[{"file_identifier":"p.pdf","page_count":2,"tables_detected":1}]}),encoding="utf-8")
            (root/"output/markdown/P/p.md").write_text("## Page 1\nText\n## Page 2\n",encoding="utf-8")
            (root/"output/asset-intelligence/P-asset-intelligence.json").write_text(json.dumps({"assets":[{"asset_type":"site_plan","source_document":"p.pdf","source_page":2}]}),encoding="utf-8")
            human,machine,report=audit_project("P",root)
            self.assertTrue(human.is_file() and machine.is_file());self.assertEqual(report["source_analysis"]["pages_analyzed"],2)
            self.assertNotIn("completeness_percentage",report)


if __name__ == "__main__": unittest.main()
