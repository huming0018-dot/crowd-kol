import {assert,canonical,hex,sha,uuid} from './contract.mjs';

// This permission renews immutable cached delivery only; it never authorizes a source start.
export async function deliveryPayload(action,payload){
  const allowed=action==='delivery_defer'?['run_id','lease_epoch','defer_id','local_run_id','outcome','api_attempts','capture_refs','manifest_hash']:['run_id','lease_epoch','manifest_hash'];
  assert(payload&&typeof payload==='object'&&!Array.isArray(payload)&&Object.keys(payload).every(k=>allowed.includes(k))&&Object.keys(payload).length===allowed.length,'invalid_delivery_manifest');
  assert(uuid(payload.run_id)&&Number.isSafeInteger(payload.lease_epoch)&&payload.lease_epoch>=1&&payload.lease_epoch<=2147483647&&hex(payload.manifest_hash),'invalid_delivery_manifest');
  if(action==='delivery_defer'){
    assert(uuid(payload.defer_id)&&(payload.local_run_id===null||uuid(payload.local_run_id))&&['completed','failed','stopped'].includes(payload.outcome)&&Number.isSafeInteger(payload.api_attempts)&&payload.api_attempts>=0&&payload.api_attempts<=500,'invalid_delivery_manifest');
    const refs=payload.capture_refs;
    assert(refs&&typeof refs==='object'&&!Array.isArray(refs)&&Object.keys(refs).length>=1&&Object.keys(refs).length<=2000&&Object.entries(refs).every(([id,hash])=>uuid(id)&&hex(hash)),'invalid_delivery_manifest');
    const body={...payload};delete body.manifest_hash;
    assert(await sha('crowd-machine-delivery-v1\n'+canonical(body))===payload.manifest_hash,'delivery_manifest_conflict');
    return {...payload,canonical_manifest:canonical(body)};
  }
  return payload;
}
