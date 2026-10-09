import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.department1.pipeline import Department1Config, Department1Error, Department1Pipeline


class SummaryRepairTests(unittest.TestCase):
    def run_stage(self, payload, repair):
        client = SimpleNamespace(responses=SimpleNamespace(create=Mock(side_effect=[
            SimpleNamespace(output_text=json.dumps(payload)),
            SimpleNamespace(output_text=json.dumps(repair)),
        ])))
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / 'VELORIA BY SHAHAN CO'
            project.mkdir()
            pipe = Department1Pipeline(project, output_root=Path(td)/'output',
                                       config=Department1Config(allow_external_ai=True), client=client)
            result = pipe._ai_json(stage='ANALYZE', instructions='ANALYZE', evidence={})
        return result, client

    def payload(self):
        return {'project': 'VELORIA BY SHAHAN CO', 'stage': 'ANALYZE',
                'summary': {'observations': ['Layout requires validation']},
                'data': {'sources': [{'source_id': 'original-1', 'page': 7}],
                         'unit_plan': {'dimensions': None, 'validation': 'pending'}},
                'unknowns': ['Dimensions unavailable'], 'warnings': ['Validate unit plan']}

    def test_summary_only_repair_preserves_provenance_and_unit_plan(self):
        original = self.payload()
        result, client = self.run_stage(original, {'summary': 'Layout requires validation'})
        for key in ('project', 'stage', 'data', 'unknowns', 'warnings'):
            self.assertEqual(result[key], original[key])
        self.assertEqual(client.responses.create.call_count, 2)

    def test_valid_summary_needs_no_repair(self):
        original = self.payload()
        original['summary'] = 'Complete'
        result, client = self.run_stage(original, {})
        self.assertEqual(result, original)
        self.assertEqual(client.responses.create.call_count, 1)

    def test_cross_project_and_invalid_data_fail_before_repair(self):
        for key, value in [('project', 'Beverly Hills'), ('data', []), ('stage', 'EXTRACT')]:
            payload = copy.deepcopy(self.payload())
            payload[key] = value
            with self.subTest(key=key), self.assertRaises(Department1Error):
                self.run_stage(payload, {'summary': 'Complete'})

    def test_invalid_or_extra_repair_fields_fail_closed(self):
        for repair in ({'summary': []}, {'summary': 'Complete', 'data': {}}, {}):
            with self.subTest(repair=repair), self.assertRaises(Department1Error):
                self.run_stage(self.payload(), repair)
