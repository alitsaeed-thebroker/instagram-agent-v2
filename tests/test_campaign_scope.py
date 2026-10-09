import unittest,tempfile,json
from pathlib import Path
from src.project_sequence import sequence_error,contract,campaign_scope

class CampaignScopeTests(unittest.TestCase):
    def setUp(self):
        self.scope={"campaign_id":"new","project_id":"A","authorization":"start new campaign","legacy_publication_identities":["old"]}
        self.item={"project_id":"A","platform":"Instagram","project_sequence":contract("overview"),"campaign_scope":self.scope}
        self.old={"project_id":"A","platform":"Instagram","status":"published","publication_identity":"old"}
    def test_authorized_legacy_history_does_not_block_new_overview(self):
        self.assertIsNone(sequence_error(self.item,[self.old]))
        self.assertEqual(self.old['publication_identity'],'old')
    def test_unknown_history_is_not_silently_excluded(self):
        self.assertIsNotNone(sequence_error(self.item,[{**self.old,'publication_identity':'unknown'}]))
    def test_new_campaign_requires_overview_before_site(self):
        site={**self.item,'project_sequence':contract('site_plan')}
        self.assertIsNotNone(sequence_error(site,[self.old]))
        overview={**self.old,'publication_identity':'new-overview','project_sequence':contract('overview'),'campaign_scope':self.scope}
        self.assertIsNone(sequence_error(site,[self.old,overview]))
        self.assertIsNotNone(sequence_error(self.item,[self.old,overview]))
    def test_invalid_scope_fails_closed(self):
        self.item['campaign_scope']={**self.scope,'project_id':'B'}
        self.assertIsNotNone(sequence_error(self.item,[self.old]))
    def test_multiple_active_campaigns_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'input/campaigns';path.mkdir(parents=True)
            c={'campaign_id':'new','project_id':'A','authorization':'start new campaign','status':'PREPARING','prior_publications':[]}
            (path/'a.json').write_text(json.dumps(c));(path/'b.json').write_text(json.dumps({**c,'campaign_id':'other'}))
            with self.assertRaises(ValueError):campaign_scope(root,'A')
