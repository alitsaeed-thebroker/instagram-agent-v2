# Department 3 Phase 4D.0 — Exact Legacy Live Call-Site Capture

This is the evidence step immediately before replacement.

Why it is necessary: the current repository has already been modified by Phase 4C, while
the uploaded source/audit snapshots are older. Exact replacement must use the current source,
not historical line numbers.

This package changes **zero production files**.

It reads:
- `app.py`
- `src/execution/stages.py`

and records:
- legacy imports
- direct legacy constructor calls
- assignments involving legacy planner classes
- candidate `.run()`, `.build()`, `.plan()`, and `.generate()` calls
- enclosing function
- exact source segment
- surrounding source lines

## Run

Extract directly into the repository root, then:

```powershell
python tools\department3_phase4d0_capture.py
python -m pytest -q tests/test_department3_phase4d0_capture.py
```

Outputs:

- `output\audits\department3\department3-phase4d0-exact-legacy-callsites.json`
- `output\audits\department3\department3-phase4d0-exact-legacy-callsites.md`

Upload the JSON. The replacement package can then patch the exact live calls rather than
guessing from historical line numbers.
