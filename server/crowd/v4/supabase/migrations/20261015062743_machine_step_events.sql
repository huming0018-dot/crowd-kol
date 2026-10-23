begin;
-- Machine run claims are not participant installations. Preserve participant FK/auth isolation.
create table crowd_machine.step_events (
 id bigint generated always as identity primary key,
 worker_id uuid not null references crowd_machine.workers,
 run_id uuid not null, lease_epoch integer not null check(lease_epoch>=1),
 event_id uuid not null, sequence bigint not null check(sequence>=1),
 event jsonb not null check(octet_length(event::text)<=2048),
 received_at timestamptz not null default clock_timestamp(),
 unique(worker_id,event_id),unique(worker_id,run_id,lease_epoch,sequence)
);
create index crowd_machine_steps_run on crowd_machine.step_events(run_id,id);
alter table crowd_machine.step_events enable row level security;
revoke all on crowd_machine.step_events from public,anon,authenticated;
grant select,insert on crowd_machine.step_events to service_role;
grant usage,select on sequence crowd_machine.step_events_id_seq to service_role;

create function public.crowd_machine_steps_rpc(p_owner_scope text,p_actor_kind text,p_worker_hash text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
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
  if jsonb_typeof(e) is distinct from 'object' or (e-array['page_sha256','scope','checkpoint_committed','page_index','outcome','sequence','observed_at_ms','event_id','run_id','lease_epoch','phase','local_run_id','saved_pages','saved_rows','acknowledged','pending'])<>'{}'::jsonb
   or coalesce(e->>'phase','') not in ('claiming','authorized','dispatching','running','importing','delivering','finishing','waiting_login','login_resumed','paused','completed','deferring_delivery','reconciling_no_dispatch','local_stop_unknown','comments_page')
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
end $$;
revoke all on function public.crowd_machine_steps_rpc(text,text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.crowd_machine_steps_rpc(text,text,text,text,jsonb) to service_role;
commit;
