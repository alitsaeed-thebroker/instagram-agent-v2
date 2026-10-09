# AI Real Estate Marketing Agent — Master Pipeline Blueprint

> **AUTHENTIC SOURCE IMAGE POLICY — AUTHORITATIVE:** The current production system creates marketing materials exclusively from authentic developer-approved project images. Synthetic project imagery is disabled by default. This policy supersedes any legacy text-to-image examples retained elsewhere in this document for backward-contract history.

## Global Brand Kit Stage

`brand-kit-analysis` is a global, deterministic foundation rather than a per-project content stage. It reads `input/brand/brand-config.json`, scans only user-supplied official logos in `input/brand/logos/`, validates conservative brand rules, and publishes `output/brand-analysis/domus-erbil-logo-inventory.json`. Its cache key covers the configuration hash, every logo hash, module version, and schema version; a project argument never duplicates its output.

Downstream branding must consume approved brand-kit data only. The pipeline never generates or guesses the Domus Erbil logo and never changes logo originals. Missing logos or unconfirmed contact, color, and font details are warnings until approved. Contact information must be verified before public output. Brand Composer, overlays, captions, QR codes, and publishing remain outside this stage.

### Phase 20A: Brand identity and readiness

`brand-identity-analyzer` deterministically extracts significant visible logo colors, ignoring transparent/near-transparent pixels and insignificant antialias or compression noise. It reports coverage, luminance, white/dark contrast, text-safety recommendations, restrained usage roles, transparency, and background compatibility. Derived colors carry `logo_derived`; they are usable working colors, never claims of officially documented corporate colors. Existing `official_confirmed` and `user_confirmed` colors are not overwritten.

Typography is an intentional `system_selected` production policy, not font identification: Segoe UI with safe Latin and Arabic-script fallbacks, role metadata, and explicit English LTR plus Arabic/Kurdish Sorani RTL rules. No fonts are downloaded or copied. `brand-readiness-validator` treats a valid identity, verified logo, website, safe color policy, and production-safe typography as blocking requirements; optional contacts and lack of an official font are warnings. `--approve-brand` accepts only `ready` or `ready_with_warnings` and stores locked configuration/logo hashes. Drift revokes the approval.

### Phase 20: Brand Composer

The implemented post-QA sequence is `image-output-qa → brand-composer → branded-image-qa`. The Brand Composer applies approved Domus Erbil branding as deterministic graphic overlays on QA-passed authentic project imagery. It does not regenerate or modify project content. All visible marketing claims must be supported by verified source evidence.

Phase 20B requires `approval.status=approved`, `approval.locked=true`, an exact normalized `approved_config_hash`, the exact approved preferred-logo hash, and current readiness of `ready` or `ready_with_warnings`. Drift stops composition and causes the readiness validator to revoke stale approval. Only produced/produced-with-warnings items with passed/passed-with-warnings source QA, matching project identity, an existing source, and an exact source hash are eligible.

Composition plans contain deterministic IDs, source/campaign/content provenance, measured positions, safe margins, overlay masks, protected regions, contrast policy, the locked palette and typography, supported editorial text, and warnings. Rendering uses the unchanged approved logo, `#781810` as logo-derived primary, white and `#111111` neutrals, Segoe UI with approved fallbacks, exact `domuserbil.com`, and no absent contact placeholders. Branded QA generates the branded manifest and interactive local review gallery; it never publishes, schedules, captions, or sends analytics.

### Final Foundation Hardening

The canonical post-brand sequence is `branded-image-qa → creative-visual-qa → self-correction → provenance-audit → production-quality-report → release-manager`. Creative QA never edits images. Correction is deterministic, item-scoped, provenance-logged, and bounded to two attempts; invalid authentic sources are reported rather than replaced. Provenance failure blocks only affected outputs unless cross-project contamination compromises the project.

Release Manager automatically includes only items with passing technical/branded QA, Creative QA of at least 85, valid provenance, a current brand lock, and no blocked errors. Every release and production run receives a new directory and manifest; prior completed artifacts remain untouched. Health and regression commands exercise integrity and orchestration without adding human approval, publishing, scheduling, or analytics.

### Phase 21: Grounded post packages

After release creation, the canonical text sequence is `content-grouping-analyzer → caption-generator → hashtag-generator → alt-text-generator → post-package-builder → post-package-qa`. The content layer groups creatives into actual social-media units before generating copy. Carousel slides share one master caption while retaining asset-specific alt text and provenance. Captions retrieve only relevant verified facts and never expose internal validation language. Each stage is deterministic, language-aware, project-isolated, dependency-cached, and independently forceable.

`social-content-review` follows Post Package QA and provides an offline visual inspection interface for actual production assets, carousel order, customer-facing copy, accessibility text, QA, source comparison, and provenance. It is informational only, requires no approval, and performs no generation or publishing.

The publishing sequence is `publishing-queue → scheduling-engine → publish-preflight → mock-platform-adapter → publication-manifest`. Scheduling is optional and defaults to unscheduled manual mode. Preflight revalidates package, media, copy, provenance, brand lock, release, schedule, and idempotency immediately before adapter execution. The mock adapter writes normalized local payloads and clearly marked dry-run receipts without credentials or external API access.

Real Instagram publication follows `publishing-queue → scheduling-engine → publish-preflight → meta-platform-adapter → publication-manifest` only under explicit real-publish invocation. The adapter never regenerates content, preserves carousel order, requires a public HTTPS URL for every image, stores partial remote container state for safe retries, and checks real-receipt idempotency before any Meta request.

The final package joins the released branded image/hash, platform/language, caption, CTA, classified hashtags, accessible alt text, campaign/content identifiers, brand hash, quality, and provenance. QA scores factual accuracy, alignment, voice, platform fit, hashtags, alt text, CTA, and provenance. The layer produces content artifacts only and has no publishing or social-network integration.

Composition plans record source and logo hashes, exact text and evidence references, layout coordinates, safe zones, typography, neutral or approved palette, and overlay masks. Branded QA applies the defined 100-point score with critical failures overriding. Successful runs also create the branded production manifest and local before/after review gallery; review decisions remain manual JSON and are never published automatically.

Status: architecture specification  
Document version: `2.0.0`  
Scope: the complete system from source upload through campaign publishing, analytics, regeneration, localization, and CRM handoff  

This document is the architectural source of truth for the remainder of the project. It describes contracts and boundaries; it does not imply that unfinished modules are implemented.

## 1. Architectural goals and rules

The system converts one or more project documents and approved visual assets into a traceable, reviewable, publishable real-estate campaign. Every factual marketing claim must be traceable to fused project knowledge. Every generated output must be reproducible from versioned inputs, settings, and provenance.

The non-negotiable rules are:

1. The Orchestrator is the only component that sequences modules.
2. Modules never call one another directly.
3. Modules communicate through immutable, schema-validated artifacts and artifact references.
4. A project has one canonical fused knowledge artifact per revision.
5. Generated media never overwrites source or previously approved media.
6. Publishing always requires an explicit approval gate.
7. External AI providers are accessible only through the AI Provider Gateway.
8. Platform and CRM credentials are accessible only through their dedicated adapters.
9. A failed stage cannot silently produce an apparently successful downstream artifact.
10. All artifacts carry project, run, schema, lineage, language, and creation metadata.
11. `PROJECT_VISUAL_MODE` defaults to `source_only`; no production stage may generate, reconstruct, replace, inpaint, or outpaint project content.
12. Every final visual must trace to one or more immutable approved source images. Unsupported ideas are marked `skipped_unavailable`; feasible ideas continue without requesting or generating substitutes.

### Source-only visual production pipeline

```text
Knowledge Extraction
  -> Visual Asset Extraction
  -> Visual Asset Analysis
  -> Available-Content Inventory
  -> Marketing Strategy
  -> Content Planner (source-supported ideas only)
  -> Creative Director (feasible ideas only)
  -> Asset Selection Planner
  -> Scene Planner (approved-image narrative order)
  -> Shot Planner (safe crop/layout variants)
  -> Layout Planner
  -> Prompt Generator (editing instructions, never text-to-image)
  -> Image Enhancement / Processing Engine
  -> Brand Composer
  -> Final Marketing Assets + provenance
```

Approved project PDFs and separately approved project images are the only visual source of truth. Extracted images are immutable. Unknown visual facts remain unknown. A content item with no suitable support is recorded in the availability report as `skipped_unavailable`; it does not enter Creative Direction or production, and it does not stop other items.

## 2. Complete pipeline diagram

```text
Workspace / Project Registry
        |
        v
Project Intake + Source Asset Registration
        |
        v
PDF Discovery -> PDF Reader -> Document Classification -> Markdown Extraction
        |                                                  |
        +---------------- one branch per document ---------+
                                                           v
                                               Knowledge Extraction
                                                           |
                                                           v
                                                 Knowledge Fusion
                                                           |
                                                           v
                                               Knowledge Evaluation
                                                           |
                                          [quality gate: pass/review]
                                                           |
                                                           v
                                              Marketing Strategy
                                                           |
                            +------------------------------+------------------+
                            v                                                 v
                    Campaign Planner                                  Content Planner
                            +------------------------------+------------------+
                                                           v
                                                Production Brief Builder
                                                           |
                                                           v
                                                   Creative Director
                                                           |
                                                           v
                                                     Scene Planner
                                                           |
                                                           v
                                                      Shot Planner
                                                           |
                                                           v
                                                   Prompt Generator
                                                           |
                                      +--------------------+-------------------+
                                      v                                        v
                              Image Generator                       Future Video Generator
                                      |                                        |
                                      +--------------------+-------------------+
                                                           v
                                                Asset Quality Control
                                                           |
                                                           v
                                                  Brand Composer
                                                           |
                                  +------------------------+-------------------+
                                  v                                            v
                         Caption/Hashtag Generator                    Localization Module
                                  +------------------------+-------------------+
                                                           v
                                                 Post Package Assembler
                                                           |
                                                           v
                                              Human Review / Approval Gate
                                         reject | revise | approve | schedule
                                            |       |         |
                                            |       |         v
                                            |       |   Publishing Scheduler
                                            |       |         |
                                            |       |         v
                                            |       |   Instagram Publisher
                                            |       |         |
                                            |       |         v
                                            |       |   Publication Receipt
                                            |       |         |
                                            |       |         v
                                            |       |   Analytics Collector
                                            |       |         |
                                            |       |         v
                                            |       +-- Performance Normalizer
                                            |                 |
                                            |                 v
                                            +---------- Insight Engine
                                                              |
                                                              v
                                                    Regeneration Request
                                                              |
                                                      selective re-entry
                                                      at owning stage

Optional side flows:
  CRM Sync <-> approved leads/campaign attribution/publication events
  Asset Registry <-> every media-producing and media-consuming stage
  Run Ledger <-> every stage transition, retry, approval, and external call
  AI Provider Gateway <-> approved AI-consuming modules only
```

Completed foundation stages are Project Folder Management, Multi-PDF Reader, Document Classification, Markdown Extraction, Knowledge Extraction, Knowledge Fusion, Knowledge Evaluation, Marketing Strategy Engine, and Content Planner. Everything after Content Planner, plus the production-grade orchestration and registries around it, remains to be built unless explicitly marked otherwise by future implementation records.

## 3. Canonical artifact envelope

All JSON artifacts must use a common envelope. Existing JSON files may be read through a compatibility adapter until migrated.

```json
{
  "schema": "content_plan",
  "schema_version": "1.0.0",
  "artifact_id": "art_01J...",
  "project_id": "prj_beverly_hills",
  "run_id": "run_01J...",
  "revision": 1,
  "language": "en",
  "status": "succeeded",
  "created_at": "2026-08-06T10:00:00Z",
  "created_by": "content_planner@1.0.0",
  "inputs": [
    {"artifact_id": "art_knowledge", "sha256": "..."},
    {"artifact_id": "art_strategy", "sha256": "..."}
  ],
  "payload": {},
  "warnings": [],
  "provenance": {
    "model": null,
    "provider_request_id": null,
    "prompt_template_version": null,
    "settings_hash": "..."
  }
}
```

Required semantics:

- `artifact_id` is immutable and globally unique.
- `revision` increases when an artifact is regenerated; an old revision is never overwritten.
- `inputs` forms the lineage graph.
- `status` is one of `pending`, `running`, `succeeded`, `failed`, `blocked`, `superseded`, or `approved`.
- `sha256` detects corruption and provides content identity.
- `payload` is validated against the schema named by `schema` and `schema_version`.
- Secret values, full provider responses containing sensitive data, and credentials must never enter artifacts.

## 4. Module inventory and responsibilities

### Asset Intelligence Agent

The Asset Intelligence Agent analyzes authentic extracted project visuals and creates a semantic inventory. It describes only what is visibly present and never generates or invents project content. It classifies photographs, plans, maps, diagrams, logos, graphics, construction imagery, and uncertain assets with explicit confidence, quality, crop-safety, marketing-suitability, restrictions, warnings, and complete provenance. Analysis is isolated per asset and cached using source SHA-256, module version, prompt-template version, and model policy. Failed or uncertain assets remain visible for review but cannot silently become production-ready.

Its artifact is `output/asset-intelligence/<project>-asset-intelligence.json`; it rebuilds `output/visual-inventory/<project>-visual-inventory.json` as the authoritative categorized semantic inventory. Python performs final semantic filtering and ranking for Content Planner and Asset Selection. Unknown or review-required assets cannot prove specific features, and assets showing no people cannot support testimonials, interviews, resident behavior, or fabricated lifestyle stories.

### Content-based document discovery

Accepts PDF, JPG, JPEG, PNG, and WEBP sources. It derives project identity, document type, purpose, roles, language, structure, text/visual density, and confidence from document contents and decoded structure only. Filenames are traceability fields and must never influence identity, classification, priority, or purpose. Supported classifications include Catalogue, Brochure, Presentation, Master Plan, Floor Plans, Price List, Payment Plan, Location Map, Technical Specifications, Lifestyle Gallery, Architectural Render Collection, Legal Document, Brand Guidelines, Mixed Document, and Unknown. Low-confidence and ambiguous sources remain available for extraction and are reported rather than discarded.

The discovery artifact is `output/inventory/<project>-document-analysis.json`. It records each source's classification, confidence, evidence, discovered roles, language, purpose, page/image counts, density, structure, headings, tables, recurring terms, project assignment, and warnings. Content-identical project evidence groups sources across folders; absent or conflicting identity evidence creates explicit project candidates for later review.

### 4.1 Completed foundation modules

| Module | Responsibility | Canonical output |
| --- | --- | --- |
| Project Folder Management | Discover projects, isolate paths, and assign stable project identities. | `project_manifest.json` |
| Multi-PDF Reader | Read all supported PDFs without interpreting business facts. | document read results |
| Document Classification | Classify documents; deterministic filename/title/keyword checks precede AI fallback. | `classification.json` |
| Markdown Extraction | Preserve readable per-page source text. | `.md` plus metadata JSON |
| Knowledge Extraction | Extract only source-supported structured facts per document. | per-document knowledge JSON |
| Knowledge Fusion | Merge facts, apply source precedence, and report conflicts. | canonical `knowledge.json` |
| Knowledge Evaluation | Score completeness, grounding, consistency, and readiness. | `evaluation.json` |
| Marketing Strategy Engine | Derive audience, positioning, messages, channels, and campaign themes. | `strategy.json` |
| Content Planner | Convert knowledge and strategy into detailed content pillars and ideas. | `content-plan.json` |

These stages remain authoritative. Future work may wrap their current payloads in the common envelope but must not change their meanings without a schema migration.

### 4.2 Remaining core control modules

| Module | Responsibility |
| --- | --- |
| Project Registry | Maintain stable project IDs, lifecycle status, default language, ownership, and active revisions. |
| Asset Registry | Index every source, generated, derivative, approved, and published asset with lineage and rights metadata. |
| Run Ledger | Record workflow state, stage attempts, errors, timings, costs, and idempotency keys. |
| Pipeline Orchestrator | Resolve dependencies, execute stages, validate handoffs, retry safe failures, and pause at gates. It contains no creative logic. |
| Contract Validator | Validate envelopes, payload schemas, enumerations, references, hashes, and compatibility before consumption. |
| AI Provider Gateway | The only module permitted to call the OpenAI API; applies model policy, structured output, budgets, retries, redaction, and audit logging. |
| Approval Service | Record human decisions and comments; enforce that only approved revisions can publish. |

### 4.3 Remaining creative production modules

| Module | Responsibility |
| --- | --- |
| Campaign Planner | Group planned posts into named campaigns, objectives, audiences, priorities, and sequence. A foundation schema exists; production integration remains. |
| Production Brief Builder | Join campaign posts and content ideas into one unambiguous brief per deliverable. |
| Creative Director | Act as the campaign's senior creative authority: decide the campaign concept, visual identity, emotional and storytelling direction, brand constraints, luxury level, realism level, intended audience perception, overall artistic vision, and creative-consistency approval. It never decides camera, lens, shot, composition, or prompt wording. |
| Visual Asset Extraction | Extract immutable images from project PDFs and copy approved project image files byte-for-byte; assign source IDs, hashes, document/page coordinates, dimensions, and extraction metadata. |
| Visual Asset Analysis | Produce conservative metadata about only what is visibly verified; unknown content remains unknown and requires review. |
| Asset Selection Planner | Select approved source IDs for feasible ideas and record unsupported items as skipped. It never requests or fabricates a substitute. |
| Scene Planner | Order approved source images into a marketing narrative: introduction, trust reinforcement, closing visual, and transitions. It cannot invent a view or scene. |
| Shot Planner | Plan safe crop windows, zoom, platform framing, text-safe areas, logo-safe areas, and layout improvements for existing source images. It cannot invent a camera angle or unseen content. |
| Prompt Generator | Produce structured non-generative editing instructions such as denoise, sharpen, margin removal, exposure correction, crop, resize, and export. It cannot write text-to-image prompts. |
| Image Processing Engine | Apply deterministic technical enhancement to approved source images while preserving geometry, architecture, proportions, materials, colors, lighting character, and visible features. |
| Image Processing Planner | Validate current-project authentic files and hashes, then create one traceable, non-destructive preparation plan per feasible framing plan. It may plan bounded crop, contain/letterbox resize, conservative correction, super-resolution when required, and platform exports, but never executes edits or generates project content. |

### Image Processing Planner artifact

The implemented Image Processing Planner consumes `output/source-images/<project>/manifest.json`, `output/visual-inventory/<project>-visual-inventory.json`, and `output/shot-plans/<project>-shot-plans.json`. It writes `output/image-processing-plans/<project>-image-processing-plans.json`. Python controls deterministic IDs, one-to-one framing coverage, source-file existence, hash verification, normalized crop bounds, positive export dimensions, operation allowlists, project isolation, fallbacks, counts, and provenance. Text-only records use approved references and future neutral-template placeholders without fabricating a background. This stage produces instructions only; it performs no transformation, branding, captioning, publishing, inpainting, or synthetic image generation.
| Asset Quality Control | Perform deterministic technical checks and AI-assisted semantic/brand/factual checks; route failures to regeneration. |
| Brand Composer | Apply logos, typography, overlays, safe zones, legal text, and export presets without modifying the raw master. |
| Caption and Hashtag Generator | Produce grounded platform copy, CTA, accessibility text, hashtag sets, and claim references. |
| Localization Module | Produce locale-specific copy variants while preserving facts, brand voice, layout constraints, and translation review status. |
| Post Package Assembler | Bind final media, copy, alt text, locale, platform settings, campaign attribution, and approval requirements. |

### 4.4 Remaining delivery and feedback modules

| Module | Responsibility |
| --- | --- |
| Publishing Scheduler | Resolve approved packages into platform-aware times, queues, time zones, and idempotency keys. |
| Instagram Publisher | Publish or schedule through the Instagram/Meta adapter and persist the platform receipt. Never generates content. |
| Analytics Collector | Poll or receive platform metrics and retain immutable snapshots. |
| Performance Normalizer | Map platform-specific metrics into canonical impressions, reach, engagement, clicks, leads, and conversions. |
| Insight Engine | Compare outcomes with campaign intent and recommend evidence-based changes; never changes approved content automatically. |
| Regeneration Controller | Convert rejection, QC, or analytics feedback into a scoped regeneration request and select the earliest affected stage. |
| CRM Adapter | Send consented leads and attribution events to a configured CRM and reconcile external IDs. |
| Video Brief Builder | Extend a production brief with scenes, duration, motion, narration, audio, and aspect-ratio requirements. |
| Video Generator | Generate shots/clips through a replaceable provider adapter and save raw video masters. |
| Video Assembly and QC | Assemble clips, captions, audio, transitions, brand treatment, and technical validation. |

## 5. JSON contracts for every remaining module

Examples below show the significant `payload`; every request and result is carried inside the canonical envelope. Artifact references are preferred over copying large upstream payloads.

### 5.1 Project Registry

Input:

```json
{"operation":"register","project":{"display_name":"Beverly Hills","slug":"beverly-hills","default_language":"en","timezone":"Asia/Baghdad","owner_id":"usr_123"}}
```

Output:

```json
{"project_id":"prj_beverly_hills","status":"active","workspace_path":"projects/prj_beverly_hills","active_revisions":{"knowledge":1,"strategy":1,"content_plan":1}}
```

### 5.2 Asset Registry

Input:

```json
{"operation":"register","asset":{"project_id":"prj_beverly_hills","kind":"source_logo","uri":"assets/projects/prj_beverly_hills/source/logos/logo.svg","sha256":"...","mime_type":"image/svg+xml","rights":{"status":"approved","expires_at":null}}}
```

Output:

```json
{"asset_id":"ast_01J...","state":"source","revision":1,"lineage":[],"usage_policy":{"allowed_channels":["instagram"],"ai_reference_allowed":true}}
```

### 5.3 Run Ledger

Input:

```json
{"operation":"record_transition","run_id":"run_01J...","stage":"image_generation","attempt":2,"from":"running","to":"succeeded","idempotency_key":"run_01J:image_generation:brief_7:r2","metrics":{"duration_ms":18420,"estimated_cost_usd":0.08}}
```

Output:

```json
{"event_id":"evt_01J...","recorded":true,"run_status":"running","next_stage":"asset_quality_control"}
```

### 5.4 Pipeline Orchestrator

Input:

```json
{"operation":"start_or_resume","project_id":"prj_beverly_hills","pipeline_version":"1.1.0","start_from":"production_brief","targets":["instagram"],"languages":["en"],"dry_run":false}
```

Output:

```json
{"run_id":"run_01J...","status":"blocked","current_stage":"human_approval","completed_stages":["production_brief","creative_direction","scene_planning","shot_planning","prompt_generation","image_generation","quality_control","brand_composition","caption_generation","package_assembly"],"blocked_reason":"approval_required"}
```

### 5.5 Contract Validator

Input:

```json
{"artifact_ref":{"artifact_id":"art_prompt_7","uri":"projects/prj_beverly_hills/artifacts/prompts/art_prompt_7.json"},"expected_schema":"image_prompt","accepted_versions":[">=1.0.0 <2.0.0"]}
```

Output:

```json
{"valid":false,"errors":[{"code":"MISSING_FIELD","path":"payload.prompts[0].aspect_ratio","message":"Required field is missing"}],"warnings":[],"validated_sha256":"..."}
```

### 5.6 AI Provider Gateway

Input:

```json
{"request_id":"air_01J...","task":"creative_direction","requesting_module":"creative_director@2.0.0","model_policy":"text_structured_standard","input_artifacts":["art_brief_7","art_knowledge_3"],"template":{"id":"creative_direction","version":"2.0.0"},"output_schema":"creative_direction@2.0.0","limits":{"max_output_tokens":3000,"max_cost_usd":0.15},"safety":{"personal_data":"none"}}
```

Output:

```json
{"request_id":"air_01J...","status":"succeeded","provider":"openai","model":"policy-resolved-model","provider_request_id":"req_...","structured_output":{"concept":"A quiet arrival into refined family living"},"usage":{"input_tokens":2100,"output_tokens":850,"estimated_cost_usd":0.04},"attempts":1}
```

### 5.7 Approval Service

Input:

```json
{"subject":{"artifact_id":"art_post_package_7","revision":2},"decision":"approved","reviewer_id":"usr_123","comment":"Approved for Instagram feed","scope":{"platform":"instagram","language":"en"}}
```

Output:

```json
{"approval_id":"apr_01J...","status":"approved","approved_artifact":{"artifact_id":"art_post_package_7","revision":2},"decided_at":"2026-08-06T12:30:00Z","revokes_approval_id":null}
```

### 5.8 Campaign Planner

Input:

```json
{"knowledge_artifact_id":"art_knowledge_3","strategy_artifact_id":"art_strategy_2","content_plan_artifact_id":"art_content_2","constraints":{"maximum_campaigns":3,"posts_per_campaign":3}}
```

Output:

```json
{"campaigns":[{"campaign_id":"cmp_legacy","campaign_name":"Invest in Your Future","objective":"Explain source-supported value","target_audience":"Affluent investors","priority":"high","post_refs":["idea_invest_01","idea_invest_02"]}]}
```

The current campaign schema remains valid during migration; stable IDs and artifact metadata should be additive in the next major contract.

### 5.9 Production Brief Builder

Input:

```json
{"campaign_artifact_id":"art_campaign_2","content_plan_artifact_id":"art_content_2","strategy_artifact_id":"art_strategy_2","knowledge_artifact_id":"art_knowledge_3","selected_idea_ids":["architecture_01"],"deliverables":[{"platform":"instagram","format":"feed","aspect_ratio":"4:5","language":"en"}]}
```

Output:

```json
{"briefs":[{"brief_id":"brf_architecture_01","idea_id":"architecture_01","objective":"Show architectural refinement","audience":"High-net-worth buyers","required_facts":[{"claim":"Premium natural stone finishes","knowledge_path":"architecture.materials[0]"}],"deliverables":[{"platform":"instagram","format":"feed","aspect_ratio":"4:5","resolution":{"width":1080,"height":1350}}],"asset_refs":[],"prohibited_claims":[]}]}
```

### 5.10 Creative Director

The Creative Director behaves like the creative director of a world-class luxury advertising agency. Its output is an artistic constitution for the campaign, not a production shot list. The schema deliberately has no camera, lens, shot, composition, framing, aspect-ratio, or prompt fields.

Input:

```json
{"brief_artifact_id":"art_brief_7","content_plan_artifact_id":"art_content_2","strategy_artifact_id":"art_strategy_2","brand_kit_artifact_id":"art_brand_kit_1","available_asset_ids":["ast_logo","ast_render_01"],"reference_policy":"approved_assets_only","consistency_scope":"campaign"}
```

Output:

```json
{"creative_directions":[{"creative_direction_id":"cdr_7","brief_id":"brf_architecture_01","campaign_concept":"A Legacy of Refined Living","visual_identity":{"description":"Quiet contemporary luxury grounded in authentic materials","palette_intent":["warm limestone","charcoal","soft gold"],"texture_language":["natural stone","polished wood","soft textiles"]},"emotional_direction":{"primary_emotion":"assured aspiration","supporting_emotions":["belonging","calm","pride"]},"storytelling_direction":{"premise":"Follow a family from arrival into an evening of refined everyday living","arc":["anticipation","discovery","connection","belonging"]},"brand_constraints":["Use approved project identity only","Preserve architectural authenticity","Avoid ostentatious wealth clichés"],"luxury_level":"ultra-premium but understated","realism_level":"photorealistic and architecturally credible","audience_perception":"A discerning buyer should perceive the project as a credible family legacy, not a fantasy resort","artistic_vision":"Editorial luxury advertising with warmth, restraint, and human truth","reference_asset_ids":["ast_render_01"],"consistency_approval":{"status":"approved","criteria":["concept alignment","brand alignment","emotional coherence"]}}]}
```

Creative consistency approval confirms that a downstream scene or shot set aligns with this direction. It does not authorize the Creative Director to repair cinematography or prompt wording; those issues return to their owning modules.

### 5.11 Scene Planner

Input:

```json
{"creative_direction_artifact_id":"art_creative_direction_7","content_plan_artifact_id":"art_content_2","brief_artifact_id":"art_brief_7","content_idea_id":"family_lifestyle_01","available_asset_ids":["ast_render_01","ast_garden_reference","ast_living_room_reference"]}
```

Output:

```json
{"scene_plan_id":"scp_7","creative_direction_id":"cdr_7","content_idea_id":"family_lifestyle_01","scenes":[{"scene_id":"scn_7_01","sequence":1,"scene_name":"Arrival","story_purpose":"Introduce the home as the beginning of an assured family legacy","main_subject":"family arriving at the residence","supporting_subjects":["villa entrance","landscaping"],"environment":"approved villa entrance","time_of_day":"late afternoon","weather":"clear and mild","mood":"anticipatory and welcoming","lighting_direction":"warm natural light transitioning toward evening","scene_dependencies":[],"reusable_asset_ids":["ast_render_01"]},{"scene_id":"scn_7_02","sequence":2,"scene_name":"Garden","story_purpose":"Move from arrival to relaxed family connection","main_subject":"family sharing time outdoors","supporting_subjects":["garden planting","terrace"],"environment":"private garden","time_of_day":"golden hour","weather":"clear and mild","mood":"calm belonging","lighting_direction":"soft warm natural light","scene_dependencies":["scn_7_01"],"reusable_asset_ids":["ast_garden_reference"]}]}
```

The full example sequence may continue with Living Room, Dinner, and Night Exterior. Every scene must be necessary to the content idea's story. The Scene Planner may reuse approved assets, but it must not infer undocumented property features.

### 5.12 Shot Planner

Input:

```json
{"scene_plan_artifact_id":"art_scene_plan_7","creative_direction_artifact_id":"art_creative_direction_7","brief_artifact_id":"art_brief_7","scene_ids":["scn_7_01","scn_7_02"],"platform_targets":["instagram_feed","instagram_carousel","instagram_story","instagram_reel","website_banner","linkedin"]}
```

Output:

```json
{"shot_plan_id":"shp_7","scene_plan_id":"scp_7","shots":[{"shot_id":"sht_7_01_hero","scene_id":"scn_7_01","sequence":1,"shot_type":"hero_shot","is_hero_shot":true,"camera_height":"eye level","camera_angle":"three-quarter front angle","lens_recommendation":"35mm full-frame equivalent","composition":"Family enters along the lower-left visual path toward the villa entrance","depth_of_field":"moderate; family and entrance readable, distant background gently softened","camera_motion":"slow stabilized push-in for motion-capable formats; locked frame for stills","lighting_notes":"Preserve the Scene Planner's warm late-afternoon direction; retain natural shadow detail","framing":"wide environmental portrait","focus_subject":"arriving family","background_subject":"architecturally accurate villa entrance","negative_space":"upper right for optional approved headline","aspect_ratios":["4:5","1:1","9:16","16:9"],"future_platforms":["instagram_feed","instagram_carousel","instagram_story","instagram_reel","website_banner","linkedin"],"reference_asset_ids":["ast_render_01"]},{"shot_id":"sht_7_01_detail","scene_id":"scn_7_01","sequence":2,"shot_type":"detail_shot","is_hero_shot":false,"camera_height":"waist level","camera_angle":"slight oblique angle","lens_recommendation":"85mm full-frame equivalent","composition":"Close architectural material detail with a family gesture entering the frame edge","depth_of_field":"shallow","camera_motion":"subtle lateral slide for motion-capable formats","lighting_notes":"Warm grazing light reveals authentic material texture","framing":"close-up detail","focus_subject":"approved facade material","background_subject":"soft indication of family arrival","negative_space":"minimal","aspect_ratios":["4:5","9:16"],"future_platforms":["instagram_carousel","instagram_story","instagram_reel"],"reference_asset_ids":["ast_render_01"]}]}
```

`shot_type` is an extensible enumeration initially containing `hero_shot`, `wide_shot`, `medium_shot`, `close_up`, `detail_shot`, and `drone_shot`. A scene normally has multiple shots. The Shot Planner behaves like a cinematographer, but it never emits natural-language generation prompts or provider syntax.

### 5.13 Prompt Generator

The unit of work is one approved `shot_id`. One request produces one canonical prompt record for that shot; additional variations are separate prompt revisions or separately identified prompt records.

Input:

```json
{"approved_shot":{"shot_plan_artifact_id":"art_shot_plan_7","shot_id":"sht_7_01_hero","approval_id":"apr_shot_7_01"},"scene_plan_artifact_id":"art_scene_plan_7","creative_direction_artifact_id":"art_creative_direction_7","brief_artifact_id":"art_brief_7","prompt_policy":{"representation":"provider_neutral@1.0.0","include_negative_constraints":true}}
```

Output:

```json
{"prompt":{"prompt_id":"prm_sht_7_01_hero","shot_id":"sht_7_01_hero","representation_version":"1.0.0","subject_clause":"An arriving family approaching the architecturally accurate approved villa entrance","environment_clause":"Approved landscaped villa entrance in clear, mild late-afternoon weather","art_direction_clause":"Understated ultra-premium editorial luxury; photorealistic, warm, restrained, human","cinematography_clause":"Eye-level three-quarter front hero shot, 35mm full-frame equivalent, wide environmental portrait, moderate depth of field, family entering on the lower-left path, villa entrance readable, upper-right negative space","lighting_clause":"Warm natural late-afternoon light with preserved natural shadow detail","continuity_constraints":["Follow scene scn_7_01","Preserve creative direction cdr_7"],"fact_constraints":["Do not alter documented facade massing or materials"],"negative_constraints":["invented signage","undocumented architecture","distorted people","text","watermark"],"aspect_ratios":["4:5","1:1","9:16","16:9"],"reference_asset_ids":["ast_render_01"],"adapter_hints":{"motion_instruction":"slow stabilized push-in when the target provider supports motion","seed_policy":"record_provider_seed"}}}
```

The canonical record remains provider-neutral. Provider adapters are pure serializers that map it to OpenAI Images, Sora, Kling, Runway, Flux, Midjourney, Stable Diffusion, or a future provider. An adapter may omit an unsupported parameter or report a capability error; it must never add creative content, revise wording, invent defaults that alter meaning, or write changes back into the canonical prompt.

### 5.14 Image Generator

Input:

```json
{"prompt_artifact_id":"art_prompt_7","prompt_id":"prm_sht_7_01_hero","provider_adapter":"policy_resolved","generation_parameters":{"count":4,"quality":"high","transparent_background":false},"idempotency_key":"run_01J:prm_sht_7_01_hero:r1"}
```

Output:

```json
{"generations":[{"generation_id":"gen_7a_01","prompt_id":"prm_sht_7_01_hero","shot_id":"sht_7_01_hero","asset_id":"ast_raw_7a_01","state":"generated_raw","mime_type":"image/png","width":1024,"height":1280,"sha256":"...","execution":{"canonical_prompt_hash":"...","adapter":"openai_images@1.0.0","adapter_payload_hash":"..."},"provider_metadata":{"request_id":"req_...","seed":18472,"provider_output_hash":"..."}}]}
```

The Image Generator cannot rewrite either the canonical prompt or provider payload after adapter serialization. A provider that automatically revises a prompt must expose that fact in provenance; the original prompt remains authoritative and the result may be rejected by quality control.

### 5.15 Asset Quality Control

Input:

```json
{"asset_ids":["ast_raw_7a_01"],"brief_artifact_id":"art_brief_7","brand_kit_artifact_id":"art_brand_kit_1","checks":["decode","dimensions","aspect_ratio","visual_artifacts","fact_alignment","brand_safety","text_legibility","rights"]}
```

Output:

```json
{"results":[{"asset_id":"ast_raw_7a_01","status":"failed","score":0.71,"checks":[{"name":"dimensions","status":"passed"},{"name":"fact_alignment","status":"failed","code":"UNSUPPORTED_ARCHITECTURE_CHANGE","evidence":"Added an undocumented tower"}],"recommended_action":"regenerate","feedback":"Preserve the supplied facade massing and remove the tower"}]}
```

### 5.16 Brand Composer

Input:

```json
{"approved_raw_asset_id":"ast_raw_7a_02","brand_kit_artifact_id":"art_brand_kit_1","template_id":"instagram_feed_4x5_v2","copy_slots":{"headline":"A legacy shaped in stone","disclaimer":null},"export_presets":["instagram_feed_1080x1350"]}
```

Output:

```json
{"derivatives":[{"asset_id":"ast_branded_7a_02","parent_asset_id":"ast_raw_7a_02","state":"branded","template_id":"instagram_feed_4x5_v2","width":1080,"height":1350,"mime_type":"image/jpeg","sha256":"...","applied_elements":["logo","headline"]}]}
```

### 5.17 Caption and Hashtag Generator

Input:

```json
{"brief_artifact_id":"art_brief_7","knowledge_artifact_id":"art_knowledge_3","strategy_artifact_id":"art_strategy_2","visual_asset_id":"ast_branded_7a_02","platform":"instagram","language":"en","variants":3}
```

Output:

```json
{"captions":[{"caption_id":"cap_7a","variant":"primary","language":"en","body":"Refined materials meet generous family living...","cta":"Schedule a private viewing.","hashtags":["#LuxuryRealEstate","#ErbilHomes"],"alt_text":"Warm stone villa facade at sunset with the project logo.","claim_refs":[{"text":"natural stone finishes","knowledge_path":"architecture.materials[0]"}],"character_count":178}]}
```

### 5.18 Localization Module

Input:

```json
{"source_caption_artifact_id":"art_caption_7","source_language":"en","target_locales":["ar-IQ","ku-Arab-IQ"],"brand_glossary_artifact_id":"art_glossary_1","mode":"transcreate","require_human_review":true}
```

Output:

```json
{"localizations":[{"localization_id":"loc_7_ar","locale":"ar-IQ","direction":"rtl","body":"...","cta":"...","hashtags":["..."],"alt_text":"...","preserved_terms":["Beverly Hills"],"claim_refs":["architecture.materials[0]"],"review_status":"pending","layout_constraints":{"max_headline_chars":34}}]}
```

### 5.19 Post Package Assembler

Input:

```json
{"campaign_id":"cmp_legacy","brief_id":"brf_architecture_01","media_asset_ids":["ast_branded_7a_02"],"caption_id":"cap_7a","localization_ids":["loc_7_ar"],"platform":"instagram","placement":"feed","publish_settings":{"comments_enabled":true,"branded_content":false}}
```

Output:

```json
{"package_id":"pkg_7","status":"awaiting_approval","platform":"instagram","placement":"feed","media":[{"asset_id":"ast_branded_7a_02","order":1}],"copy":{"en":"cap_7a","ar-IQ":"loc_7_ar"},"validation":{"status":"passed","warnings":[]},"required_approvals":["content_owner","brand_owner"]}
```

### 5.20 Publishing Scheduler

Input:

```json
{"approved_package_id":"pkg_7","approval_ids":["apr_content","apr_brand"],"requested_time":"2026-08-10T19:00:00+03:00","timezone":"Asia/Baghdad","account_id":"ig_business_123","collision_policy":"move_to_next_slot"}
```

Output:

```json
{"schedule_id":"sch_7","package_id":"pkg_7","status":"scheduled","scheduled_at":"2026-08-10T19:00:00+03:00","publish_at_utc":"2026-08-10T16:00:00Z","idempotency_key":"ig_business_123:pkg_7:r2"}
```

### 5.21 Instagram Publisher

Input:

```json
{"schedule_id":"sch_7","package_id":"pkg_7","account_id":"ig_business_123","idempotency_key":"ig_business_123:pkg_7:r2","mode":"publish"}
```

Output:

```json
{"publication_id":"pub_7","status":"published","platform":"instagram","platform_media_id":"179...","permalink":"https://www.instagram.com/p/.../","published_at":"2026-08-10T16:00:08Z","package_revision":2,"receipt_hash":"..."}
```

### 5.22 Analytics Collector

Input:

```json
{"publication_ids":["pub_7"],"window":{"from":"2026-08-10T16:00:00Z","to":"2026-08-17T16:00:00Z"},"metrics":["impressions","reach","likes","comments","saves","shares","profile_visits","link_clicks"]}
```

Output:

```json
{"snapshots":[{"snapshot_id":"ana_7_d7","publication_id":"pub_7","captured_at":"2026-08-17T16:05:00Z","platform_metrics":{"impressions":18240,"reach":14100,"likes":920,"comments":31,"saves":188,"shares":94,"profile_visits":312,"link_clicks":77},"is_final":false}]}
```

### 5.23 Performance Normalizer

Input:

```json
{"analytics_snapshot_ids":["ana_7_d7"],"attribution_window_days":7,"campaign_id":"cmp_legacy"}
```

Output:

```json
{"publication_id":"pub_7","canonical_metrics":{"impressions":18240,"reach":14100,"engagements":1233,"engagement_rate_by_reach":0.0874,"clicks":77,"leads":4,"conversions":1},"formulas_version":"1.0.0","data_quality":"partial"}
```

### 5.24 Insight Engine

Input:

```json
{"campaign_artifact_id":"art_campaign_2","normalized_performance_ids":["perf_pub_7"],"comparison_window":"28d","minimum_sample":{"reach":5000},"knowledge_artifact_id":"art_knowledge_3"}
```

Output:

```json
{"insights":[{"insight_id":"ins_7","confidence":0.82,"finding":"Architecture detail posts generate above-baseline saves","evidence":{"publication_ids":["pub_7"],"lift_percent":31},"recommendation":"Create two additional detail-led variants","affected_stage":"content_planning","auto_apply":false}]}
```

### 5.25 Regeneration Controller

Input:

```json
{"trigger":{"type":"creative_review","source_id":"sht_7_01_hero","reason_code":"POOR_CAMERA_FRAMING","feedback":"Retain the scene and emotion; increase breathing room around the family and preserve headline space"},"scope":{"project_id":"prj_beverly_hills","brief_id":"brf_architecture_01","scene_id":"scn_7_01","shot_id":"sht_7_01_hero"},"requested_by":"usr_creative_reviewer"}
```

Output:

```json
{"regeneration_id":"regen_7","status":"queued","reentry_stage":"shot_planning","invalidate_descendants":["sht_7_01_hero","prm_sht_7_01_hero","ast_raw_7a_01","ast_branded_7a_01","art_package_7"],"preserve":["art_knowledge_3","art_strategy_2","art_content_2","art_brief_7","art_creative_direction_7","art_scene_plan_7","sht_7_01_detail"],"new_revision":2,"approval_required":true}
```

### 5.26 CRM Adapter

Input:

```json
{"operation":"upsert_lead","crm_connection_id":"crm_primary","lead":{"external_source":"instagram","consent":true,"name":"Prospect name","email":"prospect@example.com","phone":null,"project_id":"prj_beverly_hills","campaign_id":"cmp_legacy","publication_id":"pub_7","utm":{"source":"instagram","medium":"social","campaign":"legacy"}}}
```

Output:

```json
{"sync_id":"crm_sync_7","status":"succeeded","crm":"configured_provider","external_contact_id":"contact_123","deduplication":"matched_by_email","synced_fields":["name","email","project_id","campaign_id","publication_id"]}
```

### 5.27 Video Brief Builder

Input:

```json
{"production_brief_id":"brf_architecture_01","format":"instagram_reel","duration_seconds":15,"aspect_ratio":"9:16","language":"en","available_asset_ids":["ast_render_01","ast_logo"]}
```

Output:

```json
{"video_brief_id":"vbr_7","duration_seconds":15,"aspect_ratio":"9:16","scenes":[{"scene_id":"scn_1","start":0,"duration":4,"purpose":"establish project","visual":"slow facade reveal","source_asset_ids":["ast_render_01"],"on_screen_text":"A legacy shaped in stone"}],"audio":{"music_mood":"cinematic calm","voiceover":false},"captions_required":true,"end_card":{"duration":2,"cta":"Schedule a private viewing"}}
```

### 5.28 Video Generator

Input:

```json
{"video_brief_artifact_id":"art_vbr_7","scene_ids":["scn_1"],"provider_policy":"video_standard","generation":{"resolution":"1080x1920","fps":30,"variants":2},"idempotency_key":"run_01J:scn_1:r1"}
```

Output:

```json
{"clips":[{"clip_id":"clip_7_1a","scene_id":"scn_1","asset_id":"ast_clip_7_1a","state":"generated_raw","duration_seconds":4,"width":1080,"height":1920,"fps":30,"mime_type":"video/mp4","sha256":"...","provider_metadata":{"request_id":"req_..."}}]}
```

### 5.29 Video Assembly and QC

Input:

```json
{"video_brief_artifact_id":"art_vbr_7","selected_clip_ids":["clip_7_1a"],"brand_kit_artifact_id":"art_brand_kit_1","audio_asset_id":"ast_music_approved","caption_track_id":"ast_captions_en","export_preset":"instagram_reel_1080x1920"}
```

Output:

```json
{"video_asset_id":"ast_video_final_7","state":"branded","duration_seconds":15,"technical_qc":{"status":"passed","codec":"h264","audio_peak_db":-1.0,"captions_in_safe_zone":true},"content_qc":{"status":"passed","fact_alignment":true,"brand_alignment":true},"poster_asset_id":"ast_video_poster_7","sha256":"..."}
```

## 6. Folder structure

The target structure separates source material, immutable artifacts, working state, reusable assets, and exports. The project ID, not a user-editable display name, is the storage key.

```text
instagram-agent/
├── AI_PIPELINE.md
├── input/                              # backward-compatible intake only
├── projects/
│   └── <project_id>/
│       ├── project.json
│       ├── source/
│       │   ├── documents/
│       │   ├── images/
│       │   ├── logos/
│       │   ├── fonts/
│       │   └── rights/
│       ├── artifacts/
│       │   ├── classifications/
│       │   ├── markdown/
│       │   ├── knowledge/documents/
│       │   ├── knowledge/fused/
│       │   ├── evaluations/
│       │   ├── strategies/
│       │   ├── campaigns/
│       │   ├── content-plans/
│       │   ├── briefs/
│       │   ├── creative-directions/
│       │   ├── visual-analysis/
│       │   ├── asset-selections/
│       │   ├── scene-plans/
│       │   ├── shot-plans/
│       │   ├── prompts/
│       │   ├── captions/
│       │   ├── localizations/
│       │   ├── post-packages/
│       │   ├── approvals/
│       │   ├── schedules/
│       │   ├── publications/
│       │   ├── analytics/
│       │   └── insights/
│       ├── media/
│       │   ├── source-images/          # immutable approved visual truth
│       │   ├── enhanced/               # technical derivatives only
│       │   ├── generated/raw/images/
│       │   ├── generated/raw/video/
│       │   ├── qc-approved/
│       │   ├── branded/
│       │   ├── localized/
│       │   ├── thumbnails/
│       │   └── published/
│       ├── runs/<run_id>/
│       │   ├── run.json
│       │   ├── events.jsonl
│       │   ├── errors/
│       │   └── temporary/
│       └── exports/<campaign_id>/<platform>/<locale>/
├── assets/
│   ├── global/templates/
│   ├── global/fonts/
│   ├── global/music/
│   └── global/policies/
├── schemas/<artifact>/<major-version>/
├── prompts/<task>/<template-version>/
├── data/
│   ├── project-registry/
│   ├── asset-registry/
│   └── run-ledger/
├── output/                             # current compatibility outputs
├── src/
│   ├── core/
│   ├── knowledge/
│   ├── strategy/
│   ├── campaign/
│   ├── content/
│   ├── production/
│   ├── media/
│   ├── publishing/
│   ├── analytics/
│   ├── localization/
│   ├── integrations/
│   ├── orchestration/
│   └── providers/
└── tests/
    ├── contracts/
    ├── fixtures/
    ├── integration/
    └── end_to_end/
```

The current `output/` layout remains readable during transition. New multi-project work should write to `projects/<project_id>/`; a compatibility exporter may mirror selected latest artifacts into `output/`.

## 7. Data flow and module communication

Each stage follows the same protocol:

1. The Orchestrator reads the Run Ledger and resolves the next eligible stage.
2. It sends only artifact IDs, execution policy, and a stage-specific request.
3. The module loads inputs through the artifact repository, verifies hashes, and calls the Contract Validator.
4. The module performs its single responsibility. If AI is required, it submits a bounded request to the AI Provider Gateway.
5. The module writes a new immutable artifact or media file, registers it, and returns its artifact ID.
6. The Orchestrator validates the output, records the transition, and schedules downstream work.
7. Downstream modules receive references to the exact revisions used; “latest” is resolved only when a run is planned, never during execution.

Communication is therefore asynchronous-friendly and file/object-store compatible. An initial implementation may invoke modules in-process, but it must preserve the same request/result contracts so a future queue can replace direct invocation. Large binaries never travel inside JSON; JSON contains asset IDs, URIs, hashes, MIME types, and dimensions.

No agent-to-agent calls, shared mutable dictionaries, implicit global state, filename guessing, or reading another stage's private temporary files are allowed.

### Visual-production handoff rules

The visual chain has strict ownership and approval boundaries:

```text
content idea + production brief
  -> Creative Director: why it should feel and mean something
  -> Scene Planner: what story events exist and in what order
  -> Shot Planner: how each event is photographed or filmed
  -> Prompt Generator: how one approved shot is expressed in canonical generation language
  -> provider adapter: how that canonical prompt is serialized for one provider
  -> Image Generator: execution only
```

- Creative Direction is approved before Scene Planning begins.
- A Scene Plan references one Creative Direction and preserves its emotional and storytelling intent.
- Every Shot references exactly one Scene. Shots may be independently accepted, rejected, or revised without changing the Scene.
- Every canonical prompt references exactly one approved Shot. Prompt content must be derivable field-by-field from the Creative Direction, Scene, Shot, brief, and factual constraints.
- Every generation references exactly one canonical prompt revision and records the adapter version and serialized-payload hash.
- Creative-consistency review may reject a scene, shot, prompt, or image, but correction is routed to the module that owns the defective decision.
- Approval is granular: approving a Creative Direction does not approve its scenes; approving a Scene Plan does not approve its shots; approving a Shot does not approve its prompt or generated image.

## 8. OpenAI API boundary

The **AI Provider Gateway is the only module allowed to call the OpenAI API directly**. It owns API credentials, provider SDKs, model selection, structured-output enforcement, timeout/retry policy, token and cost limits, safety policy, request IDs, and provider telemetry.

Modules allowed to request AI work through the gateway are:

- Document Classification, only after deterministic methods fail.
- Knowledge Extraction and Knowledge Evaluation.
- Marketing Strategy Engine, Campaign Planner, and Content Planner.
- Creative Director, Scene Planner, Shot Planner, Prompt Generator, Image Generator, Asset Quality Control semantic checks, Caption Generator, Localization, Insight Engine, and future Video Generator.

They are gateway clients; they are not allowed to import an OpenAI SDK, read `OPENAI_API_KEY`, select an arbitrary model, or call the API directly.

The following modules must never call OpenAI or any generative AI API, directly or indirectly unless a separately named AI sub-check above is explicitly invoked through the gateway:

- Project Folder Management, PDF Reader, Markdown Writer, Knowledge Fusion deterministic merge, and storage modules.
- Project Registry, Asset Registry, Run Ledger, Contract Validator, and Orchestrator.
- Brand Composer deterministic rendering and export.
- Post Package Assembler, Approval Service, Publishing Scheduler, and Instagram Publisher.
- Analytics Collector, Performance Normalizer, CRM Adapter, credential stores, and compatibility exporters.
- Hashing, file management, image/video technical inspection, rights checks, and cleanup services.

Provider-specific image or video endpoints must also sit behind the gateway or a gateway-owned provider adapter. This preserves one auditable outbound AI boundary.

## 9. Error handling and recovery

### Error artifact

Every terminal stage failure writes a sanitized error artifact:

```json
{
  "error_id":"err_01J...",
  "run_id":"run_01J...",
  "stage":"image_generation",
  "attempt":3,
  "code":"PROVIDER_TIMEOUT",
  "category":"transient_external",
  "message":"Image provider did not complete before the deadline",
  "retryable":true,
  "input_artifact_ids":["art_prompt_7"],
  "provider_request_id":"req_...",
  "occurred_at":"2026-08-06T11:20:00Z",
  "details_redacted":true
}
```

### Categories and behavior

| Category | Examples | Behavior |
| --- | --- | --- |
| Validation | malformed JSON, incompatible schema, missing reference | Do not retry; mark stage failed and require producer fix/migration. |
| Source quality | unreadable PDF, empty Markdown, unresolved knowledge conflict | Mark blocked; request replacement source or human decision. |
| Transient external | timeout, rate limit, temporary platform outage | Exponential backoff with jitter, capped attempts, then dead-letter. |
| Permanent external | invalid credential, rejected media, revoked permission | Stop retries; require operator action. |
| Policy/safety | unsupported claim, rights failure, unsafe generation | Quarantine output; prohibit publishing; route to review/regeneration. |
| Technical media | corrupt image, wrong ratio, invalid codec | Retry deterministic transform or regenerate from the owning stage. |
| Concurrency | duplicate run, stale revision, conflicting approval | Reject stale write and reload current state. |

Retries must use idempotency keys. A retry produces a new attempt record but not duplicate logical publications. Partial multi-document extraction may resume per document. Partial media batches retain successful variants and retry only failed items. Stack traces remain in restricted logs; user-facing artifacts contain sanitized messages.

Publishing uses a circuit breaker and reconciliation job. If a publish call times out with unknown outcome, the Publisher checks the platform using the idempotency key before retrying.

## 10. Versioning and migrations

Five versions are tracked independently:

- `pipeline_version`: ordering and orchestration behavior.
- `module_version`: implementation behavior of a producer.
- `schema_version`: artifact payload contract, using semantic versioning.
- `prompt_template_version`: exact instruction/template used for AI work.
- `brand_kit_version`: exact logo, font, palette, and layout policy revision.

Visual production also records the schema and producer version independently for `creative_direction`, `scene_plan`, `shot_plan`, `canonical_prompt`, and each provider adapter. Splitting the pipeline is a backward-compatible pipeline extension, while removing cinematography fields from the former Creative Direction payload requires a new major Creative Direction schema.

Version policy:

- Patch: corrections with identical contract and intended semantics.
- Minor: additive backward-compatible fields or capabilities.
- Major: required field removal/rename, semantic change, or incompatible enumeration.
- Consumers declare accepted version ranges and fail closed on incompatible majors.
- Artifacts are never rewritten during migration. A migrator creates a new artifact with lineage to the old one.
- Runs pin exact versions at start. Deployments cannot silently change an active run.
- Model aliases are resolved to a concrete provider/model snapshot in provenance when the provider exposes one.
- Architectural changes require an Architecture Decision Record and an update to this document.

Versioning example for this refinement:

```json
{
  "pipeline_version": "1.1.0",
  "artifacts": {
    "creative_direction": {"schema_version":"2.0.0","module_version":"creative_director@2.0.0"},
    "scene_plan": {"schema_version":"1.0.0","module_version":"scene_planner@1.0.0"},
    "shot_plan": {"schema_version":"1.0.0","module_version":"shot_planner@1.0.0"},
    "canonical_prompt": {"schema_version":"1.0.0","module_version":"prompt_generator@2.0.0"}
  },
  "provider_adapter": {"name":"openai_images","version":"1.0.0"}
}
```

Backward compatibility is mandatory. Existing `creative_direction@1.x` artifacts remain readable and immutable. A compatibility adapter may split legacy production fields into a derived `scene_plan@1.0.0` and `shot_plan@1.0.0`, with lineage to the legacy artifact; it must not alter the original. Existing completed workflows and current output files continue unchanged. New runs use the refined contracts once their modules are implemented.

## 11. Asset management

An asset is any binary or reusable creative resource: source image, logo, font, floor plan, render, generated image, audio, video, caption track, template, or exported post.

Every asset record contains:

- identity: `asset_id`, project, revision, hash, MIME type, size, dimensions/duration;
- lifecycle state and parent/child lineage;
- origin: uploaded, extracted, generated, transformed, or imported;
- rights: owner, license, territory, channels, expiry, AI-reference permission, releases;
- creative metadata: dominant colors, orientation, subjects, locale, safe areas;
- generation provenance: prompt artifact, provider request, model, seed when available;
- approval and publication references;
- retention class and deletion eligibility.

Source assets are read-only. Reusable global assets require explicit project usage permission. Duplicate content hashes may share storage but retain separate logical asset records and rights. Assets with unknown or expired rights cannot enter generation references or publishing packages.

## 12. Image lifecycle

```text
source/reference
      -> prompt-linked generation request
      -> generated_raw
      -> quarantined (until checks finish)
      -> qc_rejected -----> regeneration request
      -> qc_approved
      -> branded derivative
      -> localized/cropped derivative
      -> package candidate
      -> human approved
      -> scheduled
      -> published snapshot
      -> archived
```

Rules:

- Raw generations are immutable and never branded in place.
- Each crop, resize, overlay, localization, or compression creates a child asset.
- Rejected assets remain available for audit but are excluded from selection and publishing.
- Approval applies to an exact asset revision, caption revision, locale, and placement.
- Published media is copied or pinned as a publication snapshot so later template changes cannot alter historical evidence.
- Working intermediates may expire by policy; source, approved, published, and provenance assets follow longer retention rules.
- A perceptual hash detects near-duplicate variants; a cryptographic hash verifies exact bytes.

## 13. Regeneration workflow

Regeneration is selective, lineage-aware, and never overwrites approved history.

1. A human rejection, QC failure, source update, or analytic insight creates a `regeneration_request` with a reason code and precise feedback.
2. The Regeneration Controller identifies the earliest owning stage:
   - factual error -> Knowledge Extraction/Fusion, then invalidate all factual descendants;
   - strategy mismatch -> Strategy, then downstream plans and creative work;
   - weak idea -> Content Planner;
   - wrong campaign concept, visual identity, emotional direction, storytelling direction, luxury level, realism level, audience perception, or artistic vision -> Creative Director;
   - wrong, missing, unnecessary, or poorly sequenced story event; wrong environment, subject, time, weather, mood, lighting direction, dependency, or reusable asset -> Scene Planner;
   - poor camera framing, shot coverage, shot type, camera height/angle, lens, composition, depth of field, camera motion, framing, focus/background relationship, negative space, aspect ratio, or platform suitability -> Shot Planner only;
   - poor or inaccurate prompt wording or provider-neutral translation, while the approved shot is correct -> Prompt Generator only;
   - low resolution, corrupt output, generation artifact, or poor image execution, while the approved prompt is correct -> Image Generator only;
   - generated content that correctly follows a defective prompt -> route to Prompt Generator, not Image Generator;
   - branding/layout issue -> Brand Composer;
   - copy issue -> Caption Generator or Localization;
   - platform packaging issue -> Post Package Assembler.
3. Upstream artifacts outside the affected scope are pinned and reused.
4. A new revision and run branch are created. Descendants are marked `superseded`, never deleted.
5. New outputs repeat validation, QC, and human approval.
6. If previously scheduled content changes, the schedule is canceled or replaced before approval can be transferred. Approval is not inherited automatically.

Regeneration budgets cap variants, provider cost, and attempts. Repeated identical failures escalate to a human with the complete sanitized lineage.

The controller invalidates only the affected node and its descendants. For example, a framing correction supersedes one Shot and its Prompt, generations, derivatives, and packages while preserving the Creative Direction, Scene Plan, and unaffected Shots. A wording correction preserves the Shot and supersedes only the Prompt and downstream assets. An image-quality retry preserves the exact Prompt and creates a new generation attempt. No downstream approval is inherited by regenerated artifacts.

## 14. Future video generation support

Video is an extension of the same brief/asset/package model, not a separate pipeline. Content ideas already identifying Reels or video formats use the same Creative Director, Scene Planner, and Shot Planner. Motion-capable Shots then route through the canonical Prompt Generator and a video provider adapter; Video Brief Builder adds timing, audio, narration, transition, and assembly requirements without redefining the creative concept, scene, or cinematography.

The video path adds scene graphs, shot duration, motion direction, transitions, voiceover, music rights, on-screen text, subtitle tracks, poster frames, codecs, frame rate, loudness, and safe-zone checks. Image assets may become references or keyframes. Each generated clip is a raw immutable asset; assembly creates derivatives.

The provider adapter must support asynchronous jobs, progress polling, cancellation, cost limits, moderation, and provider job reconciliation. Final video must pass technical QC, scene-to-brief alignment, temporal consistency, logo/text safe zones, audio rights, caption accuracy, and platform duration/size validation before approval.

## 15. Future Instagram publishing support

Publishing is deliberately separated from generation. The Instagram integration consists of Credential Vault references, Account Registry, Platform Capability Resolver, Publishing Scheduler, Instagram Publisher, and Publication Reconciler.

Before scheduling, the system validates account authorization, placement support, media ratios and sizes, caption/hashtag limits, locale, branded-content flags, and exact approvals. Tokens never appear in artifacts or logs. Publish operations use a stable idempotency key and retain the platform media ID, permalink, timestamps, exact package revision, and response hash.

The initial rollout should support dry-run export, then sandbox/test accounts, then supervised production publishing. Automatic publishing remains opt-in per account and project. Deletion or editing of a live Instagram post is a separate explicitly approved operation and is never inferred from local regeneration.

## 16. Future analytics support

Analytics is append-only: collectors store timestamped raw snapshots, normalizers calculate canonical metrics, and insights reference both the source snapshots and formula version. Metrics must not be compared across incompatible placements or windows without normalization.

Core measures are impressions, reach, engagements, engagement rate, saves, shares, video views and completion, profile visits, clicks, leads, qualified leads, and conversions. Campaign and creative dimensions include content pillar, audience, format, concept, CTA, locale, posting time, asset lineage, and prompt/template versions.

Insights may recommend a change or open a regeneration request, but cannot alter strategy, generate a replacement, change a schedule, or publish without the normal workflow and approval gate. Personally identifiable analytics data is minimized and retained according to consent and policy.

## 17. Future multi-language support

English is not assumed to be the only source or output language. Project metadata defines default language, source languages, requested locales, fallback locale, and right-to-left requirements.

Knowledge stores facts in canonical normalized fields plus original-language evidence excerpts. Translation must never turn unknown values into claims. Brand glossaries specify protected names, approved translations, forbidden terms, tone, numeral/currency/date conventions, and legal disclaimers.

Localization produces child artifacts per BCP 47 locale (for example `en`, `ar-IQ`, `ku-Arab-IQ`). It supports transcreation rather than literal translation where appropriate, but preserves claim references. RTL layouts are rendered and checked separately. Approval is per locale, and fallback text cannot be published unless the package explicitly allows it.

## 18. Future CRM integration

The CRM boundary is a provider-neutral adapter with mappings for contacts, leads, activities, campaigns, properties, and attribution. It receives only consented fields needed for the configured workflow.

Stable internal IDs map to external CRM IDs. Upserts use deduplication keys, field-level mapping versions, retries, and a dead-letter queue. Conflicts follow configured ownership rules; the adapter must not overwrite sales-owned data merely because marketing data changed. Campaign/post IDs and UTM parameters preserve attribution from publication to lead and conversion.

Inbound CRM events may update aggregate conversion analytics or lead status. They do not change canonical project knowledge. Webhooks are authenticated, replay-protected, logged, and processed idempotently.

## 19. Future multi-project management

Multi-project support is based on stable `workspace_id` and `project_id` namespaces. Every artifact, asset, run, approval, schedule, credential reference, analytic record, and CRM mapping must include both where applicable.

Isolation requirements:

- Paths and object-store keys are rooted by project ID.
- Database queries require workspace/project scope by default.
- Project assets cannot be referenced across projects without explicit shared-library permission.
- Runs pin project-specific knowledge, strategy, brand kit, language, accounts, budgets, and approvals.
- Per-project concurrency and spend quotas prevent one project from starving others.
- Archiving a project stops new work but preserves published lineage and retention obligations.
- Templates may be shared; project facts, credentials, approvals, leads, and unpublished media are not shared.

A portfolio dashboard may summarize states across projects, but commands operate on an explicit project selection. Display-name collisions are harmless because storage and identity use stable IDs.

## 20. Security, privacy, and operational controls

- Credentials live in environment-backed or managed secret storage and are referenced by opaque connection IDs.
- Logs and error artifacts redact tokens, personal data, and provider payloads not needed for audit.
- Roles separate project administration, creative editing, brand approval, legal approval, publishing, and analytics access.
- External calls use allow-listed providers, bounded payloads, timeouts, and audit records.
- Source and generated content are scanned according to organizational policy before publishing.
- Rights and consent checks fail closed.
- Backup and restore procedures cover registries, artifact metadata, approvals, and published evidence.
- Retention policies distinguish transient generations, rejected variants, active campaign assets, published records, analytics, and leads.

## 21. End-to-end definition of done

A campaign is complete only when:

1. All source documents and assets are registered and rights-cleared.
2. Fused knowledge passes evaluation or has a documented human override.
3. Strategy, campaign plan, content plan, and production briefs are versioned and valid.
4. Media and copy pass technical, factual, brand, platform, and localization checks.
5. The exact post package revisions receive all required approvals.
6. Publishing returns a reconciled platform receipt, or a dry-run export is explicitly accepted as the delivery target.
7. Publication and campaign attribution are registered.
8. Analytics collection is scheduled when supported.
9. Every output can be traced back through prompts, directions, plans, strategy, knowledge, and original documents.

This architecture lets a new developer follow one stable chain: documents become evidence, evidence becomes knowledge, knowledge becomes strategy and plans, plans become controlled creative assets and copy, approved packages become publications, and publication performance becomes traceable feedback for the next revision.
# Asset-first planning contract

The planning system is asset-first. It identifies authentic visual opportunities before creating campaigns or content. Every content item must be supported by approved project assets and factual source evidence. Asset scarcity, reuse, confidence, funnel purpose, and campaign memory are enforced deterministically.

AI may interpret strategy and supported wording. Python makes final decisions about IDs, asset selection, fact references, scores, usage limits, sequence, memory, graph structure, and enumeration validity. The Content Planner is still-image-first and contains no lens, camera movement, drone, video, or framing-coordinate instructions.
# Image Prompt Generator

The Image Prompt Generator converts validated source assets and planning artifacts into production-ready image-editing/composition prompts. It never asks a model to recreate the real-estate project from imagination. Authentic project imagery remains the visual source of truth. Python controls IDs, assets, hashes, dimensions, facts, quality scoring, and safety decisions; prompt language is deterministic and preservation-first.
# Deterministic Production, QA, and Review

The deterministic production workflow applies only validated non-generative operations to authentic source images. It preserves project geometry and content, performs automated QA, records complete provenance, and creates a local human-review gallery. No image-generation API is called.

High-fidelity extraction preserves embedded bytes and native formats in an immutable originals vault. Detail enhancement, platform resizing, and future branding remain separate, attributable stages.
## Platform strategy

Platform strategy is selected after marketing strategy and before content planning. Mirrored mode requires both destinations and semantic equivalence; optimized mode may choose either destination, shared creative, or platform-specific packaging from verified asset suitability. The decision never expands verified facts or authentic source images and participates only in downstream cache keys.
# Media-hosting stage

The `media-hosting` stage follows final branded package creation and precedes real Meta payload creation. Its cache identity is the local SHA-256 plus release/package/media identity, bucket, public base URL, and object-key policy version. It performs no image transformation and no Meta write. Uploaded objects use `projects/<project>/<release>/<platform>/<package>/<item>-<hash>.<ext>` and are retained (`r2_cleanup_policy: retain`).

## Source-grounded content quality v2

The source file is the maximum fact and visual boundary. Extraction reads every page in order and preserves page delimiters, tables, captions, and visual-heavy-page evidence for audit. Canonical identity contains only project name, developer, actual project type, and most specific supported location. Unknown identity or visual values are explicitly unavailable/unknown rather than inferred.

Visual intelligence v2 emits `visual_category`, confidence, visible subject, associated verified facts, marketing/overlay suitability, source document/page/asset, and category-specific geometry-preservation requirements. Downstream selection must match the content category; unsupported concepts are removed. Captions establish project/developer context, explain the visible category, select up to four relevant verified facts, and retain private fact/asset references. Creative and package QA measure project identification, semantic match, usefulness, grounding, duplication, readability/hierarchy, CTA clarity, and generic-language dominance.

Affected schema/module fingerprints are v2 for asset intelligence, captions, package building, and package QA. These invalidate changed content artifacts without touching Meta credentials, hosted objects, publishing receipts, queue/scheduling architecture, or idempotency state.
