begin;
-- Candidate only. No task activation, new grant, machine task, queue or business data migration.
do $cas$ begin
 if md5(pg_get_functiondef('public.crowd_v4_guard(text,bigint,text)'::regprocedure)) <> '9be56101ce24b3495a79d3a0babf449c' then raise exception 'pro_definition_drift:crowd_v4_guard'; end if;
 if md5(pg_get_functiondef('public.crowd_v4_submit(uuid,bigint,uuid,jsonb)'::regprocedure)) <> '4c11cb3173f22aefac98f85ec455d901' then raise exception 'pro_definition_drift:crowd_v4_submit'; end if;
 if md5(pg_get_functiondef('public.crowd_v4_admin(text,jsonb)'::regprocedure)) <> '0f8575d8fbe8e48d1cdc71675c0f0bd1' then raise exception 'pro_definition_drift:crowd_v4_admin'; end if;
 if md5(pg_get_functiondef('crowd_v4.acceptance_task_input(crowd_v4.tasks)'::regprocedure)) <> 'dcb3af6c1b16e72b2aa547d4c8b27aae' then raise exception 'pro_definition_drift:acceptance_task_input';end if;
end $cas$;
alter table crowd_v4.tasks add column source_executor text not null default 'participant_extension' check(source_executor in ('participant_extension','mediacrawler_pro'));
-- Exclude executor routing metadata from immutable original task input.
create or replace function crowd_v4.acceptance_task_input(t crowd_v4.tasks) returns jsonb language sql immutable set search_path='' as $$
 select to_jsonb(t)-array['target','received','status','claimed_by','lease_token','lease_until','available_at','last_claimed_at','lease_start_received','source_executor'];
$$;
CREATE OR REPLACE FUNCTION crowd_observation.pro_guard_base(p_action text DEFAULT 'control'::text, p_task bigint DEFAULT NULL::bigint, p_note text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$ declare result jsonb; begin
 if p_action='profile' then raise exception 'invalid_action';end if;

 if auth.uid() is not null and p_action in ('control','search','detail','comment','scroll') and crowd_v4.pilot_block_reason(p_task,auth.uid()) is not null then
  result:=crowd_observation.guard_internal('control',p_task,p_note);
  if result ? 'error' then if crowd_v4.pilot_phase(auth.uid()) is not null then result:=result||jsonb_build_object('pilot_phase',crowd_v4.pilot_phase(auth.uid())); end if; return result; end if;
  return result||jsonb_build_object('allowed',false,'reason',crowd_v4.pilot_block_reason(p_task,auth.uid()),'wait_ms',600000,'action_wait_ms',600000,'pilot_phase',crowd_v4.pilot_phase(auth.uid()))
   ||case when crowd_v4.pilot_block_reason(p_task,auth.uid())='daily_quota' then jsonb_build_object('reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
    'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint) else '{}'::jsonb end;
 end if;
 result:=crowd_observation.guard_internal(p_action,p_task,p_note);
 if p_action='rate_limit' then
  perform 1 from crowd_v4.policy where singleton for update;
  insert into crowd_observation.risk_signals(user_id) values(auth.uid()) on conflict(user_id) do update set seen_at=now();
  delete from crowd_observation.risk_signals where seen_at<now()-interval '24 hours';
  if (select count(*) from crowd_observation.risk_signals where seen_at>now()-interval '10 minutes')>=2 then
   update crowd_v4.policy set paused=true,version=version+1 where not paused;
   if found then insert into crowd_v4.audit(action,payload) values('automatic_pause','{"reason":"multiple_rate_limits"}');end if;
   result:=result||jsonb_build_object('paused',true);
  end if;
 end if;

 if p_action='control' and p_task is not null then
  result:=result||jsonb_build_object('relevance_revision',coalesce((select relevance_revision
   from crowd_v4.tasks where id=p_task and claimed_by=auth.uid() and status='leased'),1));
 end if;
 if crowd_v4.pilot_phase(auth.uid()) is not null then result:=result||jsonb_build_object('pilot_phase',crowd_v4.pilot_phase(auth.uid())); end if;
 if crowd_v4.acceptance_supplement_view(p_task,auth.uid()) is not null then
  result:=result||jsonb_build_object('acceptance_supplement',crowd_v4.acceptance_supplement_view(p_task,auth.uid()));
  if p_action='control' and result->>'reason' is null and result->'paused'='false'::jsonb and not (result ? 'error') then result:=result||jsonb_build_object('allowed',true); end if;
 end if; return result;
end $function$
;
CREATE OR REPLACE FUNCTION public.crowd_v4_guard(p_action text default 'control',p_task bigint default null,p_note text default null) returns jsonb language plpgsql security definer set search_path='' as $$
begin
 if p_action in ('search','detail','comment','scroll') and exists(select from crowd_v4.tasks where id=p_task and claimed_by=auth.uid() and source_executor='mediacrawler_pro') then return crowd_observation.pro_guard_base('control',p_task,p_note)||jsonb_build_object('allowed',false,'reason','executor_changed','wait_ms',60000);end if;
 return crowd_observation.pro_guard_base(p_action,p_task,p_note);
end $$;
CREATE OR REPLACE FUNCTION public.crowd_v4_submit(p_request uuid, p_task bigint, p_lease uuid, p_record jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$ declare result jsonb; was_replay boolean;begin

 perform 1 from crowd_v4.participants where user_id=auth.uid() for update;
 if not exists(select from crowd_v4.receipts where user_id=auth.uid() and request=p_request) and exists(select from crowd_v4.tasks where id=p_task and claimed_by=auth.uid() and source_executor='mediacrawler_pro') then return jsonb_build_object('error','executor_changed');end if;
 if auth.uid() is not null and not exists(select 1 from crowd_v4.receipts where user_id=auth.uid() and request=p_request)
  and crowd_v4.pilot_block_reason(p_task,auth.uid()) is not null then
  if crowd_v4.pilot_block_reason(p_task,auth.uid())='daily_quota' then
   return jsonb_build_object('error','daily_quota','reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
    'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint);
  end if;
  return jsonb_build_object('error',case when crowd_v4.pilot_block_reason(p_task,auth.uid())='user_stopped' then 'lease_lost' else 'task_full' end);
 end if;
 if not exists(select from crowd_v4.receipts where user_id=auth.uid() and request=p_request) and exists(select from crowd_v4.acceptance_supplements where task_id=p_task and user_id=auth.uid())
 and not exists(select from crowd_v4.acceptance_supplements g join crowd_v4.node_runs nr on nr.installation_id=g.installation_id and nr.user_id=g.user_id and nr.task_id=g.task_id and nr.lease_token=p_lease where g.user_id=auth.uid() and g.task_id=p_task) then return jsonb_build_object('error','lease_lost'); end if;
 was_replay:=exists(select from crowd_v4.receipts where user_id=auth.uid() and request=p_request);
 result:=crowd_observation.submit_internal(p_request,p_task,p_lease,p_record);
 if not was_replay and result->'inserted'='true'::jsonb and crowd_v4.acceptance_supplement_view(p_task,auth.uid())->>'schema' is distinct from 'crowd-acceptance-batch-v1' then update crowd_v4.acceptance_supplements set consumed_request=p_request where task_id=p_task and user_id=auth.uid() and consumed_request is null; end if;
 if p_request is not null then
  insert into crowd_observation.submission_status(user_id,request,task_id,error,parser_version,title_chars,body_chars,anchor_terms)
  values(auth.uid(),p_request,p_task,result->>'error',left(p_record#>>'{evidence,parser_version}',20),length(p_record#>>'{standard,title}'),length(p_record#>>'{evidence,text}'),
    (select anchor_terms from crowd_v4.tasks where id=p_task and claimed_by=auth.uid()))
  on conflict(user_id) do update set request=excluded.request,task_id=excluded.task_id,error=excluded.error,parser_version=excluded.parser_version,
   title_chars=excluded.title_chars,body_chars=excluded.body_chars,anchor_terms=excluded.anchor_terms,updated_at=now();
 end if;
 return result;
end $function$
;
CREATE OR REPLACE FUNCTION public.crowd_v4_admin(p_action text, p_payload jsonb DEFAULT '{}'::jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare t crowd_v4.tasks; f crowd_v4.proofs; u uuid; n int; result jsonb; quote text; decision text;
begin
 if p_action='publish' and jsonb_typeof(p_payload->'anchor_terms')='array' then
 p_payload:=jsonb_set(p_payload,'{anchor_terms}',crowd_observation.terms(p_payload->>'store_name',p_payload->'anchor_terms'));end if;

 if p_action='control' then
  if auth.role() is distinct from 'service_role' then raise exception 'operator_required' using errcode='42501'; end if;
  if jsonb_typeof(p_payload) is distinct from 'object' or (p_payload - array['paused','search_cap','detail_cap','comment_cap','scroll_cap','gap_seconds'])<>'{}'::jsonb
   or (p_payload ? 'paused' and jsonb_typeof(p_payload->'paused') is distinct from 'boolean') then raise exception 'invalid_control'; end if;
  if p_payload='{}'::jsonb then return (select to_jsonb(c)-'singleton' from crowd_v4.policy c where singleton); end if;
  update crowd_v4.policy set version=version+1,
   paused=coalesce((p_payload->>'paused')::boolean,paused),
   search_cap=coalesce((p_payload->>'search_cap')::int,search_cap), detail_cap=coalesce((p_payload->>'detail_cap')::int,detail_cap),
   comment_cap=coalesce((p_payload->>'comment_cap')::int,comment_cap), scroll_cap=coalesce((p_payload->>'scroll_cap')::int,scroll_cap),
   gap_seconds=coalesce((p_payload->>'gap_seconds')::int,gap_seconds) where singleton;
  insert into crowd_v4.audit(action,payload) values('control',p_payload);
  return (select to_jsonb(c)-'singleton' from crowd_v4.policy c where singleton);
 end if;
 if auth.role() is distinct from 'service_role' then raise exception 'service_only' using errcode='42501'; end if;
 if jsonb_typeof(p_payload) is distinct from 'object' then raise exception 'invalid_payload'; end if;
 if p_action='publish' then
  if jsonb_array_length(p_payload->'anchor_terms')<1 or exists(select 1 from jsonb_array_elements_text(p_payload->'anchor_terms') a(term) where length(term) not between 2 and 120) then raise exception 'invalid_anchors'; end if;
  insert into crowd_v4.tasks(source_key,query,store_name,restaurant_id,anchor_terms,target) values(p_payload->>'source_key',p_payload->>'query',p_payload->>'store_name',
   (p_payload->>'restaurant_id')::bigint,p_payload->'anchor_terms',coalesce((p_payload->>'target')::int,5)) on conflict(source_key) do nothing;
  select * into t from crowd_v4.tasks where source_key=p_payload->>'source_key';
  if t.query is distinct from p_payload->>'query' or t.anchor_terms is distinct from p_payload->'anchor_terms' then raise exception 'source_key_reused'; end if;
  result:=to_jsonb(t);
 elsif p_action in ('approve','suspend') then
  update crowd_v4.participants set status=case when p_action='approve' then 'approved' else 'suspended' end,
   quota_day=coalesce((p_payload->>'quota_day')::int,quota_day) where user_id=(p_payload->>'user_id')::uuid;
  if not found then raise exception 'participant_not_found'; end if;
  result:=jsonb_build_object('updated',true);
 elsif p_action='review' then
  -- Lock order is participant -> proof, shared with submit/reward accounting.
  select user_id into u from crowd_v4.proofs where id=(p_payload->>'proof_id')::bigint;
  if u is null then raise exception 'proof_not_found'; end if;
  perform 1 from crowd_v4.participants where user_id=u for update;
  select * into f from crowd_v4.proofs where id=(p_payload->>'proof_id')::bigint for update;
  decision:=p_payload->>'decision'; quote:=p_payload->>'quote';
  if decision not in ('verified','rejected') or decision is null or length(coalesce(p_payload->>'reason',''))<8 then raise exception 'review_reason_required'; end if;
  if f.status<>'received' then
   if f.status<>decision then raise exception 'review_is_final'; end if;
   return jsonb_build_object('status',f.status,'replayed',true);
  end if;
  if decision='verified' and (p_payload->>'public_visible' is distinct from 'true' or p_payload->>'relevant' is distinct from 'true'
   or p_payload->>'personal_experience' is distinct from 'true' or length(coalesce(quote,''))<8 or strpos(f.record->'evidence'->>'text',quote)=0
   or (p_payload->>'source_checked_at')::timestamptz is null or (p_payload->>'source_checked_at')::timestamptz>now()+interval '5 minutes'
   or (p_payload->>'source_checked_at')::timestamptz<f.received_at-interval '5 minutes') then raise exception 'strict_evidence_gate'; end if;
  update crowd_v4.proofs set status=decision,reviewed_at=now(),review_note=p_payload->>'reason',verified_quote=case when decision='verified' then quote end,
   source_checked_at=case when decision='verified' then (p_payload->>'source_checked_at')::timestamptz end where id=f.id;
  if decision='verified' and coalesce(f.record->>'source_kind','')<>'mediacrawler_pro' then
   update crowd_v4.participants set verified_count=verified_count+1 where user_id=u returning verified_count into n;
   if n%100=0 then insert into crowd_v4.rewards(user_id,batch_no) values(u,n/100) on conflict do nothing; end if;
  end if;
  result:=jsonb_build_object('status',decision);
 elsif p_action='pay' then
  if length(coalesce(p_payload->>'reference',''))<4 then raise exception 'payment_reference_required'; end if;
  update crowd_v4.rewards set paid_at=now(),payment_reference=p_payload->>'reference' where user_id=(p_payload->>'user_id')::uuid and batch_no=(p_payload->>'batch_no')::int and paid_at is null;
  if not found then
   if not exists(select 1 from crowd_v4.rewards where user_id=(p_payload->>'user_id')::uuid and batch_no=(p_payload->>'batch_no')::int and payment_reference=p_payload->>'reference') then raise exception 'payment_not_found_or_conflict'; end if;
  end if;
  result:=jsonb_build_object('paid',true);
 elsif p_action='list' then
  if p_payload->>'kind'='participants' then select coalesce(jsonb_agg(to_jsonb(p)),'[]') into result from (select * from crowd_v4.participants order by joined_at limit 200) p;
  elsif p_payload->>'kind'='rewards' then select coalesce(jsonb_agg(to_jsonb(r)),'[]') into result from (select * from crowd_v4.rewards where paid_at is null order by created_at limit 200) r;
  else select coalesce(jsonb_agg(to_jsonb(proof_row)),'[]') into result from (select * from crowd_v4.proofs where status='received' order by id limit 100) proof_row; end if;
 elsif p_action='export' then
  select coalesce(jsonb_agg(jsonb_build_object('proof_id',proof_row.id,'note_id',proof_row.note_id,'record',proof_row.record,'verified_quote',proof_row.verified_quote,
   'source_checked_at',proof_row.source_checked_at,'store_name',task_row.store_name,'restaurant_id',task_row.restaurant_id,'query',task_row.query)),'[]') into result
   from (select * from crowd_v4.proofs where status='verified' and id>coalesce((p_payload->>'after_id')::bigint,0)
    and id<=coalesce((p_payload->>'through_id')::bigint,9223372036854775807) order by id limit 200) proof_row
   join crowd_v4.tasks task_row on task_row.id=proof_row.task_id;
 else raise exception 'unknown_action';
 end if;
 if p_action not in ('list','export') then insert into crowd_v4.audit(action,payload) values(p_action,p_payload); end if;
 return result;
end $function$
;

create function crowd_observation.pro_scope(p_task bigint,p_installation_id uuid,p_lease uuid default null,p_live boolean default false,p_recovery boolean default false) returns crowd_v4.tasks
language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid();t crowd_v4.tasks;g jsonb;
begin
 if u is null then raise exception 'login_required' using errcode='42501';end if;
 perform 1 from crowd_v4.participants where user_id=u for update;
 if not found then raise exception 'approval_required';end if;
 select * into t from crowd_v4.tasks where id=p_task for update;
 if p_task is distinct from 19 or t.id is null or t.claimed_by is distinct from u or t.target<>22 or t.received not between 20 and 22
  or not exists(select from crowd_v4.nodes where installation_id=p_installation_id and user_id=u)
  or not exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id=u)
  or exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id<>u) then raise exception 'pro_scope_denied' using errcode='42501';end if;
 if p_recovery then
  if not exists(select from crowd_v4.acceptance_supplements where task_id=p_task and user_id=u and installation_id=p_installation_id and id='8df461ae-cdff-4476-bc03-47126d6eaecf'::uuid) then raise exception 'pro_scope_denied';end if;return t;
 end if;
 g:=crowd_v4.acceptance_supplement_view(p_task,u);
 if g->>'schema' is distinct from 'crowd-acceptance-batch-v1' or g->>'installation_id' is distinct from p_installation_id::text or g->>'id' is distinct from '8df461ae-cdff-4476-bc03-47126d6eaecf' or g->'baseline_received' is distinct from '2'::jsonb or g->'extra_limit' is distinct from '20'::jsonb or g->'target' is distinct from '22'::jsonb then raise exception 'pro_scope_denied' using errcode='42501';end if;
 if p_lease is not null and (t.lease_token is distinct from p_lease or not exists(select from crowd_v4.node_runs where installation_id=p_installation_id and user_id=u and task_id=p_task and lease_token=p_lease)) then raise exception 'lease_lost';end if;
 if p_live and (p_lease is null or t.status<>'leased' or t.lease_until is null or t.lease_until<=now()) then raise exception 'lease_expired';end if;
 return t;
end $$;
create function public.crowd_v4_pro_claim(p_task bigint,p_installation_id uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare t crowd_v4.tasks;r jsonb;
begin
 t:=crowd_observation.pro_scope(p_task,p_installation_id);
 if t.received>=t.target then return jsonb_build_object('error','task_full');end if;
 r:=public.crowd_v4_node_claim(p_installation_id,p_task);
 if jsonb_typeof(r->'task')='object' and (r->'task'->>'id')::bigint=p_task then
  update crowd_v4.tasks set source_executor='mediacrawler_pro' where id=p_task;
  r:=jsonb_set(r,'{task,source_executor}','"mediacrawler_pro"')||jsonb_build_object('known_note_ids',(select coalesce(jsonb_agg(note_id order by note_id),'[]'::jsonb) from crowd_v4.proofs where task_id=p_task and user_id=auth.uid()));
 end if;
 return r||jsonb_build_object('source_executor','mediacrawler_pro','reward_eligible',false);
end $$;
create function public.crowd_v4_pro_guard(p_task bigint,p_lease uuid,p_action text,p_note text,p_installation_id uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare t crowd_v4.tasks;r jsonb;
begin
 if p_lease is null then raise exception 'lease_lost';end if;
 if p_action is null or p_action not in ('control','search','detail','captcha','rate_limit') or p_action='detail' and (p_note is null or p_note!~'^[a-f0-9]{24}$') then raise exception 'invalid_action';end if;
 t:=crowd_observation.pro_scope(p_task,p_installation_id,p_lease,p_action in ('search','detail'));
 if t.source_executor<>'mediacrawler_pro' then raise exception 'pro_not_selected';end if;
 if p_action in ('search','detail') and t.received>=t.target then return jsonb_build_object('error','task_full');end if;
 r:=crowd_observation.pro_guard_base(p_action,p_task,p_note);
 return r||jsonb_build_object('source_executor','mediacrawler_pro','reward_eligible',false);
end $$;
create function public.crowd_v4_pro_status(p_task bigint,p_installation_id uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare t crowd_v4.tasks;
begin
 t:=crowd_observation.pro_scope(p_task,p_installation_id,null,false,true);
 return jsonb_build_object('known_note_ids',(select coalesce(jsonb_agg(note_id order by note_id),'[]'::jsonb) from crowd_v4.proofs where task_id=p_task and user_id=auth.uid()),'status',public.crowd_v4_status(),'progress',public.crowd_v4_progress(),'task',jsonb_build_object('id',t.id,'received',t.received,'target',t.target,'status',t.status,'source_executor',t.source_executor),'acceptance_supplement',crowd_v4.acceptance_supplement_view(p_task,auth.uid()),'source_executor',t.source_executor,'reward_eligible',false);
end $$;
create function public.crowd_v4_pro_receipt(p_task bigint,p_installation_id uuid,p_request uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare t crowd_v4.tasks;r crowd_v4.receipts;
begin
 t:=crowd_observation.pro_scope(p_task,p_installation_id,null,false,true);
 select * into r from crowd_v4.receipts where user_id=auth.uid() and request=p_request and (payload->>'task')::bigint=p_task;
 return jsonb_build_object('found',r.request is not null,'request',p_request,'receipt',r.result);
end $$;
create function public.crowd_v4_pro_finish(p_task bigint,p_lease uuid,p_installation_id uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare t crowd_v4.tasks;
begin
 t:=crowd_observation.pro_scope(p_task,p_installation_id,p_lease);
 if t.source_executor<>'mediacrawler_pro' then raise exception 'pro_not_selected';end if;
 return public.crowd_v4_finish(p_task,p_lease)||jsonb_build_object('source_executor','mediacrawler_pro','reward_eligible',false);
end $$;

create function public.crowd_v4_pro_submit(p_task bigint,p_lease uuid,p_request uuid,p_payload jsonb,p_installation_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid();t crowd_v4.tasks;old crowd_v4.receipts;r jsonb;pv jsonb;record jsonb;payload jsonb;stored jsonb;result jsonb;pid bigint;existing crowd_v4.proofs;capture timestamptz;
begin
 t:=crowd_observation.pro_scope(p_task,p_installation_id,null,false,true);
 if p_request is null or p_lease is null then return jsonb_build_object('error','invalid_envelope');end if;
 payload:=jsonb_build_object('task',p_task,'installation_id',p_installation_id,'pro_payload',p_payload);
 select * into old from crowd_v4.receipts where user_id=u and request=p_request;
 if old.request is not null then
  if old.payload is distinct from payload then return jsonb_build_object('error','request_reused');end if;
  return old.result;
 end if;
 if not exists(select from crowd_v4.participants where user_id=u and status='approved' and consent='crowd-public-v4') then raise exception 'approval_required';end if;
 if jsonb_typeof(p_payload) is distinct from 'object' or p_payload-array['schema','source_kind','reward_eligible','record','canonical_record','provenance']<>'{}'::jsonb or not p_payload?&array['schema','source_kind','reward_eligible','record','canonical_record','provenance']
  or p_payload->>'schema' is distinct from 'crowd-participant-pro-v1' or p_payload->>'source_kind' is distinct from 'mediacrawler_pro' or p_payload->'reward_eligible' is distinct from 'false'::jsonb or octet_length(p_payload::text)>180000 then return jsonb_build_object('error','invalid_pro_payload');end if;
 r:=p_payload->'record';pv:=p_payload->'provenance';
 if jsonb_typeof(r) is distinct from 'object' or r->>'platform' is distinct from 'xiaohongshu' or r->>'kind' is distinct from 'content' or r->>'source_kind' is distinct from 'mediacrawler_api' or r->'reward_eligible' is distinct from 'false'::jsonb
  or coalesce(r->>'content_id','')!~'^[a-f0-9]{24}$' or jsonb_typeof(r->'title') is distinct from 'string' or length(r->>'title')>2000 or jsonb_typeof(r->'body') is distinct from 'string' or length(r->>'body') not between 8 and 24000
  or r->'text_truncated' is distinct from 'false'::jsonb or r->>'text_status' is distinct from 'reported' or coalesce(r->>'record_hash','')!~'^[a-f0-9]{64}$'
  or jsonb_typeof(pv) is distinct from 'object' or pv-array['local_run_id','upstream_commit','observation_sha256','request_sha256','captured_at']<>'{}'::jsonb or not pv?&array['local_run_id','upstream_commit','observation_sha256','request_sha256','captured_at']
  or coalesce(pv->>'local_run_id','')!~'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$' or r#>>'{origin,run_id}' is distinct from pv->>'local_run_id'
  or coalesce(pv->>'upstream_commit','')!~'^[a-f0-9]{40}$' or coalesce(pv->>'request_sha256','')!~'^[a-f0-9]{64}$' or pv->>'observation_sha256' is distinct from r->>'record_hash'
  or jsonb_typeof(p_payload->'canonical_record') is distinct from 'string' then return jsonb_build_object('error','invalid_pro_record');end if;
 begin
  if (p_payload->>'canonical_record')::jsonb is distinct from r-'record_hash' or encode(sha256(convert_to(p_payload->>'canonical_record','UTF8')),'hex') is distinct from r->>'record_hash' then return jsonb_build_object('error','record_hash_mismatch');end if;
  capture:=(pv->>'captured_at')::timestamptz;
 exception when others then return jsonb_build_object('error','invalid_pro_record');end;
 if capture is null or capture>now()+interval '5 minutes' or capture<now()-interval '24 hours' then return jsonb_build_object('error','invalid_timestamp');end if;
 if not exists(select from jsonb_array_elements_text(t.anchor_terms)a(term) where length(term)>=2 and strpos(lower(regexp_replace((r->>'title')||' '||(r->>'body'),'[[:space:][:punct:]]','','g')),lower(regexp_replace(term,'[[:space:][:punct:]]','','g')))>0) then return jsonb_build_object('error','unrelated_note');end if;
 if t.source_executor<>'mediacrawler_pro' then return jsonb_build_object('error','pro_not_selected');end if;
 select * into existing from crowd_v4.proofs where note_id=r->>'content_id';
 if existing.id is null then
  t:=crowd_observation.pro_scope(p_task,p_installation_id,p_lease,true);
  if t.received>=t.target then return jsonb_build_object('error','task_full');end if;
  if crowd_v4.pilot_block_reason(p_task,u) is not null then return jsonb_build_object('error',crowd_v4.pilot_block_reason(p_task,u));end if;
  if not exists(select from crowd_v4.note_reservations where note_id=r->>'content_id' and user_id=u and expires_at>now()) then return jsonb_build_object('error','detail_not_admitted');end if;
  if exists(select from crowd_v4.policy where singleton and paused) or exists(select from crowd_v4.safety where user_id=u and cooldown_until>now()) then return jsonb_build_object('error','safety_pause');end if;
  stored:=jsonb_build_object('schema_version','participant-pro-v1','source_kind','mediacrawler_pro','reward_eligible',false,
   'standard',jsonb_build_object('platform','xiaohongshu','note_id',r->>'content_id','url','https://www.xiaohongshu.com/explore/'||(r->>'content_id'),'title',r->>'title','captured_at',pv->>'captured_at','published_at',null,'author_display',r#>>'{author,display_name}','like_count',null,'collect_count',null,'comment_count',null),
   'evidence',jsonb_build_object('source','mediacrawler_pro','text',r->>'body','original_length',length(r->>'body'),'truncated',false,'parser_version',pv->>'upstream_commit'),
   'extra',jsonb_build_object('normalized_record',r,'provenance',pv));
  insert into crowd_v4.proofs(note_id,user_id,task_id,record)values(r->>'content_id',u,p_task,stored)on conflict(note_id)do nothing returning id into pid;
  if pid is not null then update crowd_v4.tasks set received=received+1 where id=p_task returning * into t;end if;
 end if;
 if pid is null and existing.user_id=u and existing.task_id=p_task then pid:=existing.id;end if;
 result:=jsonb_build_object('request',p_request,'gate','received','inserted',existing.id is null and pid is not null,'duplicate',existing.id is not null or pid is null,'task_received',t.received,'proof_id',pid,'source_kind','mediacrawler_pro','reward_eligible',false,'record_hash',r->>'record_hash');
 insert into crowd_v4.receipts(user_id,request,payload,result)values(u,p_request,payload,result);
 return result;
end $$;

revoke all on function crowd_observation.pro_scope(bigint,uuid,uuid,boolean,boolean),crowd_observation.pro_guard_base(text,bigint,text) from public,anon,authenticated;
revoke all on function public.crowd_v4_pro_claim(bigint,uuid),public.crowd_v4_pro_guard(bigint,uuid,text,text,uuid),public.crowd_v4_pro_submit(bigint,uuid,uuid,jsonb,uuid),public.crowd_v4_pro_status(bigint,uuid),public.crowd_v4_pro_receipt(bigint,uuid,uuid),public.crowd_v4_pro_finish(bigint,uuid,uuid) from public,anon;
grant execute on function public.crowd_v4_pro_claim(bigint,uuid),public.crowd_v4_pro_guard(bigint,uuid,text,text,uuid),public.crowd_v4_pro_submit(bigint,uuid,uuid,jsonb,uuid),public.crowd_v4_pro_status(bigint,uuid),public.crowd_v4_pro_receipt(bigint,uuid,uuid),public.crowd_v4_pro_finish(bigint,uuid,uuid) to authenticated;
commit;
