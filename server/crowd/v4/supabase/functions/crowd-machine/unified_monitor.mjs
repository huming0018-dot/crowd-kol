import {machineSteps} from './machine_steps.mjs';
import {assert,uuid} from './contract.mjs';

// Owner authentication is the existing crowd-machine custom key, never a participant key.
export async function unifiedMonitor(action,payload,backend,actor){
  assert(actor==='owner','principal_denied');
  const allowed=action==='node_events'?['limit','after_id','installation_id']:['limit'];
  assert(payload&&typeof payload==='object'&&!Array.isArray(payload)&&Object.keys(payload).every(k=>allowed.includes(k)));
  if(Object.hasOwn(payload,'limit'))assert(Number.isSafeInteger(payload.limit)&&payload.limit>=1&&payload.limit<=(action==='node_events'?200:100));
  if(Object.hasOwn(payload,'after_id'))assert(Number.isSafeInteger(payload.after_id)&&payload.after_id>=0);
  if(Object.hasOwn(payload,'installation_id'))assert(uuid(payload.installation_id));
  const result=await backend.rpc('crowd_unified_monitor_rpc',{p_owner_scope:'crowd-owner-main',p_actor_kind:actor,p_action:action,p_payload:payload});
  if(result.error)throw new Error(['principal_denied','invalid_request'].includes(result.error.message)?result.error.message:'backend_unavailable');
  if(action==='node_events'&&!payload.installation_id){
    try{const machine=await machineSteps('machine_events',{limit:200},backend,actor,null);return {...result.data,machine_events:machine.events,machine_events_error:null};}
    catch(_error){return {...result.data,machine_events:[],machine_events_error:'machine_steps_read_failed'};}
  }
  return result.data;
}
