import assert from 'node:assert/strict';
import {taskPlan} from '../supabase/functions/crowd-machine/contract.mjs';
const base={platforms:['bili'],mode:'detail',delivery_basis:'existing_saved',desired_items:1,
  max_api_requests:0,targets_by_platform:{bili:['BV1ocaW6rETo']},
  idempotency_key:'offline-ref-limit',purpose:'noncommercial_research'};
const refs=count=>Array.from({length:count},(_,i)=>({platform:'bilibili',content_id:'117355149531810',
  kind:i?'comment':'content',version_hash:i.toString(16).padStart(64,'0')}));
const input=count=>({...base,record_refs_by_platform:{bili:refs(count)}});
const plan=await taskPlan(input(200));
assert.equal(plan.children[0].record_refs.length,200);
assert.equal(plan.children[0].request_quota,0);
assert.equal(plan.children[0].item_quota,1);
assert.equal(plan.request.max_api_requests,0);
await assert.rejects(taskPlan(input(201)),/invalid_record_refs/);
await assert.rejects(taskPlan({...input(200),delivery_basis:'live_capture',max_api_requests:5}),/existing_refs_require_existing_saved/);
const snapshot=input(200);snapshot.record_refs_by_platform.bili.forEach(ref=>ref.results_revision=70);
assert.equal((await taskPlan(snapshot)).children[0].record_refs[0].results_revision,70);
for(const invalid of [0,-1,1.5,true,null,'70']) {
  const bad=input(1);bad.record_refs_by_platform.bili[0].results_revision=invalid;
  await assert.rejects(taskPlan(bad),/invalid_record_refs/);
}
const noVersion=input(1);delete noVersion.record_refs_by_platform.bili[0].version_hash;noVersion.record_refs_by_platform.bili[0].results_revision=70;
await assert.rejects(taskPlan(noVersion),/invalid_record_refs/);
const bound=input(1);Object.assign(bound.record_refs_by_platform.bili[0],{results_revision:70,record_sha256:'a'.repeat(64)});
assert.equal((await taskPlan(bound)).children[0].record_refs[0].record_sha256,'a'.repeat(64));
for(const invalid of ['bad','A'.repeat(64),null,true]) {
  const bad=structuredClone(bound);bad.record_refs_by_platform.bili[0].record_sha256=invalid;
  await assert.rejects(taskPlan(bad),/invalid_record_refs/);
}
for(const missing of ['results_revision','version_hash']) {
  const bad=structuredClone(bound);delete bad.record_refs_by_platform.bili[0][missing];
  await assert.rejects(taskPlan(bad),/invalid_record_refs/);
}
console.log('existing_saved ref limit, snapshot and full row binding: 21 offline assertions passed');
