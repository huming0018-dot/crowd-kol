-- G08 isolated candidate. Distinct explicit Owner authorization; never changes the old pilot rows.
begin;
do $cas$ begin
 if md5(pg_get_functiondef('crowd_v4.acceptance_supplement_view(bigint,uuid)'::regprocedure))<>'69b0bc2eeeb5958b8b8544c259852b5c' or(select proacl::text from pg_proc where oid='crowd_v4.acceptance_supplement_view(bigint,uuid)'::regprocedure)is distinct from '{postgres=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('crowd_v4.pilot_block_reason(bigint,uuid)'::regprocedure))<>'d343329af97b2ce5b7767010c51f44dd' or(select proacl::text from pg_proc where oid='crowd_v4.pilot_block_reason(bigint,uuid)'::regprocedure)is distinct from '{postgres=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('crowd_v4.dispatch_candidate_allowed(bigint,uuid)'::regprocedure))<>'ac2402f3a7701e1b470ba148c171df4f' or(select proacl::text from pg_proc where oid='crowd_v4.dispatch_candidate_allowed(bigint,uuid)'::regprocedure)is distinct from '{postgres=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('public.crowd_v4_claim(bigint)'::regprocedure))<>'1cef69763675a32d00cb08e7f1581df7' or(select proacl::text from pg_proc where oid='public.crowd_v4_claim(bigint)'::regprocedure)is distinct from '{postgres=X/postgres,service_role=X/postgres,authenticated=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('public.crowd_v4_node_claim(uuid,bigint)'::regprocedure))<>'67088562ef663213b8ba793be00bac56' or(select proacl::text from pg_proc where oid='public.crowd_v4_node_claim(uuid,bigint)'::regprocedure)is distinct from '{postgres=X/postgres,authenticated=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('crowd_observation.pro_scope(bigint,uuid,uuid,boolean,boolean)'::regprocedure))<>'db494e9920e1786c3520166b717bf8ee' or(select proacl::text from pg_proc where oid='crowd_observation.pro_scope(bigint,uuid,uuid,boolean,boolean)'::regprocedure)is distinct from '{postgres=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('crowd_observation.guard_internal(text,bigint,text)'::regprocedure))<>'2bddecd8b77242a0997197a2ab1d7690' or(select proacl::text from pg_proc where oid='crowd_observation.guard_internal(text,bigint,text)'::regprocedure)is distinct from '{postgres=X/postgres,service_role=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('public.crowd_unified_dispatch_rpc(text,text,text,jsonb)'::regprocedure))<>'562f9e08ec4ca6c7b7b1112047718e0a' or(select proacl::text from pg_proc where oid='public.crowd_unified_dispatch_rpc(text,text,text,jsonb)'::regprocedure)is distinct from '{postgres=X/postgres,service_role=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('crowd_machine.unified_dispatch_view(uuid)'::regprocedure))<>'868ac388c210d78e2b89ee95cee07e55' or(select proacl::text from pg_proc where oid='crowd_machine.unified_dispatch_view(uuid)'::regprocedure)is distinct from '{postgres=X/postgres,service_role=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('crowd_observation.pro_node_capable(uuid,uuid,integer)'::regprocedure))<>'2b5e1f7cd7265cf68c66b54d290508e0' or(select proacl::text from pg_proc where oid='crowd_observation.pro_node_capable(uuid,uuid,integer)'::regprocedure)is distinct from '{postgres=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('crowd_observation.pro_task_comment_options(bigint,uuid,boolean)'::regprocedure))<>'20d22e629482927c52197fa456c62fa0' or(select proacl::text from pg_proc where oid='crowd_observation.pro_task_comment_options(bigint,uuid,boolean)'::regprocedure)is distinct from '{postgres=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('public.crowd_v4_admin(text,jsonb)'::regprocedure))<>'216c6e42e4c1cd2061d0f371fef9f1c1' or(select proacl::text from pg_proc where oid='public.crowd_v4_admin(text,jsonb)'::regprocedure)is distinct from '{postgres=X/postgres,service_role=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('public.crowd_v4_pro_guard(bigint,uuid,text,text,uuid)'::regprocedure))<>'42615a1c19a6b8848d9895116ddd67e8' or(select proacl::text from pg_proc where oid='public.crowd_v4_pro_guard(bigint,uuid,text,text,uuid)'::regprocedure)is distinct from '{postgres=X/postgres,authenticated=X/postgres,service_role=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('public.crowd_v4_pro_submit(bigint,uuid,uuid,jsonb,uuid)'::regprocedure))<>'8ad52b95b316eea0eefc27bf67bd5b9f' or(select proacl::text from pg_proc where oid='public.crowd_v4_pro_submit(bigint,uuid,uuid,jsonb,uuid)'::regprocedure)is distinct from '{postgres=X/postgres,authenticated=X/postgres,service_role=X/postgres}'then raise exception'g08_function_drift';end if;
 if md5(pg_get_functiondef('public.crowd_v4_pro_finish(bigint,uuid,uuid)'::regprocedure))<>'d61261a81ea8b7d5515c1449532eaccc' or(select proacl::text from pg_proc where oid='public.crowd_v4_pro_finish(bigint,uuid,uuid)'::regprocedure)is distinct from '{postgres=X/postgres,authenticated=X/postgres,service_role=X/postgres}'then raise exception'g08_function_drift';end if;
 if exists(select from pg_attribute where attrelid='crowd_v4.participant_pro_batches'::regclass and attname='owner_dispatch_id'and not attisdropped)or(select count(*)from pg_attribute where attrelid='crowd_v4.participant_pro_batches'::regclass and attname in('invite_hash','expires_at')and attnotnull and not attisdropped)<>2 then raise exception'g08_batch_schema_drift';end if;
 if not exists(select from pg_constraint where conrelid='crowd_v4.participant_pro_batches'::regclass and conname='participant_pro_batches_installation_id_fkey'and pg_get_constraintdef(oid)='FOREIGN KEY (installation_id) REFERENCES crowd_v4.nodes(installation_id)')then raise exception'g08_batch_constraint_drift';end if;
 if not exists(select from pg_constraint where conrelid='crowd_v4.participant_pro_batches'::regclass and conname='participant_pro_batches_invite_hash_fkey'and pg_get_constraintdef(oid)='FOREIGN KEY (invite_hash) REFERENCES crowd_v4.pilot_experiments(invite_hash)')then raise exception'g08_batch_constraint_drift';end if;
 if not exists(select from pg_constraint where conrelid='crowd_v4.participant_pro_batches'::regclass and conname='participant_pro_batches_pkey'and pg_get_constraintdef(oid)='PRIMARY KEY (id)')then raise exception'g08_batch_constraint_drift';end if;
 if not exists(select from pg_constraint where conrelid='crowd_v4.participant_pro_batches'::regclass and conname='participant_pro_batches_target_check'and pg_get_constraintdef(oid)='CHECK (((target >= 1) AND (target <= 100)))')then raise exception'g08_batch_constraint_drift';end if;
 if not exists(select from pg_constraint where conrelid='crowd_v4.participant_pro_batches'::regclass and conname='participant_pro_batches_task_id_fkey'and pg_get_constraintdef(oid)='FOREIGN KEY (task_id) REFERENCES crowd_v4.tasks(id)')then raise exception'g08_batch_constraint_drift';end if;
 if not exists(select from pg_constraint where conrelid='crowd_v4.participant_pro_batches'::regclass and conname='participant_pro_batches_task_id_key'and pg_get_constraintdef(oid)='UNIQUE (task_id)')then raise exception'g08_batch_constraint_drift';end if;
 if not exists(select from pg_constraint where conrelid='crowd_v4.participant_pro_batches'::regclass and conname='participant_pro_batches_user_id_fkey'and pg_get_constraintdef(oid)='FOREIGN KEY (user_id) REFERENCES crowd_v4.participants(user_id)')then raise exception'g08_batch_constraint_drift';end if;
end $cas$;
alter table crowd_v4.participant_pro_batches add column owner_dispatch_id uuid references crowd_machine.unified_dispatches(dispatch_id),alter column invite_hash drop not null,alter column expires_at drop not null;
alter table crowd_v4.participant_pro_batches add constraint participant_pro_batches_authorization_mode check((owner_dispatch_id is null and invite_hash is not null and expires_at is not null)or(owner_dispatch_id is not null and invite_hash is null and expires_at is null));
create function crowd_observation.owner_pro_authorization(p_task bigint,p_user uuid,p_installation uuid default null,p_recovery boolean default false)returns jsonb language sql stable security definer set search_path='' as $owner$
 select jsonb_build_object('schema','crowd-acceptance-batch-v1','id',b.id,'task_id',t.id,'installation_id',b.installation_id,'baseline_received',0,'extra_limit',b.target,'target',b.target,'remaining',greatest(0,t.target-t.received))
 from crowd_v4.participant_pro_batches b join crowd_v4.tasks t on t.id=b.task_id
 join crowd_machine.unified_participant_tasks m on m.task_id=t.id and m.dispatch_id=b.owner_dispatch_id
 join crowd_machine.unified_dispatches d on d.dispatch_id=m.dispatch_id
 cross join lateral jsonb_array_elements(d.routes) r
 where b.owner_dispatch_id is not null and b.invite_hash is null and b.expires_at is null and b.user_id=p_user
 and (p_task is null or t.id=p_task) and(p_installation is null or b.installation_id=p_installation)
 and (p_task is not null or t.received<t.target and t.status in('open','leased'))
 and (p_recovery or not b.revoked and t.status in('open','leased','complete'))
 and t.target=b.target and t.target between 1 and 100 and t.received between 0 and t.target
 and t.source_executor='mediacrawler_pro' and (t.claimed_by is null or t.claimed_by=p_user)
 and crowd_v4.acceptance_task_input(t)=b.baseline_task
 and (select count(*)from crowd_v4.proofs f where f.task_id=t.id)=t.received
 and not exists(select from crowd_v4.proofs f where f.task_id=t.id and f.user_id<>p_user)
 and exists(select from crowd_v4.participants p where p.user_id=p_user and p.status='approved'and p.consent='crowd-public-v4')
 and exists(select from crowd_v4.nodes n where n.user_id=p_user and n.installation_id=b.installation_id)
 and exists(select from crowd_v4.test_task_owners o where o.task_id=t.id and o.user_id=p_user)
 and d.owner_scope='crowd-owner-main' and d.pilot_invite_hash is null and d.request_hash~'^[a-f0-9]{64}$'
 and r->>'platform'='xhs' and r->>'executor'='mediacrawler_pro' and r->>'authorization_kind'='owner_dispatch'
 and r->>'owner_request_hash'=d.request_hash and r->'task_ids'=jsonb_build_array(t.id)
 and r->'item_quota'=to_jsonb(t.target) and d.request->'desired_items'=to_jsonb(t.target)
 and r->'request_quota'=d.request->'max_api_requests'
 and d.request->>'mode'='search' and d.request->'platforms'='["xhs"]'::jsonb
 and d.request->>'purpose'='noncommercial_research' and d.request->'comments'='true'::jsonb
 and d.request->'targets'=jsonb_build_array(t.query) and exists(select from jsonb_array_elements_text(t.anchor_terms)a(term)where a.term=t.query)
 and r->'comment_options'=jsonb_build_object('comments',true,'replies',coalesce(d.request->'replies','false'::jsonb),'max_comments',coalesce(d.request->'max_comments','20'::jsonb))
 and r#>>array['participant_bindings',t.id::text,'subject']=p_user::text
 and r#>>array['participant_bindings',t.id::text,'installation_id']=b.installation_id::text
 and crowd_observation.pro_capability_valid(r#>array['participant_bindings',t.id::text,'capabilities'])
 order by b.created_at,b.task_id limit 1
$owner$;
revoke all on function crowd_observation.owner_pro_authorization(bigint,uuid,uuid,boolean)from public,anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION crowd_v4.acceptance_supplement_view(task bigint, participant uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare g crowd_v4.acceptance_supplements; t crowd_v4.tasks; old_rows jsonb; total integer;
begin
 if crowd_observation.owner_pro_authorization(task,participant) is not null then return crowd_observation.owner_pro_authorization(task,participant);end if;
 -- New batches authorize only their original node/task. Old grants are untouched.
 if exists(select from crowd_v4.participant_pro_batches b join crowd_v4.tasks bt on bt.id=b.task_id
  where b.user_id=participant and (task is null or b.task_id=task) and not b.revoked and b.expires_at>now()
   and (task is not null or bt.received<bt.target)) then
  return (select jsonb_build_object('schema','crowd-acceptance-batch-v1','id',b.id,'task_id',b.task_id,
   'installation_id',b.installation_id,'baseline_received',0,'extra_limit',b.target,'target',b.target,
   'remaining',greatest(0,b.target-bt.received))
   from crowd_v4.participant_pro_batches b join crowd_v4.tasks bt on bt.id=b.task_id
   where b.user_id=participant and (task is null or b.task_id=task) and not b.revoked and b.expires_at>now()
    and (task is not null or bt.received<bt.target)
    and bt.claimed_by=participant and bt.target=b.target and bt.received between 0 and b.target
    and bt.status in ('open','leased','complete') and bt.source_executor='mediacrawler_pro'
    and crowd_v4.acceptance_task_input(bt)=b.baseline_task
    and (select count(*) from crowd_v4.proofs p where p.task_id=bt.id)=bt.received
    and not exists(select from crowd_v4.proofs p where p.task_id=bt.id and p.user_id<>participant)
    and exists(select from crowd_v4.participants p where p.user_id=participant and p.status='approved' and p.consent='crowd-public-v4')
    and exists(select from crowd_v4.nodes n where n.installation_id=b.installation_id and n.user_id=participant)
    and exists(select from crowd_v4.test_task_owners o where o.task_id=bt.id and o.user_id=participant)
    and not exists(select from crowd_v4.test_task_owners o where o.task_id=bt.id and o.user_id<>participant)
    and exists(select from crowd_v4.enrollments e join crowd_v4.pilot_experiments x using(invite_hash)
     join crowd_v4.invites i on i.token_hash=x.invite_hash join crowd_v4.pilot_task_map m on m.invite_hash=x.invite_hash
     where e.user_id=participant and e.completed_at is not null and x.invite_hash=b.invite_hash
      and m.task_id=bt.id and x.phase='awaiting_acceptance' and not i.revoked and i.max_people<=5 and i.quota_day=2)
   order by b.created_at,b.task_id limit 1);
 end if;
 select * into g from crowd_v4.acceptance_supplements where user_id=participant and (task is null or task_id=task);
 -- Explicit local batch configuration is independent of the historical extra1 expiry/consumed marker.
 if participant='2fc8765e-700a-41c1-b325-a21c5faa22ce'::uuid and (task is null or task=19)
  and g.id='8df461ae-cdff-4476-bc03-47126d6eaecf'::uuid and g.task_id=19
  and g.installation_id='3cde2858-39a5-42e1-b7ab-dd62053d2dac'::uuid then
  select * into t from crowd_v4.tasks where id=19;
  if t.target=22 then
   if t.claimed_by is distinct from participant or t.received not between 2 and 22 or t.status not in ('open','leased','complete')
    or t.comments_capture or t.structured_capture or t.acceptance_goal<>2 or cardinality(t.comment_repair_parents)<>0
    or not exists(select from crowd_v4.test_task_owners where task_id=19 and user_id=participant)
    or exists(select from crowd_v4.test_task_owners where task_id=19 and user_id<>participant)
    or not exists(select from crowd_v4.participants where user_id=participant and status='approved' and consent='crowd-public-v4')
    or not exists(select from crowd_v4.nodes where installation_id=g.installation_id and user_id=participant)
    or not exists(select from crowd_v4.enrollments e join crowd_v4.pilot_experiments x using(invite_hash) join crowd_v4.invites i on i.token_hash=x.invite_hash join crowd_v4.pilot_task_map m on m.invite_hash=x.invite_hash
      where e.user_id=participant and e.completed_at is not null and x.invite_hash=g.invite_hash and m.task_id=19 and x.phase='awaiting_acceptance' and not i.revoked and i.max_people<=5 and i.quota_day=2)
    or (crowd_v4.acceptance_task_input(t)-array['empty_passes','action_gap_milliseconds','session_action_limit','session_window_seconds','daily_search_cap','daily_detail_cap']) is distinct from
       (crowd_v4.acceptance_task_input(jsonb_populate_record(null::crowd_v4.tasks,g.baseline_task))-array['empty_passes','action_gap_milliseconds','session_action_limit','session_window_seconds','daily_search_cap','daily_detail_cap']) then return null; end if;
   select jsonb_agg(jsonb_build_object('id',p.id,'note_id',p.note_id,'record_md5',md5(p.record::text)) order by p.id) into old_rows from crowd_v4.proofs p
    where p.user_id=participant and p.task_id=19 and p.id in(select (v->>'id')::bigint from jsonb_array_elements(g.baseline_proofs) v);
   select count(*) into total from crowd_v4.proofs where task_id=19;
   if jsonb_array_length(g.baseline_proofs) is distinct from 2 or old_rows is distinct from g.baseline_proofs
    or total<>t.received or exists(select from crowd_v4.proofs where task_id=19 and user_id<>participant) then return null; end if;
   return jsonb_build_object('schema','crowd-acceptance-batch-v1','id',g.id,'task_id',19,'installation_id',g.installation_id,
    'baseline_received',2,'extra_limit',20,'target',22,'remaining',greatest(0,22-total));
  end if;
 end if;
 if g.id is null or g.revoked or g.expires_at<=now() then return null; end if;
 if not exists(select from crowd_v4.nodes where installation_id=g.installation_id and user_id=participant)
 or not exists(select from crowd_v4.enrollments e join crowd_v4.pilot_experiments x using(invite_hash) join crowd_v4.invites i on i.token_hash=x.invite_hash
  where e.user_id=participant and e.completed_at is not null and x.invite_hash=g.invite_hash and x.phase='awaiting_acceptance' and not i.revoked and i.expires_at>now() and i.max_people<=5 and i.quota_day=2)
 or not exists(select from crowd_v4.pilot_task_map where task_id=g.task_id and invite_hash=g.invite_hash) then return null; end if;
 select * into t from crowd_v4.tasks where id=g.task_id;
 if t.target<>3 or t.received not in (2,3) or t.status not in ('open','leased','complete') or crowd_v4.acceptance_task_input(t) is distinct from crowd_v4.acceptance_task_input(jsonb_populate_record(null::crowd_v4.tasks,g.baseline_task)) then return null; end if;
 select jsonb_agg(jsonb_build_object('id',p.id,'note_id',p.note_id,'record_md5',md5(p.record::text)) order by p.id) into old_rows from crowd_v4.proofs p
 where p.user_id=participant and p.task_id=g.task_id and p.id in(select (v->>'id')::bigint from jsonb_array_elements(g.baseline_proofs) v);
 if old_rows is distinct from g.baseline_proofs then return null; end if;
 select count(*) into total from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where p.user_id=participant and m.invite_hash=g.invite_hash;
 if total not in (2,3) or total<>t.received or (g.consumed_request is not null and total<>3) then return null; end if;
 return jsonb_build_object('schema','crowd-acceptance-extra1-v1','id',g.id,'task_id',g.task_id,'installation_id',g.installation_id,
 'baseline_received',2,'extra_limit',1,'remaining',case when total=2 and g.consumed_request is null then 1 else 0 end,'expires_at',g.expires_at);
end $function$
;
CREATE OR REPLACE FUNCTION crowd_v4.pilot_block_reason(task bigint, participant uuid)
 RETURNS text
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare cohort text; task_cohort text; experiment crowd_v4.pilot_experiments; invitation crowd_v4.invites;
begin
 -- New Owner authorization is not enrollment into, or activation of, the old pilot.
 if crowd_observation.owner_pro_authorization(task,participant)is not null then
  if(select count(*)from crowd_v4.proofs where user_id=participant and received_at>=date_trunc('day',now()at time zone'Asia/Shanghai')at time zone'Asia/Shanghai')>=(select quota_day from crowd_v4.participants where user_id=participant)then return'daily_quota';end if;
  return null;
 end if;
 select e.invite_hash into cohort from crowd_v4.enrollments e join crowd_v4.pilot_experiments x using(invite_hash)
  where e.user_id=participant and e.completed_at is not null;
 select invite_hash into task_cohort from crowd_v4.pilot_task_map where task_id=task;
 if cohort is null then return case when task_cohort is not null then 'user_stopped' else null end; end if;
 if task is not null and task_cohort is distinct from cohort then return 'user_stopped'; end if;
 select * into experiment from crowd_v4.pilot_experiments where invite_hash=cohort;
 select * into invitation from crowd_v4.invites where token_hash=cohort;
 if invitation.revoked or (invitation.expires_at<=now() and crowd_v4.acceptance_supplement_view(task,participant)->>'schema' is distinct from 'crowd-acceptance-batch-v1') or invitation.max_people>5 or invitation.quota_day<>2
  or experiment.phase='closed' then return 'user_stopped'; end if;
 if experiment.phase='active' and (experiment.armed_at>now() or experiment.ends_at<=now()) then return 'user_stopped'; end if;
 if crowd_v4.acceptance_supplement_view(task,participant)->>'schema'='crowd-acceptance-batch-v1' then
  if (crowd_v4.acceptance_supplement_view(task,participant)->>'remaining')::int>0 then return null; else return 'test_completed'; end if;
 end if;
 if (select count(*) from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where m.invite_hash=cohort)>=20 then return 'test_completed'; end if;
 if coalesce((crowd_v4.acceptance_supplement_view(task,participant)->>'remaining')::int,0)<>1 and experiment.phase='awaiting_acceptance' and (select count(*) from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where p.user_id=participant and m.invite_hash=cohort)>=2 then return 'test_completed'; end if;
 if exists(select from crowd_v4.tasks where id=task and (received>=target or status in ('complete','exhausted','closed'))) then return 'task_full'; end if;
 if coalesce((crowd_v4.acceptance_supplement_view(task,participant)->>'remaining')::int,0)<>1 and (select count(*) from crowd_v4.proofs where user_id=participant and received_at>=date_trunc('day',now() at time zone 'Asia/Shanghai') at time zone 'Asia/Shanghai')>=2 then return 'daily_quota'; end if;
 return null;
end $function$
;
CREATE OR REPLACE FUNCTION crowd_v4.dispatch_candidate_allowed(task bigint, participant uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
 select crowd_observation.owner_pro_authorization(task,participant)is not null or not exists(
  select 1 from crowd_v4.enrollments e join crowd_machine.unified_dispatches d on d.pilot_invite_hash=e.invite_hash
   where e.user_id=participant and e.completed_at is not null
 ) or exists(
  select 1 from crowd_machine.unified_participant_tasks m join crowd_machine.unified_dispatches d using(dispatch_id)
   join crowd_v4.enrollments e on e.invite_hash=d.pilot_invite_hash
   where m.task_id=task and e.user_id=participant and e.completed_at is not null
 );
$function$
;
CREATE OR REPLACE FUNCTION public.crowd_v4_claim(p_task bigint DEFAULT NULL::bigint)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare u uuid := auth.uid(); p crowd_v4.participants; t crowd_v4.tasks; n int;
begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 select * into p from crowd_v4.participants where user_id=u for update;
 if p.status is distinct from 'approved' then raise exception 'approval_required' using errcode='42501'; end if;
 if p.consent is distinct from 'crowd-public-v4' then raise exception 'consent_required'; end if;
 if crowd_v4.pilot_phase(u)='awaiting_acceptance' and crowd_v4.pilot_block_reason(null::bigint,u)='test_completed' then
  return jsonb_build_object('error','test_completed','pilot_phase','awaiting_acceptance');
 end if;
 select count(*) into n from crowd_v4.proofs where user_id=u and received_at>=date_trunc('day',now() at time zone 'Asia/Shanghai') at time zone 'Asia/Shanghai';
 if (n>=p.quota_day and (crowd_observation.owner_pro_authorization(p_task,u)is not null or coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)<=0)) and not exists(select from crowd_v4.tasks rt join crowd_v4.test_task_owners ro on ro.task_id=rt.id and ro.user_id=u where rt.claimed_by=u and rt.status='leased' and rt.lease_until>clock_timestamp() and rt.comments_capture and rt.received>=rt.target and (p_task is null or rt.id=p_task)) then return jsonb_build_object('error','daily_quota',
 'reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
 'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint); end if;
 -- Same owner renews an existing lease before receiving another task.
 select * into t from crowd_v4.tasks where claimed_by=u and status='leased' and not exists(select 1 from crowd_v4.test_task_owners r where r.task_id=crowd_v4.tasks.id and r.user_id<>u) and crowd_v4.pilot_block_reason(crowd_v4.tasks.id,u) is null and (p_task is null or id=p_task) and ((n<p.quota_day or crowd_observation.owner_pro_authorization(p_task,u)is null and coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)>0) or lease_until>clock_timestamp() and comments_capture and received>=target and exists(select from crowd_v4.test_task_owners ro where ro.task_id=crowd_v4.tasks.id and ro.user_id=u)) order by id limit 1 for update;
 if t.id is null then
  if (n>=p.quota_day and (crowd_observation.owner_pro_authorization(p_task,u)is not null or coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)<=0)) then return jsonb_build_object('error','daily_quota',
 'reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
 'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint); end if;

  if p_task is not null and coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)<=0 then return jsonb_build_object('task',null); end if;
  select * into t from crowd_v4.tasks where received<target and (p_task is null or id=p_task) and crowd_v4.dispatch_candidate_allowed(crowd_v4.tasks.id,u) and not exists(select 1 from crowd_v4.test_task_owners r where r.task_id=crowd_v4.tasks.id and r.user_id<>u) and crowd_v4.pilot_block_reason(crowd_v4.tasks.id,u) is null and ((status='open' and (available_at<=now() or (crowd_v4.acceptance_supplement_view(crowd_v4.tasks.id,u)->>'schema'='crowd-acceptance-batch-v1' and coalesce((crowd_v4.acceptance_supplement_view(crowd_v4.tasks.id,u)->>'remaining')::int,0)>0 and crowd_v4.tasks.received>crowd_v4.tasks.lease_start_received))) or (status='leased' and lease_until<now())) order by last_claimed_at nulls first,id limit 1 for update skip locked;
 end if;
 if t.id is null then return jsonb_build_object('task',null); end if;
 update crowd_v4.tasks set last_claimed_at=case when status='leased' and claimed_by=u then last_claimed_at else now() end,
 lease_start_received=case when status='leased' and claimed_by=u then lease_start_received else received end,
 status='leased',claimed_by=u,lease_token=case when status='leased' and claimed_by=u then coalesce(lease_token,gen_random_uuid()) else gen_random_uuid() end,
 lease_until=now()+interval '20 minutes' where id=t.id returning * into t;
 return jsonb_build_object('task',(to_jsonb(t)-'claimed_by'-'source_key')||jsonb_build_object('remaining_today',case when crowd_v4.acceptance_supplement_view(t.id,u) is not null then (crowd_v4.acceptance_supplement_view(t.id,u)->>'remaining')::int else least(p.quota_day-n,coalesce(crowd_v4.pilot_remaining(t.id,u),p.quota_day-n)) end,
 'repair_only',t.comments_capture and t.received>=t.target and exists(select from crowd_v4.test_task_owners ro where ro.task_id=t.id and ro.user_id=u),
 'repair_notes',(select coalesce(jsonb_agg(jsonb_build_object('parent',r.request,'record',r.payload->'record')),'[]'::jsonb) from crowd_v4.receipts r where r.user_id=u and r.result->>'inserted'='true' and (r.request=any(t.comment_repair_parents) or t.comments_capture and t.received>=t.target and exists(select from crowd_v4.test_task_owners ro where ro.task_id=t.id and ro.user_id=u) and exists(select from crowd_v4.proofs f where f.user_id=u and f.task_id=t.id and f.note_id=r.payload#>>'{record,standard,note_id}')) and ((u='7033ff0c-65d7-4963-b65c-a4ac9e31f03a'::uuid
 and t.structured_capture and t.comments_capture and t.received>=t.target
 and exists(select from crowd_v4.test_task_owners explicit_owner where explicit_owner.task_id=t.id and explicit_owner.user_id=u)
 and ((t.id=17 and t.comment_repair_parents=array['907a302c-6891-4334-9aee-4fa1ec654c8a'::uuid] and r.request='907a302c-6891-4334-9aee-4fa1ec654c8a'::uuid and r.payload#>>'{record,standard,note_id}'='6aad055800000000110325cb')
 or (t.id=18 and t.comment_repair_parents=array['b7fc2ea5-6728-4e79-825b-057e6e2df693'::uuid] and r.request='b7fc2ea5-6728-4e79-825b-057e6e2df693'::uuid and r.payload#>>'{record,standard,note_id}'='6a0d5c48000000000702de09')))
 or not exists(select from crowd_observation.comment_pages cp where cp.user_id=u and cp.parent_request=r.request and cp.page=cp.total-1 and cp.data#>>'{summary,complete}'='true'))),
 'known_note_ids',(select coalesce(jsonb_agg(known.note_id),'[]'::jsonb) from (
   select f.note_id from crowd_v4.proofs f join crowd_v4.tasks source on source.id=f.task_id
   where source.query=t.query order by f.id desc limit 500
 ) known)))||case when crowd_v4.acceptance_supplement_view(t.id,u) is null then '{}'::jsonb else jsonb_build_object('acceptance_supplement',crowd_v4.acceptance_supplement_view(t.id,u)) end;
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
 if p_task is null and crowd_observation.owner_pro_authorization(null,u,p_installation)is not null then
  p_task:=(crowd_observation.owner_pro_authorization(null,u,p_installation)->>'task_id')::bigint;
 end if;
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
CREATE OR REPLACE FUNCTION crowd_observation.pro_scope(p_task bigint, p_installation_id uuid, p_lease uuid DEFAULT NULL::uuid, p_live boolean DEFAULT false, p_recovery boolean DEFAULT false)
 RETURNS crowd_v4.tasks
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare u uuid:=auth.uid();t crowd_v4.tasks;g jsonb;
begin
 if u is null then raise exception 'login_required' using errcode='42501';end if;
 perform 1 from crowd_v4.participants where user_id=u for update;
 if not found then raise exception 'approval_required';end if;
 select * into t from crowd_v4.tasks where id=p_task for update;
 if exists(select from crowd_v4.participant_pro_batches where task_id=p_task and owner_dispatch_id is not null)
  and crowd_observation.owner_pro_authorization(p_task,u,p_installation_id,p_recovery)is null then raise exception 'pro_scope_denied'using errcode='42501';end if;
 if exists(select from crowd_v4.participant_pro_batches where task_id=p_task) then
  if t.id is null or t.claimed_by is distinct from u
   or not exists(select from crowd_v4.nodes where installation_id=p_installation_id and user_id=u)
   or not exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id=u)
   or exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id<>u)
   or not exists(select from crowd_v4.participant_pro_batches b where b.task_id=p_task and b.user_id=u
     and b.installation_id=p_installation_id and b.target=t.target and crowd_v4.acceptance_task_input(t)=b.baseline_task)
   then raise exception 'pro_scope_denied' using errcode='42501';end if;
  if not p_recovery and crowd_v4.acceptance_supplement_view(p_task,u) is null then raise exception 'pro_scope_denied' using errcode='42501';end if;
  if p_lease is not null and (t.lease_token is distinct from p_lease or not exists(select from crowd_v4.node_runs where installation_id=p_installation_id and user_id=u and task_id=p_task and lease_token=p_lease)) then raise exception 'lease_lost';end if;
  if p_live and (p_lease is null or t.status<>'leased' or t.lease_until is null or t.lease_until<=now()) then raise exception 'lease_expired';end if;
  return t;
 end if;
 if p_task is distinct from 19 or t.id is null or t.claimed_by is distinct from u or t.target<>22 or t.received not between 20 and 22
  or not exists(select from crowd_v4.nodes where installation_id=p_installation_id and user_id=u)
  or not exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id=u)
  or exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id<>u) then raise exception 'pro_scope_denied' using errcode='42501';end if;
 if p_recovery then
  if not exists(select from crowd_v4.acceptance_supplements where task_id=p_task and user_id=u and installation_id=p_installation_id and id='8df461ae-cdff-4476-bc03-47126d6eaecf'::uuid) then raise exception 'pro_scope_denied';end if;return t;
 end if;
 g:=crowd_v4.acceptance_supplement_view(p_task,u);
 if g->>'schema' is distinct from 'crowd-acceptance-batch-v1' or g->>'installation_id' is distinct from p_installation_id::text or g->>'id' is distinct from '8df461ae-cdff-4476-bc03-47126d6eaecf' or g->'baseline_received' is distinct from '2'::jsonb or g->'extra_limit' is distinct from '20'::jsonb or g->'target' is distinct from '22'::jsonb then raise exception 'pro_scope_denied' using errcode='42501';end if;
 if p_lease is not null and (t.lease_token is distinct from p_lease or not exists(select from crowd_v4.node_runs where installation_id=p_installation_id and user_id=u and task_id=p_task and lease_token=p_lease)) then raise exception 'lease_lost';end if;
 if p_live and (p_lease is null or t.status<>'leased' or t.lease_until is null or t.lease_until<=now()) then raise exception 'lease_expired';end if;
 return t;
end $function$
;
CREATE OR REPLACE FUNCTION crowd_observation.guard_internal(p_action text DEFAULT 'control'::text, p_task bigint DEFAULT NULL::bigint, p_note text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
 u uuid:=auth.uid(); p crowd_v4.participants; c crowd_v4.policy; s crowd_v4.safety;
 t timestamptz:=clock_timestamp(); d date; caps jsonb; factor numeric; reason text; wait_until timestamptz;
 gap_seconds integer; configured_gap_ms integer; action_key text; admitted boolean:=false; owner uuid; result jsonb; batch_caps jsonb;
begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 if p_action is null or p_action not in ('control','search','detail','comment','scroll','captcha','rate_limit','profile') then raise exception 'invalid_action'; end if;
 action_key:=case when p_action='profile' then 'detail' else p_action end;
 -- One identity's admission decisions serialize with its quota/lease operations.
 select * into p from crowd_v4.participants where user_id=u for update;
 if p.status is distinct from 'approved' or p.consent is distinct from 'crowd-public-v4' then raise exception 'approval_required' using errcode='42501'; end if;
 select * into c from crowd_v4.policy where singleton;
 gap_seconds:=coalesce((select action_gap_seconds from crowd_v4.tasks where id=p_task and claimed_by=u and status='leased' and lease_until>t),c.gap_seconds);
 select task.action_gap_milliseconds into configured_gap_ms from crowd_v4.tasks task join crowd_v4.test_task_owners reservation on reservation.task_id=task.id and reservation.user_id=u where task.id=p_task and task.claimed_by=u and task.status='leased' and task.lease_until>t;
 if c.version is null then raise exception 'control_unavailable'; end if;
 insert into crowd_v4.safety(user_id) values(u) on conflict do nothing;
 select * into s from crowd_v4.safety where user_id=u for update;
 d:=(t at time zone 'Asia/Shanghai')::date;
 if d>s.day then s.day:=d; s.counts:='{"search":0,"detail":0,"comment":0,"scroll":0}'; end if;
 -- Server enrollment age, never a resettable client date. Future dates stay at 20%.
 factor:=least(1,0.2+greatest(0,floor(extract(epoch from t-p.joined_at)/86400))*0.8/6);
 caps:=jsonb_build_object('search',least(c.search_cap,coalesce((select task.daily_search_cap from crowd_v4.tasks task join crowd_v4.test_task_owners reservation on reservation.task_id=task.id and reservation.user_id=u where task.id=p_task and task.claimed_by=u and task.status='leased' and task.lease_until>t),greatest(1,floor(c.search_cap*factor)))),
 'detail',least(c.detail_cap,coalesce((select task.daily_detail_cap from crowd_v4.tasks task join crowd_v4.test_task_owners reservation on reservation.task_id=task.id and reservation.user_id=u where task.id=p_task and task.claimed_by=u and task.status='leased' and task.lease_until>t),greatest(1,floor(c.detail_cap*factor)))), 'comment',least(c.comment_cap*10,coalesce((select task.daily_comment_cap from crowd_v4.tasks task join crowd_v4.test_task_owners reservation on reservation.task_id=task.id and reservation.user_id=u where task.id=p_task and task.claimed_by=u and task.status='leased' and task.lease_until>t),greatest(1,floor(c.comment_cap*factor)))), 'scroll',greatest(1,floor(c.scroll_cap*factor)));
 -- Only the already-authorized original local batch may use its configured bounded detail ceiling.
 if p_task=19 then
  batch_caps:=crowd_v4.acceptance_supplement_view(p_task,u);
  if batch_caps->>'schema'='crowd-acceptance-batch-v1' and (batch_caps->>'remaining')::integer>0
   and exists(select from crowd_v4.tasks task where task.id=p_task and task.claimed_by=u and task.status='leased' and (p_action='control' or task.lease_until>t)) then
   caps:=jsonb_set(caps,'{detail}',to_jsonb(least(200,coalesce((select task.daily_detail_cap from crowd_v4.tasks task where task.id=p_task),c.detail_cap))));
   if batch_caps->>'installation_id'='3cde2858-39a5-42e1-b7ab-dd62053d2dac' then
    caps:=jsonb_set(caps,'{scroll}',to_jsonb(least(200,coalesce((select task.daily_detail_cap from crowd_v4.tasks task where task.id=p_task),c.detail_cap))));
   end if;
  end if;
 end if;
 if p_action in ('control','search','detail') and exists(
  select from crowd_v4.participant_pro_batches b join crowd_v4.tasks task on task.id=b.task_id
  where b.owner_dispatch_id is null and b.task_id=p_task and b.user_id=u and task.claimed_by=u and task.status='leased' and task.lease_until>t
   and b.installation_id=(crowd_v4.acceptance_supplement_view(p_task,u)->>'installation_id')::uuid
   and crowd_v4.acceptance_supplement_view(p_task,u)->>'id'=b.id::text
   and coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)>0) then
  caps:=jsonb_set(caps,'{detail}',to_jsonb(least(200,coalesce((select task.daily_detail_cap from crowd_v4.tasks task where task.id=p_task),c.detail_cap))));
 end if;
 if p_action in ('captcha','rate_limit') then
  if p_action='rate_limit' and exists(select from crowd_observation.recovery_controls r join crowd_v4.test_task_owners o on o.task_id=r.task_id and o.user_id=u join crowd_v4.tasks rt on rt.id=r.task_id join crowd_v4.proofs f on f.task_id=r.task_id and f.user_id=u and f.note_id=r.note_id where r.user_id=u and r.enabled and rt.claimed_by=u and rt.status='leased') and (s.cooldown_reason is null or s.cooldown_reason='rate_limit' or s.cooldown_until<=t) then
   update crowd_observation.recovery_controls r set failure_count=least(1000000,failure_count+1),last_signal_at=t,
    next_probe_at=greatest(next_probe_at,t+crowd_observation.recovery_delay(least(1000000,failure_count+1))),
    safety_deadline=greatest(next_probe_at,t+crowd_observation.recovery_delay(least(1000000,failure_count+1))),attempt=null,attempt_until=null,grant_task_ids=null,grant_bindings=null,last_result='rate_limit',last_attempt=null,last_response=null where r.user_id=u;
   select safety_deadline into s.cooldown_until from crowd_observation.recovery_controls where user_id=u;
   s.cooldown_reason:='rate_limit';
  elsif p_action='captcha' then
   update crowd_observation.recovery_controls set enabled=false,attempt=null,attempt_until=null,grant_task_ids=null,grant_bindings=null,last_result='captcha' where user_id=u;
   s.cooldown_until:=greatest(s.cooldown_until,t+interval '30 minutes'); s.cooldown_reason:='captcha';
  elsif s.cooldown_reason is distinct from 'captcha' or s.cooldown_until<=t then
   s.cooldown_until:=greatest(s.cooldown_until,t+interval '24 hours'); s.cooldown_reason:='rate_limit';
  end if;
 end if;
 -- Only a participant enrolled today has complete lifetime counts in this day.
 -- Older or cross-midnight histories cannot establish why an old rest began.
 if s.cooldown_reason='session_rest' and s.session_count=0 and s.cooldown_until>t
  and p.joined_at >= (d::timestamp at time zone 'Asia/Shanghai') and p.joined_at<=t
  and (select day from crowd_v4.safety where user_id=u)=d
  and (select coalesce(sum(value::integer),0) from jsonb_each_text(s.counts))<20 then
  wait_until:=least(s.cooldown_until,greatest(t,least(t,s.next_action)+interval '30 minutes'));
  if s.session_started=s.cooldown_until then s.session_started:=wait_until; end if;
  s.cooldown_until:=wait_until;
  wait_until:=null;
 end if;
 if s.cooldown_until>t then reason:=s.cooldown_reason; wait_until:=s.cooldown_until;
 elsif c.paused then reason:='global_pause'; wait_until:=t+interval '5 minutes';
 elsif s.next_action>t then reason:='action_gap'; wait_until:=s.next_action;
 end if;
 if p_action in ('search','detail','comment','scroll','profile') and reason is null then
  if not exists(select from crowd_v4.tasks where id=p_task and claimed_by=u and status='leased' and lease_until>t) then
   return jsonb_build_object('error','lease_expired');
  end if;
  if (s.counts->>action_key)::int >= (caps->>action_key)::int then
   reason:='action_budget'; wait_until:=(d+1)::timestamp at time zone 'Asia/Shanghai';
  else
   if s.session_count>0 and s.next_action+interval '30 minutes'<=t then
    s.session_count:=0; s.session_started:=t;
   end if;
   if s.session_count>=coalesce((select session_action_limit from crowd_v4.tasks where id=p_task and claimed_by=u and status='leased' and lease_until>t),20) or (s.session_count>0 and s.session_started+make_interval(secs=>coalesce((select session_window_seconds from crowd_v4.tasks where id=p_task and claimed_by=u and status='leased' and lease_until>t),1200))<=t) then
    if s.session_count>=coalesce((select session_action_limit from crowd_v4.tasks where id=p_task and claimed_by=u and status='leased' and lease_until>t),20) then
     s.session_started:=t+interval '30 minutes';
    else
     s.session_started:=greatest(t,least(t,s.next_action)+interval '30 minutes');
    end if;
    s.session_count:=0;
    s.cooldown_until:=s.session_started; s.cooldown_reason:='session_rest';
    reason:='session_rest'; wait_until:=s.cooldown_until;
   else
    if p_action='profile' and not exists(select from crowd_observation.profile_attempts a join crowd_observation.notes n using(author_id) where a.user_id=u and n.note_id=p_note and a.attempted_at>t-interval '1 minute') then raise exception 'profile_not_admitted'; end if; if p_action='detail' then
     if p_note is null or p_note !~ '^[a-f0-9]{24}$' then raise exception 'invalid_note'; end if;
     if exists(select from crowd_v4.proofs where note_id=p_note) and not exists(select from crowd_v4.tasks task join crowd_v4.receipts r on r.request=any(task.comment_repair_parents) and r.user_id=u and r.result->>'inserted'='true' where task.id=p_task and task.claimed_by=u and task.status='leased' and task.lease_until>t and task.comments_capture and r.payload->'record'->'standard'->>'note_id'=p_note) and not exists(select from crowd_v4.tasks rt join crowd_v4.test_task_owners ro on ro.task_id=rt.id and ro.user_id=u join crowd_v4.proofs f on f.task_id=rt.id and f.user_id=u and f.note_id=p_note where rt.id=p_task and rt.claimed_by=u and rt.status='leased' and rt.lease_until>t and rt.comments_capture and rt.received>=rt.target) then
      reason:='known_note';
     else
      -- Only reserve one requested ID, never expose another participant or proof.
      insert into crowd_v4.note_reservations(note_id,user_id,expires_at) values(p_note,u,t+interval '10 minutes')
      on conflict(note_id) do update set user_id=u,expires_at=t+interval '10 minutes'
       where crowd_v4.note_reservations.expires_at<=t or crowd_v4.note_reservations.user_id=u
      returning user_id into owner;
      if owner is null then reason:='note_busy'; end if;
     end if;
    end if;
    if reason is null then
     if s.session_count=0 then s.session_started:=t; end if;
     s.session_count:=s.session_count+1;
     s.counts:=jsonb_set(s.counts,array[action_key],to_jsonb((s.counts->>action_key)::int+1));
     -- Sample ONCE per admitted action and persist; polling never redraws the wait.
     s.next_action:=case when configured_gap_ms is not null then t+configured_gap_ms*interval '1 millisecond' else t+make_interval(secs=>gap_seconds+floor(random()*least(16,floor(gap_seconds/2.0)::int+1))::int) end;
     admitted:=true;
    end if;
   end if;
  end if;
 end if;
 update crowd_v4.safety set day=s.day,counts=s.counts,next_action=s.next_action,cooldown_until=s.cooldown_until,
 cooldown_reason=s.cooldown_reason,session_count=s.session_count,session_started=s.session_started where user_id=u;
 -- Expired reservations are not retained as a browsing history.
 delete from crowd_v4.note_reservations where expires_at<t-interval '1 day';
 result:=jsonb_build_object('observations',1,'relevance_revision',1,'version',c.version,'ttl_ms',600000,'paused',c.paused,'allowed',admitted,
 'reason',reason,'wait_ms',greatest(0,ceil(extract(epoch from (wait_until-t))*1000)),
 'action_wait_ms',greatest(0,ceil(extract(epoch from (s.next_action-t))*1000)),'gap_ms',coalesce(configured_gap_ms,gap_seconds*1000),'caps',caps,'counts',s.counts,'session_count',s.session_count);
 result:=result||jsonb_build_object('recovery_enabled',exists(select from crowd_observation.recovery_controls r where r.user_id=u and r.enabled),'recovery_wait_ms',(select greatest(0,ceil(extract(epoch from r.next_probe_at-t)*1000)) from crowd_observation.recovery_controls r where r.user_id=u and r.enabled));
 return result;
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
 routes jsonb:='[]'; child jsonb; reason text; v_dispatch uuid; owner_new boolean:=false;created_task jsonb;owner_user uuid;owner_install uuid;owner_cap jsonb;pro_mode boolean; bindings jsonb:='{}';cap jsonb;node_user uuid;node_install uuid; machine_result jsonb; machine_id uuid; key text;
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
 if p_action='unified_cancel' then
  if p_payload-array['dispatch_id']<>'{}'::jsonb or coalesce(p_payload->>'dispatch_id','')!~'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'then raise exception'invalid_request';end if;
  v_dispatch:=(p_payload->>'dispatch_id')::uuid;
  select *into old from crowd_machine.unified_dispatches where dispatch_id=v_dispatch and owner_scope=p_owner_scope;
  if not found or not exists(select from crowd_v4.participant_pro_batches where owner_dispatch_id=v_dispatch)then raise exception'principal_denied';end if;
  for selected_task in select t.*from crowd_v4.tasks t join crowd_v4.participant_pro_batches b on b.task_id=t.id where b.owner_dispatch_id=v_dispatch order by t.id loop
   perform 1 from crowd_v4.participants where user_id=(select user_id from crowd_v4.participant_pro_batches where task_id=selected_task.id)for update;
   perform 1 from crowd_v4.tasks where id=selected_task.id for update;
   update crowd_v4.participant_pro_batches set revoked=true where task_id=selected_task.id and not revoked and exists(select from crowd_v4.tasks where id=selected_task.id and status<>'complete');
   update crowd_v4.tasks set status='closed'where id=selected_task.id and status<>'complete';
  end loop;
  if exists(select from crowd_v4.participant_pro_batches where owner_dispatch_id=v_dispatch and revoked)and not exists(select from crowd_v4.audit where action='owner_pro_cancel'and payload->>'dispatch_id'=v_dispatch::text)then
   insert into crowd_v4.audit(action,payload)values('owner_pro_cancel',jsonb_build_object('dispatch_id',v_dispatch));
  end if;
  return crowd_machine.unified_dispatch_view(v_dispatch);
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
 -- Only a fresh full match for this one Owner request can authorize a new ordinary task.
 if pro_mode and reason is not null and proposal#>'{request,platforms}'='["xhs"]'::jsonb
  and jsonb_array_length(participant->'targets')=1 and (participant->>'item_quota')::integer between 1 and 100 and proposal#>>'{request,purpose}'='noncommercial_research'
  and coalesce(proposal#>'{request,headless}','false'::jsonb)='false'::jsonb
  and coalesce(proposal#>'{request,timeout_seconds}','600'::jsonb)='600'::jsonb then
  select n.user_id,n.installation_id,n.pro_capabilities into owner_user,owner_install,owner_cap
  from crowd_v4.nodes n join crowd_v4.participants p on p.user_id=n.user_id
  where p.status='approved'and p.consent='crowd-public-v4'
   and crowd_observation.pro_node_capable(n.user_id,n.installation_id,(participant->>'request_quota')::integer)
   and p.quota_day-(select count(*)from crowd_v4.proofs where user_id=p.user_id and received_at>=date_trunc('day',now()at time zone'Asia/Shanghai')at time zone'Asia/Shanghai')>=(participant->>'item_quota')::integer
   and not exists(select from crowd_v4.tasks live where live.claimed_by=n.user_id and live.status in('open','leased'))
   and not exists(select from crowd_v4.participant_pro_batches b join crowd_v4.tasks pending on pending.id=b.task_id where b.user_id=n.user_id and b.owner_dispatch_id is not null and not b.revoked and pending.status in('open','leased'))
  order by n.updated_at,n.installation_id limit 1 for update of p skip locked;
  if found then
   owner_new:=true;reason:=null;cohort:=null;ids:='{}';bindings:='{}';
   if p_action='unified_create'then
    v_dispatch:=gen_random_uuid();
    created_task:=public.crowd_v4_admin('publish',jsonb_build_object('source_key','owner-pro:'||v_dispatch::text,'query',participant#>>'{targets,0}','store_name',participant#>>'{targets,0}','anchor_terms',participant->'targets','target',participant->'item_quota'));
    update crowd_v4.tasks set comments_capture=true,source_executor='mediacrawler_pro'where id=(created_task->>'id')::bigint returning*into selected_task;
    ids:=array[selected_task.id];
    bindings:=jsonb_build_object(selected_task.id::text,jsonb_build_object('subject',owner_user,'installation_id',owner_install,'capabilities',owner_cap));
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
    'request_quota',case when pro_mode then participant->'request_quota' else null end,'state',case when reason is null then 'queued' else 'waiting' end,'reason_code',reason,'task_ids',to_jsonb(ids),'budget_basis',case when owner_new then 'owner_request_and_original_safety'else 'existing_pilot_guard'end)||case when pro_mode then jsonb_build_object('executor','mediacrawler_pro','required_capability','crowd-participant-pro-comment-options-v1','comment_options',participant->'comment_options','participant_bindings',bindings)||case when owner_new then jsonb_build_object('authorization_kind','owner_dispatch','owner_request_hash',proposal->>'request_hash','targets',participant->'targets')else '{}'::jsonb end else '{}'::jsonb end);
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
 insert into crowd_machine.unified_dispatches(dispatch_id,owner_scope,idempotency_key,request_hash,request,routes,pilot_invite_hash,machine_task_id)
  values(coalesce(v_dispatch,gen_random_uuid()),p_owner_scope,proposal->'request'->>'idempotency_key',proposal->>'request_hash',proposal->'request',routes,cohort,machine_id) returning unified_dispatches.dispatch_id into v_dispatch;
 insert into crowd_machine.unified_participant_tasks(task_id,dispatch_id) select task_id,v_dispatch from unnest(ids) task_id;
 if owner_new then
  insert into crowd_v4.test_task_owners(task_id,user_id)values(selected_task.id,owner_user);
  insert into crowd_v4.participant_pro_batches(task_id,user_id,installation_id,invite_hash,baseline_task,target,expires_at,owner_dispatch_id)
   values(selected_task.id,owner_user,owner_install,null,crowd_v4.acceptance_task_input(selected_task),selected_task.target,null,v_dispatch);
  insert into crowd_v4.audit(action,payload)values('owner_pro_authorize',jsonb_build_object('dispatch_id',v_dispatch,'task_id',selected_task.id,'request_hash',proposal->>'request_hash','items',selected_task.target,'max_api_requests',participant->'request_quota'));
 end if;
 return crowd_machine.unified_dispatch_view(v_dispatch);
end $function$
;
CREATE OR REPLACE FUNCTION crowd_machine.unified_dispatch_view(p_id uuid)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
 select jsonb_build_object('schema','crowd-unified-dispatch-v1','dispatch_id',d.dispatch_id,
  'idempotency_key',d.idempotency_key,'created_at',d.created_at,'ready',true,'reason',null,
  'routes',coalesce((select jsonb_agg(route||case when route->>'execution_kind'='participant_extension' then
    jsonb_build_object('received',(select coalesce(sum(t.received),0) from crowd_machine.unified_participant_tasks m join crowd_v4.tasks t on t.id=m.task_id where m.dispatch_id=d.dispatch_id),
      'state',case when route->>'authorization_kind'='owner_dispatch'and exists(select from crowd_v4.participant_pro_batches b where b.owner_dispatch_id=d.dispatch_id and b.revoked)then 'stopped'when (select coalesce(sum(t.received),0) from crowd_machine.unified_participant_tasks m join crowd_v4.tasks t on t.id=m.task_id where m.dispatch_id=d.dispatch_id)>=(route->>'item_quota')::integer then 'completed'
       when not exists(select 1 from crowd_machine.unified_participant_tasks m join crowd_v4.tasks t on t.id=m.task_id where m.dispatch_id=d.dispatch_id and t.status not in ('complete','exhausted','closed')) then 'exhausted'
       when exists(select 1 from crowd_machine.unified_participant_tasks m join crowd_v4.tasks t on t.id=m.task_id where m.dispatch_id=d.dispatch_id and t.status='leased' and t.lease_until>now()) then 'running' else 'queued' end)
   else coalesce((select jsonb_build_object('received',c->'contents','state',case when c->>'state'='running' and (c->>'lease_until')::timestamptz<=now() or c->>'state'='unknown' then 'interrupted_unknown' else c->>'state' end)
      from jsonb_array_elements(crowd_machine.public_task(d.machine_task_id)->'children') c where c->>'platform'=route->>'platform'),'{}'::jsonb) end)
    from jsonb_array_elements(d.routes) route),'[]'::jsonb),
  'scope',case when exists(select from crowd_v4.participant_pro_batches b where b.owner_dispatch_id=d.dispatch_id)then 'owner_authorized_pro_and_machine'else 'existing_pilot_and_machine'end,'source_actions_started',0,'created',true,'replayed',false)
 from crowd_machine.unified_dispatches d where d.dispatch_id=p_id;
$function$
;
commit;
