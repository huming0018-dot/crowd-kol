-- Candidate: only existing guard definition, no business DML or constraint change.
begin;
set local lock_timeout='3s';
do $patch$
declare source text;
begin
 select pg_get_functiondef('crowd_observation.guard_internal(text,bigint,text)'::regprocedure) into source;
 if md5(source)<>'ec3e43377553043e27c3bcacdfb55774' then raise exception 'task19_scroll_guard_preimage_changed'; end if;
 if length(source)-length(replace(source,$old$   caps:=jsonb_set(caps,'{detail}',to_jsonb(least(200,coalesce((select task.daily_detail_cap from crowd_v4.tasks task where task.id=p_task),c.detail_cap))));$old$,''))<>length($old$   caps:=jsonb_set(caps,'{detail}',to_jsonb(least(200,coalesce((select task.daily_detail_cap from crowd_v4.tasks task where task.id=p_task),c.detail_cap))));$old$) then raise exception 'task19_scroll_anchor_changed'; end if;
 source:=replace(source,$old$   caps:=jsonb_set(caps,'{detail}',to_jsonb(least(200,coalesce((select task.daily_detail_cap from crowd_v4.tasks task where task.id=p_task),c.detail_cap))));$old$,$new$   caps:=jsonb_set(caps,'{detail}',to_jsonb(least(200,coalesce((select task.daily_detail_cap from crowd_v4.tasks task where task.id=p_task),c.detail_cap))));
   if batch_caps->>'installation_id'='3cde2858-39a5-42e1-b7ab-dd62053d2dac' then
    caps:=jsonb_set(caps,'{scroll}',to_jsonb(least(200,coalesce((select task.daily_detail_cap from crowd_v4.tasks task where task.id=p_task),c.detail_cap))));
   end if;$new$);
 if md5(source)<>'5a8cbeeca0f70419b01e233a7fc5cbbc' then raise exception 'task19_scroll_reconstruction_changed'; end if;
 execute source;
end $patch$;
commit;
