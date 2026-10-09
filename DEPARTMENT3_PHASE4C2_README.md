# Department 3 Phase 4C.2 — Installer Syntax Fix

Phase 4C.1 failed before modifying the repository because the generated installer contained:

`BRIDGE = r`

instead of a valid multiline Python string.

Therefore:
- no `app.py` patch occurred
- no `src/execution/stages.py` patch occurred
- the verifier correctly failed
- the existing repository remained healthy

This corrected installer is self-contained and valid Python.

## Apply

Extract directly into:

`C:\Users\alits\instagram-agent`

Then run:

```powershell
python install_phase4c2.py
python verify_phase4c2.py
python -m pytest -q tests/test_department3_phase4c2_live_entrypoints.py
python -m pytest -q tests/test_department3_live_orchestration.py tests/test_department3_runtime_guard.py
python -m pytest -q
```

## Safety

The installer:
- parses both targets before editing
- backs up both targets
- patches only the canonical imports + bridge
- parses both targets after editing
- verifies all required markers
- restores files modified during the run if patching fails
