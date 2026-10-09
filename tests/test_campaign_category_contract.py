import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import ExitStack
from types import SimpleNamespace

from src.planning.engine import PlanningEngine, VisualOpportunityEngine
from src.department3.planning_cutover import legacy_artifact_to_candidates, cutover_legacy_planning_products, PlanningCutoverError, PlanningNoContentError
from tests.test_asset_first_planning import AssetFirstPlanningTests, asset
from tests.test_five_department_integration import FiveDepartmentIntegrationTests


def approved_contract(root, project, status='APPROVED'):
    reci=root/f'{project}-reci.json'
    reci.write_text(json.dumps({'project_id':project,'contract_role':'canonical_creative_opportunity_map',
        'opportunities':[{'opportunity_id':'architecture-approval','category':'architecture','status':'STRONG'}]}))
    value={'project_id':project,'contract_role':'canonical_campaign_decision_contract',
        'strategic_queue':[{'reci_opportunity_id':'architecture-approval','status':status}]}
    value['contract_hash']=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    campaign=root/f'{project}-decisions.json';campaign.write_text(json.dumps(value))
    return reci,campaign


class CampaignCategoryContractTests(unittest.TestCase):
    def test_architecture_approval_reaches_four_project_five_department_integration(self):
        fixture=FiveDepartmentIntegrationTests()
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        original=cutover_legacy_planning_products
        def with_approvals(**kwargs):
            reci,campaign=approved_contract(fixture.root,kwargs['project_id'])
            kwargs['planning_kwargs'].update(creative_intelligence_path=reci,campaign_intelligence_path=campaign)
            return original(**kwargs)
        with patch('tests.test_five_department_integration.cutover_legacy_planning_products',side_effect=with_approvals):
            for project in fixture.names:fixture.run_project(project)

    def test_blocked_architecture_stays_blocked(self):
        fixture=AssetFirstPlanningTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        inv=fixture.inventory([asset('a1')]);reci,campaign=approved_contract(fixture.root,'p',status='BLOCKED')
        with ExitStack() as stack:
            for name in ('VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY','CAMPAIGNS_OUTPUT_DIRECTORY','CONTENT_OUTPUT_DIRECTORY',
                         'ASSET_USAGE_OUTPUT_DIRECTORY','CONTENT_MEMORY_OUTPUT_DIRECTORY','REPORTS_OUTPUT_DIRECTORY'):
                stack.enter_context(patch(f'src.planning.engine.{name}',fixture.root/name))
            opp=VisualOpportunityEngine().run(fixture.knowledge,inv,fixture.strategy)
            with self.assertRaises(PlanningNoContentError):
                cutover_legacy_planning_products(project_id='p',planning_engine=PlanningEngine(),
                    planning_args=(fixture.knowledge,fixture.strategy,inv,opp),
                    planning_kwargs={'creative_intelligence_path':reci,'campaign_intelligence_path':campaign})

    def test_explicit_empty_is_not_malformed_or_campaign_fallback(self):
        self.assertEqual(legacy_artifact_to_candidates(project_id='P',content_document={'project_id':'P','content_ideas':[]},
            campaign_document={'items':[{'project_id':'Other'}]}),[])
        for document in ({'project_id':'P'}, {'project_id':'P','content_ideas':{}}, {'project_id':'Other','content_ideas':[]}):
            with self.assertRaises(PlanningCutoverError):legacy_artifact_to_candidates(project_id='P',content_document=document)
