# Department 3 Phase 4C.1 — Live Bridge Installation Fix

The Phase 4C modules installed successfully, but the installer did not patch the two live
orchestration files. The verifier correctly detected:

- app.py live_import = False
- app.py guard_import = False
- app.py bridge = False

The full suite remained green, so no production regression occurred.

This patch fixes only that installation gap.

## It patches

- `app.py`
- `src/execution/stages.py`

It adds:

- the canonical live orchestration import
- the runtime authority guard import
- `_department3_canonical_approve(...)`

## Safety

Before modifying:
- both Python files must parse
- Phase 4C modules must exist

Before every write:
- original file is backed up under `output/backups/department3-phase4c1/`

After every write:
- the file is parsed again
- verification checks all required markers

If an exception occurs, files already modified in the same run are restored.

## Run

Extract into the repository root, then:

```powershell
python install_phase4c1.py
python verify_phase4c1.py
python -m pytest -q tests/test_department3_phase4c1_live_entrypoints.py
python -m pytest -q tests/test_department3_live_orchestration.py tests/test_department3_runtime_guard.py
python -m pytest -q
```
