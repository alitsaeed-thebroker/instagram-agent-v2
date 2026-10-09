import { DurableObject } from "cloudflare:workers";
import { CloudPublisher, verifyEnvelope, hash } from "./publisher.mjs";
import { scheduledDay, validateSnapshot, selectCampaign, jobMatchesSlot } from "./policy.mjs";

// Never persist exception text, captions, envelopes, URLs or credentials.
const SAFE_REASONS = new Set([
  "LEDGER_IMPORT_CONFLICT", "LEDGER_SNAPSHOT_MISSING", "LEDGER_SNAPSHOT_HASH_MISMATCH",
  "INVALID_LEDGER_SNAPSHOT", "DUPLICATE_LEDGER_IDENTITIES", "INVALID_LEDGER_RECORD", "MISSING_CONFIRMED_RECEIPT",
  "RECONCILIATION_REQUIRED", "UNSIGNED_PACKAGE", "PACKAGE_SIGNATURE_INVALID", "WRONG_PUBLICATION_SCOPE",
  "UNCERTIFIED_OR_EXPIRED_PACKAGE", "INVALID_MEDIA_COUNT", "INVALID_OR_DUPLICATE_MEDIA", "INVALID_CAPTION",
  "ALREADY_RESERVED_OR_PUBLISHED", "GLOBAL_SPACING_BLOCKED", "DAILY_POST_ALREADY_PUBLISHED",
  "INVALID_APPROVED_SEQUENCE", "OVERVIEW_REQUIRED", "SITE_PLAN_REQUIRED", "INVALID_CAMPAIGN_SEQUENCE",
  "OVERVIEW_SOURCE_NOT_APPROVED", "SITE_PLAN_NOT_VERIFIED", "UNIT_PLAN_NOT_VERIFIED",
  "HOSTED_MEDIA_UNAVAILABLE", "HOSTED_MEDIA_CHANGED", "ACCOUNT_MISMATCH", "CONCURRENT_PUBLICATION_BLOCKED",
  "PACKAGE_PAYLOAD_INVALID", "VERIFIED_JOB_MISSING", "CAMPAIGN_PAUSED"
]);
function safeReason(error) {
  const message = error?.message;
  if (SAFE_REASONS.has(message)) return message;
  if (/^META_REQUEST_FAILED:[0-9]{1,5}$/.test(message || "")) return message;
  return "SAFE_DIAGNOSTIC_UNAVAILABLE";
}
async function previewProof(job) {
  return {signature_verified:true,publication_identity:job.publication_identity,project_id:job.project_id,campaign_id:job.campaign_id,scheduled_at:job.scheduled_at,package_sha256:job.certification.package_hash,caption_sha256:await hash(new TextEncoder().encode(job.caption)),ordered_media_sha256:job.media.map(m=>m.sha256),ordered_source_asset_ids:job.media.map(m=>m.source_asset_id)};
}

export class AccountState extends DurableObject {
  async importLedger() {
    const existing = await this.ctx.storage.get("migration-sha256");
    if (existing) {
      if (existing !== this.env.LEDGER_SNAPSHOT_SHA256) throw new Error("LEDGER_IMPORT_CONFLICT");
      return;
    }
    const object = await this.env.PRIVATE_PACKAGES.get("migration/live-ledger.json");
    if (!object) throw new Error("LEDGER_SNAPSHOT_MISSING");
    const bytes = await object.arrayBuffer();
    const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(x => x.toString(16).padStart(2,"0")).join("");
    if (!this.env.LEDGER_SNAPSHOT_SHA256 || digest !== this.env.LEDGER_SNAPSHOT_SHA256) throw new Error("LEDGER_SNAPSHOT_HASH_MISMATCH");
    const snapshot = JSON.parse(new TextDecoder().decode(bytes));
    validateSnapshot(snapshot,this.env.ACCOUNT_ID);
    await this.ctx.storage.transaction(async txn => {
      if (await txn.get("migration-sha256")) return;
      for (const record of snapshot.records) await txn.put("publication:"+record.publication_identity, record);
      await txn.put("campaign", snapshot.campaign);
      await txn.put("unresolved-intent", snapshot.records.some(r => ["RECONCILIATION_REQUIRED","PUBLISHING_UNCERTAIN"].includes(r.state)));
      await txn.put("imported-count", snapshot.records.length);
      await txn.put("migration-sha256", digest);
      await txn.put("migration-certified", true);
    });
  }
  async health() {
    await this.importLedger();
    const records=[...(await this.ctx.storage.list({prefix:"publication:"})).values()];
    const last=await this.ctx.storage.get("last-schedule-check");
    return {service:"instagram-agent-publisher",stage:this.env.LIVE_ENABLED==="true"?"scheduled-publisher-active":"publisher-implemented-paused",live_publishing:this.env.LIVE_ENABLED==="true",ledger_records:records.length,confirmed_publications:records.filter(r=>r.state==="CONFIRMED_PUBLISHED").length,unresolved_intent:!!(await this.ctx.storage.get("unresolved-intent")),ledger_integrity_verified:true,scheduler_status:last?.status || "NO_EXECUTION_EVIDENCE",last_schedule_check:last || null,last_schedule_failure:await this.ctx.storage.get("last-schedule-failure") || null,paused_campaigns:await this.pausedCampaigns(),scheduler_certified:false};
  }
  async pausedCampaigns() {
    const configured=JSON.parse(this.env.PAUSED_CAMPAIGNS || "[]");
    const durable=[...(await this.ctx.storage.list({prefix:"campaign-pause:"})).values()];
    return [...configured,...durable];
  }
  async campaignPaused(job) {
    return (await this.pausedCampaigns()).some(p=>p.project_id===job.project_id && p.campaign_id===job.campaign_id);
  }
  async pauseCampaign(project_id,campaign_id) {
    // Only registered scopes can be changed; no global pause and no resume side effect.
    await this.importLedger();
    selectCampaign({project_id,campaign_id},await this.ctx.storage.get("campaign"),JSON.parse(this.env.ADDITIONAL_CAMPAIGNS||"[]"));
    const pause={project_id,campaign_id,status:"PAUSED",reason:"USER_REQUESTED_RECOVERY",paused_at:new Date().toISOString()};
    await this.ctx.storage.put("campaign-pause:"+JSON.stringify([project_id,campaign_id]),pause);
    return {...pause,meta_writes:0};
  }
  async recordSchedule(value) {
    // A bounded diagnostic journal is separate from immutable publication history.
    await this.ctx.storage.transaction(async txn=>{
      const sequence=(await txn.get("schedule-check-sequence") || 0)+1;
      const key="schedule-check:"+String(sequence).padStart(12,"0");
      await txn.put(key,value);
      await txn.put("schedule-check-sequence",sequence);
      await txn.put("last-schedule-check",value);
      if(value.status==="FAILED")await txn.put("last-schedule-failure",value);
      if(sequence>200)await txn.delete("schedule-check:"+String(sequence-200).padStart(12,"0"));
    });
  }
  async scheduleStatus() {
    return {checks:[...(await this.ctx.storage.list({prefix:"schedule-check:"})).values()],paused_campaigns:await this.pausedCampaigns(),meta_writes:0};
  }
  async scheduledCheck(scheduledTime,cron) {
    const check={scheduled_time:Number.isFinite(scheduledTime)?scheduledTime:null,cron:typeof cron==="string" && /^[0-9*, /-]{1,80}$/.test(cron)?cron:null,checked_at:new Date().toISOString(),status:"STARTED"};
    await this.recordSchedule(check); // Failure to persist STARTED prevents all publication writes.
    try {
      const hours=String(this.env.SCHEDULED_HOURS_UTC || "6,9,10,19").split(",").map(Number);
      const day=scheduledDay(scheduledTime,this.env.PUBLISH_DATES,hours);
      const result=day?await this.inspect(day,false,scheduledTime,check):{status:"DATE_OR_TIME_NOT_AUTHORIZED",meta_writes:0};
      const finished={...check,status:result.status,scheduled_day:day,reason:result.reason || null,meta_writes:result.meta_writes ?? null};
      await this.recordSchedule(finished);
      return finished;
    } catch(error) {
      const failed={...check,status:"FAILED",reason:safeReason(error),meta_writes:null};
      await this.recordSchedule(failed);
      // Safe failure remains visible in both durable diagnostics and invocation outcome.
      throw new Error(failed.reason);
    }
  }
  async inspect(day, dryRun=false, scheduledTime=null,check=null) {
    const phase=async name=>{if(check){check.phase=name;await this.recordSchedule({...check});}};
    await phase("LEDGER_IMPORT");
    await this.importLedger();
    if (!dryRun && this.env.LIVE_ENABLED!=="true")return {status:"PAUSED",meta_writes:0};
    if(await this.ctx.storage.get("unresolved-intent"))return {status:"RECONCILIATION_REQUIRED",meta_writes:0};
    await phase("JOB_RETRIEVAL");
    const object=await this.env.PRIVATE_PACKAGES.get("jobs/"+day+".json");
    if(!object)return {status:"NO_VERIFIED_JOB",scheduled_day:day,meta_writes:0};
    await phase("SIGNATURE_VALIDATION");
    const job=await verifyEnvelope(await object.json(),this.env.PACKAGE_SIGNING_KEY);
    await phase("EXACT_SLOT_MATCH");
    if(!dryRun && !jobMatchesSlot(job,scheduledTime))return {status:"NOT_THIS_TIME_SLOT",meta_writes:0};
    await phase("CAMPAIGN_SCOPE_AND_PAUSE");
    const campaign=selectCampaign(job,await this.ctx.storage.get("campaign"),JSON.parse(this.env.ADDITIONAL_CAMPAIGNS||"[]"));
    if(!dryRun && await this.campaignPaused(job))return {status:"CAMPAIGN_PAUSED",meta_writes:0};
    await phase("PUBLISHER_GATES_AND_INTENT");
    const publisher=new CloudPublisher(this.ctx.storage,this.env);
    const result=await publisher.run(job,day,campaign,dryRun);
    return dryRun?{...result,validated_job:await previewProof(job)}:result;
  }
  async publicationStatus() {
    await this.importLedger();
    const records=[...(await this.ctx.storage.list({prefix:"publication:"})).values()];
    return {records:records.map(r=>({publication_identity:r.publication_identity,state:r.state,project_id:r.project_id,role:r.project_sequence?.role,published_at:r.publication_timestamp,receipt_id:r.receipt_id,media_id:r.remote_media_id||r.published_media_id,permalink:r.permalink})),unresolved_intent:!!(await this.ctx.storage.get("unresolved-intent")),meta_writes:0};
  }
  async previewSchedule() {
    await this.importLedger();
    if(await this.ctx.storage.get("unresolved-intent"))throw new Error("RECONCILIATION_REQUIRED");
    const records=await this.ctx.storage.list({prefix:"publication:"});
    const campaign=await this.ctx.storage.get("campaign");
    const shadow={list:async()=>new Map(records),get:async()=>false};
    const publisher=new CloudPublisher(shadow,this.env);
    const results=[];
    for(const day of this.env.PUBLISH_DATES.split(",").sort()) {
      const object=await this.env.PRIVATE_PACKAGES.get("jobs/"+day+".json");
      if(!object)throw new Error("VERIFIED_JOB_MISSING");
      const job=await verifyEnvelope(await object.json(),this.env.PACKAGE_SIGNING_KEY);
      const jobCampaign=selectCampaign(job,campaign,JSON.parse(this.env.ADDITIONAL_CAMPAIGNS||"[]"));
      const result=await publisher.run(job,day,jobCampaign,true);
      results.push({day,role:job.role,...result,validated_job:await previewProof(job),conditional_on_prior_scheduled_success:results.length>0});
      records.set("publication:"+job.publication_identity,{publication_identity:job.publication_identity,semantic_creative_identity:job.semantic_creative_identity,project_id:job.project_id,state:"CONFIRMED_PUBLISHED",publication_timestamp:job.scheduled_at,project_sequence:{role:job.role}});
    }
    return {status:"SCHEDULE_DRY_RUN_PASSED",results,meta_writes:0,live_ledger_modified:false};
  }
  async accountCheck() {
    if(!this.env.META_ACCESS_TOKEN)return {status:"CREDENTIALS_MISSING",meta_writes:0};
    const p=new CloudPublisher(this.ctx.storage,this.env);
    const account=await p.meta("GET",this.env.ACCOUNT_ID,{fields:"id,user_id,username"});
    if(![account.id,account.user_id].includes(this.env.ACCOUNT_ID))throw new Error("ACCOUNT_MISMATCH");
    await p.meta("GET",this.env.ACCOUNT_ID+"/content_publishing_limit",{fields:"config,quota_usage"});
    return {status:"ACCOUNT_READY",username:account.username,meta_writes:0};
  }

}
export default {
  async fetch(request, env) {
    const path=new URL(request.url).pathname;
    const stub=env.ACCOUNT_STATE.getByName(env.ACCOUNT_ID);
    if(request.method==="GET" && path==="/health") {
      try{return Response.json(await stub.health());}
      catch{return Response.json({live_publishing:false,status:"LEDGER_IMPORT_BLOCKED"},{status:503});}
    }
    if(request.method!=="POST" || !env.ADMIN_KEY || request.headers.get("Authorization")!=="Bearer "+env.ADMIN_KEY)return new Response("Not found",{status:404});
    try {
      if(path==="/publication-status")return Response.json(await stub.publicationStatus());
      if(path==="/preview-schedule")return Response.json(await stub.previewSchedule());
      if(path==="/account-check")return Response.json(await stub.accountCheck());
      if(path==="/schedule-status")return Response.json(await stub.scheduleStatus());
      if(path==="/pause-campaign") {
        const {project_id,campaign_id}=await request.json();
        return Response.json(await stub.pauseCampaign(project_id,campaign_id));
      }
      if(path==="/preview") {
        const {day}=await request.json();
        if(!env.PUBLISH_DATES.split(",").includes(day))return Response.json({status:"DATE_NOT_AUTHORIZED"},{status:400});
        return Response.json(await stub.inspect(day,true));
      }
      return new Response("Not found",{status:404});
    }catch(error){return Response.json({status:"SAFETY_CHECK_FAILED",reason:safeReason(error),meta_writes:0},{status:503});}
  },
  async scheduled(controller, env, ctx) {
    const stub = env.ACCOUNT_STATE.getByName(env.ACCOUNT_ID);
    ctx.waitUntil(stub.scheduledCheck(controller.scheduledTime,controller.cron).then(result=>console.log(JSON.stringify(result))).catch(error=>{
      console.error(JSON.stringify({status:"SCHEDULED_HANDLER_FAILED",reason:safeReason(error)}));
      throw new Error(safeReason(error));
    }));
  }
};
