# Department 3 Phase 2 — Behavioral Classification

This package performs **classification only**.

It does not modify Department 3, Department 4, app.py, configuration, output state, publication state, or Meta state.

## Install

Extract into:

`C:\Users\alits\instagram-agent`

It adds:

- `run_department3_phase2_behavioral_classification.py`
- `tools/department3_phase2_behavioral_classification.py`
- `tests/test_department3_phase2_behavioral_classification.py`

It expects the Phase 1 audit at:

`output\audits\department3\department3-phase1-authority-audit.json`

## Run

```powershell
cd C:\Users\alits\instagram-agent
python run_department3_phase2_behavioral_classification.py
python -m pytest -q tests/test_department3_phase2_behavioral_classification.py
```

Generated files:

- `output\audits\department3\department3-phase2-behavioral-classification.json`
- `output\audits\department3\department3-phase2-behavioral-classification.md`

## Meaning

The classifier separates findings into behavioral categories such as:

- `LIKELY_DETERMINISTIC_EXECUTION`
- `POTENTIAL_FAIL_OPEN_DEFAULT`
- `POTENTIAL_CREATIVE_DECISION`
- `UNAUTHORIZED_CREATIVE_AUTHORITY`
- `LEGACY_AUTHORITY_CANDIDATE`
- `AUTHORITY_AMBIGUITY`
- `STATE_OWNERSHIP_REVIEW`
- `CANONICAL_D3_REVIEW`
- `NEEDS_MANUAL_BEHAVIOR_TRACE`

No production repair should begin until the high-confidence categories are traced and verified.
