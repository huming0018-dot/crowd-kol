-- Candidate only: existing scoped control metadata may refresh an expired cached lease.
-- All source actions retain original live-lease admission. No businessDML/constraint change.
begin;
set local lock_timeout='3s';
do $patch$
declare source text;
begin
 select pg_get_functiondef('crowd_observation.guard_internal(text,bigint,text)'::regprocedure) into source;
 if md5(source)<>'c38184ca1133547a565ee47c73093100' then raise exception 'task19_expired_control_definition_changed'; end if;
 if length(source)-length(replace(source,$old$and exists(select from crowd_v4.tasks task where task.id=p_task and task.claimed_by=u and task.status='leased' and task.lease_until>t) then$old$,''))<>length($old$and exists(select from crowd_v4.tasks task where task.id=p_task and task.claimed_by=u and task.status='leased' and task.lease_until>t) then$old$) then raise exception 'task19_expired_control_anchor_changed'; end if;
 source:=replace(source,$old$and exists(select from crowd_v4.tasks task where task.id=p_task and task.claimed_by=u and task.status='leased' and task.lease_until>t) then$old$,$new$and exists(select from crowd_v4.tasks task where task.id=p_task and task.claimed_by=u and task.status='leased' and (p_action='control' or task.lease_until>t)) then$new$);
 if md5(source)<>'ec3e43377553043e27c3bcacdfb55774' then raise exception 'task19_expired_control_reconstruction_changed'; end if;
 execute source;
end $patch$;
commit;
