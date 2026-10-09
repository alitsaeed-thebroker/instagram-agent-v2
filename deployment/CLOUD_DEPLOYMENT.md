# Cloud deployment preparation

Status: prepared, not deployed or enabled.

Run a single container on an always-on Linux host with a persistent /data volume. Never run a second live publisher or the local automatic publication automation during cutover. Preserve the live SQLite ledger with an SQLite backup operation and retain all receipt history. Do not copy a database with active WAL writes using a plain file copy.

Migration must copy the exact validated production artifacts and approved inputs and rewrite Windows absolute artifact paths into /data paths. Recompute signed contracts and lineage via normal production stages after relocation; do not patch hashes to bypass gates. The next technical site plan has not yet been prepared or certified. Schedule only fully verified packages. The published overview must never be rescheduled.

Store credentials outside the source checkout in /etc/instagram-agent/credentials.env with restricted permissions. They are excluded from the container build. Install licensed fonts if needed for rerendering; Segoe UI is not available in this Linux image. Publishing existing validated renders does not require rerendering.

Before activation: validate the migrated live ledger, account, hosted image hashes, approved campaign, dry run and exact due queue entries. Keep AGENT_LIVE_ENABLED=false until migration is certified; then enable the existing worker control as well as the cloud flag. The finite schedule permits October 9, 10, 11 at 09:00 Asia/Baghdad, with a ten-minute start window; it does not backfill missed days. Durable ledger eligibility remains authoritative against duplicates and uncertainty. After October 11, remove the finite job rather than extending it without authorization.

Deployment still requires a chosen host, connection access, and preparation of the next three verified posts.
