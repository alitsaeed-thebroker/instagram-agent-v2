# Department 3 — Phase 1 Audit Package

This package is intentionally non-destructive.

It adds a static architecture/authority audit that runs against the actual local repository and produces:

- `output/audits/department3/department3-phase1-authority-audit.json`
- `output/audits/department3/department3-phase1-authority-audit.md`

## Install

Extract the ZIP directly into:

`C:\Users\alits\instagram-agent`

It adds:

- `run_department3_phase1_audit.py`
- `tools/department3_phase1_audit.py`
- `tests/test_department3_phase1_audit.py`

It does not replace production Department 3 code yet because the current source snapshot was not available in the connected file sources.

## Run

PowerShell:

```powershell
cd C:\Users\alits\instagram-agent
python run_department3_phase1_audit.py
python -m pytest -q tests/test_department3_phase1_audit.py
```

Then send back these two files:

- `output\audits\department3\department3-phase1-authority-audit.json`
- `output\audits\department3\department3-phase1-authority-audit.md`

The next phase can then modify the exact current Department 3 files rather than relying on stale historical code.
