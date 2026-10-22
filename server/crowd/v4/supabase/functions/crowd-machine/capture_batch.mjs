import {assert,canonical,captureHash,hex,uuid,validateCapture} from './contract.mjs';
const schema='crowd-machine-capture-batch-result-v1';
function exact(value,keys){assert(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(k=>Object.hasOwn(value,k)));}
export async function captureBatch(payload,backend,workerHash,sanitize){
  exact(payload,['run_id','task_id','child_id','worker_id','lease_epoch','local_run_id','items']);
  assert(['run_id','task_id','child_id','worker_id','local_run_id'].every(k=>uuid(payload[k]))&&Number.isSafeInteger(payload.lease_epoch)&&payload.lease_epoch>=1);
  assert(Array.isArray(payload.items)&&payload.items.length>=1&&payload.items.length<=4);
  const ids=new Set(),captures=[];let previous=0;
  for(const item of payload.items){
    exact(item,['sequence','envelope','envelope_hash']);
    assert(Number.isSafeInteger(item.sequence)&&item.sequence>=1&&(!previous||item.sequence===previous+1));previous=item.sequence;
    validateCapture(item.envelope);
    assert(['run_id','task_id','child_id','lease_epoch'].every(k=>item.envelope[k]===payload[k])&&!ids.has(item.envelope.capture_id),'capture_hash_conflict');ids.add(item.envelope.capture_id);
    assert(hex(item.envelope_hash)&&await captureHash(item.envelope)===item.envelope_hash,'capture_hash_conflict');
    captures.push({run_id:payload.run_id,lease_epoch:payload.lease_epoch,envelope:item.envelope,envelope_hash:item.envelope_hash,canonical_envelope:canonical(item.envelope)});
  }
  const receipts=[];
  const rpc=async(action,value)=>{
    const response=await backend.rpc('crowd_machine_rpc',{p_owner_scope:'crowd-owner-main',p_actor_kind:'worker',p_worker_hash:workerHash,p_action:action,p_payload:value});
    if(response.error)throw new Error(response.error.message);return response.data;
  };
  for(let i=0;i<captures.length;i++){
    const item=payload.items[i];
    try{
      const updated=await rpc('heartbeat',{run_id:payload.run_id,lease_epoch:payload.lease_epoch,local_run_id:payload.local_run_id,sequence:item.sequence});
      const lease=updated?.lease;
      assert(lease&&['run_id','task_id','child_id','worker_id','lease_epoch'].every(k=>lease[k]===payload[k]),'lease_binding_denied');
      assert(lease.may_dispatch===true&&lease.state==='running'&&lease.desired_state==='running','cloud_delivery_lease_denied');
      const response=await rpc('capture',captures[i]);
      const receipt=response?.receipt;
      assert(receipt&&['capture_id','task_id','child_id','run_id','lease_epoch'].every(k=>receipt[k]===item.envelope[k])&&receipt.envelope_hash===item.envelope_hash&&receipt.status==='received'&&receipt.source_kind==='machine_api'&&receipt.reward_eligible===false,'invalid_cloud_ack');
      receipts.push(receipt);
    }catch(error){
      const code=['cloud_delivery_lease_denied','invalid_cloud_ack'].includes(error.message)?error.message:sanitize(error.message);
      return {schema,run_id:payload.run_id,lease_epoch:payload.lease_epoch,receipts,error:{capture_id:item.envelope.capture_id,envelope_hash:item.envelope_hash,code}};
    }
  }
  return {schema,run_id:payload.run_id,lease_epoch:payload.lease_epoch,receipts,error:null};
}
