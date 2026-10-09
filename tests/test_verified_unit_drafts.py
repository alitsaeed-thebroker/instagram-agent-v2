"""Draft copy must use canonical unit facts and complete floor membership."""
import unittest

from src.content.schema import ContentPlan, ContentPillar
from tools.prepare_verified_unit_drafts import content_idea


class VerifiedUnitDraftTests(unittest.TestCase):
    def records(self):
        return [{"asset_id":asset,"source_page":page,
                 "unit_identity":{"unit_type":"Type D","bedrooms":5,"area_sqm":396.5},
                 "unit_plan_relationship":{"relationship_id":"proof-"+asset,
                     "catalogue_relationship":{"unit_scope_id":"unit-d",
                         "advertised_area_sqm":345,"advertised_area_basis":"UNSPECIFIED_IN_SOURCE"}}}
                for asset,page in (("ground",34),("first",35))]

    def test_copy_uses_built_up_facts_and_never_unclassified_heading(self):
        idea=content_idea(self.records())
        caption=idea.public_copy["caption"]
        self.assertIn("5-bedroom",caption)
        self.assertIn("396.5 m² built-up",caption)
        self.assertNotIn("345",caption)
        self.assertNotIn("plot",caption)
        self.assertIn("Figures reflect the brochure",caption)

    def test_complete_carousel_and_schema(self):
        idea=content_idea(self.records())
        self.assertEqual(idea.selected_source_asset_ids,["ground","first"])
        self.assertEqual(idea.required_source_asset_ids,["ground","first"])
        plan=ContentPlan([ContentPillar("Verified layouts",[idea])])
        self.assertEqual(plan.validate(),[])
        self.assertEqual(ContentPlan.from_json(plan.to_json()).validate(),[])

    def test_missing_canonical_area_is_not_replaced_by_heading(self):
        records=self.records()
        del records[0]["unit_identity"]["area_sqm"]
        with self.assertRaises(KeyError):
            content_idea(records)


if __name__=="__main__":
    unittest.main()
