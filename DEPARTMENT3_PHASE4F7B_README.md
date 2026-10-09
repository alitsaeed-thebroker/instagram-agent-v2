# Department 3 Phase 4F.7B — Authentic Upstream Asset Intelligence Rebuild

This package performs the actual upstream rebuild required after Phase 4F.7A proved that the accepted upstream asset-intelligence state was missing.

It rebuilds a canonical non-authoritative asset-intelligence artifact from preserved trusted sources only.

## Trusted inputs

- `output/source-images`
- `output/visual-assets`
- `output/visual-inventory`
- `output/plan-intelligence`
- `output/knowledge`
- `output/markdown`
- `input`

## Explicitly excluded

- `visual-opportunities`
- `simulation`
- `audits`
- `releases`
- `backups`
- `provenance`
- produced/branded images
- post packages
- publishing/queue state
- certification outputs

## Output

`output/asset-intelligence/Beverly Hills/Beverly Hills-asset-intelligence.json`

Each asset may contain:
- `asset_id`
- `category`
- `categories`
- `paths`
- `evidence`
- `plan_relationships`
- `source_files`
- `visible_summary`

This artifact is explicitly non-authoritative and is intended to feed the next canonical visual-opportunity reconstruction step.

## Safety

- no publishing
- no Meta writes
- no network
- no generated media
- no Department 3 authority changes

## Run

```powershell
python -m pytest -q tests/test_department3_phase4f7b_asset_intelligence_rebuild.py
python run_department3_phase4f7b_asset_intelligence_rebuild.py --project "Beverly Hills"
python -m pytest -q
```

Then inspect the rebuild metrics before moving to Phase 4F.7C.
