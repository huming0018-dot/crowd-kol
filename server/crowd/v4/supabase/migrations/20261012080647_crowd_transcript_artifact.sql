-- Full local transcripts are immutable owner artifacts, not model analyses or rewarded captures.
create table if not exists crowd_machine.transcript_artifacts (
 artifact_id uuid primary key default gen_random_uuid(), owner_scope text not null check(owner_scope='crowd-owner-main'),
 task_id uuid not null references crowd_machine.tasks, child_id uuid not null references crowd_machine.children,
 run_id uuid not null, lease_epoch integer not null check(lease_epoch>=1), local_run_id uuid not null, local_job_id uuid not null,
 idempotency_key text not null, artifact_hash text not null check(artifact_hash ~ '^[a-f0-9]{64}$'),
 payload jsonb not null, canonical_transcript text not null, receipt jsonb not null, created_at timestamptz not null default clock_timestamp(),
 unique(owner_scope,idempotency_key), unique(owner_scope,local_job_id)
);
alter table crowd_machine.transcript_artifacts enable row level security;
revoke all on crowd_machine.transcript_artifacts from public,anon,authenticated;
grant select,insert on crowd_machine.transcript_artifacts to service_role;
revoke update,delete on crowd_machine.transcript_artifacts from service_role;
create or replace function crowd_machine.transcript_artifact_immutable() returns trigger
language plpgsql security invoker set search_path='' as $$ begin raise exception 'transcript_immutable'; end; $$;
do $$ begin
 if not exists(select 1 from pg_trigger where tgrelid='crowd_machine.transcript_artifacts'::regclass and tgname='transcript_artifact_immutable') then
  create trigger transcript_artifact_immutable before update or delete on crowd_machine.transcript_artifacts for each row execute function crowd_machine.transcript_artifact_immutable();
 end if;
end $$;
revoke all on function crowd_machine.transcript_artifact_immutable() from public,anon,authenticated;

create or replace function public.crowd_transcript_artifact_rpc(p_owner_scope text,p_actor_kind text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare a crowd_machine.transcript_artifacts%rowtype; t crowd_machine.tasks%rowtype; c crowd_machine.children%rowtype;
 claim crowd_machine.claims%rowtype; z crowd_machine.captures%rowtype; ref jsonb; semantic jsonb; report jsonb; segment jsonb;
 receipt jsonb; body_kind text; body_type text; row_type text; chars integer:=0; joined text:=''; n integer:=0; duration numeric;
begin
 if p_owner_scope is distinct from 'crowd-owner-main' or p_actor_kind is distinct from 'owner' then raise exception 'principal_denied'; end if;
 if p_action='transcript_get' then
  if jsonb_typeof(p_payload) is distinct from 'object' or not ((p_payload ? 'artifact_id' and p_payload-array['artifact_id']='{}'::jsonb) or (p_payload ? 'local_job_id' and p_payload-array['local_job_id']='{}'::jsonb)) then raise exception 'invalid_transcript'; end if;
  select * into a from crowd_machine.transcript_artifacts where owner_scope=p_owner_scope and ((p_payload ? 'artifact_id' and artifact_id=(p_payload->>'artifact_id')::uuid) or (p_payload ? 'local_job_id' and local_job_id=(p_payload->>'local_job_id')::uuid));
  if a.artifact_id is null then raise exception 'transcript_not_found'; end if;
  return jsonb_build_object('receipt',a.receipt,'artifact',a.payload);
 end if;
 if p_action is distinct from 'transcript_put' or jsonb_typeof(p_payload) is distinct from 'object'
  or not(p_payload ?& array['idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','source_refs','report_sha256','report_json','canonical_transcript','artifact_hash'])
  or p_payload-array['idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','source_refs','report_sha256','report_json','canonical_transcript','artifact_hash']<>'{}'::jsonb
  or jsonb_typeof(p_payload->'lease_epoch') is distinct from 'number' or coalesce(p_payload->>'lease_epoch','') !~ '^[1-9][0-9]{0,9}$'
  or coalesce(p_payload->>'artifact_hash','') !~ '^[a-f0-9]{64}$' or coalesce(p_payload->>'report_sha256','') !~ '^[a-f0-9]{64}$'
  or p_payload->>'idempotency_key' is distinct from 'transcript:'||(p_payload->>'local_job_id')
  or jsonb_typeof(p_payload->'source_refs') is distinct from 'array' then raise exception 'invalid_transcript'; end if;
 if jsonb_array_length(p_payload->'source_refs') not between 1 and 2000 or octet_length(p_payload->>'report_json')>200000 then raise exception 'transcript_report_limit'; end if;
 semantic:=p_payload-array['canonical_transcript','artifact_hash'];report:=(p_payload->>'report_json')::jsonb;
 if (p_payload->>'canonical_transcript')::jsonb is distinct from semantic
  or encode(sha256(convert_to('crowd-transcript-artifact-v1'||chr(10)||(p_payload->>'canonical_transcript'),'UTF8')),'hex') is distinct from p_payload->>'artifact_hash'
  or encode(sha256(convert_to(p_payload->>'report_json','UTF8')),'hex') is distinct from p_payload->>'report_sha256' then raise exception 'transcript_hash_conflict'; end if;
 if jsonb_typeof(report) is distinct from 'object' or report->>'schema' is distinct from 'crowd-transcript-report-v1'
  or not(report ?& array['schema','job_id','audio_source_job_id','local_run_id','platform','content_id','entity_ref','asset_sha256','input_hash','full_result_file_sha256','duration_seconds','segments','text_sha256','segment_count','character_count','semantic_review','cer','human_groundtruth','diagnostics_sha256','model_manifest_sha256','processing_profile','processor','text_revision'])
  or report-array['schema','job_id','audio_source_job_id','local_run_id','platform','content_id','entity_ref','asset_sha256','input_hash','full_result_file_sha256','duration_seconds','segments','text_sha256','segment_count','character_count','semantic_review','cer','human_groundtruth','diagnostics_sha256','model_manifest_sha256','processing_profile','processor','text_revision']<>'{}'::jsonb
  or report->>'job_id' is distinct from p_payload->>'local_job_id' or report->>'local_run_id' is distinct from p_payload->>'local_run_id'
  or report->>'semantic_review' is distinct from 'not_reviewed' or report->'cer' is distinct from 'null'::jsonb or report->'human_groundtruth' is distinct from 'false'::jsonb
  or report->'segments' is null or jsonb_typeof(report->'segments') is distinct from 'array'
  or coalesce(report->>'asset_sha256','') !~ '^[a-f0-9]{64}$' or coalesce(report->>'full_result_file_sha256','') !~ '^[a-f0-9]{64}$'
  or coalesce(report->>'input_hash','') !~ '^[a-f0-9]{64}$' or coalesce(report->>'text_sha256','') !~ '^[a-f0-9]{64}$'
  or jsonb_typeof(report->'duration_seconds') is distinct from 'number' then raise exception 'invalid_transcript'; end if;
 if p_payload->>'report_json' ~* '(cookie|authorization|password|access_token|refresh_token|private_key|api_key|secret)[[:space:]]*[=:]'
  or p_payload->>'report_json' ~* '"(cookie|authorization|password|access_token|refresh_token|private_key|api_key|secret|audio|audio_base64|input_snapshot)"[[:space:]]*:' then raise exception 'sensitive_transcript'; end if;
 duration:=(report->>'duration_seconds')::numeric;
 if report->>'platform'='zhihu' and not exists(select 1 from unnest(array['answer','article','zvideo']) kind where report->>'entity_ref'='zhihu:content:'||(report->>'content_id')||':'||kind) then raise exception 'invalid_transcript'; end if;
 if duration<=0 or duration>7200 or jsonb_array_length(report->'segments') not between 1 and 8000 then raise exception 'invalid_transcript'; end if;
 for segment in select value from jsonb_array_elements(report->'segments') loop
  if jsonb_typeof(segment) is distinct from 'object' or not(segment ?& array['start','end','text']) or segment-array['start','end','text','chunk_index']<>'{}'::jsonb
   or jsonb_typeof(segment->'start') is distinct from 'number' or jsonb_typeof(segment->'end') is distinct from 'number' or jsonb_typeof(segment->'text') is distinct from 'string'
   or btrim(segment->>'text')='' or length(segment->>'text')>24000 then raise exception 'invalid_transcript'; end if;
  if (segment->>'start')::numeric<0 or (segment->>'end')::numeric<(segment->>'start')::numeric or (segment->>'end')::numeric>duration then raise exception 'invalid_transcript'; end if;
  if segment ? 'chunk_index' and (jsonb_typeof(segment->'chunk_index') is distinct from 'number' or coalesce(segment->>'chunk_index','') !~ '^(0|[1-9][0-9]{0,2})$' or (segment->>'chunk_index')::integer>=512) then raise exception 'invalid_transcript'; end if;
  if n>0 then joined:=joined||chr(10); end if;joined:=joined||(segment->>'text');n:=n+1;chars:=chars+length(segment->>'text');
 end loop;
 if report->'segment_count' is distinct from to_jsonb(n) or report->'character_count' is distinct from to_jsonb(chars) or chars>240000
  or encode(sha256(convert_to(joined,'UTF8')),'hex') is distinct from report->>'text_sha256' then raise exception 'transcript_hash_conflict'; end if;
 select * into t from crowd_machine.tasks where task_id=(p_payload->>'task_id')::uuid and owner_scope=p_owner_scope;
 select * into c from crowd_machine.children where child_id=(p_payload->>'child_id')::uuid and task_id=t.task_id;
 select * into claim from crowd_machine.claims where child_id=c.child_id and run_id=(p_payload->>'run_id')::uuid and lease_epoch=(p_payload->>'lease_epoch')::integer and local_run_id=(p_payload->>'local_run_id')::uuid;
 if t.task_id is null or c.child_id is null or claim.claim_id is null then raise exception 'transcript_source_binding_denied'; end if;
 if (select count(distinct value->>'capture_id') from jsonb_array_elements(p_payload->'source_refs'))<>jsonb_array_length(p_payload->'source_refs') then raise exception 'transcript_source_binding_denied'; end if;
 for ref in select value from jsonb_array_elements(p_payload->'source_refs') loop
  select * into z from crowd_machine.captures where capture_id=(ref->>'capture_id')::uuid and owner_scope=p_owner_scope and task_id=t.task_id and child_id=c.child_id and run_id=claim.run_id and lease_epoch=claim.lease_epoch and worker_id=claim.worker_id;
  if z.capture_id is null or z.envelope_hash is distinct from ref->>'envelope_hash' or z.envelope->'record'->'origin'->>'run_id' is distinct from claim.local_run_id::text
   or z.receipt->>'status' is distinct from 'received' or z.receipt->>'capture_id' is distinct from z.capture_id::text or z.receipt->>'envelope_hash' is distinct from z.envelope_hash
   or z.receipt->>'task_id' is distinct from t.task_id::text or z.receipt->>'child_id' is distinct from c.child_id::text or z.receipt->>'run_id' is distinct from claim.run_id::text
   or z.receipt->'lease_epoch' is distinct from to_jsonb(claim.lease_epoch) or z.receipt->'reward_eligible' is distinct from 'false'::jsonb
   or z.envelope->>'source_kind' is distinct from 'machine_api' or z.envelope->'record'->'reward_eligible' is distinct from 'false'::jsonb
   or z.canonical_envelope::jsonb is distinct from z.envelope or encode(sha256(convert_to('crowd-machine-capture-v1'||chr(10)||z.canonical_envelope,'UTF8')),'hex') is distinct from z.envelope_hash
   or coalesce(z.envelope->'record'->>'kind','') not in ('content','dynamic') or z.envelope->'record'->>'content_id' is distinct from report->>'content_id'
   or z.envelope->'record'->>'platform' is distinct from report->>'platform' or report->>'platform' is distinct from (case c.platform when 'bili' then 'bilibili' when 'dy' then 'douyin' when 'ks' then 'kuaishou' when 'wb' then 'weibo' when 'xhs' then 'xiaohongshu' when 'tieba' then 'tieba' when 'zhihu' then 'zhihu' end) then raise exception 'transcript_source_binding_denied'; end if;
  if nullif(z.envelope->'record'->>'content_type','') is not null and nullif(z.envelope->'record'->>'source_content_type','') is not null and z.envelope->'record'->>'content_type' is distinct from z.envelope->'record'->>'source_content_type' then raise exception 'transcript_source_binding_denied'; end if;
  row_type:=coalesce(nullif(z.envelope->'record'->>'content_type',''),nullif(z.envelope->'record'->>'source_content_type',''));
  if body_kind is not null and body_kind is distinct from z.envelope->'record'->>'kind' or body_type is not null and row_type is not null and body_type is distinct from row_type then raise exception 'transcript_source_binding_denied'; end if;
  body_kind:=z.envelope->'record'->>'kind';body_type:=coalesce(body_type,row_type);
 end loop;
 if report->'entity_ref' is distinct from 'null'::jsonb and report->>'entity_ref' is distinct from (report->>'platform')||':'||body_kind||':'||(report->>'content_id')||(case when report->>'platform'='zhihu' and body_kind='content' and body_type in ('answer','article','zvideo') then ':'||body_type else '' end) then raise exception 'transcript_source_binding_denied'; end if;
 if (select count(*) from crowd_machine.captures src where src.owner_scope=p_owner_scope and src.child_id=c.child_id and src.run_id=claim.run_id and src.lease_epoch=claim.lease_epoch and src.worker_id=claim.worker_id and src.envelope->'record'->>'content_id'=report->>'content_id' and src.envelope->'record'->>'kind' in ('content','dynamic'))<>jsonb_array_length(p_payload->'source_refs') then raise exception 'transcript_source_binding_denied'; end if;
 perform pg_advisory_xact_lock(hashtext(p_owner_scope||':transcript-artifacts'));
 select * into a from crowd_machine.transcript_artifacts where owner_scope=p_owner_scope and (idempotency_key=p_payload->>'idempotency_key' or local_job_id=(p_payload->>'local_job_id')::uuid);
 if a.artifact_id is not null then
  if a.artifact_hash is distinct from p_payload->>'artifact_hash' then raise exception 'transcript_conflict'; end if;
  return jsonb_build_object('receipt',a.receipt,'replayed',true);
 end if;
 a.artifact_id:=gen_random_uuid();a.created_at:=clock_timestamp();
 receipt:=semantic-array['idempotency_key','report_json']||jsonb_build_object('artifact_id',a.artifact_id,'artifact_hash',p_payload->>'artifact_hash','artifact_kind','transcript_report','status','received','reward_eligible',false,'text_sha256',report->>'text_sha256','asset_sha256',report->>'asset_sha256','full_result_file_sha256',report->>'full_result_file_sha256','segment_count',n,'character_count',chars,'semantic_review','not_reviewed','received_at',a.created_at);
 insert into crowd_machine.transcript_artifacts(artifact_id,owner_scope,task_id,child_id,run_id,lease_epoch,local_run_id,local_job_id,idempotency_key,artifact_hash,payload,canonical_transcript,receipt,created_at) values(a.artifact_id,p_owner_scope,t.task_id,c.child_id,claim.run_id,claim.lease_epoch,claim.local_run_id,(p_payload->>'local_job_id')::uuid,p_payload->>'idempotency_key',p_payload->>'artifact_hash',semantic,p_payload->>'canonical_transcript',receipt,a.created_at);
 return jsonb_build_object('receipt',receipt,'replayed',false);
end; $$;
revoke all on function public.crowd_transcript_artifact_rpc(text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.crowd_transcript_artifact_rpc(text,text,text,jsonb) to service_role;
