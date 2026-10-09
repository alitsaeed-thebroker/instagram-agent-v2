# Department 3 Phase 5 — Final Re-Audit & Freeze Certification

This package performs the final independent Department 3 certification.

It does **not** add new strategy features and does **not** modify production authority.

## Certification areas

- canonical authority ownership
- legacy demotion/quarantine
- runtime authority guards
- real-estate strategy brain
- authentic Beverly Hills provenance chain
- self-reference protection
- simulation/release/provenance exclusion
- feed/carousel/Story behavior
- evidence discipline
- plan/layout fail-closed behavior
- Department 4 boundary
- publishing/network isolation
- critical file hashes
- freeze manifest generation

## Freeze results

One of:

- `DEPARTMENT 3 — FREEZE PASS`
- `DEPARTMENT 3 — PASS WITH CONDITIONS`
- `DEPARTMENT 3 — FAIL`

## Outputs

- `output/audits/department3/department3-phase5-beverly-hills-freeze-certification.json`
- `output/audits/department3/department3-phase5-beverly-hills-freeze-certification.md`
- `output/audits/department3/DEPARTMENT3_FREEZE.json`

## Important

`DEPARTMENT3_FREEZE.json` records critical file hashes.

Any future authority-changing modification or critical hash change requires Department 3 recertification.

## Run

```powershell
python install_phase5_department3_freeze.py
python verify_phase5_department3_freeze.py

python -m pytest -q tests/test_department3_phase5_authority.py tests/test_department3_phase5_provenance.py tests/test_department3_phase5_strategy_quality.py tests/test_department3_phase5_plan_integrity.py tests/test_department3_phase5_boundary.py tests/test_department3_phase5_freeze.py

python run_department3_phase5_freeze_certification.py --project "Beverly Hills"

python -m pytest -q
```

The package performs:
- Meta writes: 0
- Instagram publishing attempts: 0
- publishing queue mutations: 0
- Department 4 production mutations: 0
- network publishing operations: 0
