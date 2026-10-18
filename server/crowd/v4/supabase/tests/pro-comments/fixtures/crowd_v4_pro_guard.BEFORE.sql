CREATE OR REPLACE FUNCTION public.crowd_v4_pro_guard(p_task bigint, p_lease uuid, p_action text, p_note text, p_installation_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare t crowd_v4.tasks;r jsonb;
begin
 if p_lease is null then raise exception 'lease_lost';end if;
 if p_action is null or p_action not in ('control','search','detail','captcha','rate_limit') or p_action='detail' and (p_note is null or p_note!~'^[a-f0-9]{24}$') then raise exception 'invalid_action';end if;
 t:=crowd_observation.pro_scope(p_task,p_installation_id,p_lease,p_action in ('search','detail'));
 if t.source_executor<>'mediacrawler_pro' then raise exception 'pro_not_selected';end if;
 if p_action in ('search','detail') and t.received>=t.target then return jsonb_build_object('error','task_full');end if;
 r:=crowd_observation.pro_guard_base(p_action,p_task,p_note);
 return r||jsonb_build_object('source_executor','mediacrawler_pro','reward_eligible',false);
end $function$
