import {assert} from './contract.mjs';

export async function participantHealth(payload,backend,actor){
  assert(actor==='owner','principal_denied');
  assert(payload&&typeof payload==='object'&&!Array.isArray(payload)&&Object.keys(payload).every(key=>['limit','event_limit'].includes(key)));
  for(const [key,max] of [['limit',100],['event_limit',200]])if(Object.hasOwn(payload,key))assert(Number.isSafeInteger(payload[key])&&payload[key]>=1&&payload[key]<=max);
  const response=await backend.rpc('crowd_participant_health_rpc',{p_owner_scope:'crowd-owner-main',p_actor_kind:actor,p_payload:payload});
  if(response.error)throw new Error(['principal_denied','invalid_request'].includes(response.error.message)?response.error.message:'backend_unavailable');
  return response.data;
}
