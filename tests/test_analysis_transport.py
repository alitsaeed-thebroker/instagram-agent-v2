import unittest,tempfile,hashlib,io
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from src.ai.agents.asset_intelligence_agent import _vision_payload,AssetIntelligenceAgent
from src.post_package.pipeline import _caption_record
class AnalysisTransportTests(unittest.TestCase):
 def test_complete_image_is_bounded_without_changing_source(self):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/'source.png';image=Image.new('RGB',(3000,1500),'white');image.paste('red',(0,0,1500,1500));image.save(p);before=hashlib.sha256(p.read_bytes()).hexdigest()
   payload,mime=_vision_payload(p);output=Image.open(io.BytesIO(payload))
   self.assertEqual(output.size,(2048,1024));self.assertEqual(mime,'image/jpeg');self.assertLess(len(payload),4*1024*1024)
   self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),before)
   self.assertGreater(output.getpixel((1,512))[0],200);self.assertGreater(output.getpixel((2046,512))[1],200)
 def test_community_caption_does_not_claim_completed_facilities(self):
  group={'language_code':'en','group_type':'carousel','content_idea_id':'community','content_group_id':'g','release_id':'r','branded_item_ids':['a','b'],'platform':'Instagram Feed'}
  members=[{'plan':{'asset_type':'amenity'},'source_asset_ids':['a']},{'plan':{'asset_type':'amenity'},'source_asset_ids':['b']}]
  facts={'selected_facts':[],'fact_relevance_scores':{},'excluded_facts':[],'exclusion_reasons':{}}
  ctx={'knowledge':{},'content':{'content_ideas':[{'content_idea_id':'community','content_category':'community_lifestyle'}]}}
  with patch('src.post_package.pipeline.canonical_project_identity',return_value={'project_name':'P'}),patch('src.post_package.pipeline._caption_registry',return_value={}):caption=_caption_record('P',group,members,facts,ctx)
  self.assertIn('project brochure',caption['full_caption']);self.assertIn('do not confirm completed facilities',caption['full_caption']);self.assertNotIn('coordinated views',caption['full_caption'])
