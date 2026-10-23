-- Additive private media receipts. Storage bucket is created only by explicit Owner action.
create table if not exists crowd_machine.video_artifacts (
 artifact_id uuid primary key default gen_random_uuid(),owner_scope text not null check(owner_scope='crowd-owner-main'),
 worker_id uuid not null references crowd_machine.workers,task_id uuid not null references crowd_machine.tasks,
 child_id uuid not null references crowd_machine.children,run_id uuid not null,lease_epoch integer not null,
 local_run_id uuid not null,local_job_id uuid not null,capture_id uuid not null references crowd_machine.captures,
 idempotency_key text not null,manifest_hash text not null check(manifest_hash ~ '^[a-f0-9]{64}$'),
 manifest jsonb not null,canonical_manifest text not null,bucket_id text not null check(bucket_id='crowd-machine-media'),
 object_path text unique not null,state text not null default 'pending' check(state in ('pending','ready')),
 receipt jsonb,created_at timestamptz not null default clock_timestamp(),verified_at timestamptz,
 unique(owner_scope,idempotency_key),unique(owner_scope,local_job_id),
 check((state='ready')=(receipt is not null)),check((state='ready')=(verified_at is not null))
);
alter table crowd_machine.video_artifacts enable row level security;
revoke all on crowd_machine.video_artifacts from public,anon,authenticated;
grant select,insert on crowd_machine.video_artifacts to service_role;
revoke update,delete on crowd_machine.video_artifacts from service_role;
create or replace function crowd_machine.guard_video_artifacts() returns trigger language plpgsql set search_path=pg_catalog as $$
begin
 if TG_OP='DELETE' or OLD.state='ready' or NEW.state<>'ready' or (to_jsonb(NEW)-array['state','receipt','verified_at']) is distinct from (to_jsonb(OLD)-array['state','receipt','verified_at']) then raise exception 'media_immutable';end if;
 return NEW;
end;$$;
drop trigger if exists crowd_video_immutable on crowd_machine.video_artifacts;
create trigger crowd_video_immutable before update or delete on crowd_machine.video_artifacts for each row execute function crowd_machine.guard_video_artifacts();
create or replace function public.crowd_video_artifact_rpc(p_owner_scope text,p_actor_kind text,p_worker_hash text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security definer set search_path=pg_catalog,crowd_machine as $$
declare a crowd_machine.video_artifacts;w crowd_machine.workers;z crowd_machine.captures;c crowd_machine.children;
 cl crowd_machine.claims;t crowd_machine.tasks;semantic jsonb;k text;v_receipt jsonb;replayed boolean:=false;
begin
 if p_owner_scope is distinct from 'crowd-owner-main' or p_actor_kind not in ('owner','worker') or p_actor_kind is null then raise exception 'principal_denied';end if;
 if p_actor_kind='worker' then
  select * into w from crowd_machine.workers where token_hash=p_worker_hash and owner_scope=p_owner_scope and enabled and expires_at>clock_timestamp();
  if w.worker_id is null then raise exception 'worker_revoked';end if;
 end if;
 if p_action in ('media_lookup','media_get','media_commit') then
  select * into a from crowd_machine.video_artifacts where artifact_id=(p_payload->>'artifact_id')::uuid and owner_scope=p_owner_scope for update;
  if a.artifact_id is null or p_actor_kind='worker' and a.worker_id is distinct from w.worker_id then raise exception 'media_not_found';end if;
  if p_action='media_commit' then
   if p_payload->>'verified_sha256' is distinct from a.manifest->>'asset_sha256'
    or p_payload->'verified_bytes' is distinct from a.manifest->'asset_bytes' then raise exception 'media_object_mismatch';end if;
  end if;
  if p_action='media_commit' and a.state='pending' then
   v_receipt:=jsonb_build_object('artifact_id',a.artifact_id,'artifact_kind','video_object','status','received','verification','server_storage_bytes_sha256',
    'manifest_hash',a.manifest_hash,'bucket_id',a.bucket_id,'object_path',a.object_path,'manifest',a.manifest,
    'reward_eligible',false,'received_at',clock_timestamp(),'semantic_review','not_reviewed');
   update crowd_machine.video_artifacts set state='ready',receipt=v_receipt,verified_at=clock_timestamp() where artifact_id=a.artifact_id;
   a.state:='ready';a.receipt:=v_receipt;
  elsif p_action='media_commit' then replayed:=true;
  end if;
  return jsonb_build_object('artifact_id',a.artifact_id,'state',a.state,'bucket_id',a.bucket_id,'object_path',a.object_path,'manifest',a.manifest,'manifest_hash',a.manifest_hash,'receipt',a.receipt,'replayed',replayed);
 end if;
 if p_action is distinct from 'media_prepare' then raise exception 'invalid_request';end if;
 semantic:=p_payload-'canonical_manifest'-'manifest_hash';
 if jsonb_typeof(semantic->'content_id') is distinct from 'string' or jsonb_typeof(semantic->'idempotency_key') is distinct from 'string' or (select count(*) from jsonb_object_keys(semantic))<>19 or not semantic ?& array['idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','platform','content_id','capture_id','envelope_hash','asset_sha256','asset_bytes','duration_ms','source_duration_ms','source_asset_sha256','source_file_sha256','source_reference_sha256','result_file_sha256']
  or octet_length(p_payload->>'canonical_manifest')>10000 or (p_payload->>'canonical_manifest')::jsonb is distinct from semantic
  or encode(sha256(convert_to('crowd-media-video-v1'||chr(10)||(p_payload->>'canonical_manifest'),'UTF8')),'hex') is distinct from p_payload->>'manifest_hash'
  or semantic->>'idempotency_key' is distinct from 'video:'||(semantic->>'local_job_id') or semantic->>'platform' is distinct from 'douyin'
  or semantic->>'content_id' !~ '^[0-9]{1,30}$' then raise exception 'invalid_media_manifest';end if;
 foreach k in array array['lease_epoch','asset_bytes','duration_ms','source_duration_ms'] loop
  if jsonb_typeof(semantic->k) is distinct from 'number' or semantic->>k !~ '^[0-9]{1,10}$' then raise exception 'invalid_media_manifest';end if;
 end loop;
 if (semantic->>'lease_epoch')::bigint not between 1 and 2147483647 or (semantic->>'asset_bytes')::bigint not between 12 and 52428800
  or (semantic->>'duration_ms')::bigint not between 1 and 7200000 or (semantic->>'source_duration_ms')::bigint not between 1 and 7200000
  or abs((semantic->>'duration_ms')::bigint-(semantic->>'source_duration_ms')::bigint)>250 then raise exception 'invalid_media_manifest';end if;
 foreach k in array array['asset_sha256','envelope_hash','source_asset_sha256','source_file_sha256','source_reference_sha256','result_file_sha256'] loop
  if jsonb_typeof(semantic->k) is distinct from 'string' or semantic->>k !~ '^[a-f0-9]{64}$' then raise exception 'invalid_media_manifest';end if;
 end loop;
 select * into z from crowd_machine.captures where capture_id=(semantic->>'capture_id')::uuid and owner_scope=p_owner_scope;
 select * into c from crowd_machine.children where child_id=z.child_id;
 select * into t from crowd_machine.tasks where task_id=z.task_id and owner_scope=p_owner_scope;
 select * into cl from crowd_machine.claims where worker_id=z.worker_id and child_id=z.child_id and run_id=z.run_id and lease_epoch=z.lease_epoch;
 if z.capture_id is null or c.child_id is null or t.task_id is null or cl.claim_id is null
  or p_actor_kind='worker' and z.worker_id is distinct from w.worker_id
  or z.task_id::text is distinct from semantic->>'task_id' or z.child_id::text is distinct from semantic->>'child_id'
  or z.run_id::text is distinct from semantic->>'run_id' or to_jsonb(z.lease_epoch) is distinct from semantic->'lease_epoch'
  or cl.local_run_id::text is distinct from semantic->>'local_run_id' or z.envelope_hash is distinct from semantic->>'envelope_hash'
  or c.platform is distinct from 'dy' or z.envelope->'record'->>'platform' is distinct from 'douyin'
  or z.envelope->'record'->>'kind' is distinct from 'content' or z.envelope->'record'->>'content_id' is distinct from semantic->>'content_id'
  or z.envelope->'record'->'origin'->>'run_id' is distinct from cl.local_run_id::text
  or z.envelope->'record'->'origin'->>'file_sha256' is distinct from semantic->>'source_file_sha256'
  or z.receipt->>'status' is distinct from 'received' or z.receipt->>'capture_id' is distinct from z.capture_id::text
  or z.receipt->>'task_id' is distinct from z.task_id::text or z.receipt->>'child_id' is distinct from z.child_id::text
  or z.receipt->>'run_id' is distinct from z.run_id::text or z.receipt->'lease_epoch' is distinct from to_jsonb(z.lease_epoch)
  or z.envelope->>'source_kind' is distinct from 'machine_api' or z.envelope->'record'->'reward_eligible' is distinct from 'false'::jsonb
  or z.receipt->>'envelope_hash' is distinct from z.envelope_hash or z.receipt->'reward_eligible' is distinct from 'false'::jsonb
  or z.canonical_envelope::jsonb is distinct from z.envelope
  or encode(sha256(convert_to('crowd-machine-capture-v1'||chr(10)||z.canonical_envelope,'UTF8')),'hex') is distinct from z.envelope_hash then raise exception 'media_source_binding_denied';end if;
 perform pg_advisory_xact_lock(hashtext(p_owner_scope||':video-artifacts'));
 select * into a from crowd_machine.video_artifacts where owner_scope=p_owner_scope and (idempotency_key=semantic->>'idempotency_key' or local_job_id=(semantic->>'local_job_id')::uuid) for update;
 if a.artifact_id is not null then
  if a.manifest_hash is distinct from p_payload->>'manifest_hash' then raise exception 'media_conflict';end if;
  replayed:=true;
 else
  if p_actor_kind='worker' then raise exception 'media_owner_preparation_required';end if;
  a.artifact_id:=gen_random_uuid();a.object_path:=p_owner_scope||'/'||a.artifact_id::text||'/'||(semantic->>'asset_sha256')||'.mp4';
  insert into crowd_machine.video_artifacts(artifact_id,owner_scope,worker_id,task_id,child_id,run_id,lease_epoch,local_run_id,local_job_id,capture_id,idempotency_key,manifest_hash,manifest,canonical_manifest,bucket_id,object_path)
  values(a.artifact_id,p_owner_scope,z.worker_id,z.task_id,z.child_id,z.run_id,z.lease_epoch,cl.local_run_id,(semantic->>'local_job_id')::uuid,z.capture_id,semantic->>'idempotency_key',p_payload->>'manifest_hash',semantic,p_payload->>'canonical_manifest','crowd-machine-media',a.object_path);
 end if;
 select * into a from crowd_machine.video_artifacts where artifact_id=a.artifact_id;
 return jsonb_build_object('artifact_id',a.artifact_id,'state',a.state,'bucket_id',a.bucket_id,'object_path',a.object_path,'manifest',a.manifest,'manifest_hash',a.manifest_hash,'receipt',a.receipt,'replayed',replayed);
end;$$;
revoke all on function public.crowd_video_artifact_rpc(text,text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.crowd_video_artifact_rpc(text,text,text,text,jsonb) to service_role;
