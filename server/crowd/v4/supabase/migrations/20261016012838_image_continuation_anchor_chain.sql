begin;
DO $guard$ BEGIN IF md5(pg_get_functiondef('public.crowd_image_artifact_rpc(text,text,text,text,jsonb)'::regprocedure)) IS DISTINCT FROM '77ce791584e7728da098bef9a5a9022e' THEN RAISE EXCEPTION 'baseline_changed'; END IF; END $guard$;
create or replace function public.crowd_image_artifact_rpc(p_owner_scope text,p_actor_kind text,p_worker_hash text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security definer set search_path=pg_catalog,crowd_machine as $$
declare a crowd_machine.image_artifacts;w crowd_machine.workers;z crowd_machine.captures;c crowd_machine.children;
 sc crowd_machine.source_continuations; anchor crowd_machine.source_continuations; next_claim crowd_machine.claims; cl crowd_machine.claims;t crowd_machine.tasks;semantic jsonb;k text;v_receipt jsonb;replayed boolean:=false;
begin
 if p_owner_scope is distinct from 'crowd-owner-main' or p_actor_kind not in ('owner','worker') or p_actor_kind is null then raise exception 'principal_denied';end if;
 if p_actor_kind='worker' then
  select * into w from crowd_machine.workers where token_hash=p_worker_hash and owner_scope=p_owner_scope and enabled and expires_at>clock_timestamp();
  if w.worker_id is null then raise exception 'worker_revoked';end if;
 end if;
 if p_action in ('image_lookup','image_get','image_commit') then
  select * into a from crowd_machine.image_artifacts where artifact_id=(p_payload->>'artifact_id')::uuid and owner_scope=p_owner_scope for update;
  if a.artifact_id is null or not exists(select 1 from crowd_machine.workers ww where ww.worker_id=a.worker_id and ww.owner_scope=p_owner_scope and ww.enabled and ww.expires_at>clock_timestamp()) or p_actor_kind='worker' and a.worker_id is distinct from w.worker_id then raise exception 'image_not_found';end if;
  if p_action='image_commit' then
   if p_payload->>'verified_sha256' is distinct from a.manifest->>'asset_sha256'
    or p_payload->'verified_bytes' is distinct from a.manifest->'asset_bytes' or p_payload->>'verified_pixel_sha256' is distinct from a.manifest->>'pixel_sha256' or p_payload->'verified_width' is distinct from a.manifest->'width' or p_payload->'verified_height' is distinct from a.manifest->'height' or p_payload->'verified_frames' is distinct from a.manifest->'frames' or p_payload->'verified_content_mime' is distinct from a.manifest->'content_mime' then raise exception 'image_object_mismatch';end if;
  end if;
  if p_action='image_commit' and a.state='pending' then
   v_receipt:=jsonb_build_object('artifact_id',a.artifact_id,'artifact_kind','image_object','status','received','verification','server_storage_bytes_sha256_decode',
    'manifest_hash',a.manifest_hash,'bucket_id',a.bucket_id,'object_path',a.object_path,'manifest',a.manifest,
    'reward_eligible',false,'received_at',clock_timestamp(),'semantic_review','not_reviewed');
   update crowd_machine.image_artifacts set state='ready',receipt=v_receipt,verified_at=clock_timestamp() where artifact_id=a.artifact_id;
   a.state:='ready';a.receipt:=v_receipt;
  elsif p_action='image_commit' then replayed:=true;
  end if;
  return jsonb_build_object('artifact_id',a.artifact_id,'state',a.state,'bucket_id',a.bucket_id,'object_path',a.object_path,'manifest',a.manifest,'manifest_hash',a.manifest_hash,'receipt',a.receipt,'replayed',replayed);
 end if;
 if p_action is distinct from 'image_prepare' then raise exception 'invalid_request';end if;
 semantic:=p_payload-'canonical_manifest'-'manifest_hash';
 if jsonb_typeof(semantic) is distinct from 'object' or (select count(*) from jsonb_object_keys(semantic))<>(case when semantic->>'schema'='crowd-image-object-v3' then 37 else 33 end) or not semantic ?& array['schema','manifest_version','idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','capture_id','envelope_hash','platform','content_kind','content_id','comment_id','entity_ref','media_id','attachment_id','asset_sha256','asset_bytes','content_mime','width','height','frames','pixel_sha256','source_record_hash','source_observation_sha256','source_reference_sha256','source_url_sha256','transport_url_sha256','normalized_sha256','canonical_reference','source_record_canonical']
  or ((semantic->>'schema'='crowd-image-object-v1' and semantic->'manifest_version'='1'::jsonb and semantic->>'platform'='xiaohongshu') or (semantic->>'schema'='crowd-image-object-v2' and semantic->'manifest_version'='2'::jsonb and semantic->>'platform'='weibo' and semantic->>'content_kind'='content') or (semantic->>'schema'='crowd-image-object-v3' and semantic->'manifest_version'='3'::jsonb and semantic->>'platform'='weibo' and semantic->>'content_kind'='content' and semantic ?& array['continuation_id','continuation_run_id','continuation_lease_epoch','source_local_run_id'])) is not true
  or octet_length(p_payload->>'canonical_manifest')>200000 or (p_payload->>'canonical_manifest')::jsonb is distinct from semantic
  or encode(sha256(convert_to('crowd-media-image-v'||(semantic->>'manifest_version')||chr(10)||(p_payload->>'canonical_manifest'),'UTF8')),'hex') is distinct from p_payload->>'manifest_hash'
  or semantic->>'idempotency_key' is distinct from 'image:'||(semantic->>'local_job_id')
  or semantic->>'platform' not in ('xiaohongshu','weibo') or semantic->>'content_kind' not in ('content','comment')
  or semantic->>'content_kind' is null or semantic->>'content_id' !~ '^[A-Za-z0-9_.:-]{1,200}$'
  or semantic->>'content_mime' not in ('image/png','image/jpeg','image/webp') or semantic->>'content_mime' is null
  or semantic->>'entity_ref' is distinct from (semantic->>'platform')||':'||(semantic->>'content_kind')||':'||(semantic->>'content_id')||(case when semantic->>'content_kind'='comment' then ':'||(semantic->>'comment_id') else '' end)
  or semantic->>'content_kind'='content' and semantic->'comment_id' is distinct from 'null'::jsonb
  or semantic->>'content_kind'='comment' and coalesce(semantic->>'comment_id','') !~ '^[A-Za-z0-9_.:-]{1,200}$'
  then raise exception 'invalid_image_manifest';end if;
 foreach k in array array['lease_epoch','asset_bytes','width','height','frames'] loop
  if jsonb_typeof(semantic->k) is distinct from 'number' or semantic->>k !~ '^[0-9]{1,10}$' then raise exception 'invalid_image_manifest';end if;
 end loop;
 if (semantic->>'lease_epoch')::bigint not between 1 and 2147483647 or (semantic->>'asset_bytes')::bigint not between 1 and (case when semantic->>'platform'='weibo' then 26214400 else 2097152 end)
  or (semantic->>'width')::bigint not between 1 and 16384 or (semantic->>'height')::bigint not between 1 and 16384
  or (semantic->>'width')::bigint*(semantic->>'height')::bigint>16000000 or semantic->'frames' is distinct from '1'::jsonb then raise exception 'invalid_image_manifest';end if;
 foreach k in array array['envelope_hash','media_id','attachment_id','asset_sha256','pixel_sha256','source_record_hash','source_observation_sha256','source_reference_sha256','source_url_sha256','transport_url_sha256','normalized_sha256'] loop
  if jsonb_typeof(semantic->k) is distinct from 'string' or semantic->>k !~ '^[a-f0-9]{64}$' then raise exception 'invalid_image_manifest';end if;
 end loop;
 if octet_length(semantic->>'source_record_canonical')>131072 or jsonb_typeof((semantic->>'source_record_canonical')::jsonb) is distinct from 'object'
  or ((semantic->>'source_record_canonical')::jsonb) ? 'record_hash'
  or encode(sha256(convert_to(semantic->>'source_record_canonical','UTF8')),'hex') is distinct from semantic->>'source_record_hash'
  or octet_length(semantic->>'canonical_reference')>16000 or jsonb_typeof((semantic->>'canonical_reference')::jsonb) is distinct from 'object'
  or encode(sha256(convert_to(semantic->>'canonical_reference','UTF8')),'hex') is distinct from semantic->>'source_reference_sha256' then raise exception 'invalid_image_manifest';end if;
 select * into z from crowd_machine.captures where capture_id=(semantic->>'capture_id')::uuid and owner_scope=p_owner_scope;
 select * into c from crowd_machine.children where child_id=z.child_id;
 select * into t from crowd_machine.tasks where task_id=z.task_id and owner_scope=p_owner_scope;
 select * into cl from crowd_machine.claims where worker_id=z.worker_id and child_id=z.child_id and run_id=z.run_id and lease_epoch=z.lease_epoch;
 if z.capture_id is null or c.child_id is null or t.task_id is null or cl.claim_id is null
  or not exists(select 1 from crowd_machine.workers ww where ww.worker_id=z.worker_id and ww.owner_scope=p_owner_scope and ww.enabled and ww.expires_at>clock_timestamp())
  or p_actor_kind='worker' and z.worker_id is distinct from w.worker_id
  or z.task_id::text is distinct from semantic->>'task_id' or z.child_id::text is distinct from semantic->>'child_id'
  or z.run_id::text is distinct from semantic->>'run_id' or to_jsonb(z.lease_epoch) is distinct from semantic->'lease_epoch'
  or z.envelope_hash is distinct from semantic->>'envelope_hash'
  or z.envelope->'record'->>'platform' is distinct from semantic->>'platform' or c.platform is distinct from (case when semantic->>'platform'='weibo' then 'wb' else 'xhs' end)
  or z.envelope->'record'->>'kind' is distinct from semantic->>'content_kind'
  or z.envelope->'record'->>'content_id' is distinct from semantic->>'content_id'
  or coalesce(z.envelope->'record'->'comment_id','null'::jsonb) is distinct from semantic->'comment_id'
  or z.envelope->'record'->'origin'->>'run_id' is distinct from coalesce(semantic->>'source_local_run_id',semantic->>'local_run_id')
  or z.envelope->'record'->'origin'->>'executor' is distinct from 'mediacrawler_pro' or z.envelope->'record'->'origin'->>'operation_id' is distinct from coalesce(semantic->>'source_local_run_id',semantic->>'local_run_id')
  or z.envelope->'record'->'origin'->>'observation_sha256' is distinct from semantic->>'source_observation_sha256'
  or z.envelope->'record'->>'source_kind' is distinct from 'mediacrawler_api'
  or z.receipt->>'status' is distinct from 'received' or z.receipt->>'capture_id' is distinct from z.capture_id::text
  or z.receipt->>'task_id' is distinct from z.task_id::text or z.receipt->>'child_id' is distinct from z.child_id::text
  or z.receipt->>'run_id' is distinct from z.run_id::text or z.receipt->'lease_epoch' is distinct from to_jsonb(z.lease_epoch)
  or z.envelope->>'source_kind' is distinct from 'machine_api' or z.envelope->'record'->'reward_eligible' is distinct from 'false'::jsonb
  or z.receipt->>'envelope_hash' is distinct from z.envelope_hash or z.receipt->'reward_eligible' is distinct from 'false'::jsonb
  or z.canonical_envelope::jsonb is distinct from z.envelope
  or encode(sha256(convert_to('crowd-machine-capture-v1'||chr(10)||z.canonical_envelope,'UTF8')),'hex') is distinct from z.envelope_hash
  then raise exception 'image_source_binding_denied';end if;
 if semantic->>'schema'='crowd-image-object-v3' then
  select * into sc from crowd_machine.source_continuations where continuation_id=(semantic->>'continuation_id')::uuid;
  if sc.proof ? 'chain' then
   select * into anchor from crowd_machine.source_continuations aa where aa.continuation_id=(sc.proof->'chain'->>'previous_continuation_id')::uuid;
   if anchor.continuation_id is null or anchor.proof ? 'chain' or anchor.task_id<>sc.task_id or anchor.child_id<>sc.child_id or anchor.source_worker_id<>sc.source_worker_id or anchor.source_lease_epoch+1<>sc.source_lease_epoch or anchor.account_context is distinct from sc.account_context or sc.proof->>'failure_reason'<>'wb_reply_page_shape_invalid' then raise exception 'image_source_binding_denied';end if;
  else anchor:=sc;end if;
  select * into next_claim from crowd_machine.claims where worker_id=z.worker_id and child_id=z.child_id and run_id=(semantic->>'continuation_run_id')::uuid and lease_epoch=(semantic->>'continuation_lease_epoch')::int;
  if c.plan->'request'->'media' is distinct from 'true'::jsonb or c.plan->'request'->>'source_executor' is distinct from 'pro' or cl.outcome is distinct from 'failed' or cl.finished_at is null or sc.continuation_id is null or next_claim.claim_id is null or sc.task_id<>z.task_id or sc.child_id<>z.child_id or sc.source_worker_id<>z.worker_id or anchor.source_run_id<>z.run_id or anchor.source_claim_id<>cl.claim_id or anchor.source_lease_epoch<>z.lease_epoch
   or anchor.source_local_run_id::text is distinct from semantic->>'source_local_run_id' or anchor.source_finish_hash is null or sc.source_finish_hash is null
   or to_jsonb(next_claim.lease_epoch) is distinct from semantic->'continuation_lease_epoch' or next_claim.lease_epoch<>sc.source_lease_epoch+1
   or next_claim.local_run_id::text is distinct from semantic->>'local_run_id' or next_claim.local_run_id=sc.source_local_run_id or next_claim.outcome is distinct from 'completed' or next_claim.finished_at is null
   or c.run_id<>next_claim.run_id or c.lease_epoch<>next_claim.lease_epoch or c.local_run_id<>next_claim.local_run_id or c.worker_id<>z.worker_id or c.state<>'completed' or c.account_context is distinct from sc.account_context
   or sc.account_context->>'session_id' is distinct from c.plan->'request'->>'session_id'
   then raise exception 'image_source_binding_denied';end if;
 end if;
 -- Exact documented export projection: only record_hash omission and derived author_id are allowed.
 if ((z.envelope->'record')-'record_hash'-'author_id') is distinct from (semantic->>'source_record_canonical')::jsonb
  or z.envelope->'record' ? 'record_hash' and z.envelope->'record'->>'record_hash' is distinct from semantic->>'source_record_hash'
  or z.envelope->'record' ? 'author_id' and z.envelope->'record'->'author_id' is distinct from coalesce(((semantic->>'source_record_canonical')::jsonb)->'author'->'author_id','null'::jsonb)
  or (select count(*) from jsonb_array_elements(z.envelope->'record'->'media') ref where ref=(semantic->>'canonical_reference')::jsonb)<>1
  then raise exception 'image_source_binding_denied';end if;
 if semantic->>'platform'='weibo' and (((semantic->>'canonical_reference')::jsonb)->>'kind' is distinct from 'image' or coalesce(((semantic->>'canonical_reference')::jsonb)->>'url','') !~ '^https?://([a-z0-9-]+\.)*sinaimg\.cn/[^#[:space:]]*$') then raise exception 'image_source_binding_denied';end if;
 if ((semantic->>'canonical_reference')::jsonb)->>'media_id' is distinct from semantic->>'media_id'
  or ((semantic->>'canonical_reference')::jsonb)->>'platform' is distinct from semantic->>'platform'
  or ((semantic->>'canonical_reference')::jsonb)->>'content_id' is distinct from semantic->>'content_id'
  or coalesce(((semantic->>'canonical_reference')::jsonb)->'comment_id','null'::jsonb) is distinct from semantic->'comment_id'
  or ((semantic->>'canonical_reference')::jsonb)->>'source_kind' is distinct from 'mediacrawler_api'
  or ((semantic->>'canonical_reference')::jsonb)->'reward_eligible' is distinct from 'false'::jsonb
  or ((semantic->>'canonical_reference')::jsonb)->>'status' is distinct from 'reference_only'
  then raise exception 'image_source_binding_denied';end if;
 perform pg_advisory_xact_lock(hashtext(p_owner_scope||':image-artifacts'));
 select * into a from crowd_machine.image_artifacts where owner_scope=p_owner_scope and (idempotency_key=semantic->>'idempotency_key' or local_job_id=(semantic->>'local_job_id')::uuid) for update;
 if a.artifact_id is not null then
  if a.manifest_hash is distinct from p_payload->>'manifest_hash' then raise exception 'image_conflict';end if;
  replayed:=true;
 else
  if p_actor_kind='worker' then raise exception 'image_owner_preparation_required';end if;
  a.artifact_id:=gen_random_uuid();a.object_path:=p_owner_scope||'/'||a.artifact_id::text||'/'||(semantic->>'asset_sha256')||(case semantic->>'content_mime' when 'image/png' then '.png' when 'image/jpeg' then '.jpg' else '.webp' end);
  insert into crowd_machine.image_artifacts(artifact_id,owner_scope,worker_id,task_id,child_id,run_id,lease_epoch,local_run_id,local_job_id,capture_id,idempotency_key,manifest_hash,manifest,canonical_manifest,bucket_id,object_path)
  values(a.artifact_id,p_owner_scope,z.worker_id,z.task_id,z.child_id,z.run_id,z.lease_epoch,(semantic->>'local_run_id')::uuid,(semantic->>'local_job_id')::uuid,z.capture_id,semantic->>'idempotency_key',p_payload->>'manifest_hash',semantic,p_payload->>'canonical_manifest','crowd-machine-media',a.object_path);
 end if;
 select * into a from crowd_machine.image_artifacts where artifact_id=a.artifact_id;
 return jsonb_build_object('artifact_id',a.artifact_id,'state',a.state,'bucket_id',a.bucket_id,'object_path',a.object_path,'manifest',a.manifest,'manifest_hash',a.manifest_hash,'receipt',a.receipt,'replayed',replayed);
end;$$;
revoke all on function public.crowd_image_artifact_rpc(text,text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.crowd_image_artifact_rpc(text,text,text,text,jsonb) to service_role;

commit;
