begin;
-- Optional fixed enums on the existing opt-in latest-only diagnostic snapshot.
-- No URLs, cookies, content, new tables or new grants.
do $migration$
declare def text;
 fields text := $s$'page_failures','last_tick_age_s','next_in_s'$s$;
 errors text := $s$'page_timeout','page_loading'$s$;
 validation text := $s$
 if p_state ? 'document_kind' and (jsonb_typeof(p_state->'document_kind') is distinct from 'string' or p_state->>'document_kind' not in ('blank','platform','other','unavailable')) then raise exception 'invalid_diagnostics'; end if;
 if p_state ? 'pending_kind' and (jsonb_typeof(p_state->'pending_kind') is distinct from 'string' or p_state->>'pending_kind' not in ('none','blank','platform','other','unavailable')) then raise exception 'invalid_diagnostics'; end if;
$s$;
begin
 def := pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure);
 if position(fields in def)=0 or position(errors in def)=0 or position(' update crowd_v4.diagnostics set state=p_state' in def)=0 or position('document_kind' in def)>0 then raise exception 'navigation_commit_anchor_mismatch'; end if;
 def := replace(def, fields, fields || $s$,'document_kind','pending_kind'$s$);
 def := replace(def, errors, errors || $s$,'navigation_failed','navigation_uncommitted'$s$);
 def := replace(def, ' update crowd_v4.diagnostics set state=p_state', validation || ' update crowd_v4.diagnostics set state=p_state');
 execute def;
end $migration$;
commit;
