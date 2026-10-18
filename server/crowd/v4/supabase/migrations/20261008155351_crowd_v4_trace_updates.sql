begin;
-- Latest report only, at most 24 fixed events. No new grants or free text.
alter table crowd_v4.diagnostics drop constraint diagnostics_state_check;
alter table crowd_v4.diagnostics add constraint diagnostics_state_check check(state is null or (jsonb_typeof(state)='object' and octet_length(state::text)<=8192));
do $migration$
declare def text; validation text := $s$
 if p_state ? 'update_state' and (jsonb_typeof(p_state->'update_state') is distinct from 'string' or p_state->>'update_state' not in ('unknown','ready','applied','current','checking','pending_reload','helper_unavailable','error','rolled_back')) then raise exception 'invalid_diagnostics'; end if;
 if p_state ? 'trace' then
  if jsonb_typeof(p_state->'trace') is distinct from 'array' then raise exception 'invalid_diagnostics'; end if;
  if jsonb_array_length(p_state->'trace')>24 then raise exception 'invalid_diagnostics'; end if;
  for event in select value from jsonb_array_elements(p_state->'trace') loop
   if jsonb_typeof(event) is distinct from 'object' or not(event ?& array['id','stage','at']) then raise exception 'invalid_diagnostics'; end if;
   if exists(select 1 from jsonb_object_keys(event) k where k<>all(array['id','stage','at']))
   or jsonb_typeof(event->'id') is distinct from 'string' or coalesce(event->>'id','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   or jsonb_typeof(event->'stage') is distinct from 'string' or event->>'stage' not in ('worker_started','admission_requested','admission_allowed','admission_denied','open_requested','tab_created','tab_reused','update_accepted','update_failed','nav_started','nav_committed','nav_dom_ready','nav_complete','nav_failed','probe_ready','probe_missing','probe_timeout','navigation_timeout','submit_requested','submit_accepted','submit_rejected','submit_failed')
   or jsonb_typeof(event->'at') is distinct from 'number' or coalesce(event->>'at','') !~ '^[0-9]{1,10}$' then raise exception 'invalid_diagnostics'; end if;
   if (event->>'at')::bigint>4102444800 then raise exception 'invalid_diagnostics'; end if;
  end loop;
 end if;
$s$;
begin
 def:=pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure);
 if position('field text;' in def)=0 or position($s$'document_kind','pending_kind'$s$ in def)=0 or position('>2048' in def)=0 or position(' update crowd_v4.diagnostics set state=p_state' in def)=0 then raise exception 'trace_updates_anchor_mismatch'; end if;
 def:=replace(def,'field text;','field text; event jsonb;');
 def:=replace(def,'>2048','>8192');
 def:=replace(def,$s$'document_kind','pending_kind'$s$,$s$'document_kind','pending_kind','trace','update_state'$s$);
 def:=replace(def,' update crowd_v4.diagnostics set state=p_state',validation || ' update crowd_v4.diagnostics set state=p_state');
 execute def;
end $migration$;
commit;
