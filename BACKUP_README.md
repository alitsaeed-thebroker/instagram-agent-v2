# Instagram-agent V2 code backup

Source: `C:\Users\alits\instagram-agent V2`  
Snapshot date: **10 October 2026 (Asia/Baghdad)**  
Intended destination: **private** `alitsaeed-thebroker/instagram-agent-v2`  
Branch: `backup/2026-10-10`

This snapshot records the current files, rather than an older implementation.
The source directory had no Git metadata or history when inspected. A fresh
backup history avoids importing unrelated repository history. Remote completion
must be established by a verified push and matching remote commit; this document
alone is not evidence that a GitHub backup exists.

## Coverage

Included: current application entry points and `src/`, tests and deterministic
test fixtures, `requirements.txt`, architecture and department contract documents,
implementation certification documentation/manifests, audit and maintenance
scripts, Docker/deployment source, Cloudflare source/tests/package lockfiles,
sanitized `.env.example` and inert deployment templates. Historic certification
results and manifest hashes are retained as documentation, not fresh test results.
`BACKUP_MANIFEST.json` records SHA-256 hashes of the selected snapshot files;
it excludes itself to avoid a recursive checksum.

Excluded: real `.env` files, credentials and authentication material, private keys,
Cloudflare `.private-migration/` and signed jobs, actual `wrangler.jsonc` and
`compose.yaml`, the operational Cloudflare README, installed dependencies,
virtual environments, caches/build previews, old `.bak`/patch payload copies,
debug reports, `input/` contents, brand assets in `assets/`, `prompts/` contents,
`data/` contents (including the curated creative-intelligence library), `output/`,
`state/`, databases/WAL files, publication receipts, `archive/`, `artifacts/`, and
local `.backup-private/` tooling/reports. Empty `.gitkeep` placeholders may remain.
The originals remain local and intact; ignore rules do not encrypt or back them up.

This is a **code/configuration backup, not a complete operational disaster-recovery
backup**. Restore private developer/property documents, approved imagery, brand
configuration/logos/templates/fonts, project prompt inputs, curated data/libraries,
credentials, operational databases, signed jobs, approval/cancellation records,
receipts and hosted Cloudflare/R2/Durable Object state separately from a trusted,
access-controlled backup. A code snapshot cannot establish live deployment state
or reconstruct safe publication history. Test baselines contain references/hashes
whose private media bytes may need separate restoration.

## Restore code without enabling publication

After the private remote backup has been verified, authenticate Git for the owner
account and clone the snapshot:

```powershell
git clone --branch backup/2026-10-10 https://github.com/alitsaeed-thebroker/instagram-agent-v2.git instagram-agent-v2-restore
Set-Location instagram-agent-v2-restore
git log -1 --format=%H
git status --short
```

Compare the commit with the verified backup report. Validate file hashes using
`BACKUP_MANIFEST.json` before using the restored code. Dependency declarations are
included; installed Python/Node packages and runtimes are not. Install dependencies
only in an isolated environment after reviewing the project documentation.

Cloning is the end of code restoration. **Do not run the agent, publisher,
deployment commands, compose services, Windows scheduler installers, or schedule
reconstruction scripts.** Do not enable GitHub Actions that deploy or publish.
The example deployment files keep live publishing disabled, publication dates
empty, cron triggers empty, and automatic service restarts disabled. Do not copy
old schedules or activate credentials during restoration.

Before any separately authorized operational recovery, reconcile authoritative
remote publication receipts, uncertain intents, cancellations, approved assets,
ledger integrity and current hosted state. Restoring code must never automatically
enable publishing or recreate schedules. Historical runbooks in other documents
are descriptive and do not authorize execution.
