# Department 3 Phase 4D.2 — Legacy Strategy / Opportunity / Creative-Director Demotion

This package demotes the three remaining live legacy calls captured in Phase 4D.0.

- MarketingStrategyAgent remains available only as advisory/compatibility output.
- VisualOpportunityEngine remains available only as opportunity/candidate compatibility output.
- CreativeDirectorAgent remains temporarily for the old ScenePlanner/ShotPlanner artifact schema, but it is explicitly non-authoritative and cannot emit Approved Content Plan or VDC authority.

This phase does not delete CreativeDirectorAgent or replace its schema with VDC output; that requires the exact ScenePlanner/ShotPlanner creative-artifact contract.

## Install
Extract into `C:\Users\alits\instagram-agent`, then run:

```powershell
python install_phase4d2.py
python verify_phase4d2.py
python -m pytest -q tests/test_department3_legacy_live.py tests/test_department3_phase4d2_entrypoint.py
python -m pytest -q
```
