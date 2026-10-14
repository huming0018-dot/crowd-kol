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
console.log('existing_saved ref limit: 6 offline assertions passed');
