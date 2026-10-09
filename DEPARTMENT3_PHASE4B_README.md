# Department 3 Phase 4B — Advisory Intelligence Integration & Legacy Quarantine

This package continues the controlled Department 3 upgrade.

## What it changes

It adds three production modules:

- `src/department3/advisory.py`
- `src/department3/integration.py`
- `src/department3/legacy_quarantine.py`

And updates `src/department3/__init__.py`.

## New authority behavior

### Advisory engines

These remain useful:

- `src.creative_intelligence.engine`
- `src.campaign_intelligence.engine`

But their output must be wrapped in `AdvisoryEnvelope`.

An advisory envelope is explicitly:

`authoritative = False`

It may influence canonical strategy through `Department3CanonicalPlanner`, but it cannot itself become an Approved Content Plan.

### Legacy planners

These remain compatibility-only:

- `src.ai.agents.content_planner`
- `src.ai.agents.creative_director_agent`
- `src.ai.agents.marketing_strategy_agent`
- `src.ai.agents.campaign_planner`
- `src.ai.agents.visual_art_director_agent`
- `src.planning.engine`

Their output can be passed through `LegacyModuleAdapter` only as non-authoritative compatibility data.

If legacy output attempts to contain canonical fields such as:

- `approved_content_plan`
- `visual_direction_contract`
- `vdc`
- `authority_signature`
- `contract_integrity_hash`

the quarantine gate fails closed.

## Important scope boundary

This package does NOT yet patch the existing application orchestration to force every production call through the new adapters.

That wiring must use the exact live orchestration source and belongs to the next subphase after this contract passes.

This avoids blind modification of the already-certified pipeline.

## Install

Extract the package, then run from the repository root:

```powershell
python <EXTRACTED_FOLDER>\install_phase4b.py
```

If you extract the ZIP directly into the repository root, the files will already be in place and the installer is optional.

## Tests

```powershell
python -m pytest -q tests/test_department3_advisory_integration.py tests/test_department3_legacy_quarantine.py tests/test_department3_phase4b_contract.py
python -m pytest -q
```

## Expected outcome

- advisory intelligence remains usable
- advisory output is explicitly non-authoritative
- cross-project advisory contamination fails closed
- advisory fingerprints become part of Approved Content Plan decisions
- legacy modules cannot emit Approved Content Plans or VDCs
- Department 4 is untouched
- full repository regression remains green

After this passes, the next step is Phase 4C: wire the live Department 3 orchestration through `Department3CanonicalPlanner` and enforce the new authority boundary at production entrypoints.
