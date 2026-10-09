begin;
-- Optional fixed error categories. Keep existing status values and opt-in rules.
do $migration$
declare def text; fields text := $s$'document_kind','pending_kind'$s$;
 validation text := $s$
 if p_state ? 'probe_error' and (jsonb_typeof(p_state->'probe_error') is distinct from 'string' or p_state->>'probe_error' not in ('unknown','none','no_receiver','empty_response','port_closed','tab_missing','access_denied','timed_out','message_failed')) then raise exception 'invalid_diagnostics'; end if;
$s$;
begin
 def := pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure);
 if position(fields in def)=0 or position(' update crowd_v4.diagnostics set state=p_state' in def)=0 or position('probe_error' in def)>0 then raise exception 'probe_error_anchor_mismatch'; end if;
 def := replace(def, fields, fields || $s$,'probe_error'$s$);
 def := replace(def, ' update crowd_v4.diagnostics set state=p_state', validation || ' update crowd_v4.diagnostics set state=p_state');
 execute def;
end $migration$;
commit;
