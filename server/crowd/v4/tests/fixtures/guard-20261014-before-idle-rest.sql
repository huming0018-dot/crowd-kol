CREATE OR REPLACE FUNCTION crowd_observation.guard_internal(p_action text DEFAULT 'control'::text, p_task bigint DEFAULT NULL::bigint, p_note text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
 u uuid:=auth.uid(); p crowd_v4.participants; c crowd_v4.policy; s crowd_v4.safety;
 t timestamptz:=clock_timestamp(); d date; caps jsonb; factor numeric; reason text; wait_until timestamptz;
 gap_seconds integer; configured_gap_ms integer; action_key text; admitted boolean:=false; owner uuid; result jsonb;
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
    s.session_count:=0; s.session_started:=t+interval '30 minutes';
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

