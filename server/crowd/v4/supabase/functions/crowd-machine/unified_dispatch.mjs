import {assert,taskPlan} from './contract.mjs';

export async function unifiedPlan(input){
  const proposal=await taskPlan(input);
  const candidate=proposal.delivery_basis==='live_capture'&&proposal.mode==='search'
    ?proposal.children.find(child=>child.platform==='xhs'):null;
  // Select the extension only when its existing pilot contract can provide every requested dimension.
  // Rich capture stays on the existing machine path; missing pilot targets/budgets never fall back.
  const participant=candidate&&candidate.item_quota>0&&candidate.request.comments===false&&!candidate.request.replies
    &&!candidate.request.media&&!candidate.request.wordcloud&&candidate.request.start_page===1
    &&!candidate.request.session_id&&!Object.keys(candidate.request.platform_options).length?candidate:null;
  const machines=proposal.children.filter(child=>child!==participant);
  let machine_proposal=null;
  if(machines.length){
    const request={...proposal.request,platforms:machines.map(child=>child.platform),
      desired_items:machines.reduce((total,child)=>total+child.item_quota,0),
      max_api_requests:machines.reduce((total,child)=>total+child.request_quota,0),
      idempotency_key:'unified:'+proposal.request_hash};
    for(const key of ['targets_by_platform','session_by_platform','record_refs_by_platform','platform_options_by_platform'])
      if(request[key])request[key]=Object.fromEntries(Object.entries(request[key]).filter(([platform])=>request.platforms.includes(platform)));
    assert(request.desired_items>0,'invalid_budget');
    machine_proposal=await taskPlan(request);
  }
  return {proposal,machine_proposal,participant:participant?{
    item_quota:participant.item_quota,targets:participant.request.targets,
    compatible:true
  }:null};
}

export async function unifiedDispatch(action,payload,backend,actor){
  assert(actor==='owner','principal_denied');
  if(action==='unified_dispatches'){
    assert(payload&&typeof payload==='object'&&!Array.isArray(payload)&&Object.keys(payload).every(key=>key==='idempotency_key'));
    if(Object.hasOwn(payload,'idempotency_key'))assert(typeof payload.idempotency_key==='string'&&payload.idempotency_key.length>=1&&payload.idempotency_key.length<=160&&!/[\x00-\x1f]/.test(payload.idempotency_key));
  }
  else payload=await unifiedPlan(payload);
  const response=await backend.rpc('crowd_unified_dispatch_rpc',{p_owner_scope:'crowd-owner-main',p_actor_kind:actor,p_action:action,p_payload:payload});
  if(response.error)throw new Error(['principal_denied','invalid_request','idempotency_conflict'].includes(response.error.message)?response.error.message:'backend_unavailable');
  return response.data;
}
