CREATE OR REPLACE FUNCTION public.crowd_v4_pro_finish(p_task bigint, p_lease uuid, p_installation_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare t crowd_v4.tasks;
begin
 t:=crowd_observation.pro_scope(p_task,p_installation_id,p_lease);
 if t.source_executor<>'mediacrawler_pro' then raise exception 'pro_not_selected';end if;
 return public.crowd_v4_finish(p_task,p_lease)||jsonb_build_object('source_executor','mediacrawler_pro','reward_eligible',false);
end $function$
