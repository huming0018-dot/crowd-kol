-- Additive RPC recovery fix: existing records and permissions preserved.
create or replace function public.crowd_machine_rpc(p_owner_scope text,p_actor_kind text,p_worker_hash text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
#variable_conflict use_column
declare w crowd_machine.workers%rowtype; t crowd_machine.tasks%rowtype; c crowd_machine.children%rowtype;
 x crowd_machine.captures%rowtype; claimed crowd_machine.claims%rowtype;
 v_proposal jsonb; item jsonb; v_id uuid; v_hash text; now_at timestamptz;
 envelope jsonb; receipt jsonb; content_count integer; ids jsonb;
begin
 if p_owner_scope<>'crowd-owner-main' or p_actor_kind not in ('owner','worker') or jsonb_typeof(p_payload)<>'object' then raise exception 'principal_denied'; end if;
 if p_actor_kind='worker' then
   select * into w from crowd_machine.workers where owner_scope=p_owner_scope and token_hash=p_worker_hash for update;
   if not found or not w.enabled or w.expires_at<=clock_timestamp() then raise exception 'worker_revoked'; end if;
   if p_action not in ('claim','heartbeat','capture','receipt','finish','resume_login') then raise exception 'principal_denied'; end if;
 else
   if p_action not in ('task_create','task_list','task_status','task_control','worker_pair','worker_revoke','worker_list','results') then raise exception 'principal_denied'; end if;
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
       insert into crowd_machine.claims(worker_id,claim_id,child_id,run_id,lease_epoch) values(w.worker_id,v_id,c.child_id,c.run_id,c.lease_epoch);
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
   if not(c.state='waiting' and c.reason_code='login_required' or c.state='queued' and c.reason_code='same_account_resumed') or c.finished_at is null or t.desired_state<>'running' or c.requests_reserved<>0 or c.requests_spent>=(c.plan->>'request_quota')::integer or c.local_run_id::text is distinct from p_payload->>'local_run_id' or c.account_context->>'session_id' is distinct from p_payload->>'session_id' or c.account_context->>'generation' is distinct from p_payload->>'generation' or c.account_context->'account_ref' is distinct from p_payload->'account_ref' or c.account_context->>'generation' is null or (c.account_context->>'generation')::integer<0 or ((c.account_context->>'generation')::integer=0 and (c.account_context->'account_ref' is distinct from 'null'::jsonb or p_payload->>'identity_status' is distinct from 'manually_confirmed_same_account')) or (c.account_context->'account_ref'='null'::jsonb and p_payload->>'identity_status' is distinct from 'manually_confirmed_same_account') or jsonb_typeof(p_payload->'verified_at_ms') is distinct from 'number' or coalesce(p_payload->>'verified_at_ms','') !~ '^[0-9]{1,16}$' or (p_payload->>'verified_at_ms')::bigint>9007199254740991 or (extract(epoch from clock_timestamp())*1000)-(p_payload->>'verified_at_ms')::bigint not between 0 and 180000 or p_payload->>'authorized_for_run' is distinct from c.local_run_id::text then raise exception 'login_resume_denied'; end if;
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
revoke all on function public.crowd_machine_rpc(text,text,text,text,jsonb) from public, anon, authenticated;
grant execute on function public.crowd_machine_rpc(text,text,text,text,jsonb) to service_role;
