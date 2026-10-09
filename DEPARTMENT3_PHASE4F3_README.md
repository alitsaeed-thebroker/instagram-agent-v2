# Department 3 Phase 4F.3 — Source-Type Hardening

Phase 4F.2 correctly excluded audit files but still selected:

`output/releases/Beverly Hills/.../provenance/...json`

A release provenance audit is real project data, but it is not a Department 3 opportunity or
visual-inventory source. Using it flattened the certification into 19 generic feed items.

Phase 4F.3 fixes this by:

- excluding `releases/` and `provenance/`
- searching only known Department 3 / visual-intelligence source families
- requiring each candidate source to contain visual items with both:
  - an asset identity/path
  - a semantic category/description
- refusing generic release/package/status lists

## Apply

Replace:

`src/department3/phase4f_certification.py`

Then run:

```powershell
python -m pytest -q tests/test_department3_phase4f3_source_type.py
python run_department3_phase4f_certification.py --project "Beverly Hills"
python -m pytest -q
```

If the runner now reports that no eligible artifact exists, that is useful evidence: the next
step is to regenerate the real Beverly Hills D3 visual opportunity/inventory artifact rather
than certify against the wrong source type.
