-- Read-only production definitions captured 2026-10-14 Asia/Shanghai.
-- Used only by isolated tests; no migration or production mutation.
CREATE OR REPLACE FUNCTION crowd_v4.participant_health_error(value text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO ''
AS $function$
 select case when value is null then null when value=any(array[
 'page_timeout','page_loading','navigation_failed','navigation_uncommitted','content_unavailable','probe_timeout','page_mismatch','wrong_note','login_required','backend_login_required','user_login','captcha','rate_limit','approval_required','consent_required','user_stopped','logged_out','system_suspended','lease_lost','daily_quota','review_local_rejections','backend_unavailable','control_unavailable','global_pause','action_budget','action_gap','session_rest','known_note','note_busy','invalid_receipt','unexpected_error','test_completed','test_comments_partial','test_expired','test_quota','test_no_task','test_partial','test_new_run_required','parallel_unavailable','pool_recovery_required','executor_busy','update_in_progress','cancelled','source_outcome_unknown','executor_released','delivery_retry_exhausted','identity_verification_required','platform_session_changed','checkpoint_conflict','old_outbox_pending','unknown_source_outcome','delivery_retry_limit','platform_identity_changed','old_executor_required','checkpoint_gap','lease_expired','unknown_delivery_history','checkpoint_regression','invalid_checkpoint','legacy_executor_required','explicit_recovery_required','lease_expired_requires_release','recovery_not_supported','outbox_not_drained','pending_identity_delivery','comment_page_budget','content_already_received','source_not_found','source_private','source_deleted','parser_paused','invalid_overlap_window','incomplete_window_outside_authorization','scan_window_blocked'
 ]) then value else 'unexpected_error' end;
$function$
;

CREATE OR REPLACE FUNCTION public.crowd_v4_step_events(p_installation uuid, p_events jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare u uuid:=auth.uid(); n crowd_v4.nodes; e jsonb; old crowd_v4.node_step_events; k text; v jsonb;
 accepted jsonb:='[]'; duplicates jsonb:='[]'; discarded jsonb:='[]'; opted boolean; seq bigint; eid uuid; rid uuid;
begin
 if u is null then raise exception 'login_required'; end if;
 perform 1 from crowd_v4.participants where user_id=u and consent='crowd-public-v4' for update;
 if not found then raise exception 'consent_required'; end if;
 select * into n from crowd_v4.nodes where installation_id=p_installation and user_id=u for update;
 if not found then raise exception 'node_binding_denied'; end if;
 if jsonb_typeof(p_events) is distinct from 'array' or jsonb_array_length(p_events)>50 or octet_length(p_events::text)>100000 then raise exception 'invalid_events'; end if;
 select coalesce((select enabled from crowd_v4.diagnostics where user_id=u),false) into opted;
 if not opted then
  return jsonb_build_object('schema','crowd-step-events-v1','accepted','[]'::jsonb,'duplicates','[]'::jsonb,'diagnostics_enabled',false,'discard',true,'max_node_seq',n.max_node_seq);
 end if;
 -- Serializes only bounded telemetry writes/pruning, never source actions or receipt writes.
 perform pg_advisory_xact_lock(713249121);
 for e in select value from jsonb_array_elements(p_events) loop
  if jsonb_typeof(e) is distinct from 'object' or octet_length(e::text)>2048
   or (e-array['event_id','node_seq','run_id','step','status','at_ms','duration_ms','error_code','counts'])<>'{}'::jsonb
   or not(e ?& array['event_id','node_seq','run_id','step','status','at_ms','duration_ms','error_code'])
   or coalesce(e->>'event_id','') !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
   or (e->>'run_id' is not null and e->>'run_id' !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')
   or jsonb_typeof(e->'node_seq') is distinct from 'number' or coalesce(e->>'node_seq','') !~ '^[0-9]{1,16}$'
   or jsonb_typeof(e->'at_ms') is distinct from 'number' or coalesce(e->>'at_ms','') !~ '^[0-9]{1,13}$'
   or coalesce(e->>'step','') not in ('claim','session','navigation','list','detail','comments','media','subtitle','outbox','upload','receipt','stop','ota','telemetry_gap')
   or coalesce(e->>'status','') not in ('started','completed','waiting','failed','skipped')
   or (e->>'duration_ms' is not null and (jsonb_typeof(e->'duration_ms')<>'number' or e->>'duration_ms' !~ '^[0-9]{1,10}$'))
   or (e->>'error_code' is not null and crowd_v4.participant_health_error(e->>'error_code') is distinct from e->>'error_code')
  then raise exception 'invalid_events'; end if;
  eid:=(e->>'event_id')::uuid; seq:=(e->>'node_seq')::bigint; rid:=(e->>'run_id')::uuid;
  if seq<1 or seq>9007199254740991 or (e->>'at_ms')::bigint>4102444800000 or (e->>'duration_ms')::bigint>2147483647 then raise exception 'invalid_events'; end if;
  if e ? 'counts' then
   if jsonb_typeof(e->'counts') is distinct from 'object' or ((e->'counts')-array['contents','comments','replies','media','queued','received','pages','source_actions'])<>'{}'::jsonb then raise exception 'invalid_events'; end if;
   for k,v in select * from jsonb_each(e->'counts') loop
    if jsonb_typeof(v)<>'number' or v::text !~ '^[0-9]{1,6}$' or (v::text)::integer>100000 then raise exception 'invalid_events'; end if;
   end loop;
  end if;
  if rid is not null and not exists(select 1 from crowd_v4.node_runs where run_id=rid and installation_id=p_installation and user_id=u) then raise exception 'node_binding_denied'; end if;
  if rid is null and e->>'step' not in ('claim','session','stop','ota','telemetry_gap') then raise exception 'node_binding_denied'; end if;
  select * into old from crowd_v4.node_step_events where installation_id=p_installation and (event_id=eid or node_seq=seq) limit 1;
  if found then
   if old.event is distinct from e then raise exception 'event_conflict'; end if;
   duplicates:=duplicates||jsonb_build_array(eid);
  elsif seq<=n.max_node_seq then
   -- The ordered client stream has already advanced and its exact event is no
   -- longer retained. Do not resurrect old logs or claim an unverifiable duplicate.
   discarded:=discarded||jsonb_build_array(eid);
  else
   insert into crowd_v4.node_step_events(installation_id,event_id,node_seq,run_id,event) values(p_installation,eid,seq,rid,e);
   accepted:=accepted||jsonb_build_array(eid);
  end if;
  n.max_node_seq:=greatest(n.max_node_seq,seq);
 end loop;
 update crowd_v4.nodes set updated_at=now(),max_node_seq=n.max_node_seq where installation_id=p_installation;
 delete from crowd_v4.node_step_events where received_at<now()-interval '7 days';
 delete from crowd_v4.node_step_events where id in (select id from crowd_v4.node_step_events where installation_id=p_installation order by id desc offset 2000);
 delete from crowd_v4.node_step_events where id in (select id from crowd_v4.node_step_events order by id desc offset 50000);
 return jsonb_build_object('schema','crowd-step-events-v1','accepted',accepted,'duplicates',duplicates,'discarded',discarded,
  'discard_reason',case when jsonb_array_length(discarded)>0 then 'sequence_not_retained' end,'diagnostics_enabled',true,'max_node_seq',n.max_node_seq);
end $function$
;

