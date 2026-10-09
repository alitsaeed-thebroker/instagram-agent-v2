from __future__ import annotations

import unittest

from src.visual_assets.topic_linking import link_visual_topics


def record(asset: str, kind: str, page: int, context: str, *, quality: int = 80, selected: bool = False, duplicate: bool = False, property_type: str | None = None):
    return {
        "asset_id": asset, "path": f"Project/originals/{asset}.png", "sha256": asset * 4,
        "width": 1600, "height": 1000, "source_image_type": kind, "visual_quality_score": quality,
        "overall_score": quality, "source_page": page, "source_document": "catalogue.pdf",
        "source_section": context, "page_title": context, "nearby_text": context,
        "deep_description": context, "deep_image_type": kind, "source_confidence": .95,
        "related_property_type": property_type, "likely_duplicate": duplicate, "selected": selected,
        "selection_priority": "HIGH", "rejection_reason": None,
    }


class VisualTopicLinkingTests(unittest.TestCase):
    def test_full_inventory_not_selected_images_only_and_context_controls_linking(self):
        floor = record("floor", "floor_plan", 12, "Plans and Layouts Type A ground floor", selected=False, quality=62)
        result = link_visual_topics([floor], {"plans_and_layouts": [{"asset_id": "floor", "description": "Type A plan"}]})
        selected = result["topics"]["unit_information"]["selected"]
        self.assertEqual(selected[0]["asset_id"], "floor");self.assertTrue(selected[0]["page_context_used"]);self.assertGreater(selected[0]["semantic_topic_score"], .8)

    def test_floorplans_maps_and_provenance_link_to_correct_topics(self):
        floor = record("floor", "floor_plan", 20, "First Floor unit layout")
        map_asset = record("map", "map", 6, "The Location Advantage vicinity map", quality=55)
        knowledge = {"plans_and_layouts": [{"asset_id": "floor", "description": "floor plan"}], "location": {"facts": [{"value": "Airport access", "sources": [{"source_document": "catalogue.pdf", "source_page": 6}]}]}}
        result = link_visual_topics([floor, map_asset], knowledge)
        self.assertEqual(result["topics"]["unit_information"]["selected"][0]["asset_id"], "floor")
        linked = result["topics"]["location"]["selected"][0];self.assertEqual(linked["asset_id"], "map");self.assertEqual(linked["verified_knowledge_linkage"][0]["relationship"], "same_page")

    def test_features_require_verified_knowledge_support(self):
        feature = record("ev", "unknown", 15, "electric vehicle charging stations features")
        without = link_visual_topics([feature], {"features": []})["topics"]["features"]
        self.assertFalse(without["selected"]);self.assertEqual(without["candidates"][0]["link_rejection_reason"], "feature_not_supported_by_verified_knowledge")
        knowledge = {"features": [{"name": "Electric vehicle charging", "sources": [{"document": "catalogue.pdf", "page": 15}]}]}
        self.assertEqual(link_visual_topics([feature], knowledge)["topics"]["features"]["selected"][0]["asset_id"], "ev")

    def test_property_types_are_project_agnostic_and_lifestyle_is_not_generic_amenity(self):
        apartment = record("apt", "floor_plan", 30, "Apartment Type C floor plan", property_type="Apartment Type C")
        facility = record("gym", "amenity", 8, "gym facility")
        experience = record("walk", "landscape", 9, "family community walking lifestyle")
        knowledge = {"property_types": [{"label": "Apartment Type C", "source_pages": [{"document": "catalogue.pdf", "page": 30}]}], "lifestyle": [{"value": "Family walking experience", "sources": [{"source_document": "catalogue.pdf", "source_page": 9}]}]}
        result = link_visual_topics([apartment, facility, experience], knowledge)
        self.assertEqual(result["topics"]["property_types"]["selected"][0]["asset_id"], "apt")
        self.assertEqual([x["asset_id"] for x in result["topics"]["lifestyle"]["selected"]], ["walk"])

    def test_semantics_outweigh_quality_duplicates_are_excluded_and_investment_is_conservative(self):
        map_asset = record("map", "map", 6, "location access map", quality=45)
        premium = record("hero", "exterior_render", 7, "premium architecture", quality=100)
        duplicate = record("dup", "map", 6, "location access map", quality=99, duplicate=True)
        knowledge = {"location": {"facts": [{"value": "Access map", "sources": [{"source_document": "catalogue.pdf", "source_page": 6}]}]}, "canonical_facts": [{"value": "Buildup area 400m2", "category": "technical_specification"}]}
        result = link_visual_topics([map_asset, premium, duplicate], knowledge)
        self.assertEqual(result["topics"]["location"]["selected"][0]["asset_id"], "map")
        self.assertNotIn("dup", [x["asset_id"] for x in result["topics"]["location"]["candidates"]])
        self.assertFalse(result["topics"]["investment_facts"]["selected"]);self.assertEqual(result["topics"]["investment_facts"]["reason"], "no_explicit_investment_fact_support")


if __name__ == "__main__":
    unittest.main()
