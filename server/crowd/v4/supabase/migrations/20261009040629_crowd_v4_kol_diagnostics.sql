begin;
-- Optional KOL counters within the existing opt-in/latest-only snapshot.
-- No source identifiers, URLs, free-text errors, records or account credentials.
do $migration$
declare def text; validation text := $s$
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
$s$;
begin
 def:=pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure);
 if position($s$'trace','update_state'$s$ in def)=0 or position(' update crowd_v4.diagnostics set state=p_state' in def)=0 or position('invalid_kol_diagnostics' in def)>0 then raise exception 'kol_diagnostics_anchor_mismatch';end if;
 def:=replace(def,$s$'trace','update_state'$s$,$s$'trace','update_state','kol'$s$);
 def:=replace(def,' update crowd_v4.diagnostics set state=p_state',validation || ' update crowd_v4.diagnostics set state=p_state');
 execute def;
end $migration$;
commit;
