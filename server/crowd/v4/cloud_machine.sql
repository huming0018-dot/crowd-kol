-- Additive source SQL. Generate the migration with `supabase migration new crowd_machine`.
-- Deploy only after independent review. Existing participant/reward/OTA tables are untouched.
create schema if not exists crowd_machine;
revoke all on schema crowd_machine from public, anon, authenticated;
grant usage on schema crowd_machine to service_role;

create table if not exists crowd_machine.workers (
 worker_id uuid primary key, owner_scope text not null check(owner_scope='crowd-owner-main'),
 token_hash text unique not null check(token_hash ~ '^[a-f0-9]{64}$'),
 name text not null, platforms jsonb not null, enabled boolean not null default true,
 expires_at timestamptz not null, created_at timestamptz not null default clock_timestamp()
);
create table if not exists crowd_machine.tasks (
 task_id uuid primary key default gen_random_uuid(), owner_scope text not null check(owner_scope='crowd-owner-main'),
 idempotency_key text not null, request_hash text not null, proposal jsonb not null,
 desired_state text not null default 'running' check(desired_state in ('running','paused','stopped')),
 revision bigint not null default 1, created_at timestamptz not null default clock_timestamp(),
 updated_at timestamptz not null default clock_timestamp(), unique(owner_scope,idempotency_key)
);
create table if not exists crowd_machine.children (
 child_id uuid primary key, task_id uuid not null references crowd_machine.tasks,
 platform text not null check(platform in ('xhs','dy','ks','bili','wb','tieba','zhihu')),
 plan jsonb not null, state text not null check(state in ('queued','waiting','running','unknown','completed','failed','stopped')),
 reason_code text, worker_id uuid references crowd_machine.workers, run_id uuid unique,
 lease_epoch integer not null default 0, lease_until timestamptz, heartbeat_seq bigint not null default 0,
 requests_reserved integer not null default 0, requests_spent integer not null default 0,
 local_run_id uuid, account_context jsonb not null default '{}'::jsonb, finish_hash text, finished_at timestamptz,
 unique(task_id,platform)
);
create index if not exists crowd_machine_children_queue on crowd_machine.children(state,platform,task_id);
create table if not exists crowd_machine.claims (
 worker_id uuid not null references crowd_machine.workers, claim_id uuid not null,
 child_id uuid references crowd_machine.children, run_id uuid, lease_epoch integer, created_at timestamptz not null default clock_timestamp(),
 local_run_id uuid, outcome text, api_attempts integer, finished_at timestamptz,
 primary key(worker_id,claim_id)
);
alter table crowd_machine.claims add column if not exists local_run_id uuid;
alter table crowd_machine.claims add column if not exists outcome text;
alter table crowd_machine.claims add column if not exists api_attempts integer;
alter table crowd_machine.claims add column if not exists finished_at timestamptz;
create table if not exists crowd_machine.resolutions (
 worker_id uuid not null, claim_id uuid not null, run_id uuid not null, lease_epoch integer not null,
 kind text not null check(kind='no_dispatch'), proof jsonb not null,
 released_requests integer not null check(released_requests>=0),
 created_at timestamptz not null default clock_timestamp(),
 primary key(worker_id,claim_id), foreign key(worker_id,claim_id) references crowd_machine.claims
);
-- Supplemental work is explicit and append-only; the original proposal and attempt remain unchanged.
create table if not exists crowd_machine.recoveries (
 recovery_id uuid primary key default gen_random_uuid(), task_id uuid not null references crowd_machine.tasks,
 child_id uuid not null references crowd_machine.children, idempotency_key text not null,
 request_hash text not null check(request_hash ~ '^[a-f0-9]{64}$'), dimensions jsonb not null, long_audio boolean not null,
 request jsonb not null, source_content_id text check(source_content_id ~ '^[A-Za-z0-9_.:-]{1,200}$'), source_worker_id uuid not null references crowd_machine.workers,
 source_run_id uuid not null, source_lease_epoch integer not null, source_local_run_id uuid not null,
 source_finish_hash text not null, account_context jsonb not null,
 created_at timestamptz not null default clock_timestamp(), unique(task_id,idempotency_key)
);
alter table crowd_machine.recoveries add column if not exists source_content_id text check(source_content_id ~ '^[A-Za-z0-9_.:-]{1,200}$');
alter table crowd_machine.children add column if not exists recovery_id uuid references crowd_machine.recoveries;
alter table crowd_machine.claims add column if not exists recovery_id uuid references crowd_machine.recoveries;
create table if not exists crowd_machine.captures (
 capture_id uuid primary key, owner_scope text not null check(owner_scope='crowd-owner-main'),
 worker_id uuid not null references crowd_machine.workers, task_id uuid not null references crowd_machine.tasks,
 child_id uuid not null references crowd_machine.children, run_id uuid not null,
 lease_epoch integer not null, envelope_hash text not null check(envelope_hash ~ '^[a-f0-9]{64}$'),
 canonical_envelope text not null, envelope jsonb not null, receipt jsonb not null,
 received_at timestamptz not null default clock_timestamp()
);
create index if not exists crowd_machine_captures_task on crowd_machine.captures(task_id,child_id,received_at);
alter table crowd_machine.workers enable row level security;
alter table crowd_machine.tasks enable row level security;
alter table crowd_machine.children enable row level security;
alter table crowd_machine.claims enable row level security;
alter table crowd_machine.captures enable row level security;
alter table crowd_machine.resolutions enable row level security;
alter table crowd_machine.recoveries enable row level security;
revoke all on all tables in schema crowd_machine from public, anon, authenticated;
grant select,insert,update on all tables in schema crowd_machine to service_role;
revoke update,delete on crowd_machine.resolutions,crowd_machine.recoveries from service_role;

-- Freeze the unique original ACK identity; Bili's native store can report AID for a BV locator.
create or replace function crowd_machine.bili_bound_content(p_child uuid) returns text
language sql stable security invoker set search_path='' as $$
select case when count(distinct z.envelope->'record'->>'content_id')=1 and bool_and(coalesce(
 z.envelope->'record'->>'platform'='bilibili'
 and z.envelope->'record'->'origin'->>'run_id'=c.local_run_id::text
 and coalesce(z.envelope->'record'->'origin'->>'file_sha256','') ~ '^[a-f0-9]{64}$'
 and (z.envelope->'record'->>'canonical_id_scheme'='bilibili.bvid.v1' and z.envelope->'record'->>'content_id'=substring(c.plan->'request'->'targets'->>0 from 'BV[A-Za-z0-9]{10}')
   or z.envelope->'record'->>'canonical_id_scheme'='bilibili.aid.v1' and z.envelope->'record'->>'content_id' ~ '^[1-9][0-9]{0,19}$')
 ,false)) then min(z.envelope->'record'->>'content_id') else null end
from crowd_machine.children c join crowd_machine.captures z on z.child_id=c.child_id and z.task_id=c.task_id
 and z.worker_id=c.worker_id and z.run_id=c.run_id and z.lease_epoch=c.lease_epoch
where c.child_id=p_child and c.platform='bili' and c.local_run_id is not null
 and z.envelope->'record'->>'kind'='content'
 and length(btrim(coalesce(z.envelope->'record'->>'body','')||coalesce(z.envelope->'record'->>'title','')))>0;
$$;

create or replace function crowd_machine.supplemental_available(p_child uuid) returns boolean
language sql stable security invoker set search_path='' as $$
select coalesce(t.desired_state='running' and t.proposal->>'delivery_basis'='live_capture'
 and c.platform='bili' and c.plan->'request'->>'mode'='detail'
 and jsonb_typeof(c.plan->'request'->'targets')='array' and jsonb_array_length(c.plan->'request'->'targets')=1
 and c.plan->'request'->'comments'='true'::jsonb and c.plan->'request'->'media'='true'::jsonb
 and c.state='failed' and c.finished_at is not null and c.finish_hash is not null and c.requests_reserved=0
 and c.requests_spent<(c.plan->>'request_quota')::integer and c.local_run_id is not null
 and exists(select 1 from crowd_machine.claims h where h.worker_id=c.worker_id and h.run_id=c.run_id and h.lease_epoch=c.lease_epoch and h.local_run_id=c.local_run_id and h.outcome='failed' and h.api_attempts is not null and h.finished_at is not null)
 and exists(select 1 from crowd_machine.workers w where w.worker_id=c.worker_id and w.enabled and w.expires_at>clock_timestamp() and w.platforms ? 'bili')
 and crowd_machine.bili_bound_content(c.child_id) is not null,false)
from crowd_machine.children c join crowd_machine.tasks t on t.task_id=c.task_id where c.child_id=p_child;
$$;

create or replace function crowd_machine.public_task(p_id uuid) returns jsonb
language sql stable security invoker set search_path='' as $$
select jsonb_build_object(
 'task_id',t.task_id,'mode',t.proposal->>'mode','delivery_basis',t.proposal->>'delivery_basis',
 'desired_items',t.proposal->'desired_items','max_api_requests',t.proposal->'max_api_requests',
 'desired_state',t.desired_state,'revision',t.revision,'created_at',t.created_at,'updated_at',t.updated_at,
 'storage_scope','cloud','source_kind','machine_api','reward_eligible',false,
 'coverage','observed_machine_receipts_only','quantity_semantics','expected_entities_not_hard_source_limit',
 'request_limit_scope','Python httpx/requests attempts; browser resources excluded',
 'state',case when t.desired_state<>'running' then t.desired_state
   when exists(select 1 from crowd_machine.children c where c.task_id=t.task_id and c.state='unknown') then 'interrupted_unknown'
   when not exists(select 1 from crowd_machine.children c where c.task_id=t.task_id and c.state<>'completed') then 'completed'
   when exists(select 1 from crowd_machine.children c where c.task_id=t.task_id and c.state='running') then 'running'
   when exists(select 1 from crowd_machine.children c where c.task_id=t.task_id and c.state='queued') then 'queued'
   else 'waiting' end,
 'contents',(select count(distinct concat(z.envelope->'record'->>'platform',':',z.envelope->'record'->>'kind',':',z.envelope->'record'->>'content_id')) from crowd_machine.captures z where z.task_id=t.task_id and z.envelope->'record'->>'kind' in ('content','dynamic') and length(btrim(coalesce(z.envelope->'record'->>'body','')||coalesce(z.envelope->'record'->>'title','')||coalesce(z.envelope->'record'->>'text','')))>0),
 'comments',(select count(distinct concat(z.envelope->'record'->>'platform',':',z.envelope->'record'->>'content_id',':',z.envelope->'record'->>'comment_id')) from crowd_machine.captures z where z.task_id=t.task_id and z.envelope->'record'->>'kind'='comment' and nullif(z.envelope->'record'->>'comment_id','') is not null),
 'children',coalesce((select jsonb_agg(jsonb_build_object(
   'child_id',c.child_id,'platform',c.platform,'state',c.state,'supplemental_available',crowd_machine.supplemental_available(c.child_id),
   'reason_code',c.reason_code,'item_quota',c.plan->'item_quota','request_quota',c.plan->'request_quota',
   'requests_spent',c.requests_spent,'requests_reserved',c.requests_reserved,
   'active_run_id',case when c.state in ('running','unknown') then c.run_id else null end,
   'runs',case when c.run_id is null then '[]'::jsonb else jsonb_build_array(c.run_id) end,
   'supplemental',(select jsonb_build_object('recovery_id',r.recovery_id,'dimensions',r.dimensions,'long_audio',r.long_audio,'source_run_id',r.source_run_id,'source_content_id',r.source_content_id,'created_at',r.created_at) from crowd_machine.recoveries r where r.recovery_id=c.recovery_id),
   'local_run_id',c.local_run_id,'worker_id',c.worker_id,'lease_epoch',c.lease_epoch,'lease_until',c.lease_until,
   'attempts',coalesce((select jsonb_agg(jsonb_build_object('run_id',h.run_id,'lease_epoch',h.lease_epoch,
      'recovery_id',h.recovery_id,'local_run_id',h.local_run_id,'outcome',h.outcome,'api_attempts',h.api_attempts,
      'started_at',h.created_at,'finished_at',h.finished_at,
      'resolution',(select jsonb_build_object('kind',r.kind,'released_requests',r.released_requests,'created_at',r.created_at)
                    from crowd_machine.resolutions r where r.worker_id=h.worker_id and r.claim_id=h.claim_id)) order by h.created_at)
      from crowd_machine.claims h where h.child_id=c.child_id and h.run_id is not null),'[]'::jsonb),
   'contents',(select count(distinct concat(x.envelope->'record'->>'kind',':',x.envelope->'record'->>'content_id')) from crowd_machine.captures x where x.child_id=c.child_id and x.envelope->'record'->>'kind' in ('content','dynamic') and length(btrim(coalesce(x.envelope->'record'->>'body','')||coalesce(x.envelope->'record'->>'title','')||coalesce(x.envelope->'record'->>'text','')))>0),
   'comments',(select count(distinct concat(x.envelope->'record'->>'content_id',':',x.envelope->'record'->>'comment_id')) from crowd_machine.captures x where x.child_id=c.child_id and x.envelope->'record'->>'kind'='comment' and nullif(x.envelope->'record'->>'comment_id','') is not null),
   'received_captures',(select count(*) from crowd_machine.captures x where x.child_id=c.child_id),
   'delivery_state',case when exists(select 1 from crowd_machine.captures x where x.child_id=c.child_id) then 'cloud_received' else 'none' end,
   'coverage','observed_machine_receipts_only','session_selection','worker_local','session_login_state','unverified'
 ) order by c.platform) from crowd_machine.children c where c.task_id=t.task_id),'[]'::jsonb))
from crowd_machine.tasks t where t.task_id=p_id;
$$;

create or replace function crowd_machine.supplemental_scope(p_child uuid) returns uuid
language sql stable security invoker set search_path='' as $$
select coalesce((select h.local_run_id from crowd_machine.claims h
 where h.child_id=c.child_id and h.worker_id=r.source_worker_id and h.recovery_id=r.recovery_id
 and h.run_id is distinct from c.run_id and h.lease_epoch<c.lease_epoch
 and h.outcome='login_required' and h.local_run_id is not null
 order by h.lease_epoch desc limit 1),r.source_local_run_id)
from crowd_machine.children c join crowd_machine.recoveries r on r.recovery_id=c.recovery_id where c.child_id=p_child;
$$;

create or replace function crowd_machine.lease_view(p_child uuid) returns jsonb
language sql stable security invoker set search_path='' as $$
select jsonb_build_object('task_id',c.task_id,'child_id',c.child_id,'run_id',c.run_id,'worker_id',c.worker_id,
 'platform',c.platform,'lease_epoch',c.lease_epoch,'lease_until',c.lease_until,'server_time',clock_timestamp(),
 'state',c.state,'desired_state',t.desired_state,'reason_code',c.reason_code,
 'may_dispatch',c.state='running' and c.lease_until>clock_timestamp() and t.desired_state='running',
 'delivery_basis',t.proposal->>'delivery_basis','request',jsonb_set(jsonb_set(coalesce(r.request,c.plan->'request'),'{max_api_requests}',to_jsonb(c.requests_reserved)),'{max_items}',to_jsonb(case when r.recovery_id is not null then 1 else greatest(0,(c.plan->>'item_quota')::integer-(select count(distinct concat(mx.envelope->'record'->>'kind',':',mx.envelope->'record'->>'content_id'))::integer from crowd_machine.captures mx where mx.child_id=c.child_id and mx.envelope->'record'->>'kind' in ('content','dynamic') and length(btrim(coalesce(mx.envelope->'record'->>'body','')||coalesce(mx.envelope->'record'->>'title','')||coalesce(mx.envelope->'record'->>'text','')))>0)) end)),
 'supplemental_context',case when r.recovery_id is null then null else jsonb_build_object('recovery_id',r.recovery_id,'dimensions',r.dimensions,'long_audio',r.long_audio,'source_content_id',r.source_content_id,'source_run_id',r.source_run_id,'source_lease_epoch',r.source_lease_epoch,'source_local_run_id',r.source_local_run_id,'source_worker_id',r.source_worker_id,'authorization_local_run_id',crowd_machine.supplemental_scope(c.child_id),'account_context',r.account_context,'request_session_id',r.request->'session_id') end,
 'record_refs',c.plan->'record_refs',
 'item_quota',c.plan->'item_quota','request_quota',c.requests_reserved,
 'requests_reserved',c.requests_reserved,'local_run_id',c.local_run_id)
from crowd_machine.children c join crowd_machine.tasks t on t.task_id=c.task_id left join crowd_machine.recoveries r on r.recovery_id=c.recovery_id where c.child_id=p_child;
$$;

create or replace function public.crowd_machine_rpc(p_owner_scope text,p_actor_kind text,p_worker_hash text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
#variable_conflict use_column
declare w crowd_machine.workers%rowtype; t crowd_machine.tasks%rowtype; c crowd_machine.children%rowtype;
 x crowd_machine.captures%rowtype; claimed crowd_machine.claims%rowtype;
 v_proposal jsonb; item jsonb; v_id uuid; v_hash text; now_at timestamptz;
 envelope jsonb; receipt jsonb; content_count integer; ids jsonb; resolution crowd_machine.resolutions%rowtype;
 recovery crowd_machine.recoveries%rowtype; expected_scope uuid; supplemental_request jsonb; target_id text;
begin
 if p_owner_scope<>'crowd-owner-main' or p_actor_kind not in ('owner','worker') or jsonb_typeof(p_payload)<>'object' then raise exception 'principal_denied'; end if;
 if p_actor_kind='worker' then
   select * into w from crowd_machine.workers where owner_scope=p_owner_scope and token_hash=p_worker_hash for update;
   if not found or not w.enabled or w.expires_at<=clock_timestamp() then raise exception 'worker_revoked'; end if;
   if p_action not in ('claim','heartbeat','capture','receipt','finish','resume_login','reconcile_no_dispatch') then raise exception 'principal_denied'; end if;
 else
   if p_action not in ('task_create','task_list','task_status','task_control','retry_supplemental','worker_pair','worker_revoke','worker_list','results') then raise exception 'principal_denied'; end if;
 end if;
 if p_action='worker_pair' then
   v_id=(p_payload->>'worker_id')::uuid;
   select * into w from crowd_machine.workers where worker_id=v_id for update;
   if found then
     if w.owner_scope<>p_owner_scope or w.token_hash<>p_payload->>'token_hash' or w.platforms<>p_payload->'platforms' then raise exception 'idempotency_conflict'; end if;
   else
     insert into crowd_machine.workers(worker_id,owner_scope,token_hash,name,platforms,expires_at)
     values(v_id,p_owner_scope,p_payload->>'token_hash',p_payload->>'name',p_payload->'platforms',(p_payload->>'expires_at')::timestamptz) returning * into w;
   end if;
   return jsonb_build_object('worker_id',w.worker_id,'name',w.name,'platforms',w.platforms,'enabled',w.enabled,'expires_at',w.expires_at);
 elsif p_action='worker_list' then
   return jsonb_build_object('workers',coalesce((select jsonb_agg(jsonb_build_object('worker_id',worker_id,'name',name,'platforms',platforms,'enabled',enabled,'expires_at',expires_at) order by created_at desc) from crowd_machine.workers where owner_scope=p_owner_scope),'[]'::jsonb));
 elsif p_action='worker_revoke' then
   update crowd_machine.workers set enabled=false where owner_scope=p_owner_scope and worker_id=(p_payload->>'worker_id')::uuid returning * into w;
   if not found then raise exception 'worker_not_found'; end if;
   update crowd_machine.children set state='unknown',reason_code='worker_revoked' where worker_id=w.worker_id and state='running';
   return jsonb_build_object('worker_id',w.worker_id,'enabled',false);
 elsif p_action='task_create' then
   v_proposal=p_payload->'proposal';
   -- Edge validates and hashes the complete request; callers cannot supply their own scope.
   if jsonb_typeof(v_proposal->'children')<>'array' or jsonb_array_length(v_proposal->'children') not between 1 and 7 or v_proposal->>'request_hash' !~ '^[a-f0-9]{64}$' then raise exception 'invalid_request'; end if;
   insert into crowd_machine.tasks(owner_scope,idempotency_key,request_hash,proposal)
   values(p_owner_scope,v_proposal->'request'->>'idempotency_key',v_proposal->>'request_hash',v_proposal)
   on conflict(owner_scope,idempotency_key) do nothing returning * into t;
   if not found then
     select * into t from crowd_machine.tasks where owner_scope=p_owner_scope and idempotency_key=v_proposal->'request'->>'idempotency_key' for update;
     if t.request_hash<>v_proposal->>'request_hash' then raise exception 'idempotency_conflict'; end if;
   else
     for item in select value from jsonb_array_elements(v_proposal->'children') loop
       insert into crowd_machine.children(child_id,task_id,platform,plan,state,reason_code)
       values((item->>'child_id')::uuid,t.task_id,item->>'platform',item,item->>'state',item->>'reason_code');
     end loop;
   end if;
   return jsonb_build_object('task',crowd_machine.public_task(t.task_id));
 elsif p_action='retry_supplemental' then
   select * into t from crowd_machine.tasks where owner_scope=p_owner_scope and task_id=(p_payload->>'task_id')::uuid for update;
   if not found then raise exception 'task_not_found'; end if;
   select * into recovery from crowd_machine.recoveries where task_id=t.task_id and idempotency_key=p_payload->>'idempotency_key';
   if found then
     if recovery.request_hash is distinct from p_payload->>'request_hash' then raise exception 'idempotency_conflict'; end if;
     return jsonb_build_object('recovery_id',recovery.recovery_id,'replayed',true,'task',crowd_machine.public_task(t.task_id));
   end if;
   if (p_payload->>'expected_revision')::bigint is distinct from t.revision then raise exception 'revision_conflict'; end if;
   select * into c from crowd_machine.children where task_id=t.task_id and child_id=(p_payload->>'child_id')::uuid for update;
   if not found then raise exception 'supplemental_retry_denied'; end if;
   select * into claimed from crowd_machine.claims where worker_id=c.worker_id and run_id=c.run_id and lease_epoch=c.lease_epoch;
   target_id=substring(c.plan->'request'->'targets'->>0 from 'BV[A-Za-z0-9]{10}');
   if t.desired_state<>'running' or t.proposal->>'delivery_basis'<>'live_capture' or c.platform<>'bili'
      or c.plan->'request'->>'mode'<>'detail' or jsonb_typeof(c.plan->'request'->'targets') is distinct from 'array'
      or jsonb_array_length(c.plan->'request'->'targets')<>1 or target_id is null
      or c.state<>'failed' or c.finished_at is null or c.finish_hash is null or c.requests_reserved<>0
      or c.requests_spent>=(c.plan->>'request_quota')::integer or c.local_run_id is null
      or claimed.run_id is null or claimed.outcome is distinct from 'failed' or claimed.finished_at is null
      or claimed.local_run_id is distinct from c.local_run_id or claimed.api_attempts is null
      or not exists(select 1 from crowd_machine.workers ww where ww.worker_id=c.worker_id and ww.enabled and ww.expires_at>clock_timestamp() and ww.platforms ? 'bili')
      or jsonb_typeof(p_payload->'dimensions') is distinct from 'array' or jsonb_array_length(p_payload->'dimensions') not between 1 and 2
      or exists(select 1 from jsonb_array_elements_text(p_payload->'dimensions') d where d not in ('comments','media'))
      or (select count(distinct d) from jsonb_array_elements_text(p_payload->'dimensions') d)<>jsonb_array_length(p_payload->'dimensions')
      or p_payload->'dimensions' ? 'comments' and c.plan->'request'->'comments' is distinct from 'true'::jsonb
      or p_payload->'dimensions' ? 'media' and c.plan->'request'->'media' is distinct from 'true'::jsonb
      or jsonb_typeof(p_payload->'long_audio') is distinct from 'boolean' or p_payload->'long_audio'='true'::jsonb and not(p_payload->'dimensions' ? 'media')
      or coalesce(p_payload->>'request_hash','') !~ '^[a-f0-9]{64}$'
      or length(coalesce(p_payload->>'idempotency_key','')) not between 1 and 160
      or crowd_machine.bili_bound_content(c.child_id) is null
      then raise exception 'supplemental_retry_denied'; end if;
   supplemental_request=c.plan->'request'||jsonb_build_object('comments',p_payload->'dimensions' ? 'comments','replies',p_payload->'dimensions' ? 'comments' and c.plan->'request'->'replies'='true'::jsonb,'media',p_payload->'dimensions' ? 'media','wordcloud',false,'max_items',1,'max_api_requests',(c.plan->>'request_quota')::integer-c.requests_spent,'platform_options',coalesce(c.plan->'request'->'platform_options','{}'::jsonb)||jsonb_build_object('long_audio',(p_payload->>'long_audio')::boolean));
   insert into crowd_machine.recoveries(task_id,child_id,idempotency_key,request_hash,dimensions,long_audio,request,source_content_id,source_worker_id,source_run_id,source_lease_epoch,source_local_run_id,source_finish_hash,account_context)
   values(t.task_id,c.child_id,p_payload->>'idempotency_key',p_payload->>'request_hash',p_payload->'dimensions',(p_payload->>'long_audio')::boolean,supplemental_request,crowd_machine.bili_bound_content(c.child_id),c.worker_id,c.run_id,c.lease_epoch,c.local_run_id,c.finish_hash,c.account_context) returning * into recovery;
   update crowd_machine.children set state='queued',reason_code='supplemental_requested',recovery_id=recovery.recovery_id where child_id=c.child_id;
   update crowd_machine.tasks set revision=revision+1,updated_at=clock_timestamp() where task_id=t.task_id;
   return jsonb_build_object('recovery_id',recovery.recovery_id,'replayed',false,'task',crowd_machine.public_task(t.task_id));
 elsif p_action='task_list' then
   update crowd_machine.children cc set state='unknown',reason_code='lease_expired_source_outcome_unknown'
   from crowd_machine.tasks tt where cc.task_id=tt.task_id and tt.owner_scope=p_owner_scope and cc.state='running' and cc.lease_until<=clock_timestamp();
   return jsonb_build_object('tasks',coalesce((select jsonb_agg(crowd_machine.public_task(task_id) order by created_at desc) from (select task_id,created_at from crowd_machine.tasks where owner_scope=p_owner_scope order by created_at desc limit 200)t),'[]'::jsonb));
 elsif p_action in ('task_status','task_control','results') then
   select * into t from crowd_machine.tasks where owner_scope=p_owner_scope and task_id=(p_payload->>'task_id')::uuid for update;
   if not found then raise exception 'task_not_found'; end if;
   update crowd_machine.children set state='unknown',reason_code='lease_expired_source_outcome_unknown' where task_id=t.task_id and state='running' and lease_until<=clock_timestamp();
   if p_action='task_control' then
     if (p_payload->>'expected_revision')::bigint<>t.revision then raise exception 'revision_conflict'; end if;
     if p_payload->>'desired_state' not in ('running','paused','stopped') then raise exception 'invalid_request'; end if;
     update crowd_machine.tasks set desired_state=p_payload->>'desired_state',revision=revision+1,updated_at=clock_timestamp() where task_id=t.task_id returning * into t;
     if t.desired_state='stopped' then update crowd_machine.children set state='stopped',reason_code='owner_stopped_before_dispatch' where task_id=t.task_id and state='queued'; end if;
     if t.desired_state='running' then
       update crowd_machine.children set state='queued',reason_code=null where task_id=t.task_id and state='stopped' and run_id is null and reason_code='owner_stopped_before_dispatch';
     end if;
   elsif p_action='results' then
     return jsonb_build_object('task_id',t.task_id,'source_kind','machine_api','reward_eligible',false,'items',coalesce((select jsonb_agg(jsonb_build_object('record',envelope->'record','receipt',receipt,'delivery_basis',envelope->>'delivery_basis','packaged_at',envelope->>'packaged_at') order by received_at,capture_id) from (select * from crowd_machine.captures where task_id=t.task_id order by received_at,capture_id limit 2000)s),'[]'::jsonb));
   end if;
   return jsonb_build_object('task',crowd_machine.public_task(t.task_id));
 elsif p_action='reconcile_no_dispatch' then
   -- Authenticated worker attests an audited durable pre-start snapshot; this is not remote proof of no dispatch.
   if jsonb_typeof(p_payload->'proof') is distinct from 'object'
      or p_payload->'proof'->>'phase' is distinct from 'authorized'
      or p_payload->'proof'->'local_run_id' is distinct from 'null'::jsonb
      or jsonb_typeof(p_payload->'proof'->'sequence') is distinct from 'number'
      or coalesce(p_payload->'proof'->>'sequence','') !~ '^[1-9][0-9]{0,15}$'
      or (p_payload->'proof'->>'sequence')::bigint>9007199254740991
      or coalesce(p_payload->'proof'->>'evidence_sha256','') !~ '^[a-f0-9]{64}$'
      then raise exception 'no_dispatch_reconciliation_denied'; end if;
   select * into claimed from crowd_machine.claims where worker_id=w.worker_id and claim_id=(p_payload->>'claim_id')::uuid for update;
   if not found or claimed.run_id is distinct from (p_payload->>'run_id')::uuid or claimed.lease_epoch is distinct from (p_payload->>'lease_epoch')::integer then raise exception 'lease_binding_denied'; end if;
   select * into resolution from crowd_machine.resolutions where worker_id=w.worker_id and claim_id=claimed.claim_id;
   if found then
     if resolution.proof is distinct from p_payload->'proof' then raise exception 'reconciliation_conflict'; end if;
     return jsonb_build_object('reconciled',true,'replayed',true,'worker_id',w.worker_id,'claim_id',claimed.claim_id,'run_id',claimed.run_id,'lease_epoch',claimed.lease_epoch,'released_requests',resolution.released_requests,'task',crowd_machine.public_task((select task_id from crowd_machine.children where child_id=claimed.child_id)));
   end if;
   select * into c from crowd_machine.children where child_id=claimed.child_id and worker_id=w.worker_id for update;
   if not found or c.run_id is distinct from claimed.run_id or c.lease_epoch is distinct from claimed.lease_epoch
      or c.state is distinct from 'unknown' or c.local_run_id is not null or claimed.local_run_id is not null
      or claimed.outcome is not null and claimed.outcome<>'unknown'
      or claimed.api_attempts is not null and claimed.api_attempts<>0
      or (p_payload->'proof'->>'sequence')::bigint>c.heartbeat_seq
      or exists(select 1 from crowd_machine.captures where run_id=claimed.run_id)
      then raise exception 'no_dispatch_reconciliation_denied'; end if;
   insert into crowd_machine.resolutions(worker_id,claim_id,run_id,lease_epoch,kind,proof,released_requests)
   values(w.worker_id,claimed.claim_id,claimed.run_id,claimed.lease_epoch,'no_dispatch',p_payload->'proof',c.requests_reserved) returning * into resolution;
   update crowd_machine.children set state='waiting',reason_code='no_dispatch_reconciled',requests_reserved=0 where child_id=c.child_id;
   return jsonb_build_object('reconciled',true,'replayed',false,'worker_id',w.worker_id,'claim_id',claimed.claim_id,'run_id',claimed.run_id,'lease_epoch',claimed.lease_epoch,'released_requests',resolution.released_requests,'task',crowd_machine.public_task(c.task_id));
 elsif p_action='claim' then
   v_id=(p_payload->>'claim_id')::uuid;
   select * into claimed from crowd_machine.claims where worker_id=w.worker_id and claim_id=v_id;
   if found then return jsonb_build_object('lease',case when claimed.child_id is null then null when exists(select 1 from crowd_machine.children cc where cc.child_id=claimed.child_id and cc.run_id=claimed.run_id and cc.lease_epoch=claimed.lease_epoch) then crowd_machine.lease_view(claimed.child_id) else null end,'replayed',true); end if;
   update crowd_machine.children set state='unknown',reason_code='lease_expired_source_outcome_unknown' where worker_id=w.worker_id and state='running' and lease_until<=clock_timestamp();
   if not exists(select 1 from crowd_machine.children where worker_id=w.worker_id and state in ('running','unknown')) then
     select c0.* into c from crowd_machine.children c0 join crowd_machine.tasks t0 on t0.task_id=c0.task_id
     where t0.owner_scope=p_owner_scope and t0.desired_state='running' and c0.state='queued' and w.platforms ? c0.platform and not(coalesce(p_payload->'unavailable_platforms','[]'::jsonb) ? c0.platform) and (c0.worker_id is null or c0.worker_id=w.worker_id)
     order by t0.created_at,c0.platform for update of c0 skip locked limit 1;
     if found then
       update crowd_machine.children set state='running',worker_id=w.worker_id,run_id=gen_random_uuid(),lease_epoch=lease_epoch+1,lease_until=clock_timestamp()+interval '90 seconds',requests_reserved=(plan->>'request_quota')::integer-requests_spent,finished_at=null,finish_hash=null,local_run_id=null,heartbeat_seq=0 where child_id=c.child_id returning * into c;
       insert into crowd_machine.claims(worker_id,claim_id,child_id,run_id,lease_epoch,recovery_id) values(w.worker_id,v_id,c.child_id,c.run_id,c.lease_epoch,c.recovery_id);
       return jsonb_build_object('lease',crowd_machine.lease_view(c.child_id),'replayed',false);
     end if;
   end if;
   insert into crowd_machine.claims(worker_id,claim_id,child_id) values(w.worker_id,v_id,null);
   return jsonb_build_object('lease',null,'replayed',false);
 end if;
 -- Historical ACKs remain bound to their original actor/run after a login recovery.
 if p_action='receipt' then
   select * into x from crowd_machine.captures where capture_id=(p_payload->>'capture_id')::uuid and worker_id=w.worker_id and run_id=(p_payload->>'run_id')::uuid and lease_epoch=(p_payload->>'lease_epoch')::integer;
   if not found then return jsonb_build_object('receipt',null); end if;
   if x.envelope_hash<>p_payload->>'envelope_hash' then raise exception 'capture_hash_conflict'; end if;
   return jsonb_build_object('receipt',x.receipt);
 elsif p_action='capture' then
   select * into x from crowd_machine.captures where capture_id=(p_payload->'envelope'->>'capture_id')::uuid;
   if found then
     if x.worker_id<>w.worker_id or x.run_id<>(p_payload->>'run_id')::uuid or x.lease_epoch<>(p_payload->>'lease_epoch')::integer or x.envelope_hash<>p_payload->>'envelope_hash' then raise exception 'capture_hash_conflict'; end if;
     return jsonb_build_object('receipt',x.receipt,'replayed',true);
   end if;
 end if;
 -- All remaining worker operations bind to the registered worker, immutable run and epoch.
 select * into c from crowd_machine.children where run_id=(p_payload->>'run_id')::uuid and worker_id=w.worker_id for update;
 if not found or c.lease_epoch<>(p_payload->>'lease_epoch')::integer then raise exception 'lease_binding_denied'; end if;
 if p_action in ('capture','finish','resume_login') and exists(select 1 from crowd_machine.resolutions where worker_id=w.worker_id and run_id=c.run_id and lease_epoch=c.lease_epoch) then raise exception 'run_reconciled_no_dispatch'; end if;
 select * into t from crowd_machine.tasks where task_id=c.task_id and owner_scope=p_owner_scope;
 if not found then raise exception 'principal_denied'; end if;
 now_at=clock_timestamp();
 if p_action='receipt' then
   select * into x from crowd_machine.captures where capture_id=(p_payload->>'capture_id')::uuid and worker_id=w.worker_id and run_id=c.run_id;
   if not found then return jsonb_build_object('receipt',null); end if;
   if x.envelope_hash<>p_payload->>'envelope_hash' then raise exception 'capture_hash_conflict'; end if;
   return jsonb_build_object('receipt',x.receipt);
 elsif p_action='capture' then
   envelope=p_payload->'envelope';v_id=(envelope->>'capture_id')::uuid;v_hash=p_payload->>'envelope_hash';
   select * into x from crowd_machine.captures where capture_id=v_id;
   if found then
     if x.worker_id<>w.worker_id or x.run_id<>c.run_id or x.envelope_hash<>v_hash then raise exception 'capture_hash_conflict'; end if;
     return jsonb_build_object('receipt',x.receipt,'replayed',true);
   end if;
   if envelope->>'schema'<>'crowd-machine-capture-v1' or envelope->>'source_kind'<>'machine_api' or envelope->>'task_id'<>t.task_id::text or envelope->>'child_id'<>c.child_id::text or envelope->>'run_id'<>c.run_id::text or (envelope->>'lease_epoch')::integer<>c.lease_epoch or envelope->>'delivery_basis'<>t.proposal->>'delivery_basis' or envelope->'record'->>'reward_eligible'<>'false' or envelope->'record'->>'source_kind'<>'mediacrawler_api' or envelope->'record'->>'platform'<>envelope->>'platform' or envelope->>'platform'<>(jsonb_build_object('xhs','xiaohongshu','dy','douyin','ks','kuaishou','bili','bilibili','wb','weibo','tieba','tieba','zhihu','zhihu')->>c.platform) then raise exception 'invalid_capture'; end if;
   if c.recovery_id is not null and envelope->'record'->>'content_id' is distinct from (select source_content_id from crowd_machine.recoveries where recovery_id=c.recovery_id) then raise exception 'invalid_capture'; end if;
   if octet_length(p_payload->>'canonical_envelope')>262144 or (p_payload->>'canonical_envelope')::jsonb<>envelope or encode(sha256(convert_to('crowd-machine-capture-v1'||chr(10)||(p_payload->>'canonical_envelope'),'UTF8')),'hex')<>v_hash then raise exception 'capture_hash_conflict'; end if;
   -- Delivery is allowed after source authorization ends, for a bounded cached outbox window.
   -- It never renews the lease or authorizes another source action.
   if c.lease_until is null or now_at>c.lease_until+interval '24 hours' then raise exception 'delivery_window_expired'; end if;
   receipt=jsonb_build_object('capture_id',v_id,'envelope_hash',v_hash,'task_id',t.task_id,'child_id',c.child_id,'run_id',c.run_id,'lease_epoch',c.lease_epoch,'status','received','source_kind','machine_api','reward_eligible',false,'received_at',now_at);
   insert into crowd_machine.captures(capture_id,owner_scope,worker_id,task_id,child_id,run_id,lease_epoch,envelope_hash,canonical_envelope,envelope,receipt)
   values(v_id,p_owner_scope,w.worker_id,t.task_id,c.child_id,c.run_id,c.lease_epoch,v_hash,p_payload->>'canonical_envelope',envelope,receipt);
   return jsonb_build_object('receipt',receipt,'replayed',false);
 elsif p_action='heartbeat' then
   if c.state='running' and c.lease_until<=now_at then update crowd_machine.children set state='unknown',reason_code='lease_expired_source_outcome_unknown' where child_id=c.child_id returning * into c; end if;
   if c.state='running' and c.lease_until>now_at and t.desired_state='running' and (p_payload->>'sequence')::bigint>c.heartbeat_seq then
     if p_payload ? 'local_run_id' and c.local_run_id is not null and c.local_run_id::text is distinct from p_payload->>'local_run_id' then raise exception 'lease_binding_denied'; end if;
     update crowd_machine.children set heartbeat_seq=(p_payload->>'sequence')::bigint,lease_until=now_at+interval '90 seconds',local_run_id=coalesce(local_run_id,(p_payload->>'local_run_id')::uuid) where child_id=c.child_id;
     update crowd_machine.claims set local_run_id=coalesce(local_run_id,(p_payload->>'local_run_id')::uuid)
       where worker_id=w.worker_id and run_id=c.run_id and lease_epoch=c.lease_epoch;
   end if;
   return jsonb_build_object('lease',crowd_machine.lease_view(c.child_id));
 elsif p_action='resume_login' then
   expected_scope=c.local_run_id;
   if expected_scope is null and c.recovery_id is not null then
     select * into recovery from crowd_machine.recoveries where recovery_id=c.recovery_id;
     select * into claimed from crowd_machine.claims where worker_id=w.worker_id and run_id=c.run_id and lease_epoch=c.lease_epoch;
     if recovery.source_worker_id=w.worker_id and (recovery.account_context='{}'::jsonb or recovery.account_context=c.account_context) and claimed.local_run_id is null and claimed.outcome='login_required' and claimed.api_attempts=0
        and not exists(select 1 from crowd_machine.captures where run_id=c.run_id) then expected_scope=crowd_machine.supplemental_scope(c.child_id); end if;
   end if;
   if not(c.state='waiting' and c.reason_code='login_required' or c.state='queued' and c.reason_code='same_account_resumed') or c.finished_at is null or t.desired_state<>'running' or c.requests_reserved<>0 or c.requests_spent>=(c.plan->>'request_quota')::integer or expected_scope is null or expected_scope::text is distinct from p_payload->>'local_run_id' or c.account_context->>'session_id' is distinct from p_payload->>'session_id' or c.account_context->>'generation' is distinct from p_payload->>'generation' or c.account_context->'account_ref' is distinct from p_payload->'account_ref' or c.account_context->>'generation' is null or (c.account_context->>'generation')::integer<0 or ((c.account_context->>'generation')::integer=0 and (c.account_context->'account_ref' is distinct from 'null'::jsonb or p_payload->>'identity_status' is distinct from 'manually_confirmed_same_account')) or (c.account_context->'account_ref'='null'::jsonb and p_payload->>'identity_status' is distinct from 'manually_confirmed_same_account') or jsonb_typeof(p_payload->'verified_at_ms') is distinct from 'number' or coalesce(p_payload->>'verified_at_ms','') !~ '^[0-9]{1,16}$' or (p_payload->>'verified_at_ms')::bigint>9007199254740991 or (extract(epoch from clock_timestamp())*1000)-(p_payload->>'verified_at_ms')::bigint not between 0 and 180000 or p_payload->>'authorized_for_run' is distinct from expected_scope::text then raise exception 'login_resume_denied'; end if;
   if c.state='queued' and c.reason_code='same_account_resumed' then return jsonb_build_object('resumed',true,'replayed',true,'task',crowd_machine.public_task(t.task_id)); end if;
   update crowd_machine.children set state='queued',reason_code='same_account_resumed' where child_id=c.child_id;
   return jsonb_build_object('resumed',true,'task',crowd_machine.public_task(t.task_id));
 elsif p_action='finish' then
   v_hash=p_payload->>'finish_hash';
   if c.finish_hash is not null then
     if c.finish_hash<>v_hash then raise exception 'finish_conflict'; end if;
     return jsonb_build_object('task',crowd_machine.public_task(t.task_id),'replayed',true);
   end if;
   ids=p_payload->'capture_ids';
   if jsonb_typeof(ids)<>'array' or jsonb_array_length(ids)>2000 or exists(select 1 from jsonb_array_elements_text(ids) v where not exists(select 1 from crowd_machine.captures cx where cx.capture_id=v::uuid and cx.run_id=c.run_id and cx.worker_id=w.worker_id)) then raise exception 'unacknowledged_capture'; end if;
   select count(distinct concat(envelope->'record'->>'kind',':',envelope->'record'->>'content_id')) into content_count from crowd_machine.captures where child_id=c.child_id and envelope->'record'->>'kind' in ('content','dynamic') and length(btrim(coalesce(envelope->'record'->>'body','')||coalesce(envelope->'record'->>'title','')||coalesce(envelope->'record'->>'text','')))>0;
   if p_payload->>'outcome' not in ('completed','stopped','failed','unknown','login_required') then raise exception 'invalid_request'; end if;
   update crowd_machine.children set
    state=case when p_payload->>'outcome'='unknown' or c.state='unknown' then 'unknown' when t.desired_state='stopped' or p_payload->>'outcome'='stopped' then 'stopped' when p_payload->>'outcome'='failed' then 'failed' when p_payload->>'outcome'='login_required' then 'waiting' when content_count>=(plan->>'item_quota')::integer then 'completed' else 'waiting' end,
    reason_code=case when p_payload->>'outcome'='unknown' or c.state='unknown' then 'source_outcome_unknown' when p_payload->>'outcome'='login_required' then 'login_required' when content_count=0 then 'no_content_observed' when content_count<(plan->>'item_quota')::integer then 'observed_window_partial' else null end,
    requests_spent=requests_spent+least(requests_reserved,greatest(0,(p_payload->>'api_attempts')::integer)),requests_reserved=case when p_payload->>'outcome'='unknown' or c.state='unknown' then requests_reserved else 0 end,account_context=coalesce(p_payload->'account_context',account_context),finish_hash=v_hash,finished_at=clock_timestamp()
    where child_id=c.child_id;
   update crowd_machine.claims set local_run_id=c.local_run_id,outcome=p_payload->>'outcome',
     api_attempts=greatest(0,(p_payload->>'api_attempts')::integer),finished_at=clock_timestamp()
     where worker_id=w.worker_id and run_id=c.run_id and lease_epoch=c.lease_epoch;
   -- Unknown source outcomes retain the full reservation. Known terminal attempts may release unused budget.
   return jsonb_build_object('task',crowd_machine.public_task(t.task_id),'replayed',false);
 end if;
 raise exception 'invalid_request';
end $$;
revoke all on all functions in schema crowd_machine from public, anon, authenticated;
grant execute on all functions in schema crowd_machine to service_role;
revoke all on function public.crowd_machine_rpc(text,text,text,text,jsonb) from public, anon, authenticated;
grant execute on function public.crowd_machine_rpc(text,text,text,text,jsonb) to service_role;
