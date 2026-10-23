BEGIN;
CREATE OR REPLACE FUNCTION public.crowd_video_artifact_rpc(p_owner_scope text, p_actor_kind text, p_worker_hash text, p_action text, p_payload jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'crowd_machine'
AS $function$
declare a crowd_machine.video_artifacts;w crowd_machine.workers;z crowd_machine.captures;c crowd_machine.children;
 cl crowd_machine.claims;t crowd_machine.tasks;semantic jsonb;k text;v_receipt jsonb;replayed boolean:=false; native boolean; audio boolean; source_record jsonb; canonical_platform text;
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
   v_receipt:=jsonb_build_object('artifact_id',a.artifact_id,'artifact_kind',case when a.manifest->'manifest_version'='3'::jsonb then 'audio_object' else 'video_object' end,'status','received','verification','server_storage_bytes_sha256',
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
 audio:=coalesce(semantic->'manifest_version'='3'::jsonb,false);
 native:=semantic->'manifest_version'='2'::jsonb or audio;
 native:=coalesce(native,false);
 if jsonb_typeof(semantic->'content_id') is distinct from 'string' or jsonb_typeof(semantic->'idempotency_key') is distinct from 'string'
  or (select count(*) from jsonb_object_keys(semantic))<>(case when audio then 31 when native then 28 else 19 end)
  or not semantic ?& (case when audio then array['idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','platform','content_id','capture_id','envelope_hash','asset_sha256','asset_bytes','duration_ms','source_duration_ms','source_asset_sha256','source_observation_sha256','source_reference_sha256','result_file_sha256'] else array['idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','platform','content_id','capture_id','envelope_hash','asset_sha256','asset_bytes','duration_ms','source_duration_ms','source_asset_sha256','source_file_sha256','source_reference_sha256','result_file_sha256'] end)
  or octet_length(p_payload->>'canonical_manifest')>(case when audio then 262144 else 10000 end) or (p_payload->>'canonical_manifest')::jsonb is distinct from semantic
  or encode(sha256(convert_to((case when audio then 'crowd-media-audio-v3' else 'crowd-media-video-v'||case when native then '2' else '1' end end)||chr(10)||(p_payload->>'canonical_manifest'),'UTF8')),'hex') is distinct from p_payload->>'manifest_hash' then raise exception 'invalid_media_manifest';end if;
 if audio then
  if not semantic ?& array['manifest_version','representation','completeness','content_kind','content_type','entity_ref','container','video_track_present','source_record_hash','audio_track_present','content_mime','source_record_canonical']
   or semantic->>'idempotency_key' is distinct from 'audio:'||(semantic->>'local_job_id')
   or semantic->>'platform' is distinct from 'bilibili' or semantic->>'content_kind' is distinct from 'content'
   or semantic->'content_type' is distinct from 'null'::jsonb or semantic->>'content_id' !~ '^[1-9][0-9]{0,15}$'
   or semantic->>'representation' is distinct from 'pro_collected_audio' or semantic->>'completeness' is distinct from 'saved_asset_not_full_length_verified'
   or semantic->>'container' is distinct from 'm4a' or semantic->>'content_mime' is distinct from 'audio/mp4'
   or semantic->'audio_track_present' is distinct from 'true'::jsonb or semantic->'video_track_present' is distinct from 'false'::jsonb
   or jsonb_typeof(semantic->'source_record_hash') is distinct from 'string' or semantic->>'source_record_hash' !~ '^[a-f0-9]{64}$'
   or semantic->'source_duration_ms' is distinct from semantic->'duration_ms' or semantic->'source_asset_sha256' is distinct from semantic->'asset_sha256'
   or semantic->>'entity_ref' is distinct from 'bilibili:content:'||(semantic->>'content_id') then raise exception 'invalid_media_manifest';end if;
  if jsonb_typeof(semantic->'source_record_canonical') is distinct from 'string' or octet_length(semantic->>'source_record_canonical')>131072 then raise exception 'invalid_media_manifest';end if;
  source_record:=(semantic->>'source_record_canonical')::jsonb;
  if jsonb_typeof(source_record) is distinct from 'object' or source_record ? 'record_hash'
   or encode(sha256(convert_to(semantic->>'source_record_canonical','UTF8')),'hex') is distinct from semantic->>'source_record_hash'
   or source_record->>'platform' is distinct from 'bilibili' or source_record->>'kind' is distinct from 'content'
   or source_record->>'content_id' is distinct from semantic->>'content_id' or source_record->>'source_kind' is distinct from 'mediacrawler_api'
   or source_record->'reward_eligible' is distinct from 'false'::jsonb or source_record->'origin'->>'run_id' is distinct from semantic->>'local_run_id'
   or source_record->'origin'->>'observation_sha256' is distinct from semantic->>'source_observation_sha256' then raise exception 'invalid_media_manifest';end if;
 elsif native then
  if not semantic ?& array['manifest_version','representation','completeness','content_kind','content_type','entity_ref','container','video_track_present','source_record_hash']
   or semantic->>'idempotency_key' is distinct from 'native:'||(semantic->>'local_job_id')
   or semantic->>'platform' not in ('xiaohongshu','douyin','kuaishou','bilibili','weibo','tieba','zhihu')
   or semantic->>'platform' is null or semantic->>'content_id' !~ '^[A-Za-z0-9_.:-]{1,200}$'
   or semantic->>'representation' is distinct from 'native_collected' or semantic->>'completeness' is distinct from 'saved_asset_not_full_length_verified'
   or jsonb_typeof(semantic->'source_record_hash') is distinct from 'string' or semantic->>'source_record_hash' !~ '^[a-f0-9]{64}$'
   or semantic->>'container' is distinct from 'mp4' or semantic->'video_track_present' is distinct from 'true'::jsonb
   or semantic->>'content_kind'='dynamic' and semantic->>'platform' is distinct from 'bilibili'
   or semantic->>'content_kind' not in ('content','dynamic') or semantic->>'content_kind' is null
   or semantic->'source_duration_ms' is distinct from semantic->'duration_ms' or semantic->'source_asset_sha256' is distinct from semantic->'asset_sha256'
   or (case when semantic->>'platform'='zhihu' then semantic->>'content_kind' is distinct from 'content' or semantic->>'content_type' not in ('answer','article','zvideo') or semantic->>'content_type' is null else semantic->'content_type' is distinct from 'null'::jsonb end)
   or semantic->>'entity_ref' is distinct from (semantic->>'platform')||':'||(semantic->>'content_kind')||':'||(semantic->>'content_id')||(case when semantic->>'platform'='zhihu' then ':'||(semantic->>'content_type') else '' end) then raise exception 'invalid_media_manifest';end if;
 else
  if semantic->>'idempotency_key' is distinct from 'video:'||(semantic->>'local_job_id') or semantic->>'platform' is distinct from 'douyin' or semantic->>'content_id' !~ '^[0-9]{1,30}$' then raise exception 'invalid_media_manifest';end if;
 end if;
 foreach k in array array['lease_epoch','asset_bytes','duration_ms','source_duration_ms'] loop
  if jsonb_typeof(semantic->k) is distinct from 'number' or semantic->>k !~ '^[0-9]{1,10}$' then raise exception 'invalid_media_manifest';end if;
 end loop;
 if (semantic->>'lease_epoch')::bigint not between 1 and 2147483647 or (semantic->>'asset_bytes')::bigint not between 12 and 52428800
  or (semantic->>'duration_ms')::bigint not between 1 and 7200000 or (semantic->>'source_duration_ms')::bigint not between 1 and 7200000
  or abs((semantic->>'duration_ms')::bigint-(semantic->>'source_duration_ms')::bigint)>250 then raise exception 'invalid_media_manifest';end if;
 foreach k in array (case when audio then array['asset_sha256','envelope_hash','source_asset_sha256','source_observation_sha256','source_reference_sha256','result_file_sha256'] else array['asset_sha256','envelope_hash','source_asset_sha256','source_file_sha256','source_reference_sha256','result_file_sha256'] end) loop
  if jsonb_typeof(semantic->k) is distinct from 'string' or semantic->>k !~ '^[a-f0-9]{64}$' then raise exception 'invalid_media_manifest';end if;
 end loop;
 select * into z from crowd_machine.captures where capture_id=(semantic->>'capture_id')::uuid and owner_scope=p_owner_scope;
 select * into c from crowd_machine.children where child_id=z.child_id;
 select * into t from crowd_machine.tasks where task_id=z.task_id and owner_scope=p_owner_scope;
 select * into cl from crowd_machine.claims where worker_id=z.worker_id and child_id=z.child_id and run_id=z.run_id and lease_epoch=z.lease_epoch;
 canonical_platform:=case c.platform when 'xhs' then 'xiaohongshu' when 'dy' then 'douyin' when 'ks' then 'kuaishou' when 'bili' then 'bilibili' when 'wb' then 'weibo' when 'tieba' then 'tieba' when 'zhihu' then 'zhihu' end;
 if z.capture_id is null or c.child_id is null or t.task_id is null or cl.claim_id is null
  or p_actor_kind='worker' and z.worker_id is distinct from w.worker_id
  or z.task_id::text is distinct from semantic->>'task_id' or z.child_id::text is distinct from semantic->>'child_id'
  or z.run_id::text is distinct from semantic->>'run_id' or to_jsonb(z.lease_epoch) is distinct from semantic->'lease_epoch'
  or cl.local_run_id::text is distinct from semantic->>'local_run_id' or z.envelope_hash is distinct from semantic->>'envelope_hash'
  or canonical_platform is distinct from semantic->>'platform' or z.envelope->'record'->>'platform' is distinct from semantic->>'platform'
  or z.envelope->'record'->>'kind' is distinct from (case when native then semantic->>'content_kind' else 'content' end)
  or native and semantic->>'platform'='zhihu' and z.envelope->'record'->>'content_type' is distinct from semantic->>'content_type' or native and not audio and z.envelope->'record'->>'record_hash' is distinct from semantic->>'source_record_hash'
  or z.envelope->'record'->>'content_id' is distinct from semantic->>'content_id'
  or z.envelope->'record'->'origin'->>'run_id' is distinct from cl.local_run_id::text
  or (case when audio then z.envelope->'record'->'origin'->>'observation_sha256' is distinct from semantic->>'source_observation_sha256' else z.envelope->'record'->'origin'->>'file_sha256' is distinct from semantic->>'source_file_sha256' end)
  or z.receipt->>'status' is distinct from 'received' or z.receipt->>'capture_id' is distinct from z.capture_id::text
  or z.receipt->>'task_id' is distinct from z.task_id::text or z.receipt->>'child_id' is distinct from z.child_id::text
  or z.receipt->>'run_id' is distinct from z.run_id::text or z.receipt->'lease_epoch' is distinct from to_jsonb(z.lease_epoch)
  or z.envelope->>'source_kind' is distinct from 'machine_api' or z.envelope->'record'->'reward_eligible' is distinct from 'false'::jsonb
  or z.receipt->>'envelope_hash' is distinct from z.envelope_hash or z.receipt->'reward_eligible' is distinct from 'false'::jsonb
  or z.canonical_envelope::jsonb is distinct from z.envelope
  or encode(sha256(convert_to('crowd-machine-capture-v1'||chr(10)||z.canonical_envelope,'UTF8')),'hex') is distinct from z.envelope_hash then raise exception 'media_source_binding_denied';end if;
 if audio and (((z.envelope->'record')-'record_hash'-'author_id') is distinct from source_record
  or z.envelope->'record' ? 'record_hash' and z.envelope->'record'->>'record_hash' is distinct from semantic->>'source_record_hash'
  or z.envelope->'record' ? 'author_id' and z.envelope->'record'->'author_id' is distinct from coalesce(source_record->'author'->'author_id','null'::jsonb)) then raise exception 'media_source_binding_denied';end if;
 perform pg_advisory_xact_lock(hashtext(p_owner_scope||':video-artifacts'));
 select * into a from crowd_machine.video_artifacts where owner_scope=p_owner_scope and (idempotency_key=semantic->>'idempotency_key' or local_job_id=(semantic->>'local_job_id')::uuid) for update;
 if a.artifact_id is not null then
  if a.manifest_hash is distinct from p_payload->>'manifest_hash' then raise exception 'media_conflict';end if;
  replayed:=true;
 else
  if p_actor_kind='worker' then raise exception 'media_owner_preparation_required';end if;
  a.artifact_id:=gen_random_uuid();a.object_path:=p_owner_scope||'/'||a.artifact_id::text||'/'||(semantic->>'asset_sha256')||(case when audio then '.m4a' else '.mp4' end);
  insert into crowd_machine.video_artifacts(artifact_id,owner_scope,worker_id,task_id,child_id,run_id,lease_epoch,local_run_id,local_job_id,capture_id,idempotency_key,manifest_hash,manifest,canonical_manifest,bucket_id,object_path)
  values(a.artifact_id,p_owner_scope,z.worker_id,z.task_id,z.child_id,z.run_id,z.lease_epoch,cl.local_run_id,(semantic->>'local_job_id')::uuid,z.capture_id,semantic->>'idempotency_key',p_payload->>'manifest_hash',semantic,p_payload->>'canonical_manifest','crowd-machine-media',a.object_path);
 end if;
 select * into a from crowd_machine.video_artifacts where artifact_id=a.artifact_id;
 return jsonb_build_object('artifact_id',a.artifact_id,'state',a.state,'bucket_id',a.bucket_id,'object_path',a.object_path,'manifest',a.manifest,'manifest_hash',a.manifest_hash,'receipt',a.receipt,'replayed',replayed);
end;$function$;

REVOKE ALL ON FUNCTION public.crowd_video_artifact_rpc(text,text,text,text,jsonb) FROM public,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.crowd_video_artifact_rpc(text,text,text,text,jsonb) TO service_role;

DO $audio_bucket$
BEGIN
 PERFORM 1 FROM storage.buckets WHERE id='crowd-machine-media' AND public=false AND file_size_limit=52428800
  AND (allowed_mime_types @> ARRAY['video/mp4','image/jpeg','image/png','image/webp']::text[])
  AND ((cardinality(allowed_mime_types)=4) OR (cardinality(allowed_mime_types)=5 AND allowed_mime_types @> ARRAY['audio/mp4']::text[])) FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'media_storage_unavailable';
 END IF;
 UPDATE storage.buckets SET allowed_mime_types=ARRAY['video/mp4','image/jpeg','image/png','image/webp','audio/mp4']::text[] WHERE id='crowd-machine-media';
END;
$audio_bucket$;

COMMIT;
