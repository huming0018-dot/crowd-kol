-- Candidate only. Fresh actual preimage required before root sole migration.
do $g76$
declare before record; after record; original text; changed text;
begin
 select oid,md5(pg_get_functiondef(oid)) md5,proacl,proconfig,proowner,prosecdef,provolatile into strict before
 from pg_proc where oid='public.crowd_machine_rpc(text,text,text,text,jsonb)'::regprocedure;
 if before.md5 is distinct from '4d0fb9fa094c918c5b24a2a0a7311618'
 or before.proacl::text is distinct from '{postgres=X/postgres,service_role=X/postgres}'
 or before.proconfig is distinct from array['search_path=""'] or before.prosecdef is distinct from false
 or before.provolatile is distinct from 'v'::"char" or pg_get_userbyid(before.proowner) is distinct from 'postgres'
 then raise exception 'terminal_recovery_preimage_changed';end if;
 original:=pg_get_functiondef(before.oid);
 if (length(original)-length(replace(original,$old$if p_payload->'proof'->>'local_state' is distinct from 'interrupted_unknown'
        or p_payload->'proof'->'exit_code' is distinct from 'null'::jsonb
        or p_payload->'proof'->'api_attempts' is distinct from 'null'::jsonb$old$,'')))/length($old$if p_payload->'proof'->>'local_state' is distinct from 'interrupted_unknown'
        or p_payload->'proof'->'exit_code' is distinct from 'null'::jsonb
        or p_payload->'proof'->'api_attempts' is distinct from 'null'::jsonb$old$) <> 1 then raise exception 'terminal_recovery_anchor_changed';end if;
 changed:=replace(original,$old$if p_payload->'proof'->>'local_state' is distinct from 'interrupted_unknown'
        or p_payload->'proof'->'exit_code' is distinct from 'null'::jsonb
        or p_payload->'proof'->'api_attempts' is distinct from 'null'::jsonb$old$,$new$if not coalesce(((p_payload->'proof'->>'local_state' = 'interrupted_unknown'
           and p_payload->'proof'->'exit_code' = 'null'::jsonb)
        or (p_payload->'proof'->>'local_state' = 'failed'
           and case when jsonb_typeof(p_payload->'proof'->'exit_code') = 'number'
             and coalesce(p_payload->'proof'->>'exit_code','') ~ '^-?[0-9]{1,3}$'
             then (p_payload->'proof'->>'exit_code')::int between -128 and 255
               and (p_payload->'proof'->>'exit_code')::int <> 0
             else false end)),false)
        or p_payload->'proof'->'api_attempts' is distinct from 'null'::jsonb$new$);
 execute changed;
 select oid,md5(pg_get_functiondef(oid)) md5,proacl,proconfig,proowner,prosecdef,provolatile into strict after
 from pg_proc where oid='public.crowd_machine_rpc(text,text,text,text,jsonb)'::regprocedure;
 if after.oid is distinct from before.oid or after.md5 is distinct from md5(changed)
 or after.proacl is distinct from before.proacl or after.proconfig is distinct from before.proconfig
 or after.proowner is distinct from before.proowner or after.prosecdef is distinct from before.prosecdef
 or after.provolatile is distinct from before.provolatile then raise exception 'terminal_recovery_postcondition_changed';end if;
end $g76$;
