# Department 2 Final Certification & Re-Audit

**Status: CERTIFIED for Phases 1–10**

## Final test gates

- Phase 1–10 focused certification: **150 passed + 5 adversarial subtests, 0 failed**
- Full repository: **824 passed, 2 failed, 1 skipped, 44 subtests passed**
- Production module compilation: **PASS**
- Direct legacy knowledge-authority reads in Departments 3–5: **0**
- The two full-suite failures are pre-existing/non-Department-2 issues:
  1. Brand Composer pixel-preservation regression.
  2. Creative Research Windows/Linux path-separator assertion.

## Phase matrix

| Phase | Certification result |
|---|---|
| 1 — Department 1→2 handoff / source isolation | PASS — explicit handoff contract, source/project identity, deterministic source hashing |
| 2 — Relational real-estate intelligence | PASS — canonical entity/fact graph replaces flat authority |
| 3 — Universal provenance | PASS — VERIFIED facts require exact evidence and cannot be inferred into authority |
| 4 — Authority, freshness, structured conflicts | PASS — source authority/freshness and equal-authority conflict fail-closed behavior |
| 5 — Commercial relationship hardening | PASS — only `price_per_sqm`, `total_unit_price`, `starting_price`; payment-plan field forced empty |
| 6 / 6B — Plan/layout trust boundary | PASS — exact asset/project/document/page/hash; unverified/cross-asset layout claims blocked downstream |
| 7 — Canonical consumer migration | PASS — Departments 3–5 consume canonical intelligence only; 0 legacy-authority bypass hits |
| 8 — Cache lineage / stale rejection | PASS — canonical D2 fingerprints, parent artifact fingerprints, stale artifact rejection |
| 9 — DOCX/table provenance | PASS — paragraph/table-row coordinates preserved; merged/headerless/nested/irregular structures fail closed |
| 10 — Adversarial generalization | PASS — sparse/bad input, prompt injection, placeholder prices, cross-project leakage, provenance poisoning tested |

## Final commercial contract

Department 2 recognizes only:

- `price_per_sqm`
- `total_unit_price`
- `starting_price`

It does **not** model payment plans, installments, down payments, booking terms, reservation fees, financing, discounts, ROI, yield, or payment schedules. `pricing.payment_plan` remains only as a legacy schema compatibility field and is constrained to the empty string.

## Provenance contract for VERIFIED facts

A VERIFIED fact must have:

- `evidence_id`
- `source_project`
- `source_file`
- `source_id`
- `source_sha256`
- exact locator: page / line range / paragraph / table+row
- `source_text`
- `extraction_method`

Missing or cross-project evidence fails closed.

## Replacement package scope

The replacement bundle contains only the production source and tests required by the certified Department 2 architecture. It deliberately excludes `.env`, credentials, runtime state, publishing ledgers, generated output, project data, research libraries, reset audits, and unrelated baseline artifacts.

Use `DEPARTMENT2_REPLACEMENT_MANIFEST.json` to verify every file SHA-256 before copying it into the local repository.
