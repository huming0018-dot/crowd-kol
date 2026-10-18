begin;
-- Safe, opted-in health projections only; original diagnostics snapshots stay unchanged.
create table crowd_v4.participant_health_events (
 id bigint generated always as identity primary key,
 user_id uuid not null references crowd_v4.participants(user_id) on delete cascade,
 at timestamptz not null,
 snapshot jsonb not null check(jsonb_typeof(snapshot)='object' and octet_length(snapshot::text)<=2048)
);
create index participant_health_events_user_at on crowd_v4.participant_health_events(user_id,at desc,id desc);
create index participant_health_events_at on crowd_v4.participant_health_events(at desc,id desc);
alter table crowd_v4.participant_health_events enable row level security;
revoke all on crowd_v4.participant_health_events from public,anon,authenticated,service_role;

create function crowd_v4.participant_health_error(value text) returns text language sql immutable set search_path='' as $$
 select case when value is null then null when value=any(array[
 'page_timeout','page_loading','navigation_failed','navigation_uncommitted','content_unavailable','probe_timeout','page_mismatch','wrong_note','login_required','backend_login_required','user_login','captcha','rate_limit','approval_required','consent_required','user_stopped','logged_out','system_suspended','lease_lost','daily_quota','review_local_rejections','backend_unavailable','control_unavailable','global_pause','action_budget','action_gap','session_rest','known_note','note_busy','invalid_receipt','unexpected_error','test_completed','test_comments_partial','test_expired','test_quota','test_no_task','test_partial','test_new_run_required','parallel_unavailable','pool_recovery_required','executor_busy','update_in_progress','cancelled','source_outcome_unknown','executor_released','delivery_retry_exhausted','identity_verification_required','platform_session_changed','checkpoint_conflict','old_outbox_pending','unknown_source_outcome','delivery_retry_limit','platform_identity_changed','old_executor_required','checkpoint_gap','lease_expired','unknown_delivery_history','checkpoint_regression','invalid_checkpoint','legacy_executor_required','explicit_recovery_required','lease_expired_requires_release','recovery_not_supported','outbox_not_drained','pending_identity_delivery','comment_page_budget','content_already_received','source_not_found','source_private','source_deleted','parser_paused','invalid_overlap_window','incomplete_window_outside_authorization','scan_window_blocked'
 ]) then value else 'unexpected_error' end;
$$;
revoke all on function crowd_v4.participant_health_error(text) from public,anon,authenticated,service_role;

create function crowd_v4.participant_health_projection(enabled_diagnostics boolean,state jsonb) returns jsonb
language sql immutable set search_path='' as $$
 select jsonb_build_object(
 'diagnostics_enabled',enabled_diagnostics,
 'version',case when enabled_diagnostics and state->>'version' ~ '^4\.[0-9]{1,3}\.[0-9]{1,3}$' then state->>'version' end,
 'enabled',case when enabled_diagnostics and jsonb_typeof(state->'enabled')='boolean' then (state->>'enabled')::boolean end,
 'queued',case when enabled_diagnostics and jsonb_typeof(state->'queued')='number' and state->>'queued' ~ '^[0-9]{1,5}$' then (state->>'queued')::integer end,
 'error',case when enabled_diagnostics then crowd_v4.participant_health_error(state->>'error') end,
 'kol_error',case when enabled_diagnostics then crowd_v4.participant_health_error(state->'kol'->>'error') end,
 'update_state',case when enabled_diagnostics and state->>'update_state'=any(array['unknown','ready','applied','current','checking','pending_reload','helper_unavailable','error','rolled_back']) then state->>'update_state' end,
 'ota_last_poll_at',case when enabled_diagnostics and jsonb_typeof(state->'ota_last_poll_at')='number' and state->>'ota_last_poll_at' ~ '^[0-9]{1,10}$' and (state->>'ota_last_poll_at')::bigint<=4102444800 then (state->>'ota_last_poll_at')::bigint end,
 'ota_poll_status',case when enabled_diagnostics and state->>'ota_poll_status'=any(array['current','downloaded','pending_reload','error']) then state->>'ota_poll_status' end,
 'ota_poll_error',case when enabled_diagnostics and state->>'ota_poll_error'=any(array['invalid_signature','hash_mismatch','permission_change','replayed_release','recovery_required','busy','operation_failed','invalid_manifest','invalid_url','wrong_extension','update_failed']) then state->>'ota_poll_error' end,
 'ota_poll_query_error',case when enabled_diagnostics and state->>'ota_poll_query_error'=any(array['busy','invalid_response','helper_unavailable']) then state->>'ota_poll_query_error' end
 );
$$;
revoke all on function crowd_v4.participant_health_projection(boolean,jsonb) from public,anon,authenticated,service_role;

create function crowd_v4.record_participant_health() returns trigger language plpgsql security definer set search_path='' as $$
declare projected jsonb; previous jsonb;
begin
 perform pg_advisory_xact_lock(713249120);
 delete from crowd_v4.participant_health_events where at<now()-interval '7 days';
 if not new.enabled then
  delete from crowd_v4.participant_health_events where user_id=new.user_id;
  return new;
 end if;
 projected:=crowd_v4.participant_health_projection(new.enabled,new.state);
 select snapshot into previous from crowd_v4.participant_health_events where user_id=new.user_id order by at desc,id desc limit 1;
 -- Poll times refresh current diagnostics, but do not flood unchanged-state history.
 if (previous-'ota_last_poll_at') is distinct from (projected-'ota_last_poll_at') then
  insert into crowd_v4.participant_health_events(user_id,at,snapshot) values(new.user_id,new.updated_at,projected);
 end if;
 delete from crowd_v4.participant_health_events where id in (
  select id from crowd_v4.participant_health_events where user_id=new.user_id order by at desc,id desc offset 500);
 delete from crowd_v4.participant_health_events where id in (
  select id from crowd_v4.participant_health_events order by at desc,id desc offset 10000);
 return new;
end $$;
revoke all on function crowd_v4.record_participant_health() from public,anon,authenticated,service_role;
create trigger crowd_participant_health_changed after insert or update on crowd_v4.diagnostics
 for each row execute function crowd_v4.record_participant_health();

-- Extend, rather than overwrite, the deployed optional diagnostics contract.
do $migration$
declare definition text; anchor text:=' update crowd_v4.diagnostics set state=p_state';
validation text:=$v$
 if p_state ? 'ota_last_poll_at' and jsonb_typeof(p_state->'ota_last_poll_at')<>'null' then
  if jsonb_typeof(p_state->'ota_last_poll_at') is distinct from 'number' or p_state->>'ota_last_poll_at' !~ '^[0-9]{1,10}$' then raise exception 'invalid_diagnostics'; end if;
  if (p_state->>'ota_last_poll_at')::bigint>4102444800 then raise exception 'invalid_diagnostics'; end if;
 end if;
 if p_state ? 'ota_poll_status' and jsonb_typeof(p_state->'ota_poll_status')<>'null' and (jsonb_typeof(p_state->'ota_poll_status') is distinct from 'string' or p_state->>'ota_poll_status' not in ('current','downloaded','pending_reload','error')) then raise exception 'invalid_diagnostics'; end if;
 if p_state ? 'ota_poll_error' and jsonb_typeof(p_state->'ota_poll_error')<>'null' and (jsonb_typeof(p_state->'ota_poll_error') is distinct from 'string' or p_state->>'ota_poll_error' not in ('invalid_signature','hash_mismatch','permission_change','replayed_release','recovery_required','busy','operation_failed','invalid_manifest','invalid_url','wrong_extension','update_failed')) then raise exception 'invalid_diagnostics'; end if;
 if p_state ? 'ota_poll_query_error' and jsonb_typeof(p_state->'ota_poll_query_error')<>'null' and (jsonb_typeof(p_state->'ota_poll_query_error') is distinct from 'string' or p_state->>'ota_poll_query_error' not in ('busy','invalid_response','helper_unavailable')) then raise exception 'invalid_diagnostics'; end if;
$v$;
begin
 definition:=pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure);
 if position(anchor in definition)=0 or position('ota_last_poll_at' in definition)>0
  or position('where k<>all(array[' in definition)=0 then raise exception 'participant_health_anchor_mismatch'; end if;
 definition:=replace(definition,'where k<>all(array[','where k<>all(array[''ota_last_poll_at'',''ota_poll_status'',''ota_poll_error'',''ota_poll_query_error'',');
 definition:=replace(definition,anchor,validation||anchor);
 execute definition;
end $migration$;

create function public.crowd_participant_health_rpc(p_owner_scope text,p_actor_kind text,p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare participant_limit integer:=100; event_limit integer:=200; result jsonb;
begin
 if p_owner_scope is distinct from 'crowd-owner-main' or p_actor_kind is distinct from 'owner' then raise exception 'principal_denied'; end if;
 if jsonb_typeof(p_payload) is distinct from 'object' or (p_payload-array['limit','event_limit'])<>'{}'::jsonb then raise exception 'invalid_request'; end if;
 if p_payload ? 'limit' then
  if jsonb_typeof(p_payload->'limit') is distinct from 'number' or p_payload->>'limit' !~ '^[0-9]{1,3}$' then raise exception 'invalid_request'; end if;
  participant_limit:=(p_payload->>'limit')::integer;
 end if;
 if p_payload ? 'event_limit' then
  if jsonb_typeof(p_payload->'event_limit') is distinct from 'number' or p_payload->>'event_limit' !~ '^[0-9]{1,3}$' then raise exception 'invalid_request'; end if;
  event_limit:=(p_payload->>'event_limit')::integer;
 end if;
 if participant_limit<1 or participant_limit>100 or event_limit<1 or event_limit>200 then raise exception 'invalid_request'; end if;
 perform pg_advisory_xact_lock(713249120);
 delete from crowd_v4.participant_health_events where at<now()-interval '7 days';
 select jsonb_build_object('schema','crowd-participant-health-v1','checked_at',now(),'retention_days',7,
 'max_events_per_participant',500,'max_events_total',10000,'stale_after_seconds',180,
 'participants',coalesce((select jsonb_agg(value order by updated_at desc,user_id) from (
  select d.user_id,d.updated_at,crowd_v4.participant_health_projection(d.enabled,d.state)||jsonb_build_object(
   'user_id',d.user_id,'updated_at',d.updated_at,'stale',d.enabled and d.updated_at<now()-interval '180 seconds') value
  from crowd_v4.diagnostics d join crowd_v4.participants p using(user_id)
  where p.consent='crowd-public-v4' order by d.updated_at desc,d.user_id limit participant_limit) snapshots),'[]'::jsonb),
 'events',coalesce((select jsonb_agg(value order by at desc,id desc) from (
  select e.id,e.at,e.snapshot||jsonb_build_object('id',e.id,'user_id',e.user_id,'at',e.at) value
  from crowd_v4.participant_health_events e join crowd_v4.diagnostics d using(user_id)
  join crowd_v4.participants p using(user_id)
  where d.enabled and p.consent='crowd-public-v4' order by e.at desc,e.id desc limit event_limit) changes),'[]'::jsonb)) into result;
 return result;
end $$;
revoke all on function public.crowd_participant_health_rpc(text,text,jsonb) from public,anon,authenticated;
grant execute on function public.crowd_participant_health_rpc(text,text,jsonb) to service_role;
commit;
