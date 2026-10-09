# instagram-agent

## Phase 1 unit-plan integrity

The unit-plan source-integrity upgrade preserves complete PDF pages, visible
unit numbers and dimensions, exact project/document/page/hash/asset evidence,
and fail-closed production eligibility. See
[`PHASE1_UNIT_PLAN_UPGRADE.md`](PHASE1_UNIT_PLAN_UPGRADE.md) for installation,
verification, and artifact-audit instructions.

## Global Brand Kit

The permanent brand source is `input/brand/brand-config.json`. It identifies **Domus Erbil Company for Real Estate**, holds conservative voice and visual defaults, and is shared by every project. Put official SVG, PNG, WEBP, JPG, or JPEG logo files in `input/brand/logos/`, then run `python app.py --stage brand-kit-analysis`. An optional `--project` argument is accepted but does not create project-specific copies.

Phase 20A adds `brand-identity-analyzer` and `brand-readiness-validator`. Run `python app.py --brand-status` to analyze the preferred hash-verified logo, migrate legacy brand fields safely, build the production-safe palette and typography policy, and print the readiness score. Run `python app.py --approve-brand` only after review; approval stores a configuration and logo hash and locks their use for production. Editing remains allowed, but a later config or logo change revokes the production lock until reapproval.

### Brand Identity Status Model

Every configurable brand property uses one explicit source status: `official_confirmed` for documented official facts, `user_confirmed` for values explicitly accepted by the user, `logo_derived` for deterministic observations from the preferred logo, `system_selected` for intentional production-safe defaults, `missing`, or `invalid`. Logo-derived colors are production-usable but are not officially documented corporate colors. Segoe UI with Arial/Helvetica fallbacks (and Tahoma for Arabic-script fallback) is intentionally system-selected and is not claimed as an official Domus Erbil font. Missing phone, email, social handles, or address are warnings only and must be omitted by future output when absent.

Only approved assets may be used for branding. The system inventories originals without changing them and never generates or guesses a company logo. Missing logos, phone numbers, email addresses, confirmed colors, or approved fonts remain explicit warnings. Confirm all contact information before public use. Future approved layouts belong in `input/brand/templates/`; project source images do not.

### Brand Composer and branded QA

The Brand Composer applies approved Domus Erbil branding as deterministic graphic overlays on QA-passed authentic project imagery. It does not regenerate or modify project content. All visible marketing claims must be supported by verified source evidence.

The Brand Composer uses only the approved and locked Domus Erbil Brand Kit. Before rendering it verifies the normalized approved configuration hash, live preferred-logo hash, and current readiness report. Branding uses the logo-derived `#781810` primary sparingly with only white/dark neutral panels; missing secondary, accent, phone, and email values are omitted rather than invented. Project imagery outside declared overlay regions remains pixel-identical.

Run `python app.py --project "<project>" --stage brand-composer` for composition only, `--stage branded-image-qa` for QA of an existing composition, or `--from-stage brand-composer` for composition through branded QA and review artifacts. Outputs include deterministic composition plans, lossless branded images, scored branded QA, the branded production manifest, review gallery, and an initially empty decisions JSON. The gallery supports before/after viewing, zoom, filters, approval/rejection/revision decisions, notes, and JSON export. No publishing action is performed.

### Final Foundation Hardening

After branded QA, the autonomous foundation runs `creative-visual-qa → self-correction → provenance-audit → production-quality-report → release-manager`. Creative QA measures premium visual quality separately from technical correctness. Self-correction is limited to two item-level cycles and never regenerates the whole project when an item-level repair API is unavailable. Provenance traces each final image through planning, source assets/documents/pages, verified facts, and locked brand hashes.

Successful eligible items are copied into sequential immutable release directories under `output/releases/<project>/release-NNN/`; completed releases are never reused or overwritten. Stable run manifests and a non-destructive current pointer live under `output/runs/<project>/`. Use `python app.py --health-check` or add `--project "<project>"` for integrity diagnostics. Run the small deterministic regression suite with `python app.py --regression-check` or `python -m unittest discover -s tests/regression`.

### Phase 21: Post packages

The post-package layer groups creatives into actual social-media units before generating copy. Carousel slides share one customer-facing master caption while retaining asset-specific alt text and provenance. Captions retrieve only relevant verified facts and never expose internal validation language. It does not publish content. Run `python app.py --project "<project>" --from-stage content-grouping-analyzer --language en`.

Outputs are written under `output/content-groups`, `output/captions`, `output/hashtags`, `output/alt-text`, `output/post-packages`, and `output/qa/*-post-package-qa.json`. Text-only QA corrections route only to grouping, caption, hashtag, alt-text, or package-builder stages and never rerun image production. Packages are ready-to-publish artifacts, but no API posting, scheduling, or analytics occurs.

The `social-content-review` stage provides an offline visual inspection interface for final social-media packages. It displays actual production assets, carousel order, customer-facing copy, accessibility text, QA, source comparisons, and provenance without altering production outputs or requiring human approval. Run `python app.py --project "<project>" --stage social-content-review`; outputs are written to `output/social-review`.

The publishing foundation is platform-independent. Final post packages enter a persistent queue, receive optional schedules, pass strict preflight validation, and are handed to platform adapters. The initial adapter is a dry-run mock adapter that never contacts external services. Run `python app.py --project "<project>" --publish-dry-run`; inspect state without mutation using `--show-publishing-queue`. Manual scheduling is the default and never invents a publication time.

The Meta/Instagram adapter is isolated and disabled by default. It supports Instagram professional-account single-image and carousel publication only, requires explicit `--publish-meta` or `--stage meta-platform-adapter`, reads secrets exclusively from environment variables, and refuses local-only media paths. See `META_PUBLISHING.md` before activation and use `python app.py --meta-status` for a secret-safe readiness report.

Run `python app.py --project "<project>" --from-stage brand-composer` to create composition plans, lossless branded PNGs, branded QA, a branded production manifest, and a local branded review gallery. The gallery exports `approved`, `rejected`, or `needs_revision` decisions as JSON and never publishes them. Missing logos block branding without failing other projects; unconfirmed colors use only neutral presentation.

> **Authentic-source production rule:** The current production system creates marketing materials exclusively from authentic developer-approved project images. Synthetic project imagery is disabled by default.

The foundation for a professional AI-powered real-estate marketing agent. The application converts PDFs to Markdown, extracts and evaluates knowledge, generates marketing strategy and a detailed content plan, produces grounded creative directions and scenes, and converts those scenes into production-ready cinematography plans.

## Current behavior

Install dependencies with `python -m pip install -r requirements.txt`, place PDFs in `input/`, then run:

```bash
python app.py
```

The application supports both a legacy single PDF in `input/` and project folders containing any number of PDFs. For a project folder, each source PDF is written to `output/markdown/<project>/<document>.md`, classified, and extracted independently before the factual results are fused into one `output/knowledge/<project>.json`. Evaluation, strategy generation, and campaign planning consume only that final knowledge artifact or its direct downstream JSON output.

Example multi-document input:

```text
input/
  Beverly Hills/
    Catalogue.pdf
    Price List.pdf
    Payment Plan.pdf
    Floor Plans.pdf
```

Document classification recognizes catalogues, price lists, payment plans, floor plans, master plans, FAQs, technical specifications, location guides, presentations, and `Other`. Per-document knowledge artifacts are retained under `output/knowledge/<project>/documents/`; fusion prefers higher-confidence document types for conflicting scalar facts and reports conflicts in the terminal.

Before strategy and content planning, the application extracts immutable approved visuals, analyzes only verifiable metadata, and writes `output/visual-inventory/<project>-visual-inventory.json`. Content Planner then combines knowledge, strategy, and that inventory. Every idea records required and available source IDs, visual/text evidence, support status, and feasible platforms/formats. Unavailable ideas are skipped and reported without stopping feasible work.

The Asset Intelligence Agent analyzes authentic extracted project visuals and creates a semantic inventory. It describes only what is visibly present and never generates or invents project content. Its versioned, hash-keyed analysis is saved under `output/asset-intelligence/`; successful results rebuild the categorized visual inventory used by Content Planner, Asset Selection, Scene Planner, Shot Planner, and Image Processing Planner. Exact duplicate analyses are reused while retaining every source occurrence, cache hits avoid repeated API calls, and individual failures remain review records without stopping the project.

Document discovery is content-based. PDF and approved image filenames are retained only as traceability identifiers: they never determine document classification, project identity, role, purpose, or priority. The system inspects extracted text and decoded document structure, assigns confidence and supporting evidence, retains low-confidence material as `Unknown`, and writes `output/inventory/<project>-document-analysis.json`. Documents with a shared identity discovered from their contents are grouped even when their filenames or containing folders conflict; ambiguous inputs receive stable candidate IDs and explicit warnings.

After every successful content plan, Creative Director reads the validated knowledge, strategy, and content plan and writes `output/creative-directions/<project>-creative-directions.json`. It creates one senior-level creative direction per content idea, covering campaign concept, visual identity, emotion, storytelling, brand constraints, luxury and realism levels, intended audience perception, artistic vision, references, and consistency criteria. Factual project elements are kept separate from creative interpretation. Creative Director does not decide scenes, shots, cameras, lenses, composition, framing, aspect ratios, prompts, generation settings, captions, branding, or publishing.

After Creative Director succeeds, Scene Planner reads the knowledge, content plan, and creative directions and writes `output/scene-plans/<project>-scene-plans.json`. It creates one ordered scene plan per approved creative direction, with explicit factual basis, creative interpretation, subjects, environments, time, weather, mood, lighting direction, dependencies, continuity, restrictions, transitions, and approved reusable assets. It validates exact direction-to-idea coverage, sequence integrity, dependencies, and asset references. Scene Planner deliberately makes no camera, lens, shot, framing, composition, depth-of-field, motion, aspect-ratio, prompt, or generation decision.

After Scene Planner succeeds, Shot Planner writes `output/shot-plans/<project>-shot-plans.json`. In source-only mode it is a deterministic existing-asset framing planner: Python owns IDs, coverage, links, asset validation, and fallbacks, while optional AI output is limited to framing recommendations.

Image Processing Planner then reads the framing plans, current-project visual inventory, and immutable source manifest and writes `output/image-processing-plans/<project>-image-processing-plans.json`. It validates source files and hashes and prepares non-destructive crop, contain/letterbox resize, conservative enhancement, super-resolution, export, text-safe-area, and provenance instructions. It does not execute transformations, add branding or captions, generate backgrounds, or create or modify project content.

The source-only workflow extracts immutable images from project PDFs and approved image files into `output/source-images/<project>/`, records hashes and source-page provenance, and creates conservative metadata in `output/visual-analysis/`. Asset Selection processes only feasible ideas. Unsupported items become `skipped_unavailable` in `output/reports/<project>-content-availability.json`; the project continues without requesting or fabricating substitutes.

`PROJECT_VISUAL_MODE` defaults to `source_only`. Text-to-image generation, synthetic architecture, replacement imagery, generative fill, inpainting, and content-changing edits are forbidden. Technical enhancement may denoise, sharpen, correct exposure/white balance, upscale, crop, resize, and export while retaining source hashes and complete provenance.

## Architecture

`src/core` owns non-AI file processing: PDF reading, Markdown writing, file discovery, and logging. `src/ai` owns the orchestrator, shared agent contract, and single-responsibility agent placeholders. `src/knowledge` owns JSON schema and validation concerns. `src/models` contains domain models, and `src/utils` centralizes paths and general helpers.

## Knowledge Extraction Engine

The Knowledge Extraction Engine defines a structured `ProjectKnowledge` artifact for real-estate catalogues. It captures project details, branding, pricing, units, amenities, architecture, investment, and catalogue-supported marketing data through nested dataclasses. The artifact can be validated, serialized to JSON, and saved or loaded from `output/knowledge/`.

To extract knowledge from the first Markdown file in `output/markdown/`, add `OPENAI_API_KEY` to a local `.env` file and run:

```bash
python extract_knowledge.py
```

Create `.env` in the project root, add your OpenAI API key there, and never commit this file to Git. It is already ignored by `.gitignore`.

The extractor asks OpenAI for strict JSON, validates it against the local dataclass model, and writes `output/knowledge/<project-name>.json`. It records only facts present in the catalogue and does not create marketing ideas, image prompts, or captions.

Agents communicate only through saved artifacts. The orchestrator defines their order and will eventually pass output artifact paths between stages; agents never call each other directly.

## Multi-agent workflow

```text
PDF
  -> PDF Agent (Markdown)
  -> Knowledge Agent (knowledge.json)
  -> Knowledge Evaluation (evaluation.json)
  -> Visual Asset Extraction (immutable source images)
  -> Visual Asset Analysis (metadata only)
  -> Asset Intelligence Agent (visible semantics; cached per source hash)
  -> Semantic Visual Inventory
  -> Marketing Strategist Agent (strategy.json)
  -> Content Planner (inventory-grounded content-plan.json)
  -> Creative Director Agent (feasible ideas only)
  -> Asset Selection Planner (ready items; unavailable items skipped)
  -> Scene Planner Agent (scene-plans.json)
  -> Shot Planner Agent (source-image crops/layouts)
  -> Image Processing Planner (validated non-destructive instructions)
```

Image Processing Planner is the final implemented workflow stage. The planned downstream architecture is:

```text
Image Processing Planner
  -> Image Processing Engine (future execution of approved instructions)
  -> Brand Agent (branded images)
  -> Caption Agent (captions.json)
```

The Caption Agent consumes knowledge and strategy through an orchestrator-managed JSON artifact. This preserves the JSON-only communication boundary.

## Folder structure

```text
instagram-agent/
├── app.py
├── input/
├── output/
│   ├── markdown/  ├── knowledge/  ├── strategy/  ├── prompts/
│   ├── images/    └── captions/
├── assets/logos/
├── data/
├── tests/
└── src/
    ├── ai/
    │   ├── orchestrator.py
    │   ├── shared.py
    │   └── agents/
    ├── core/
    ├── knowledge/
    ├── models/
    └── utils/
```

The `output/` directory includes `reports/`, `strategy/`, `content/`, `creative-directions/`, `scene-plans/`, and `shot-plans/` alongside the existing artifact folders. Content plans, creative directions, scene plans, and shot plans are saved as independent, validated JSON artifacts.

## Agent responsibilities

Each agent has a constructor, a `run()` entry point, a documented input/output contract, and logging. Implemented AI stages use strict structured JSON responses and validate them locally before saving. Unimplemented downstream agent classes remain placeholders. `PdfAgent` is the future workflow-facing PDF-to-Markdown stage; the present `app.py` workflow remains the production entry point.

## Roadmap

1. Implement artifact creation and validation for each JSON contract.
2. Implement agents one at a time behind their existing `run()` interfaces.
3. Connect those agents in `Orchestrator.run()` once each stage is verified.
4. Add AI providers, image generation, branding, and caption generation without changing the package layout or contracts.
# Asset-first planning

The planning system is asset-first. It identifies authentic visual opportunities before creating campaigns or content. Every content item must be supported by approved project assets and factual source evidence. Asset scarcity, reuse, confidence, funnel purpose, and campaign memory are enforced deterministically.

## Fast Development Commands

Run the planning upgrade and all dependent downstream stages for one project while reusing knowledge, authentic images, Asset Intelligence, and semantic inventory:

```powershell
python app.py --project "320M2" --from-stage visual-opportunities
```

Run only the Smart Content Planner after validating its prerequisites:

```powershell
python app.py --project "320M2" --stage content-planner
```

Resume from the first missing, stale, incomplete, or failed stage:

```powershell
python app.py --resume
```

List canonical stage identifiers:

```powershell
python app.py --list-stages
```
# Source-grounded image prompts

The Image Prompt Generator converts validated source assets and planning artifacts into production-ready image-editing/composition prompts. It never asks a model to recreate the real-estate project from imagination. Authentic project imagery remains the visual source of truth.

Run it with `python app.py --stage image-prompt-generator --project "<project>"` or continue from it with `python app.py --from-stage image-prompt-generator --project "<project>"`.
# Production Commands

Run `python app.py --project "<project>" --from-stage deterministic-image-processor`, `python app.py --project "<project>" --stage image-output-qa`, or `python app.py --project "<project>" --stage review-gallery`.

The deterministic production workflow applies only validated non-generative operations to authentic source images. It preserves project geometry and content, performs automated QA, records complete provenance, and creates a local human-review gallery.

Use `python app.py --project "<project>" --stage detail-preservation-enhancer` to create conservative, non-generative detail derivatives. Exact extracted originals remain immutable under `output/source-images/<project>/originals/`; enhancement and platform resizing are distinct provenance stages.
## Platform-aware planning

Planning defaults to `both_platform_optimized`. `--platform-strategy` also accepts `instagram_only`, `facebook_only`, and `both_mirrored`. Before publishing, `--publish-target` accepts `instagram`, `facebook`, `both`, or `use_planned` without rewriting campaign history. `python app.py --meta-status` reports independent readiness. Credentials remain environment-only; tests and dry runs make no Meta requests.
# Cloudflare R2 media hosting

Meta can only fetch public media URLs. Set `media_hosting_mode` to `cloudflare_r2` in `input/publishing/meta-config.json`, configure the five `R2_*` variables shown in `.env.example`, and run `python app.py --media-host-status`. Upload current branded release media with `python app.py --project "PROJECT" --stage media-hosting`; this never publishes to Meta. Records are retained in `output/publishing/media-hosting/<project>-r2-media.json` and unchanged verified objects are reused. Cloudflare's public `r2.dev` URL is supported for development; use a custom HTTPS domain for production. Never commit `.env` or log R2/Meta credentials.

## Source intelligence and knowledge audit

Knowledge v2 adds exactly four canonical `project_identity` fields: `project_name`, `developer_name`, `project_type`, and `location`. Missing values remain empty/unavailable; the developer is never substituted with the broker, architect, contractor, or consultant. Important identity facts carry internal page/document provenance where direct textual support is found.

Run `python app.py --project "PROJECT" --knowledge-audit` for a read-only source → extracted content → structured knowledge → fused knowledge diagnostic. It writes human-readable `.txt` and machine-readable `.json` reports under `output/reports/`. The report uses observed document/page/table/visual/fact counts and deliberately does not invent a completeness percentage. This command performs zero Meta writes.

Visual intelligence v2 classifies authentic assets into real-estate categories such as villa/building exterior or interior, site plan, masterplan, villa layout, floor plan, community services, landscape, amenities, location map, entrance, streetscape, clubhouse, pool, commercial area, parking, and technical plan. Low-confidence evidence remains `unknown`. Semantic selection, captions, preservation instructions, package traceability, generic-copy detection, duplicate-copy detection, and marketing-comprehension QA consume this metadata.

Run `python app.py --project "PROJECT" --stage deep-source-analysis` for deterministic page-by-page PDF understanding. It writes page records and merged source-grounded knowledge under `output/knowledge/<project>/`, plus coverage and page-audit JSON/Markdown under `output/reports/`. Every fact retains page provenance; unresolved or image-only ambiguity produces `knowledge_status: partial` instead of silent completion. This stage makes no internet, image-generation, publishing, or Meta calls and does not feed current ranking or branded-content behavior.

### Source image ranking

Run `python app.py --project "PROJECT" --stage source-image-ranking` to recursively score extracted source images without making AI or Meta requests. The deterministic stage combines resolution, sharpness, clarity, compression indicators, crop suitability, social aspect ratio, exact/perceptual duplicate checks, and existing Asset Intelligence semantics. It prioritizes a genuine full-project site plan or masterplan, then exterior architecture, interiors, and amenities/lifestyle; unit and floor plans remain low-priority supporting material. It writes a project ranking JSON, Markdown summary, and deterministic `content-plan-<project>.md` under `output/inventory/`, then copies at most ten genuinely strong `HIGH`/`MEDIUM` assets to `output/selected-images/<project>/`. Originals are never moved or modified; maps, logos, text-heavy pages, corrupted files, weak images, and duplicates are penalized or rejected.

### Branded content from selected originals

Run `python app.py --project "PROJECT" --stage project-brand-identity` to deterministically inspect early catalogue assets for authentic project wordmark artwork. Verified crops and provenance are written to `output/project-brand/<project>/` and `output/inventory/project-brand-<project>.json`. The stage never guesses fonts or removes backgrounds when doing so could damage the mark; unavailable identity records explicitly select neutral fallback typography.

Run `python app.py --project "PROJECT" --stage branded-content` to render the first two explicitly grouped content-plan posts at 1080×1350. The deterministic stage consumes `content-plan-<project>.json` rather than re-sorting by visual score: a full-project overview defaults to `post-001/post.jpg`, while all approved, non-duplicate assets confidently belonging to the same villa story become a variable-length `post-002/slide-XX.jpg` carousel, capped only by Instagram’s ten-slide limit. Villa ordering favors exterior overview, additional exterior/detail perspectives, villa-specific interiors, then villa-specific amenities. It accepts only selected `HIGH`/`MEDIUM` records, verifies source hashes, uses the locked approved Domus Erbil logo without recoloring or distortion, and requires the verified structured project name. Full-project site plans use a non-destructive safe fit. The manifest is `output/inventory/branded-content-<project>.json`. No AI, image-generation, publishing, or Meta APIs are called.
