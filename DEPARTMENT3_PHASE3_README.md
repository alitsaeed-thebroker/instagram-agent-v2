# Department 3 Phase 3 — Runtime Authority Trace

This package is **non-destructive**.

It does not modify production source. It runs the existing Department 3/VDC/D4-boundary tests in-process while tracing:

- runtime calls into legacy authority candidates
- runtime calls into canonical Visual Art Director/VDC code
- runtime calls into Department 4 boundary modules
- repository file reads and writes
- authoritative-looking output writes
- caller → callee edges

## Install

Extract into:

`C:\Users\alits\instagram-agent`

Files added:

- `run_department3_phase3_runtime_authority_trace.py`
- `tools/department3_phase3_runtime_authority_trace.py`
- `tests/test_department3_phase3_runtime_authority_trace.py`

## Run

```powershell
cd C:\Users\alits\instagram-agent
python run_department3_phase3_runtime_authority_trace.py
python -m pytest -q tests/test_department3_phase3_runtime_authority_trace.py
```

Generated:

- `output\audits\department3\department3-phase3-runtime-authority-trace.json`
- `output\audits\department3\department3-phase3-runtime-authority-trace.md`

## Important

This phase observes the runtime behavior of the existing test suite. It intentionally does **not** invoke live publishing or make Meta writes.

A legacy module executing during a test is not automatically a defect. A production repair should only follow when the runtime trace or a targeted adversarial test proves that the module can independently control or overwrite an authoritative Department 3 artifact, or bypass the Visual Art Director/VDC chain.
