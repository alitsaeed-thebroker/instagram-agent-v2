# Phase 1.1 — Bounded Marketing Strategy Context

This migration repairs the `context_length_exceeded` failure at the advisory
`marketing-strategy` stage. It does not remove or bypass Departments 1–3.

## Changes

- Replaces the full knowledge/provenance/creative-map prompt with a deterministic
  strategy brief capped at 90,000 characters.
- Retains verified fact IDs, concise fact text, evidence status, opportunity
  restrictions, campaign decisions, and the canonical five-stage real-estate
  campaign sequence.
- Treats unit plans as technical evidence and forbids inferred dimensions,
  areas, labels, unit numbers, redrawing, or repair.
- Keeps full provenance upstream in Departments 1–2 and references it by fact ID.
- Bumps the marketing-strategy cache contract from `1.2.0` to `1.3.0`.

## Install

Extract the complete ZIP into the root of `instagram-agent V2`, keeping the
payload folder beside the installer. From that root, run:

```powershell
python install_phase1_marketing_strategy_context_fix.py
```

The installer makes no API calls. It verifies the baseline and payload hashes,
backs up all changed files, compiles them, and runs focused tests.

After it passes, rerun:

```powershell
python app.py --project "Beverly Hills"
```

No project output, Department 1 handoff, authentic source asset, knowledge,
cache, publication record, or source PDF should be deleted.
