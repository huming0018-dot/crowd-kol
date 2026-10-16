begin;
DO $guard$ BEGIN IF md5(pg_get_functiondef('public.crowd_machine_rpc(text,text,text,text,jsonb)'::regprocedure)) IS DISTINCT FROM 'd18030f62b42827f28f8b02c7c81e4c3' THEN RAISE EXCEPTION 'baseline_changed'; END IF; END $guard$;
CREATE OR REPLACE FUNCTION public.crowd_machine_rpc(p_owner_scope text, p_actor_kind text, p_worker_hash text, p_action text, p_payload jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
#variable_conflict use_column
declare w crowd_machine.workers%rowtype; t crowd_machine.tasks%rowtype; c crowd_machine.children%rowtype;
 delivery crowd_machine.deliveries%rowtype;
 x crowd_machine.captures%rowtype; claimed crowd_machine.claims%rowtype;
 v_proposal jsonb; item jsonb; v_id uuid; v_hash text; now_at timestamptz;
 envelope jsonb; receipt jsonb; content_count integer; ids jsonb; resolution crowd_machine.resolutions%rowtype;
 recovery crowd_machine.recoveries%rowtype; expected_scope uuid; supplemental_request jsonb; target_id text;
 audited crowd_machine.terminal_audits%rowtype; audit_count integer; audit_digest text; quota integer; charged integer; released integer; final_state text; coverage jsonb;
 previous_grant crowd_machine.source_continuations%rowtype; chain_mode boolean; anchor_count integer; anchor_digest text;
begin
 if p_owner_scope<>'crowd-owner-main' or p_actor_kind not in ('owner','worker') or jsonb_typeof(p_payload)<>'object' then raise exception 'principal_denied'; end if;
 if p_actor_kind='worker' then
   select * into w from crowd_machine.workers where owner_scope=p_owner_scope and token_hash=p_worker_hash for update;
   if not found or not w.enabled or w.expires_at<=clock_timestamp() then raise exception 'worker_revoked'; end if;
   if p_action not in ('claim','heartbeat','capture','receipt','finish','resume_login','reconcile_no_dispatch','delivery_defer','delivery_resume') then raise exception 'principal_denied'; end if;
 else
   if p_action not in ('task_create','task_list','task_status','task_control','task_reconcile','retry_supplemental','continue_failed_source_preview','continue_failed_source','worker_pair','worker_revoke','worker_list','results') then raise exception 'principal_denied'; end if;
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
 elsif p_action='continue_failed_source_preview' then
   if p_payload-array['task_id','child_id']<>'{}'::jsonb or not(p_payload ?& array['task_id','child_id']) then raise exception 'source_continuation_denied'; end if;
   select * into t from crowd_machine.tasks where owner_scope=p_owner_scope and task_id=(p_payload->>'task_id')::uuid;
   if not found then raise exception 'task_not_found'; end if;
   select * into c from crowd_machine.children where task_id=t.task_id and child_id=(p_payload->>'child_id')::uuid;
   select * into claimed from crowd_machine.claims where worker_id=c.worker_id and run_id=c.run_id and lease_epoch=c.lease_epoch;
   if c.child_id is null or c.platform<>'wb' or c.plan->'request'->>'source_executor' is distinct from 'pro' or c.plan->'request'->>'mode' is distinct from 'detail'
      or c.plan->'request'->'comments' is distinct from 'true'::jsonb or c.plan->'request'->'replies' is distinct from 'true'::jsonb
      or c.state<>'failed' or c.finished_at is null or c.finish_hash is null or c.requests_reserved<>0 or c.requests_spent>=(c.plan->>'request_quota')::integer or c.local_run_id is null
      or claimed.claim_id is null or claimed.outcome is distinct from 'failed' or claimed.finished_at is null or claimed.local_run_id is distinct from c.local_run_id or claimed.api_attempts is null
      or t.desired_state<>'running' then raise exception 'source_continuation_denied'; end if;
   select count(*)::int,encode(sha256(convert_to('crowd-machine-capture-audit-v1'||chr(10)||coalesce(string_agg(capture_id::text||':'||envelope_hash,chr(10) order by capture_id::text),''),'UTF8')),'hex') into audit_count,audit_digest from crowd_machine.captures where child_id=c.child_id and run_id=c.run_id and worker_id=c.worker_id and lease_epoch=c.lease_epoch;
   if audit_count=0 then
    select * into previous_grant from crowd_machine.source_continuations sc where sc.task_id=t.task_id and sc.child_id=c.child_id and sc.source_worker_id=c.worker_id and sc.source_lease_epoch+1=c.lease_epoch;
    if previous_grant.continuation_id is null or previous_grant.proof ? 'chain' or previous_grant.proof->>'failure_reason'<>'wb_embedded_replies_incomplete'
     or c.account_context is distinct from previous_grant.account_context or claimed.api_attempts<=0
     or c.requests_spent is distinct from (previous_grant.proof->>'api_attempts')::int+claimed.api_attempts
     then raise exception 'source_continuation_denied';end if;
   end if;
   return jsonb_build_object('continuation_preview',jsonb_build_object('task_id',t.task_id,'child_id',c.child_id,'worker_id',c.worker_id,'claim_id',claimed.claim_id,'run_id',c.run_id,'lease_epoch',c.lease_epoch,'local_run_id',c.local_run_id,'expected_revision',t.revision,'expected_finish_hash',c.finish_hash,'capture_count',audit_count,'capture_digest',audit_digest,'account_context',c.account_context,'api_attempts',claimed.api_attempts,'requests_remaining',(c.plan->>'request_quota')::integer-c.requests_spent,'request',c.plan->'request'));
 elsif p_action='continue_failed_source' then
   select * into t from crowd_machine.tasks where owner_scope=p_owner_scope and task_id=(p_payload->>'task_id')::uuid for update;
   if not found then raise exception 'task_not_found'; end if;
   if not (p_payload ?& array['task_id','child_id','worker_id','claim_id','run_id','lease_epoch','local_run_id','expected_revision','idempotency_key','expected_finish_hash','capture_count','capture_digest','account_context','proof','audit_hash','canonical_audit'])
      or p_payload - array['task_id','child_id','worker_id','claim_id','run_id','lease_epoch','local_run_id','expected_revision','idempotency_key','expected_finish_hash','capture_count','capture_digest','account_context','proof','audit_hash','canonical_audit'] <> '{}'::jsonb
      or jsonb_typeof(p_payload->'proof') is distinct from 'object'
      or (p_payload->'proof')-array['continuation_kind','failure_reason','executor_inactive','local_state','exit_code','api_attempts','status_sha256','manifest_sha256','account_state_sha256','seed_sha256','runtime_sha256','identity_binding','chain']<>'{}'::jsonb
      or not(p_payload->'proof' ?& array['continuation_kind','failure_reason','executor_inactive','local_state','exit_code','api_attempts','status_sha256','manifest_sha256','account_state_sha256','seed_sha256','runtime_sha256','identity_binding'])
      or exists(select 1 from jsonb_each_text(p_payload->'proof') e where e.key in ('status_sha256','manifest_sha256','account_state_sha256','seed_sha256','runtime_sha256') and e.value !~ '^[a-f0-9]{64}$')
      or p_payload->'proof'->>'continuation_kind' is distinct from 'wb-replies-v1'
      or ((p_payload->'proof'->>'failure_reason'='wb_embedded_replies_incomplete' and not(p_payload->'proof' ? 'chain')) or
        (p_payload->'proof'->>'failure_reason'='wb_reply_page_shape_invalid' and jsonb_typeof(p_payload->'proof'->'chain')='object'
        and (p_payload->'proof'->'chain')-array['previous_continuation_id','seed_source_local_run_id','prior_api_attempts']='{}'::jsonb
        and (p_payload->'proof'->'chain') ?& array['previous_continuation_id','seed_source_local_run_id','prior_api_attempts']
        and jsonb_typeof(p_payload->'proof'->'chain'->'prior_api_attempts')='number'
        and coalesce(p_payload->'proof'->'chain'->>'prior_api_attempts','') ~ '^[1-9][0-9]{0,2}$'
        and p_payload->'proof'->>'identity_binding'='same_verified_subject')) is distinct from true
      or p_payload->'proof'->'executor_inactive' is distinct from 'true'::jsonb
      or p_payload->'proof'->>'local_state' is distinct from 'failed'
      or p_payload->'proof'->'exit_code' is distinct from '74'::jsonb
      or coalesce(p_payload->>'audit_hash','') !~ '^[a-f0-9]{64}$'
      or encode(sha256(convert_to('crowd-source-continuation-v1'||chr(10)||(p_payload->>'canonical_audit'),'UTF8')),'hex') is distinct from p_payload->>'audit_hash'
      or (p_payload->>'canonical_audit')::jsonb is distinct from p_payload-array['expected_revision','audit_hash','canonical_audit']
      then raise exception 'source_continuation_denied'; end if;
   if exists(select 1 from crowd_machine.source_continuations z where z.task_id=t.task_id and z.idempotency_key=p_payload->>'idempotency_key') then
     if not exists(select 1 from crowd_machine.source_continuations z where z.task_id=t.task_id and z.idempotency_key=p_payload->>'idempotency_key' and z.audit_hash=p_payload->>'audit_hash') then raise exception 'idempotency_conflict'; end if;
     return jsonb_build_object('replayed',true,'task',crowd_machine.public_task(t.task_id));
   end if;
   if (p_payload->>'expected_revision')::bigint is distinct from t.revision then raise exception 'revision_conflict'; end if;
   select * into c from crowd_machine.children where task_id=t.task_id and child_id=(p_payload->>'child_id')::uuid for update;
   if not found then raise exception 'source_continuation_denied'; end if;
   select * into claimed from crowd_machine.claims where worker_id=c.worker_id and run_id=c.run_id and lease_epoch=c.lease_epoch;
   if t.desired_state<>'running' or t.proposal->>'delivery_basis'<>'live_capture' or c.platform<>'wb'
      or c.plan->'request'->>'source_executor' is distinct from 'pro' or c.plan->'request'->>'mode' is distinct from 'detail'
      or c.plan->'request'->'comments' is distinct from 'true'::jsonb or c.plan->'request'->'replies' is distinct from 'true'::jsonb
      or c.state<>'failed' or c.finished_at is null or c.finish_hash is null or c.requests_reserved<>0
      or c.requests_spent>=(c.plan->>'request_quota')::integer or c.local_run_id is null
      or claimed.run_id is null or claimed.outcome is distinct from 'failed' or claimed.finished_at is null
      or claimed.local_run_id is distinct from c.local_run_id or claimed.api_attempts is null
      or claimed.claim_id::text is distinct from p_payload->>'claim_id'
      or c.worker_id::text is distinct from p_payload->>'worker_id' or c.run_id::text is distinct from p_payload->>'run_id'
      or to_jsonb(c.lease_epoch) is distinct from p_payload->'lease_epoch' or c.local_run_id::text is distinct from p_payload->>'local_run_id'
      or c.finish_hash is distinct from p_payload->>'expected_finish_hash'
      or to_jsonb(claimed.api_attempts) is distinct from p_payload->'proof'->'api_attempts'
      or not exists(select 1 from crowd_machine.workers ww where ww.worker_id=c.worker_id and ww.enabled and ww.expires_at>clock_timestamp() and ww.platforms ? 'wb')
      or jsonb_typeof(p_payload->'account_context') is distinct from 'object'
      or (p_payload->'account_context')-array['session_id','generation','account_ref']<>'{}'::jsonb
      or not(p_payload->'account_context' ?& array['session_id','generation','account_ref'])
      or p_payload->'account_context'->>'session_id' is distinct from c.plan->'request'->>'session_id'
      or jsonb_typeof(p_payload->'account_context'->'generation') is distinct from 'number'
      or c.account_context='{}'::jsonb and p_payload->'proof'->>'identity_binding' is distinct from 'first_verified_subject'
      or c.account_context<>'{}'::jsonb and p_payload->'proof'->>'identity_binding' is distinct from 'same_verified_subject'
      or coalesce(p_payload->'account_context'->>'generation','') !~ '^[1-9][0-9]{0,8}$'
      or coalesce(p_payload->'account_context'->>'account_ref','') !~ '^[a-f0-9]{64}$'
      or c.account_context<>'{}'::jsonb and c.account_context is distinct from p_payload->'account_context'
      then raise exception 'source_continuation_denied'; end if;
   select count(*)::int,encode(sha256(convert_to('crowd-machine-capture-audit-v1'||chr(10)||coalesce(string_agg(capture_id::text||':'||envelope_hash,chr(10) order by capture_id::text),''),'UTF8')),'hex')
     into audit_count,audit_digest from crowd_machine.captures where child_id=c.child_id and run_id=c.run_id and worker_id=c.worker_id and lease_epoch=c.lease_epoch;
   chain_mode:=p_payload->'proof' ? 'chain';
   if chain_mode then
    select * into previous_grant from crowd_machine.source_continuations sc where sc.continuation_id=(p_payload->'proof'->'chain'->>'previous_continuation_id')::uuid;
    if previous_grant.continuation_id is null or previous_grant.task_id<>t.task_id or previous_grant.child_id<>c.child_id or previous_grant.source_worker_id<>c.worker_id
      or previous_grant.source_lease_epoch+1<>c.lease_epoch or previous_grant.proof ? 'chain' or previous_grant.proof->>'failure_reason'<>'wb_embedded_replies_incomplete'
      or previous_grant.source_local_run_id::text is distinct from p_payload->'proof'->'chain'->>'seed_source_local_run_id'
      or previous_grant.account_context is distinct from p_payload->'account_context'
      or previous_grant.proof->'seed_sha256' is distinct from p_payload->'proof'->'seed_sha256'
      or previous_grant.proof->'api_attempts' is distinct from p_payload->'proof'->'chain'->'prior_api_attempts'
      or claimed.api_attempts<=0 or c.requests_spent is distinct from (previous_grant.proof->>'api_attempts')::int+claimed.api_attempts
      or not exists(select 1 from crowd_machine.claims h where h.claim_id=previous_grant.source_claim_id and h.run_id=previous_grant.source_run_id and h.worker_id=c.worker_id and h.child_id=c.child_id and h.lease_epoch=previous_grant.source_lease_epoch and h.outcome='failed' and h.finished_at is not null and to_jsonb(h.api_attempts)=previous_grant.proof->'api_attempts')
      or audit_count<>0 then raise exception 'source_continuation_denied';end if;
    select count(*)::int,encode(sha256(convert_to('crowd-machine-capture-audit-v1'||chr(10)||coalesce(string_agg(capture_id::text||':'||envelope_hash,chr(10) order by capture_id::text),''),'UTF8')),'hex') into anchor_count,anchor_digest from crowd_machine.captures z where z.child_id=c.child_id and z.run_id=previous_grant.source_run_id and z.worker_id=c.worker_id and z.lease_epoch=previous_grant.source_lease_epoch;
    if to_jsonb(anchor_count) is distinct from previous_grant.canonical_audit::jsonb->'capture_count' or anchor_digest is distinct from previous_grant.canonical_audit::jsonb->>'capture_digest'
     or exists(select 1 from crowd_machine.captures z where z.run_id=previous_grant.source_run_id and
       (z.child_id<>c.child_id or z.worker_id<>c.worker_id or z.lease_epoch<>previous_grant.source_lease_epoch or z.task_id<>c.task_id
       or z.receipt->>'status' is distinct from 'received' or z.receipt->>'envelope_hash' is distinct from z.envelope_hash
       or z.receipt->>'capture_id' is distinct from z.capture_id::text or z.canonical_envelope::jsonb is distinct from z.envelope
       or encode(sha256(convert_to('crowd-machine-capture-v1'||chr(10)||z.canonical_envelope,'UTF8')),'hex') is distinct from z.envelope_hash))
     then raise exception 'source_continuation_denied';end if;
   end if;
   if (not chain_mode and audit_count<1) or audit_count is distinct from (p_payload->>'capture_count')::int or audit_digest is distinct from p_payload->>'capture_digest'
      or exists(select 1 from crowd_machine.captures z where z.run_id=c.run_id and
        (z.child_id<>c.child_id or z.worker_id<>c.worker_id or z.lease_epoch<>c.lease_epoch or z.task_id<>c.task_id
        or z.receipt->>'status' is distinct from 'received' or z.receipt->>'envelope_hash' is distinct from z.envelope_hash
        or z.receipt->>'capture_id' is distinct from z.capture_id::text
        or z.canonical_envelope::jsonb is distinct from z.envelope
        or encode(sha256(convert_to('crowd-machine-capture-v1'||chr(10)||z.canonical_envelope,'UTF8')),'hex') is distinct from z.envelope_hash))
      then raise exception 'source_continuation_denied'; end if;
   insert into crowd_machine.source_continuations(task_id,child_id,idempotency_key,audit_hash,canonical_audit,source_worker_id,source_claim_id,source_run_id,source_lease_epoch,source_local_run_id,source_finish_hash,account_context,proof)
   values(t.task_id,c.child_id,p_payload->>'idempotency_key',p_payload->>'audit_hash',p_payload->>'canonical_audit',c.worker_id,claimed.claim_id,c.run_id,c.lease_epoch,c.local_run_id,c.finish_hash,p_payload->'account_context',p_payload->'proof');
   update crowd_machine.children set state='queued',reason_code='owner_source_continuation' where child_id=c.child_id;
   update crowd_machine.tasks set revision=revision+1,updated_at=clock_timestamp() where task_id=t.task_id;
   return jsonb_build_object('replayed',false,'task',crowd_machine.public_task(t.task_id));
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
 elsif p_action='task_reconcile' then
   -- Owner attests the reviewed local artifacts/inactive executor; database binds all receipts.
   if not(p_payload ?& array['task_id','child_id','worker_id','claim_id','run_id','lease_epoch','local_run_id','expected_revision','idempotency_key','expected_finish_hash','mode','capture_count','capture_digest','proof','audit_hash','canonical_audit'])
      or p_payload - array['task_id','child_id','worker_id','claim_id','run_id','lease_epoch','local_run_id','expected_revision','idempotency_key','expected_finish_hash','mode','capture_count','capture_digest','proof','audit_hash','canonical_audit'] <> '{}'::jsonb
      or p_payload->>'mode' is null or p_payload->>'mode' not in ('terminal_unknown','completed_receipts')
      or jsonb_typeof(p_payload->'expected_revision') is distinct from 'number'
      or coalesce(p_payload->>'expected_revision','') !~ '^[1-9][0-9]{0,15}$'
      or jsonb_typeof(p_payload->'lease_epoch') is distinct from 'number'
      or coalesce(p_payload->>'lease_epoch','') !~ '^[1-9][0-9]{0,8}$'
      or jsonb_typeof(p_payload->'capture_count') is distinct from 'number'
      or coalesce(p_payload->>'capture_count','') !~ '^[0-9]{1,4}$' or (p_payload->>'capture_count')::int>2000
      or coalesce(p_payload->>'capture_digest','') !~ '^[a-f0-9]{64}$'
      or coalesce(p_payload->>'audit_hash','') !~ '^[a-f0-9]{64}$'
      or coalesce(p_payload->>'idempotency_key','')='' or length(p_payload->>'idempotency_key')>160
      or jsonb_typeof(p_payload->'proof') is distinct from 'object'
      or not(p_payload->'proof' ?& array['executor_inactive','local_state','exit_code','api_attempts','status_sha256','manifest_sha256'])
      or (p_payload->'proof') - array['executor_inactive','local_state','exit_code','api_attempts','status_sha256','manifest_sha256'] <> '{}'::jsonb
      or p_payload->'proof'->'executor_inactive' is distinct from 'true'::jsonb
      or coalesce(p_payload->'proof'->>'status_sha256','') !~ '^[a-f0-9]{64}$'
      or coalesce(p_payload->'proof'->>'manifest_sha256','') !~ '^[a-f0-9]{64}$'
      or (p_payload->>'canonical_audit')::jsonb is distinct from p_payload - array['audit_hash','canonical_audit','expected_revision']
      or encode(sha256(convert_to('crowd-machine-terminal-audit-v1'||chr(10)||(p_payload->>'canonical_audit'),'UTF8')),'hex') is distinct from p_payload->>'audit_hash'
      then raise exception 'terminal_reconciliation_denied'; end if;
   select * into t from crowd_machine.tasks where task_id=(p_payload->>'task_id')::uuid and owner_scope=p_owner_scope for update;
   if not found then raise exception 'task_not_found'; end if;
   select * into audited from crowd_machine.terminal_audits where task_id=t.task_id and idempotency_key=p_payload->>'idempotency_key';
   if found then
     if audited.audit_hash is distinct from p_payload->>'audit_hash' then raise exception 'reconciliation_conflict'; end if;
     return jsonb_build_object('reconciled',true,'replayed',true,'audit_id',audited.audit_id,'audit_hash',audited.audit_hash,'worker_id',audited.worker_id,'claim_id',audited.claim_id,'run_id',audited.run_id,'lease_epoch',audited.lease_epoch,'task',crowd_machine.public_task(t.task_id));
   end if;
   if t.revision is distinct from (p_payload->>'expected_revision')::bigint then raise exception 'revision_conflict'; end if;
   select * into c from crowd_machine.children where child_id=(p_payload->>'child_id')::uuid and task_id=t.task_id for update;
   if not found or c.state is distinct from 'unknown' or c.worker_id is distinct from (p_payload->>'worker_id')::uuid
      or c.run_id is distinct from (p_payload->>'run_id')::uuid or c.lease_epoch is distinct from (p_payload->>'lease_epoch')::int
      or c.local_run_id is null or c.local_run_id is distinct from (p_payload->>'local_run_id')::uuid
      or c.finish_hash is distinct from p_payload->>'expected_finish_hash'
      or c.lease_until is null or c.lease_until>clock_timestamp()
      or exists(select 1 from crowd_machine.terminal_audits where worker_id=c.worker_id and run_id=c.run_id and lease_epoch=c.lease_epoch)
      or not exists(select 1 from crowd_machine.workers where worker_id=c.worker_id and owner_scope=p_owner_scope)
      then raise exception 'terminal_reconciliation_denied'; end if;
   select * into claimed from crowd_machine.claims where worker_id=c.worker_id and claim_id=(p_payload->>'claim_id')::uuid;
   if not found or claimed.child_id is distinct from c.child_id or claimed.run_id is distinct from c.run_id
      or claimed.lease_epoch is distinct from c.lease_epoch or claimed.local_run_id is distinct from c.local_run_id
      then raise exception 'terminal_reconciliation_denied'; end if;
   select count(*)::int,encode(sha256(convert_to('crowd-machine-capture-audit-v1'||chr(10)||coalesce(string_agg(capture_id::text||':'||envelope_hash,chr(10) order by capture_id::text),''),'UTF8')),'hex')
     into audit_count,audit_digest from crowd_machine.captures where child_id=c.child_id and run_id=c.run_id and worker_id=c.worker_id and lease_epoch=c.lease_epoch;
   if audit_count<>(p_payload->>'capture_count')::int or audit_digest is distinct from p_payload->>'capture_digest'
      or exists(select 1 from crowd_machine.captures z where z.run_id=c.run_id and
         (z.child_id is distinct from c.child_id or z.worker_id is distinct from c.worker_id or z.lease_epoch is distinct from c.lease_epoch
          or z.owner_scope is distinct from p_owner_scope
          or z.task_id is distinct from c.task_id or z.receipt->>'status' is distinct from 'received'
          or z.receipt->>'envelope_hash' is distinct from z.envelope_hash
          or z.receipt->>'capture_id' is distinct from z.capture_id::text
          or z.receipt->>'task_id' is distinct from z.task_id::text
          or z.receipt->>'child_id' is distinct from z.child_id::text
          or z.receipt->>'run_id' is distinct from z.run_id::text
          or z.receipt->'lease_epoch' is distinct from to_jsonb(z.lease_epoch)
          or z.receipt->>'source_kind' is distinct from 'machine_api'
          or z.receipt->'reward_eligible' is distinct from 'false'::jsonb
          or z.canonical_envelope::jsonb is distinct from z.envelope
          or encode(sha256(convert_to('crowd-machine-capture-v1'||chr(10)||z.canonical_envelope,'UTF8')),'hex') is distinct from z.envelope_hash))
      then raise exception 'terminal_receipts_mismatch'; end if;
   quota=(c.plan->>'request_quota')::int;
   if c.requests_spent<0 or c.requests_reserved<0 or c.requests_spent>quota then raise exception 'terminal_reconciliation_denied'; end if;
   select jsonb_build_object('nonempty_body_contents',count(*) filter(where z.envelope->'record'->>'kind' in ('content','dynamic') and length(btrim(coalesce(z.envelope->'record'->>'body','')))>0),
      'title_only_contents',count(*) filter(where z.envelope->'record'->>'kind' in ('content','dynamic') and length(btrim(coalesce(z.envelope->'record'->>'body','')))=0 and length(btrim(coalesce(z.envelope->'record'->>'title','')))>0)) into coverage
     from crowd_machine.captures z where z.child_id=c.child_id and z.run_id=c.run_id;
   if p_payload->>'mode'='terminal_unknown' then
     if p_payload->'proof'->>'local_state' is distinct from 'interrupted_unknown'
        or p_payload->'proof'->'exit_code' is distinct from 'null'::jsonb
        or p_payload->'proof'->'api_attempts' is distinct from 'null'::jsonb
        then raise exception 'terminal_reconciliation_denied'; end if;
     charged=quota-c.requests_spent;released=0;final_state='failed';
   else
     if claimed.outcome is distinct from 'completed' or claimed.finished_at is null or c.finished_at is null or c.finish_hash is null
        or claimed.api_attempts is null or claimed.api_attempts<0 or claimed.api_attempts>quota or c.requests_spent<claimed.api_attempts
        or p_payload->'proof'->>'local_state' is distinct from 'completed'
        or p_payload->'proof'->'exit_code' is distinct from '0'::jsonb
        or p_payload->'proof'->'api_attempts' is distinct from to_jsonb(claimed.api_attempts) or audit_count=0
        then raise exception 'terminal_reconciliation_denied'; end if;
     charged=0;released=least(c.requests_reserved,quota-c.requests_spent);
     select count(distinct concat(z.envelope->'record'->>'kind',':',z.envelope->'record'->>'content_id')) into content_count from crowd_machine.captures z where z.child_id=c.child_id and z.envelope->'record'->>'kind' in ('content','dynamic') and length(btrim(coalesce(z.envelope->'record'->>'body','')||coalesce(z.envelope->'record'->>'title','')||coalesce(z.envelope->'record'->>'text','')))>0;
     final_state=case when content_count>=(c.plan->>'item_quota')::int then 'completed' else 'failed' end;
   end if;
   insert into crowd_machine.terminal_audits(owner_scope,task_id,child_id,worker_id,claim_id,run_id,lease_epoch,local_run_id,idempotency_key,audit_hash,mode,proof,prior_reason,prior_spent,prior_reserved,charged_requests,released_requests,final_state,body_coverage)
    values(p_owner_scope,t.task_id,c.child_id,c.worker_id,claimed.claim_id,c.run_id,c.lease_epoch,c.local_run_id,p_payload->>'idempotency_key',p_payload->>'audit_hash',p_payload->>'mode',p_payload->'proof',c.reason_code,c.requests_spent,c.requests_reserved,charged,released,final_state,coverage) returning * into audited;
   update crowd_machine.children set state=final_state,reason_code=case when audited.mode='terminal_unknown' then 'audited_terminal_unknown' when final_state='completed' then 'audited_executor_completed' else 'audited_executor_completed_without_content' end,requests_spent=requests_spent+charged,requests_reserved=0 where child_id=c.child_id;
   update crowd_machine.tasks set revision=revision+1,updated_at=clock_timestamp() where task_id=t.task_id;
   return jsonb_build_object('reconciled',true,'replayed',false,'audit_id',audited.audit_id,'audit_hash',audited.audit_hash,'worker_id',audited.worker_id,'claim_id',audited.claim_id,'run_id',audited.run_id,'lease_epoch',audited.lease_epoch,'task',crowd_machine.public_task(t.task_id));
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
   -- Keep one running execution; an unresolved source blocks only its platform on this worker.
   if not exists(select 1 from crowd_machine.children where worker_id=w.worker_id and state='running') then
     select c0.* into c from crowd_machine.children c0 join crowd_machine.tasks t0 on t0.task_id=c0.task_id
     where t0.owner_scope=p_owner_scope and t0.desired_state='running' and c0.state='queued' and w.platforms ? c0.platform and not(coalesce(p_payload->'unavailable_platforms','[]'::jsonb) ? c0.platform) and (c0.worker_id is null or c0.worker_id=w.worker_id)
       and not exists(select 1 from crowd_machine.children blocked where blocked.worker_id=w.worker_id and blocked.platform=c0.platform and blocked.state='unknown')
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
 if p_action in ('capture','finish','resume_login','delivery_defer','delivery_resume') and exists(select 1 from crowd_machine.resolutions where worker_id=w.worker_id and run_id=c.run_id and lease_epoch=c.lease_epoch) then raise exception 'run_reconciled_no_dispatch'; end if;
 if p_action in ('capture','finish','resume_login','delivery_defer','delivery_resume') and exists(select 1 from crowd_machine.terminal_audits where worker_id=w.worker_id and run_id=c.run_id and lease_epoch=c.lease_epoch) then raise exception 'run_terminally_reconciled'; end if;
 select * into t from crowd_machine.tasks where task_id=c.task_id and owner_scope=p_owner_scope;
 if not found then raise exception 'principal_denied'; end if;
 now_at=clock_timestamp();
 select * into delivery from crowd_machine.deliveries where run_id=c.run_id;
 if p_action='delivery_defer' then
   v_hash=p_payload->>'manifest_hash';
   if delivery.run_id is not null then
     if delivery.manifest_hash is distinct from v_hash or delivery.manifest is distinct from p_payload-'manifest_hash'-'canonical_manifest' then raise exception 'delivery_manifest_conflict'; end if;
   else
     if c.state is distinct from 'running' or c.lease_until is null or c.lease_until<=now_at or c.finish_hash is not null
       or p_payload->>'outcome' is null or p_payload->>'outcome' not in ('completed','failed','stopped')
       or jsonb_typeof(p_payload->'api_attempts') is distinct from 'number' or coalesce(p_payload->>'api_attempts','') !~ '^[0-9]{1,3}$'
       or (p_payload->>'api_attempts')::integer>c.requests_reserved
       or p_payload->'local_run_id' is distinct from to_jsonb(c.local_run_id) and not(c.local_run_id is null and p_payload->'local_run_id'='null'::jsonb)
       or c.local_run_id is null and t.proposal->>'delivery_basis'<>'existing_saved'
       or jsonb_typeof(p_payload->'capture_refs') is distinct from 'object'
       then raise exception 'delivery_defer_denied'; end if;
     if (select count(*) from jsonb_object_keys(p_payload->'capture_refs')) not between 1 and 2000
       or exists(select 1 from jsonb_each_text(p_payload->'capture_refs') r where r.key !~ '^[a-f0-9-]{36}$' or r.value !~ '^[a-f0-9]{64}$')
       or exists(select 1 from crowd_machine.captures z where z.run_id=c.run_id and (p_payload->'capture_refs'->>z.capture_id::text is distinct from z.envelope_hash))
       or exists(select 1 from jsonb_each_text(p_payload->'capture_refs') r join crowd_machine.captures z on z.capture_id=r.key::uuid where z.run_id<>c.run_id or z.worker_id<>w.worker_id or z.lease_epoch<>c.lease_epoch or z.envelope_hash<>r.value)
       or (p_payload->>'canonical_manifest')::jsonb is distinct from p_payload-'manifest_hash'-'canonical_manifest'
       or encode(sha256(convert_to('crowd-machine-delivery-v1'||chr(10)||(p_payload->>'canonical_manifest'),'UTF8')),'hex') is distinct from v_hash
       then raise exception 'delivery_manifest_conflict'; end if;
     charged=(p_payload->>'api_attempts')::integer;
     insert into crowd_machine.deliveries(run_id,worker_id,child_id,lease_epoch,defer_id,manifest_hash,manifest,charged_requests)
       values(c.run_id,w.worker_id,c.child_id,c.lease_epoch,(p_payload->>'defer_id')::uuid,v_hash,p_payload-'manifest_hash'-'canonical_manifest',charged) returning * into delivery;
     update crowd_machine.children set state='delivery_pending',reason_code='unacknowledged_delivery',requests_spent=requests_spent+charged,requests_reserved=0 where child_id=c.child_id;
     update crowd_machine.claims set local_run_id=c.local_run_id,outcome=p_payload->>'outcome',api_attempts=charged,finished_at=now_at where worker_id=w.worker_id and run_id=c.run_id and lease_epoch=c.lease_epoch;
   end if;
   return jsonb_build_object('deferred',true,'run_id',c.run_id,'lease_epoch',c.lease_epoch,'worker_id',w.worker_id,'manifest_hash',delivery.manifest_hash,'lease',crowd_machine.lease_view(c.child_id));
 elsif p_action='delivery_resume' then
   if delivery.run_id is null or delivery.manifest_hash is distinct from p_payload->>'manifest_hash' then raise exception 'delivery_resume_denied'; end if;
   if c.state='delivery_pending' and t.desired_state='running' then
     update crowd_machine.children set lease_until=now_at+interval '90 seconds' where child_id=c.child_id;
   end if;
   return jsonb_build_object('may_deliver',c.state='delivery_pending' and t.desired_state='running','run_id',c.run_id,'lease_epoch',c.lease_epoch,'worker_id',w.worker_id,'manifest_hash',delivery.manifest_hash,'lease',crowd_machine.lease_view(c.child_id));
 elsif p_action='receipt' then
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
   target_id=envelope->'record'->>'content_id';
   if exists(select 1 from crowd_machine.source_continuations sc where sc.child_id=c.child_id and sc.source_worker_id=w.worker_id and sc.source_lease_epoch+1=c.lease_epoch) and
    (envelope->'record'->>'kind' is distinct from 'comment' or envelope->'record'->'origin'->>'run_id' is distinct from c.local_run_id::text or envelope->'record'->'origin'->>'operation_id' is distinct from c.local_run_id::text or not exists(
      select 1 from crowd_machine.source_continuations sc join crowd_machine.source_continuations anchor on anchor.continuation_id=case when sc.proof ? 'chain' then (sc.proof->'chain'->>'previous_continuation_id')::uuid else sc.continuation_id end join crowd_machine.captures oldbody on oldbody.run_id=anchor.source_run_id and oldbody.child_id=anchor.child_id and oldbody.worker_id=anchor.source_worker_id and oldbody.lease_epoch=anchor.source_lease_epoch
      where sc.child_id=c.child_id and sc.source_lease_epoch+1=c.lease_epoch and oldbody.envelope->'record'->>'kind'='content' and oldbody.envelope->'record'->>'content_id'=target_id)) then raise exception 'invalid_capture';end if;
   if c.recovery_id is not null and envelope->'record'->>'content_id' is distinct from (select source_content_id from crowd_machine.recoveries where recovery_id=c.recovery_id) then raise exception 'invalid_capture'; end if;
   if octet_length(p_payload->>'canonical_envelope')>262144 or (p_payload->>'canonical_envelope')::jsonb<>envelope or encode(sha256(convert_to('crowd-machine-capture-v1'||chr(10)||(p_payload->>'canonical_envelope'),'UTF8')),'hex')<>v_hash then raise exception 'capture_hash_conflict'; end if;
   if delivery.run_id is not null and (c.state is distinct from 'delivery_pending' or t.desired_state<>'running' or delivery.manifest->'capture_refs'->>v_id::text is distinct from v_hash) then raise exception 'delivery_resume_denied'; end if;
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
   if delivery.run_id is not null and (c.state is distinct from 'delivery_pending' or t.desired_state<>'running' or p_payload->>'outcome' is distinct from delivery.manifest->>'outcome' or p_payload->'api_attempts' is distinct from delivery.manifest->'api_attempts' or (select jsonb_agg(k order by k) from jsonb_object_keys(delivery.manifest->'capture_refs') k) is distinct from (select jsonb_agg(k order by k) from jsonb_array_elements_text(ids) k)) then raise exception 'unacknowledged_capture'; end if;
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
end $function$

;

commit;
