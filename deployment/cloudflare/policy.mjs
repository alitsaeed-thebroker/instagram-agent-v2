export function scheduledDay(timestamp, allowedDates, allowedHours=[6]) {
  if (!Number.isFinite(timestamp)) return null;
  const date = new Date(timestamp);
  if (!Number.isFinite(date.getTime())) return null;
  const local = new Date(date.getTime() + 3 * 60 * 60 * 1000);
  const day = local.toISOString().slice(0, 10);
  return String(allowedDates || "").split(",").map(x=>x.trim()).includes(day) && allowedHours.includes(date.getUTCHours()) && date.getUTCMinutes() === 0 && date.getUTCSeconds() === 0 && date.getUTCMilliseconds() === 0 ? day : null;
}
export function cloudGate(enabled, migrated, unresolved) {
  if (enabled !== "true") return "PAUSED";
  if (!migrated) return "LEDGER_MIGRATION_REQUIRED";
  if (unresolved) return "RECONCILIATION_REQUIRED";
  return "PUBLISHER_PORT_CERTIFICATION_REQUIRED";
}

export function validateSnapshot(snapshot, account) {
  if (snapshot.schema_version !== "cloud-ledger-import-v1" || snapshot.account_id !== account || !Array.isArray(snapshot.records) || !snapshot.records.length) throw new Error("INVALID_LEDGER_SNAPSHOT");
  const ids = snapshot.records.map(r => r.publication_identity);
  if (new Set(ids).size !== ids.length || ids.some(x => !x)) throw new Error("DUPLICATE_LEDGER_IDENTITIES");
  for (const r of snapshot.records) {
    if (r.account_id !== account || !["CONFIRMED_PUBLISHED","PUBLISHING_UNCERTAIN","CONFIRMED_NOT_PUBLISHED","RECONCILIATION_REQUIRED"].includes(r.state)) throw new Error("INVALID_LEDGER_RECORD");
    if (r.state === "CONFIRMED_PUBLISHED" && (!r.remote_media_id || !r.receipt_id)) throw new Error("MISSING_CONFIRMED_RECEIPT");
  }
  return true;
}

export function selectCampaign(job,primary,additional=[]) {
 const allowed=[primary,...additional].filter(c=>c?.project_id===job.project_id && c?.campaign_id===job.campaign_id);
 if(allowed.length!==1 || !Array.isArray(allowed[0].prior_publications))throw new Error("WRONG_PUBLICATION_SCOPE");
 return allowed[0];
}
export function jobMatchesSlot(job,timestamp) {
 const when=Date.parse(job.scheduled_at);return Number.isFinite(when) && when===timestamp;
}
