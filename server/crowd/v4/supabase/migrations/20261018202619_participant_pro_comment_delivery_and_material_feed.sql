-- Candidate only. Root creates the formal filename with Supabase CLI; reviewer gate before apply.
-- Saved Pro child ACK mapping. No table, role, target, source counter, grant or scoring mutation.
-- Before-functions are pinned from saved actual production readbacks. Existing OIDs/ACLs are retained.
begin;
do $$begin
 if md5(pg_get_functiondef('public.crowd_v4_pro_guard(bigint,uuid,text,text,uuid)'::regprocedure)) is distinct from 'c18e5552a7cc1f1c0be9df88f3ad72d7' then raise exception 'g06_function_preimage_mismatch';end if;
 if md5(pg_get_functiondef('public.crowd_v4_pro_finish(bigint,uuid,uuid)'::regprocedure)) is distinct from 'ae97c689b769510c7f1f892e7075dbd2' then raise exception 'g06_function_preimage_mismatch';end if;
 if md5(pg_get_functiondef('public.crowd_participant_pro_receipts_rpc(text,text,jsonb)'::regprocedure)) is distinct from '4ff5ab3b1b216d8761e5ce39ad7c4b78' then raise exception 'g06_function_preimage_mismatch';end if;
 if md5(pg_get_functiondef('crowd_observation.pro_scope(bigint,uuid,uuid,boolean,boolean)'::regprocedure)) is distinct from 'db494e9920e1786c3520166b717bf8ee' then raise exception 'g06_function_preimage_mismatch';end if;
end $$;
-- Participant Pro saved-comment mapping only. No table, source, quota or body-target mutation.
create function crowd_observation.pro_comment_parent(p_task bigint,p_installation_id uuid,p_user uuid,p_parent uuid,p_run uuid) returns crowd_v4.receipts
language plpgsql stable security definer set search_path='' as $$
declare r crowd_v4.receipts;p crowd_v4.proofs;
begin
 select * into r from crowd_v4.receipts where user_id=p_user and request=p_parent;
 if r.request is null or r.payload->>'task' is distinct from p_task::text or r.payload->>'installation_id' is distinct from p_installation_id::text
 or r.payload#>>'{pro_payload,schema}' is distinct from 'crowd-participant-pro-v1' or r.payload#>>'{pro_payload,provenance,local_run_id}' is distinct from p_run::text
 or r.result->'inserted' is distinct from 'true'::jsonb or r.result->'duplicate' is distinct from 'false'::jsonb or r.result->>'gate' is distinct from 'received'
 or r.payload#>>'{pro_payload,record,kind}' is distinct from 'content' or r.result->>'record_hash' is distinct from r.payload#>>'{pro_payload,record,record_hash}'
 or encode(sha256(convert_to(r.payload#>>'{pro_payload,canonical_record}','UTF8')),'hex') is distinct from r.result->>'record_hash' or (r.payload#>>'{pro_payload,canonical_record}')::jsonb is distinct from (r.payload#>'{pro_payload,record}')-'record_hash'
 or r.result->>'source_kind' is distinct from 'mediacrawler_pro' or r.result->'reward_eligible' is distinct from 'false'::jsonb then raise exception 'comment_parent_denied';end if;
 select * into p from crowd_v4.proofs where id::text=r.result->>'proof_id';
 if p.id is null or p.user_id is distinct from p_user or p.task_id is distinct from p_task or p.note_id is distinct from r.payload#>>'{pro_payload,record,content_id}'
 or p.record#>'{extra,normalized_record}' is distinct from r.payload#>'{pro_payload,record}' or p.record#>'{extra,provenance}' is distinct from r.payload#>'{pro_payload,provenance}'
 or p.record->>'source_kind' is distinct from 'mediacrawler_pro' or p.record->'reward_eligible' is distinct from 'false'::jsonb then raise exception 'comment_parent_denied';end if;
 return r;
end $$;

create function crowd_observation.pro_comment_validate(p_task bigint,p_installation_id uuid,p_user uuid,p_parent uuid,p_request uuid,p_payload jsonb,p_kind text) returns crowd_v4.receipts
language plpgsql stable security definer set search_path='' as $$
declare rec jsonb:=p_payload->'record';pv jsonb:=p_payload->'provenance';par crowd_v4.receipts;run uuid;capture timestamptz;expected uuid;
begin
 if p_kind not in ('pro_comment','pro_comment_capture') or p_request is null or p_parent is null
 or jsonb_typeof(p_payload) is distinct from 'object' or p_payload-array['schema','source_kind','reward_eligible','record','canonical_record','provenance']<>'{}'::jsonb
 or not p_payload?&array['schema','source_kind','reward_eligible','record','canonical_record','provenance'] or octet_length(p_payload::text)>131072
 or p_payload->>'schema' is distinct from (case p_kind when 'pro_comment' then 'crowd-participant-pro-comment-v1' else 'crowd-participant-pro-comment-capture-v1' end)
 or p_payload->>'source_kind' is distinct from 'mediacrawler_pro' or p_payload->'reward_eligible' is distinct from 'false'::jsonb
 or jsonb_typeof(rec) is distinct from 'object' or rec->>'platform' is distinct from 'xiaohongshu' or coalesce(rec->>'content_id','')!~'^[a-f0-9]{24}$'
 or rec->>'kind' is distinct from (case p_kind when 'pro_comment' then 'comment' else 'comment_capture' end)
 or rec->>'source_kind' is distinct from (case p_kind when 'pro_comment' then 'mediacrawler_api' else 'mediacrawler_pro_manifest' end)
 or rec->'reward_eligible' is distinct from 'false'::jsonb or coalesce(rec->>'record_hash','')!~'^[a-f0-9]{64}$'
 or jsonb_typeof(pv) is distinct from 'object' or pv-array['local_run_id','upstream_commit','observation_sha256','request_sha256','captured_at']<>'{}'::jsonb
 or not pv?&array['local_run_id','upstream_commit','observation_sha256','request_sha256','captured_at']
 or coalesce(pv->>'upstream_commit','')!~'^[a-f0-9]{40}$' or coalesce(pv->>'request_sha256','')!~'^[a-f0-9]{64}$'
 or pv->>'observation_sha256' is distinct from rec->>'record_hash' or jsonb_typeof(p_payload->'canonical_record') is distinct from 'string'
 or p_payload::text ~* '"(cookie|authorization|access_token|refresh_token|password|private_key|api_key|lease_token)"[[:space:]]*:' then raise exception 'invalid_pro_comment';end if;
 begin
  run:=(pv->>'local_run_id')::uuid;capture:=(pv->>'captured_at')::timestamptz;
  if run is null or rec#>>'{origin,run_id}' is distinct from run::text or capture is null or capture>now()+interval '5 minutes'
  or (p_payload->>'canonical_record')::jsonb is distinct from rec-'record_hash'
  or encode(sha256(convert_to(p_payload->>'canonical_record','UTF8')),'hex') is distinct from rec->>'record_hash' then raise exception 'invalid_pro_comment';end if;
 exception when others then raise exception 'invalid_pro_comment';end;
 par:=crowd_observation.pro_comment_parent(p_task,p_installation_id,p_user,p_parent,run);
 if p_parent is distinct from extensions.uuid_generate_v5(run,p_task::text||':'||(rec->>'content_id')) or pv-'observation_sha256' is distinct from (par.payload#>'{pro_payload,provenance}')-'observation_sha256' or rec->>'content_id' is distinct from par.payload#>>'{pro_payload,record,content_id}' or capture<(par.payload#>>'{pro_payload,provenance,captured_at}')::timestamptz-interval '5 minutes' then raise exception 'comment_parent_denied';end if;
 if p_kind='pro_comment' then
  if coalesce(rec->>'comment_id','')!~'^[a-f0-9]{24}$'
   or jsonb_typeof(rec->'text') is distinct from 'string'
   or rec->>'text_status' is distinct from 'reported' or rec->'text_truncated' is distinct from 'false'::jsonb or not rec?'parent_comment_id' or (rec->>'parent_comment_id'<>''and coalesce(rec->>'parent_comment_id','')!~'^[a-f0-9]{24}$') or rec->>'parent_comment_id' is null then raise exception 'invalid_pro_comment';end if;
  expected:=extensions.uuid_generate_v5(run,p_task::text||':comment:'||(rec->>'content_id')||':'||(rec->>'comment_id'));
 else
  expected:=extensions.uuid_generate_v5(run,p_task::text||':comment-capture:'||(rec->>'content_id'));
 end if;
 if p_request is distinct from expected then raise exception 'comment_request_mismatch';end if;
 return par;
end $$;

create function public.crowd_v4_pro_comment_submit(p_task bigint,p_lease uuid,p_request uuid,p_parent_request uuid,p_payload jsonb,p_installation_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid();t crowd_v4.tasks;old crowd_observation.receipts;par crowd_v4.receipts;data jsonb;result jsonb;
begin
 t:=crowd_observation.pro_scope(p_task,p_installation_id,null,false,true);
 data:=jsonb_build_object('task',p_task,'installation_id',p_installation_id,'pro_payload',p_payload);
 select * into old from crowd_observation.receipts where user_id=u and request=p_request;
 if old.request is not null then
  if old.kind<>'pro_comment' or old.parent_request is distinct from p_parent_request or old.data is distinct from data then return jsonb_build_object('error','request_reused');end if;return old.result;
 end if;
 if not t.comments_capture or t.source_executor<>'mediacrawler_pro' then raise exception 'comments_not_enabled';end if;
 if p_lease is null or not exists(select from crowd_v4.node_runs where user_id=u and installation_id=p_installation_id and task_id=p_task and lease_token=p_lease) then raise exception 'lease_lost';end if;
 if not exists(select from crowd_v4.participants where user_id=u and status='approved'and consent='crowd-public-v4') then raise exception 'approval_required';end if;
 par:=crowd_observation.pro_comment_validate(p_task,p_installation_id,u,p_parent_request,p_request,p_payload,'pro_comment');
 if exists(select from crowd_observation.receipts where user_id=u and parent_request=p_parent_request and kind='pro_comment_capture') then raise exception 'comment_capture_sealed';end if;
 result:=jsonb_build_object('request',p_request,'gate','comment_received','inserted',true,'duplicate',false,'parent_request',p_parent_request,
 'note_id',p_payload#>>'{record,content_id}','comment_id',p_payload#>>'{record,comment_id}','record_hash',p_payload#>>'{record,record_hash}','source_kind','mediacrawler_pro','reward_eligible',false,'created_at',to_char(clock_timestamp() at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 insert into crowd_observation.receipts(user_id,request,parent_request,kind,data,result)values(u,p_request,p_parent_request,'pro_comment',data,result);
 return result;
end $$;

create function public.crowd_v4_pro_comment_receipt(p_task bigint,p_installation_id uuid,p_request uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare t crowd_v4.tasks;r crowd_observation.receipts;
begin
 t:=crowd_observation.pro_scope(p_task,p_installation_id,null,false,true);
 select * into r from crowd_observation.receipts where user_id=auth.uid()and request=p_request and kind in ('pro_comment','pro_comment_capture')and data->>'task'=p_task::text and data->>'installation_id'=p_installation_id::text;
 return jsonb_build_object('found',r.request is not null,'request',p_request,'receipt',r.result);
end $$;

create function crowd_observation.pro_comment_capture_check(p_user uuid,p_task bigint,p_installation_id uuid,p_parent uuid,p_record jsonb) returns void
language plpgsql stable security definer set search_path='' as $$
declare obj jsonb;pg jsonb;x record;r crowd_observation.receipts;ids text[]:='{}';requests uuid[]:='{}';page_ids text[]:='{}';chains jsonb:='{}';chain text;last jsonb;coverage text:=p_record#>>'{coverage,coverage}';root_ids text[]:='{}';root_cursors text[]:='{}';rp jsonb;reply_count integer;reply_unique integer;reply_first jsonb;reply_expected bigint;reply boolean:=p_record#>'{resolved_native_options,replies}'='true'::jsonb;
begin
 if p_record-array['kind','platform','content_id','source_kind','reward_eligible','origin','objects','pages','source_pagination_sha256','coverage','resolved_native_options','record_hash']<>'{}'::jsonb
 or not p_record?&array['kind','platform','content_id','source_kind','reward_eligible','origin','objects','pages','source_pagination_sha256','coverage','resolved_native_options','record_hash']
 or jsonb_typeof(p_record->'origin')is distinct from'object' or(p_record->'origin')-array['run_id']<>'{}'::jsonb
 or jsonb_typeof(p_record->'objects') is distinct from 'array' or jsonb_typeof(p_record->'pages') is distinct from 'array' or jsonb_array_length(p_record->'pages')>1000 or jsonb_array_length(p_record->'objects')>10000
 or (jsonb_array_length(p_record->'pages')>0 and coalesce(p_record->>'source_pagination_sha256','')!~'^[a-f0-9]{64}$') or jsonb_typeof(p_record->'coverage') is distinct from 'object'
 or (p_record->'coverage')-array['coverage','reason']<>'{}'::jsonb or not(p_record->'coverage')?&array['coverage','reason']
 or coalesce(coverage,'') not in ('exhausted','limit_reached','partial','unknown')or jsonb_typeof(p_record#>'{coverage,reason}') is distinct from 'string' or coalesce(p_record#>>'{coverage,reason}','')!~'^[a-z_]{1,100}$'
 or jsonb_typeof(p_record->'resolved_native_options') is distinct from 'object' or(p_record->'resolved_native_options')-array['comments','replies','max_comments']<>'{}'::jsonb
 or not(p_record->'resolved_native_options')?&array['comments','replies','max_comments']or p_record#>'{resolved_native_options,comments}'is distinct from 'true'::jsonb
 or jsonb_typeof(p_record#>'{resolved_native_options,replies}')is distinct from 'boolean' or jsonb_typeof(p_record#>'{resolved_native_options,max_comments}') is distinct from 'number' or coalesce(p_record#>>'{resolved_native_options,max_comments}','')!~'^[0-9]{1,9}$'
 then raise exception 'invalid_comment_capture';end if;
 if jsonb_array_length(p_record->'pages')=0 then
  if jsonb_array_length(p_record->'objects')<>0 or p_record->'source_pagination_sha256'is distinct from'null'::jsonb or coalesce(coverage,'') not in('partial','unknown')or exists(select from crowd_observation.receipts where user_id=p_user and parent_request=p_parent and kind='pro_comment')then raise exception 'invalid_comment_capture';end if;return;
 end if;
 for obj in select value from jsonb_array_elements(p_record->'objects')loop
  if jsonb_typeof(obj) is distinct from 'object' or obj-array['request','comment_id','record_hash']<>'{}'::jsonb or not obj?&array['request','comment_id','record_hash']then raise exception 'invalid_comment_capture';end if;
  begin
   if(obj->>'request')::uuid=any(requests)or obj->>'comment_id'=any(ids)then raise exception 'invalid_comment_capture';end if;
   requests:=array_append(requests,(obj->>'request')::uuid);ids:=array_append(ids,obj->>'comment_id');
  exception when others then raise exception 'invalid_comment_capture';end;
  select * into r from crowd_observation.receipts where user_id=p_user and request=(obj->>'request')::uuid;
  if r.request is null or r.kind<>'pro_comment' or r.parent_request is distinct from p_parent or r.data->>'task' is distinct from p_task::text or r.data->>'installation_id' is distinct from p_installation_id::text
  or r.data#>>'{pro_payload,provenance,local_run_id}' is distinct from p_record#>>'{origin,run_id}' or r.result->>'comment_id' is distinct from obj->>'comment_id' or r.result->>'record_hash' is distinct from obj->>'record_hash'
  or r.result->>'gate' is distinct from 'comment_received' or r.result->'inserted' is distinct from 'true'::jsonb or r.result->'duplicate' is distinct from 'false'::jsonb then raise exception 'comment_capture_objects_mismatch';end if;
 end loop;
 if (select count(*)from crowd_observation.receipts where user_id=p_user and parent_request=p_parent and kind='pro_comment')<>cardinality(requests)then raise exception 'comment_capture_objects_mismatch';end if;
 for pg in select value from jsonb_array_elements(p_record->'pages')loop
  if jsonb_typeof(pg) is distinct from 'object' or pg-array['checkpoint_committed','content_id','cursor_in','cursor_out','embedded','has_more','ids','invalid','parent_id','pinned_gap','reply_cursor_start','reply_roots','saved','scope']<>'{}'::jsonb
  or not pg?&array['checkpoint_committed','content_id','cursor_in','cursor_out','embedded','has_more','ids','invalid','parent_id','pinned_gap','reply_roots','saved','scope']
  or jsonb_typeof(pg->'embedded')is distinct from'boolean' or jsonb_typeof(pg->'reply_roots')is distinct from'object' or (pg->>'scope'='root'and pg->'parent_id'is distinct from'null'::jsonb) or (pg->>'scope'='reply'and coalesce(pg->>'parent_id','')!~'^[a-f0-9]{24}$')
  or pg->>'content_id' is distinct from p_record->>'content_id' or coalesce(pg->>'scope','') not in('root','reply')or jsonb_typeof(pg->'ids')is distinct from'array'
  or jsonb_typeof(pg->'saved')is distinct from'boolean'or jsonb_typeof(pg->'checkpoint_committed')is distinct from'boolean'
  or jsonb_typeof(pg->'has_more')is distinct from'boolean'or jsonb_typeof(pg->'invalid')is distinct from'boolean'or jsonb_typeof(pg->'pinned_gap')is distinct from'boolean'
  then raise exception 'invalid_comment_pages';end if;
  if jsonb_array_length(pg->'ids')<>(select count(distinct value)from jsonb_array_elements_text(pg->'ids')) or (pg->>'scope'='reply'and not reply) or length(pg->>'cursor_in')>512 or length(pg->>'cursor_out')>512 then raise exception 'invalid_comment_pages';end if;
  chain:=(pg->>'scope')||':'||coalesce(pg->>'parent_id','');last:=chains->chain;
  if last is not null and pg->'cursor_in' is distinct from last->'cursor_out'then raise exception 'invalid_comment_pages';end if;
  if last is not null and last->'has_more'='false'::jsonb then raise exception 'invalid_comment_pages';end if;
  if jsonb_typeof(pg->'cursor_in')not in('null','string')or jsonb_typeof(pg->'cursor_out')is distinct from'string' or exists(select from jsonb_array_elements(pg->'ids')e where jsonb_typeof(e)is distinct from'string' or(e#>>'{}')!~'^[a-f0-9]{24}$')then raise exception 'invalid_comment_pages';end if;
  chains:=jsonb_set(chains,array[chain],pg);
  if pg->'saved'='false'::jsonb and coverage not in('partial','unknown')then raise exception 'comment_capture_incomplete';end if;
  if pg->'saved'='true'::jsonb then
  for x in select value from jsonb_array_elements_text(pg->'ids')loop
   if not x.value=any(page_ids)then page_ids:=array_append(page_ids,x.value);end if;
   if not x.value=any(ids)then raise exception 'comment_capture_pages_mismatch';end if;
   if not exists(select from crowd_observation.receipts cr where cr.user_id=p_user and cr.parent_request=p_parent and cr.kind='pro_comment'and cr.result->>'comment_id'=x.value
    and(case when pg->>'scope'='root' then cr.data#>>'{pro_payload,record,parent_comment_id}'='' else cr.data#>>'{pro_payload,record,parent_comment_id}'=pg->>'parent_id'end))then raise exception 'comment_capture_parent_mismatch';end if;
  end loop;
  end if;
  if coverage='exhausted'and(pg->'saved'is distinct from'true'::jsonb or pg->'invalid'is distinct from'false'::jsonb or pg->'pinned_gap'is distinct from'false'::jsonb or(pg->>'scope'='root'and pg->'checkpoint_committed'is distinct from'true'::jsonb))then raise exception 'comment_capture_incomplete';end if;
 end loop;
 if not chains?'root:'or cardinality(page_ids)<>cardinality(ids)then raise exception 'comment_capture_pages_mismatch';end if;
 if coverage='exhausted' then
  for x in select value from jsonb_each(chains)loop if x.value->'has_more'is distinct from'false'::jsonb then raise exception 'comment_capture_incomplete';end if;end loop;
  for pg in select value from jsonb_array_elements(p_record->'pages')where value->>'scope'='root'loop
   if cardinality(root_cursors)=0 and pg->>'cursor_in'is distinct from'' then raise exception 'comment_capture_incomplete';end if;
   if coalesce(pg->>'cursor_in','')=any(root_cursors)or exists(select from jsonb_array_elements_text(pg->'ids')e where e.value=any(root_ids))then raise exception 'comment_capture_incomplete';end if;
   root_cursors:=array_append(root_cursors,pg->>'cursor_in');
   root_ids:=root_ids||array(select jsonb_array_elements_text(pg->'ids'));
   if (select count(*)from jsonb_object_keys(pg->'reply_roots'))<>jsonb_array_length(pg->'ids')or exists(select from jsonb_object_keys(pg->'reply_roots')k where not (pg->'ids')?k)then raise exception 'comment_capture_incomplete';end if;
   if reply and jsonb_typeof(pg->'reply_cursor_start')is distinct from'object'then raise exception 'comment_capture_incomplete';end if;
   for x in select key,value from jsonb_each(pg->'reply_roots')loop
    if jsonb_typeof(x.value)is distinct from'number'or x.value::text!~'^[0-9]{1,9}$'then raise exception 'comment_capture_incomplete';end if;
    reply_expected:=x.value::text::bigint;
    if reply then
     select count(e.value),count(distinct e.value)into reply_count,reply_unique from jsonb_array_elements(p_record->'pages')q cross join lateral jsonb_array_elements_text(q.value->'ids')e where q.value->>'scope'='reply'and q.value->>'parent_id'=x.key;
     select value into reply_first from jsonb_array_elements(p_record->'pages')where value->>'scope'='reply'and value->>'parent_id'=x.key limit 1;
     if reply_count<>reply_expected or reply_unique<>reply_expected or(reply_expected=0 and reply_first is not null)or(reply_expected>0 and reply_first is null)then raise exception 'comment_capture_incomplete';end if;
     if reply_first is not null and reply_first->'embedded'='false'::jsonb and reply_first->'cursor_in'is distinct from(pg->'reply_cursor_start')->x.key then raise exception 'comment_capture_incomplete';end if;
    end if;
   end loop;
  end loop;
  if exists(select from jsonb_array_elements(p_record->'pages')q where q.value->>'scope'='reply'and not(q.value->>'parent_id')=any(root_ids))then raise exception 'comment_capture_incomplete';end if;
 end if;
end $$;

create function public.crowd_v4_pro_comment_commit(p_task bigint,p_lease uuid,p_request uuid,p_parent_request uuid,p_payload jsonb,p_installation_id uuid)returns jsonb
language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid();t crowd_v4.tasks;old crowd_observation.receipts;par crowd_v4.receipts;data jsonb;result jsonb;
begin
 t:=crowd_observation.pro_scope(p_task,p_installation_id,null,false,true);data:=jsonb_build_object('task',p_task,'installation_id',p_installation_id,'pro_payload',p_payload);
 select * into old from crowd_observation.receipts where user_id=u and request=p_request;
 if old.request is not null then
  if old.kind<>'pro_comment_capture'or old.parent_request is distinct from p_parent_request or old.data is distinct from data then return jsonb_build_object('error','request_reused');end if;return old.result;
 end if;
 if not t.comments_capture or t.source_executor<>'mediacrawler_pro'then raise exception 'comments_not_enabled';end if;
 if p_lease is null or not exists(select from crowd_v4.node_runs where user_id=u and installation_id=p_installation_id and task_id=p_task and lease_token=p_lease)then raise exception 'lease_lost';end if;
 if not exists(select from crowd_v4.participants where user_id=u and status='approved'and consent='crowd-public-v4')then raise exception 'approval_required';end if;
 par:=crowd_observation.pro_comment_validate(p_task,p_installation_id,u,p_parent_request,p_request,p_payload,'pro_comment_capture');
 perform crowd_observation.pro_comment_capture_check(u,p_task,p_installation_id,p_parent_request,p_payload->'record');
 result:=jsonb_build_object('request',p_request,'gate','comment_capture_received','inserted',true,'duplicate',false,'parent_request',p_parent_request,
 'note_id',p_payload#>>'{record,content_id}','comment_id',null,'record_hash',p_payload#>>'{record,record_hash}','source_kind','mediacrawler_pro','reward_eligible',false,'created_at',to_char(clock_timestamp() at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 insert into crowd_observation.receipts(user_id,request,parent_request,kind,data,result)values(u,p_request,p_parent_request,'pro_comment_capture',data,result);return result;
end $$;

CREATE OR REPLACE FUNCTION public.crowd_v4_pro_guard(p_task bigint, p_lease uuid, p_action text, p_note text, p_installation_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare t crowd_v4.tasks;r jsonb;
begin
 if p_lease is null then raise exception 'lease_lost';end if;
 if p_action is null or p_action not in ('control','search','detail','comment','captcha','rate_limit') or p_action in ('detail','comment') and (p_note is null or p_note!~'^[a-f0-9]{24}$') then raise exception 'invalid_action';end if;
 t:=crowd_observation.pro_scope(p_task,p_installation_id,p_lease,p_action in ('search','detail','comment'));
 if t.source_executor<>'mediacrawler_pro' then raise exception 'pro_not_selected';end if;
 if p_action in ('search','detail','comment') and t.received>=t.target then return jsonb_build_object('error','task_full');end if;
 if p_action='comment' and not t.comments_capture then raise exception 'comments_not_enabled';end if;
 r:=crowd_observation.pro_guard_base(p_action,p_task,p_note);
 return r||jsonb_build_object('source_executor','mediacrawler_pro','reward_eligible',false);
end $function$;

CREATE OR REPLACE FUNCTION public.crowd_v4_pro_finish(p_task bigint, p_lease uuid, p_installation_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare t crowd_v4.tasks;b record;c crowd_observation.receipts;n integer:=0;
begin
 t:=crowd_observation.pro_scope(p_task,p_installation_id,p_lease);
 if t.source_executor<>'mediacrawler_pro' then raise exception 'pro_not_selected';end if;
 if t.comments_capture then
  for b in select request,payload from crowd_v4.receipts where user_id=auth.uid() and payload->>'task'=p_task::text and payload->>'installation_id'=p_installation_id::text and payload#>>'{pro_payload,schema}'='crowd-participant-pro-v1' and result->>'gate'='received' and result->'inserted'='true'::jsonb and result->'duplicate'='false'::jsonb loop
   n:=n+1;
   select * into c from crowd_observation.receipts where user_id=auth.uid() and parent_request=b.request and kind='pro_comment_capture';
   if c.request is null then return jsonb_build_object('error','comments_incomplete','source_executor','mediacrawler_pro','reward_eligible',false);end if;
   perform crowd_observation.pro_comment_validate(p_task,p_installation_id,auth.uid(),b.request,c.request,c.data->'pro_payload','pro_comment_capture');
   perform crowd_observation.pro_comment_capture_check(auth.uid(),p_task,p_installation_id,b.request,c.data#>'{pro_payload,record}');
   if c.data#>>'{pro_payload,record,coverage,coverage}' is distinct from 'exhausted' then return jsonb_build_object('error','comments_incomplete','source_executor','mediacrawler_pro','reward_eligible',false);end if;
  end loop;
  if n<>t.received or n=0 then return jsonb_build_object('error','comments_incomplete','source_executor','mediacrawler_pro','reward_eligible',false);end if;
 end if;
 return public.crowd_v4_finish(p_task,p_lease)||jsonb_build_object('source_executor','mediacrawler_pro','reward_eligible',false);
end $function$;

create function crowd_observation.pro_comment_feed_rows(p_task bigint,p_user uuid,p_installation_id uuid,p_kind text) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare r crowd_observation.receipts;par crowd_v4.receipts;rows jsonb:='[]';stamp timestamptz;
begin
 if p_kind not in ('pro_comment','pro_comment_capture') then raise exception 'participant_receipt_feed_invalid';end if;
 for r in select * from crowd_observation.receipts where user_id=p_user and data->>'task'=p_task::text and data->>'installation_id'=p_installation_id::text and kind=p_kind order by (result->>'created_at')::timestamptz,request loop
  par:=crowd_observation.pro_comment_validate(p_task,p_installation_id,p_user,r.parent_request,r.request,r.data->'pro_payload',r.kind);
  if r.kind='pro_comment_capture' then perform crowd_observation.pro_comment_capture_check(p_user,p_task,p_installation_id,r.parent_request,r.data#>'{pro_payload,record}');end if;
  if r.data-array['task','installation_id','pro_payload']<>'{}'::jsonb or not r.data?&array['task','installation_id','pro_payload']
   or r.result-array['request','gate','inserted','duplicate','parent_request','note_id','comment_id','record_hash','source_kind','reward_eligible','created_at']<>'{}'::jsonb
   or not r.result?&array['request','gate','inserted','duplicate','parent_request','note_id','comment_id','record_hash','source_kind','reward_eligible','created_at']
   or r.result->>'request' is distinct from r.request::text or r.result->>'parent_request' is distinct from r.parent_request::text
   or r.result->>'gate' is distinct from (case r.kind when 'pro_comment' then 'comment_received' else 'comment_capture_received' end)
   or r.result->'inserted' is distinct from 'true'::jsonb or r.result->'duplicate' is distinct from 'false'::jsonb
   or r.result->>'note_id' is distinct from r.data#>>'{pro_payload,record,content_id}'
   or r.result->'comment_id' is distinct from (case r.kind when 'pro_comment' then r.data#>'{pro_payload,record,comment_id}' else 'null'::jsonb end)
   or r.result->>'record_hash' is distinct from r.data#>>'{pro_payload,record,record_hash}'
   or r.result->>'source_kind' is distinct from 'mediacrawler_pro' or r.result->'reward_eligible' is distinct from 'false'::jsonb
   or jsonb_typeof(r.result->'created_at') is distinct from 'string' then raise exception 'participant_receipt_feed_invalid';end if;
  stamp:=(r.result->>'created_at')::timestamptz;if stamp is null then raise exception 'participant_receipt_feed_invalid';end if;
  rows:=rows||jsonb_build_array(jsonb_build_object('request',r.request,'parent_request',r.parent_request,'created_at',stamp,'pro_payload',r.data->'pro_payload','receipt',r.result));
 end loop;return rows;
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
  )select * from last_per_group where cursor_time is null or (created_at,request,task_id,user_id,installation_id,dispatch_id)>(cursor_time,cursor_request,cursor_task,cursor_user,cursor_install,cursor_dispatch)
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

revoke all on function crowd_observation.pro_comment_parent(bigint,uuid,uuid,uuid,uuid),crowd_observation.pro_comment_validate(bigint,uuid,uuid,uuid,uuid,jsonb,text),crowd_observation.pro_comment_capture_check(uuid,bigint,uuid,uuid,jsonb),crowd_observation.pro_comment_feed_rows(bigint,uuid,uuid,text) from public,anon,authenticated,service_role;
revoke all on function public.crowd_v4_pro_comment_submit(bigint,uuid,uuid,uuid,jsonb,uuid),public.crowd_v4_pro_comment_commit(bigint,uuid,uuid,uuid,jsonb,uuid),public.crowd_v4_pro_comment_receipt(bigint,uuid,uuid) from public,anon;
grant execute on function public.crowd_v4_pro_comment_submit(bigint,uuid,uuid,uuid,jsonb,uuid),public.crowd_v4_pro_comment_commit(bigint,uuid,uuid,uuid,jsonb,uuid),public.crowd_v4_pro_comment_receipt(bigint,uuid,uuid) to authenticated,service_role;

commit;
