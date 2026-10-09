# Department 3 Phase 4E — Real-Estate Strategy Brain Upgrade

Phase 4E upgrades decision quality while preserving the authority architecture certified in 4A-4D.

## Adds

- `src/department3/real_estate_brain.py`
- `src/department3/real_estate_orchestrator.py`

## What the brain reasons about

- category priority
- location-first strategy
- masterplan/site-plan importance
- exterior/interior/amenity relevance
- low priority for developer and construction-update content
- audience
- marketing objective
- proposition
- feed vs carousel vs Story
- CTA intent
- Story sequencing role
- duplicate/fatigue penalties
- evidence confidence
- plan/layout restrictions
- unsupported-format rejection
- cross-project rejection

## Current business priorities encoded

High:
- Location
- Masterplan/site plan
- Exterior
- Interior
- Amenities/lifestyle

Low:
- Developer credibility
- Construction updates

Story is first-class.
Reels remain disabled.

## Authority remains unchanged

RealEstateStrategyBrain
-> canonical candidate mappings
-> LiveDepartment3Orchestrator
-> Department3CanonicalPlanner
-> Department3StrategyAuthority
-> ApprovedContentPlan

The brain cannot bypass canonical approval.

## Install

Extract directly into:
`C:\Users\alits\instagram-agent`

Then run:

```powershell
python -m pytest -q tests/test_department3_real_estate_brain.py tests/test_department3_real_estate_orchestrator.py
python -m pytest -q
```

## Next

After Phase 4E passes, Phase 4F should run the new brain against a real authenticated project and certify:
- feed decisions
- carousel decisions
- Story decisions
- evidence safety
- plan/layout handling
- duplication/fatigue behavior
- advisory integration
- canonical ApprovedContentPlan generation
- VDC handoff
