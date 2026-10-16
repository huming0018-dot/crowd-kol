import {assert,uuid} from './contract.mjs';
export const phases=['claiming','authorized','dispatching','running','importing','delivering','finishing','waiting_login','login_resumed','paused','completed','deferring_delivery','reconciling_no_dispatch','local_stop_unknown','comments_page','source_step'];
export const diagnosticCodes=["login_required", "native_provider_browser_unavailable", "native_provider_busy", "native_provider_cleanup_unknown", "native_provider_cookie_scope_invalid", "native_provider_cookie_shape_invalid", "native_provider_credentials_unavailable", "native_provider_exit_observer_unavailable", "native_provider_lock_invalid", "native_provider_mc_missing", "native_provider_ownership_lost", "native_provider_persistence_unavailable", "native_provider_profile_busy", "native_provider_profile_invalid", "native_provider_profile_missing", "native_provider_profile_mode_unverified", "native_provider_retry_forbidden", "native_provider_session_invalid", "native_provider_unavailable", "phase_observation_failed", "pro_account_changed", "pro_bili_wbi_unavailable", "pro_content_access_denied", "pro_cookiebridge_unavailable", "pro_existing_cdp_credentials_unavailable", "pro_login_verification_failed", "pro_native_credentials_unavailable", "pro_self_check_unsupported", "pro_signer_source_changed", "pro_signer_wrapper_changed", "pro_weibo_reply_target_invalid", "run_completed", "run_failure_unclassified", "run_outcome_unknown", "run_stopped", "wb_checkpoint_binding", "wb_checkpoint_unconfirmed", "wb_comment_identity_invalid", "wb_comment_limit_state_invalid", "wb_comment_parent_invalid", "wb_comment_replayed", "wb_cursor_stalled", "wb_embedded_replies_incomplete", "wb_operation_unsupported", "wb_page_budget", "wb_page_budget_invalid", "wb_page_cursor_invalid", "wb_page_evidence_limit", "wb_page_file_binding", "wb_page_file_invalid", "wb_partial_page_requires_resolution", "wb_protocol_mapping_conflict", "wb_reply_business_code_invalid", "wb_reply_count_invalid", "wb_reply_cursor_invalid", "wb_reply_cursor_stalled", "wb_reply_http_invalid", "wb_reply_nested_shape_unverified", "wb_reply_page_budget", "wb_reply_page_shape_invalid", "wb_reply_parent_invalid", "wb_reply_target_invalid", "wb_reply_target_unbound", "wb_reply_terminal_incomplete", "wb_reply_transport_contract_invalid", "wb_resume_cursor_type_unverified", "wb_save_failed", "wb_save_not_durable"];
const diagnosticPhases=['importing','delivering','finishing','completed','waiting_login','paused'];
export async function machineSteps(action,payload,backend,actor,workerHash){
  assert(payload&&typeof payload==='object'&&!Array.isArray(payload),'invalid_step_events');
  if(action==='step_events'){
    assert(actor==='worker','principal_denied');
    assert(Object.keys(payload).length===1&&Array.isArray(payload.events)&&payload.events.length>=1&&payload.events.length<=50,'invalid_step_events');
    const ids=new Set();
    for(const e of payload.events){
      assert(e&&typeof e==='object'&&!Array.isArray(e)&&Object.keys(e).every(k=>['error_code','exit_code','source_sequence','source_stage','api_attempts','http_status','page_sha256','scope','checkpoint_committed','page_index','outcome','sequence','observed_at_ms','event_id','run_id','lease_epoch','phase','local_run_id','saved_pages','saved_rows','acknowledged','pending'].includes(k)),'invalid_step_events');
      assert(Number.isSafeInteger(e.sequence)&&e.sequence>=1&&Number.isSafeInteger(e.observed_at_ms)&&e.observed_at_ms>=0&&e.observed_at_ms<=Date.now()+300000&&uuid(e.event_id)&&uuid(e.run_id)&&Number.isSafeInteger(e.lease_epoch)&&e.lease_epoch>=1&&phases.includes(e.phase)&&!ids.has(e.event_id),'invalid_step_events');ids.add(e.event_id);
      if(Object.hasOwn(e,'error_code')||Object.hasOwn(e,'exit_code'))assert(diagnosticPhases.includes(e.phase)&&typeof e.error_code==='string'&&diagnosticCodes.includes(e.error_code)&&(!Object.hasOwn(e,'exit_code')||Number.isSafeInteger(e.exit_code)&&e.exit_code>=-128&&e.exit_code<=255),'invalid_step_events');
      if(e.phase!=='source_step')assert(!['source_sequence','source_stage','api_attempts','http_status'].some(k=>Object.hasOwn(e,k)),'invalid_step_events');
      if(!['source_step','comments_page'].includes(e.phase))assert(!Object.hasOwn(e,'scope'),'invalid_step_events');
      if(e.phase==='source_step'){
        assert(['request_started','response_received','request_failed','page_received','page_saved','page_partially_saved','content_saved','store_failed','monitor_failed'].includes(e.source_stage)&&['request','content','root','reply'].includes(e.scope),'invalid_step_events');
        assert(Number.isSafeInteger(e.source_sequence)&&e.source_sequence>=1&&e.source_sequence<=4000&&Number.isSafeInteger(e.api_attempts)&&e.api_attempts>=0&&e.api_attempts<=500&&Number.isSafeInteger(e.http_status)&&e.http_status>=0&&e.http_status<=599&&e.checkpoint_committed===false,'invalid_step_events');
        if(Object.hasOwn(e,'page_sha256'))assert(typeof e.page_sha256==='string'&&/^[a-f0-9]{64}$/.test(e.page_sha256),'invalid_step_events');
        if(e.source_stage==='page_partially_saved')assert(['root','reply'].includes(e.scope),'invalid_step_events');
        if(['page_saved','page_partially_saved','content_saved'].includes(e.source_stage))assert(Object.hasOwn(e,'page_sha256')&&Object.hasOwn(e,'saved_rows'),'invalid_step_events');
        if(e.source_stage==='page_partially_saved')assert(e.saved_rows>=1,'invalid_step_events');
      }
      if(e.phase==='comments_page')assert(typeof e.page_sha256==='string'&&/^[a-f0-9]{64}$/.test(e.page_sha256)&&['root','reply'].includes(e.scope)&&typeof e.checkpoint_committed==='boolean'&&Number.isSafeInteger(e.page_index)&&e.page_index>=1,'invalid_step_events');
      if(Object.hasOwn(e,'outcome'))assert(['completed','failed','stopped','unknown','login_required'].includes(e.outcome),'invalid_step_events');
      if(Object.hasOwn(e,'local_run_id'))assert(uuid(e.local_run_id),'invalid_step_events');
      for(const k of ['saved_pages','saved_rows','acknowledged','pending','page_index'])if(Object.hasOwn(e,k))assert(Number.isSafeInteger(e[k])&&e[k]>=0&&e[k]<=1e9,'invalid_step_events');
    }
  }else{
    assert(actor==='owner','principal_denied');
    assert(Object.keys(payload).every(k=>['limit','after_id','run_id'].includes(k)),'invalid_step_events');
    if(Object.hasOwn(payload,'limit'))assert(Number.isSafeInteger(payload.limit)&&payload.limit>=1&&payload.limit<=200,'invalid_step_events');
    if(Object.hasOwn(payload,'after_id'))assert(Number.isSafeInteger(payload.after_id)&&payload.after_id>=0,'invalid_step_events');
    if(Object.hasOwn(payload,'run_id'))assert(uuid(payload.run_id),'invalid_step_events');
  }
  const result=await backend.rpc('crowd_machine_steps_rpc',{p_owner_scope:'crowd-owner-main',p_actor_kind:actor,p_worker_hash:workerHash,p_action:action,p_payload:payload});
  if(result.error)throw new Error(['principal_denied','worker_revoked','lease_binding_denied','step_event_conflict','invalid_step_events'].includes(result.error.message)?result.error.message:'backend_unavailable');
  return result.data;
}
