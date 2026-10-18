-- Optional safe client control observation only; no source/receipt/permissions/table changes.
begin;
do $patch$
declare original text;
begin
 original:=pg_get_functiondef('public.crowd_v4_step_events(uuid,jsonb)'::regprocedure);
 if md5(original) is distinct from 'be8d1842551e8243ff627f558045d81a' then raise exception 'control_diagnostic_definition_drift'; end if;
 if (length(original)-length(replace(original,$n0$array['event_id','node_seq','run_id','step','status','at_ms','duration_ms','error_code','counts']$n0$,'')))/length($n0$array['event_id','node_seq','run_id','step','status','at_ms','duration_ms','error_code','counts']$n0$)<>1 then raise exception 'control_diagnostic_anchor_mismatch'; end if;
 original:=replace(original,$n0$array['event_id','node_seq','run_id','step','status','at_ms','duration_ms','error_code','counts']$n0$,$r0$array['event_id','node_seq','run_id','step','status','at_ms','duration_ms','error_code','counts','control_diagnostic']$r0$);
 if (length(original)-length(replace(original,$n1$  eid:=(e->>'event_id')::uuid; seq:=(e->>'node_seq')::bigint; rid:=(e->>'run_id')::uuid;
$n1$,'')))/length($n1$  eid:=(e->>'event_id')::uuid; seq:=(e->>'node_seq')::bigint; rid:=(e->>'run_id')::uuid;
$n1$)<>1 then raise exception 'control_diagnostic_anchor_mismatch'; end if;
 original:=replace(original,$n1$  eid:=(e->>'event_id')::uuid; seq:=(e->>'node_seq')::bigint; rid:=(e->>'run_id')::uuid;
$n1$,$r1$  if e ? 'control_diagnostic' then
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
$r1$);
 execute original;
end $patch$;
commit;
