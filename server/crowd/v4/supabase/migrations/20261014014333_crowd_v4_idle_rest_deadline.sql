begin;
-- Count time already spent idle toward the existing 30-minute rest. Keep all
-- daily caps, action-count limits, hard cooldowns and source admission checks.
do $$
declare
 def text;
 old_check text := $anchor$ if s.cooldown_until>t then reason:=s.cooldown_reason; wait_until:=s.cooldown_until;$anchor$;
 old_start text := $anchor$    s.session_count:=0; s.session_started:=t+interval '30 minutes';$anchor$;
 new_check text := $replacement$ -- Only a participant enrolled today has complete lifetime counts in this day.
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
 if s.cooldown_until>t then reason:=s.cooldown_reason; wait_until:=s.cooldown_until;$replacement$;
 new_start text := $replacement$    if s.session_count>=coalesce((select session_action_limit from crowd_v4.tasks where id=p_task and claimed_by=u and status='leased' and lease_until>t),20) then
     s.session_started:=t+interval '30 minutes';
    else
     s.session_started:=greatest(t,least(t,s.next_action)+interval '30 minutes');
    end if;
    s.session_count:=0;$replacement$;
begin
 select pg_get_functiondef('crowd_observation.guard_internal(text,bigint,text)'::regprocedure) into def;
 if length(def)-length(replace(def,old_check,''))<>length(old_check)
  or length(def)-length(replace(def,old_start,''))<>length(old_start) then
  raise exception 'idle_rest_contract_changed';
 end if;
 def:=replace(replace(def,old_check,new_check),old_start,new_start);
 execute def;
end $$;
commit;
