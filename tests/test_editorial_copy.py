import json,tempfile,unittest
from pathlib import Path
from src.post_package.editorial_copy import apply_copy,copy_path
class EditorialCopyTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.item={'content_idea_id':'i','language_code':'en','package_type':'single_post','branded_item_ids':['b']}
  self.eligible={'b':{'content_idea_id':'i','source_asset_ids':['a']}}
  self.ctx={'assets':{'assets':[{'asset_id':'a','project_id':'p','source_hash':'hash'}]}}
  self.config={'version':'1.0.0','project_id':'p','items':[{'content_idea_id':'i','language_code':'en','asset_id':'a','source_hash':'hash','headline':'Overview','body':'An architectural rendering.','CTA':'Explore the project','alt_text':'An architectural rendering in a white frame with identity in a separate footer.'}]}
  path=copy_path(self.root,'p');path.parent.mkdir(parents=True);path.write_text(json.dumps(self.config))
 def tearDown(self):self.temp.cleanup()
 def test_bound_copy_updates_counts_and_digest(self):
  apply_copy(self.root,'p',[self.item],self.eligible,self.ctx)
  self.assertEqual(self.item['character_count'],len(self.item['full_caption']));self.assertEqual(len(self.item['editorial_copy_sha256']),64)
 def test_foreign_project_rejected(self):
  self.ctx['assets']['assets'][0]['project_id']='q'
  with self.assertRaises(ValueError):apply_copy(self.root,'p',[self.item],self.eligible,self.ctx)
 def test_changed_hash_rejected(self):
  self.ctx['assets']['assets'][0]['source_hash']='changed'
  with self.assertRaises(ValueError):apply_copy(self.root,'p',[self.item],self.eligible,self.ctx)
 def test_other_project_has_no_copy_override(self):
  apply_copy(self.root,'q',[self.item],self.eligible,self.ctx);self.assertNotIn('full_caption',self.item)

 def test_explicit_overview_role_is_carried_for_source_validation(self):
  self.config['items'][0]['publication_role']='project_overview'
  copy_path(self.root,'p').write_text(json.dumps(self.config))
  apply_copy(self.root,'p',[self.item],self.eligible,self.ctx)
  self.assertEqual(self.item['editorial_publication_role'],'project_overview')
 def test_unknown_editorial_role_is_rejected(self):
  self.config['items'][0]['publication_role']='unit_layout'
  copy_path(self.root,'p').write_text(json.dumps(self.config))
  with self.assertRaises(ValueError):apply_copy(self.root,'p',[self.item],self.eligible,self.ctx)
