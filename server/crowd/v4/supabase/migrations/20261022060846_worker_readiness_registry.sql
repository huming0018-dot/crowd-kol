-- Only queued new claims: an explicit Pro task requires an existing reviewed operation gate.
-- Existing MC/auto, same-claim replay, inflight runs, UNKNOWN and all delivery/accounting paths remain unchanged.
do $g126$
declare before record; after record; original text; changed text;
 anchor text:=$anchor$       and (not coalesce(c0.platform='dy' and c0.plan->'request'->>'source_executor'='pro' and c0.plan->'request'->>'mode'='trending',false) or coalesce(p_payload->'source_capabilities','[]'::jsonb) ? 'pro_dy_trending_v1')$anchor$;
 addition text:=$addition$       and (c0.plan->'request'->>'source_executor' is distinct from 'pro'
         or (c0.platform='dy' and c0.plan->'request'->>'mode'='trending')
         or (c0.platform='tieba' and c0.plan->'request'->>'mode'='detail')
         or crowd_machine.pro_readiness_matches(w.worker_id,nullif(p_payload->>'capability_report_id','')::uuid,c0.plan->'request'))
$addition$;
validation_anchor text:=$val$   if p_payload ? 'source_capabilities' and$val$;
 validation_added text:=$vadd$   if p_payload ? 'capability_report_id' and (jsonb_typeof(p_payload->'capability_report_id') is distinct from 'string' or coalesce(p_payload->>'capability_report_id','') !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$') then raise exception 'invalid_request'; end if;
$vadd$;
begin
 select oid,md5(pg_get_functiondef(oid)) md5,proacl,proconfig,proowner,prosecdef,provolatile into strict before
 from pg_proc where oid='public.crowd_machine_rpc(text,text,text,text,jsonb)'::regprocedure;
 if before.md5 is distinct from '10b5d3a23faa7bd0c3e5e510254b89f2'
 or before.proacl::text is distinct from '{postgres=X/postgres,service_role=X/postgres}'
 or before.proconfig is distinct from array['search_path=""'] or before.prosecdef is distinct from false
 or before.provolatile is distinct from 'v'::"char" or pg_get_userbyid(before.proowner) is distinct from 'postgres'
 then raise exception 'pro_gate_preimage_changed';end if;
 original:=pg_get_functiondef(before.oid);
 if (length(original)-length(replace(original,anchor,'')))/length(anchor)<>1 then raise exception 'pro_gate_anchor_changed';end if;
 if (length(original)-length(replace(original,validation_anchor,'')))/length(validation_anchor)<>1 then raise exception 'pro_gate_validation_anchor_changed';end if;
 execute $registry_ddl$create table crowd_machine.worker_capability_reports(
 worker_id uuid not null references crowd_machine.workers(worker_id),report_id uuid not null,
 sequence bigint not null check(sequence between 1 and 9007199254740991),report_hash text not null check(report_hash~'^[a-f0-9]{64}$'),
 report jsonb not null,receipt jsonb not null,received_at timestamptz not null,expires_at timestamptz not null,
 primary key(worker_id,report_id),unique(worker_id,sequence)
);
alter table crowd_machine.worker_capability_reports enable row level security;
revoke all on crowd_machine.worker_capability_reports from public,anon,authenticated,service_role;
grant select on crowd_machine.worker_capability_reports to service_role;
create function crowd_machine.worker_capability_immutable()returns trigger language plpgsql set search_path='' as $$begin raise exception 'capability_report_immutable';end$$;
create trigger worker_capability_immutable before update or delete on crowd_machine.worker_capability_reports for each row execute function crowd_machine.worker_capability_immutable();
create function crowd_machine.capability_int(v jsonb,minimum bigint default 0)returns boolean language sql immutable set search_path='' as $$select case when jsonb_typeof(v)='number'and v::text~'^(0|[1-9][0-9]*)$'then(v::text)::numeric between minimum and 9007199254740991 else false end$$;
create function crowd_machine.valid_worker_capability(v jsonb)returns boolean language plpgsql immutable set search_path='' as $valid$
declare s jsonb;observed bigint;
begin
 if not crowd_machine.native_saved_keys(v,array['schema','report_id','sequence','observed_at_ms','host','state','reason_code','source_readiness'])or v->>'schema'is distinct from'crowd-worker-capabilities-v1'
 or jsonb_typeof(v->'report_id')is distinct from'string'or coalesce(v->>'report_id','')!~'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
 or not crowd_machine.capability_int(v->'sequence',1)or not crowd_machine.capability_int(v->'observed_at_ms',1)then return false;end if;
 observed:=(v->>'observed_at_ms')::bigint;
 if not crowd_machine.native_saved_keys(v->'host',array['os','arch'])or coalesce(v#>>'{host,os}','')not in('darwin','linux','windows','android','ios','unknown')or coalesce(v#>>'{host,arch}','')not in('arm64','x64','x86','unknown')
 or coalesce(v->>'state','')not in('ready','not_ready')or coalesce(v->>'reason_code','')not in('ready','not_configured','dependency_unavailable','identity_unverified','login_in_progress','unsupported_scope','source_changed','preflight_failed')or jsonb_typeof(v->'source_readiness')is distinct from'array'then return false;end if;
 if v->>'state'='not_ready'then return v->>'reason_code'<>'ready'and jsonb_array_length(v->'source_readiness')=0;end if;
 if v->>'reason_code'<>'ready'or jsonb_array_length(v->'source_readiness')<>1 or v#>>'{host,os}'not in('darwin','linux','windows')or v#>>'{host,arch}'='unknown'then return false;end if;
 s:=v#>'{source_readiness,0}';
 if not crowd_machine.native_saved_keys(s,array['schema','engine','protocol','platform','mode','scope','comments','replies','media','max_items','max_comments','source_commit','identity_basis','identity_verified_at_ms','session_generation','session_ref','binding_sha256'])then return false;end if;
 if s->>'schema'is distinct from'crowd-pro-source-readiness-v1'or s->>'engine'is distinct from'mediacrawler_pro'or s->>'protocol'is distinct from'vox-acquisition-v1'or s->>'platform'is distinct from'xhs'or s->>'mode'is distinct from'detail'or s->>'scope'is distinct from'xhs_detail_body_comments_v1'
 or s->'comments'is distinct from'true'::jsonb or s->'replies'is distinct from'true'::jsonb or s->'media'is distinct from'false'::jsonb or s->'max_items'is distinct from'1'::jsonb or s->'max_comments'is distinct from'200'::jsonb or s->>'source_commit'is distinct from'd32dd565277116ba4880c28ccd417a7c376cb62d'
 or s->>'identity_basis'is distinct from'cached_authenticated_self_id'or not crowd_machine.capability_int(s->'identity_verified_at_ms',1)or not crowd_machine.capability_int(s->'session_generation',1)
 or jsonb_typeof(s->'session_ref')is distinct from'string'or coalesce(s->>'session_ref','')!~'^[a-f0-9]{64}$'or jsonb_typeof(s->'binding_sha256')is distinct from'string'or coalesce(s->>'binding_sha256','')!~'^[a-f0-9]{64}$'then return false;end if;
 return(s->>'identity_verified_at_ms')::bigint<=observed;
end $valid$;
create function crowd_machine.worker_pro_capability_live(p_worker uuid,p_at timestamptz)returns boolean language sql stable security definer set search_path='' as $live$
 select coalesce((select w.enabled and w.expires_at>p_at and r.expires_at>p_at
 and(r.report->>'observed_at_ms')::numeric<=extract(epoch from p_at)*1000 and(r.report->>'observed_at_ms')::numeric>=extract(epoch from p_at)*1000-120000
 and r.report->>'state'='ready'and crowd_machine.valid_worker_capability(r.report)and w.platforms?'xhs'
 from crowd_machine.workers w join lateral(select *from crowd_machine.worker_capability_reports where worker_id=w.worker_id order by sequence desc limit 1)r on true
 where w.worker_id=p_worker and w.owner_scope='crowd-owner-main'),false)
$live$;
create function crowd_machine.pro_readiness_matches(p_worker uuid,p_report uuid,p_request jsonb)returns boolean language plpgsql security definer set search_path='' as $match$
declare r crowd_machine.worker_capability_reports;s jsonb;count_value bigint;at_time timestamptz:=clock_timestamp();
begin
 if p_report is null or not crowd_machine.worker_pro_capability_live(p_worker,at_time)then return false;end if;
 select *into r from crowd_machine.worker_capability_reports where worker_id=p_worker order by sequence desc limit 1;
 if r.report_id is distinct from p_report then return false;end if;s:=r.report#>'{source_readiness,0}';
 if p_request->>'source_executor'is distinct from'pro'or p_request->>'platform'is distinct from'xhs'or p_request->>'mode'is distinct from'detail'or p_request->'max_items'is distinct from'1'::jsonb or (case when jsonb_typeof(p_request->'targets')='array'then jsonb_array_length(p_request->'targets')<>1 else true end) or p_request->'media'is distinct from'false'::jsonb or p_request->'wordcloud'is distinct from'false'::jsonb or p_request->'platform_options'is distinct from'{}'::jsonb or p_request->'start_page'is distinct from'1'::jsonb
 or jsonb_typeof(p_request->'comments')is distinct from'boolean'or jsonb_typeof(p_request->'replies')is distinct from'boolean'or(p_request->'replies'='true'::jsonb and p_request->'comments'<>'true'::jsonb)or not crowd_machine.capability_int(p_request->'max_comments')then return false;end if;
 count_value:=(p_request->>'max_comments')::bigint;if count_value>200 or(p_request->'comments'='true'::jsonb and count_value<1)then return false;end if;
 if p_request?'session_id'and p_request->'session_id'<>'null'::jsonb then
  if jsonb_typeof(p_request->'session_id')is distinct from'string'or encode(sha256(convert_to(p_request->>'session_id','UTF8')),'hex')is distinct from s->>'session_ref'then return false;end if;
 end if;return true;
end $match$;
create function crowd_machine.worker_capability_view(p_worker uuid,p_at timestamptz)returns jsonb language plpgsql stable security definer set search_path='' as $view$
declare w crowd_machine.workers;r crowd_machine.worker_capability_reports;s jsonb;state text;reason text;
begin
 select *into w from crowd_machine.workers where worker_id=p_worker and owner_scope='crowd-owner-main';if not found then return null;end if;
 select *into r from crowd_machine.worker_capability_reports where worker_id=p_worker order by sequence desc limit 1;
 s:=r.report#>'{source_readiness,0}';
 if not w.enabled then state:='needs_attention';reason:='worker_disabled';
 elsif w.expires_at<=p_at then state:='needs_attention';reason:='worker_expired';
 elsif r.report_id is null then state:='not_reported';reason:='not_reported';
 elsif r.expires_at<=p_at or(r.report->>'observed_at_ms')::numeric<extract(epoch from p_at)*1000-120000 then state:='needs_attention';reason:='expired';
 elsif crowd_machine.worker_pro_capability_live(p_worker,p_at)then state:='assignable';reason:='ready';
 else state:='needs_attention';reason:=coalesce(r.report->>'reason_code','preflight_failed');end if;
 return jsonb_build_object('node_kind','machine_worker','worker_id',w.worker_id,'name',w.name,'platforms',w.platforms,'enabled',w.enabled,'worker_expires_at',w.expires_at,
 'host_os',r.report#>'{host,os}','host_arch',r.report#>'{host,arch}','engine',s->'engine','protocol',s->'protocol','source_commit',s->'source_commit',
 'scopes',case when s is null then'[]'::jsonb else jsonb_build_array(s->'scope')end,'status',state,'reason',reason,'reported_at',r.received_at,'expires_at',r.expires_at,'sequence',r.sequence,'identity_basis',s->'identity_basis','identity_verified_at_ms',s->'identity_verified_at_ms');
end $view$;
create function public.crowd_machine_capability_rpc(p_owner_scope text,p_actor_kind text,p_worker_hash text,p_action text,p_payload jsonb)returns jsonb language plpgsql security definer set search_path='' as $rpc$
declare w crowd_machine.workers;r crowd_machine.worker_capability_reports;latest crowd_machine.worker_capability_reports;
 v jsonb;sem text;h text;seq bigint;observed bigint;at_time timestamptz:=clock_timestamp();expiry timestamptz;receipt jsonb;
 page_limit integer:=100;after_worker uuid;nodes jsonb;all_nodes jsonb;counts jsonb;total integer;next_id uuid;
begin
 if p_owner_scope is distinct from'crowd-owner-main'or jsonb_typeof(p_payload)is distinct from'object'then raise exception'principal_denied';end if;
 if p_action='worker_capabilities'then
  if p_actor_kind is distinct from'owner'or p_worker_hash is not null then raise exception'principal_denied';end if;
  if(p_payload-array['limit','after_worker_id'])<>'{}'::jsonb then raise exception'invalid_worker_capability';end if;
  if p_payload?'limit'then if not crowd_machine.capability_int(p_payload->'limit',1)then raise exception'invalid_worker_capability';end if;if(p_payload->>'limit')::numeric>100 then raise exception'invalid_worker_capability';end if;page_limit:=(p_payload->>'limit')::integer;end if;
  if p_payload?'after_worker_id'then if jsonb_typeof(p_payload->'after_worker_id')is distinct from'string'or coalesce(p_payload->>'after_worker_id','')!~'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'then raise exception'invalid_worker_capability';end if;after_worker:=(p_payload->>'after_worker_id')::uuid;end if;
  select coalesce(jsonb_agg(crowd_machine.worker_capability_view(worker_id,at_time)order by worker_id),'[]'::jsonb)into all_nodes from crowd_machine.workers where owner_scope=p_owner_scope;
  total:=jsonb_array_length(all_nodes);
  select jsonb_build_object('assignable',count(*)filter(where x->>'status'='assignable'),'needs_attention',count(*)filter(where x->>'status'='needs_attention'),'not_reported',count(*)filter(where x->>'status'='not_reported'))into counts from jsonb_array_elements(all_nodes)x;
  select coalesce(jsonb_agg(x order by(x->>'worker_id')::uuid),'[]'::jsonb)into nodes from(select x from jsonb_array_elements(all_nodes)x where after_worker is null or(x->>'worker_id')::uuid>after_worker order by(x->>'worker_id')::uuid limit page_limit)page;
  if jsonb_array_length(nodes)>0 and exists(select 1 from jsonb_array_elements(all_nodes)x where(x->>'worker_id')::uuid>(nodes->-1->>'worker_id')::uuid)then next_id:=(nodes->-1->>'worker_id')::uuid;end if;
  return jsonb_build_object('schema','crowd-worker-capabilities-page-v1','nodes',nodes,'total',total,'counts',counts,'next_cursor',next_id,'server_time',at_time);
 end if;
 if p_actor_kind is distinct from'worker'or p_action is null or p_action not in('worker_capability_report','worker_capability_status')then raise exception'principal_denied';end if;
 select *into w from crowd_machine.workers where owner_scope=p_owner_scope and token_hash=p_worker_hash for update;
 if not found or not w.enabled or w.expires_at<=at_time then raise exception'worker_revoked';end if;
 select *into latest from crowd_machine.worker_capability_reports where worker_id=w.worker_id order by sequence desc limit 1;
 if p_action='worker_capability_status'then
  if(p_payload-array['report_id'])<>'{}'::jsonb then raise exception'invalid_worker_capability';end if;
  if p_payload?'report_id'then
   if jsonb_typeof(p_payload->'report_id')is distinct from'string'or coalesce(p_payload->>'report_id','')!~'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'then raise exception'invalid_worker_capability';end if;
   select *into r from crowd_machine.worker_capability_reports where worker_id=w.worker_id and report_id=(p_payload->>'report_id')::uuid;
   if not found then raise exception'capability_report_not_found';end if;
  else r:=latest;end if;
  return jsonb_build_object('schema','crowd-worker-capability-status-v1','worker_id',w.worker_id,'latest_sequence',coalesce(latest.sequence,0),'latest_report_id',latest.report_id,'report_receipt',case when r.report_id is null then null else r.receipt||jsonb_build_object('replayed',true)end);
 end if;
 if not crowd_machine.native_saved_keys(p_payload,array['report','canonical_report','report_hash'])then raise exception'invalid_worker_capability';end if;
 v:=p_payload->'report';sem:=p_payload->>'canonical_report';h:=p_payload->>'report_hash';
 if not crowd_machine.valid_worker_capability(v)or octet_length(coalesce(sem,''))>16384 then raise exception'invalid_worker_capability';end if;
 if jsonb_typeof(p_payload->'canonical_report')is distinct from'string'or jsonb_typeof(p_payload->'report_hash')is distinct from'string'or h is distinct from encode(sha256(convert_to(E'crowd-machine-capability-report-v1\n'||sem,'UTF8')),'hex')or sem is distinct from crowd_machine.native_saved_canonical(v)then raise exception'capability_hash_mismatch';end if;
 select *into r from crowd_machine.worker_capability_reports where worker_id=w.worker_id and report_id=(v->>'report_id')::uuid;
 if found then if r.report_hash<>h or r.report<>v then raise exception'capability_report_conflict';end if;return r.receipt||jsonb_build_object('replayed',true);end if;
 observed:=(v->>'observed_at_ms')::bigint;
 if observed>extract(epoch from at_time)*1000 or observed<extract(epoch from at_time)*1000-120000 then raise exception'capability_observation_stale';end if;
 seq:=(v->>'sequence')::bigint;if seq<>coalesce(latest.sequence,0)+1 then raise exception'capability_sequence_conflict';end if;
 if v->>'state'='ready'and not(w.platforms?'xhs')then raise exception'invalid_worker_capability';end if;
 expiry:=least(at_time+interval'120 seconds',to_timestamp((observed::numeric+120000)/1000));
 receipt:=jsonb_build_object('schema','crowd-worker-capability-receipt-v1','worker_id',w.worker_id,'report_id',v->'report_id','sequence',seq,'report_hash',h,'received_at',at_time,'expires_at',expiry);
 insert into crowd_machine.worker_capability_reports values(w.worker_id,(v->>'report_id')::uuid,seq,h,v,receipt,at_time,expiry);
 return receipt||jsonb_build_object('replayed',false);
end $rpc$;
revoke all on function crowd_machine.worker_capability_immutable(),crowd_machine.capability_int(jsonb,bigint),crowd_machine.valid_worker_capability(jsonb),crowd_machine.worker_pro_capability_live(uuid,timestamptz),crowd_machine.pro_readiness_matches(uuid,uuid,jsonb),crowd_machine.worker_capability_view(uuid,timestamptz),public.crowd_machine_capability_rpc(text,text,text,text,jsonb)from public,anon,authenticated,service_role;
grant execute on function crowd_machine.pro_readiness_matches(uuid,uuid,jsonb),public.crowd_machine_capability_rpc(text,text,text,text,jsonb)to service_role;
$registry_ddl$;
 changed:=replace(replace(original,anchor,addition||anchor),validation_anchor,validation_added||validation_anchor);execute changed;
 select oid,proacl,proconfig,proowner,prosecdef,provolatile into strict after from pg_proc where oid=before.oid;
 if pg_get_functiondef(before.oid) is distinct from changed
 or after is distinct from row(before.oid,before.proacl,before.proconfig,before.proowner,before.prosecdef,before.provolatile)
 then raise exception 'pro_gate_postcondition_failed';end if;
end $g126$;
