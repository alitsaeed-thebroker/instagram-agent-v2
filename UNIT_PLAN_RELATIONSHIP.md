# Canonical unit–plan verification

Unit plans can no longer inherit VERIFIED from model confidence, visible-label
transcriptions, attached source metadata, or a saved eligibility flag.

## Verification contract

`src/unit_plan_relationship.py` recomputes a canonical relationship from source
bytes. Its object contains schema version, authority, deterministic relationship
ID, exact provenance, typed unit identity, per-field source evidence, status,
and review reasons. The relationship ID is a content digest, not a signature.
Consumers revalidate the source; they do not trust the digest alone.

The standard labelled-page proof is deliberately narrow:

- The exact complete PDF page rendered at 300 dpi by the extraction pipeline.
- SHA-256 checks of both the original PDF and the complete plan image.
- A fresh page render must equal the selected image bytes.
- Exactly one standalone UNIT PLAN heading; no floor/site/master-plan scope.
- Exactly one explicit source label for each required field: Project, Unit Type,
  Bedrooms, Area sqm. At least one of Floor, Tower, Building, or Context is
  required. Context is an explicit source value, not an inferred default.
- Candidate metadata must agree with the PDF. Repeated labels are ambiguous
  even when their values agree. Existing ambiguous/conflicted/probable states
  remain blocked.
- Optional asserted facts also need their corresponding explicit source labels.
  Supported labels are declared in LABELS in the verifier. Dimensions use a
  semicolon-separated list if asserted as structured facts.

Only successful proof plus explicit COMPLETE and READABLE plan checks makes
the inventory record marketing eligible. Missing/ambiguous/conflicting proof
produces REVIEW_REQUIRED; production redirects the item. A source record can
retain UNVERIFIED/AMBIGUOUS/CONFLICTED as its diagnostic relationship status.

## Consumer behavior

- Extraction persists the original PDF path alongside its hash.
- Asset intelligence treats model output as candidate metadata; it calls the
  verifier before publishing eligibility, including cached analysis.
- Plan inventory schema is 2.0.0 and stores unit_plan_relationship.
- Creative intelligence requires canonical proof and limits layout asset
  candidates to verified records.
- Department 4 revalidates proof, project, asset ID, and actual image bytes.
  Nested provenance no longer overwrites an inventory record during indexing.
- Package/publishing plan checks revalidate canonical proof even without
  numeric claims. Rendering validates displayed unit claims and requires FIT.
  Overlapping branding/text, out-of-canvas placement, cropping, rotation,
  perspective transformations, and generative edits are rejected.
- The existing compositor uses proportional containment, preserving the full
  source plan rather than redrawing its geometry or dimensions.

## Changed files

Production:

- src/unit_plan_relationship.py
- src/plan_integrity.py
- src/visual_assets/extraction.py
- src/ai/agents/asset_intelligence_agent.py
- src/creative/visual_art_director.py
- src/creative/visual_direction.py
- src/creative_intelligence/engine.py

Tests:

- tests/unit_plan_fixtures.py
- tests/test_unit_plan_relationship.py
- tests/test_plan_integrity.py
- tests/test_unit_plan_phase1.py
- tests/test_visual_art_director.py
- tests/test_real_estate_creative_intelligence.py

The fixtures generate actual PDFs and complete image renders; successful
verification is not mocked. Tests cover source proof, metadata conflicts,
ambiguous/missing labels, missing provenance, legacy LLM-only rejection,
non-unit substitution, altered proof/evidence/hashes, production image
substitution, geometry/label protection, and a valid Department 4 handoff.

Validation: 189 tests passed across test_unit_plan_relationship,
test_plan_integrity, test_unit_plan_phase1, test_asset_intelligence_agent,
test_visual_art_director, test_department4_production_contract,
test_production_workflow, test_post_package, test_multiplatform_integrity,
test_publishing_eligibility, test_phase26_source_quality,
test_real_estate_creative_intelligence, and test_brand_composer.
The run used Python 3.14.6 with a repository-local temporary directory because
the default sandbox temporary directory denied fixture writes. The final
test process exited successfully. Existing Pillow deprecation warnings remain.

## Migration and remaining limits

Existing inventories must be regenerated from original PDFs to capture the
new provenance. No automatic grandfathering of old VERIFIED records occurs.
Source PDFs must remain available to consumers. A rendering-library change
that changes image bytes will safely require re-extraction.

Scanned/OCR-only sources, arbitrary brochure typography, multiple layouts on
one page, cross-document joins, and arbitrary cross-page relationships are
not auto-verified. A separately validated structural catalogue adapter can
prove a specific cross-page relationship; changing a status flag is not a
review override.
This layer proves the source's explicit relationship, not the correctness of
the developer's underlying architectural drawing.

Before the catalogue migration, a read-only recheck of the Beverly Hills inventory found one unit
plan and zero eligible plans: missing provenance, incomplete page provenance,
missing canonical render DPI, unsupported unit-type evidence, and INCOMPLETE
plan status. The saved inventory was not rewritten by that check.

The supplied V2 directory has no Git metadata, so its base commit could not be
confirmed and no commit or push was performed.

## Beverly Hills source certification

The source-specific adapter is implemented in src/unit_plan_catalogue.py and
integrated into extraction, asset intelligence, and canonical verification.
It separates complete printed pages at the PDF spread's binding line. It
preserves each whole technical drawing, legend, area table, and printed labels;
it never crops a drawing or infers new geometry.

The adapter proves the project from the same source document's explicit
standalone-villa statement, finds unique villa-type sections, and requires
contiguous ground/first floors with identical explicit area tables. Numbered
room legends must be contiguous and must match the numbers in the actual
plan drawing. Bedroom count is a deterministic sum of explicitly labelled
BEDROOM/BED ROOM entries; MAID ROOM is excluded.

The canonical object records every supporting floor page and region, source
room legend, area table, protected text position/font size, complete required
asset set, and a unit_scope_id shared by that villa's floors. A multi-slide
caption can bind those floors only when their complete canonical set is
present. A partial set fails the package and publishing gates.

Automatic VERIFIED relationships:

| Villa | Bedrooms from room legends | Built-up area | PDF pages |
| --- | ---: | ---: | --- |
| Type D | 5 | 396.5 sqm | 34, 35 |
| Type E | 4 | 328 sqm | 39, 40 |

The large 345 sqm and 260 sqm type-title figures remain classified as
UNSPECIFIED_IN_SOURCE. They are not silently treated as built-up or plot areas.

Types A and B require clarification of Penthouse area versus Second Floor
headings and are outside the certified two-floor adapter. Type C additionally
has conflicting stated floor totals (270 + 246.5 + 65 versus built-up 328).
All three remain REVIEW_REQUIRED across planning, processor validation,
Department 4, package validation, and publishing preflight.

The isolated source certification recovered all 45 complete PDF page renders
and 118 authentic assets including 13 complete printed plan leaves, with zero
hash failures. It rendered four real 1080x1350 slides for D/E through the
VisualArtDirector and BrandComposer, checked source geometry pixel for pixel
against the prescribed uniform resizing, and checked source text size at the
final output scale. All original labels, room areas, and plan numbers are
retained. Both complete packages pass the publishing preflight's eight checks.
The source does not supply room length/width dimensions; none were invented.

The certification reuses a hash-verified, approved Domus brand configuration
and logo from the existing sibling instagram-agent project, snapshots them
inside the isolated certification directory, and records their provenance.
No live publication jobs or external requests are made.

The canonical plan inventory, authentic-source manifest, asset intelligence,
and semantic visual inventory are migrated only after successful source
certification. Previous inventories are retained under the certification
directory. Existing content plans and live queues require their normal
regeneration/revalidation before using the new unit assets.

Reproduce with tools/certify_beverly_unit_plans.py and an explicit approved
--brand-root. --reuse-extraction is permitted only after current document and
all source asset hashes pass. Full evidence is stored at
output/verification/unit-plans/Beverly-Hills/certification-report.json.

Additional regression coverage includes test_unit_plan_catalogue and
test_controlled_publish. Controlled publishing now checks canonical plan
integrity again before credential checks or external calls; cached queue
readiness cannot bypass it. The unbranded processor also verifies unit
relationships and prevents enhanced images replacing technical sources.
