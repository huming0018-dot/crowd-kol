begin;
do $cas$ begin
 if md5(pg_get_functiondef('crowd_v4.pilot_block_reason(bigint,uuid)'::regprocedure)) is distinct from 'dca003a52f651ec993ec0b0d67dbe800' then raise exception 'supplement_definition_drift'; end if;
 if md5(pg_get_functiondef('crowd_v4.pilot_remaining(bigint,uuid)'::regprocedure)) is distinct from '3e9c07786eebc86b3f4340087eb7f74f' then raise exception 'supplement_definition_drift'; end if;
 if md5(pg_get_functiondef('public.crowd_v4_claim(bigint)'::regprocedure)) is distinct from 'aa6921d80e924e553803c4f5579fd538' then raise exception 'supplement_definition_drift'; end if;
 if md5(pg_get_functiondef('public.crowd_v4_guard(text,bigint,text)'::regprocedure)) is distinct from '8b4c35ba37bbd2b375fd2282325dcd74' then raise exception 'supplement_definition_drift'; end if;
 if md5(pg_get_functiondef('public.crowd_v4_status()'::regprocedure)) is distinct from '2f30047d0363f05dd6bdd9c03b262910' then raise exception 'supplement_definition_drift'; end if;
 if md5(pg_get_functiondef('public.crowd_v4_submit(uuid,bigint,uuid,jsonb)'::regprocedure)) is distinct from '8325e723f538c4c0265bd9a95335bed7' then raise exception 'supplement_definition_drift'; end if;
 if md5(pg_get_functiondef('crowd_observation.submit_internal(uuid,bigint,uuid,jsonb)'::regprocedure)) is distinct from '836650b9cf77bb8bd1f3f82c596012ae' then raise exception 'supplement_definition_drift'; end if;
 if md5(pg_get_functiondef('public.crowd_v4_node_claim(uuid,bigint)'::regprocedure)) is distinct from '8e90df13ec94169f6b8726f1f06b2644' then raise exception 'supplement_definition_drift'; end if;
end $cas$;
-- One explicitly authorized extra receipt per original participant/task/node. No activation of48h.
create table crowd_v4.acceptance_supplements (
 id uuid primary key, user_id uuid not null unique references crowd_v4.participants(user_id),
 task_id bigint not null unique references crowd_v4.tasks(id), installation_id uuid not null references crowd_v4.nodes(installation_id),
 invite_hash text not null references crowd_v4.pilot_experiments(invite_hash), baseline_proofs jsonb not null,
 baseline_task jsonb not null, expires_at timestamptz not null, created_at timestamptz not null default now(),
 revoked boolean not null default false, consumed_request uuid,
 check ((task_id=19 and user_id='2fc8765e-700a-41c1-b325-a21c5faa22ce'::uuid and installation_id='3cde2858-39a5-42e1-b7ab-dd62053d2dac'::uuid)
 or (task_id=20 and user_id='77395977-c94d-4b1c-bda8-21ba249c7878'::uuid and installation_id='6a88f8fd-c41d-4e5e-ab24-efc2c622d575'::uuid)),
 check(jsonb_typeof(baseline_proofs)='array' and jsonb_array_length(baseline_proofs)=2),check(expires_at>created_at and expires_at<=created_at+interval '2 hours')
);
alter table crowd_v4.acceptance_supplements enable row level security;
revoke all on crowd_v4.acceptance_supplements from public,anon,authenticated,service_role;

create function crowd_v4.acceptance_task_input(t crowd_v4.tasks) returns jsonb language sql immutable set search_path='' as $$
 select to_jsonb(t)-array['target','received','status','claimed_by','lease_token','lease_until','available_at','last_claimed_at','lease_start_received'];
$$;
create function crowd_v4.acceptance_supplement_view(task bigint,participant uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare g crowd_v4.acceptance_supplements; t crowd_v4.tasks; old_rows jsonb; total integer;
begin
 select * into g from crowd_v4.acceptance_supplements where user_id=participant and (task is null or task_id=task);
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
end $$;

create function public.crowd_v4_acceptance_supplement(p_action text,p_id uuid,p_task bigint,p_user uuid,p_installation uuid,p_expires_at timestamptz default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare g crowd_v4.acceptance_supplements; t crowd_v4.tasks; cohort text; baseline jsonb;
begin
 if auth.role() is distinct from 'service_role' then raise exception 'owner_required' using errcode='42501'; end if;
 if p_action not in ('grant','revoke') or p_action is null or p_id is null or p_task is null or p_user is null or p_installation is null
 or not ((p_task=19 and p_user='2fc8765e-700a-41c1-b325-a21c5faa22ce'::uuid and p_installation='3cde2858-39a5-42e1-b7ab-dd62053d2dac'::uuid)
 or (p_task=20 and p_user='77395977-c94d-4b1c-bda8-21ba249c7878'::uuid and p_installation='6a88f8fd-c41d-4e5e-ab24-efc2c622d575'::uuid)) then raise exception 'supplement_scope_denied'; end if;
 perform 1 from crowd_v4.participants where user_id=p_user and status='approved' and consent='crowd-public-v4' and quota_day=2 for update;
 if not found then raise exception 'supplement_subject_denied'; end if;
 select * into g from crowd_v4.acceptance_supplements where id=p_id or user_id=p_user or task_id=p_task for update;
 if found then
  if g.id is distinct from p_id or g.task_id<>p_task or g.user_id<>p_user or g.installation_id<>p_installation then raise exception 'supplement_intent_conflict'; end if;
  if p_action='revoke' then
   if p_expires_at is not null then raise exception 'invalid_supplement'; end if;
   update crowd_v4.acceptance_supplements set revoked=true where id=g.id;
  elsif p_expires_at is distinct from g.expires_at then raise exception 'supplement_intent_conflict'; end if;
  return jsonb_build_object('id',g.id,'revoked',g.revoked or p_action='revoke','acceptance_supplement',crowd_v4.acceptance_supplement_view(p_task,p_user));
 end if;
 if p_action<>'grant' or p_expires_at is null or p_expires_at<=now() or p_expires_at>now()+interval '2 hours' then raise exception 'invalid_supplement'; end if;
 select * into t from crowd_v4.tasks where id=p_task for update;
 if t.status is distinct from 'complete' or t.target<>2 or t.received<>2 or t.comments_capture or t.structured_capture or t.acceptance_goal<>2 or cardinality(t.comment_repair_parents)>0
 or exists(select from crowd_v4.tasks live where live.claimed_by=p_user and live.status='leased' and live.lease_until>now())
 or not exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id=p_user)
 or exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id<>p_user)
 or not exists(select from crowd_v4.nodes where installation_id=p_installation and user_id=p_user) then raise exception 'supplement_task_denied'; end if;
 select e.invite_hash into cohort from crowd_v4.enrollments e join crowd_v4.pilot_experiments x using(invite_hash) join crowd_v4.invites i on i.token_hash=x.invite_hash join crowd_v4.pilot_task_map m on m.task_id=p_task and m.invite_hash=x.invite_hash
 where e.user_id=p_user and e.completed_at is not null and x.phase='awaiting_acceptance' and not i.revoked and i.expires_at>now() and i.max_people<=5 and i.quota_day=2;
 if cohort is null or (select count(*) from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where p.user_id=p_user and m.invite_hash=cohort)<>2
 or (select count(*) from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where m.invite_hash=cohort)>=20 then raise exception 'supplement_baseline_denied'; end if;
 select jsonb_agg(jsonb_build_object('id',p.id,'note_id',p.note_id,'record_md5',md5(p.record::text)) order by p.id) into baseline from crowd_v4.proofs p where p.user_id=p_user and p.task_id=p_task;
 if jsonb_array_length(baseline) is distinct from 2 then raise exception 'supplement_baseline_denied'; end if;
 insert into crowd_v4.acceptance_supplements(id,user_id,task_id,installation_id,invite_hash,baseline_proofs,baseline_task,expires_at)
 values(p_id,p_user,p_task,p_installation,cohort,baseline,to_jsonb(t),p_expires_at);
 update crowd_v4.tasks set target=3,status='open',available_at=now() where id=p_task;
 return jsonb_build_object('id',p_id,'revoked',false,'acceptance_supplement',crowd_v4.acceptance_supplement_view(p_task,p_user));
end $$;
revoke all on function crowd_v4.acceptance_task_input(crowd_v4.tasks),crowd_v4.acceptance_supplement_view(bigint,uuid) from public,anon,authenticated,service_role;
revoke all on function public.crowd_v4_acceptance_supplement(text,uuid,bigint,uuid,uuid,timestamptz) from public,anon,authenticated;
grant execute on function public.crowd_v4_acceptance_supplement(text,uuid,bigint,uuid,uuid,timestamptz) to service_role;

CREATE OR REPLACE FUNCTION crowd_v4.pilot_block_reason(task bigint, participant uuid)
 RETURNS text
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare cohort text; task_cohort text; experiment crowd_v4.pilot_experiments; invitation crowd_v4.invites;
begin
 select e.invite_hash into cohort from crowd_v4.enrollments e join crowd_v4.pilot_experiments x using(invite_hash)
  where e.user_id=participant and e.completed_at is not null;
 select invite_hash into task_cohort from crowd_v4.pilot_task_map where task_id=task;
 if cohort is null then return case when task_cohort is not null then 'user_stopped' else null end; end if;
 if task is not null and task_cohort is distinct from cohort then return 'user_stopped'; end if;
 select * into experiment from crowd_v4.pilot_experiments where invite_hash=cohort;
 select * into invitation from crowd_v4.invites where token_hash=cohort;
 if invitation.revoked or invitation.expires_at<=now() or invitation.max_people>5 or invitation.quota_day<>2
  or experiment.phase='closed' then return 'user_stopped'; end if;
 if experiment.phase='active' and (experiment.armed_at>now() or experiment.ends_at<=now()) then return 'user_stopped'; end if;
 if (select count(*) from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where m.invite_hash=cohort)>=20 then return 'test_completed'; end if;
 if coalesce((crowd_v4.acceptance_supplement_view(task,participant)->>'remaining')::int,0)<>1 and experiment.phase='awaiting_acceptance' and (select count(*) from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where p.user_id=participant and m.invite_hash=cohort)>=2 then return 'test_completed'; end if;
 if exists(select from crowd_v4.tasks where id=task and (received>=target or status in ('complete','exhausted','closed'))) then return 'task_full'; end if;
 if coalesce((crowd_v4.acceptance_supplement_view(task,participant)->>'remaining')::int,0)<>1 and (select count(*) from crowd_v4.proofs where user_id=participant and received_at>=date_trunc('day',now() at time zone 'Asia/Shanghai') at time zone 'Asia/Shanghai')>=2 then return 'daily_quota'; end if;
 return null;
end $function$
;
CREATE OR REPLACE FUNCTION crowd_v4.pilot_remaining(task bigint, participant uuid)
 RETURNS integer
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare cohort text; phase text; received_count integer;
begin
 select m.invite_hash,x.phase into cohort,phase from crowd_v4.pilot_task_map m join crowd_v4.pilot_experiments x using(invite_hash) where m.task_id=task;
 if cohort is null then return null; end if;
 if crowd_v4.acceptance_supplement_view(task,participant) is not null then
  return least((crowd_v4.acceptance_supplement_view(task,participant)->>'remaining')::int,greatest(0,20-(select count(*) from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where m.invite_hash=cohort)::int));
 end if;
 if phase='awaiting_acceptance' then
  select count(*) into received_count from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where p.user_id=participant and m.invite_hash=cohort;
 else
  select count(*) into received_count from crowd_v4.proofs where user_id=participant and received_at>=date_trunc('day',now() at time zone 'Asia/Shanghai') at time zone 'Asia/Shanghai';
 end if;
 return least(greatest(0,2-received_count),greatest(0,20-(select count(*) from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where m.invite_hash=cohort)::integer));
end $function$
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
 if (n>=p.quota_day and coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)<>1) and not exists(select from crowd_v4.tasks rt join crowd_v4.test_task_owners ro on ro.task_id=rt.id and ro.user_id=u where rt.claimed_by=u and rt.status='leased' and rt.lease_until>clock_timestamp() and rt.comments_capture and rt.received>=rt.target and (p_task is null or rt.id=p_task)) then return jsonb_build_object('error','daily_quota',
 'reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
 'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint); end if;
 -- Same owner renews an existing lease before receiving another task.
 select * into t from crowd_v4.tasks where claimed_by=u and status='leased' and not exists(select 1 from crowd_v4.test_task_owners r where r.task_id=crowd_v4.tasks.id and r.user_id<>u) and crowd_v4.pilot_block_reason(crowd_v4.tasks.id,u) is null and (p_task is null or id=p_task) and ((n<p.quota_day or coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)=1) or lease_until>clock_timestamp() and comments_capture and received>=target and exists(select from crowd_v4.test_task_owners ro where ro.task_id=crowd_v4.tasks.id and ro.user_id=u)) order by id limit 1 for update;
 if t.id is null then
  if (n>=p.quota_day and coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)<>1) then return jsonb_build_object('error','daily_quota',
 'reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
 'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint); end if;

  if p_task is not null and coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)<>1 then return jsonb_build_object('task',null); end if;
  select * into t from crowd_v4.tasks where received<target and (p_task is null or id=p_task) and crowd_v4.dispatch_candidate_allowed(crowd_v4.tasks.id,u) and not exists(select 1 from crowd_v4.test_task_owners r where r.task_id=crowd_v4.tasks.id and r.user_id<>u) and crowd_v4.pilot_block_reason(crowd_v4.tasks.id,u) is null and ((status='open' and available_at<=now()) or (status='leased' and lease_until<now())) order by last_claimed_at nulls first,id limit 1 for update skip locked;
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
CREATE OR REPLACE FUNCTION public.crowd_v4_guard(p_action text DEFAULT 'control'::text, p_task bigint DEFAULT NULL::bigint, p_note text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$ declare result jsonb; begin
 if p_action='profile' then raise exception 'invalid_action';end if;

 if auth.uid() is not null and p_action in ('control','search','detail','comment','scroll') and crowd_v4.pilot_block_reason(p_task,auth.uid()) is not null then
  result:=crowd_observation.guard_internal('control',p_task,p_note);
  if result ? 'error' then if crowd_v4.pilot_phase(auth.uid()) is not null then result:=result||jsonb_build_object('pilot_phase',crowd_v4.pilot_phase(auth.uid())); end if; return result; end if;
  return result||jsonb_build_object('allowed',false,'reason',crowd_v4.pilot_block_reason(p_task,auth.uid()),'wait_ms',600000,'action_wait_ms',600000,'pilot_phase',crowd_v4.pilot_phase(auth.uid()))
   ||case when crowd_v4.pilot_block_reason(p_task,auth.uid())='daily_quota' then jsonb_build_object('reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
    'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint) else '{}'::jsonb end;
 end if;
 result:=crowd_observation.guard_internal(p_action,p_task,p_note);
 if p_action='rate_limit' then
  perform 1 from crowd_v4.policy where singleton for update;
  insert into crowd_observation.risk_signals(user_id) values(auth.uid()) on conflict(user_id) do update set seen_at=now();
  delete from crowd_observation.risk_signals where seen_at<now()-interval '24 hours';
  if (select count(*) from crowd_observation.risk_signals where seen_at>now()-interval '10 minutes')>=2 then
   update crowd_v4.policy set paused=true,version=version+1 where not paused;
   if found then insert into crowd_v4.audit(action,payload) values('automatic_pause','{"reason":"multiple_rate_limits"}');end if;
   result:=result||jsonb_build_object('paused',true);
  end if;
 end if;

 if p_action='control' and p_task is not null then
  result:=result||jsonb_build_object('relevance_revision',coalesce((select relevance_revision
   from crowd_v4.tasks where id=p_task and claimed_by=auth.uid() and status='leased'),1));
 end if;
 if crowd_v4.pilot_phase(auth.uid()) is not null then result:=result||jsonb_build_object('pilot_phase',crowd_v4.pilot_phase(auth.uid())); end if;
 if crowd_v4.acceptance_supplement_view(p_task,auth.uid()) is not null then
  result:=result||jsonb_build_object('acceptance_supplement',crowd_v4.acceptance_supplement_view(p_task,auth.uid()));
  if p_action='control' and result->>'reason' is null and result->'paused'='false'::jsonb and not (result ? 'error') then result:=result||jsonb_build_object('allowed',true); end if;
 end if; return result;
end $function$
;
CREATE OR REPLACE FUNCTION public.crowd_v4_status()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare u uuid := auth.uid(); p crowd_v4.participants; n int;
begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 select * into p from crowd_v4.participants where user_id=u;
 select count(*) into n from crowd_v4.proofs where user_id=u;
 return jsonb_build_object('participant',case when p.user_id is null then null else to_jsonb(p)-'user_id' end,
 'received',n,'verified',coalesce(p.verified_count,0),'remainder',coalesce(p.verified_count,0)%100,
 'reward_fen',(select coalesce(sum(amount_fen),0) from crowd_v4.rewards where user_id=u),
 'paid_fen',(select coalesce(sum(amount_fen),0) from crowd_v4.rewards where user_id=u and paid_at is not null))||case when crowd_v4.acceptance_supplement_view(null,u) is null then '{}'::jsonb else jsonb_build_object('acceptance_supplement',crowd_v4.acceptance_supplement_view(null,u)) end;
end $function$
;
CREATE OR REPLACE FUNCTION public.crowd_v4_submit(p_request uuid, p_task bigint, p_lease uuid, p_record jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$ declare result jsonb; was_replay boolean;begin

 perform 1 from crowd_v4.participants where user_id=auth.uid() for update;
 if auth.uid() is not null and not exists(select 1 from crowd_v4.receipts where user_id=auth.uid() and request=p_request)
  and crowd_v4.pilot_block_reason(p_task,auth.uid()) is not null then
  if crowd_v4.pilot_block_reason(p_task,auth.uid())='daily_quota' then
   return jsonb_build_object('error','daily_quota','reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
    'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint);
  end if;
  return jsonb_build_object('error',case when crowd_v4.pilot_block_reason(p_task,auth.uid())='user_stopped' then 'lease_lost' else 'task_full' end);
 end if;
 if not exists(select from crowd_v4.receipts where user_id=auth.uid() and request=p_request) and exists(select from crowd_v4.acceptance_supplements where task_id=p_task and user_id=auth.uid())
 and not exists(select from crowd_v4.acceptance_supplements g join crowd_v4.node_runs nr on nr.installation_id=g.installation_id and nr.user_id=g.user_id and nr.task_id=g.task_id and nr.lease_token=p_lease where g.user_id=auth.uid() and g.task_id=p_task) then return jsonb_build_object('error','lease_lost'); end if;
 was_replay:=exists(select from crowd_v4.receipts where user_id=auth.uid() and request=p_request);
 result:=crowd_observation.submit_internal(p_request,p_task,p_lease,p_record);
 if not was_replay and result->'inserted'='true'::jsonb then update crowd_v4.acceptance_supplements set consumed_request=p_request where task_id=p_task and user_id=auth.uid() and consumed_request is null; end if;
 if p_request is not null then
  insert into crowd_observation.submission_status(user_id,request,task_id,error,parser_version,title_chars,body_chars,anchor_terms)
  values(auth.uid(),p_request,p_task,result->>'error',left(p_record#>>'{evidence,parser_version}',20),length(p_record#>>'{standard,title}'),length(p_record#>>'{evidence,text}'),
    (select anchor_terms from crowd_v4.tasks where id=p_task and claimed_by=auth.uid()))
  on conflict(user_id) do update set request=excluded.request,task_id=excluded.task_id,error=excluded.error,parser_version=excluded.parser_version,
   title_chars=excluded.title_chars,body_chars=excluded.body_chars,anchor_terms=excluded.anchor_terms,updated_at=now();
 end if;
 return result;
end $function$
;
CREATE OR REPLACE FUNCTION crowd_observation.submit_internal(p_request uuid, p_task bigint, p_lease uuid, p_record jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare u uuid := auth.uid(); p crowd_v4.participants; t crowd_v4.tasks; old crowd_v4.receipts; n int; inserted_id bigint; s jsonb; e jsonb; result jsonb; capture timestamptz; payload jsonb;
begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 if p_request is null or p_task is null or p_lease is null then return jsonb_build_object('error','invalid_envelope'); end if;
 select * into p from crowd_v4.participants where user_id=u for update;
 if p.user_id is null then raise exception 'approval_required' using errcode='42501'; end if;
 payload:=jsonb_build_object('task',p_task,'record',p_record);
 select * into old from crowd_v4.receipts where user_id=u and request=p_request;
 -- Replays return the EXACT receipt, even after task completion/expiry/suspension.
 if old.request is not null then
  if old.payload is distinct from payload then return jsonb_build_object('error','request_reused'); end if;
  return old.result;
 end if;
 if p.status<>'approved' or p.consent<>'crowd-public-v4' then raise exception 'approval_required' using errcode='42501'; end if;
 select * into t from crowd_v4.tasks where id=p_task for update;
 if t.id is null or t.claimed_by is distinct from u or t.lease_token is distinct from p_lease or t.status<>'leased' then return jsonb_build_object('error','lease_lost'); end if;
 if t.lease_until<now() then return jsonb_build_object('error','lease_expired'); end if;
 if t.received>=t.target then return jsonb_build_object('error','task_full'); end if;
 result:=crowd_observation.validate_note(p_record,p_task); if result ? 'error' then return result; end if; s:=p_record->'standard'; e:=p_record->'evidence';
 if jsonb_typeof(p_record) is distinct from 'object' or p_record->>'schema_version' is distinct from '4'
 or jsonb_typeof(s) is distinct from 'object' or jsonb_typeof(e) is distinct from 'object' or jsonb_typeof(p_record->'extra') is distinct from 'object'
 or octet_length(p_record::text)>180000 or s->>'platform' is distinct from 'xiaohongshu'
 or coalesce(s->>'note_id','') !~ '^[a-f0-9]{24}$' or s->>'url' is distinct from ('https://www.xiaohongshu.com/explore/'||(s->>'note_id'))
 or jsonb_typeof(s->'title') is distinct from 'string' or length(s->>'title')>300
 or jsonb_typeof(e->'text') is distinct from 'string' or length(e->>'text')>24000
 or e->>'source' is distinct from 'rendered_public_dom' then return jsonb_build_object('error','invalid_record'); end if;
 if not (s ?& array['platform','note_id','url','title','captured_at','published_at','author_display','like_count','collect_count','comment_count'])
 or jsonb_typeof(s->'author_display') not in ('string','null') or length(s->>'author_display')>100
 or jsonb_typeof(s->'published_at') not in ('string','null')
 or (s->>'published_at' is not null and s->>'published_at' !~ '^20[0-9]{2}-[0-9]{2}-[0-9]{2}$')
 or e->>'parser_version' is null or e->>'parser_version' !~ '^4\.[0-9]+\.[0-9]+$'
 or jsonb_typeof(e->'original_length') is distinct from 'number' or coalesce(e->>'original_length','') !~ '^[0-9]{1,8}$'
 or jsonb_typeof(e->'truncated') is distinct from 'boolean'
 or jsonb_typeof(p_record->'extra'->'author_opinion_quotes') is distinct from 'array'
 then return jsonb_build_object('error','invalid_record'); end if;
 if (e->>'original_length')::int<length(e->>'text') or jsonb_array_length(p_record->'extra'->'author_opinion_quotes')>30
 or exists(select 1 from jsonb_array_elements(p_record->'extra'->'author_opinion_quotes') q where jsonb_typeof(q)<>'string' or strpos(e->>'text',q#>>'{}')=0)
 or exists(select 1 from jsonb_each(s) a(key,value) where key in ('like_count','collect_count','comment_count','view_count') and
   (jsonb_typeof(value) not in ('null','number') or (value<>'null'::jsonb and value::text !~ '^[0-9]{1,10}$')))
 then return jsonb_build_object('error','invalid_record'); end if;
 if exists(select 1 from jsonb_each(s) a(key,value) where key in ('like_count','collect_count','comment_count','view_count') and value<>'null'::jsonb and value::text::numeric>2147483647)
 then return jsonb_build_object('error','invalid_record'); end if;
 begin perform (s->>'published_at')::date; exception when others then return jsonb_build_object('error','invalid_published_date'); end;
 begin capture:=(s->>'captured_at')::timestamptz; exception when others then return jsonb_build_object('error','invalid_timestamp'); end;
 if capture is null or capture>now()+interval '5 minutes' or capture<now()-interval '24 hours' then return jsonb_build_object('error','invalid_timestamp'); end if;
 if not exists(select 1 from jsonb_array_elements_text(t.anchor_terms) a(term) where length(term)>=2 and
 strpos(lower(regexp_replace((s->>'title')||' '||(e->>'text'),'[[:space:][:punct:]]','','g')),lower(regexp_replace(term,'[[:space:][:punct:]]','','g')))>0)
 then return jsonb_build_object('error','unrelated_note'); end if;
 select count(*) into n from crowd_v4.proofs where user_id=u and received_at>=date_trunc('day',now() at time zone 'Asia/Shanghai') at time zone 'Asia/Shanghai';
 if n>=p.quota_day and coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)<>1 then return jsonb_build_object('error','daily_quota',
 'reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
 'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint); end if;
 insert into crowd_v4.proofs(note_id,user_id,task_id,record) values(s->>'note_id',u,p_task,p_record) on conflict(note_id) do nothing returning id into inserted_id;
 if inserted_id is not null then update crowd_v4.tasks set received=received+1 where id=p_task returning * into t; end if;
 result:=jsonb_build_object('inserted',inserted_id is not null,'duplicate',inserted_id is null,'task_received',t.received,'request',p_request,'gate','received');
 insert into crowd_v4.receipts(user_id,request,payload,result) values(u,p_request,payload,result);
 return result;
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
 if exists(select from crowd_v4.acceptance_supplements g where g.user_id=u and coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)=1 and (g.installation_id<>p_installation or p_task is not null and g.task_id<>p_task)) then raise exception 'node_binding_denied'; end if;
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
end $function$
;
commit;
