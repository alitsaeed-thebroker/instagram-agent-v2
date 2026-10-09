import test from "node:test";
import assert from "node:assert/strict";
import {scheduledDay,cloudGate} from "./policy.mjs";
test("Baghdad 09:00 equals UTC 06:00",()=>assert.equal(scheduledDay(Date.parse("2026-10-09T06:00:00Z"),"2026-10-09,2026-10-10,2026-10-11"),"2026-10-09"));
test("outside approved dates is blocked",()=>assert.equal(scheduledDay(Date.parse("2026-10-12T06:00:00Z"),"2026-10-09,2026-10-10,2026-10-11"),null));
test("wrong hour is blocked",()=>assert.equal(scheduledDay(Date.parse("2026-10-09T09:00:00Z"),"2026-10-09"),null));
test("paused configuration cannot publish",()=>assert.equal(cloudGate("false",true,false),"PAUSED"));
test("missing migrated ledger fails closed",()=>assert.equal(cloudGate("true",false,false),"LEDGER_MIGRATION_REQUIRED"));
test("uncertain intent blocks",()=>assert.equal(cloudGate("true",true,true),"RECONCILIATION_REQUIRED"));
test("infrastructure cannot enable unported publisher",()=>assert.equal(cloudGate("true",true,false),"PUBLISHER_PORT_CERTIFICATION_REQUIRED"));

import {validateSnapshot} from "./policy.mjs";
const valid = () => ({schema_version:"cloud-ledger-import-v1",account_id:"A",records:[{publication_identity:"id",account_id:"A",state:"CONFIRMED_PUBLISHED",remote_media_id:"media",receipt_id:"receipt"}]});
test("confirmed receipt migrates",()=>assert.equal(validateSnapshot(valid(),"A"),true));
test("wrong account blocks migration",()=>assert.throws(()=>validateSnapshot(valid(),"B")));
test("duplicate identity blocks migration",()=>{const s=valid();s.records.push(s.records[0]);assert.throws(()=>validateSnapshot(s,"A"));});
test("missing receipt blocks confirmation",()=>{const s=valid();delete s.records[0].receipt_id;assert.throws(()=>validateSnapshot(s,"A"));});
test("unknown ledger state blocks migration",()=>{const s=valid();s.records[0].state="READY";assert.throws(()=>validateSnapshot(s,"A"));});

import {selectCampaign,jobMatchesSlot} from './policy.mjs';
test('noon trigger and exact job time',()=>{const at=Date.parse('2026-10-11T12:00:00+03:00');assert.equal(scheduledDay(at,'2026-10-11',[6,9]),'2026-10-11');assert.ok(jobMatchesSlot({scheduled_at:'2026-10-11T12:00:00+03:00'},at));assert.equal(jobMatchesSlot({scheduled_at:'2026-10-11T09:00:00+03:00'},at),false);});
test('project campaigns remain isolated',()=>{const p={project_id:'BH',campaign_id:'C1',prior_publications:[]},v={project_id:'VEL',campaign_id:'C2',prior_publications:[]};assert.equal(selectCampaign({project_id:'VEL',campaign_id:'C2'},p,[v]),v);assert.throws(()=>selectCampaign({project_id:'VEL',campaign_id:'C1'},p,[v]));});

test("approved 13:00 Baghdad slot routes only at 10:00 UTC",()=>{
 assert.equal(scheduledDay(Date.parse("2026-10-10T10:00:00Z"),"2026-10-10",[6,9,10]),"2026-10-10");
 assert.equal(scheduledDay(Date.parse("2026-10-10T10:01:00Z"),"2026-10-10",[6,9,10]),null);
});

test("22:00 Baghdad routes at 19:00 UTC on October 9",()=>{
 assert.equal(scheduledDay(Date.parse("2026-10-09T19:00:00Z"),"2026-10-09",[6,9,10,19]),"2026-10-09");
 assert.equal(scheduledDay(Date.parse("2026-10-09T19:01:00Z"),"2026-10-09",[6,9,10,19]),null);
});
