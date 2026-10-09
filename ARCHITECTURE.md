# Architecture

## Global Brand Kit Boundary

`input/brand/brand-config.json` is the single global source of truth for Domus Erbil branding across all projects. Official logos belong in `input/brand/logos/`; approved assets, future templates, and approved font metadata have separate directories under `input/brand/`. The isolated `brand-kit-analysis` stage validates the configuration and writes one deterministic inventory to `output/brand-analysis/domus-erbil-logo-inventory.json`.

Logo sources are immutable. The analyzer records dimensions, transparency, suitability, and SHA-256 provenance but never fabricates, recolors, crops, or overwrites a logo. Missing optional contacts and unconfirmed visual details produce warnings. Public branding must use approved assets only, and contact details must be confirmed before use. Brand Composer and branded-image generation are outside this stage.

The global brand sequence is `brand-kit-analysis → brand-identity-analyzer → brand-readiness-validator`. Identity analysis verifies inventory membership, file integrity, suitability, and SHA-256 before deterministic raster/SVG color analysis. It writes `domus-erbil-brand-identity.json`; readiness writes `domus-erbil-brand-readiness.json` and scores identity (20), logo integrity (25), colors (15), typography (15), website/contact (10), multilingual support (10), and provenance (5). Critical integrity failures override the score.

Brand properties distinguish `official_confirmed`, `user_confirmed`, `logo_derived`, `system_selected`, `missing`, and `invalid`. Approval is a production-use lock, not a filesystem lock: an approved configuration stores normalized config and logo hashes. Hash drift revokes approval and requires analysis and review again. Analyzer-owned derived values are excluded from cache inputs where required, while user/official values are preserved.

Phase 20B begins only after that lock gate succeeds: `QA-passed produced image → brand composition plan → deterministic Brand Composer → branded-image QA → branded production manifest → branded review gallery`. The composer never calls a generative image service. It renders a separate RGBA layer, records exact overlay rectangles, and exports lossless PNG so QA can require byte-equivalent RGBA pixels outside the overlay mask. Technical plans and known protected subject regions influence deterministic layout selection.

Branded QA scores source preservation (25), logo integrity (15), factual/content accuracy (15), layout hierarchy (15), critical-region protection (10), contrast (10), platform compliance (5), and provenance (5). Any source alteration outside the mask, logo distortion/hash failure, incorrect website, unsupported content, critical obstruction, clipping, or corruption is a critical failure regardless of score. Composer and QA caches cover locked config/logo hashes, source and context hashes, composition inputs, expected text, output hashes, versions, platform, and language.

## Final Foundation Hardening

Post-branding hardening is additive and does not redesign upstream stage boundaries. Creative Visual QA is read-only and scores project focus, hierarchy, balance, typography, whitespace, restraint, consistency, platform fit, and uniqueness. Self-correction routes only affected items to the smallest responsible stage, enforces two total/per-stage attempts, preserves sources/facts/brand locks, and refuses project-wide regeneration where no item-level repair boundary exists.

Phase 21.1 extends the frozen foundation with `content-grouping-analyzer → caption-generator → hashtag-generator → alt-text-generator → post-package-builder → post-package-qa`. The content layer groups creatives into actual social-media units before generating copy. Carousel slides share one master caption while retaining asset-specific alt text and provenance. Captions retrieve only relevant verified facts and never expose internal validation language. Eligibility is resolved against the newest immutable release, current-project manifests, technical/creative QA, provenance, live image hashes, and the approved brand lock.

Phase 21.2 adds `social-content-review` after package QA. This read-only presentation stage emits an offline HTML dashboard and JSON aggregation, referencing final and source image files directly. It never alters packages, QA scores, provenance, or production assets.

Phase 22 adds `publishing-queue → scheduling-engine → publish-preflight → mock-platform-adapter → publication-manifest`. Queue mutations use per-project locks and atomic replacement. Idempotency keys bind project, release, package, platform, language, and package hash. The adapter boundary is platform-independent; only the explicitly dry-run mock adapter is active, and it performs no network requests.

Phase 23 implements `meta-platform-adapter` as an opt-in sibling of the mock adapter. It uses a centralized versioned Graph client, environment-only credentials, account and permission discovery, an external-URL media host boundary, container readiness polling, exact-order carousel assembly, remote status verification, and real receipt persistence. It is excluded from normal publishing descendants so ordinary and dry-run executions cannot invoke it.

Captions use curated visual-editorial statements unless explicit verified fact references exist. Hashtags derive only from verified identity/location and content context. Alt text describes visible asset classes without marketing claims. Package QA treats unsupported facts, wrong images/projects, invalid provenance, stale brand hashes, and unverified commercial claims as blockers. Text corrections remain below the image-production boundary.

Provenance audits connect branded/production/planning identifiers to exact visual assets, source documents/pages/hashes, fact references, and brand hashes. Consolidated reports weight knowledge, source, assets, planning, processing, technical QA, brand, branded QA, creative QA, provenance, and release integrity. Run directories are append-only completed records with a mutable pointer; releases are sequential copy snapshots whose existing files are never modified. Health checks validate source through release integrity and classify results as `HEALTHY`, `HEALTHY_WITH_WARNINGS`, `DEGRADED`, or `CRITICAL`.

## Deterministic Brand Composition Boundary

After source-image QA, `brand-composer` reads only current-project artifacts and the global validated brand kit. It creates an explicit composition plan before using Pillow-based text, logo, gradient, and geometric overlays. The approved processed image remains the base layer; outputs are lossless PNGs with overlay masks and regions recorded so `branded-image-qa` can require identical decoded pixels everywhere outside those regions.

Branded QA validates dimensions, provenance, approved logo/contact data, layout bounds, safe margins, and factual references. It writes a separate branded manifest and review gallery. Manual decisions are exported locally; no publishing, scheduling, caption, analytics, or social API boundary is crossed.

## Authentic Source Image Policy

**The current production system creates marketing materials exclusively from authentic developer-approved project images. Synthetic project imagery is disabled by default.**

`PROJECT_VISUAL_MODE=source_only` is the mandatory default. Project PDFs, brochures, masterplans, floorplans, official renderings, approved photos, and separately approved project image files are the only visual source of truth. Every visual derivative must retain its source asset ID, document, page, source hash, crop coordinates, enhancement operations, templates, dimensions, timestamp, and output hash.

The authoritative visual workflow is:

```text
Knowledge Extraction
  -> Visual Asset Extraction (immutable bytes)
  -> Visual Asset Analysis (metadata only; unknown remains unknown)
  -> Available-Content Inventory
  -> Marketing Strategy
  -> Content Planner (feasible ideas only)
  -> Creative Director
  -> Asset Selection Planner (unsupported items skipped)
  -> Scene Planner (narrative order of approved visuals)
  -> Shot Planner (safe crops/layouts of existing visuals)
  -> Layout Planner
  -> Prompt Generator (structured editing instructions only)
  -> Image Enhancement (non-generative technical correction)
  -> Brand Composer
  -> Final Marketing Assets with complete provenance
```

Scene Planner cannot invent visual scenes. Shot Planner cannot invent camera angles or unseen views. Prompt Generator cannot request text-to-image content. The former Image Generator role is an Image Processing Engine limited to enhancement, crop, resize, and export. When one idea lacks support, that item is recorded as `skipped_unavailable`; all feasible ideas continue and no substitute is requested or fabricated.

## 1. Project Vision

`instagram-agent` is a modular, scalable, AI-powered Real Estate Marketing Agent. Its purpose is to transform a real-estate project catalogue into complete marketing campaigns through specialized AI agents.

The architecture separates source processing, structured project knowledge, marketing decisions, creative production, and publishing-ready content. This allows each capability to evolve independently without destabilizing the system.

## 2. System Architecture

The system uses a multi-agent architecture. Every agent has exactly one responsibility, owns the business logic for that responsibility, and produces a defined output artifact.

Agents never communicate directly or invoke one another. The Orchestrator coordinates the workflow by providing each agent with the required structured input artifact and collecting its output. JSON artifacts are the boundary between AI-oriented stages.

```text
Project folder (one or more PDFs)
 |
 v
PDF Agent (one Markdown artifact per document)
 |
 v
Knowledge Agent (one temporary knowledge artifact per document)
 |
 v
Knowledge Fusion (one final knowledge.json)
 |
 v
Marketing Strategist Agent
 |
 v
Creative Director Agent
 |
 v
Visual Asset Extraction
 |
 v
Visual Asset Analysis
 |
 v
Asset Selection Planner
 |
 v
Scene Planner (approved image sequence)
 |
 v
Shot Planner (safe crops/layouts)
 |
 v
Prompt Agent (editing instructions)
 |
 v
Image Processing Engine
 |
 v
Brand Agent
 |
 v
Caption Agent
```

The implemented workflow now includes knowledge, strategy, content, creative direction, immutable source-image extraction, metadata analysis, fail-safe selection, scene planning, and source-image shot/layout planning. Enhancement and final brand composition remain downstream stages.

## 3. Project Structure

| Location | Responsibility |
| --- | --- |
| `input/` | Source PDFs. A subfolder represents one project and may contain any number of documents; one flat PDF remains supported for backward compatibility. |
| `output/` | Stage-specific artifacts, including `source-images/`, `visual-analysis/`, `asset-selections/`, scene/shot plans, enhanced derivatives, and provenance. |
| `assets/` | Reusable visual resources, including brand logos. |
| `data/` | Versioned or local reference data used by future workflow stages. |
| `tests/` | Automated tests that protect existing behavior and future contracts. |
| `src/core/` | Deterministic infrastructure: PDF reading, Markdown writing, file management, and logging. |
| `src/knowledge/` | Knowledge artifact schemas and validation. |
| `src/ai/` | Agent contracts, the Orchestrator, shared agent utilities, and individual agent modules. |
| `src/models/` | Domain models representing stable business concepts. |
| `src/utils/` | Configuration, project paths, and small shared helpers. |

## 4. Agent Responsibilities

### PDF Agent

| Area | Definition |
| --- | --- |
| Purpose | Convert a source project catalogue into a Markdown artifact. |
| Input | PDF file. |
| Output | Markdown file, for example `markdown.md`. |
| Responsibilities | Locate/read the selected PDF, extract readable text, and save Markdown through core services. |
| Dependencies | `src/core/pdf_reader.py`, `src/core/markdown_writer.py`, file management, and logging. |
| Future implementation notes | Preserve the existing extraction behavior and error handling; do not introduce knowledge inference here. |

### Knowledge Agent

| Area | Definition |
| --- | --- |
| Purpose | Turn extracted project content into reliable structured knowledge. |
| Input | Markdown artifact. |
| Output | `knowledge.json`. |
| Responsibilities | Extract, normalize, validate, and persist factual project knowledge. |
| Dependencies | Knowledge schema, validators, configuration, and logging. |
| Future implementation notes | Keep source traceability and validate output against a backward-compatible schema. |

### Document Classification and Knowledge Fusion

Each PDF is classified from its filename and extracted contents as a Catalogue, Price List, Payment Plan, Floor Plans, Master Plan, FAQ, Technical Specifications, Location Guide, Presentation, or Other. The Knowledge Agent processes each Markdown artifact independently and retains its temporary JSON under `output/knowledge/<project>/documents/`. Knowledge Fusion merges those artifacts without inventing facts, prefers higher-confidence sources on scalar conflicts, and logs every conflict. It writes exactly one final `output/knowledge/<project>.json`, so evaluator and downstream agents do not depend on the number of source documents.

### Authoritative Project Intelligence Contract

`output/knowledge/<project>.json` is the sole downstream authority for project identity and commercial decisions. Its `commercial_intelligence` member is a typed, deterministic contract with pricing, a structured payment plan, commercial terms, conflicts, unsupported claims, sources, warnings, and a machine-readable audit summary. Per-document JSON, Markdown/block provenance, and `output/knowledge/<project-slug>/project-knowledge.json` remain intermediate evidence or page-native visual-analysis artifacts; they must not be used independently for pricing or payment decisions. New commercial consumers use `load_authoritative_project_intelligence()`.

Commercial facts explicitly distinguish starting price, exact unit price, price per square metre/foot, ranges, booking/reservation amounts, down payments, installments, milestones, discounts/promotions, charges/fees/taxes, financing, handover, and construction-linked payments. Qualifiers such as `starting_from`, `exact`, `range`, `per_sqm`, and `per_sqft` are retained. Payment percentages remain separate typed installments; incomplete totals produce warnings and no missing percentage is fabricated.

Every usable fact carries the original project, filename, document classification, source text, extraction method, confidence, and available PDF page, TXT line range, or DOCX paragraph. Unknown and internal-note sources preserve evidence as `supported` but cannot independently become verified facts. Source authority is classification-led and then refined by explicit revision/date signals. A newer same-class official document can supersede an older value while both candidates remain in conflict history; equal-authority contradictions remain unresolved. Critical identity conflicts follow the same discipline.

Promotional language is stored separately from verified commercial facts. ROI, yields, exchange-rate conversions, missing installments, and missing prices are never inferred. The downstream fact gate requires valid type, project association, verified status, and source evidence. Page-native extraction remains valuable raw evidence but is not a second commercial source of truth.

### Department 3: Authoritative Content Opportunity Inventory

Department 3 owns `output/content-inventory/<project>-content-opportunity-inventory.json`. The `ContentOpportunityInventory` contract is the sole authority for deciding what is worth communicating. Discovery reads authoritative project knowledge first, expands distinct evidence-backed topics, deduplicates by normalized topic and evidence identity, and only then attaches optional authentic visuals. Location is first-class and high priority; separate overview, landmark, connectivity, destination, accessibility, and supported-advantage opportunities may coexist. Verified commercial opportunities consume only `commercial_intelligence` facts with acceptable provenance and status.

Each opportunity separates strategy readiness from `renderer_readiness`, so text-only opportunities survive with zero visual assets and no approved renderer. Recommended formats are advisory. Publication items remain downstream. The inventory also contains ordered story sequences, safe CTA opportunities, source references, full fact evidence, optional visual IDs, priority, confidence, limitations, forbidden claims, carousel relationships, and diagnostics.

Evidence modes remain explicit through grouping: `fact_supported`, `visual_only`, `mixed`, and `policy_generated`. Carousel and sequence wrappers cannot increase member confidence or convert visual classification into factual support. All visual compatibility diagnostics, reservations, totals, and planning inputs use one fail-closed project-owned asset collection.

Source ranking emits `output/inventory/visual-editorial-inventory-<project>.json`, an explicitly pre-strategy `visual_intelligence` artifact with `authoritative_strategy: false` and `may_not_drive_branded_content: true`. It is not a content plan. Public internet evidence is supported only as future supplementary input carrying URL/domain, retrieval time, source type, authority, project match, claim, freshness, verification, and conflict state; it cannot override source-package or canonical knowledge and must pass the commercial gate before supporting commercial content.

`output/visual-opportunities/<project>-visual-opportunities.json`, `output/campaigns/<project>-campaign-plan.json`, and `output/content/<project>-content-plan.json` are compatibility representations generated from the canonical inventory for existing Creative Director and production consumers. `output/inventory/content-plan-<project>.json` remains an earlier source-ranking/rendering artifact and is not a competing Department 3 authority. Discovery has no three-asset or ten-image limit; those limits remain permissible only in downstream selection and rendering adapters.

### Marketing Strategist Agent

| Area | Definition |
| --- | --- |
| Purpose | Define the marketing strategy for the project. |
| Input | `knowledge.json`. |
| Output | `strategy.json`. |
| Responsibilities | Identify audiences, positioning, campaign themes, channel guidance, and messaging priorities. |
| Dependencies | Knowledge contract, strategy contract, configuration, and logging. |
| Future implementation notes | Make recommendations explainable and avoid modifying factual knowledge. |

### Creative Director Agent

| Area | Definition |
| --- | --- |
| Purpose | Translate marketing strategy into an actionable creative direction. |
| Input | `strategy.json`. |
| Output | `creative_direction.json`. |
| Responsibilities | Define visual mood, composition direction, creative concepts, tone, and asset requirements. |
| Dependencies | Strategy contract, asset conventions, configuration, and logging. |
| Future implementation notes | Produce machine-readable creative direction rather than rendering images. |

### Prompt Agent

| Area | Definition |
| --- | --- |
| Purpose | Convert an approved source-image treatment into structured editing instructions. |
| Input | Approved source asset, crop/layout plan, and preservation constraints. |
| Output | `editing_instructions.json`. |
| Responsibilities | Request only technical operations such as denoise, sharpen, margin removal, exposure correction, crop, resize, and export. |
| Dependencies | Source-asset provenance, layout contract, enhancement policy, and logging. |
| Future implementation notes | Text-to-image prompts and synthetic project content are forbidden. |

### Image Processing Engine

| Area | Definition |
| --- | --- |
| Purpose | Improve and export authentic approved source images without changing project content. |
| Input | Approved source image and validated editing instructions. |
| Output | Enhanced PNG/JPG derivatives plus provenance JSON. |
| Responsibilities | Apply deterministic enhancement, crop, resize, and export while preserving source identity and geometry. |
| Dependencies | Source-only policy, Pillow-based processing, source hashes, output paths, and logging. |
| Future implementation notes | Generation, replacement, inpainting, outpainting, and feature addition/removal are forbidden. |

### Brand Agent

| Area | Definition |
| --- | --- |
| Purpose | Apply required visual brand treatment to enhanced authentic source images. |
| Input | Enhanced source-image derivatives and approved brand assets. |
| Output | Branded image artifacts. |
| Responsibilities | Apply logos, approved visual treatments, layout rules, and export settings. |
| Dependencies | `assets/logos/`, image utilities, output paths, and logging. |
| Future implementation notes | Never alter source images; retain complete source, enhancement, layout, and branding provenance. |

### Caption Agent

| Area | Definition |
| --- | --- |
| Purpose | Produce publishing-ready copy aligned with project knowledge and strategy. |
| Input | `knowledge.json` and `strategy.json`, supplied by the Orchestrator. |
| Output | `captions.json`. |
| Responsibilities | Generate caption variants, calls to action, hashtags, and any defined platform metadata. |
| Dependencies | Knowledge and strategy contracts, caption schema, configuration, and logging. |
| Future implementation notes | The agent consumes structured inputs only; it must not call Knowledge or Strategy agents. |

## 5. Orchestrator

The Orchestrator is the workflow coordinator. It determines stage order, supplies artifact paths or validated artifact references, records workflow state, and handles stage-level control flow.

It does not contain domain-specific business logic, prompt-writing logic, extraction logic, or image-processing logic. Those responsibilities remain inside the owning agent or core service. The Orchestrator is therefore the only component permitted to coordinate multiple agents.

## 6. JSON Contracts

JSON is the single communication format between agents. Raw PDFs and raw Markdown are handled only by the ingestion boundary; downstream AI-oriented stages exchange structured JSON artifacts.

| Artifact | Producer | Consumer |
| --- | --- | --- |
| `markdown.md` | PDF Agent | Knowledge Agent |
| `knowledge.json` | Knowledge Agent | Marketing Strategist Agent; Caption Agent |
| `strategy.json` | Marketing Strategist Agent | Creative Director Agent; Caption Agent |
| `creative_direction.json` | Creative Director Agent | Prompt Agent |
| `image_prompts.json` | Prompt Agent | Image Agent |
| `captions.json` | Caption Agent | Future publishing stage |

Every JSON contract must define a schema, include a schema version when implemented, validate before consumption, and remain backward compatible when it evolves. Image files are output artifacts from image stages; their associated metadata must be captured in structured JSON.

## 7. Knowledge Model

The future `knowledge.json` schema is the factual source of truth for a project. Its top-level sections are expected to include:

| Section | Contents |
| --- | --- |
| `project` | Project identity, catalogue source, status, and summary. |
| `developer` | Developer identity, history, and relevant credentials. |
| `location` | Address, area context, connectivity, and nearby landmarks. |
| `property` | Property types, unit details, design, and specifications. |
| `financial` | Pricing, payment plans, fees, and financial disclosures. |
| `amenities` | On-site facilities, services, and shared spaces. |
| `lifestyle` | Resident experience, community, and daily-life benefits. |
| `investment` | Investment rationale, market signals, and risk-aware claims. |
| `marketing` | Approved claims, differentiators, audiences, and source-backed messaging. |

The schema may evolve as the product matures, but changes must remain backward compatible. New fields should be additive where possible, existing meanings must not be silently changed, and validators must support documented schema versions.

## 8. Development Principles

- **Single Responsibility Principle:** each module and agent has one clear purpose.
- **One Agent = One Responsibility:** split new responsibilities into new agents rather than expanding an existing agent beyond its boundary.
- **No duplicated logic:** shared deterministic behavior belongs in core services, models, or utilities.
- **No agent-to-agent calls:** the Orchestrator coordinates all agent sequencing and handoff.
- **JSON communication only:** structured artifacts are the integration boundary between agents.
- **Business logic stays inside agents:** the Orchestrator coordinates; agents decide within their own domains.
- **Keep modules small:** favor focused modules with explicit inputs, outputs, and dependencies.
- **Keep architecture stable:** extend contracts and agent implementations without reshaping the package structure unless necessary.

## 9. Roadmap

| Phase | Focus |
| --- | --- |
| Phase 1 | Foundation: stable folders, core PDF extraction, configuration, contracts, and tests. |
| Phase 2 | Knowledge Agent: schema, validation, and `knowledge.json` generation. |
| Phase 3 | Marketing Strategist: `strategy.json` generation from validated knowledge. |
| Phase 4 | Creative Director: `creative_direction.json` generation from strategy. |
| Phase 5 | Prompt Agent: generation of `image_prompts.json`. |
| Phase 6 | Image Agent: provider-backed image generation and artifact metadata. |
| Phase 7 | Brand Agent: brand application and export workflow. |
| Phase 8 | Caption Agent: `captions.json` generation from knowledge and strategy. |
| Phase 9 | Publishing: platform-specific approval, scheduling, and publishing workflows. |

## 10. Architecture Rules

This document is the architectural source of truth for the project. Future development must follow these boundaries, contracts, and principles.

Avoid structural refactoring unless it is absolutely necessary and justified by a documented architectural decision. Future work should focus on implementing agents and their contracts, rather than redesigning the architecture.
# Asset Intelligence boundary

The Asset Intelligence Agent analyzes authentic extracted project visuals and creates a semantic inventory. It describes only what is visibly present and never generates or invents project content. It runs after immutable source extraction and before marketing/content generation. The source manifest remains the provenance authority; semantic records are cached by source hash, module version, prompt version, and model policy. Downstream regeneration begins at Content Planner unless a strategy artifact explicitly depends on visual availability. Document extraction, knowledge extraction/fusion, and knowledge evaluation remain outside this regeneration boundary when their sources are unchanged.
# Phase 9.1 planning architecture

The planning system is asset-first. It identifies authentic visual opportunities before creating campaigns or content. Every content item must be supported by approved project assets and factual source evidence. Asset scarcity, reuse, confidence, funnel purpose, and campaign memory are enforced deterministically.

The source-only planning path is `Knowledge -> Asset Intelligence -> Semantic Visual Inventory -> Visual Opportunity Engine -> Marketing Strategy -> Campaign Planner -> Content Planner -> Creative Director -> Scene Planner -> Shot Planner -> Image Processing Planner`. The deterministic planning layer owns identifiers, evidence validation, ranking, normalized confidence, uniqueness, reservation and reuse limits, sequence repair, memory updates, graph assembly, and quality counts.
# Image Prompt Generator

`image-prompt-generator` follows the Image Processing Planner. It validates project ownership, source existence and SHA-256 integrity, suitability, inventory membership, and processing provenance before emitting one deterministic source-only prompt per export variant plus a prompt manifest. Invalid or unsupported deliverables are blocked rather than synthesized.
# Deterministic Production

Four cached stages follow prompt generation: deterministic image processing, output QA, production-manifest finalization, and a standalone review gallery. Source assets are immutable; derivatives use aspect-ratio-preserving contain/padding and revisioned deterministic filenames.

`detail-preservation-enhancer` sits between prompt generation and platform production. It measures source detail, applies bounded small-radius deterministic enhancement only when useful, rolls back artifact increases, and writes separate derivatives and detail QA.
## Platform-aware Meta boundary

Campaign planning records `instagram_only`, `facebook_only`, `both_mirrored`, or `both_platform_optimized` before creative production. Content retains its master concept, planned destinations, evidence, and platform rationale. Master facts and provenance are immutable inputs to variants; variants may change packaging and copy only. `src/platforms` centralizes capabilities, and unverified API limits remain configurable instead of guessed. Publishing overrides are operational history, not strategy rewrites; queue identity includes package, destination, and content version/hash.
# R2 media-hosting boundary

`CloudflareR2MediaHost` owns S3-compatible credentials, deterministic object keys, exact-file uploads, and public delivery checks. Its persistent manifest is the boundary to publishing: `MetaInstagramAdapter` reads only validated HTTPS URL mappings and remains unaware of R2 credentials. R2 readiness and Meta authentication readiness are independent; missing or stale hosted mappings block real publishing as `blocked_media_hosting`.

## Phase 26 source-grounding boundary

`ProjectKnowledge.project_identity` is the canonical four-field identity boundary, while legacy `project` fields remain synchronized for compatibility. `fact_provenance` is internal verification data and must never be rendered into public captions. `knowledge.audit` compares persisted source-document analysis, page-separated Markdown, fused knowledge, and immutable asset intelligence.

Asset Intelligence owns visual classification and preservation metadata; planners may select only semantically compatible, current-project asset IDs. The trace is concept → visual category → source asset/page → verified fact references → graphic/caption copy. Content/package QA blocks semantic mismatches, unsupported claims, duplicate fields, and low-information generic messages. Publishing, R2, receipts, queue identity, scheduling, and idempotency remain outside this boundary.
