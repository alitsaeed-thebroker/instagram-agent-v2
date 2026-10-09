# Department 3 Phase 4D.1 — Canonical Planning Authority Cutover

This package replaces the exact live `PlanningEngine().run(...)` authority call captured in Phase 4D.0.

Before:
PlanningEngine -> campaign_plan/content_plan -> downstream

After:
PlanningEngine -> temporary compatibility candidate artifacts
-> runtime authority guard
-> canonical candidate normalization
-> LiveDepartment3Orchestrator
-> Department3CanonicalPlanner
-> Department3StrategyAuthority
-> ApprovedContentPlan
-> same campaign_plan/content_plan paths rewritten with canonical authority metadata
-> downstream

PlanningEngine is no longer the authoritative approver. It remains temporarily only as a compatibility candidate generator.

## Safety
- exact captured call must appear exactly once
- installer aborts on source drift
- app.py is backed up before modification
- app.py is parsed after modification
- rollback occurs on syntax/verification failure
- missing canonical fields fail closed; nothing is invented

## Install
Extract directly into:
`C:\Users\alits\instagram-agent`

Then run:

```powershell
python install_phase4d1.py
python verify_phase4d1.py
python -m pytest -q tests/test_department3_planning_cutover.py tests/test_department3_phase4d1_entrypoint.py
python -m pytest -q
```
