# Department 3 — Phase 4A Authority Consolidation Foundation

This is the **first production upgrade package**.

It establishes an explicit, executable authority policy:

- exactly one canonical creator of the Approved Content Plan
- creative intelligence = advisory only
- campaign intelligence = advisory only
- legacy planners/agents = non-authoritative
- Visual Art Director / visual-direction contract = canonical D3 visual-direction authority
- Department 4 modules = executors only

It also introduces a canonical `Department3StrategyAuthority` and `ApprovedContentPlan` contract.

## Why Phase 4A is intentionally narrow

The runtime trace proved that legacy modules execute but do not currently write authoritative-looking state. Therefore the safe first modification is to establish the authority contract before wiring legacy/advisory modules through it.

This package does **not** yet edit:

- `src/creative_intelligence/engine.py`
- `src/campaign_intelligence/engine.py`
- legacy `src/ai/agents/*`
- `src/creative/visual_art_director.py`
- `src/creative/visual_direction.py`
- Department 4

Those integrations belong to Phase 4B after this foundation passes.

## Install

Extract the ZIP somewhere, then from the extracted package run:

```powershell
cd C:\Users\alits\instagram-agent
python C:\path\to\extracted\Department3_Phase4A_Authority_Consolidation\install_phase4a.py
```

If you extract directly over the repository instead, you can skip the installer; the files are additive.

## Test

```powershell
python -m pytest -q tests/test_department3_authority_policy.py tests/test_department3_strategy_authority.py
python -m pytest -q
```

Expected Phase 4A behavior:

- legacy/advisory modules cannot claim strategy authority through the registry
- D4 cannot create D3 authority artifacts
- Story is first-class
- Reel remains disabled
- cross-project strategy candidates fail closed
- plan/layout marketing requires evidence
- duplicate production item IDs fail closed
- Approved Content Plan identity is deterministic

After this passes, Phase 4B will wire the two useful intelligence engines into this authority as advisory inputs and quarantine the legacy planners from the production authority path.
