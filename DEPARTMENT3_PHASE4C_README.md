# Department 3 Phase 4C — Live Orchestration Wiring

Phase 4C touches the two real orchestration surfaces:

- `app.py`
- `src/execution/stages.py`

Historical audit evidence shows `app.py` reaches creative intelligence, campaign intelligence,
legacy planners, and the canonical Visual Art Director, while `src/execution/stages.py` is the
separate stage-graph authority. Therefore Phase 4C patches both surfaces.

## Safety design

The installer is guarded.

Before changing anything it requires:

1. Phase 4A/4B files to exist.
2. `app.py` and `src/execution/stages.py` to parse.
3. live creative/campaign intelligence anchors to be present.
4. live Visual Art Director/VDC anchors to be present.

If those checks fail, it exits without modification.

Before changing the two orchestration files it creates backups under:

`output/backups/department3-phase4c/`

It syntax-checks both files again after patching and rolls back on parse failure.

## What the patch does

It adds the canonical live imports and a `_department3_canonical_approve(...)` bridge to both
real orchestration surfaces.

The bridge:

creative intelligence
+ campaign intelligence
→ non-authoritative AdvisoryEnvelope
→ Department3CanonicalPlanner
→ ApprovedContentPlan

The package also adds runtime authority guards so advisory/legacy code cannot claim
Approved Content Plan or VDC authority.

## What Phase 4C deliberately does NOT do

It does not use a regex to replace unknown production call sites.

The repository has multiple execution modes and substantial special-case routing in app.py.
Blindly replacing a call by line number would be unsafe.

Phase 4C establishes the canonical live bridge and captures it at both entrypoints.
Phase 4D can then replace the exact legacy call sites using evidence from the current patched
source/tests.

## Install

Extract into the repository or any folder. From the repository root:

```powershell
python <EXTRACTED_FOLDER>\install_phase4c.py
```

If the ZIP was extracted directly into the repo, run:

```powershell
python install_phase4c.py
```

## Verify

```powershell
python verify_phase4c.py
python -m pytest -q tests/test_department3_live_orchestration.py tests/test_department3_runtime_guard.py
python -m pytest -q
```

Expected:
- guarded installer succeeds
- both live orchestration surfaces contain the canonical bridge
- focused tests pass
- full regression passes
