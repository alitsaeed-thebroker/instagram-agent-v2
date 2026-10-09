# Department 3 Phase 4F — Real Project Strategy Certification Runner

This is a certification package, not another authority rewrite.

Default certification project: **Beverly Hills**.

## What it does

It searches the existing repository for real Beverly Hills Department 3 opportunity artifacts. If none are available, it falls back to authenticated selected/ranked source-image inventory artifacts.

It then runs the Phase 4E `RealEstateStrategyBrain` against those real artifacts and certifies:

- real-project source presence
- candidate generation
- feed/carousel/Story format safety
- Story activation
- location preservation when real location evidence exists
- masterplan/site-plan preservation when real evidence exists
- unsupported unit/floor/layout fail-closed behavior
- project isolation
- source-asset integrity
- evidence-sensitive claim safety
- history/fatigue input availability
- canonical authority handoff architecture
- runtime legacy-authority guard
- Phase 4D.2 direct-call demotions
- zero Meta writes / zero Instagram publishing

## Status

The runner returns:

- `PASS`
- `PASS_WITH_CONDITIONS`
- `FAIL`

Critical authority, project-isolation, source-integrity, plan-safety, or evidence-safety failures produce `FAIL`.

Missing noncritical content coverage, such as no Story candidate from the real asset set, produces `PASS_WITH_CONDITIONS`.

## Safety

The certification runner does not import or invoke Meta publishing.

It writes only certification reports under:

`output/audits/department3/`

## Install

Extract directly into:

`C:\Users\alits\instagram-agent`

Then run:

```powershell
python verify_phase4f.py
python -m pytest -q tests/test_department3_phase4f_certification.py
python run_department3_phase4f_certification.py --project "Beverly Hills"
python -m pytest -q
```

Expected report files:

```text
output/audits/department3/department3-phase4f-beverly-hills-certification.json
output/audits/department3/department3-phase4f-beverly-hills-certification.md
```

Do not publish anything after this run. The next step is to inspect the Phase 4F report and perform the final Department 3 re-audit.
