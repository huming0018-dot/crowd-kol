begin;
create table crowd_v4.pilot_experiments (
 invite_hash text primary key references crowd_v4.invites(token_hash),
 phase text not null default 'awaiting_acceptance' check(phase in ('awaiting_acceptance','active','closed')),
 armed_at timestamptz, ends_at timestamptz,
 created_at timestamptz not null default now(),
 check((phase='active' and armed_at is not null and ends_at=armed_at+interval '48 hours') or phase<>'active')
);
create table crowd_v4.pilot_task_map (
 task_id bigint primary key references crowd_v4.tasks(id),
 invite_hash text not null references crowd_v4.pilot_experiments(invite_hash)
);
alter table crowd_v4.pilot_experiments enable row level security;
alter table crowd_v4.pilot_task_map enable row level security;
revoke all on crowd_v4.pilot_experiments,crowd_v4.pilot_task_map from public,anon,authenticated;

create function crowd_v4.pilot_block_reason(task bigint,participant uuid) returns text
language plpgsql stable security definer set search_path='' as $$
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
 if exists(select from crowd_v4.tasks where id=task and (received>=target or status in ('complete','exhausted','closed'))) then return 'task_full'; end if;
 if experiment.phase='awaiting_acceptance' and (select count(*) from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where p.user_id=participant and m.invite_hash=cohort)>=2 then return 'test_completed'; end if;
 if (select count(*) from crowd_v4.proofs where user_id=participant and received_at>=date_trunc('day',now() at time zone 'Asia/Shanghai') at time zone 'Asia/Shanghai')>=2 then return 'daily_quota'; end if;
 return null;
end $$;
revoke all on function crowd_v4.pilot_block_reason(bigint,uuid) from public,anon,authenticated;

create function crowd_v4.pilot_remaining(task bigint,participant uuid) returns integer
language plpgsql stable security definer set search_path='' as $$
declare cohort text; phase text; received_count integer;
begin
 select m.invite_hash,x.phase into cohort,phase from crowd_v4.pilot_task_map m join crowd_v4.pilot_experiments x using(invite_hash) where m.task_id=task;
 if cohort is null then return null; end if;
 if phase='awaiting_acceptance' then
  select count(*) into received_count from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where p.user_id=participant and m.invite_hash=cohort;
 else
  select count(*) into received_count from crowd_v4.proofs where user_id=participant and received_at>=date_trunc('day',now() at time zone 'Asia/Shanghai') at time zone 'Asia/Shanghai';
 end if;
 return least(greatest(0,2-received_count),greatest(0,20-(select count(*) from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where m.invite_hash=cohort)::integer));
end $$;
revoke all on function crowd_v4.pilot_remaining(bigint,uuid) from public,anon,authenticated;

create function crowd_v4.pilot_phase(participant uuid) returns text
language sql stable security definer set search_path='' as $$
 select case when i.revoked or i.expires_at<=now() or i.max_people>5 or i.quota_day<>2
  or x.phase='closed' or x.phase='active' and (x.armed_at>now() or x.ends_at<=now()) then 'closed' else x.phase end
 from crowd_v4.enrollments e join crowd_v4.pilot_experiments x using(invite_hash)
 join crowd_v4.invites i on i.token_hash=x.invite_hash
 where e.user_id=participant and e.completed_at is not null;
$$;
revoke all on function crowd_v4.pilot_phase(uuid) from public,anon,authenticated;

-- Preserve all deployed claim/lease/reconciliation logic, extend exact query anchors only.
do $migration$
declare definition text; anchor text:='not exists(select 1 from crowd_v4.test_task_owners r where r.task_id=crowd_v4.tasks.id and r.user_id<>u)';
begin
 definition:=pg_get_functiondef('public.crowd_v4_claim(bigint)'::regprocedure);
 if (length(definition)-length(replace(definition,anchor,'')))/length(anchor)<>2
  or position($a$'remaining_today',p.quota_day-n$a$ in definition)=0
  or position('pilot_block_reason' in definition)>0 then raise exception 'pilot_claim_anchor_mismatch'; end if;
 definition:=replace(definition,anchor,anchor||' and crowd_v4.pilot_block_reason(crowd_v4.tasks.id,u) is null');
 definition:=replace(definition,$a$'remaining_today',p.quota_day-n$a$,$a$'remaining_today',least(p.quota_day-n,coalesce(crowd_v4.pilot_remaining(t.id,u),p.quota_day-n))$a$);
 execute definition;
end $migration$;

-- Cached leases still need admission every action; captcha/rate signals retain their original path.
do $migration$
declare definition text; anchor text:=' result:=crowd_observation.guard_internal(p_action,p_task,p_note);';
addition text:=$a$
 if auth.uid() is not null and p_action in ('control','search','detail','comment','scroll') and crowd_v4.pilot_block_reason(p_task,auth.uid()) is not null then
  result:=crowd_observation.guard_internal('control',p_task,p_note);
  if result ? 'error' then return result; end if;
  return result||jsonb_build_object('allowed',false,'reason',crowd_v4.pilot_block_reason(p_task,auth.uid()),'wait_ms',600000,'action_wait_ms',600000,'pilot_phase',crowd_v4.pilot_phase(auth.uid()))
   ||case when crowd_v4.pilot_block_reason(p_task,auth.uid())='daily_quota' then jsonb_build_object('reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
    'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint) else '{}'::jsonb end;
 end if;
$a$;
begin
 definition:=pg_get_functiondef('public.crowd_v4_guard(text,bigint,text)'::regprocedure);
 if position(anchor in definition)=0 or position('pilot_block_reason' in definition)>0 then raise exception 'pilot_guard_anchor_mismatch'; end if;
 definition:=replace(definition,anchor,addition||anchor);
 if position(' return result;' in definition)=0 then raise exception 'pilot_guard_result_anchor_mismatch'; end if;
 execute replace(definition,' return result;', ' if crowd_v4.pilot_phase(auth.uid()) is not null then result:=result||jsonb_build_object(''pilot_phase'',crowd_v4.pilot_phase(auth.uid())); end if; return result;');
end $migration$;

-- New capture budgets serialize with original participant lock; old receipts always replay unchanged.
do $migration$
declare definition text; anchor text:=' result:=crowd_observation.submit_internal(p_request,p_task,p_lease,p_record);';
addition text:=$a$
 perform 1 from crowd_v4.participants where user_id=auth.uid() for update;
 if auth.uid() is not null and not exists(select 1 from crowd_v4.receipts where user_id=auth.uid() and request=p_request)
  and crowd_v4.pilot_block_reason(p_task,auth.uid()) is not null then
  if crowd_v4.pilot_block_reason(p_task,auth.uid())='daily_quota' then
   return jsonb_build_object('error','daily_quota','reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
    'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint);
  end if;
  return jsonb_build_object('error',case when crowd_v4.pilot_block_reason(p_task,auth.uid())='user_stopped' then 'lease_lost' else 'task_full' end);
 end if;
$a$;
begin
 definition:=pg_get_functiondef('public.crowd_v4_submit(uuid,bigint,uuid,jsonb)'::regprocedure);
 if position(anchor in definition)=0 or position('pilot_block_reason' in definition)>0 then raise exception 'pilot_submit_anchor_mismatch'; end if;
 execute replace(definition,anchor,addition||anchor);
end $migration$;
commit;
