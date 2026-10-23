begin;
do $patch$
declare before_def text; after_def text;
 old_anchor text := $anchor$or (p_state->>'error' is not null and p_state->>'error' not in ('page_timeout'$anchor$;
 new_anchor text := $anchor$or (p_state->>'error' is not null and p_state->>'error' not in ('identity_verification_required','platform_identity_changed','page_timeout'$anchor$;
begin
 select pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure) into before_def;
 if before_def is null or (length(before_def)-length(replace(before_def,old_anchor,'')))/length(old_anchor) <> 1
 or before_def like '%' || new_anchor || '%' then
  raise exception 'diagnostics_identity_contract_changed';
 end if;
 after_def := replace(before_def,old_anchor,new_anchor);
 execute after_def;
end
$patch$;
commit;
