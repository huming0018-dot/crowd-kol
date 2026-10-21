-- Candidate only: append one reviewed own-runtime manifest; no business DML.
DO $cas$
DECLARE before_oid oid; before_acl aclitem[]; before_config text[]; before_security boolean; before_volatility char; definition text;
BEGIN
 SELECT oid,proacl,proconfig,prosecdef,provolatile INTO before_oid,before_acl,before_config,before_security,before_volatility FROM pg_proc WHERE oid='crowd_observation.pro_node_capable(uuid,uuid,integer)'::regprocedure;
 definition:=pg_get_functiondef(before_oid);
 IF md5(definition)<>'686cdadf3247cd1a070d4743cafd699d' THEN RAISE EXCEPTION 'runtime126_function_drift'; END IF;
 IF before_acl::text IS DISTINCT FROM '{postgres=X/postgres}' OR before_config IS DISTINCT FROM ARRAY['search_path=""']::text[] OR before_security IS DISTINCT FROM true OR before_volatility IS DISTINCT FROM 's' THEN RAISE EXCEPTION 'runtime126_attributes_drift'; END IF;
 IF length(definition)-length(replace(definition,'''5d292476332e18a322a04fadb378cc1b0edf1b7415b86f48e49f874de8195e2e'')',''))<>length('''5d292476332e18a322a04fadb378cc1b0edf1b7415b86f48e49f874de8195e2e'')') THEN RAISE EXCEPTION 'runtime126_literal_drift'; END IF;
 EXECUTE replace(definition,'''5d292476332e18a322a04fadb378cc1b0edf1b7415b86f48e49f874de8195e2e'')','''5d292476332e18a322a04fadb378cc1b0edf1b7415b86f48e49f874de8195e2e'',''597b61fe8b1a86d9514175f9ba6fa508f69cb6ee4442bda9855f45b7bf50f81c'')');
 IF pg_get_functiondef(before_oid)<>replace(definition,'''5d292476332e18a322a04fadb378cc1b0edf1b7415b86f48e49f874de8195e2e'')','''5d292476332e18a322a04fadb378cc1b0edf1b7415b86f48e49f874de8195e2e'',''597b61fe8b1a86d9514175f9ba6fa508f69cb6ee4442bda9855f45b7bf50f81c'')') OR NOT EXISTS(SELECT FROM pg_proc WHERE oid=before_oid AND proacl IS NOT DISTINCT FROM before_acl AND proconfig IS NOT DISTINCT FROM before_config AND prosecdef=before_security AND provolatile=before_volatility) THEN RAISE EXCEPTION 'runtime126_postcondition'; END IF;
END $cas$;
