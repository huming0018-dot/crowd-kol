-- Read-only production function snapshot, 2026-10-14. No credentials or participant data.
CREATE OR REPLACE FUNCTION public.crowd_v4_diagnostics(p_action text, p_revision bigint, p_state jsonb DEFAULT NULL::jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare u uuid:=auth.uid(); p crowd_v4.participants; d crowd_v4.diagnostics; stamp timestamptz:=now(); field text; event jsonb;
begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 select * into p from crowd_v4.participants where user_id=u for update;
 if p.user_id is null or p.consent<>'crowd-public-v4' then raise exception 'approval_required' using errcode='42501'; end if;
 if p_revision is null or p_revision<1 or p_revision>9007199254740991 or p_action is null or p_action not in ('enable','disable','report') then raise exception 'invalid_diagnostics'; end if;
 select * into d from crowd_v4.diagnostics where user_id=u;
 if p_action in ('enable','disable') then
  if p_state is not null then raise exception 'invalid_diagnostics'; end if;
  if p_action='enable' and p.status<>'approved' then raise exception 'approval_required' using errcode='42501'; end if;
  if d.user_id is not null and (p_revision<d.revision or (p_revision=d.revision and d.enabled is distinct from (p_action='enable'))) then raise exception 'stale_diagnostics'; end if;
  insert into crowd_v4.diagnostics(user_id,enabled,revision,state,updated_at) values(u,p_action='enable',p_revision,null,stamp)
  on conflict(user_id) do update set enabled=excluded.enabled,revision=excluded.revision,
    state=case when excluded.enabled then crowd_v4.diagnostics.state else null end,updated_at=stamp;
  return jsonb_build_object('enabled',p_action='enable','cleared',p_action='disable');
 end if;
 if d.user_id is null or not d.enabled or d.revision<>p_revision then raise exception 'stale_diagnostics'; end if;
 if p.status<>'approved' then raise exception 'approval_required' using errcode='42501'; end if;
 if jsonb_typeof(p_state) is distinct from 'object' or octet_length(p_state::text)>8192
 or not (p_state ?& array['version','enabled','phase','error','task_id','queued','rejected','page_kind','tab_status','document','gate','links','search_note_links','body_chars','visible'])
 or exists(select 1 from jsonb_object_keys(p_state) k where k<>all(array['ota_last_poll_at','ota_poll_status','ota_poll_error','ota_poll_query_error','version','enabled','phase','error','task_id','queued','rejected','page_kind','tab_status','document','gate','links','search_note_links','body_chars','visible','nav_stage','nav_error','nav_age_s','probe_status','prev_nav_stage','prev_nav_error','prev_nav_age_s','page_failures','last_tick_age_s','next_in_s','document_kind','pending_kind','probe_error','trace','update_state','updater_enabled','auto_test_enabled','kol','pool_failure']))
 or jsonb_typeof(p_state->'version') is distinct from 'string' or coalesce(p_state->>'version','') !~ '^4\.[0-9]{1,3}\.[0-9]{1,3}$'
 or jsonb_typeof(p_state->'enabled') is distinct from 'boolean'
 or coalesce(p_state->>'phase','') not in ('idle','search','search_done','note','reopen_note','enrich','parallel')
 or coalesce(p_state->>'page_kind','') not in ('search','note','other','unknown','missing')
 or coalesce(p_state->>'tab_status','') not in ('loading','complete','discarded','missing','no_content')
 or coalesce(p_state->>'document','') not in ('loading','interactive','complete','unknown')
 or jsonb_typeof(p_state->'visible') not in ('boolean','null')
 or jsonb_typeof(p_state->'error') not in ('string','null')
 or (p_state->>'error' is not null and p_state->>'error' not in ('page_timeout','page_loading','navigation_failed','navigation_uncommitted','content_unavailable','probe_timeout','page_mismatch','wrong_note','login_required','backend_login_required','user_login','captcha','rate_limit','approval_required','consent_required','user_stopped','logged_out','system_suspended','lease_lost','daily_quota','review_local_rejections','backend_unavailable','control_unavailable','global_pause','action_budget','action_gap','session_rest','known_note','note_busy','invalid_receipt','unexpected_error','test_completed','test_comments_partial','test_expired','test_quota','test_no_task','test_partial','test_new_run_required','parallel_unavailable','pool_recovery_required','executor_busy','update_in_progress','cancelled'))
 or jsonb_typeof(p_state->'gate') not in ('string','null')
 or (p_state->>'gate' is not null and p_state->>'gate' not in ('login_required','captcha','rate_limit'))
 or jsonb_typeof(p_state->'task_id') not in ('number','null')
 or (p_state->>'task_id' is not null and coalesce(p_state->>'task_id','') !~ '^[1-9][0-9]{0,15}$')
 then raise exception 'invalid_diagnostics'; end if;
 if (p_state ? 'nav_stage' and (jsonb_typeof(p_state->'nav_stage') is distinct from 'string' or coalesce(p_state->>'nav_stage','') not in ('unknown','started','committed','dom_ready','complete','failed')))
 or (p_state ? 'probe_status' and (jsonb_typeof(p_state->'probe_status') is distinct from 'string' or coalesce(p_state->>'probe_status','') not in ('unknown','ok','no_receiver','timed_out')))
 or (p_state ? 'nav_error' and (jsonb_typeof(p_state->'nav_error') not in ('string','null') or (p_state->>'nav_error' is not null and p_state->>'nav_error' not in ('ERR_NAME_NOT_RESOLVED','ERR_INTERNET_DISCONNECTED','ERR_CONNECTION_TIMED_OUT','ERR_TIMED_OUT','ERR_CONNECTION_RESET','ERR_CONNECTION_REFUSED','ERR_CONNECTION_CLOSED','ERR_ADDRESS_UNREACHABLE','ERR_NETWORK_CHANGED','ERR_TUNNEL_CONNECTION_FAILED','ERR_PROXY_CONNECTION_FAILED','ERR_CERT_AUTHORITY_INVALID','ERR_CERT_DATE_INVALID','ERR_SSL_PROTOCOL_ERROR','ERR_BLOCKED_BY_CLIENT','ERR_BLOCKED_BY_ADMINISTRATOR','ERR_ABORTED','OTHER'))))
 or (p_state ? 'nav_age_s' and jsonb_typeof(p_state->'nav_age_s') <> 'null' and (jsonb_typeof(p_state->'nav_age_s') is distinct from 'number' or coalesce(p_state->>'nav_age_s','') !~ '^[0-9]{1,5}$'))
 then raise exception 'invalid_diagnostics'; end if;
 if p_state->>'nav_age_s' is not null and (p_state->>'nav_age_s')::int > 86400 then raise exception 'invalid_diagnostics'; end if;
 foreach field in array array['queued','rejected','links','search_note_links','body_chars'] loop
  if jsonb_typeof(p_state->field) is distinct from 'number' or coalesce(p_state->>field,'') !~ '^[0-9]{1,5}$' then raise exception 'invalid_diagnostics'; end if;
 end loop;
 if (p_state->>'links')::int>500 or (p_state->>'search_note_links')::int>500 or (p_state->>'body_chars')::int>24000 then raise exception 'invalid_diagnostics'; end if;

 if p_state ? 'prev_nav_stage' and (jsonb_typeof(p_state->'prev_nav_stage') is distinct from 'string' or p_state->>'prev_nav_stage' not in ('unknown','started','committed','dom_ready','complete','failed')) then raise exception 'invalid_diagnostics'; end if;
 if p_state ? 'prev_nav_error' and (jsonb_typeof(p_state->'prev_nav_error') not in ('string','null') or (p_state->>'prev_nav_error' is not null and p_state->>'prev_nav_error' not in ('ERR_NAME_NOT_RESOLVED','ERR_INTERNET_DISCONNECTED','ERR_CONNECTION_TIMED_OUT','ERR_TIMED_OUT','ERR_CONNECTION_RESET','ERR_CONNECTION_REFUSED','ERR_CONNECTION_CLOSED','ERR_ADDRESS_UNREACHABLE','ERR_NETWORK_CHANGED','ERR_TUNNEL_CONNECTION_FAILED','ERR_PROXY_CONNECTION_FAILED','ERR_CERT_AUTHORITY_INVALID','ERR_CERT_DATE_INVALID','ERR_SSL_PROTOCOL_ERROR','ERR_BLOCKED_BY_CLIENT','ERR_BLOCKED_BY_ADMINISTRATOR','ERR_ABORTED','OTHER'))) then raise exception 'invalid_diagnostics'; end if;
 foreach field in array array['prev_nav_age_s','last_tick_age_s','next_in_s','page_failures'] loop
  if p_state ? field and jsonb_typeof(p_state->field) <> 'null' then
   if jsonb_typeof(p_state->field) is distinct from 'number' or coalesce(p_state->>field,'') !~ '^[0-9]{1,5}$' then raise exception 'invalid_diagnostics'; end if;
   if (p_state->>field)::int > (case when field='page_failures' then 3 else 86400 end) then raise exception 'invalid_diagnostics'; end if;
  end if;
  if field in ('next_in_s','page_failures') and p_state ? field and jsonb_typeof(p_state->field) = 'null' then raise exception 'invalid_diagnostics'; end if;
 end loop;

 if p_state ? 'document_kind' and (jsonb_typeof(p_state->'document_kind') is distinct from 'string' or p_state->>'document_kind' not in ('blank','platform','other','unavailable')) then raise exception 'invalid_diagnostics'; end if;
 if p_state ? 'pending_kind' and (jsonb_typeof(p_state->'pending_kind') is distinct from 'string' or p_state->>'pending_kind' not in ('none','blank','platform','other','unavailable')) then raise exception 'invalid_diagnostics'; end if;

 if p_state ? 'update_state' and (jsonb_typeof(p_state->'update_state') is distinct from 'string' or p_state->>'update_state' not in ('unknown','ready','applied','current','checking','pending_reload','helper_unavailable','error','rolled_back')) then raise exception 'invalid_diagnostics'; end if;
 if p_state ? 'trace' then
  if jsonb_typeof(p_state->'trace') is distinct from 'array' then raise exception 'invalid_diagnostics'; end if;
  if jsonb_array_length(p_state->'trace')>24 then raise exception 'invalid_diagnostics'; end if;
  for event in select value from jsonb_array_elements(p_state->'trace') loop
   if jsonb_typeof(event) is distinct from 'object' or not(event ?& array['id','stage','at']) then raise exception 'invalid_diagnostics'; end if;
   if exists(select 1 from jsonb_object_keys(event) k where k<>all(array['ota_last_poll_at','ota_poll_status','ota_poll_error','ota_poll_query_error','id','stage','at']))
   or jsonb_typeof(event->'id') is distinct from 'string' or coalesce(event->>'id','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   or jsonb_typeof(event->'stage') is distinct from 'string' or event->>'stage' not in ('worker_started','admission_requested','admission_allowed','admission_denied','open_requested','tab_created','tab_reused','update_accepted','update_failed','nav_started','nav_committed','nav_dom_ready','nav_complete','nav_failed','probe_ready','probe_missing','probe_timeout','navigation_timeout','submit_requested','submit_accepted','submit_rejected','submit_failed')
   or jsonb_typeof(event->'at') is distinct from 'number' or coalesce(event->>'at','') !~ '^[0-9]{1,10}$' then raise exception 'invalid_diagnostics'; end if;
   if (event->>'at')::bigint>4102444800 then raise exception 'invalid_diagnostics'; end if;
  end loop;
 end if;

 if p_state ? 'kol' then
  event:=p_state->'kol';
  if jsonb_typeof(event) is distinct from 'object' then raise exception 'invalid_kol_diagnostics'; end if;
  if not(event ?& array['enabled','phase','error','platform','queued','rejected','received','attempts','checkpoint_revision','delivery_paused','next_in_s'])
   or (event-array['enabled','phase','error','platform','queued','rejected','received','attempts','checkpoint_revision','delivery_paused','next_in_s'])<>'{}'::jsonb
   or jsonb_typeof(event->'enabled') is distinct from 'boolean'
   or jsonb_typeof(event->'delivery_paused') is distinct from 'boolean'
   or jsonb_typeof(event->'phase') is distinct from 'string'
   or event->>'phase' not in ('idle','open','discover','next','detail','comments','comment_read','finish','resume_detail','resume_listing','discovery_scroll')
   or jsonb_typeof(event->'platform') not in ('string','null')
   or (event->>'platform' is not null and event->>'platform' not in ('xiaohongshu','bilibili'))
   or jsonb_typeof(event->'error') not in ('string','null')
   or (event->>'error' is not null and event->>'error' not in ('navigation_failed','navigation_uncommitted','page_timeout','page_loading','content_unavailable','probe_timeout','page_mismatch','wrong_note','login_required','backend_login_required','user_login','captcha','rate_limit','approval_required','consent_required','user_stopped','logged_out','system_suspended','lease_lost','daily_quota','review_local_rejections','backend_unavailable','control_unavailable','global_pause','action_budget','action_gap','session_rest','known_note','note_busy','invalid_receipt','source_outcome_unknown','executor_busy','executor_released','delivery_retry_exhausted','identity_verification_required','platform_session_changed','checkpoint_conflict','old_outbox_pending','unknown_source_outcome','delivery_retry_limit','platform_identity_changed','old_executor_required','checkpoint_gap','lease_expired','unknown_delivery_history','checkpoint_regression','invalid_checkpoint','legacy_executor_required','explicit_recovery_required','lease_expired_requires_release','recovery_not_supported','outbox_not_drained','pending_identity_delivery','comment_page_budget','content_already_received','source_not_found','source_private','source_deleted','parser_paused','invalid_overlap_window','incomplete_window_outside_authorization','scan_window_blocked','unexpected_error'))
   then raise exception 'invalid_kol_diagnostics';end if;
  foreach field in array array['queued','rejected','received','attempts','checkpoint_revision','next_in_s'] loop
   if jsonb_typeof(event->field) is distinct from 'number' or coalesce(event->>field,'') !~ '^[0-9]{1,5}$' then raise exception 'invalid_kol_diagnostics';end if;
  end loop;
  if (event->>'next_in_s')::int>86400 then raise exception 'invalid_kol_diagnostics';end if;
 end if;

 if p_state ? 'pool_failure' and (jsonb_typeof(p_state->'pool_failure') is distinct from 'string' or p_state->>'pool_failure' not in ('entry_state','tab_missing','tab_discarded','url_changed','token_changed','document_changed','unbound_restart','bind_failed','presentation_identity','close_identity','unknown')) then raise exception 'invalid_diagnostics'; end if;

 if p_state ? 'probe_error' and (jsonb_typeof(p_state->'probe_error') is distinct from 'string' or p_state->>'probe_error' not in ('unknown','none','no_receiver','empty_response','port_closed','tab_missing','access_denied','timed_out','message_failed')) then raise exception 'invalid_diagnostics'; end if;

 foreach field in array array['updater_enabled','auto_test_enabled'] loop
  if p_state ? field and jsonb_typeof(p_state->field) is distinct from 'boolean' then raise exception 'invalid_diagnostics'; end if;
 end loop;

 if p_state ? 'ota_last_poll_at' and jsonb_typeof(p_state->'ota_last_poll_at')<>'null' then
  if jsonb_typeof(p_state->'ota_last_poll_at') is distinct from 'number' or p_state->>'ota_last_poll_at' !~ '^[0-9]{1,10}$' then raise exception 'invalid_diagnostics'; end if;
  if (p_state->>'ota_last_poll_at')::bigint>4102444800 then raise exception 'invalid_diagnostics'; end if;
 end if;
 if p_state ? 'ota_poll_status' and jsonb_typeof(p_state->'ota_poll_status')<>'null' and (jsonb_typeof(p_state->'ota_poll_status') is distinct from 'string' or p_state->>'ota_poll_status' not in ('current','downloaded','pending_reload','error')) then raise exception 'invalid_diagnostics'; end if;
 if p_state ? 'ota_poll_error' and jsonb_typeof(p_state->'ota_poll_error')<>'null' and (jsonb_typeof(p_state->'ota_poll_error') is distinct from 'string' or p_state->>'ota_poll_error' not in ('invalid_signature','hash_mismatch','permission_change','replayed_release','recovery_required','busy','operation_failed','invalid_manifest','invalid_url','wrong_extension','update_failed')) then raise exception 'invalid_diagnostics'; end if;
 if p_state ? 'ota_poll_query_error' and jsonb_typeof(p_state->'ota_poll_query_error')<>'null' and (jsonb_typeof(p_state->'ota_poll_query_error') is distinct from 'string' or p_state->>'ota_poll_query_error' not in ('busy','invalid_response','helper_unavailable')) then raise exception 'invalid_diagnostics'; end if;
 update crowd_v4.diagnostics set state=p_state,updated_at=stamp where user_id=u;
 return jsonb_build_object('saved_at',stamp);
end $function$;
