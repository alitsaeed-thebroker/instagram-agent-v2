import json
import tempfile
from pathlib import Path
import pytest
from src.department3.legacy_live import run_legacy_creative_compat, run_legacy_strategy_advisory, run_legacy_visual_opportunity_compat
from src.department3.runtime_guard import RuntimeAuthorityViolation

def test_strategy_plain_output_is_preserved():
    payload={'strategy':{'audience':'buyer'}}
    assert run_legacy_strategy_advisory(lambda: payload) is payload

def test_strategy_cannot_emit_canonical_plan():
    with pytest.raises(RuntimeAuthorityViolation):
        run_legacy_strategy_advisory(lambda:{'approved_content_plan':{'project_id':'x'}})

def test_visual_opportunity_json_path_is_checked():
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'opportunities.json'; path.write_text(json.dumps({'items':[]}),encoding='utf-8')
        assert run_legacy_visual_opportunity_compat(lambda:path)==path

def test_creative_director_cannot_emit_vdc():
    with pytest.raises(RuntimeAuthorityViolation):
        run_legacy_creative_compat(lambda:{'vdc':{'contract_id':'x'}})
