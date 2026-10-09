# Department 3 Phase 4F.5 — Beverly Hills Canonical Visual Opportunity Regenerator

Phase 4F.3 correctly proved that no acceptable Department 3 visual-opportunity/inventory artifact currently exists for Beverly Hills.

This package regenerates one from existing local authenticated inputs only.

It scans:
- `output/source-images/**`
- `output/visual-assets/**`
- `output/visual-inventory/**`
- `output/asset-intelligence/**`
- `output/plan-intelligence/**`
- `input/**`

It excludes:
- audits
- releases
- provenance
- backups
- archives
- produced/branded images
- post packages

The resulting artifact is:

`output/visual-opportunities/Beverly Hills/Beverly Hills-visual-opportunities.json`

This is non-authoritative candidate input for `RealEstateStrategyBrain`.

## Safety

- no network
- no Meta writes
- no Instagram publishing
- no production media generation

## Run

```powershell
python -m pytest -q tests/test_department3_phase4f5_regenerator.py
python run_department3_phase4f5_regenerator.py --project "Beverly Hills"
python run_department3_phase4f_certification.py --project "Beverly Hills"
python -m pytest -q
```

If the regenerator finds zero valid source assets, do not loosen it. That means Beverly Hills source-image state must first be recreated from the preserved project inputs.
