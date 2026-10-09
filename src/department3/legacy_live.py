from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Callable, Mapping
from .runtime_guard import assert_noncanonical_output

class LegacyLiveDemotionError(RuntimeError):
    pass

def _load_if_json_path(value: Any) -> Any:
    path = value if isinstance(value, Path) else Path(value) if isinstance(value, str) and value.lower().endswith('.json') else None
    if path is None or not path.is_file():
        return value
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return value

def _assert_legacy_non_authority(module: str, value: Any) -> None:
    inspected = _load_if_json_path(value)
    if isinstance(inspected, Mapping):
        assert_noncanonical_output(module, inspected)

def run_legacy_strategy_advisory(runner: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    result = runner(*args, **kwargs)
    _assert_legacy_non_authority('src.ai.agents.marketing_strategy_agent', result)
    return result

def run_legacy_visual_opportunity_compat(runner: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    result = runner(*args, **kwargs)
    _assert_legacy_non_authority('src.planning.engine', result)
    return result

def run_legacy_creative_compat(runner: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    result = runner(*args, **kwargs)
    _assert_legacy_non_authority('src.ai.agents.creative_director_agent', result)
    return result
