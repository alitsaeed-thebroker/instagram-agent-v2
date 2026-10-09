// Import the production entry point. Only Cloudflare's runtime base class is stubbed.
import { registerHooks } from "node:module";
import test from "node:test";
import assert from "node:assert/strict";
import {createHmac} from "node:crypto";
import {readFile} from "node:fs/promises";
registerHooks({resolve(specifier,context,next){
  if(specifier==="cloudflare:workers")return {url:"data:text/javascript,export class DurableObject {constructor(ctx,env){this.ctx=ctx;this.env=env}}",shortCircuit:true};
  return next(specifier,context);
}});
const {default:worker,AccountState}=await import("./worker.mjs");
const {hash}=await import("./publisher.mjs");
const at=Date.parse("2026-10-09T19:00:00Z");
class Store {
  constructor(){this.data=new Map();this.chain=Promise.resolve();}
  async get(k){return structuredClone(this.data.get(k));}
  async put(k,v){this.data.set(k,structuredClone(v));}
  async delete(k){this.data.delete(k);}
  async list({prefix}){return new Map([...this.data].filter(([k])=>k.startsWith(prefix)));}
  transaction(fn){const p=this.chain.then(()=>fn(this));this.chain=p.catch(()=>{});return p;}
}
async function harness(t){
  const clock=Date.now,request=globalThis.fetch;
  Date.now=()=>at;
  t.after(()=>{Date.now=clock;globalThis.fetch=request;});
  const storage=new Store(),pixels=new TextEncoder().encode("exact approved fixture bytes");
  const campaign={project_id:"P",campaign_id:"C",prior_publications:[]};
  const snapshot={schema_version:"cloud-ledger-import-v1",account_id:"A",campaign,records:[{publication_identity:"overview",project_id:"P",account_id:"A",state:"CONFIRMED_PUBLISHED",remote_media_id:"old",receipt_id:"old-receipt",publication_timestamp:"2026-10-07T06:00:00Z",project_sequence:{role:"project_overview"}}]};
  const ledger=new TextEncoder().encode(JSON.stringify(snapshot));
  const job={account_id:"A",project_id:"P",campaign_id:"C",scheduled_day:"2026-10-09",scheduled_at:"2026-10-09T22:00:00+03:00",valid_until:at+21600000,publication_identity:"community",semantic_creative_identity:"creative",package_type:"carousel",role:"community_lifestyle",caption:"Brochure lifestyle imagery; these images do not confirm completed facilities.",certification:{final_gate_passed:true,package_hash:"approved-fixture"},media:[]};
  // Distinct fixture bytes prove all carousel hashes and child order are checked.
  const images=new Map();
  for(let i=0;i<3;i++){const bytes=new Uint8Array([...pixels,i]);const url=`https://images.example/${i}.png`;images.set(url,bytes);job.media.push({url,sha256:await hash(bytes),source_asset_id:"source"+i});}
  let writes=0;const order=[];const requested=[];
  const env={ACCOUNT_ID:"A",LIVE_ENABLED:"true",PACKAGE_SIGNING_KEY:"private-test-fixture",ADMIN_KEY:"admin-test-fixture",META_ACCESS_TOKEN:"token-test-fixture",META_API_VERSION:"v23.0",PUBLISH_DATES:"2026-10-09,2026-10-11",LEDGER_SNAPSHOT_SHA256:await hash(ledger),APPROVED_SEQUENCE_OVERRIDE:JSON.stringify({project_id:"P",campaign_id:"C",ordered_publication_identities:["community","unit"]})};
  const objects=new Map();
  const sign=(value=job)=>{const payload=typeof value==="string"?value:JSON.stringify(value);return {payload,signature:createHmac("sha256",env.PACKAGE_SIGNING_KEY).update(payload).digest("hex")};};
  objects.set("migration/live-ledger.json",{arrayBuffer:async()=>ledger.buffer});
  objects.set("jobs/2026-10-09.json",{json:async()=>sign()});
  env.PRIVATE_PACKAGES={get:async key=>{requested.push(key);return objects.get(key);}};
  const state=new AccountState({storage},env);
  env.ACCOUNT_STATE={getByName:name=>{assert.equal(name,"A");return state;}};
  globalThis.fetch=async(url,opts={})=>{
    const u=String(url);
    if(images.has(u))return new Response(images.get(u),{headers:{"Content-Type":"image/png"}});
    if(opts.method==="POST"){
      assert.equal(await storage.get("unresolved-intent"),"community");
      assert.equal((await storage.get("publication:community")).state,"RECONCILIATION_REQUIRED");
      writes++;order.push(opts.body.get("image_url") || opts.body.get("children") || "publish");
      return Response.json({id:u.endsWith("/media_publish")?"published":"container"+writes});
    }
    if(u.includes("content_publishing_limit"))return Response.json({data:[]});
    if(u.includes("status_code"))return Response.json({status_code:"FINISHED"});
    if(u.includes("/published?"))return Response.json({id:"published",caption:job.caption,media_type:"CAROUSEL_ALBUM",children:{data:[{id:"container1"},{id:"container2"},{id:"container3"}]},permalink:"https://instagram.com/p/fixture",timestamp:new Date(at).toISOString()});
    return Response.json({id:"A",username:"fixture"});
  };
  const invoke=async(time=at,cron="0 19 * * *")=>{
    const pending=[];
    await worker.scheduled({scheduledTime:time,cron},env,{waitUntil:p=>pending.push(p)});
    assert.equal(pending.length,1,"actual scheduled handler must retain its promise");
    await Promise.all(pending);
    return storage.get("last-schedule-check");
  };
  return {state,env,storage,objects,job,sign,invoke,images,requested,order,writes:()=>writes};
}
test("actual scheduled handler: Baghdad 22:00, private signed job, ordered carousel, intent then durable receipt",async t=>{
  const h=await harness(t);const result=await h.invoke();assert.equal(result.status,"PUBLISHED");assert.equal(h.writes(),5);
  assert.ok(h.requested.includes("jobs/2026-10-09.json"));
  assert.deepEqual(h.order,[...h.images.keys(),"container1,container2,container3","publish"]);
  assert.equal((await h.storage.get("publication:community")).receipt_id,"cloud-receipt:published");
  assert.equal(await h.storage.get("unresolved-intent"),undefined);
});
test("actual handler never publishes the right-day job at the wrong exact slot",async t=>{
  const h=await harness(t);assert.equal((await h.invoke(at-13*3600000,"0 6 * * *")).status,"NOT_THIS_TIME_SLOT");assert.equal(h.writes(),0);
});
test("actual handler publishes the exact Baghdad 09:00 job at 06:00 UTC",async t=>{
  const h=await harness(t),morning=at-13*3600000;
  Date.now=()=>morning;h.job.scheduled_at="2026-10-09T09:00:00+03:00";
  assert.equal((await h.invoke(morning,"0 6 * * *")).status,"PUBLISHED");
  assert.equal(h.writes(),5);
});
test("actual VELORIA noon handler remains operational with Beverly's configured pause",async t=>{
  const h=await harness(t),noon=Date.parse("2026-10-11T09:00:00Z");
  Date.now=()=>noon;
  h.env.PAUSED_CAMPAIGNS=JSON.stringify([{project_id:"P",campaign_id:"C"}]);
  h.env.ADDITIONAL_CAMPAIGNS=JSON.stringify([{project_id:"VELORIA BY SHAHAN CO",campaign_id:"V",prior_publications:[],require_overview_source_certification:true}]);
  Object.assign(h.job,{project_id:"VELORIA BY SHAHAN CO",campaign_id:"V",role:"project_overview",scheduled_day:"2026-10-11",scheduled_at:"2026-10-11T12:00:00+03:00",valid_until:noon+21600000});
  Object.assign(h.job.certification,{overview_source_approved:true,source_evidence:h.job.media.map(m=>({asset_id:m.source_asset_id,project_id:h.job.project_id,source_hash:"a".repeat(64),source_document_hash:"b".repeat(64),source_page:1}))});
  h.objects.set("jobs/2026-10-11.json",{json:async()=>h.sign()});
  assert.equal((await h.invoke(noon,"0 9 * * *")).status,"PUBLISHED");
  assert.ok(h.requested.includes("jobs/2026-10-11.json"));
  assert.equal(h.writes(),5);assert.equal((await h.storage.get("publication:community")).project_id,"VELORIA BY SHAHAN CO");
});
test("actual handler replay and uncertain Meta write never retry publication",async t=>{
  const h=await harness(t);const fetch=globalThis.fetch;
  globalThis.fetch=async(url,opts)=>{if(String(url).endsWith("/media_publish"))throw new Error("lost response with PRIVATE details");return fetch(url,opts);};
  await assert.rejects(h.invoke(),/RECONCILIATION_REQUIRED/);
  assert.equal((await h.storage.get("publication:community")).state,"PUBLISHING_UNCERTAIN");
  const count=h.writes();assert.equal((await h.invoke()).status,"RECONCILIATION_REQUIRED");assert.equal(h.writes(),count);
  assert.equal((await h.state.health()).last_schedule_failure.reason,"RECONCILIATION_REQUIRED");
});
test("campaign pause arriving during remote preflight is rechecked before durable intent",async t=>{
  const h=await harness(t);const fetch=globalThis.fetch;let paused=false;
  globalThis.fetch=async(url,opts)=>{if(!paused && String(url).includes("content_publishing_limit")){paused=true;await h.state.pauseCampaign("P","C");}return fetch(url,opts);};
  await assert.rejects(h.invoke(),/CAMPAIGN_PAUSED/);assert.equal(h.writes(),0);assert.equal(await h.storage.get("publication:community"),undefined);
});
test("unauthorized day, minute, second, millisecond and invalid time persist skips",async t=>{
  const h=await harness(t);
  for(const time of [at+86400000,at+60000,at+1000,at+1,NaN])assert.equal((await h.invoke(time)).status,"DATE_OR_TIME_NOT_AUTHORIZED");
  assert.equal(h.writes(),0);assert.equal(h.requested.length,0);
});
test("missing private job leaves a durable diagnostic before intent",async t=>{
  const h=await harness(t);h.objects.delete("jobs/2026-10-09.json");assert.equal((await h.invoke()).status,"NO_VERIFIED_JOB");assert.equal(h.writes(),0);assert.equal(await h.storage.get("publication:community"),undefined);
});
test("R2 retrieval rejection is persisted safely and fails invocation",async t=>{
  const h=await harness(t);h.env.PRIVATE_PACKAGES.get=async key=>{if(key.startsWith("jobs/"))throw new Error("Authorization: Bearer SECRET");return h.objects.get(key);};
  await assert.rejects(h.invoke(),/SAFE_DIAGNOSTIC_UNAVAILABLE/);const r=await h.storage.get("last-schedule-check");assert.equal(r.phase,"JOB_RETRIEVAL");assert.ok(!JSON.stringify(r).includes("SECRET"));assert.equal(h.writes(),0);
});
test("bad signature and signed malformed JSON fail before intent with diagnostics",async t=>{
  const h=await harness(t);
  h.objects.set("jobs/2026-10-09.json",{json:async()=>({...h.sign(),signature:"0".repeat(64)})});
  await assert.rejects(h.invoke(),/PACKAGE_SIGNATURE_INVALID/);
  h.objects.set("jobs/2026-10-09.json",{json:async()=>h.sign("invalid JSON")});
  await assert.rejects(h.invoke(),/PACKAGE_PAYLOAD_INVALID/);assert.equal(h.writes(),0);
});
test("campaign identity mismatch and invalid sequence never reach Meta writes",async t=>{
  const h=await harness(t);h.job.campaign_id="OTHER";await assert.rejects(h.invoke(),/WRONG_PUBLICATION_SCOPE/);
  h.job.campaign_id="C";h.job.role="unit_layouts";await assert.rejects(h.invoke(),/INVALID_APPROVED_SEQUENCE/);assert.equal(h.writes(),0);
});
test("global and campaign pause persist skip, preserving another registered campaign",async t=>{
  const h=await harness(t);h.env.LIVE_ENABLED="false";assert.equal((await h.invoke()).status,"PAUSED");
  h.env.LIVE_ENABLED="true";h.env.ADDITIONAL_CAMPAIGNS=JSON.stringify([{project_id:"VELORIA",campaign_id:"V",prior_publications:[]}]);
  await h.state.pauseCampaign("P","C");assert.equal((await h.invoke()).status,"CAMPAIGN_PAUSED");
  assert.equal(await h.state.campaignPaused({project_id:"VELORIA",campaign_id:"V"}),false);assert.equal(h.writes(),0);
  await assert.rejects(h.state.pauseCampaign("OTHER","C"),/WRONG_PUBLICATION_SCOPE/);
});
test("configured Beverly-only recovery pause does not pause VELORIA",async t=>{
  const h=await harness(t);h.env.PAUSED_CAMPAIGNS=JSON.stringify([{project_id:"P",campaign_id:"C"}]);
  assert.equal((await h.invoke()).status,"CAMPAIGN_PAUSED");assert.equal(await h.state.campaignPaused({project_id:"VELORIA",campaign_id:"V"}),false);
});
test("unresolved intent and ledger import failures are observable without ledger reset",async t=>{
  const h=await harness(t);await h.state.importLedger();await h.storage.put("unresolved-intent","old-uncertain");
  assert.equal((await h.invoke()).status,"RECONCILIATION_REQUIRED");
  h.env.LEDGER_SNAPSHOT_SHA256="changed";await assert.rejects(h.invoke(),/LEDGER_IMPORT_CONFLICT/);assert.equal(h.writes(),0);
  assert.equal((await h.storage.get("publication:overview")).receipt_id,"old-receipt");
});
test("changed hosted bytes fail before intent and health exposes scheduler failure",async t=>{
  const h=await harness(t);h.images.set(h.job.media[0].url,new Uint8Array([0]));await assert.rejects(h.invoke(),/HOSTED_MEDIA_CHANGED/);
  const health=await h.state.health();assert.equal(health.scheduler_status,"FAILED");assert.equal(health.last_schedule_check.reason,"HOSTED_MEDIA_CHANGED");assert.equal(health.scheduler_certified,false);assert.equal(h.writes(),0);
});
test("diagnostic persistence failure prevents publication",async t=>{
  const h=await harness(t);h.storage.transaction=async()=>{throw new Error("storage unavailable");};await assert.rejects(h.invoke());assert.equal(h.writes(),0);
});
test("dry run of exact job never creates intent or overwrites real scheduler evidence",async t=>{
  const h=await harness(t);await h.invoke(at-13*3600000);const before=await h.storage.get("last-schedule-check");
  const preview=await h.state.inspect("2026-10-09",true);
  assert.equal(preview.status,"DRY_RUN_PASSED");
  assert.equal(preview.validated_job.publication_identity,h.job.publication_identity);
  assert.equal(preview.validated_job.caption_sha256,await hash(new TextEncoder().encode(h.job.caption)));
  assert.deepEqual(preview.validated_job.ordered_media_sha256,h.job.media.map(m=>m.sha256));
  assert.ok(!JSON.stringify(preview).includes(h.job.caption));
  assert.deepEqual(await h.storage.get("last-schedule-check"),before);assert.equal(h.writes(),0);assert.equal(await h.storage.get("publication:community"),undefined);
});
test("only authenticated admin can pause a registered campaign or read diagnostic history",async t=>{
  const h=await harness(t);const make=key=>new Request("https://worker.example/pause-campaign",{method:"POST",headers:{Authorization:"Bearer "+key,"Content-Type":"application/json"},body:JSON.stringify({project_id:"P",campaign_id:"C"})});
  assert.equal((await worker.fetch(make("wrong"),h.env)).status,404);
  assert.equal((await (await worker.fetch(make(h.env.ADMIN_KEY),h.env)).json()).status,"PAUSED");assert.equal((await h.invoke()).status,"CAMPAIGN_PAUSED");
  const response=await worker.fetch(new Request("https://worker.example/schedule-status",{method:"POST",headers:{Authorization:"Bearer "+h.env.ADMIN_KEY}}),h.env);assert.ok((await response.json()).checks.length>0);
});
test("diagnostic retention removes only old diagnostics, preserving publication history",async t=>{
  const h=await harness(t);await h.state.importLedger();for(let i=0;i<205;i++)await h.state.recordSchedule({status:"NO_VERIFIED_JOB",scheduled_time:i});
  assert.equal((await h.storage.list({prefix:"schedule-check:"})).size,200);assert.equal((await h.storage.get("publication:overview")).receipt_id,"old-receipt");
});
test("deployment cron hours match the actual scheduled handler configuration",async()=>{
  const config=JSON.parse(await readFile(new URL("./wrangler.jsonc",import.meta.url),"utf8"));
  assert.deepEqual(config.triggers.crons.map(c=>Number(c.split(" ")[1])).sort((a,b)=>a-b),config.vars.SCHEDULED_HOURS_UTC.split(",").map(Number).sort((a,b)=>a-b));
  assert.deepEqual(JSON.parse(config.vars.PAUSED_CAMPAIGNS).map(p=>p.project_id),["Beverly Hills"]);
});
