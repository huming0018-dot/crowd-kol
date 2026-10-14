begin;
-- OTA status belongs to the top-level snapshot, never to a navigation trace event.
-- The earlier health migration used a global string replacement; repair only the
-- event allowlist, retaining the OTA snapshot validation and all other behavior.
do $migration$
declare
 definition text;
 anchor text := $old$if exists(select 1 from jsonb_object_keys(event) k where k<>all(array['ota_last_poll_at','ota_poll_status','ota_poll_error','ota_poll_query_error','id','stage','at']))$old$;
 replacement text := $new$if exists(select 1 from jsonb_object_keys(event) k where k<>all(array['id','stage','at']))$new$;
begin
 definition := pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure);
 if (length(definition)-length(replace(definition,anchor,'')))/length(anchor) <> 1 then
  raise exception 'diagnostics_trace_contract_changed';
 end if;
 execute replace(definition,anchor,replacement);
end $migration$;
commit;
