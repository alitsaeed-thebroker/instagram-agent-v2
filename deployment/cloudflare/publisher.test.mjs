import test from "node:test";
import assert from "node:assert/strict";
import {CloudPublisher,validateJob,verifyEnvelope,hash} from "./publisher.mjs";
const account="A",day="2026-10-09";
const campaign={project_id:"P",campaign_id:"C",prior_publications:[]};
function job(){return {account_id:account,project_id:"P",campaign_id:"C",scheduled_day:day,valid_until:Date.now()+86400000,publication_identity:"post",semantic_creative_identity:"creative",package_type:"single_post",role:"project_overview",caption:"Source-backed overview",certification:{final_gate_passed:true,package_hash:"hash"},media:[{url:"https://images.example/a.png",sha256:"a".repeat(64),source_asset_id:"source"}]};}
class Store {
  constructor(){this.data=new Map();this.chain=Promise.resolve();}
  async get(k){return structuredClone(this.data.get(k));}
  async put(k,v){this.data.set(k,structuredClone(v));}
  async delete(k){this.data.delete(k);}
  async list({prefix}){return new Map([...this.data].filter(([k])=>k.startsWith(prefix)));}
  transaction(fn){const next=this.chain.then(()=>fn(this));this.chain=next.catch(()=>{});return next;}
}
const env={ACCOUNT_ID:account,META_API_VERSION:"v24.0",META_ACCESS_TOKEN:"test-token",LIVE_ENABLED:"true"};
test("wrong account and stale proof block",()=>{const j=job();j.account_id="B";assert.throws(()=>validateJob(j,env,day,[],campaign));j.account_id=account;j.certification.final_gate_passed=false;assert.throws(()=>validateJob(j,env,day,[],campaign));});
test("duplicate identity and semantic image block",()=>{const j=job();assert.throws(()=>validateJob(j,env,day,[{publication_identity:j.publication_identity}],campaign));assert.throws(()=>validateJob(j,env,day,[{semantic_creative_identity:j.semantic_creative_identity}],campaign));});
test("uncertain history blocks",()=>assert.throws(()=>validateJob(job(),env,day,[{state:"PUBLISHING_UNCERTAIN"}],campaign)));
test("site plan required after overview",()=>{const j=job();const records=[{project_id:"P",state:"CONFIRMED_PUBLISHED",project_sequence:{role:"project_overview"},publication_timestamp:"2026-08-01T00:00:00Z"}];assert.throws(()=>validateJob(j,env,day,records,campaign));j.role="project_site_plan";assert.throws(()=>validateJob(j,env,day,records,campaign));j.certification.technical_site_plan_verified=true;assert.doesNotThrow(()=>validateJob(j,env,day,records,campaign));});
test("unsigned and modified packages rejected",async()=>{await assert.rejects(verifyEnvelope({payload:"{}",signature:"0".repeat(64)},"secret"));});
async function harness(failPublish=false){
  const store=new Store(),j=job(),bytes=new TextEncoder().encode("pixels");j.media[0].sha256=await hash(bytes);let writes=0,serial=0;
  const request=async(url,opts={})=>{
    const u=String(url);if(u.startsWith("https://images.example"))return new Response(bytes,{headers:{"Content-Type":"image/png"}});
    if(opts.method==="POST"){
      assert.ok(await store.get("unresolved-intent"),"intent must precede every Meta write");writes++;
      if(u.endsWith("/media_publish") && failPublish)throw new Error("process crash after submission");
      return Response.json({id:u.endsWith("/media_publish")?"published":"container"+(++serial)});
    }
    if(u.includes("content_publishing_limit"))return Response.json({data:[]});
    if(u.includes("status_code"))return Response.json({status_code:"FINISHED"});
    if(u.includes("/published?"))return Response.json({id:"published",caption:j.caption,media_type:"IMAGE",permalink:"https://instagram.com/p/test",timestamp:new Date().toISOString()});
    return Response.json({id:account,username:"test"});
  };
  return {store,j,publisher:new CloudPublisher(store,env,request),writes:()=>writes};
}
test("dry run makes no intent or writes",async()=>{const h=await harness();assert.equal((await h.publisher.run(h.j,day,campaign,true)).status,"DRY_RUN_PASSED");assert.equal(h.writes(),0);assert.equal(await h.store.get("unresolved-intent"),undefined);});
test("successful publish retains durable receipt and rejects replay",async()=>{const h=await harness();assert.equal((await h.publisher.run(h.j,day,campaign)).status,"PUBLISHED");assert.equal((await h.store.get("publication:post")).state,"CONFIRMED_PUBLISHED");await assert.rejects(h.publisher.run(h.j,day,campaign));assert.equal(h.writes(),2);});
test("lost response quarantines without blind recovery writes",async()=>{const h=await harness(true);await assert.rejects(h.publisher.run(h.j,day,campaign));assert.equal((await h.store.get("publication:post")).state,"PUBLISHING_UNCERTAIN");assert.equal((await h.publisher.reconcile()).status,"REVIEW_REQUIRED");assert.equal(h.writes(),2);});
test("simultaneous publication reserves once",async()=>{const h=await harness();await Promise.allSettled([h.publisher.run(h.j,day,campaign),h.publisher.run(h.j,day,campaign)]);assert.equal(h.writes(),2);});

test("illustrated layout needs exact source proof and disclosure",()=>{
  const j=job();j.role="project_site_plan";
  const records=[{project_id:"P",state:"CONFIRMED_PUBLISHED",project_sequence:{role:"project_overview"},publication_timestamp:"2026-08-01T00:00:00Z"}];
  j.caption+=" Project brochure illustration; not a measured site drawing";
  j.certification.project_layout={verified:true,representations:["architectural_illustration"],disclosures:["Project brochure illustration; not a measured site drawing"]};
  assert.throws(()=>validateJob(j,env,day,records,campaign));
  j.certification.source_evidence=[{asset_id:"source",project_id:"P",source_hash:"b".repeat(64),source_document_hash:"c".repeat(64),source_page:4}];
  assert.doesNotThrow(()=>validateJob(j,env,day,records,campaign));
  j.caption="Measured plots";assert.throws(()=>validateJob(j,env,day,records,campaign));
});
test("missing expiry fails closed",()=>{const j=job();delete j.valid_until;assert.throws(()=>validateJob(j,env,day,[],campaign));});

test("future schedule spacing is evaluated at its time in preview only",()=>{
 const j=job();j.role="community_lifestyle";
 const records=[{project_id:"P",state:"CONFIRMED_PUBLISHED",publication_timestamp:"2026-10-07T06:00:00Z",project_sequence:{role:"project_overview"}},{project_id:"P",state:"CONFIRMED_PUBLISHED",publication_timestamp:"2026-10-08T06:00:00Z",project_sequence:{role:"project_site_plan"}}];
 j.valid_until=Date.parse("2026-10-10T00:00:00Z");
 assert.doesNotThrow(()=>validateJob(j,env,day,records,campaign,Date.parse("2026-10-09T06:00:00Z")));
 assert.throws(()=>validateJob(j,env,day,records,campaign,Date.parse("2026-10-08T07:00:00Z")));
});

test("unit verification flag cannot replace canonical exact-source proof",()=>{
 const j=job();j.role="unit_layouts";j.certification.canonical_relationships_verified=true;
 const records=[{project_id:"P",state:"CONFIRMED_PUBLISHED",publication_timestamp:"2026-08-01T06:00:00Z",project_sequence:{role:"project_overview"}},{project_id:"P",state:"CONFIRMED_PUBLISHED",publication_timestamp:"2026-08-02T06:00:00Z",project_sequence:{role:"project_site_plan"}}];
 assert.throws(()=>validateJob(j,env,day,records,campaign));
 j.certification.source_evidence=[{asset_id:"source",source_hash:"b".repeat(64),source_document_hash:"c".repeat(64),source_page:34}];
 j.certification.canonical_relationships=[{status:"VERIFIED",authority:"deterministic_catalogue_villa_relationship",provenance:{asset_id:"source",project_id:"P",source_hash:"b".repeat(64),source_document_hash:"c".repeat(64),source_page:34}}];
 assert.doesNotThrow(()=>validateJob(j,env,day,records,campaign));
 j.certification.canonical_relationships[0].authority="llm_only";assert.throws(()=>validateJob(j,env,day,records,campaign));
});

test("approved cancellation allows only the exact community identity after overview",()=>{
 const j=job();j.role="community_lifestyle";
 const records=[{publication_identity:"overview",project_id:"P",state:"CONFIRMED_PUBLISHED",project_sequence:{role:"project_overview"},publication_timestamp:"2026-08-01T00:00:00Z"}];
 const e={...env,APPROVED_SEQUENCE_OVERRIDE:JSON.stringify({project_id:"P",campaign_id:"C",ordered_publication_identities:["post","unit"]})};
 assert.doesNotThrow(()=>validateJob(j,e,day,records,campaign));
 j.publication_identity="other";assert.throws(()=>validateJob(j,e,day,records,campaign));
 j.publication_identity="unit";j.role="unit_layouts";assert.throws(()=>validateJob(j,e,day,records,campaign),/INVALID_APPROVED_SEQUENCE/);
 j.publication_identity="post";j.role="community_lifestyle";assert.throws(()=>validateJob(j,e,day,[],campaign),/INVALID_APPROVED_SEQUENCE/);
 const wrong={...e,APPROVED_SEQUENCE_OVERRIDE:JSON.stringify({project_id:"P",campaign_id:"OTHER",ordered_publication_identities:["post","unit"]})};assert.throws(()=>validateJob(j,wrong,day,records,campaign));
});

test("approved unit post still rejects weak provenance after confirmed community",()=>{
 const j=job();j.publication_identity="unit";j.role="unit_layouts";
 const records=[{publication_identity:"overview",project_id:"P",state:"CONFIRMED_PUBLISHED",project_sequence:{role:"project_overview"},publication_timestamp:"2026-08-01T00:00:00Z"},{publication_identity:"community",project_id:"P",state:"CONFIRMED_PUBLISHED",project_sequence:{role:"community_lifestyle"},publication_timestamp:"2026-08-02T00:00:00Z"}];
 const e={...env,APPROVED_SEQUENCE_OVERRIDE:JSON.stringify({project_id:"P",campaign_id:"C",ordered_publication_identities:["community","unit"]})};
 assert.throws(()=>validateJob(j,e,day,records,campaign),/UNIT_PLAN_NOT_VERIFIED/);
 records[1].publication_identity="different";assert.throws(()=>validateJob(j,e,day,records,campaign),/INVALID_APPROVED_SEQUENCE/);
});

test('registered overview requires exact approved source evidence',()=>{const j=job(),c={...campaign,require_overview_source_certification:true};assert.throws(()=>validateJob(j,env,day,[],c));j.certification.overview_source_approved=true;j.certification.source_evidence=[{asset_id:'source',project_id:'P',source_hash:'b'.repeat(64),source_document_hash:'c'.repeat(64),source_page:1}];assert.doesNotThrow(()=>validateJob(j,env,day,[],c));j.certification.source_evidence[0].project_id='OTHER';assert.throws(()=>validateJob(j,env,day,[],c));});
test('another project receipt still enforces global spacing',()=>{const j=job();assert.throws(()=>validateJob(j,env,day,[{project_id:'OTHER',state:'CONFIRMED_PUBLISHED',publication_timestamp:new Date().toISOString()}],campaign),/GLOBAL_SPACING_BLOCKED/);});
