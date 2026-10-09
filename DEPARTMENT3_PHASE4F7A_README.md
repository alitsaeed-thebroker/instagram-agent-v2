# Department 3 Phase 4F.7A — Authentic Upstream Semantic Discovery Audit

This is a read-only audit.

The uploaded Phase 4F.6 artifact proved that reconstruction was contaminated by:
- the generated `visual-opportunities` file itself
- simulation `category-selection.json`
- duplicate ID/path representations

4F.7A scans only authentic upstream source families and maps each real asset to the source
files that actually contain its semantics.

## Explicitly excluded

- `output/visual-opportunities/`
- `output/simulation/`
- `output/audits/`
- `output/releases/`
- `output/backups/`
- provenance
- produced/branded images
- post packages
- publishing/queue state

## Authentic source families searched

- source-images
- visual-assets
- visual-inventory
- asset-intelligence
- plan-intelligence
- creative-intelligence
- campaign-intelligence
- knowledge / markdown
- input

## Output per asset

- sources_found
- classifications_found
- paths_found
- evidence_found
- plan_relationships_found
- canonical_source

## Run

Recommended, using the current Phase 4F.6 artifact only as a TARGET-ID list:

```powershell
python -m pytest -q tests/test_department3_phase4f7a_semantic_discovery.py
python run_department3_phase4f7a_semantic_discovery.py --project "Beverly Hills" --asset-file "output\\visual-opportunities\\Beverly Hills\\Beverly Hills-visual-opportunities.json"
python -m pytest -q
```

The visual-opportunities file is NOT used as a semantic source; it only supplies the asset IDs
to trace.

## Safety

- production files modified: 0
- Meta writes: 0
- Instagram publish attempts: 0
- no network
