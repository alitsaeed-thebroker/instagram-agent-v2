# Meta / Instagram Publishing

The Meta adapter publishes final packages to an Instagram professional account authenticated either directly with Instagram Login or through Facebook Login and a connected Facebook Page. It supports single-image feed posts and image carousels only. Stories, Reels, video, Facebook publishing, analytics, comments, and inbox automation are not implemented.

## Safety defaults

### Department 5 final-boundary and crash safeguards

Controlled and batch Meta publishing now share a current-input validation gate.
It checks canonical unit-plan relationships, media bytes, package identity,
current release, package QA/social review, provenance, and locked brand approval.
Stored preflight results alone cannot authorize a remote write. Due schedules
are evaluated by execution eligibility rather than the planning preflight's
future-schedule check.

All publishing entry points acquire the same repository-wide publishing lock,
then their project lock. An atomic SQLite reservation checks confirmed history
and unresolved intents before committing an account-bound publish intent.
This reservation precedes the first Meta write and survives generated queue
rollback or deletion. An unresolved intent blocks subsequent publishing until
reconciliation; it never becomes an automatic retry merely because a queue was
rebuilt. The current implementation conservatively serializes every configured
account in the repository, not just jobs within one project.

Remote writes save durable checkpoints before the call and after its response.
Child/parent container IDs and returned published media IDs are retained in
`state/publishing/publication-ledger.sqlite3`; tokens, URLs and captions are not
included in checkpoint details. Generated publication history is not trusted
as authority for resuming containers from a previous attempt.

Read-only reconciliation can use a saved media ID or a saved parent container
bound to the validated account. Only an explicit `PUBLISHED` container status
confirms publication; `FINISHED`, `ERROR`, `EXPIRED`, missing evidence and lookup
failures remain uncertain. A container-confirmed publication may have no final
media ID: the ledger preserves the known container without inventing an ID.
Dry-run reconciliation reports the result without changing publication truth.

Locks now use OS-managed file locks, which release automatically on process
death. Lock files intentionally remain on disk; their existence is not evidence
of an active owner. Do not delete a lock file to resolve an apparent overlap.
The SQLite and filesystem coordination is for one repository on one host; it
does not certify a distributed cloud deployment with independent state stores.

Local verification and remaining operational prerequisites are recorded in
`output/verification/department5/POST_FIX_VERIFICATION.md`.

`input/publishing/meta-config.json` ships with `enabled: false` and `allow_immediate_publish: false`. Normal pipeline runs and `--publish-dry-run` never invoke the Meta adapter. Real execution requires one of:

```powershell
python app.py --project "<project>" --publish-meta
python app.py --project "<project>" --stage meta-platform-adapter
```

When a future local schedule exists, the adapter processes it only when due. An unscheduled item can publish immediately only when `allow_immediate_publish` is explicitly enabled.

## Account requirements

- Instagram Login: `META_INSTAGRAM_ACCOUNT_ID`, an Instagram Login token, and the configured `instagram_business_basic` and `instagram_business_content_publish` permissions. No Facebook Page is required.
- Facebook Login: a Facebook Page accessible by the token, an Instagram professional account connected to it, and the configured `instagram_basic`, `instagram_content_publish`, `pages_show_list`, and `pages_read_engagement` permissions.
- A token and application setup suitable for the configured Graph API version.

The API version is configured once in `meta-config.json` and recorded in real receipts. Review Meta’s current migration guidance before changing it.

## Environment variables

Copy `.env.example` to a local `.env` and configure values there. Never put tokens in JSON, documentation, logs, or source control.

```dotenv
META_ACCESS_TOKEN=
META_APP_ID=
META_APP_SECRET=
META_FACEBOOK_PAGE_ID=
META_INSTAGRAM_ACCOUNT_ID=
```

When `META_FACEBOOK_PAGE_ID` is set, the adapter uses Facebook Login and resolves the Page's `instagram_business_account`. Otherwise, when `META_INSTAGRAM_ACCOUNT_ID` is set, it uses Instagram Login directly. Instagram Login confirms `instagram_business_basic` through read-only account access and confirms `instagram_business_content_publish` through a read-only `content_publishing_limit` capability request on `graph.instagram.com`. It never depends on either Facebook or Instagram `debug_token`. A transient capability lookup failure does not erase successful account access. The access token is required for credential validation.

The API hosts are mode-specific: Facebook Login uses `graph.facebook.com`; Instagram Login uses `graph.instagram.com`. Required permission lists are versioned/configurable in `meta-config.json`.

Check readiness without exposing secrets:

```powershell
python app.py --meta-status
```

## Autonomous Windows worker

The repository-owned task `InstagramAgent-PublishingWorker` runs at user logon
and repeats every 15 minutes. Each invocation is short-lived and asks the
canonical eligibility engine for zero or one item. Missed intervals are not
queued, overlapping instances are ignored, and the application lock remains a
second concurrency barrier. The task runs as the current interactive user at
least privilege and uses absolute Python, application, and working-directory
paths. Secrets continue to load from the normal runtime environment and never
appear in the task definition.

```powershell
# Inspect the exact non-secret definition without installing
python app.py --install-publishing-worker --dry-run

# Install/update, inspect, pause, resume, and uninstall
python app.py --install-publishing-worker
python app.py --publishing-worker-status
python app.py --pause-publishing-worker
python app.py --resume-publishing-worker
python app.py --uninstall-publishing-worker

# Validate a complete local cycle with no state mutation or Meta writes
python app.py --publishing-worker --dry-run

# Resolve quarantined remote outcomes separately
python app.py --project "<project>" --publishing-reconcile --reconcile-dry-run
```

After installation, status should show a next-run time and the absolute command.
For a safe launch check, pause the worker, run the task from Task Scheduler, and
verify `state/publishing/worker-status.json`; then resume. An actual reboot test
is manual: reboot while paused, confirm the task remains installed and invokes
the worker, then resume only after status and ledger health pass.

If the ledger is unavailable or a publication is uncertain, keep the worker
paused and use ledger repair/reconciliation. If credentials expire, restore
them in the existing `.env` and confirm `--meta-status`. Scheduler or network
failures end that invocation; the next scheduled check performs one normal
cycle and never catches up missed slots.

Safe account metadata is written to `output/publishing/meta-account-status.json`.

## Public media URLs

Meta must fetch publication media over the public internet. A local path such as `C:\...` is never considered accessible. Every package image or carousel slide must provide `public_media_url`, or a package-level mapping keyed by `branded_item_id`.

URLs must:

- use HTTPS;
- be publicly reachable without authentication;
- return an image media type;
- refer to the intended final branded image.

The current `external_url` media-hosting mode validates supplied URLs but never uploads images. No third-party hosting service is selected automatically. Missing URLs produce `blocked_missing_public_media_url` before any Meta publishing request.

## Publication and idempotency

The adapter uses the exact packaged caption and optionally appends the exact packaged hashtags. It does not regenerate copy. Carousel children are created in packaged slide order, then attached to one parent container. Container readiness is checked before publication, and the published media is queried for remote status when available.

Per-image alt text is retained in the publication payload and manifest. The current adapter does not claim endpoint support for sending it and records that limitation as a receipt warning.

Before any real request, the adapter checks `real_receipts` for the deterministic idempotency key. A successful existing receipt prevents new containers from being created. Partial carousel container IDs are retained in publication history so safe remote state can be reused on retry.

Retryable errors are limited to rate limits, temporary transport failures, and transient platform errors. Invalid credentials, permissions, packages, accounts, and media URLs are permanent blockers. Real receipts contain remote IDs and `dry_run: false`; mock receipts remain intact and separate.
## Independent Meta readiness

`--meta-status` reports Instagram and Facebook independently and never prints secrets. Authentication mode is explicit when configured. A `both` request creates per-platform idempotency keys and receipts; one platform's success is never rolled back when the other fails, so an aggregate may be partial success. The default policy permits independent publication.
# Cloudflare R2 URLs

In `cloudflare_r2` mode, run the media-hosting stage before real publishing. Meta payload preparation resolves each package and branded item against `output/publishing/media-hosting/<project>-r2-media.json`, requires matching release identity and local SHA-256, and rechecks public HTTPS image accessibility. There is no fallback to a local path or manually supplied URL. A public `r2.dev` hostname is suitable for development but a custom domain is recommended for production. R2 access keys, secret keys, Meta tokens, and the Meta App Secret must never appear in logs or committed configuration.

## Controlled single-item publishing

Use `--list-publishable` to obtain an explicit queue item ID. Running `--publish-one QUEUE_ID` performs a read-only preview with zero Meta writes. A real write additionally requires `--confirm-real-publish`; the override applies only to that selected Instagram item and does not change global `allow_immediate_publish`. `--publish-one-package PACKAGE_ID` is accepted only when it maps to exactly one active platform job. Successful real receipts prevent duplicate publication, while mock receipts do not. Meta POST attempts are recorded without credentials in `output/publishing/live-write-audit.json`.


## Mandatory project introduction sequence
Department 3 orders the approved plan with project overview first and project site plan second. Community/lifestyle and unit types/layouts are preferred next; later topics may vary. Department 5 requires durable confirmed receipts for the first two roles in order before any later content can publish. Priorities, schedules, manual controlled publication, and batch publishing cannot bypass these prerequisites. If either required item is missing or fails validation, publishing waits rather than skipping it. A location map or unit layout cannot substitute for the project site plan.

Sequence contracts travel in immutable packages and queue jobs. The durable publish intent stores each contract in ledger metadata atomically, so confirmations, restarts and output rollback retain the sequence evidence. Old jobs without contracts fail the final gate; historical receipts without classified roles require evidence-based review. They are never assumed to be overviews and history is never reset to manufacture a new first post.
