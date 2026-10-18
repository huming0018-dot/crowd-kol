begin;
-- Extend the opt-in, latest-only snapshot with one previous navigation attempt.
-- No URL/body/header/cookie, no event archive or additional access grants.
do $migration$
declare def text; anchor text := $s$'nav_stage','nav_error','nav_age_s','probe_status'$s$;
 validation text := $s$
 if p_state ? 'prev_nav_stage' and (jsonb_typeof(p_state->'prev_nav_stage') is distinct from 'string' or p_state->>'prev_nav_stage' not in ('unknown','started','committed','dom_ready','complete','failed')) then raise exception 'invalid_diagnostics'; end if;
 if p_state ? 'prev_nav_error' and (jsonb_typeof(p_state->'prev_nav_error') not in ('string','null') or (p_state->>'prev_nav_error' is not null and p_state->>'prev_nav_error' not in ('ERR_NAME_NOT_RESOLVED','ERR_INTERNET_DISCONNECTED','ERR_CONNECTION_TIMED_OUT','ERR_TIMED_OUT','ERR_CONNECTION_RESET','ERR_CONNECTION_REFUSED','ERR_CONNECTION_CLOSED','ERR_ADDRESS_UNREACHABLE','ERR_NETWORK_CHANGED','ERR_TUNNEL_CONNECTION_FAILED','ERR_PROXY_CONNECTION_FAILED','ERR_CERT_AUTHORITY_INVALID','ERR_CERT_DATE_INVALID','ERR_SSL_PROTOCOL_ERROR','ERR_BLOCKED_BY_CLIENT','ERR_BLOCKED_BY_ADMINISTRATOR','ERR_ABORTED','OTHER'))) then raise exception 'invalid_diagnostics'; end if;
 foreach field in array array['prev_nav_age_s','last_tick_age_s','next_in_s','page_failures'] loop
  if p_state ? field and jsonb_typeof(p_state->field) <> 'null' then
   if jsonb_typeof(p_state->field) is distinct from 'number' or coalesce(p_state->>field,'') !~ '^[0-9]{1,5}$' then raise exception 'invalid_diagnostics'; end if;
   if (p_state->>field)::int > (case when field='page_failures' then 3 else 86400 end) then raise exception 'invalid_diagnostics'; end if;
  end if;
  if field in ('next_in_s','page_failures') and p_state ? field and jsonb_typeof(p_state->field) = 'null' then raise exception 'invalid_diagnostics'; end if;
 end loop;
$s$;
begin
 def:=pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure);
 if position(anchor in def)=0 or position(' update crowd_v4.diagnostics set state=p_state' in def)=0 then raise exception 'navigation_recovery_anchor_missing'; end if;
 def:=replace(def,anchor,anchor || $s$,'prev_nav_stage','prev_nav_error','prev_nav_age_s','page_failures','last_tick_age_s','next_in_s'$s$);
 def:=replace(def,' update crowd_v4.diagnostics set state=p_state',validation || ' update crowd_v4.diagnostics set state=p_state');
 execute def;
end $migration$;
commit;
