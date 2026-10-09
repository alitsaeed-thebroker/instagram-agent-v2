# Department 3 Phase 4B.1 — Advisory Fingerprint Provenance Fix

The Phase 4B test failure exposed one narrow provenance bug.

`AdvisoryEngineAdapter` correctly created a provider fingerprint, but
`Department3CanonicalPlanner` converted the envelope to a dictionary and Phase 4A's
strategy authority hashed that dictionary again. The Approved Content Plan therefore
stored a second hash instead of the original provider fingerprint.

This patch fixes the boundary so the exact provider-issued advisory fingerprints are
preserved in every StrategyDecision.

It does not change the authority model and does not touch Department 4.

## Apply

Extract this ZIP directly into:

`C:\Users\alits\instagram-agent`

It replaces only:

- `src/department3/integration.py`

and adds:

- `tests/test_department3_phase4b1_fingerprint.py`

## Test

```powershell
python -m pytest -q tests/test_department3_advisory_integration.py tests/test_department3_legacy_quarantine.py tests/test_department3_phase4b_contract.py tests/test_department3_phase4b1_fingerprint.py
python -m pytest -q
```
