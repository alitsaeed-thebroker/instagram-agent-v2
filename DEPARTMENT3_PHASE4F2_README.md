# Department 3 Phase 4F.2 — Self-Reference Exclusion Fix

The Phase 4F.1 run returned `PASS_WITH_CONDITIONS`, but its reported source was:

`output/audits/department3/department3-phase4f-beverly-hills-certification.json`

That is the certification report itself, so the result is not valid certification evidence.

Phase 4F.2 fixes this by excluding:

- `output/audits/**`
- backup/archive trees
- any Phase 4F certification filename

from source discovery.

The runner must now locate a real project artifact such as:

- creative-intelligence output
- campaign-intelligence output
- visual-opportunity output
- visual inventory
- source-image ranking/selection
- asset-intelligence output

If no real artifact is found, it fails rather than certifying against its own report.

## Apply

Replace:

`src/department3/phase4f_certification.py`

with this package version.

## Run

```powershell
python -m pytest -q tests/test_department3_phase4f2_self_reference.py
python run_department3_phase4f_certification.py --project "Beverly Hills"
python -m pytest -q
```

Do not treat the previous Phase 4F.1 `PASS_WITH_CONDITIONS` as certification.
