-- Candidate: only validated local batch with actual progress may reclaim before existing availability.
begin;
do $patch$
declare original text;
begin
 original:=pg_get_functiondef('public.crowd_v4_claim(bigint)'::regprocedure);
 if md5(original) is distinct from 'cf58ae697d5603a25dcfda2c5b200186' then raise exception 'batch20_reclaim_definition_drift'; end if;
 if (length(original)-length(replace(original,$old$available_at<=now()$old$,'')))/length($old$available_at<=now()$old$)<>1 then raise exception 'batch20_reclaim_anchor_drift'; end if;
 original:=replace(original,$old$available_at<=now()$old$,$new$(available_at<=now() or (crowd_v4.acceptance_supplement_view(crowd_v4.tasks.id,u)->>'schema'='crowd-acceptance-batch-v1' and coalesce((crowd_v4.acceptance_supplement_view(crowd_v4.tasks.id,u)->>'remaining')::int,0)>0 and crowd_v4.tasks.received>crowd_v4.tasks.lease_start_received))$new$);
 if md5(pg_get_functiondef('crowd_v4.acceptance_supplement_view(bigint,uuid)'::regprocedure)) is distinct from '4f39a1792466cca5fb142d045ad8c9f9' then raise exception 'batch20_reclaim_view_drift'; end if;
 execute original;
 original:=pg_get_functiondef('crowd_v4.acceptance_supplement_view(bigint,uuid)'::regprocedure);
 if (length(original)-length(replace(original,$vold$array['action_gap_milliseconds','session_action_limit','session_window_seconds','daily_search_cap','daily_detail_cap']$vold$,'')))/length($vold$array['action_gap_milliseconds','session_action_limit','session_window_seconds','daily_search_cap','daily_detail_cap']$vold$)<>2 then raise exception 'batch20_reclaim_view_anchor_drift'; end if;
 original:=replace(original,$vold$array['action_gap_milliseconds','session_action_limit','session_window_seconds','daily_search_cap','daily_detail_cap']$vold$,$vnew$array['empty_passes','action_gap_milliseconds','session_action_limit','session_window_seconds','daily_search_cap','daily_detail_cap']$vnew$);
 execute original;
end $patch$;
commit;
