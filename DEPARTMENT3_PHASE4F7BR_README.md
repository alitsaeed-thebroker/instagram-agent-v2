# Department 3 Phase 4F.7B-R — Beverly Hills Authentic Source Asset Recovery

Phase 4F.7A and 4F.7B proved the historical output tree no longer contains enough genuine upstream asset state for Beverly Hills.

This recovery phase goes directly back to preserved original project inputs.

## Reads

- `input/Beverly Hills/**`
- root-level `input/**` files whose paths identify Beverly Hills
- preserved source/upload/original trees if present
- optional trusted current metadata from:
  - `output/source-images/Beverly Hills`
  - `output/visual-assets/Beverly Hills`
  - `output/plan-intelligence/Beverly Hills`

## Explicitly ignores

- visual opportunities
- simulation
- audits
- releases
- provenance
- backups
- produced/branded images
- post packages
- publishing/queue/certification state

## Output

`output/source-images/Beverly Hills/Beverly Hills-recovered-source-inventory.json`

The output contains:
- fresh deterministic `src_*` asset IDs from SHA-256
- original image paths
- source file hashes
- recovered visual categories where possible
- evidence links where trusted metadata still exists
- plan relationship state
- fail-closed plan restrictions
- source document inventory

## Safety

- no network
- no publishing
- no Meta writes
- no media generation
- no Department 3 authority changes

## Run

```powershell
python -m pytest -q tests/test_department3_phase4f7br_source_asset_recovery.py
python run_department3_phase4f7br_source_asset_recovery.py --project "Beverly Hills"
python -m pytest -q
```

After recovery, inspect the metrics before rerunning 4F.7B asset-intelligence reconstruction.
