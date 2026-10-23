CREATE OR REPLACE FUNCTION public.crowd_v4_finish(p_task bigint, p_lease uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare u uuid:=auth.uid(); t crowd_v4.tasks; empty_count int;
begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 perform 1 from crowd_v4.participants where user_id=u and status='approved' and consent='crowd-public-v4' for update;
 if not found then raise exception 'approval_required' using errcode='42501'; end if;
 select * into t from crowd_v4.tasks where id=p_task for update;
 if t.id is null or p_lease is null or t.claimed_by is distinct from u or t.lease_token is distinct from p_lease then
  return jsonb_build_object('error','lease_lost');
 end if;
 -- A lost finish response may be replayed, but only until a NEW lease rotates the token.
 if t.status='leased' then
  if t.lease_until is null or (t.lease_until<now() and ((
   t.target>0 and t.received>=t.target and t.comments_capture is false
   and t.structured_capture is false and cardinality(t.comment_repair_parents)=0
  ) is not true)) then return jsonb_build_object('error','lease_lost'); end if;
  empty_count:=case when t.received>t.lease_start_received then 0 else least(t.empty_passes+1,6) end;
  update crowd_v4.tasks set status=case when received>=target then 'complete' else 'open' end,
   empty_passes=empty_count,
   available_at=now()+make_interval(mins=>least(360,15*(2^greatest(0,empty_count-1))::int))
   where id=p_task returning * into t;
 end if;
 return jsonb_build_object('status',t.status,'received',t.received,'available_at',t.available_at);
end $function$
