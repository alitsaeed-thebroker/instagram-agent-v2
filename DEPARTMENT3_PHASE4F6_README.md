# Department 3 Phase 4F.6 — Canonical Visual Opportunity Quality Reconstruction

Phase 4F.5 successfully recreated a valid visual-opportunity artifact, but quality was too flat:

- 26 opportunities
- 0 with evidence
- 26 feed
- 0 carousel
- 0 Story

Phase 4F.6 reconstructs richer semantics from existing structured project metadata.

## Improvements

- recover visual categories
- recover evidence/fact references when present
- group related exterior/interior/masterplan/commercial assets into carousel opportunities
- map amenity/lifestyle assets to Story opportunities
- map location content to Story hook opportunities
- preserve plan/layout assets but mark unsupported ones `PLAN_EVIDENCE_REQUIRED`
- preserve authenticated asset identity/path
- remain non-authoritative

## Safety

- no publishing
- no Meta writes
- no network
- no generated media

## Run

```powershell
python -m pytest -q tests/test_department3_phase4f6_quality_reconstruction.py
python run_department3_phase4f6_quality_reconstruction.py --project "Beverly Hills"
python run_department3_phase4f_certification.py --project "Beverly Hills"
python -m pytest -q
```

Target certification should show a meaningful mixture of feed/carousel/Story when the underlying Beverly Hills metadata supports those categories.
