-- Candidate only. Schema/capability capacity, no task configuration or counter writes.
begin;
set local lock_timeout='3s';
do $patch$
declare source text;
begin
 select pg_get_functiondef('crowd_observation.guard_internal(text,bigint,text)'::regprocedure) into source;
 if md5(source)<>'80c4d56740a706be396c137a50748460' then raise exception 'task19_guard_definition_changed'; end if;
 if (select pg_get_constraintdef(oid) from pg_constraint where conrelid='crowd_v4.tasks'::regclass and conname='tasks_daily_detail_cap_check') is distinct from 'CHECK (((daily_detail_cap >= 1) AND (daily_detail_cap <= 60)))' then raise exception 'task19_detail_constraint_changed'; end if;
 source:=replace(source,$old$admitted boolean:=false; owner uuid; result jsonb;$old$,$new$admitted boolean:=false; owner uuid; result jsonb; batch_caps jsonb;$new$);
 source:=replace(source,$old$ if p_action in ('captcha','rate_limit') then$old$,$new$ -- Only the already-authorized original local batch may use its configured bounded detail ceiling.
 if p_task=19 then
  batch_caps:=crowd_v4.acceptance_supplement_view(p_task,u);
  if batch_caps->>'schema'='crowd-acceptance-batch-v1' and (batch_caps->>'remaining')::integer>0
   and exists(select from crowd_v4.tasks task where task.id=p_task and task.claimed_by=u and task.status='leased' and task.lease_until>t) then
   caps:=jsonb_set(caps,'{detail}',to_jsonb(least(200,coalesce((select task.daily_detail_cap from crowd_v4.tasks task where task.id=p_task),c.detail_cap))));
  end if;
 end if;
 if p_action in ('captcha','rate_limit') then$new$);
 if md5(source)<>'c38184ca1133547a565ee47c73093100' then raise exception 'task19_guard_reconstruction_changed'; end if;
 execute source;
end $patch$;
alter table crowd_v4.tasks drop constraint tasks_daily_detail_cap_check;
alter table crowd_v4.tasks add constraint tasks_daily_detail_cap_check check(daily_detail_cap between 1 and 200);
commit;
