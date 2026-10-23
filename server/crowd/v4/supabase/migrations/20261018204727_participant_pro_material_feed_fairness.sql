-- Candidate only: ROOT copies exact bytes to CLI-created formal 20261018203933 file after review.
-- One existing read-only Owner feed function, no data/table/queue/scheduler/source changes.
begin;
do $$begin
 if md5(pg_get_functiondef('public.crowd_participant_pro_receipts_rpc(text,text,jsonb)'::regprocedure)) is distinct from '66972c3dc2c9922e5780b38b34627cfd' then raise exception 'g06_feed_fairness_preimage_mismatch';end if;
 if (select proacl::text from pg_proc where oid='public.crowd_participant_pro_receipts_rpc(text,text,jsonb)'::regprocedure)is distinct from '{postgres=X/postgres,service_role=X/postgres}' then raise exception 'g06_feed_fairness_acl_mismatch';end if;
 if (select proconfig from pg_proc where oid='public.crowd_participant_pro_receipts_rpc(text,text,jsonb)'::regprocedure)is distinct from array['search_path=""']::text[] then raise exception 'g06_feed_fairness_config_mismatch';end if;
end $$;
CREATE OR REPLACE FUNCTION public.crowd_participant_pro_receipts_rpc(p_owner_scope text, p_actor_kind text, p_payload jsonb DEFAULT '{}'::jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare lim integer:=8; c jsonb; cursor_time timestamptz;cursor_request uuid;cursor_task bigint;cursor_user uuid;cursor_install uuid;cursor_dispatch uuid;
 g record; rows jsonb; children jsonb; captures jsonb;child_n bigint;child_bytes bigint; item record; groups jsonb:='[]'; next_c jsonb:=null; more boolean:=false;with_comments boolean:=false; n bigint; bytes bigint; result jsonb;
begin
 if p_owner_scope is distinct from 'crowd-owner-main' or p_actor_kind is distinct from 'owner' then raise exception 'principal_denied' using errcode='42501';end if;
 if jsonb_typeof(p_payload) is distinct from 'object' or p_payload-array['after','limit']<>'{}' then raise exception 'invalid_request';end if;
 if p_payload?'limit' then
  if jsonb_typeof(p_payload->'limit') is distinct from 'number' or (p_payload->>'limit')!~'^[1-8]$' then raise exception 'invalid_request';end if;lim:=(p_payload->>'limit')::int;
 end if;
 c:=p_payload->'after';
 if c is not null and c<>'null'::jsonb then
  if jsonb_typeof(c) is distinct from 'object' or c-array['created_at','request','task_id','subject','installation_id','dispatch_id']<>'{}' or not c?&array['created_at','request','task_id','subject','installation_id','dispatch_id'] then raise exception 'invalid_request';end if;
  begin
   if jsonb_typeof(c->'task_id')<>'number' or (c->>'task_id')!~'^[1-9][0-9]{0,15}$' or c->>'created_at'!~'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$' then raise exception 'invalid_request';end if;
   cursor_time:=(c->>'created_at')::timestamptz;cursor_request:=(c->>'request')::uuid;cursor_task:=(c->>'task_id')::bigint;cursor_user:=(c->>'subject')::uuid;cursor_install:=(c->>'installation_id')::uuid;cursor_dispatch:=(c->>'dispatch_id')::uuid;
   if cursor_time is null or cursor_request is null or cursor_task is null or cursor_user is null or cursor_install is null or cursor_dispatch is null then raise exception 'invalid_request';end if;
  exception when others then raise exception 'invalid_request';end;
 end if;
 -- Cursor is a per-scan traversal position, not a commit-order watermark.
 next_c:=case when c is null or c='null'::jsonb then null else c end;
 for g in
  with eligible as (
   select t.id task_id,r.user_id,(r.payload->>'installation_id')::uuid installation_id,d.dispatch_id,t.status,t.target,t.received,r.created_at,r.request
   from crowd_v4.receipts r join crowd_v4.tasks t on r.payload->>'task'=t.id::text
   join crowd_machine.unified_participant_tasks m on m.task_id=t.id join crowd_machine.unified_dispatches d on d.dispatch_id=m.dispatch_id and d.owner_scope=p_owner_scope
   where r.payload#>>'{pro_payload,schema}'='crowd-participant-pro-v1' and r.result->'inserted'='true'::jsonb and r.result->'duplicate'='false'::jsonb and r.result->>'gate'='received' and r.result->>'source_kind'='mediacrawler_pro'
   union all
   select t.id task_id,r.user_id,(r.data->>'installation_id')::uuid installation_id,d.dispatch_id,t.status,t.target,t.received,(r.result->>'created_at')::timestamptz created_at,r.request
   from crowd_observation.receipts r join crowd_v4.tasks t on r.data->>'task'=t.id::text
   join crowd_machine.unified_participant_tasks m on m.task_id=t.id join crowd_machine.unified_dispatches d on d.dispatch_id=m.dispatch_id and d.owner_scope=p_owner_scope
   where t.comments_capture and r.kind in ('pro_comment','pro_comment_capture')
  ), last_per_group as (
   select distinct on(task_id,user_id,installation_id,dispatch_id) * from eligible order by task_id,user_id,installation_id,dispatch_id,created_at desc,request desc
  )select * from last_per_group l where
   not exists(select from crowd_v4.tasks ct where ct.id=l.task_id and ct.comments_capture and exists(
    select from crowd_v4.receipts br where br.user_id=l.user_id and br.payload->>'task'=l.task_id::text and br.payload->>'installation_id'=l.installation_id::text
    and br.payload#>>'{pro_payload,schema}'='crowd-participant-pro-v1' and br.result->>'gate'='received' and br.result->'inserted'='true'::jsonb and br.result->'duplicate'='false'::jsonb
    and not exists(select from crowd_observation.receipts cr where cr.user_id=l.user_id and cr.parent_request=br.request and cr.kind='pro_comment_capture')
   ))
   and (cursor_time is null or (created_at,request,task_id,user_id,installation_id,dispatch_id)>(cursor_time,cursor_request,cursor_task,cursor_user,cursor_install,cursor_dispatch))
  order by created_at,request,task_id,user_id,installation_id,dispatch_id limit lim+1
 loop
  if jsonb_array_length(groups)>=lim then more:=true;exit;end if;
  select count(*),coalesce(sum(octet_length(r.payload::text)+octet_length(r.result::text)),0) into n,bytes
   from crowd_v4.receipts r where r.user_id=g.user_id and r.payload->>'task'=g.task_id::text and r.payload->>'installation_id'=g.installation_id::text
    and r.payload#>>'{pro_payload,schema}'='crowd-participant-pro-v1' and r.result->'inserted'='true'::jsonb and r.result->'duplicate'='false'::jsonb and r.result->>'gate'='received' and r.result->>'source_kind'='mediacrawler_pro';
  select count(*),coalesce(sum(octet_length(cr.data::text)+octet_length(cr.result::text)),0) into child_n,child_bytes from crowd_observation.receipts cr where cr.user_id=g.user_id and cr.data->>'task'=g.task_id::text and cr.data->>'installation_id'=g.installation_id::text and cr.kind in ('pro_comment','pro_comment_capture');
  if n<1 or n+child_n>2000 or bytes+child_bytes>8*1024*1024 then raise exception 'participant_receipt_feed_limit';end if;
  if exists(select from crowd_v4.tasks t where t.id=g.task_id and t.comments_capture) and exists(
   select from crowd_v4.receipts br where br.user_id=g.user_id and br.payload->>'task'=g.task_id::text and br.payload->>'installation_id'=g.installation_id::text
    and br.payload#>>'{pro_payload,schema}'='crowd-participant-pro-v1' and br.result->>'gate'='received' and br.result->'inserted'='true'::jsonb and br.result->'duplicate'='false'::jsonb
    and not exists(select from crowd_observation.receipts cr where cr.user_id=g.user_id and cr.parent_request=br.request and cr.kind='pro_comment_capture')
  )then raise exception 'comment_capture_pending';end if;
  rows:='[]';
  for item in
   select r.request,r.user_id,r.payload,r.result,r.created_at,p.id proof_id,p.user_id proof_user,p.task_id proof_task,p.note_id,p.record proof_record,p.status proof_status
   from crowd_v4.receipts r left join crowd_v4.proofs p on p.id::text=r.result->>'proof_id'
   where r.user_id=g.user_id and r.payload->>'task'=g.task_id::text and r.payload->>'installation_id'=g.installation_id::text
    and r.payload#>>'{pro_payload,schema}'='crowd-participant-pro-v1' and r.result->'inserted'='true'::jsonb and r.result->'duplicate'='false'::jsonb and r.result->>'gate'='received' and r.result->>'source_kind'='mediacrawler_pro'
   order by r.created_at,r.request
  loop
   if item.proof_id is null or item.proof_user is distinct from g.user_id or item.proof_task is distinct from g.task_id or item.note_id is distinct from item.payload#>>'{pro_payload,record,content_id}'
    or jsonb_typeof(item.result) is distinct from 'object'
    or item.result-array['request','gate','inserted','duplicate','task_received','proof_id','source_kind','reward_eligible','record_hash']<>'{}'::jsonb
    or not item.result?&array['request','gate','inserted','duplicate','task_received','proof_id','source_kind','reward_eligible','record_hash']
    or item.proof_status is null
    or item.result->>'request' is distinct from item.request::text or item.result->'reward_eligible' is distinct from 'false'::jsonb
    or item.payload-array['task','installation_id','pro_payload']<>'{}'
    or jsonb_typeof(item.payload->'pro_payload') is distinct from 'object'
    or (item.payload->'pro_payload')-array['schema','source_kind','reward_eligible','record','canonical_record','provenance']<>'{}'::jsonb
    or not (item.payload->'pro_payload')?&array['schema','source_kind','reward_eligible','record','canonical_record','provenance']
    or jsonb_typeof(item.payload#>'{pro_payload,provenance}') is distinct from 'object'
    or (item.payload#>'{pro_payload,provenance}')-array['local_run_id','upstream_commit','observation_sha256','request_sha256','captured_at']<>'{}'::jsonb
    or not (item.payload#>'{pro_payload,provenance}')?&array['local_run_id','upstream_commit','observation_sha256','request_sha256','captured_at']
    or (item.payload->'pro_payload')::text ~* '"(cookie|authorization|access_token|refresh_token|password|private_key|api_key|lease_token)"[[:space:]]*:'
    or item.payload#>>'{pro_payload,record,kind}' is distinct from 'content' or item.payload#>>'{pro_payload,record,platform}' is distinct from 'xiaohongshu'
    or item.payload#>>'{pro_payload,source_kind}' is distinct from 'mediacrawler_pro' or item.payload#>'{pro_payload,reward_eligible}' is distinct from 'false'::jsonb
    or item.payload#>>'{pro_payload,record,source_kind}' is distinct from 'mediacrawler_api' or item.payload#>'{pro_payload,record,reward_eligible}' is distinct from 'false'::jsonb
    or item.proof_record->>'source_kind' is distinct from 'mediacrawler_pro' or item.proof_record->'reward_eligible' is distinct from 'false'::jsonb
    or item.proof_record#>'{extra,normalized_record}' is distinct from item.payload#>'{pro_payload,record}'
    or item.proof_record#>'{extra,provenance}' is distinct from item.payload#>'{pro_payload,provenance}'
    or item.result->>'record_hash' is distinct from item.payload#>>'{pro_payload,record,record_hash}'
    or item.payload#>>'{pro_payload,provenance,observation_sha256}' is distinct from item.result->>'record_hash'
    or encode(sha256(convert_to(item.payload#>>'{pro_payload,canonical_record}','UTF8')),'hex') is distinct from item.result->>'record_hash'
    or (item.payload#>>'{pro_payload,canonical_record}')::jsonb is distinct from (item.payload#>'{pro_payload,record}')-'record_hash'
    then raise exception 'participant_receipt_feed_invalid';end if;
   rows:=rows||jsonb_build_array(jsonb_build_object('request',item.request,'proof_id',item.proof_id,'created_at',item.created_at,'pro_payload',item.payload->'pro_payload','receipt',item.result,'proof_status',item.proof_status));
  end loop;
  if exists(select from crowd_v4.tasks t where t.id=g.task_id and t.comments_capture)then
   with_comments:=true;
   children:=crowd_observation.pro_comment_feed_rows(g.task_id,g.user_id,g.installation_id,'pro_comment');
   captures:=crowd_observation.pro_comment_feed_rows(g.task_id,g.user_id,g.installation_id,'pro_comment_capture');
  elsif child_n<>0 then raise exception 'participant_receipt_feed_invalid';end if;
  next_c:=jsonb_build_object('created_at',g.created_at,'request',g.request,'task_id',g.task_id,'subject',g.user_id,'installation_id',g.installation_id,'dispatch_id',g.dispatch_id);
  groups:=groups||jsonb_build_array(jsonb_build_object('task_id',g.task_id,'subject',g.user_id,'installation_id',g.installation_id,'dispatch_id',g.dispatch_id,'task_status',g.status,'target',g.target,'received',g.received,'group_cursor',next_c,'receipts',rows)||(case when exists(select from crowd_v4.tasks t where t.id=g.task_id and t.comments_capture)then jsonb_build_object('comment_receipts',children,'comment_captures',captures)else '{}'::jsonb end));
 end loop;
 result:=jsonb_build_object('schema',(case when with_comments then 'crowd-participant-pro-receipt-feed-v2'else 'crowd-participant-pro-receipt-feed-v1'end),'groups',groups,'next_cursor',next_c,'has_more',more);
 if octet_length(result::text)>8*1024*1024 then raise exception 'participant_receipt_feed_limit';end if;
 return result;
end $function$;
commit;
