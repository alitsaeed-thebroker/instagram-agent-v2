# Department 3 Phase 4F.7C — Canonical Visual Opportunity Reconstruction from Authentic Asset Intelligence

This phase consumes only:

`output/asset-intelligence/Beverly Hills/Beverly Hills-asset-intelligence.json`

It does not read:
- simulation
- releases
- provenance
- audits
- previous visual-opportunity files

## Reconstruction rules

### Carousel
Created only when multiple authenticated assets share a structured category:
- masterplan
- exterior
- interior
- commercial

### Story
Created for:
- location
- amenity

### Feed
Used conservatively for:
- single structured assets
- generic `project feature` assets

### Plans / layouts
Plan-like assets are blocked from marketing unless `plan_relationships` is non-empty.

## Evidence

All recovered asset evidence is preserved into the opportunity layer.

## Output

`output/visual-opportunities/Beverly Hills/Beverly Hills-visual-opportunities.json`

## Safety

- no publishing
- no Meta writes
- no network
- no Department 3 authority changes

## Run

```powershell
python -m pytest -q tests/test_department3_phase4f7c_opportunity_reconstruction.py
python run_department3_phase4f7c_opportunity_reconstruction.py --project "Beverly Hills"
python run_department3_phase4f_certification.py --project "Beverly Hills"
python -m pytest -q
```

After certification, inspect the real distribution of feed/carousel/Story before the final Department 3 re-audit.
