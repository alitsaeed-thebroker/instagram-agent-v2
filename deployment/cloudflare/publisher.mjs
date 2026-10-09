const enc = new TextEncoder();
export async function hash(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))].map(x=>x.toString(16).padStart(2,"0")).join("");
}
export async function verifyEnvelope(envelope,secret) {
  if (!secret || !envelope || typeof envelope.payload!=="string" || !/^[a-f0-9]{64}$/.test(envelope.signature||"")) throw new Error("UNSIGNED_PACKAGE");
  const key=await crypto.subtle.importKey("raw",enc.encode(secret),{name:"HMAC",hash:"SHA-256"},false,["verify"]);
  const sig=Uint8Array.from(envelope.signature.match(/../g),x=>parseInt(x,16));
  if (!await crypto.subtle.verify("HMAC",key,sig,enc.encode(envelope.payload))) throw new Error("PACKAGE_SIGNATURE_INVALID");
  try {
    const job=JSON.parse(envelope.payload);
    if(!job || typeof job!=="object" || Array.isArray(job))throw new Error();
    return job;
  } catch {throw new Error("PACKAGE_PAYLOAD_INVALID");}
}
export function validateJob(job,env,day,records,campaign,now=Date.now()) {
  if (job.account_id!==env.ACCOUNT_ID || job.project_id!==campaign.project_id || job.campaign_id!==campaign.campaign_id || job.scheduled_day!==day) throw new Error("WRONG_PUBLICATION_SCOPE");
  if (!Number.isFinite(job.valid_until) || job.valid_until < now || job.certification?.final_gate_passed!==true || !job.certification?.package_hash || !job.publication_identity || !job.semantic_creative_identity) throw new Error("UNCERTIFIED_OR_EXPIRED_PACKAGE");
  if (!["single_post","carousel"].includes(job.package_type) || !Array.isArray(job.media) || job.media.length<1 || job.media.length>10 || (job.package_type==="single_post" && job.media.length!==1)) throw new Error("INVALID_MEDIA_COUNT");
  if (new Set(job.media.map(x=>x.sha256)).size!==job.media.length || job.media.some(x=>!/^https:\/\//.test(x.url||"") || !/^[a-f0-9]{64}$/.test(x.sha256||"") || !x.source_asset_id)) throw new Error("INVALID_OR_DUPLICATE_MEDIA");
  if (!job.caption || job.caption.length>2200) throw new Error("INVALID_CAPTION");
  if (records.some(r=>r.publication_identity===job.publication_identity || r.semantic_creative_identity===job.semantic_creative_identity)) throw new Error("ALREADY_RESERVED_OR_PUBLISHED");
  if (records.some(r=>["PUBLISHING_UNCERTAIN","RECONCILIATION_REQUIRED"].includes(r.state))) throw new Error("RECONCILIATION_REQUIRED");
  const confirmed=records.filter(r=>r.state==="CONFIRMED_PUBLISHED");
  const latest=Math.max(0,...confirmed.map(r=>Date.parse(r.publication_timestamp)||0));
  if (now-latest<12*60*60*1000) throw new Error("GLOBAL_SPACING_BLOCKED");
  if (confirmed.some(r=>new Date((Date.parse(r.publication_timestamp)||0)+3*3600000).toISOString().slice(0,10)===day)) throw new Error("DAILY_POST_ALREADY_PUBLISHED");
  const legacy=new Set(campaign.prior_publications.map(x=>x.publication_identity));
  const history=confirmed.filter(r=>r.project_id===job.project_id && !legacy.has(r.publication_identity)).sort((a,b)=>Date.parse(a.publication_timestamp)-Date.parse(b.publication_timestamp));
  const roles=history.map(r=>r.project_sequence?.role);
  const override=env.APPROVED_SEQUENCE_OVERRIDE?JSON.parse(env.APPROVED_SEQUENCE_OVERRIDE):null;
  const approved=override?.project_id===job.project_id && override?.campaign_id===job.campaign_id && Array.isArray(override.ordered_publication_identities) && override.ordered_publication_identities.length===2 && override.ordered_publication_identities.includes(job.publication_identity);
  if (approved) {
    const index=override.ordered_publication_identities.indexOf(job.publication_identity);
    if(roles[0]!=="project_overview" || history.length!==index+1 || job.role!==["community_lifestyle","unit_layouts"][index] || (index===1 && (roles[1]!=="community_lifestyle" || history[1].publication_identity!==override.ordered_publication_identities[0]))) throw new Error("INVALID_APPROVED_SEQUENCE");
  } else {
    if (!roles.length && job.role!=="project_overview") throw new Error("OVERVIEW_REQUIRED");
    if (roles.length===1 && (roles[0]!=="project_overview" || job.role!=="project_site_plan")) throw new Error("SITE_PLAN_REQUIRED");
    if (roles.length>=2 && (roles[0]!=="project_overview" || roles[1]!=="project_site_plan" || ["project_overview","project_site_plan"].includes(job.role))) throw new Error("INVALID_CAMPAIGN_SEQUENCE");
  }
  if(campaign.require_overview_source_certification && job.role==="project_overview") {
    const proof=job.certification.source_evidence||[];
    if(job.certification.overview_source_approved!==true || proof.length!==job.media.length || job.media.some(m=>!proof.some(e=>e.asset_id===m.source_asset_id && e.project_id===job.project_id && /^[a-f0-9]{64}$/.test(e.source_hash||"") && /^[a-f0-9]{64}$/.test(e.source_document_hash||"") && Number.isInteger(e.source_page) && e.source_page>0)))throw new Error("OVERVIEW_SOURCE_NOT_APPROVED");
  }
  if (job.role==="project_site_plan" && job.certification.technical_site_plan_verified!==true) {
    const proof=job.certification.project_layout;
    const sources=job.certification.source_evidence || [];
    if (proof?.verified!==true || proof.representations?.length!==job.media.length || sources.length!==job.media.length || proof.representations.some(x=>x!=="architectural_illustration") || !proof.disclosures?.includes("Project brochure illustration; not a measured site drawing") || !job.caption.includes("Project brochure illustration; not a measured site drawing") || job.media.some(m=>!sources.some(s=>s.asset_id===m.source_asset_id && s.project_id===job.project_id && /^[a-f0-9]{64}$/.test(s.source_hash||"") && /^[a-f0-9]{64}$/.test(s.source_document_hash||"") && Number.isInteger(s.source_page) && s.source_page>0))) throw new Error("SITE_PLAN_NOT_VERIFIED");
  }
  if (job.role==="unit_layouts") {
    const proof=job.certification.canonical_relationships;
    const evidence=job.certification.source_evidence || [];
    if(job.certification.canonical_relationships_verified!==true || !Array.isArray(proof) || proof.length!==job.media.length || job.media.some(m=>!proof.some(r=>r.status==="VERIFIED" && ["deterministic_catalogue_villa_relationship","deterministic_pdf_labels_and_exact_render"].includes(r.authority) && r.provenance?.asset_id===m.source_asset_id && r.provenance?.project_id===job.project_id && evidence.some(e=>e.asset_id===m.source_asset_id && e.source_hash===r.provenance.source_hash && e.source_document_hash===r.provenance.source_document_hash && e.source_page===r.provenance.source_page)))) throw new Error("UNIT_PLAN_NOT_VERIFIED");
  }
}
export class CloudPublisher {
  constructor(storage,env,request=(...args)=>fetch(...args)){this.storage=storage;this.env=env;this.request=request;}
  async meta(method,path,params={}) {
    const url=new URL(`https://graph.instagram.com/${this.env.META_API_VERSION}/${path}`);
    const options={method,headers:{Authorization:`Bearer ${this.env.META_ACCESS_TOKEN}`}};
    if(method==="GET") for(const [k,v] of Object.entries(params))url.searchParams.set(k,v);
    else {options.body=new URLSearchParams(params);options.headers["Content-Type"]="application/x-www-form-urlencoded";}
    const response=await this.request(url,options);const body=await response.json();
    if(!response.ok || body.error)throw new Error("META_REQUEST_FAILED:"+(Number(body.error?.code)||response.status));
    return body;
  }
  async checkpoint(record) {await this.storage.put("publication:"+record.publication_identity,record);}
  async write(record,path,params) {
    record.last_write={path_category:path.endsWith("/media_publish")?"publish":"container",started_at:new Date().toISOString()};
    await this.checkpoint(record);
    const result=await this.meta("POST",path,params);
    if(!result.id)throw new Error("META_MISSING_ID");
    record.last_write.remote_id=result.id;await this.checkpoint(record);return result.id;
  }
  async ready(id) {
    for(let i=0;i<10;i++){
      const value=await this.meta("GET",id,{fields:"status_code"});
      if(value.status_code==="FINISHED")return;
      if(["ERROR","EXPIRED"].includes(value.status_code))throw new Error("CONTAINER_REJECTED");
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
    throw new Error("CONTAINER_NOT_READY");
  }
  async remoteConfirm(record) {
    const remote=await this.meta("GET",record.remote_media_id,{fields:"id,caption,media_type,permalink,timestamp,children{id}"});
    const count=record.format==="carousel"?(remote.children?.data||[]).length:1;
    if(remote.media_type!==(record.format==="carousel"?"CAROUSEL_ALBUM":"IMAGE") || remote.id!==record.remote_media_id || remote.caption!==record.caption || count!==record.media_hashes.length)throw new Error("REMOTE_CONFIRMATION_FAILED");
    record.state="CONFIRMED_PUBLISHED";record.publication_timestamp=remote.timestamp;record.confirmation_timestamp=new Date().toISOString();record.permalink=remote.permalink;record.receipt_id="cloud-receipt:"+remote.id;
    await this.storage.transaction(async txn=>{await txn.put("publication:"+record.publication_identity,record);await txn.delete("unresolved-intent");});
    return {status:"PUBLISHED",media_id:remote.id,permalink:remote.permalink};
  }
  async run(job,day,campaign,dryRun=false) {
    const records=[...(await this.storage.list({prefix:"publication:"})).values()];
    validateJob(job,this.env,day,records,campaign,dryRun?Math.max(Date.now(),Date.parse(job.scheduled_at)||0):Date.now());
    if(await this.storage.get("unresolved-intent"))throw new Error("RECONCILIATION_REQUIRED");
    for(const media of job.media){
      const response=await this.request(media.url);
      if(!response.ok || !(response.headers.get("Content-Type")||"").startsWith("image/"))throw new Error("HOSTED_MEDIA_UNAVAILABLE");
      if(await hash(await response.arrayBuffer())!==media.sha256)throw new Error("HOSTED_MEDIA_CHANGED");
    }
    const account=await this.meta("GET",this.env.ACCOUNT_ID,{fields:"id,user_id,username"});
    if(![account.id,account.user_id].includes(this.env.ACCOUNT_ID))throw new Error("ACCOUNT_MISMATCH");
    await this.meta("GET",this.env.ACCOUNT_ID+"/content_publishing_limit",{fields:"config,quota_usage"});
    if(dryRun)return {status:"DRY_RUN_PASSED",meta_writes:0};
    if(this.env.LIVE_ENABLED!=="true")return {status:"PAUSED",meta_writes:0};
    const record={publication_identity:job.publication_identity,semantic_creative_identity:job.semantic_creative_identity,project_id:job.project_id,account_id:this.env.ACCOUNT_ID,state:"RECONCILIATION_REQUIRED",caption:job.caption,media_hashes:job.media.map(x=>x.sha256),format:job.package_type,project_sequence:{role:job.role},campaign_id:job.campaign_id,child_container_ids:[],created_at:new Date().toISOString()};
    await this.storage.transaction(async txn=>{
      const pauses=JSON.parse(this.env.PAUSED_CAMPAIGNS || "[]");
      if(pauses.some(p=>p.project_id===job.project_id && p.campaign_id===job.campaign_id) || await txn.get("campaign-pause:"+JSON.stringify([job.project_id,job.campaign_id])))throw new Error("CAMPAIGN_PAUSED");
      validateJob(job,this.env,day,[...(await txn.list({prefix:"publication:"})).values()],campaign);
      if(await txn.get("unresolved-intent") || await txn.get("publication:"+job.publication_identity))throw new Error("CONCURRENT_PUBLICATION_BLOCKED");
      await txn.put("unresolved-intent",job.publication_identity);await txn.put("publication:"+job.publication_identity,record);
    });
    try {
      if(job.package_type==="carousel"){
        for(const media of job.media){const id=await this.write(record,this.env.ACCOUNT_ID+"/media",{image_url:media.url,is_carousel_item:"true"});record.child_container_ids.push(id);await this.checkpoint(record);await this.ready(id);}
        record.parent_container_id=await this.write(record,this.env.ACCOUNT_ID+"/media",{media_type:"CAROUSEL",children:record.child_container_ids.join(","),caption:job.caption});
      }else record.parent_container_id=await this.write(record,this.env.ACCOUNT_ID+"/media",{image_url:job.media[0].url,caption:job.caption});
      await this.checkpoint(record);await this.ready(record.parent_container_id);
      record.remote_media_id=await this.write(record,this.env.ACCOUNT_ID+"/media_publish",{creation_id:record.parent_container_id});await this.checkpoint(record);
      return await this.remoteConfirm(record);
    }catch{record.state="PUBLISHING_UNCERTAIN";await this.checkpoint(record);throw new Error("RECONCILIATION_REQUIRED");}
  }
  async reconcile() {
    const identity=await this.storage.get("unresolved-intent");if(!identity)return {status:"NO_UNCERTAIN_INTENT"};
    const record=await this.storage.get("publication:"+identity);
    if(record?.remote_media_id)return this.remoteConfirm(record);
    if(record?.last_write?.path_category==="publish" && record.last_write.remote_id){record.remote_media_id=record.last_write.remote_id;return this.remoteConfirm(record);}
    // Container IDs cannot prove which post exists; do not replay any write.
    return {status:"REVIEW_REQUIRED",meta_writes:0};
  }
}

