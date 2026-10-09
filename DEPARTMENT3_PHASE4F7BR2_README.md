# Department 3 Phase 4F.7B-R2 — Beverly Hills Catalogue Embedded Visual Recovery

Phase 4F.7B-R proved the surviving authentic Beverly Hills state contains:
- 0 standalone project images
- 1 project document

R2 recovers embedded catalogue visuals directly from that preserved PDF.

## Recovery flow

Preserved Beverly Hills PDF
→ embedded raster image extraction
→ page provenance
→ SHA-256 deduplication
→ deterministic `src_*` IDs
→ dimension filtering
→ page-context classification
→ plan separation
→ authenticated source inventory

## PDF extraction backends

The runner tries, in order:
1. PyMuPDF (`fitz`)
2. `pypdf`

It does not use OCR.

## Output

Recovered images:
- `output/source-images/Beverly Hills/originals/`
- plan-like assets:
  `output/source-images/Beverly Hills/plans/`

Inventory:
- `output/source-images/Beverly Hills/Beverly Hills-catalogue-recovered-source-inventory.json`

Each asset records:
- asset ID
- source PDF
- source PDF hash
- page number
- extraction method
- xref when available
- file hash
- width/height
- category
- classification source/confidence
- plan-like flag
- PDF-page evidence
- plan restriction when applicable

## Safety

- catalogue only
- no simulation
- no visual-opportunity reuse
- no release/provenance reuse
- no network
- no publishing
- no Meta writes
- no Department 3 authority changes

## Run

```powershell
python -m pytest -q tests/test_department3_phase4f7br2_catalogue_visual_recovery.py
python run_department3_phase4f7br2_catalogue_visual_recovery.py --project "Beverly Hills"
python -m pytest -q
```

If R2 recovers assets successfully, rerun Phase 4F.7B asset-intelligence rebuild next.
