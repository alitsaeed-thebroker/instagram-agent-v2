from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ai.agents.knowledge_agent import KnowledgeAgent
from src.content.inventory import _facts as inventory_facts
from src.knowledge.document_classifier import DocumentType
from src.knowledge.fusion import fuse_knowledge
from src.knowledge.relational import CanonicalIntelligence
from src.knowledge.schema import ProjectKnowledge


def extracted_knowledge() -> ProjectKnowledge:
    return ProjectKnowledge.from_dict({
        "project_identity": {
            "project_name": "Avenue Square",
            "developer_name": "Alcove",
            "project_type": "Commercial",
            "location": "Erbil Avenue",
        },
        "project": {
            "name": "Avenue Square",
            "developer": "Alcove",
            "location": "Erbil Avenue",
            "description": "Premium office development on Erbil Avenue",
        },
        "branding": {
            "name": "Avenue Square",
            "tagline": "",
            "tone_of_voice": "",
            "key_messages": [],
        },
        "pricing": {
            "currency": "USD",
            "starting_price": None,
            "payment_plan": "",
            "notes": "",
        },
        "units": [{
            "name": "Office Type A",
            "bedrooms": None,
            "bathrooms": 1,
            "area_sqm": 120,
            "starting_price": None,
            "features": ["Private balcony"],
        }],
        "amenities": ["Business lounge", "Helipad"],
        "architecture": {
            "style": "Contemporary",
            "architect": "",
            "materials": ["Glass facade"],
            "design_features": [],
        },
        "investment": {
            "highlights": ["Commercial district"],
            "expected_return": "",
            "rental_potential": "",
            "completion_date": "2028",
        },
        "marketing": {
            "target_audience": [],
            "selling_points": ["[Fact | High] Business lounge for office users"],
            "calls_to_action": [],
        },
    })


class UniversalProvenanceTests(unittest.TestCase):
    def _run_agent(self, markdown: str) -> ProjectKnowledge:
        response = extracted_knowledge().to_json()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.md"
            source.write_text(markdown, encoding="utf-8")
            output = root / "knowledge"
            agent = KnowledgeAgent(model="test-model")
            with (
                patch.object(agent, "_load_api_key", return_value="key"),
                patch.object(agent, "_request_knowledge", return_value=response),
            ):
                path = agent.run(
                    source,
                    output_directory=output,
                    output_filename="doc",
                    source_document="catalogue.pdf",
                    source_project="Avenue Square",
                    source_id="src_123",
                    source_sha256="abc123",
                )
            self.assertIsNotNone(path)
            return ProjectKnowledge.from_json(path.read_text(encoding="utf-8"))

    def test_producer_generates_complete_fact_level_provenance(self):
        knowledge = self._run_agent("""# Source: catalogue.pdf
Project: Avenue Square

## Page 2

Avenue Square is a Commercial project by Alcove on Erbil Avenue.
Premium office development on Erbil Avenue.
Office Type A, 120 sqm, 1 bathroom, with Private balcony.
Business lounge for office users. Contemporary architecture with Glass facade.
The development is in a Commercial district. Completion date: 2028.
""")
        expected_paths = [
            "project_identity.project_name",
            "project_identity.developer_name",
            "project_identity.project_type",
            "project_identity.location",
            "project.description",
            "units[0].name",
            "units[0].bathrooms",
            "units[0].area_sqm",
            "units[0].features[0]",
            "amenities[0]",
            "architecture.style",
            "architecture.materials[0]",
            "investment.highlights[0]",
            "investment.completion_date",
            "marketing.selling_points[0]",
        ]
        for path in expected_paths:
            self.assertTrue(knowledge.fact_provenance.get(path), path)
            record = knowledge.fact_provenance[path][0]
            self.assertEqual(record["source_project"], "Avenue Square")
            self.assertEqual(record["source_file"], "catalogue.pdf")
            self.assertEqual(record["source_id"], "src_123")
            self.assertEqual(record["source_sha256"], "abc123")
            self.assertEqual(record["source_page"], 2)
            self.assertTrue(record["evidence_id"].startswith("ev_"))
            self.assertEqual(record["extraction_method"], "openai_structured_extraction")
            self.assertTrue(record["source_text"])

    def test_unsupported_extracted_value_receives_no_provenance(self):
        knowledge = self._run_agent("""# Source: catalogue.pdf
Project: Avenue Square

## Page 2

Avenue Square is a Commercial project by Alcove on Erbil Avenue.
Business lounge for office users.
""")
        self.assertTrue(knowledge.fact_provenance["amenities[0]"])
        self.assertEqual(knowledge.fact_provenance["amenities[1]"], [])

        merged, _ = fuse_knowledge(
            [(knowledge, DocumentType.CATALOGUE, Path("catalogue.pdf"))],
            project_namespace="Avenue Square",
        )
        graph = CanonicalIntelligence.from_dict(merged.canonical_intelligence)
        helipad = [
            f for f in graph.facts
            if f.fact_type == "amenity.name" and f.value == "Helipad"
        ][0]
        self.assertEqual(helipad.state, "UNKNOWN")
        self.assertFalse(helipad.marketing_eligible)

    def test_canonical_facts_reach_department3_with_same_evidence_id(self):
        knowledge = self._run_agent("""# Source: catalogue.pdf
Project: Avenue Square

## Page 2

Avenue Square is a Commercial project by Alcove on Erbil Avenue.
Business lounge for office users.
""")
        merged, _ = fuse_knowledge(
            [(knowledge, DocumentType.CATALOGUE, Path("catalogue.pdf"))],
            project_namespace="Avenue Square",
        )
        facts = inventory_facts(merged.to_dict(), "Avenue Square")
        amenity = next(f for f in facts if f.knowledge_path == "amenities")
        source_record = knowledge.fact_provenance["amenities[0]"][0]
        self.assertEqual(amenity.evidence_id, source_record["evidence_id"])
        self.assertEqual(amenity.source_sha256, "abc123")
        self.assertEqual(amenity.extraction_method, "openai_structured_extraction")
        self.assertEqual(amenity.project, "Avenue Square")

    def test_inference_marketing_fact_is_not_verified(self):
        knowledge = self._run_agent("""# Source: catalogue.pdf
Project: Avenue Square

## Page 2

Avenue Square is a Commercial project by Alcove on Erbil Avenue.
Business lounge for office users.
""")
        knowledge.marketing.selling_points = [
            "[Inference | Medium] Attractive to international investors"
        ]
        # Re-run through fusion with no direct provenance for the new inference.
        knowledge.fact_provenance["marketing.selling_points[0]"] = []
        merged, _ = fuse_knowledge(
            [(knowledge, DocumentType.CATALOGUE, Path("catalogue.pdf"))],
            project_namespace="Avenue Square",
        )
        graph = CanonicalIntelligence.from_dict(merged.canonical_intelligence)
        inferred = [
            f for f in graph.facts if f.fact_type == "marketing.selling_points"
        ][0]
        self.assertNotEqual(inferred.state, "VERIFIED")
        self.assertFalse(inferred.marketing_eligible)


if __name__ == "__main__":
    unittest.main()
