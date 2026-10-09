# Phase 1 — Unit-plan source integrity

This upgrade preserves the existing five-department workflow. It does not
remove, rename, or bypass any stage, and it does not require deleting output,
clearing caches, or installing an older archive.

## What Phase 1 changes

- Every PDF page is rendered once at 300 DPI as a complete-page PNG, even when
  the page also contains embedded images. Embedded images remain separate,
  byte-exact assets.
- Department 1 passes complete-page assets to Department 2 with the original
  project, document, page, source-document hash, rendered-asset hash, and asset
  ID provenance.
- Asset Intelligence treats individual unit plans separately from masterplans,
  site plans, typical floor plans, and photography. It records visible unit
  numbers and dimension labels exactly and does not estimate unreadable text.
- A unit plan is marketing eligible only when all of the following are true:
  the unit identity is non-empty; the complete plan is present; labels, numbers,
  and dimensions are readable; every asserted fact has evidence; and the exact
  project/document/page/hash/asset chain matches.
- Missing or conflicting evidence changes the plan to `UNVERIFIED` and
  `REVIEW_REQUIRED`. Department 4 refuses that plan instead of repairing,
  redrawing, cropping, or inventing details.
- All supported unit-plan aliases use the same technical-preservation behavior
  and content-inventory category.

## Install safely

1. Keep the current working installation as a backup.
2. Extract this ZIP into a new folder. Do not merge it into the live folder yet.
3. Copy the current `.env` into the new folder if the workflow needs configured
   credentials. Never place `.env` in a shared archive.
4. Install dependencies with `python -m pip install -r requirements.txt`.
5. Run the Phase 1 verification command below.
6. When it passes, move the project PDFs into `input/<Project Name>/` and run the
   normal command: `python app.py --project "<Project Name>"`.

No existing stage or output folder must be cleaned before this upgrade. Testing
in a separate folder is the rollback mechanism.

## Verify Phase 1

```bash
python -m unittest tests.test_unit_plan_phase1 tests.test_plan_integrity \
  tests.test_authentic_visual_workflow tests.test_asset_intelligence_agent \
  tests.test_department1_pipeline
```

Expected result: all tests pass. The dedicated Phase 1 suite includes a PDF page
that mixes an embedded logo with vector plan geometry, unit numbers, and room
dimensions; it confirms that the complete page and embedded source are both
retained.

## Audit a processed project

Inspect these artifacts after a project run:

- `output/source-images/<Project>/manifest.json`: every PDF page should have one
  `pdf_page_render`, `contains_entire_page: true`, and `render_dpi: 300`.
- `output/asset-intelligence/<Project>-asset-intelligence.json`: plan assets
  should contain visible unit numbers, visible dimension labels, completeness,
  legibility, and exact source metadata.
- `output/plan-intelligence/<Project>-plan-intelligence.json`: only records with
  `marketing_eligible: true` may proceed as individual unit-plan content.

If information is absent from the source, leave it absent. Do not add it to the
PDF, JSON, caption, or creative manually.
