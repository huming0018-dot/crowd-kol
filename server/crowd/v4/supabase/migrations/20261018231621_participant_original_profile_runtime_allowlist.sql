-- Admit the independently reviewed original-profile migration runtime as well as G07.
-- No node, task, authorization or participant business data changes.
begin;
do $cas$ begin
 if md5(pg_get_functiondef('crowd_observation.pro_node_capable(uuid,uuid,integer)'::regprocedure)) <> '2b5e1f7cd7265cf68c66b54d290508e0' then raise exception 'g10_capability_function_drift'; end if;
 if (select proacl::text from pg_proc where oid='crowd_observation.pro_node_capable(uuid,uuid,integer)'::regprocedure) is distinct from '{postgres=X/postgres}' then raise exception 'g10_capability_acl_drift'; end if;
end $cas$;
CREATE OR REPLACE FUNCTION crowd_observation.pro_node_capable(p_user uuid, p_install uuid, p_quota integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
 select exists(select from crowd_v4.nodes n where n.user_id=p_user and n.installation_id=p_install and n.enabled and n.login_state in('ready','unknown')
 and n.release_digest~'^[a-f0-9]{64}$' and n.pro_capability_at>now()-interval '120 seconds' and n.pro_capability_at<=now()
 and crowd_observation.pro_capability_valid(n.pro_capabilities)
 and n.pro_capabilities->>'runtime_sha256' in ('a72d375f60a19e0c3ef131751a7dea584830a0a624afe81eaf768603d804d2b2','9b37329a0dc973a3909d010f02b808988e01f8a4efd1c1eb855fad12d03dd843') and n.pro_capabilities->>'worker_sha256'='60ef9cb86e8d6f76b260f6faf75a054338fd3d49663f7e228ffe565f14b259fe' and n.pro_capabilities->>'entry_sha256'='62d16fa096a23b79d6c62d6b757c7a4b909f62d6a947592d12ad418113afd12f'
 and n.pro_capabilities->>'upstream_commit'='d32dd565277116ba4880c28ccd417a7c376cb62d'
 and (n.pro_capabilities->>'max_api_requests')::integer>=p_quota and p_quota>0)
$function$;
commit;
