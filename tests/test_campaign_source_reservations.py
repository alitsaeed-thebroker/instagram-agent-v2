from collections import Counter
from copy import deepcopy
import unittest

from src.planning.engine import _project_assets, _reserved_candidates


class SourceReservationTests(unittest.TestCase):
    def test_unreserved_reference_does_not_crash_or_gain_authority(self):
        missing = 'src_25510092d4274168d327'
        assets = {missing: {'asset_id': missing}, 'approved': {
            'asset_id': 'approved', 'project_id': 'Beverly Hills',
            'quality_score': 90, 'confidence': .9, 'source_hash': 'exact-source'}}
        reservations = {'approved': {'maximum_reuse_count': 2}}
        before = deepcopy((assets, reservations))
        result = _reserved_candidates([missing, 'approved', 'unknown'], assets, Counter(), reservations)
        self.assertEqual([x['asset_id'] for x in result], ['approved'])
        self.assertEqual(result[0]['source_hash'], 'exact-source')
        self.assertEqual((assets, reservations), before)

    def test_reservation_cannot_import_another_project_asset(self):
        inventory = {'available_exterior_images': [
            {'asset_id': 'other', 'project_id': 'VELORIA BY SHAHAN CO'},
            {'asset_id': 'local', 'project_id': 'Beverly Hills', 'confidence': .9}]}
        assets = {a['asset_id']: a for a in _project_assets(inventory, 'Beverly Hills')}
        result = _reserved_candidates(['other', 'local'], assets, Counter(), {'other': {}, 'local': {}})
        self.assertEqual([a['asset_id'] for a in result], ['local'])

    def test_all_unreserved_is_empty(self):
        self.assertEqual(_reserved_candidates(['missing'], {'missing': {'asset_id': 'missing'}}, Counter(), {}), [])
