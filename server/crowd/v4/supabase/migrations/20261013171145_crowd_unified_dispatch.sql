begin;
create table crowd_machine.unified_dispatches (
 dispatch_id uuid primary key default gen_random_uuid(),owner_scope text not null check(owner_scope='crowd-owner-main'),
 idempotency_key text not null,request_hash text not null,request jsonb not null,
 routes jsonb not null,pilot_invite_hash text references crowd_v4.pilot_experiments(invite_hash),
 machine_task_id uuid unique references crowd_machine.tasks(task_id),
 created_at timestamptz not null default now(),unique(owner_scope,idempotency_key)
);
create table crowd_machine.unified_participant_tasks (
 task_id bigint primary key references crowd_v4.tasks(id),
 dispatch_id uuid not null references crowd_machine.unified_dispatches(dispatch_id)
);
create index crowd_dispatch_participant on crowd_machine.unified_participant_tasks(dispatch_id);
alter table crowd_machine.unified_dispatches enable row level security;
alter table crowd_machine.unified_participant_tasks enable row level security;
revoke all on crowd_machine.unified_dispatches,crowd_machine.unified_participant_tasks from public,anon,authenticated,service_role;

create function crowd_v4.dispatch_candidate_allowed(task bigint,participant uuid) returns boolean
language sql stable security definer set search_path='' as $$
 select not exists(
  select 1 from crowd_v4.enrollments e join crowd_machine.unified_dispatches d on d.pilot_invite_hash=e.invite_hash
   where e.user_id=participant and e.completed_at is not null
 ) or exists(
  select 1 from crowd_machine.unified_participant_tasks m join crowd_machine.unified_dispatches d using(dispatch_id)
   join crowd_v4.enrollments e on e.invite_hash=d.pilot_invite_hash
   where m.task_id=task and e.user_id=participant and e.completed_at is not null
 );
$$;
revoke all on function crowd_v4.dispatch_candidate_allowed(bigint,uuid) from public,anon,authenticated,service_role;

-- Only constrain the NEW candidate branch; an existing lease/outbox renews exactly as before.
do $migration$
declare definition text; anchor text:='select * into t from crowd_v4.tasks where received<target and';
begin
 definition:=pg_get_functiondef('public.crowd_v4_claim(bigint)'::regprocedure);
 if (length(definition)-length(replace(definition,anchor,'')))/length(anchor)<>1
  or position('dispatch_candidate_allowed' in definition)>0 then raise exception 'unified_dispatch_claim_anchor_mismatch'; end if;
 execute replace(definition,anchor,anchor||' crowd_v4.dispatch_candidate_allowed(crowd_v4.tasks.id,u) and');
end $migration$;

create function crowd_machine.unified_dispatch_view(p_id uuid) returns jsonb
language sql stable security invoker set search_path='' as $$
 select jsonb_build_object('schema','crowd-unified-dispatch-v1','dispatch_id',d.dispatch_id,
  'idempotency_key',d.idempotency_key,'created_at',d.created_at,'ready',true,'reason',null,
  'routes',coalesce((select jsonb_agg(route||case when route->>'execution_kind'='participant_extension' then
    jsonb_build_object('received',(select coalesce(sum(t.received),0) from crowd_machine.unified_participant_tasks m join crowd_v4.tasks t on t.id=m.task_id where m.dispatch_id=d.dispatch_id),
      'state',case when (select coalesce(sum(t.received),0) from crowd_machine.unified_participant_tasks m join crowd_v4.tasks t on t.id=m.task_id where m.dispatch_id=d.dispatch_id)>=(route->>'item_quota')::integer then 'completed'
       when not exists(select 1 from crowd_machine.unified_participant_tasks m join crowd_v4.tasks t on t.id=m.task_id where m.dispatch_id=d.dispatch_id and t.status not in ('complete','exhausted','closed')) then 'exhausted'
       when exists(select 1 from crowd_machine.unified_participant_tasks m join crowd_v4.tasks t on t.id=m.task_id where m.dispatch_id=d.dispatch_id and t.status='leased' and t.lease_until>now()) then 'running' else 'queued' end)
   else coalesce((select jsonb_build_object('received',c->'contents','state',case when c->>'state'='running' and (c->>'lease_until')::timestamptz<=now() or c->>'state'='unknown' then 'interrupted_unknown' else c->>'state' end)
      from jsonb_array_elements(crowd_machine.public_task(d.machine_task_id)->'children') c where c->>'platform'=route->>'platform'),'{}'::jsonb) end)
    from jsonb_array_elements(d.routes) route),'[]'::jsonb),
  'scope','existing_pilot_and_machine','source_actions_started',0,'created',true,'replayed',false)
 from crowd_machine.unified_dispatches d where d.dispatch_id=p_id;
$$;
revoke all on function crowd_machine.unified_dispatch_view(uuid) from public,anon,authenticated,service_role;

create function public.crowd_unified_dispatch_rpc(p_owner_scope text,p_actor_kind text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare old crowd_machine.unified_dispatches; proposal jsonb; participant jsonb; machine jsonb;
 cohort text; needed integer; remaining integer; total_available integer; ids bigint[]:='{}'; selected_task crowd_v4.tasks;
 routes jsonb:='[]'; child jsonb; reason text; v_dispatch uuid; machine_result jsonb; machine_id uuid; key text;
begin
 if p_owner_scope is distinct from 'crowd-owner-main' or p_actor_kind is distinct from 'owner' then raise exception 'principal_denied'; end if;
 if jsonb_typeof(p_payload) is distinct from 'object' then raise exception 'invalid_request'; end if;
 if p_action='unified_dispatches' then
  if (p_payload-array['idempotency_key'])<>'{}'::jsonb then raise exception 'invalid_request'; end if;
  key:=p_payload->>'idempotency_key';
  if p_payload ? 'idempotency_key' and (jsonb_typeof(p_payload->'idempotency_key')<>'string' or length(key) not between 1 and 160 or key ~ '[[:cntrl:]]') then raise exception 'invalid_request'; end if;
  return jsonb_build_object('schema','crowd-unified-dispatch-list-v1','dispatches',coalesce((
   select jsonb_agg(crowd_machine.unified_dispatch_view(dispatch_id) order by created_at desc)
   from (select d.dispatch_id,d.created_at from crowd_machine.unified_dispatches d where d.owner_scope=p_owner_scope
    and (key is null or d.idempotency_key=key) order by d.created_at desc limit 100) visible),'[]'::jsonb));
 end if;
 if p_action not in ('unified_preview','unified_create') or (p_payload-array['proposal','participant','machine_proposal'])<>'{}'::jsonb then raise exception 'invalid_request'; end if;
 proposal:=p_payload->'proposal';participant:=p_payload->'participant';machine:=p_payload->'machine_proposal';
 if jsonb_typeof(proposal) is distinct from 'object' or coalesce(proposal->>'request_hash','') !~ '^[a-f0-9]{64}$'
  or jsonb_typeof(proposal->'children') is distinct from 'array' or jsonb_array_length(proposal->'children') not between 1 and 7
  or length(coalesce(proposal->'request'->>'idempotency_key','')) not between 1 and 160 then raise exception 'invalid_request'; end if;
 if p_action='unified_create' then perform pg_advisory_xact_lock(713249122); end if;
 select * into old from crowd_machine.unified_dispatches where owner_scope=p_owner_scope and idempotency_key=proposal->'request'->>'idempotency_key';
 if found then
  if old.request_hash is distinct from proposal->>'request_hash' then raise exception 'idempotency_conflict'; end if;
  return crowd_machine.unified_dispatch_view(old.dispatch_id)||jsonb_build_object('created',false,'replayed',true);
 end if;
 if jsonb_typeof(participant)='object' then
  if (participant->>'compatible')::boolean is not true then reason:='participant_route_unavailable';
  else
   needed:=(participant->>'item_quota')::integer;remaining:=needed;
   select x.invite_hash into cohort from crowd_v4.pilot_experiments x join crowd_v4.invites i on i.token_hash=x.invite_hash
    where x.phase in ('awaiting_acceptance','active') and not i.revoked and i.expires_at>now()
     and (x.phase='awaiting_acceptance' or x.armed_at<=now() and x.ends_at>now()) order by x.created_at desc limit 1;
   if cohort is null then reason:='participant_route_unavailable';
   else
    select 20-count(*)::integer into total_available from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where m.invite_hash=cohort;
    total_available:=total_available-coalesce((select sum(greatest(0,t.target-t.received))::integer from crowd_machine.unified_participant_tasks m
      join crowd_v4.tasks t on t.id=m.task_id join crowd_machine.unified_dispatches d using(dispatch_id) where d.pilot_invite_hash=cohort and t.status not in ('closed','exhausted','complete')),0);
    if needed>total_available then reason:='participant_budget_unavailable';
    elsif exists(select 1 from jsonb_array_elements_text(participant->'targets') goal where not exists(
      select 1 from crowd_v4.pilot_task_map mapped join crowd_v4.tasks available on available.id=mapped.task_id
       where mapped.invite_hash=cohort and available.query=goal)) then reason:='participant_target_unavailable';
    else
     for selected_task in select candidate.* from crowd_v4.tasks candidate join crowd_v4.pilot_task_map pm on pm.task_id=candidate.id
      where pm.invite_hash=cohort and candidate.status='open' and candidate.received=0 and candidate.claimed_by is null
       and candidate.available_at<=now() and not candidate.comments_capture and not candidate.structured_capture
       and candidate.query in(select jsonb_array_elements_text(participant->'targets'))
       and not exists(select 1 from crowd_machine.unified_participant_tasks used where used.task_id=candidate.id)
      order by candidate.last_claimed_at nulls first,candidate.id for update of candidate skip locked loop
      if selected_task.target<=remaining then ids:=array_append(ids,selected_task.id);remaining:=remaining-selected_task.target;end if;
      exit when remaining=0;
     end loop;
     if remaining<>0 then reason:='participant_target_unavailable';end if;
    end if;
   end if;
  end if;
 end if;
 for child in select value from jsonb_array_elements(proposal->'children') loop
  if child->>'platform'='xhs' and jsonb_typeof(participant)='object' then
   routes:=routes||jsonb_build_array(jsonb_build_object('platform','xhs','execution_kind','participant_extension','item_quota',child->'item_quota',
    'request_quota',null,'state',case when reason is null then 'queued' else 'waiting' end,'reason_code',reason,'task_ids',to_jsonb(ids),'budget_basis','existing_pilot_guard'));
  else
   routes:=routes||jsonb_build_array(jsonb_build_object('platform',child->>'platform','execution_kind','machine_worker','item_quota',child->'item_quota',
     'request_quota',child->'request_quota','state',child->>'state','reason_code',child->>'reason_code'));
  end if;
 end loop;
 if reason is not null or p_action='unified_preview' then
  return jsonb_build_object('schema','crowd-unified-dispatch-v1','dispatch_id',null,'idempotency_key',proposal->'request'->>'idempotency_key',
   'ready',reason is null,'reason',reason,'routes',routes,'scope','existing_pilot_and_machine','source_actions_started',0,'created',false,'replayed',false);
 end if;
 -- Both routes commit atomically. A lost HTTP response replays the same logical task.
 if jsonb_typeof(machine)='object' then
  machine_result:=public.crowd_machine_rpc(p_owner_scope,'owner',null,'task_create',jsonb_build_object('proposal',machine));
  machine_id:=(machine_result->'task'->>'task_id')::uuid;
  if machine_id is null then raise exception 'invalid_request'; end if;
  select jsonb_agg(route||case when route->>'execution_kind'='machine_worker' then jsonb_build_object('task_id',machine_id) else '{}'::jsonb end) into routes from jsonb_array_elements(routes) route;
 end if;
 insert into crowd_machine.unified_dispatches(owner_scope,idempotency_key,request_hash,request,routes,pilot_invite_hash,machine_task_id)
  values(p_owner_scope,proposal->'request'->>'idempotency_key',proposal->>'request_hash',proposal->'request',routes,cohort,machine_id) returning unified_dispatches.dispatch_id into v_dispatch;
 insert into crowd_machine.unified_participant_tasks(task_id,dispatch_id) select task_id,v_dispatch from unnest(ids) task_id;
 return crowd_machine.unified_dispatch_view(v_dispatch);
end $$;
revoke all on function public.crowd_unified_dispatch_rpc(text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.crowd_unified_dispatch_rpc(text,text,text,jsonb) to service_role;
commit;
