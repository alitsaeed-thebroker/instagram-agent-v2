import unittest
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from src.publishing.controlled import ControlledPublishError, resolve_item
from src.publishing.controlled import _controlled_publish_locked
from src.publishing.meta import MetaHttpClient


class ControlledPublishSelectionTests(unittest.TestCase):
    def setUp(self):
        self.queue={"items":[
            {"queue_item_id":"q1","package_id":"p","platform":"instagram","status":"preflight_ready"},
            {"queue_item_id":"q2","package_id":"p","platform":"facebook","status":"preflight_ready"},
            {"queue_item_id":"old","package_id":"old","platform":"instagram","status":"superseded"},
        ]}
    def test_explicit_queue_id_required_and_resolved(self):
        self.assertEqual(resolve_item(self.queue,queue_item_id="q1")["queue_item_id"],"q1")
        with self.assertRaises(ControlledPublishError):resolve_item(self.queue)
    def test_package_ambiguity_is_rejected(self):
        with self.assertRaisesRegex(ControlledPublishError,"more than one"):resolve_item(self.queue,package_id="p")
    def test_inactive_item_is_not_selectable(self):
        with self.assertRaises(ControlledPublishError):resolve_item(self.queue,queue_item_id="old")
    def test_meta_write_audit_has_no_credentials(self):
        events=[]
        client=MetaHttpClient("secret-token","v23.0",transport=lambda method,path,params:{"id":"remote-1"},audit=lambda *args:events.append(args))
        client.request("POST","ig/media",{"image_url":"https://example.test/image.png"})
        self.assertEqual(events,[('POST','ig/media',True,{'id':'remote-1'})]);self.assertNotIn("secret-token",repr(events))

    def test_stale_ready_queue_cannot_publish_unverified_unit_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            foundation=MagicMock()
            foundation.output=root/"output"
            queue={"items":[{"queue_item_id":"q1","package_id":"p1","status":"preflight_ready"}]}
            packages={"p1":{"package_id":"p1","caption":{"full_caption":"Unit layout, Type D, 5-bedroom"},
                            "slides":[{"source_asset_ids":["unverified-plan"]}]}}
            ledger=MagicMock();ledger.get.return_value=None
            adapter=MagicMock();host=MagicMock()
            with (patch("src.publishing.controlled._state",return_value=(foundation,queue,packages,{})),
                  patch("src.publishing.controlled.PublicationLedger",return_value=ledger)):
                with self.assertRaisesRegex(ControlledPublishError,"Canonical plan integrity failed"):
                    _controlled_publish_locked(root,"Beverly Hills",queue_item_id="q1",confirm=True,adapter=adapter,r2_host=host)
            adapter.validate_credentials.assert_not_called()
            adapter.publish.assert_not_called()
            host.status.assert_not_called()

if __name__ == "__main__":unittest.main()
