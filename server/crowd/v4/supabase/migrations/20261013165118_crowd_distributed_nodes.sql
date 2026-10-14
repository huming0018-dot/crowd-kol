begin;
-- Additive participant adapter. Existing claim/guard/submit and reward accounting remain authoritative.
create table crowd_v4.nodes (
 installation_id uuid primary key,
 user_id uuid not null references crowd_v4.participants(user_id),
 version text not null, enabled boolean not null, login_state text not null,
 release_digest text, max_node_seq bigint not null default 0,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index crowd_nodes_user on crowd_v4.nodes(user_id);
create table crowd_v4.node_runs (
 run_id uuid primary key default gen_random_uuid(),
 installation_id uuid not null references crowd_v4.nodes(installation_id),
 user_id uuid not null references crowd_v4.participants(user_id),
 task_id bigint not null references crowd_v4.tasks(id), lease_token uuid not null,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(task_id,lease_token)
);
create table crowd_v4.node_step_events (
 id bigint generated always as identity primary key,
 installation_id uuid not null references crowd_v4.nodes(installation_id),
 event_id uuid not null, node_seq bigint not null, run_id uuid references crowd_v4.node_runs(run_id),
 event jsonb not null check(octet_length(event::text)<=2048),
 received_at timestamptz not null default now(),
 unique(installation_id,event_id),unique(installation_id,node_seq)
);
create index crowd_node_events_received on crowd_v4.node_step_events(received_at,id);
alter table crowd_v4.nodes enable row level security;
alter table crowd_v4.node_runs enable row level security;
alter table crowd_v4.node_step_events enable row level security;
revoke all on crowd_v4.nodes,crowd_v4.node_runs,crowd_v4.node_step_events from public,anon,authenticated,service_role;

create function public.crowd_v4_node_register(p_installation uuid,p_state jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid(); n crowd_v4.nodes; opted boolean;
begin
 if u is null then raise exception 'login_required'; end if;
 perform 1 from crowd_v4.participants where user_id=u and consent='crowd-public-v4' for update;
 if not found then raise exception 'consent_required'; end if;
 if p_installation is null or jsonb_typeof(p_state) is distinct from 'object'
 or (p_state-array['version','enabled','login_state','release_digest'])<>'{}'::jsonb
 or coalesce(p_state->>'version','') !~ '^4\.[0-9]{1,3}\.[0-9]{1,3}$'
 or jsonb_typeof(p_state->'enabled') is distinct from 'boolean'
 or coalesce(p_state->>'login_state','') not in ('ready','needs_login','verification','unknown')
 or (p_state->>'release_digest' is not null and p_state->>'release_digest' !~ '^[a-f0-9]{64}$')
 then raise exception 'invalid_node'; end if;
 select * into n from crowd_v4.nodes where installation_id=p_installation for update;
 if found and n.user_id<>u then raise exception 'node_binding_denied'; end if;
 if n.installation_id is null and (select count(*) from crowd_v4.nodes where user_id=u)>=10 then raise exception 'node_limit'; end if;
 insert into crowd_v4.nodes(installation_id,user_id,version,enabled,login_state,release_digest)
 values(p_installation,u,p_state->>'version',(p_state->>'enabled')::boolean,p_state->>'login_state',p_state->>'release_digest')
 on conflict(installation_id) do update set version=excluded.version,enabled=excluded.enabled,
 login_state=excluded.login_state,release_digest=excluded.release_digest,updated_at=now()
 where crowd_v4.nodes.user_id=u returning * into n;
 if not found then raise exception 'node_binding_denied'; end if;
 select coalesce((select enabled from crowd_v4.diagnostics where user_id=u),false) into opted;
 return jsonb_build_object('schema','crowd-node-v1','registered',true,'installation_id',p_installation,'diagnostics_enabled',opted,'max_node_seq',coalesce(n.max_node_seq,0));
end $$;

create function public.crowd_v4_node_claim(p_installation uuid,p_task bigint default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid(); n crowd_v4.nodes; r crowd_v4.node_runs; result jsonb; t crowd_v4.tasks;
begin
 if u is null then raise exception 'login_required'; end if;
 -- Same lock order as original claim: participant, then task. Registration and events follow it too.
 perform 1 from crowd_v4.participants where user_id=u for update;
 select * into n from crowd_v4.nodes where installation_id=p_installation and user_id=u;
 if not found then raise exception 'node_binding_denied'; end if;
 -- enabled is a cached status, not an authorization gate. Original claim/guard and local
 -- manual-stop control source work; old outbox delivery can still renew its original task.
 result:=public.crowd_v4_claim(p_task);
 if result->'task' is not null and jsonb_typeof(result->'task')='object' then
  select * into t from crowd_v4.tasks where id=(result->'task'->>'id')::bigint;
  if t.claimed_by is distinct from u or t.lease_token is null then raise exception 'node_binding_denied'; end if;
  select * into r from crowd_v4.node_runs where task_id=t.id and lease_token=t.lease_token;
  if found and (r.user_id<>u or r.installation_id<>p_installation) then raise exception 'node_binding_denied'; end if;
  if r.run_id is null then
   insert into crowd_v4.node_runs(installation_id,user_id,task_id,lease_token)
    values(p_installation,u,t.id,t.lease_token) returning * into r;
  else update crowd_v4.node_runs set updated_at=now() where run_id=r.run_id; end if;
  result:=result||jsonb_build_object('node_run',jsonb_build_object('run_id',r.run_id,'installation_id',p_installation,'task_id',t.id));
 end if;
 update crowd_v4.nodes set updated_at=now() where installation_id=p_installation;
 return result;
end $$;

create function public.crowd_v4_step_events(p_installation uuid,p_events jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
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
end $$;

create function crowd_v4.clear_node_telemetry() returns trigger language plpgsql security definer set search_path='' as $$
begin
 if not new.enabled then
  delete from crowd_v4.node_step_events where installation_id in(select installation_id from crowd_v4.nodes where user_id=new.user_id);
 end if;
 return new;
end $$;
revoke all on function crowd_v4.clear_node_telemetry() from public,anon,authenticated,service_role;
create trigger crowd_node_telemetry_optout after insert or update on crowd_v4.diagnostics for each row execute function crowd_v4.clear_node_telemetry();

create function public.crowd_unified_monitor_rpc(p_owner_scope text,p_actor_kind text,p_action text,p_payload jsonb default '{}')
returns jsonb language plpgsql security definer set search_path='' as $$
declare lim integer:=100; after_id bigint:=0; installation uuid; events jsonb; cursor_id bigint; more boolean; tasks jsonb; nodes jsonb;
begin
 if p_owner_scope is distinct from 'crowd-owner-main' or p_actor_kind is distinct from 'owner' then raise exception 'principal_denied'; end if;
 if jsonb_typeof(p_payload) is distinct from 'object' then raise exception 'invalid_request'; end if;
 if p_payload ? 'limit' then
  if jsonb_typeof(p_payload->'limit') is distinct from 'number' or coalesce(p_payload->>'limit','') !~ '^[0-9]{1,3}$' then raise exception 'invalid_request'; end if;
  lim:=(p_payload->>'limit')::integer;
 end if;
 if lim<1 or lim>(case when p_action='node_events' then 200 else 100 end) then raise exception 'invalid_request'; end if;
 if p_action='node_events' then
  if (p_payload-array['limit','after_id','installation_id'])<>'{}'::jsonb then raise exception 'invalid_request'; end if;
  if p_payload ? 'after_id' then
   if jsonb_typeof(p_payload->'after_id') is distinct from 'number' or coalesce(p_payload->>'after_id','') !~ '^[0-9]{1,16}$' then raise exception 'invalid_request'; end if;
   after_id:=(p_payload->>'after_id')::bigint;
   if after_id>9007199254740991 then raise exception 'invalid_request'; end if;
  end if;
  if p_payload ? 'installation_id' then
   if coalesce(p_payload->>'installation_id','') !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$' then raise exception 'invalid_request'; end if;
   installation:=(p_payload->>'installation_id')::uuid;
  end if;
  select coalesce(jsonb_agg(value order by id),'[]'::jsonb),coalesce(max(id),after_id) into events,cursor_id from (
   select e.id,e.event||jsonb_build_object('id',e.id,'installation_id',e.installation_id,'occurred_at',to_timestamp((e.event->>'at_ms')::double precision/1000),
    'received_at',e.received_at,'logical_task_id',case when r.task_id is not null then 'participant:'||r.task_id end,'source_kind','participant_extension','evidence_kind','client_reported_step') value
   from crowd_v4.node_step_events e join crowd_v4.nodes n using(installation_id)
   join crowd_v4.diagnostics d on d.user_id=n.user_id left join crowd_v4.node_runs r on r.run_id=e.run_id
   where d.enabled and e.id>after_id and e.received_at>=now()-interval '7 days' and (installation is null or e.installation_id=installation)
   order by e.id limit lim) items;
  select exists(select 1 from crowd_v4.node_step_events e join crowd_v4.nodes n using(installation_id) join crowd_v4.diagnostics d on d.user_id=n.user_id
   where d.enabled and e.id>cursor_id and e.received_at>=now()-interval '7 days' and (installation is null or e.installation_id=installation)) into more;
  return jsonb_build_object('schema','crowd-node-events-v1','checked_at',now(),'events',events,'cursor',cursor_id,'has_more',more,'retention_days',7);
 elsif p_action='unified_status' then
  if (p_payload-array['limit'])<>'{}'::jsonb then raise exception 'invalid_request'; end if;
  select coalesce(jsonb_agg(value order by created_at desc),'[]'::jsonb) into tasks from (
   select t.created_at,jsonb_build_object('logical_task_id','participant:'||t.id,'task_id',t.id,'execution_kind','participant_extension',
    'source_kind','participant_extension','platforms',jsonb_build_array('xhs'),'mode','search','title',t.query,'state',t.status,
    'desired_state',case when t.status='closed' then 'stopped' else 'running' end,'received',t.received,'comments',null,
    'created_at',t.created_at,'coverage','observed_participant_receipts_only','step_monitoring','opted_in_upgraded_nodes','reward_eligible',true) value
   from crowd_v4.tasks t
   union all
   select t.created_at,jsonb_build_object('logical_task_id','machine:'||t.task_id,'task_id',t.task_id,'execution_kind','machine_worker',
    'source_kind','machine_api','platforms',(select coalesce(jsonb_agg(c.platform),'[]'::jsonb) from crowd_machine.children c where c.task_id=t.task_id),
    'mode',t.proposal->>'mode','title',t.proposal->>'mode','state',case when t.desired_state='running' and exists(
      select 1 from crowd_machine.children expired where expired.task_id=t.task_id and expired.state='running' and expired.lease_until<=now()
     ) then 'interrupted_unknown' else mt.value->>'state' end,'desired_state',t.desired_state,
    'received',mt.value->'contents','comments',mt.value->'comments',
    'created_at',t.created_at,'coverage','observed_machine_receipts_only','step_monitoring','not_integrated','reward_eligible',false)
   from (select * from crowd_machine.tasks where owner_scope=p_owner_scope order by created_at desc limit lim) t
   cross join lateral (select crowd_machine.public_task(t.task_id) as value offset 0) mt
   order by created_at desc limit lim) items;
  select coalesce(jsonb_agg(value order by updated_at desc),'[]'::jsonb) into nodes from (
   select n.updated_at,jsonb_build_object('node_id',n.installation_id,'installation_id',n.installation_id,'user_id',n.user_id,'worker_id',null,
    'execution_kind','participant_extension','version',case when d.enabled then n.version end,'enabled',n.enabled,
    'login_state',case when d.enabled then n.login_state else 'unknown' end,'updated_at',n.updated_at,'stale',n.updated_at<now()-interval '180 seconds',
    'diagnostics_enabled',coalesce(d.enabled,false),'capabilities',jsonb_build_array(jsonb_build_object('platform','xhs','mode','search')),
    'step_monitoring',case when d.enabled then 'available' else 'disabled' end) value
   from crowd_v4.nodes n left join crowd_v4.diagnostics d using(user_id)
   union all
   select w.created_at,jsonb_build_object('node_id',w.worker_id,'installation_id',null,'user_id',null,'worker_id',w.worker_id,
    'execution_kind','machine_worker','version',null,'enabled',w.enabled,'login_state','unknown','updated_at',null,'stale',null,
    'diagnostics_enabled',false,'capabilities',w.platforms,'step_monitoring','not_integrated')
   from crowd_machine.workers w where w.owner_scope=p_owner_scope
   order by updated_at desc limit lim) items;
  return jsonb_build_object('schema','crowd-unified-status-v1','checked_at',now(),'tasks',tasks,'nodes',nodes,
   'coverage',jsonb_build_object('participant_step_events','opted_in_upgraded_nodes','machine_step_events','not_integrated'));
 else raise exception 'invalid_request'; end if;
end $$;

revoke all on function public.crowd_v4_node_register(uuid,jsonb),public.crowd_v4_node_claim(uuid,bigint),public.crowd_v4_step_events(uuid,jsonb) from public,anon,service_role;
grant execute on function public.crowd_v4_node_register(uuid,jsonb),public.crowd_v4_node_claim(uuid,bigint),public.crowd_v4_step_events(uuid,jsonb) to authenticated;
revoke all on function public.crowd_unified_monitor_rpc(text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.crowd_unified_monitor_rpc(text,text,text,jsonb) to service_role;
commit;
