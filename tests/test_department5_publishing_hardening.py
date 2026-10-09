"""Forty focused adversarial probes for canonical Department 5 safety."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.publishing.foundation import _is_active_job, _publication_identity
from src.publishing.meta import MetaAdapterError, MetaHttpClient


def _package()->dict:
    return {"project_id":"A","package_id":"generated-1","release_id":"release-1","package_type":"single_post","content_idea_id":"idea-1","master_concept_id":"concept-1","language_code":"en","creative_production_contract_version":"1.0.0","created_at":"now","platform":"Instagram Feed","CTA":"Explore","caption":{"full_caption":"Approved caption","created_at":"now"},"hashtags":[{"hashtag":"#DomusErbil"}],"image":{"branded_item_id":"b1","image_hash":"hash-1","image_path":"old/name.png","source_asset_ids":["asset-1"],"slide_number":1}}


class Department5PublishingHardeningTests(unittest.TestCase):
    pass


def _stable_probe(index,mutate):
    def test(self):
        first=_package();second=deepcopy(first);mutate(second)
        self.assertEqual(_publication_identity("A",first,"instagram"),_publication_identity("A",second,"instagram"))
    setattr(Department5PublishingHardeningTests,f"test_{index:02d}_volatile_regeneration_does_not_republish",test)


def _distinct_probe(index,mutate):
    def test(self):
        first=_package();second=deepcopy(first);mutate(second)
        self.assertNotEqual(_publication_identity("A",first,"instagram"),_publication_identity("A",second,"instagram"))
    setattr(Department5PublishingHardeningTests,f"test_{index:02d}_semantic_change_has_distinct_identity",test)


volatile=[
 lambda p:p.update(package_id="renamed"),lambda p:p.update(release_id="release-2"),lambda p:p.update(created_at="later"),
 lambda p:p["caption"].update(created_at="later"),lambda p:p["image"].update(image_path="new/folder/renamed.png"),
 lambda p:p.update(status="ready"),lambda p:p.update(builder_version="99"),lambda p:p.update(brand_config_hash="same-render"),
 lambda p:p.update(content_version="new"),lambda p:p.update(destination="Instagram Feed"),
 lambda p:p.update(warnings=["diagnostic"]),lambda p:p.update(selected_facts=[]),lambda p:p.update(verified_fact_refs=[]),
 lambda p:p["caption"].update(word_count=2),lambda p:p["caption"].update(confidence=.9),
 lambda p:p["image"].update(final_output_hash="derived"),lambda p:p["image"].update(source_pages=[1]),
 lambda p:p["image"].update(provenance_id="trace-1"),lambda p:p.update(language="English"),lambda p:p.update(updated_at="later"),
]
semantic=[
 lambda p:p.update(package_type="carousel"),lambda p:p.update(content_idea_id="idea-2"),lambda p:p.update(master_concept_id="concept-2"),
 lambda p:p.update(language_code="ar"),lambda p:p.update(creative_production_contract_version="2.0.0"),
 lambda p:p.update(CTA="Request details"),lambda p:p["caption"].update(full_caption="Different approved caption"),
 lambda p:p.update(hashtags=[{"hashtag":"#Erbil"}]),lambda p:p["image"].update(image_hash="hash-2"),lambda p:p["image"].update(source_asset_ids=["asset-2"]),
]
for i,mutation in enumerate(volatile,1):_stable_probe(i,mutation)
for i,mutation in enumerate(semantic,21):_distinct_probe(i,mutation)


def _inactive_probe(index,status):
    def test(self,status=status):self.assertFalse(_is_active_job({"status":status}))
    setattr(Department5PublishingHardeningTests,f"test_{index:02d}_{status}_cannot_be_reclaimed",test)


def _ambiguous_post_probe(index,exception):
    def test(self,exception=exception):
        client=MetaHttpClient("secret","v1",transport=lambda *_:(_ for _ in ()).throw(exception))
        with self.assertRaises(MetaAdapterError) as raised:client.request("POST","ig/media_publish",{"creation_id":"c"})
        self.assertEqual(raised.exception.classification,"uncertain_remote_state");self.assertFalse(raised.exception.retryable);self.assertTrue(raised.exception.safe_details["request_submitted"]);self.assertNotIn("secret",str(raised.exception))
    setattr(Department5PublishingHardeningTests,f"test_{index:02d}_ambiguous_post_failure_fails_closed",test)


for i,status in enumerate(("publishing","publishing_uncertain","published","published_with_warnings","failed"),31):_inactive_probe(i,status)
for i,exception in enumerate((TimeoutError("timeout"),ConnectionError("reset"),OSError("network"),RuntimeError("transport"),ValueError("bad transport")),36):_ambiguous_post_probe(i,exception)


if __name__=="__main__":unittest.main()
