-- Formal latest-source baseline only. Fresh live definition/attributes must match before deployment.
DO $guard$
DECLARE original_oid oid; original_acl aclitem[]; original_config text[]; original_security boolean; original_owner oid;
BEGIN
 SELECT oid,proacl,proconfig,prosecdef,proowner INTO STRICT original_oid,original_acl,original_config,original_security,original_owner FROM pg_catalog.pg_proc WHERE oid='public.crowd_machine_steps_rpc(text,text,text,text,jsonb)'::regprocedure;
 IF pg_catalog.md5(pg_catalog.pg_get_functiondef(original_oid)) IS DISTINCT FROM '65dfd220ea17878edb63fa28f3ffd2e5' OR original_acl::text IS DISTINCT FROM '{postgres=X/postgres,service_role=X/postgres}' OR original_config IS DISTINCT FROM ARRAY['search_path=""']::text[] OR original_security IS DISTINCT FROM false OR pg_catalog.pg_get_userbyid(original_owner) IS DISTINCT FROM 'postgres' THEN RAISE EXCEPTION 'machine_steps_baseline_changed'; END IF;
 EXECUTE $replacement$CREATE OR REPLACE FUNCTION public.crowd_machine_steps_rpc(p_owner_scope text, p_actor_kind text, p_worker_hash text, p_action text, p_payload jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare w crowd_machine.workers; e jsonb; old crowd_machine.step_events; accepted jsonb:='[]'; r uuid; ep integer; seq bigint; eid uuid;
begin
 if p_owner_scope is distinct from 'crowd-owner-main' or jsonb_typeof(p_payload) is distinct from 'object' then raise exception 'principal_denied'; end if;
 if p_actor_kind='owner' and p_action='machine_events' then
  if (p_payload-array['limit','after_id','run_id'])<>'{}'::jsonb
   or coalesce(p_payload->>'limit','100') !~ '^[0-9]{1,3}$'
   or (p_payload->>'limit')::integer not between 1 and 200
   or coalesce(p_payload->>'after_id','0') !~ '^[0-9]{1,16}$'
   then raise exception 'invalid_step_events'; end if;
  return jsonb_build_object('schema','crowd-machine-step-events-v1','events',coalesce((select jsonb_agg(to_jsonb(q) order by q.id) from (
   select s.id,s.worker_id,s.run_id,s.lease_epoch,s.event_id,s.sequence,s.event,s.received_at,c.child_id,ch.task_id
   from crowd_machine.step_events s join crowd_machine.workers mw using(worker_id)
   join crowd_machine.claims c on c.worker_id=s.worker_id and c.run_id=s.run_id and c.lease_epoch=s.lease_epoch
   join crowd_machine.children ch on ch.child_id=c.child_id
   where mw.owner_scope=p_owner_scope and s.id>coalesce((p_payload->>'after_id')::bigint,0)
    and (p_payload->>'run_id' is null or s.run_id=(p_payload->>'run_id')::uuid)
   order by case when p_payload ? 'after_id' then s.id else -s.id end limit coalesce((p_payload->>'limit')::integer,100)) q),'[]'::jsonb));
 end if;
 if p_actor_kind is distinct from 'worker' or p_action is distinct from 'step_events' then raise exception 'principal_denied'; end if;
 select * into w from crowd_machine.workers where owner_scope=p_owner_scope and token_hash=p_worker_hash for update;
 if not found then raise exception 'principal_denied'; end if;
 if not w.enabled or w.expires_at<=clock_timestamp() then raise exception 'worker_revoked'; end if;
 if (p_payload-array['events'])<>'{}'::jsonb or jsonb_typeof(p_payload->'events') is distinct from 'array'
 or jsonb_array_length(p_payload->'events') not between 1 and 50 or octet_length(p_payload::text)>100000 then raise exception 'invalid_step_events'; end if;
 for e in select value from jsonb_array_elements(p_payload->'events') loop
  if jsonb_typeof(e) is distinct from 'object' or (e-array['error_code','exit_code','source_sequence','source_stage','api_attempts','http_status','page_sha256','scope','checkpoint_committed','page_index','outcome','sequence','observed_at_ms','event_id','run_id','lease_epoch','phase','local_run_id','saved_pages','saved_rows','acknowledged','pending'])<>'{}'::jsonb
   or coalesce(e->>'phase','') not in ('claiming','authorized','dispatching','running','importing','delivering','finishing','waiting_login','login_resumed','paused','completed','deferring_delivery','reconciling_no_dispatch','local_stop_unknown','comments_page','source_step')
   or coalesce(e->>'sequence','') !~ '^[1-9][0-9]{0,15}$' or coalesce(e->>'lease_epoch','') !~ '^[1-9][0-9]{0,8}$'
   or coalesce(e->>'observed_at_ms','') !~ '^[0-9]{1,16}$' or (e->>'observed_at_ms')::bigint>extract(epoch from clock_timestamp())*1000+300000
   then raise exception 'invalid_step_events'; end if;
  if not (e ?& array['sequence','observed_at_ms','event_id','run_id','lease_epoch','phase']) then raise exception 'invalid_step_events'; end if;
  for seq in 1..4 loop
   if e ? (array['saved_pages','saved_rows','acknowledged','pending'])[seq] then
    if jsonb_typeof(e->(array['saved_pages','saved_rows','acknowledged','pending'])[seq]) is distinct from 'number'
     or coalesce(e->>(array['saved_pages','saved_rows','acknowledged','pending'])[seq],'') !~ '^[0-9]{1,10}$'
     or (e->>(array['saved_pages','saved_rows','acknowledged','pending'])[seq])::bigint>1000000000 then raise exception 'invalid_step_events'; end if;
   end if;
  end loop;
  if e->>'phase'='comments_page' and (coalesce(e->>'page_sha256','') !~ '^[a-f0-9]{64}$' or coalesce(e->>'scope','') not in ('root','reply') or jsonb_typeof(e->'checkpoint_committed') is distinct from 'boolean' or coalesce(e->>'page_index','') !~ '^[1-9][0-9]{0,8}$') then raise exception 'invalid_step_events'; end if;
  if e ?| array['error_code','exit_code'] and (
    e->>'phase' not in ('importing','delivering','finishing','completed','waiting_login','paused')
    or jsonb_typeof(e->'error_code') is distinct from 'string'
    or coalesce(e->>'error_code','') not in ('login_required','native_provider_browser_unavailable','native_provider_busy','native_provider_cleanup_unknown','native_provider_cookie_scope_invalid','native_provider_cookie_shape_invalid','native_provider_credentials_unavailable','native_provider_exit_observer_unavailable','native_provider_lock_invalid','native_provider_mc_missing','native_provider_ownership_lost','native_provider_persistence_unavailable','native_provider_profile_busy','native_provider_profile_invalid','native_provider_profile_missing','native_provider_profile_mode_unverified','native_provider_retry_forbidden','native_provider_session_invalid','native_provider_unavailable','phase_observation_failed','pro_account_changed','pro_bili_wbi_unavailable','pro_content_access_denied','pro_cookiebridge_unavailable','pro_existing_cdp_credentials_unavailable','pro_login_verification_failed','pro_native_credentials_unavailable','pro_self_check_unsupported','pro_signer_source_changed','pro_signer_wrapper_changed','pro_weibo_reply_target_invalid','run_completed','run_failure_unclassified','run_outcome_unknown','run_stopped','wb_checkpoint_binding','wb_checkpoint_unconfirmed','wb_comment_identity_invalid','wb_comment_limit_state_invalid','wb_comment_parent_invalid','wb_comment_replayed','wb_cursor_stalled','wb_embedded_replies_incomplete','wb_operation_unsupported','wb_page_budget','wb_page_budget_invalid','wb_page_cursor_invalid','wb_page_evidence_limit','wb_page_file_binding','wb_page_file_invalid','wb_partial_page_requires_resolution','wb_protocol_mapping_conflict','wb_reply_business_code_invalid','wb_reply_count_invalid','wb_reply_cursor_invalid','wb_reply_cursor_stalled','wb_reply_http_invalid','wb_reply_nested_shape_unverified','wb_reply_page_budget','wb_reply_page_shape_invalid','wb_reply_parent_invalid','wb_reply_target_invalid','wb_reply_target_unbound','wb_reply_terminal_incomplete','wb_reply_transport_contract_invalid','wb_resume_cursor_type_unverified','wb_save_failed','wb_save_not_durable','xhs_manager_changed','xhs_manager_import_changed','xhs_media_budget_exhausted','xhs_media_context_changed','xhs_media_guard_failed','xhs_media_http_rejected','xhs_media_http_status','xhs_media_length_mismatch','xhs_media_output_exists','xhs_media_output_invalid','xhs_media_size_invalid','xhs_media_stopped','xhs_media_stream_invalid','xhs_media_timeout','xhs_media_transport_failed','xhs_media_transport_timeout','xhs_media_type_invalid','xhs_media_unknown_failure')
    or (e ? 'exit_code' and (jsonb_typeof(e->'exit_code') is distinct from 'number' or coalesce(e->>'exit_code','') !~ '^-?[0-9]{1,3}$' or (e->>'exit_code')::integer not between -128 and 255))
  ) then raise exception 'invalid_step_events'; end if;
  if e->>'phase'<>'source_step' and e ?| array['source_sequence','source_stage','api_attempts','http_status'] then raise exception 'invalid_step_events'; end if;
  if e->>'phase' not in ('source_step','comments_page') and e ? 'scope' then raise exception 'invalid_step_events'; end if;
  if e->>'phase'='source_step' and (
    coalesce(e->>'source_stage','') not in ('request_started','response_received','request_failed','page_received','page_saved','page_partially_saved','content_saved','store_failed','monitor_failed')
    or coalesce(e->>'scope','') not in ('request','content','root','reply')
    or jsonb_typeof(e->'source_sequence') is distinct from 'number' or coalesce(e->>'source_sequence','') !~ '^[1-9][0-9]{0,3}$' or (e->>'source_sequence')::integer>4000
    or jsonb_typeof(e->'api_attempts') is distinct from 'number' or coalesce(e->>'api_attempts','') !~ '^[0-9]{1,3}$' or (e->>'api_attempts')::integer>500
    or jsonb_typeof(e->'http_status') is distinct from 'number' or coalesce(e->>'http_status','') !~ '^[0-9]{1,3}$' or (e->>'http_status')::integer>599
    or (e->>'source_stage'='page_partially_saved' and e->>'scope' not in ('root','reply'))
    or e->'checkpoint_committed' is distinct from 'false'::jsonb
    or (e ? 'page_sha256' and coalesce(e->>'page_sha256','') !~ '^[a-f0-9]{64}$')
    or (e->>'source_stage' in ('page_saved','page_partially_saved','content_saved') and (not (e ?& array['page_sha256','saved_rows']) ))
    or (e->>'source_stage'='page_partially_saved' and (e->>'saved_rows')::bigint<1)
   ) then raise exception 'invalid_step_events'; end if;
  if e ? 'outcome' and coalesce(e->>'outcome','') not in ('completed','failed','stopped','unknown','login_required') then raise exception 'invalid_step_events'; end if;
  r:=(e->>'run_id')::uuid; ep:=(e->>'lease_epoch')::integer; seq:=(e->>'sequence')::bigint; eid:=(e->>'event_id')::uuid;
  if not exists(select 1 from crowd_machine.claims c where c.worker_id=w.worker_id and c.run_id=r and c.lease_epoch=ep
    and (e->>'local_run_id' is null or c.local_run_id=(e->>'local_run_id')::uuid)) then raise exception 'lease_binding_denied'; end if;
  select * into old from crowd_machine.step_events where worker_id=w.worker_id and (event_id=eid or (run_id=r and lease_epoch=ep and sequence=seq));
  if found then
   if old.event_id<>eid or old.run_id<>r or old.lease_epoch<>ep or old.sequence<>seq or old.event<>e then raise exception 'step_event_conflict'; end if;
  else
   insert into crowd_machine.step_events(worker_id,run_id,lease_epoch,event_id,sequence,event) values(w.worker_id,r,ep,eid,seq,e);
  end if;
  accepted:=accepted||jsonb_build_array(eid);
 end loop;
 return jsonb_build_object('schema','crowd-machine-step-events-v1','event_ids',accepted);
end $function$
;
$replacement$;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc WHERE oid=original_oid AND proacl IS NOT DISTINCT FROM original_acl AND proconfig IS NOT DISTINCT FROM original_config AND prosecdef IS NOT DISTINCT FROM original_security AND proowner=original_owner AND pg_catalog.md5(pg_catalog.pg_get_functiondef(oid))='e1f94ee7eb2632d2cbde945f86f0fe09') THEN RAISE EXCEPTION 'machine_steps_postcondition_failed'; END IF;
END $guard$;
