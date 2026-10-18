begin;
-- Participant 4.2.62 sends JSON null when no tab-pool fault is present.
-- Keep the existing exact enum for non-null faults and every other validation.
do $migration$
declare
 definition text;
 anchor text := $old$if p_state ? 'pool_failure' and (jsonb_typeof(p_state->'pool_failure') is distinct from 'string'$old$;
 replacement text := $new$if p_state ? 'pool_failure' and jsonb_typeof(p_state->'pool_failure') <> 'null' and (jsonb_typeof(p_state->'pool_failure') is distinct from 'string'$new$;
begin
 definition := pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure);
 if (length(definition)-length(replace(definition,anchor,'')))/length(anchor) <> 1 then
  raise exception 'diagnostics_pool_contract_changed';
 end if;
 execute replace(definition,anchor,replacement);
end $migration$;
commit;
