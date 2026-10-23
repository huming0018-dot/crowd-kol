-- G07 candidate only. No production/source/authorization DML.
begin;
do $cas$ begin
 if md5(pg_get_functiondef('crowd_observation.pro_comment_capture_check(uuid,bigint,uuid,uuid,jsonb)'::regprocedure))<>'e93ddfb601b5deb5c78eba4a3c9cfacb' then raise exception 'g07_function_drift';end if;
 if (select proacl::text from pg_proc where oid='crowd_observation.pro_comment_capture_check(uuid,bigint,uuid,uuid,jsonb)'::regprocedure) is distinct from '{postgres=X/postgres}' then raise exception 'g07_acl_drift';end if;
 if md5(pg_get_functiondef('crowd_observation.pro_scope(bigint,uuid,uuid,boolean,boolean)'::regprocedure))<>'db494e9920e1786c3520166b717bf8ee' then raise exception 'g07_function_drift';end if;
 if (select proacl::text from pg_proc where oid='crowd_observation.pro_scope(bigint,uuid,uuid,boolean,boolean)'::regprocedure) is distinct from '{postgres=X/postgres}' then raise exception 'g07_acl_drift';end if;
 if md5(pg_get_functiondef('crowd_v4.acceptance_task_input(crowd_v4.tasks)'::regprocedure))<>'19cf256345c45861d180c86926efbfa8' then raise exception 'g07_function_drift';end if;
 if (select proacl::text from pg_proc where oid='crowd_v4.acceptance_task_input(crowd_v4.tasks)'::regprocedure) is distinct from '{postgres=X/postgres}' then raise exception 'g07_acl_drift';end if;
 if md5(pg_get_functiondef('public.crowd_unified_dispatch_rpc(text,text,text,jsonb)'::regprocedure))<>'f40b66b4816953b6d47f47d66b4e5162' then raise exception 'g07_function_drift';end if;
 if (select proacl::text from pg_proc where oid='public.crowd_unified_dispatch_rpc(text,text,text,jsonb)'::regprocedure) is distinct from '{postgres=X/postgres,service_role=X/postgres}' then raise exception 'g07_acl_drift';end if;
 if md5(pg_get_functiondef('public.crowd_v4_node_claim(uuid,bigint)'::regprocedure))<>'074905eb5e0f0522246d336d620a29f3' then raise exception 'g07_function_drift';end if;
 if (select proacl::text from pg_proc where oid='public.crowd_v4_node_claim(uuid,bigint)'::regprocedure) is distinct from '{postgres=X/postgres,authenticated=X/postgres}' then raise exception 'g07_acl_drift';end if;
 if md5(pg_get_functiondef('public.crowd_v4_pro_claim(bigint,uuid)'::regprocedure))<>'22cf4501c2582446881f09248667ecd6' then raise exception 'g07_function_drift';end if;
 if (select proacl::text from pg_proc where oid='public.crowd_v4_pro_claim(bigint,uuid)'::regprocedure) is distinct from '{postgres=X/postgres,authenticated=X/postgres,service_role=X/postgres}' then raise exception 'g07_acl_drift';end if;
 if md5(pg_get_functiondef('public.crowd_v4_node_register(uuid,jsonb)'::regprocedure))<>'29867137f489440490aad3b494f5d6d4' then raise exception 'g07_function_drift';end if;
 if (select proacl::text from pg_proc where oid='public.crowd_v4_node_register(uuid,jsonb)'::regprocedure) is distinct from '{postgres=X/postgres,authenticated=X/postgres}' then raise exception 'g07_acl_drift';end if;
end $cas$;
alter table crowd_v4.nodes add column pro_capabilities jsonb,add column pro_capability_at timestamptz;
-- Capability is an account-bound feature declaration, NOT remote execution attestation.
create or replace function crowd_observation.pro_capability_valid(v jsonb) returns boolean language sql immutable set search_path='' as $$
 select coalesce(jsonb_typeof(v)='object' and v-array['schema','runtime_sha256','entry_sha256','worker_sha256','upstream_commit','comment_options_v1','max_api_requests']='{}'::jsonb
 and v?&array['schema','runtime_sha256','entry_sha256','worker_sha256','upstream_commit','comment_options_v1','max_api_requests']
 and v->>'schema'='crowd-participant-pro-capability-v1' and v->'comment_options_v1'='true'::jsonb
 and v->>'runtime_sha256'~'^[a-f0-9]{64}$' and v->>'entry_sha256'~'^[a-f0-9]{64}$' and v->>'worker_sha256'~'^[a-f0-9]{64}$' and v->>'upstream_commit'~'^[a-f0-9]{40}$'
 and jsonb_typeof(v->'max_api_requests')='number' and v->>'max_api_requests'~'^(?:[1-9]|[1-9][0-9]|100)$',false)
$$;
create or replace function crowd_observation.pro_node_capable(p_user uuid,p_install uuid,p_quota integer) returns boolean language sql stable security definer set search_path='' as $$
 select exists(select from crowd_v4.nodes n where n.user_id=p_user and n.installation_id=p_install and n.enabled and n.login_state in('ready','unknown')
 and n.release_digest~'^[a-f0-9]{64}$' and n.pro_capability_at>now()-interval '120 seconds' and n.pro_capability_at<=now()
 and crowd_observation.pro_capability_valid(n.pro_capabilities)
 and n.pro_capabilities->>'runtime_sha256'='a72d375f60a19e0c3ef131751a7dea584830a0a624afe81eaf768603d804d2b2' and n.pro_capabilities->>'worker_sha256'='60ef9cb86e8d6f76b260f6faf75a054338fd3d49663f7e228ffe565f14b259fe' and n.pro_capabilities->>'entry_sha256'='62d16fa096a23b79d6c62d6b757c7a4b909f62d6a947592d12ad418113afd12f'
 and n.pro_capabilities->>'upstream_commit'='d32dd565277116ba4880c28ccd417a7c376cb62d'
 and (n.pro_capabilities->>'max_api_requests')::integer>=p_quota and p_quota>0)
$$;
create or replace function crowd_observation.pro_task_comment_options(p_task bigint,p_install uuid,p_fresh boolean default true) returns jsonb language plpgsql security definer set search_path='' as $opts$
declare r record;bind jsonb;opt jsonb;quota integer;u uuid:=auth.uid();
begin
 select t.comments_capture,d.dispatch_id,d.request,d.request_hash,route into r
 from crowd_v4.tasks t join crowd_machine.unified_participant_tasks m on m.task_id=t.id join crowd_machine.unified_dispatches d using(dispatch_id)
 cross join lateral jsonb_array_elements(d.routes)route
 where t.id=p_task and route->>'platform'='xhs' and route->>'executor'='mediacrawler_pro' and route->>'required_capability'='crowd-participant-pro-comment-options-v1';
 if not found then return null;end if;
 bind:=r.route->'participant_bindings'->p_task::text;opt:=r.route->'comment_options';
 if not r.comments_capture or r.request->'comments'is distinct from'true'::jsonb or r.request_hash!~'^[a-f0-9]{64}$'
 or jsonb_typeof(opt)is distinct from'object' or opt-array['comments','replies','max_comments']<>'{}'::jsonb or not opt?&array['comments','replies','max_comments']
 or opt->'comments'is distinct from'true'::jsonb or jsonb_typeof(opt->'replies')is distinct from'boolean' or opt->'replies'is distinct from coalesce(r.request->'replies','false'::jsonb)
 or opt->'max_comments'is distinct from coalesce(r.request->'max_comments','20'::jsonb) or jsonb_typeof(opt->'max_comments')is distinct from'number' or coalesce(opt->>'max_comments','')!~'^[0-9]{1,16}$' or (opt->>'max_comments')::bigint>9007199254740991
 or jsonb_typeof(r.route->'request_quota')is distinct from'number' or coalesce(r.route->>'request_quota','')!~'^[0-9]{1,3}$'
 or jsonb_typeof(bind)is distinct from'object' or bind-array['subject','installation_id','capabilities']<>'{}'::jsonb
 or bind->>'subject'is distinct from u::text or bind->>'installation_id'is distinct from p_install::text or not crowd_observation.pro_capability_valid(bind->'capabilities')
 or not exists(select from crowd_v4.participant_pro_batches b where b.task_id=p_task and b.user_id=u and b.installation_id=p_install)
 then raise exception 'participant_task_options_invalid';end if;
 quota:=(r.route->>'request_quota')::integer;
 if quota<1 or quota>(bind#>>'{capabilities,max_api_requests}')::integer then raise exception 'participant_task_options_invalid';end if;
 if p_fresh and (not crowd_observation.pro_node_capable(u,p_install,quota) or not exists(select from crowd_v4.nodes n where n.user_id=u and n.installation_id=p_install and n.pro_capabilities=bind->'capabilities')) then raise exception 'participant_capability_required';end if;
 return jsonb_build_object('schema','crowd-participant-pro-comment-options-v1','task_id',p_task,'dispatch_id',r.dispatch_id,'request_hash',r.request_hash,'comments',true,'replies',opt->'replies','max_comments',opt->'max_comments','max_api_requests',quota);
end $opts$;
revoke all on function crowd_observation.pro_capability_valid(jsonb),crowd_observation.pro_node_capable(uuid,uuid,integer),crowd_observation.pro_task_comment_options(bigint,uuid,boolean) from public,anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION public.crowd_v4_node_register(p_installation uuid, p_state jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare u uuid:=auth.uid(); n crowd_v4.nodes; opted boolean;
begin
 if u is null then raise exception 'login_required'; end if;
 perform 1 from crowd_v4.participants where user_id=u and consent='crowd-public-v4' for update;
 if not found then raise exception 'consent_required'; end if;
 if p_installation is null or jsonb_typeof(p_state) is distinct from 'object'
 or (p_state-array['version','enabled','login_state','release_digest','pro_capabilities'])<>'{}'::jsonb
 or coalesce(p_state->>'version','') !~ '^4\.[0-9]{1,3}\.[0-9]{1,3}$'
 or jsonb_typeof(p_state->'enabled') is distinct from 'boolean'
 or coalesce(p_state->>'login_state','') not in ('ready','needs_login','verification','unknown')
 or (p_state->>'release_digest' is not null and p_state->>'release_digest' !~ '^[a-f0-9]{64}$')
 or (p_state?'pro_capabilities' and (not crowd_observation.pro_capability_valid(p_state->'pro_capabilities') or coalesce(p_state->>'release_digest','')!~'^[a-f0-9]{64}$'))
 then raise exception 'invalid_node'; end if;
 select * into n from crowd_v4.nodes where installation_id=p_installation for update;
 if found and n.user_id<>u then raise exception 'node_binding_denied'; end if;
 if n.installation_id is null and (select count(*) from crowd_v4.nodes where user_id=u)>=10 then raise exception 'node_limit'; end if;
 insert into crowd_v4.nodes(installation_id,user_id,version,enabled,login_state,release_digest,pro_capabilities,pro_capability_at)
 values(p_installation,u,p_state->>'version',(p_state->>'enabled')::boolean,p_state->>'login_state',p_state->>'release_digest',p_state->'pro_capabilities',case when p_state?'pro_capabilities' then now() else null end)
 on conflict(installation_id) do update set version=excluded.version,enabled=excluded.enabled,
 login_state=excluded.login_state,release_digest=excluded.release_digest,pro_capabilities=excluded.pro_capabilities,pro_capability_at=excluded.pro_capability_at,updated_at=now()
 where crowd_v4.nodes.user_id=u returning * into n;
 if not found then raise exception 'node_binding_denied'; end if;
 select coalesce((select enabled from crowd_v4.diagnostics where user_id=u),false) into opted;
 return jsonb_build_object('schema','crowd-node-v1','registered',true,'installation_id',p_installation,'diagnostics_enabled',opted,'max_node_seq',coalesce(n.max_node_seq,0));
end $function$
;
CREATE OR REPLACE FUNCTION public.crowd_unified_dispatch_rpc(p_owner_scope text, p_actor_kind text, p_action text, p_payload jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare old crowd_machine.unified_dispatches; proposal jsonb; participant jsonb; machine jsonb;
 cohort text; needed integer; remaining integer; total_available integer; ids bigint[]:='{}'; selected_task crowd_v4.tasks;
 routes jsonb:='[]'; child jsonb; reason text; v_dispatch uuid; pro_mode boolean; bindings jsonb:='{}';cap jsonb;node_user uuid;node_install uuid; machine_result jsonb; machine_id uuid; key text;
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
 if p_action not in ('unified_preview','unified_create') or (p_payload-array['proposal','participant','machine_proposal','machine_fallback'])<>'{}'::jsonb then raise exception 'invalid_request'; end if;
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
 pro_mode:=participant->>'executor'='mediacrawler_pro';
 if pro_mode and (participant->>'required_capability'is distinct from'crowd-participant-pro-comment-options-v1'
  or participant->'comment_options'is distinct from jsonb_build_object('comments',true,'replies',coalesce(proposal#>'{request,replies}','false'::jsonb),'max_comments',coalesce(proposal#>'{request,max_comments}','20'::jsonb))
  or proposal#>'{request,comments}'is distinct from'true'::jsonb
  or not exists(select from jsonb_array_elements(proposal->'children')ch where ch->>'platform'='xhs' and ch->'request_quota'=participant->'request_quota' and ch->'item_quota'=participant->'item_quota')) then raise exception 'participant_task_options_invalid';end if;
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
       and candidate.available_at<=now() and not candidate.structured_capture
       and (coalesce(pro_mode,false) and candidate.comments_capture and candidate.source_executor='mediacrawler_pro' and exists(select from crowd_v4.participant_pro_batches b where b.task_id=candidate.id and not b.revoked and b.expires_at>now() and b.target=candidate.target and b.baseline_task=crowd_v4.acceptance_task_input(candidate) and crowd_observation.pro_node_capable(b.user_id,b.installation_id,(participant->>'request_quota')::integer)) or not coalesce(pro_mode,false) and not candidate.comments_capture)
       and candidate.query in(select jsonb_array_elements_text(participant->'targets'))
       and not exists(select 1 from crowd_machine.unified_participant_tasks used where used.task_id=candidate.id)
      order by candidate.last_claimed_at nulls first,candidate.id for update of candidate skip locked loop
      if selected_task.target<=remaining then
       if pro_mode then
        select b.user_id,b.installation_id,n.pro_capabilities into node_user,node_install,cap from crowd_v4.participant_pro_batches b join crowd_v4.nodes n on n.installation_id=b.installation_id and n.user_id=b.user_id
        where b.task_id=selected_task.id and crowd_observation.pro_node_capable(b.user_id,b.installation_id,(participant->>'request_quota')::integer);
        if not found then raise exception 'participant_capability_required';end if;
        bindings:=bindings||jsonb_build_object(selected_task.id::text,jsonb_build_object('subject',node_user,'installation_id',node_install,'capabilities',cap));
       end if;
       ids:=array_append(ids,selected_task.id);remaining:=remaining-selected_task.target;end if;
      exit when remaining=0;
     end loop;
     if remaining<>0 then reason:=case when pro_mode and exists(select from crowd_v4.tasks q join crowd_v4.pilot_task_map pm on pm.task_id=q.id join crowd_v4.participant_pro_batches b on b.task_id=q.id where pm.invite_hash=cohort and q.comments_capture and q.status='open' and q.query in(select jsonb_array_elements_text(participant->'targets'))) then 'participant_capability_required' else 'participant_target_unavailable' end;end if;
    end if;
   end if;
  end if;
 end if;
 if pro_mode and reason is not null then
  machine:=p_payload->'machine_fallback';
  if (participant#>>'{comment_options,max_comments}')::bigint=0 or (participant#>>'{comment_options,max_comments}')::bigint>200 then
   if machine is not null and machine<>'null'::jsonb then raise exception 'invalid_request';end if;
   reason:='owner_pro_comment_options_unavailable';
  else
  if jsonb_typeof(machine)is distinct from'object' or machine->'children'is distinct from proposal->'children'
   or (machine->'request')-'idempotency_key' is distinct from (proposal->'request')-'idempotency_key'
   or machine#>>'{request,idempotency_key}'is distinct from'unified:'||(proposal->>'request_hash')
   then raise exception 'invalid_request';end if;
  participant:=null;ids:='{}';bindings:='{}';reason:=null;cohort:=null;
  end if;
 end if;
 for child in select value from jsonb_array_elements(proposal->'children') loop
  if child->>'platform'='xhs' and jsonb_typeof(participant)='object' then
   routes:=routes||jsonb_build_array(jsonb_build_object('platform','xhs','execution_kind','participant_extension','item_quota',child->'item_quota',
    'request_quota',case when pro_mode then participant->'request_quota' else null end,'state',case when reason is null then 'queued' else 'waiting' end,'reason_code',reason,'task_ids',to_jsonb(ids),'budget_basis','existing_pilot_guard')||case when pro_mode then jsonb_build_object('executor','mediacrawler_pro','required_capability','crowd-participant-pro-comment-options-v1','comment_options',participant->'comment_options','participant_bindings',bindings)else '{}'::jsonb end);
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
end $function$
;
CREATE OR REPLACE FUNCTION public.crowd_v4_node_claim(p_installation uuid, p_task bigint DEFAULT NULL::bigint)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare u uuid:=auth.uid(); n crowd_v4.nodes; r crowd_v4.node_runs; result jsonb; t crowd_v4.tasks;
begin
 if u is null then raise exception 'login_required'; end if;
 -- Same lock order as original claim: participant, then task. Registration and events follow it too.
 perform 1 from crowd_v4.participants where user_id=u for update;
 select * into n from crowd_v4.nodes where installation_id=p_installation and user_id=u;
 if not found then raise exception 'node_binding_denied'; end if;
 -- enabled is a cached status, not an authorization gate. Original claim/guard and local
 -- manual-stop control source work; old outbox delivery can still renew its original task.
 if coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)>0 and
  ((crowd_v4.acceptance_supplement_view(p_task,u)->>'installation_id')::uuid<>p_installation or p_task is not null and (crowd_v4.acceptance_supplement_view(p_task,u)->>'task_id')::bigint<>p_task) then raise exception 'node_binding_denied'; end if;
 begin
 result:=public.crowd_v4_claim(p_task);
 if jsonb_typeof(result->'task')='object' then perform crowd_observation.pro_task_comment_options((result->'task'->>'id')::bigint,p_installation,true);end if;
 exception when others then
  if sqlerrm='participant_capability_required' then return jsonb_build_object('error','participant_capability_required','task',null);else raise;end if;
 end;
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
end $function$
;
CREATE OR REPLACE FUNCTION public.crowd_v4_pro_claim(p_task bigint, p_installation_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare t crowd_v4.tasks;r jsonb;
begin
 t:=crowd_observation.pro_scope(p_task,p_installation_id);
 if t.received>=t.target then return jsonb_build_object('error','task_full');end if;
 r:=public.crowd_v4_node_claim(p_installation_id,p_task);
 if jsonb_typeof(r->'task')='object' and (r->'task'->>'id')::bigint=p_task then
  update crowd_v4.tasks set source_executor='mediacrawler_pro' where id=p_task;
  if crowd_observation.pro_task_comment_options(p_task,p_installation_id,true) is not null then r:=r||jsonb_build_object('pro_comment_options',crowd_observation.pro_task_comment_options(p_task,p_installation_id,true));end if;
  r:=jsonb_set(r,'{task,source_executor}','"mediacrawler_pro"')||jsonb_build_object('known_note_ids',(select coalesce(jsonb_agg(note_id order by note_id),'[]'::jsonb) from crowd_v4.proofs where task_id=p_task and user_id=auth.uid()));
 end if;
 return r||jsonb_build_object('source_executor','mediacrawler_pro','reward_eligible',false);
end $function$
;
CREATE OR REPLACE FUNCTION crowd_observation.pro_comment_capture_check(p_user uuid, p_task bigint, p_installation_id uuid, p_parent uuid, p_record jsonb)
 RETURNS void
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare obj jsonb;pg jsonb;x record;r crowd_observation.receipts;ids text[]:='{}';requests uuid[]:='{}';page_ids text[]:='{}';chains jsonb:='{}';chain text;last jsonb;coverage text:=p_record#>>'{coverage,coverage}';root_ids text[]:='{}';root_cursors text[]:='{}';rp jsonb;reply_count integer;reply_unique integer;reply_first jsonb;reply_expected bigint;reply boolean:=p_record#>'{resolved_native_options,replies}'='true'::jsonb;
begin
 declare authority jsonb;begin
  authority:=crowd_observation.pro_task_comment_options(p_task,p_installation_id,false);
  if authority is not null and p_record->'resolved_native_options'is distinct from authority-array['schema','task_id','dispatch_id','request_hash','max_api_requests'] then raise exception 'comment_capture_options_mismatch';end if;
 end;
 if p_record-array['kind','platform','content_id','source_kind','reward_eligible','origin','objects','pages','source_pagination_sha256','coverage','resolved_native_options','record_hash']<>'{}'::jsonb
 or not p_record?&array['kind','platform','content_id','source_kind','reward_eligible','origin','objects','pages','source_pagination_sha256','coverage','resolved_native_options','record_hash']
 or jsonb_typeof(p_record->'origin')is distinct from'object' or(p_record->'origin')-array['run_id']<>'{}'::jsonb
 or jsonb_typeof(p_record->'objects') is distinct from 'array' or jsonb_typeof(p_record->'pages') is distinct from 'array' or jsonb_array_length(p_record->'pages')>1000 or jsonb_array_length(p_record->'objects')>10000
 or (jsonb_array_length(p_record->'pages')>0 and coalesce(p_record->>'source_pagination_sha256','')!~'^[a-f0-9]{64}$') or jsonb_typeof(p_record->'coverage') is distinct from 'object'
 or (p_record->'coverage')-array['coverage','reason']<>'{}'::jsonb or not(p_record->'coverage')?&array['coverage','reason']
 or coalesce(coverage,'') not in ('exhausted','limit_reached','partial','unknown')or jsonb_typeof(p_record#>'{coverage,reason}') is distinct from 'string' or coalesce(p_record#>>'{coverage,reason}','')!~'^[a-z_]{1,100}$'
 or jsonb_typeof(p_record->'resolved_native_options') is distinct from 'object' or(p_record->'resolved_native_options')-array['comments','replies','max_comments']<>'{}'::jsonb
 or not(p_record->'resolved_native_options')?&array['comments','replies','max_comments']or p_record#>'{resolved_native_options,comments}'is distinct from 'true'::jsonb
 or jsonb_typeof(p_record#>'{resolved_native_options,replies}')is distinct from 'boolean' or jsonb_typeof(p_record#>'{resolved_native_options,max_comments}') is distinct from 'number' or coalesce(p_record#>>'{resolved_native_options,max_comments}','')!~'^[0-9]{1,16}$' or (p_record#>>'{resolved_native_options,max_comments}')::numeric>9007199254740991
 then raise exception 'invalid_comment_capture';end if;
 if jsonb_array_length(p_record->'pages')=0 then
  if jsonb_array_length(p_record->'objects')<>0 or p_record->'source_pagination_sha256'is distinct from'null'::jsonb or coalesce(coverage,'') not in('partial','unknown')or exists(select from crowd_observation.receipts where user_id=p_user and parent_request=p_parent and kind='pro_comment')then raise exception 'invalid_comment_capture';end if;return;
 end if;
 for obj in select value from jsonb_array_elements(p_record->'objects')loop
  if jsonb_typeof(obj) is distinct from 'object' or obj-array['request','comment_id','record_hash']<>'{}'::jsonb or not obj?&array['request','comment_id','record_hash']then raise exception 'invalid_comment_capture';end if;
  begin
   if(obj->>'request')::uuid=any(requests)or obj->>'comment_id'=any(ids)then raise exception 'invalid_comment_capture';end if;
   requests:=array_append(requests,(obj->>'request')::uuid);ids:=array_append(ids,obj->>'comment_id');
  exception when others then raise exception 'invalid_comment_capture';end;
  select * into r from crowd_observation.receipts where user_id=p_user and request=(obj->>'request')::uuid;
  if r.request is null or r.kind<>'pro_comment' or r.parent_request is distinct from p_parent or r.data->>'task' is distinct from p_task::text or r.data->>'installation_id' is distinct from p_installation_id::text
  or r.data#>>'{pro_payload,provenance,local_run_id}' is distinct from p_record#>>'{origin,run_id}' or r.result->>'comment_id' is distinct from obj->>'comment_id' or r.result->>'record_hash' is distinct from obj->>'record_hash'
  or r.result->>'gate' is distinct from 'comment_received' or r.result->'inserted' is distinct from 'true'::jsonb or r.result->'duplicate' is distinct from 'false'::jsonb then raise exception 'comment_capture_objects_mismatch';end if;
 end loop;
 if (select count(*)from crowd_observation.receipts where user_id=p_user and parent_request=p_parent and kind='pro_comment')<>cardinality(requests)then raise exception 'comment_capture_objects_mismatch';end if;
 for pg in select value from jsonb_array_elements(p_record->'pages')loop
  if jsonb_typeof(pg) is distinct from 'object' or pg-array['checkpoint_committed','content_id','cursor_in','cursor_out','embedded','has_more','ids','invalid','parent_id','pinned_gap','reply_cursor_start','reply_roots','saved','scope']<>'{}'::jsonb
  or not pg?&array['checkpoint_committed','content_id','cursor_in','cursor_out','embedded','has_more','ids','invalid','parent_id','pinned_gap','reply_roots','saved','scope']
  or jsonb_typeof(pg->'embedded')is distinct from'boolean' or jsonb_typeof(pg->'reply_roots')is distinct from'object' or (pg->>'scope'='root'and pg->'parent_id'is distinct from'null'::jsonb) or (pg->>'scope'='reply'and coalesce(pg->>'parent_id','')!~'^[a-f0-9]{24}$')
  or pg->>'content_id' is distinct from p_record->>'content_id' or coalesce(pg->>'scope','') not in('root','reply')or jsonb_typeof(pg->'ids')is distinct from'array'
  or jsonb_typeof(pg->'saved')is distinct from'boolean'or jsonb_typeof(pg->'checkpoint_committed')is distinct from'boolean'
  or jsonb_typeof(pg->'has_more')is distinct from'boolean'or jsonb_typeof(pg->'invalid')is distinct from'boolean'or jsonb_typeof(pg->'pinned_gap')is distinct from'boolean'
  then raise exception 'invalid_comment_pages';end if;
  if jsonb_array_length(pg->'ids')<>(select count(distinct value)from jsonb_array_elements_text(pg->'ids')) or (pg->>'scope'='reply'and not reply) or length(pg->>'cursor_in')>512 or length(pg->>'cursor_out')>512 then raise exception 'invalid_comment_pages';end if;
  chain:=(pg->>'scope')||':'||coalesce(pg->>'parent_id','');last:=chains->chain;
  if last is not null and pg->'cursor_in' is distinct from last->'cursor_out'then raise exception 'invalid_comment_pages';end if;
  if last is not null and last->'has_more'='false'::jsonb then raise exception 'invalid_comment_pages';end if;
  if jsonb_typeof(pg->'cursor_in')not in('null','string')or jsonb_typeof(pg->'cursor_out')is distinct from'string' or exists(select from jsonb_array_elements(pg->'ids')e where jsonb_typeof(e)is distinct from'string' or(e#>>'{}')!~'^[a-f0-9]{24}$')then raise exception 'invalid_comment_pages';end if;
  chains:=jsonb_set(chains,array[chain],pg);
  if pg->'saved'='false'::jsonb and coverage not in('partial','unknown')then raise exception 'comment_capture_incomplete';end if;
  if pg->'saved'='true'::jsonb then
  for x in select value from jsonb_array_elements_text(pg->'ids')loop
   if not x.value=any(page_ids)then page_ids:=array_append(page_ids,x.value);end if;
   if not x.value=any(ids)then raise exception 'comment_capture_pages_mismatch';end if;
   if not exists(select from crowd_observation.receipts cr where cr.user_id=p_user and cr.parent_request=p_parent and cr.kind='pro_comment'and cr.result->>'comment_id'=x.value
    and(case when pg->>'scope'='root' then cr.data#>>'{pro_payload,record,parent_comment_id}'='' else cr.data#>>'{pro_payload,record,parent_comment_id}'=pg->>'parent_id'end))then raise exception 'comment_capture_parent_mismatch';end if;
  end loop;
  end if;
  if coverage='exhausted'and(pg->'saved'is distinct from'true'::jsonb or pg->'invalid'is distinct from'false'::jsonb or pg->'pinned_gap'is distinct from'false'::jsonb or(pg->>'scope'='root'and pg->'checkpoint_committed'is distinct from'true'::jsonb))then raise exception 'comment_capture_incomplete';end if;
 end loop;
 if not chains?'root:'or cardinality(page_ids)<>cardinality(ids)then raise exception 'comment_capture_pages_mismatch';end if;
 if coverage='exhausted' then
  for x in select value from jsonb_each(chains)loop if x.value->'has_more'is distinct from'false'::jsonb then raise exception 'comment_capture_incomplete';end if;end loop;
  for pg in select value from jsonb_array_elements(p_record->'pages')where value->>'scope'='root'loop
   if cardinality(root_cursors)=0 and pg->>'cursor_in'is distinct from'' then raise exception 'comment_capture_incomplete';end if;
   if coalesce(pg->>'cursor_in','')=any(root_cursors)or exists(select from jsonb_array_elements_text(pg->'ids')e where e.value=any(root_ids))then raise exception 'comment_capture_incomplete';end if;
   root_cursors:=array_append(root_cursors,pg->>'cursor_in');
   root_ids:=root_ids||array(select jsonb_array_elements_text(pg->'ids'));
   if (select count(*)from jsonb_object_keys(pg->'reply_roots'))<>jsonb_array_length(pg->'ids')or exists(select from jsonb_object_keys(pg->'reply_roots')k where not (pg->'ids')?k)then raise exception 'comment_capture_incomplete';end if;
   if reply and jsonb_typeof(pg->'reply_cursor_start')is distinct from'object'then raise exception 'comment_capture_incomplete';end if;
   for x in select key,value from jsonb_each(pg->'reply_roots')loop
    if jsonb_typeof(x.value)is distinct from'number'or x.value::text!~'^[0-9]{1,9}$'then raise exception 'comment_capture_incomplete';end if;
    reply_expected:=x.value::text::bigint;
    if reply then
     select count(e.value),count(distinct e.value)into reply_count,reply_unique from jsonb_array_elements(p_record->'pages')q cross join lateral jsonb_array_elements_text(q.value->'ids')e where q.value->>'scope'='reply'and q.value->>'parent_id'=x.key;
     select value into reply_first from jsonb_array_elements(p_record->'pages')where value->>'scope'='reply'and value->>'parent_id'=x.key limit 1;
     if reply_count<>reply_expected or reply_unique<>reply_expected or(reply_expected=0 and reply_first is not null)or(reply_expected>0 and reply_first is null)then raise exception 'comment_capture_incomplete';end if;
     if reply_first is not null and reply_first->'embedded'='false'::jsonb and reply_first->'cursor_in'is distinct from(pg->'reply_cursor_start')->x.key then raise exception 'comment_capture_incomplete';end if;
    end if;
   end loop;
  end loop;
  if exists(select from jsonb_array_elements(p_record->'pages')q where q.value->>'scope'='reply'and not(q.value->>'parent_id')=any(root_ids))then raise exception 'comment_capture_incomplete';end if;
 end if;
end $function$
;
commit;
