CREATE OR REPLACE FUNCTION public.crowd_v4_step_events(p_installation uuid, p_events jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare u uuid:=auth.uid(); n crowd_v4.nodes; e jsonb; old crowd_v4.node_step_events; k text; v jsonb;
 accepted jsonb:='[]'; duplicates jsonb:='[]'; discarded jsonb:='[]'; opted boolean; seq bigint; eid uuid; rid uuid;
begin
 if u is null then raise exception 'login_required'; end if;
 perform 1 from crowd_v4.participants where user_id=u and consent='crowd-public-v4' for update;
 if not found then raise exception 'consent_required'; end if;
 select * into n from crowd_v4.nodes where installation_id=p_installation and user_id=u for update;
 if not found then raise exception 'node_binding_denied'; end if;
 if jsonb_typeof(p_events) is distinct from 'array' or jsonb_array_length(p_events)>50 or octet_length(p_events::text)>100000 then raise exception 'invalid_events'; end if;
 select coalesce((select enabled from crowd_v4.diagnostics where user_id=u),false) into opted;
 if not opted then
  return jsonb_build_object('schema','crowd-step-events-v1','accepted','[]'::jsonb,'duplicates','[]'::jsonb,'diagnostics_enabled',false,'discard',true,'max_node_seq',n.max_node_seq);
 end if;
 -- Serializes only bounded telemetry writes/pruning, never source actions or receipt writes.
 perform pg_advisory_xact_lock(713249121);
 for e in select value from jsonb_array_elements(p_events) loop
  if jsonb_typeof(e) is distinct from 'object' or octet_length(e::text)>2048
   or (e-array['event_id','node_seq','run_id','step','status','at_ms','duration_ms','error_code','counts','control_diagnostic'])<>'{}'::jsonb
   or not(e ?& array['event_id','node_seq','run_id','step','status','at_ms','duration_ms','error_code'])
   or coalesce(e->>'event_id','') !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
   or (e->>'run_id' is not null and e->>'run_id' !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')
   or jsonb_typeof(e->'node_seq') is distinct from 'number' or coalesce(e->>'node_seq','') !~ '^[0-9]{1,16}$'
   or jsonb_typeof(e->'at_ms') is distinct from 'number' or coalesce(e->>'at_ms','') !~ '^[0-9]{1,13}$'
   or coalesce(e->>'step','') not in ('claim','session','navigation','list','detail','comments','media','subtitle','outbox','upload','receipt','stop','ota','telemetry_gap')
   or coalesce(e->>'status','') not in ('started','completed','waiting','failed','skipped')
   or (e->>'duration_ms' is not null and (jsonb_typeof(e->'duration_ms')<>'number' or e->>'duration_ms' !~ '^[0-9]{1,10}$'))
   or (e->>'error_code' is not null and crowd_v4.participant_health_error(e->>'error_code') is distinct from e->>'error_code' and not (e->>'step'='ota' and e->>'error_code'=any(array['ota_network_dns','ota_network_connect','ota_network_timeout','ota_network_tls','ota_network_http','ota_network_transfer','ota_io_permission','ota_io_missing','ota_io_space','ota_io_failed','ota_package_tool_failed','ota_service_failed','ota_process_terminated','ota_process_launch_failed','ota_unknown_exit','ota_signature_invalid','ota_hash_mismatch','ota_permission_change','ota_replayed_release','ota_recovery_required','ota_handshake_mismatch','ota_version_mismatch','ota_busy','ota_invalid_package','ota_invalid_url','ota_wrong_extension','ota_unknown','ota_io_failed'])))
  then raise exception 'invalid_events'; end if;
  if e ? 'control_diagnostic' then
   v:=e->'control_diagnostic';
   if e->>'step' not in ('session','stop') or jsonb_typeof(v) is distinct from 'object' or octet_length(v::text)>512 then raise exception 'invalid_events'; end if;
   if (v-array['schema','kind','http_status','elapsed_ms','at_ms','cause'])<>'{}'::jsonb
    or not(v ?& array['schema','kind','http_status','elapsed_ms','at_ms'])
    or coalesce(v->>'schema','')<>'crowd-control-diagnostic-v1'
    or coalesce(v->>'kind','') not in ('timeout','cancelled','network_unknown','http_4xx','http_5xx','invalid_json','backend_error','policy_schema_invalid','policy_version_regression','response_slow','clock_regression','local_gate_failure','ok','terminal_response')
    or (v ? 'cause' and (v->>'kind'<>'local_gate_failure' or coalesce(v->>'cause','') not in ('cancelled','task_reconciliation_required','admission_rejected','local_unknown')))
    then raise exception 'invalid_events'; end if;
   foreach k in array array['http_status','elapsed_ms','at_ms'] loop
    if v->>k is not null and (jsonb_typeof(v->k) is distinct from 'number' or v->>k !~ '^[0-9]{1,13}$') then raise exception 'invalid_events'; end if;
   end loop;
   if (v->>'http_status' is not null and ((v->>'http_status')::bigint<100 or (v->>'http_status')::bigint>599))
    or (v->>'elapsed_ms')::bigint>300000 or (v->>'at_ms')::bigint>4102444800000
    or (v->>'at_ms')::bigint>(e->>'at_ms')::bigint
    or (v->>'kind'='http_4xx' and coalesce(v->>'http_status','') !~ '^4[0-9]{2}$')
    or (v->>'kind'='http_5xx' and coalesce(v->>'http_status','') !~ '^5[0-9]{2}$')
    then raise exception 'invalid_events'; end if;
  end if;
  eid:=(e->>'event_id')::uuid; seq:=(e->>'node_seq')::bigint; rid:=(e->>'run_id')::uuid;
  if seq<1 or seq>9007199254740991 or (e->>'at_ms')::bigint>4102444800000 or (e->>'duration_ms')::bigint>2147483647 then raise exception 'invalid_events'; end if;
  if e ? 'counts' then
   if jsonb_typeof(e->'counts') is distinct from 'object' or ((e->'counts')-array['contents','comments','replies','media','queued','received','pages','source_actions'])<>'{}'::jsonb then raise exception 'invalid_events'; end if;
   for k,v in select * from jsonb_each(e->'counts') loop
    if jsonb_typeof(v)<>'number' or v::text !~ '^[0-9]{1,6}$' or (v::text)::integer>100000 then raise exception 'invalid_events'; end if;
   end loop;
  end if;
  if rid is not null and not exists(select 1 from crowd_v4.node_runs where run_id=rid and installation_id=p_installation and user_id=u) then raise exception 'node_binding_denied'; end if;
  if rid is null and e->>'step' not in ('claim','session','stop','ota','telemetry_gap') then raise exception 'node_binding_denied'; end if;
  select * into old from crowd_v4.node_step_events where installation_id=p_installation and (event_id=eid or node_seq=seq) limit 1;
  if found then
   if old.event is distinct from e then raise exception 'event_conflict'; end if;
   duplicates:=duplicates||jsonb_build_array(eid);
  elsif seq<=n.max_node_seq then
   -- The ordered client stream has already advanced and its exact event is no
   -- longer retained. Do not resurrect old logs or claim an unverifiable duplicate.
   discarded:=discarded||jsonb_build_array(eid);
  else
   insert into crowd_v4.node_step_events(installation_id,event_id,node_seq,run_id,event) values(p_installation,eid,seq,rid,e);
   accepted:=accepted||jsonb_build_array(eid);
  end if;
  n.max_node_seq:=greatest(n.max_node_seq,seq);
 end loop;
 update crowd_v4.nodes set updated_at=now(),max_node_seq=n.max_node_seq where installation_id=p_installation;
 delete from crowd_v4.node_step_events where received_at<now()-interval '7 days';
 delete from crowd_v4.node_step_events where id in (select id from crowd_v4.node_step_events where installation_id=p_installation order by id desc offset 2000);
 delete from crowd_v4.node_step_events where id in (select id from crowd_v4.node_step_events order by id desc offset 50000);
 return jsonb_build_object('schema','crowd-step-events-v1','accepted',accepted,'duplicates',duplicates,'discarded',discarded,
  'discard_reason',case when jsonb_array_length(discarded)>0 then 'sequence_not_retained' end,'diagnostics_enabled',true,'max_node_seq',n.max_node_seq);
end $function$
