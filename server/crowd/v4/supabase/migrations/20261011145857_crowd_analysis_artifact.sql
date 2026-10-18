-- Analysis is a separate append-only owner artifact, never a machine capture/reward.
create table if not exists crowd_machine.analysis_artifacts (
 artifact_id uuid primary key default gen_random_uuid(),
 owner_scope text not null check(owner_scope='crowd-owner-main'),
 task_id uuid not null references crowd_machine.tasks,
 child_id uuid not null references crowd_machine.children,
 run_id uuid not null, lease_epoch integer not null check(lease_epoch>=1),
 local_run_id uuid not null, local_job_id uuid not null,
 idempotency_key text not null, artifact_hash text not null check(artifact_hash ~ '^[a-f0-9]{64}$'),
 payload jsonb not null, canonical_artifact text not null, receipt jsonb not null,
 created_at timestamptz not null default clock_timestamp(),
 unique(owner_scope,idempotency_key), unique(owner_scope,local_job_id)
);
alter table crowd_machine.analysis_artifacts enable row level security;
revoke all on crowd_machine.analysis_artifacts from public,anon,authenticated;
grant select,insert on crowd_machine.analysis_artifacts to service_role;
revoke update,delete on crowd_machine.analysis_artifacts from service_role;

create or replace function crowd_machine.analysis_artifact_immutable() returns trigger
language plpgsql security invoker set search_path='' as $$
begin raise exception 'artifact_immutable'; end;
$$;
do $$ begin
 if not exists(select 1 from pg_trigger where tgrelid='crowd_machine.analysis_artifacts'::regclass and tgname='analysis_artifact_immutable') then
  create trigger analysis_artifact_immutable before update or delete on crowd_machine.analysis_artifacts
  for each row execute function crowd_machine.analysis_artifact_immutable();
 end if;
end $$;
revoke all on function crowd_machine.analysis_artifact_immutable() from public,anon,authenticated;

create or replace function public.crowd_analysis_artifact_rpc(p_owner_scope text,p_actor_kind text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare
 a crowd_machine.analysis_artifacts%rowtype;
 c crowd_machine.children%rowtype;
 t crowd_machine.tasks%rowtype;
 claim crowd_machine.claims%rowtype;
 ref jsonb; z crowd_machine.captures%rowtype;
 content_identity text; body_seen boolean:=false; receipt jsonb; semantic jsonb;
 body_identity text; record_identity text; known_type text; record_type text;
begin
 if p_owner_scope is distinct from 'crowd-owner-main' or p_actor_kind is distinct from 'owner' then raise exception 'principal_denied'; end if;
 if p_action='artifact_get' then
  if jsonb_typeof(p_payload) is distinct from 'object' or not(p_payload ? 'artifact_id') or p_payload-array['artifact_id']<>'{}'::jsonb then raise exception 'invalid_artifact'; end if;
  select * into a from crowd_machine.analysis_artifacts where artifact_id=(p_payload->>'artifact_id')::uuid and owner_scope=p_owner_scope;
  if a.artifact_id is null then raise exception 'artifact_not_found'; end if;
  return jsonb_build_object('receipt',a.receipt,'artifact',a.payload);
 end if;
 if p_action is distinct from 'artifact_put' or jsonb_typeof(p_payload) is distinct from 'object' then raise exception 'invalid_artifact'; end if;
 if not(p_payload ?& array['idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','source_refs','local_job_id','input_snapshot_hash','full_result_file_sha256','report_sha256','provider','provider_version','model_version','model_version_status','coverage','report_json','canonical_artifact','artifact_hash'])
  or p_payload-array['idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','source_refs','local_job_id','input_snapshot_hash','full_result_file_sha256','report_sha256','provider','provider_version','model_version','model_version_status','coverage','report_json','canonical_artifact','artifact_hash']<>'{}'::jsonb
  or jsonb_typeof(p_payload->'lease_epoch') is distinct from 'number' or coalesce(p_payload->>'lease_epoch','') !~ '^[1-9][0-9]{0,9}$'
  or p_payload->'model_version' is distinct from 'null'::jsonb or p_payload->>'model_version_status' is distinct from 'not_recorded_by_local_provider'
  or coalesce(p_payload->>'artifact_hash','') !~ '^[a-f0-9]{64}$'
  or coalesce(p_payload->>'report_sha256','') !~ '^[a-f0-9]{64}$'
  or coalesce(p_payload->>'full_result_file_sha256','') !~ '^[a-f0-9]{64}$'
  or coalesce(p_payload->>'input_snapshot_hash','') !~ '^[a-f0-9]{64}$'
  or octet_length(p_payload->>'report_json')>200000
  or jsonb_typeof(p_payload->'source_refs') is distinct from 'array'
  or jsonb_array_length(p_payload->'source_refs') not between 1 and 2000 then raise exception 'invalid_artifact'; end if;
 semantic:=p_payload-array['canonical_artifact','artifact_hash'];
 if (p_payload->>'canonical_artifact')::jsonb is distinct from semantic
  or encode(sha256(convert_to('crowd-analysis-artifact-v1'||chr(10)||(p_payload->>'canonical_artifact'),'UTF8')),'hex') is distinct from p_payload->>'artifact_hash'
  or encode(sha256(convert_to(p_payload->>'report_json','UTF8')),'hex') is distinct from p_payload->>'report_sha256'
  or (p_payload->>'report_json')::jsonb->'full_analysis_coverage' is distinct from p_payload->'coverage'
  or p_payload->'coverage'->>'state' is distinct from 'all_selected_segments_analyzed'
  or p_payload->'coverage'->>'semantic_review' is distinct from 'not_reviewed'
  or p_payload->'coverage'->'automatic_retry' is distinct from 'false'::jsonb
  or p_payload->'coverage'->'batches_completed' is distinct from p_payload->'coverage'->'batches_total'
  or not(p_payload->'coverage' ?& array['state','batches_completed','batches_total','selected_segments','selected_characters','source_refs','semantic_review','automatic_retry'])
  or (p_payload->'coverage')-array['state','batches_completed','batches_total','selected_segments','selected_characters','source_refs','semantic_review','automatic_retry']<>'{}'::jsonb
  or jsonb_typeof(p_payload->'coverage'->'batches_total') is distinct from 'number'
  or coalesce(p_payload->'coverage'->>'batches_total','') !~ '^([1-9]|1[0-6])$'
  or jsonb_typeof(p_payload->'coverage'->'selected_segments') is distinct from 'number'
  or coalesce(p_payload->'coverage'->>'selected_segments','') !~ '^[1-9][0-9]{0,3}$'
  or (p_payload->'coverage'->>'selected_segments')::integer>8000
  or jsonb_typeof(p_payload->'coverage'->'selected_characters') is distinct from 'number'
  or coalesce(p_payload->'coverage'->>'selected_characters','') !~ '^[1-9][0-9]{0,5}$'
  or (p_payload->'coverage'->>'selected_characters')::integer>240000
  or jsonb_typeof(p_payload->'coverage'->'source_refs') is distinct from 'array'
  or jsonb_array_length(p_payload->'coverage'->'source_refs') is distinct from (p_payload->'coverage'->>'selected_segments')::integer
  or p_payload->>'report_json' ~* '(cookie|authorization|password|access_token|refresh_token|private_key|api_key|secret)[[:space:]]*[=:]'
  or p_payload->>'report_json' ~* '"(cookie|authorization|password|access_token|refresh_token|private_key|api_key|secret|input_snapshot|analysis_batches|batch_snapshot|audio|audio_base64)"[[:space:]]*:' then raise exception 'artifact_hash_conflict'; end if;
 if (select count(distinct r) from jsonb_array_elements_text(p_payload->'coverage'->'source_refs') r)<>(p_payload->'coverage'->>'selected_segments')::integer
  or exists(select 1 from jsonb_array_elements_text(p_payload->'coverage'->'source_refs') r where r !~ '^derived:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}:(0|[1-9][0-9]{0,3})$') then raise exception 'invalid_artifact_coverage'; end if;
 select * into t from crowd_machine.tasks where task_id=(p_payload->>'task_id')::uuid and owner_scope=p_owner_scope;
 select * into c from crowd_machine.children where child_id=(p_payload->>'child_id')::uuid and task_id=t.task_id;
 select * into claim from crowd_machine.claims where child_id=c.child_id and run_id=(p_payload->>'run_id')::uuid
  and lease_epoch=(p_payload->>'lease_epoch')::integer and local_run_id=(p_payload->>'local_run_id')::uuid;
 if t.task_id is null or c.child_id is null or claim.claim_id is null then raise exception 'artifact_source_binding_denied'; end if;
 if (select count(distinct r->>'capture_id') from jsonb_array_elements(p_payload->'source_refs') r)<>jsonb_array_length(p_payload->'source_refs') then raise exception 'artifact_source_binding_denied'; end if;
 for ref in select value from jsonb_array_elements(p_payload->'source_refs') loop
  select * into z from crowd_machine.captures where capture_id=(ref->>'capture_id')::uuid and owner_scope=p_owner_scope
   and task_id=t.task_id and child_id=c.child_id and run_id=claim.run_id and lease_epoch=claim.lease_epoch and worker_id=claim.worker_id;
  if z.capture_id is null or z.envelope_hash is distinct from ref->>'envelope_hash'
   or z.envelope->'record'->'origin'->>'run_id' is distinct from claim.local_run_id::text
   or z.receipt->>'status' is distinct from 'received'
   or z.receipt->>'capture_id' is distinct from z.capture_id::text or z.receipt->>'envelope_hash' is distinct from z.envelope_hash
   or z.receipt->>'task_id' is distinct from t.task_id::text or z.receipt->>'child_id' is distinct from c.child_id::text
   or z.receipt->>'run_id' is distinct from claim.run_id::text or z.receipt->'lease_epoch' is distinct from to_jsonb(claim.lease_epoch)
   or z.receipt->'reward_eligible' is distinct from 'false'::jsonb
   or coalesce(z.envelope->'record'->>'kind','') not in ('content','dynamic','comment')
   or z.envelope->'record'->>'platform' is distinct from c.platform
   or coalesce(z.envelope->'record'->>'content_id','')=''
   or z.envelope->'record'->'reward_eligible' is distinct from 'false'::jsonb
   or z.envelope->>'source_kind' is distinct from 'machine_api'
   or z.canonical_envelope::jsonb is distinct from z.envelope
   or encode(sha256(convert_to('crowd-machine-capture-v1'||chr(10)||z.canonical_envelope,'UTF8')),'hex') is distinct from z.envelope_hash then raise exception 'artifact_source_binding_denied'; end if;
  if content_identity is not null and content_identity is distinct from z.envelope->'record'->>'content_id' then raise exception 'artifact_source_binding_denied'; end if;
  content_identity:=z.envelope->'record'->>'content_id';
  if nullif(z.envelope->'record'->>'content_type','') is not null and nullif(z.envelope->'record'->>'source_content_type','') is not null
   and z.envelope->'record'->>'content_type' is distinct from z.envelope->'record'->>'source_content_type' then raise exception 'artifact_source_binding_denied'; end if;
  record_type:=coalesce(nullif(z.envelope->'record'->>'content_type',''),nullif(z.envelope->'record'->>'source_content_type',''));
  if known_type is not null and record_type is not null and known_type is distinct from record_type then raise exception 'artifact_source_binding_denied'; end if;
  known_type:=coalesce(known_type,record_type);
  if z.envelope->'record'->>'kind' in ('content','dynamic') then
   record_identity:=(z.envelope->'record'->>'kind')||':'||coalesce(record_type,'unknown');
   if body_identity is not null and body_identity is distinct from record_identity then raise exception 'artifact_source_binding_denied'; end if;
   body_identity:=record_identity;
  end if;
  body_seen:=body_seen or z.envelope->'record'->>'kind' in ('content','dynamic');
 end loop;
 if not body_seen then raise exception 'artifact_source_binding_denied'; end if;
 if (select count(*) from crowd_machine.captures src where src.owner_scope=p_owner_scope and src.task_id=t.task_id and src.child_id=c.child_id
  and src.worker_id=claim.worker_id and src.run_id=claim.run_id and src.lease_epoch=claim.lease_epoch
  and src.envelope->'record'->>'content_id'=content_identity and src.envelope->'record'->>'kind' in ('content','dynamic','comment'))<>jsonb_array_length(p_payload->'source_refs') then raise exception 'artifact_source_binding_denied'; end if;
 perform pg_advisory_xact_lock(hashtext(p_owner_scope||':analysis-artifacts'));
 select * into a from crowd_machine.analysis_artifacts where owner_scope=p_owner_scope and (idempotency_key=p_payload->>'idempotency_key' or local_job_id=(p_payload->>'local_job_id')::uuid);
 if a.artifact_id is not null then
  if a.artifact_hash is distinct from p_payload->>'artifact_hash' then raise exception 'artifact_conflict'; end if;
  return jsonb_build_object('receipt',a.receipt,'replayed',true);
 end if;
 a.artifact_id:=gen_random_uuid();a.created_at:=clock_timestamp();
 -- Compute immutable receipt before insertion; never update an artifact to add its receipt.
 receipt:=jsonb_build_object('artifact_id',a.artifact_id,'artifact_hash',p_payload->>'artifact_hash','artifact_kind','analysis_report','status','received',
  'task_id',t.task_id,'child_id',c.child_id,'run_id',claim.run_id,'lease_epoch',claim.lease_epoch,'local_run_id',claim.local_run_id,'local_job_id',p_payload->>'local_job_id',
  'source_refs',semantic->'source_refs','input_snapshot_hash',semantic->>'input_snapshot_hash','full_result_file_sha256',semantic->>'full_result_file_sha256',
  'report_sha256',semantic->>'report_sha256','provider',semantic->>'provider','provider_version',semantic->>'provider_version','model_version',semantic->'model_version','model_version_status',semantic->>'model_version_status','coverage',semantic->'coverage','coverage_basis','validated_local_full_analysis_metadata','reward_eligible',false,'received_at',a.created_at);
 insert into crowd_machine.analysis_artifacts(artifact_id,owner_scope,task_id,child_id,run_id,lease_epoch,local_run_id,local_job_id,idempotency_key,artifact_hash,payload,canonical_artifact,receipt,created_at)
 values(a.artifact_id,p_owner_scope,t.task_id,c.child_id,claim.run_id,claim.lease_epoch,claim.local_run_id,(p_payload->>'local_job_id')::uuid,p_payload->>'idempotency_key',p_payload->>'artifact_hash',semantic,p_payload->>'canonical_artifact',receipt,a.created_at);
 return jsonb_build_object('receipt',receipt,'replayed',false);
end;
$$;
revoke all on function public.crowd_analysis_artifact_rpc(text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.crowd_analysis_artifact_rpc(text,text,text,jsonb) to service_role;
