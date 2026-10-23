-- Reuse the explicit task detail ceiling for valid Pro batches; no counter reset/global change.
begin;
do $patch$
declare original text;changed text;
begin
 original:=pg_get_functiondef('crowd_observation.guard_internal(text,bigint,text)'::regprocedure);
 if md5(original)<>'5a8cbeeca0f70419b01e233a7fc5cbbc' then raise exception 'pro_batch_guard_drift';end if;
 changed:=replace(original,$old$ if p_action in ('captcha','rate_limit') then$old$,$new$ if p_action in ('control','search','detail') and exists(
  select from crowd_v4.participant_pro_batches b join crowd_v4.tasks task on task.id=b.task_id
  where b.task_id=p_task and b.user_id=u and task.claimed_by=u and task.status='leased' and task.lease_until>t
   and b.installation_id=(crowd_v4.acceptance_supplement_view(p_task,u)->>'installation_id')::uuid
   and crowd_v4.acceptance_supplement_view(p_task,u)->>'id'=b.id::text
   and coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)>0) then
  caps:=jsonb_set(caps,'{detail}',to_jsonb(least(200,coalesce((select task.daily_detail_cap from crowd_v4.tasks task where task.id=p_task),c.detail_cap))));
 end if;
 if p_action in ('captcha','rate_limit') then$new$);
 if changed=original then raise exception 'pro_batch_guard_patch_missing';end if;execute changed;
end $patch$;
commit;

