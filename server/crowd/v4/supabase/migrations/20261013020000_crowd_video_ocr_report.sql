-- Add explicit sampled screen-text OCR reports; preserve ASR, captions, owner gate and immutable receipts.
create or replace function public.crowd_transcript_artifact_rpc(p_owner_scope text,p_actor_kind text,p_action text,p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare a crowd_machine.transcript_artifacts%rowtype; t crowd_machine.tasks%rowtype; c crowd_machine.children%rowtype;
 claim crowd_machine.claims%rowtype; z crowd_machine.captures%rowtype; ref jsonb; semantic jsonb; report jsonb; segment jsonb;
 report_keys text[]; provenance jsonb; previous_start numeric:=-1; subtitle_cursor numeric:=0; receipt jsonb; body_kind text; body_type text; row_type text; chars integer:=0; joined text:=''; n integer:=0; duration numeric; canonical_expected text; refs_canonical text; report_json_canonical text;
 -- ECMAScript trim/\s set; PostgreSQL btrim defaults to ASCII space only.
 whitespace text:=chr(9)||chr(10)||chr(11)||chr(12)||chr(13)||chr(32)||chr(160)||chr(5760)||chr(8192)||chr(8193)||chr(8194)||chr(8195)||chr(8196)||chr(8197)||chr(8198)||chr(8199)||chr(8200)||chr(8201)||chr(8202)||chr(8232)||chr(8233)||chr(8239)||chr(8287)||chr(12288)||chr(65279);
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
 -- Rebuild the fixed artifact envelope, not an arbitrary JSON canonicalizer. Report JSON stays byte-exact.
 if exists(select 1 from jsonb_array_elements(p_payload->'source_refs') r where jsonb_typeof(r) is distinct from 'object'
  or not(r ?& array['capture_id','envelope_hash']) or r-array['capture_id','envelope_hash']<>'{}'::jsonb
  or jsonb_typeof(r->'capture_id') is distinct from 'string' or jsonb_typeof(r->'envelope_hash') is distinct from 'string') then raise exception 'invalid_transcript'; end if;
 select '['||string_agg('{"capture_id":'||(r->'capture_id')::text||',"envelope_hash":'||(r->'envelope_hash')::text||'}',',' order by r->>'capture_id' collate "C")||']'
 into refs_canonical from jsonb_array_elements(p_payload->'source_refs') r;
 -- The project canonical encoder uses \u00XX for every control character, including newlines.
 select '"'||string_agg(case when ascii(ch)<32 then '\u'||lpad(to_hex(ascii(ch)),4,'0') when ch='"' then '\"' when ch='\' then '\\' else ch end,'' order by ord)||'"'
 into report_json_canonical from regexp_split_to_table(p_payload->>'report_json','') with ordinality part(ch,ord);
 select '{'||string_agg(to_jsonb(key)::text||':'||case when key='source_refs' then refs_canonical when key='report_json' then report_json_canonical else value::text end,',' order by key collate "C")||'}'
 into canonical_expected from jsonb_each(semantic);
 if p_payload->>'canonical_transcript' is distinct from canonical_expected
  or (p_payload->>'canonical_transcript')::jsonb is distinct from semantic
  or encode(sha256(convert_to('crowd-transcript-artifact-v1'||chr(10)||(p_payload->>'canonical_transcript'),'UTF8')),'hex') is distinct from p_payload->>'artifact_hash'
  or encode(sha256(convert_to(p_payload->>'report_json','UTF8')),'hex') is distinct from p_payload->>'report_sha256' then raise exception 'transcript_hash_conflict'; end if;
 if report->>'schema' in ('crowd-subtitle-report-v1','crowd-platform-subtitle-report-v1') then
  report_keys:=array['schema','job_id','local_run_id','platform','content_id','entity_ref','asset_sha256','input_hash','full_result_file_sha256','duration_seconds','segments','text_sha256','segment_count','character_count','semantic_review','cer','human_groundtruth','diagnostics_sha256','model_manifest_sha256','processing_profile','processor','text_revision','subtitle_source_run_id','subtitle_provenance'];
 elsif report->>'schema'='crowd-video-ocr-report-v1' then
  report_keys:=array['schema','job_id','local_run_id','platform','content_id','entity_ref','asset_sha256','input_hash','full_result_file_sha256','duration_seconds','segments','text_sha256','segment_count','character_count','semantic_review','cer','human_groundtruth','diagnostics_sha256','model_manifest_sha256','processing_profile','processor','text_revision','video_source_job_id','visual_provenance'];
 elsif report->>'schema'='crowd-transcript-report-v1' then
  report_keys:=array['schema','job_id','audio_source_job_id','local_run_id','platform','content_id','entity_ref','asset_sha256','input_hash','full_result_file_sha256','duration_seconds','segments','text_sha256','segment_count','character_count','semantic_review','cer','human_groundtruth','diagnostics_sha256','model_manifest_sha256','processing_profile','processor','text_revision'];
 else raise exception 'invalid_transcript'; end if;
 if jsonb_typeof(report) is distinct from 'object' or not(report ?& report_keys) or report-report_keys<>'{}'::jsonb
  or report->>'job_id' is distinct from p_payload->>'local_job_id' or report->>'local_run_id' is distinct from p_payload->>'local_run_id'
  or report->>'semantic_review' is distinct from 'not_reviewed' or report->'cer' is distinct from 'null'::jsonb or report->'human_groundtruth' is distinct from 'false'::jsonb
  or report->'segments' is null or jsonb_typeof(report->'segments') is distinct from 'array'
  or coalesce(report->>'asset_sha256','') !~ '^[a-f0-9]{64}$' or coalesce(report->>'full_result_file_sha256','') !~ '^[a-f0-9]{64}$'
  or coalesce(report->>'input_hash','') !~ '^[a-f0-9]{64}$' or coalesce(report->>'text_sha256','') !~ '^[a-f0-9]{64}$'
  or jsonb_typeof(report->'duration_seconds') is distinct from 'number' then raise exception 'invalid_transcript'; end if;
 if report->>'schema'='crowd-subtitle-report-v1' then
  provenance:=report->'subtitle_provenance';
  if report->>'platform' is distinct from 'bilibili' or report->>'subtitle_source_run_id' is distinct from p_payload->>'local_run_id'
   or report->>'entity_ref' is distinct from 'bilibili:content:'||(report->>'content_id')
   or report->>'processor' is distinct from 'native_bilibili_subtitle_json_v1' or report->>'processing_profile' is distinct from 'native_bilibili_subtitle_json_v1'
   or report->'model_manifest_sha256' is distinct from 'null'::jsonb or report->'diagnostics_sha256' is distinct from 'null'::jsonb or report->'text_revision' is distinct from 'null'::jsonb
   or jsonb_typeof(provenance) is distinct from 'object'
   or not(provenance ?& array['provider','subtitle_kind','language','track_id','coverage','semantic_status','semantic_completeness','source_body_sha256','raw_subtitle_sha256','player_response_sha256','aid','cid','bvid','first_seconds','last_seconds','duration_seconds'])
   or provenance-array['provider','subtitle_kind','language','track_id','coverage','semantic_status','semantic_completeness','source_body_sha256','raw_subtitle_sha256','player_response_sha256','aid','cid','bvid','first_seconds','last_seconds','duration_seconds']<>'{}'::jsonb
   or provenance->>'provider' is distinct from 'bilibili' or coalesce(provenance->>'subtitle_kind','') not in ('human','platform_auto','unknown')
   or provenance->>'coverage' is distinct from 'source_track_full_duration_candidate' or provenance->>'semantic_status' is distinct from 'not_reviewed' or provenance->>'semantic_completeness' is distinct from 'unknown'
   or jsonb_typeof(provenance->'language') is distinct from 'string' or coalesce(provenance->>'language','') !~ '^[A-Za-z0-9_-]{1,30}$'
   or jsonb_typeof(provenance->'track_id') is distinct from 'string' or coalesce(provenance->>'track_id','') !~ '^[0-9]{1,40}$'
   or jsonb_typeof(provenance->'aid') is distinct from 'string' or coalesce(provenance->>'aid','') !~ '^[1-9][0-9]{0,19}$'
   or jsonb_typeof(provenance->'cid') is distinct from 'string' or coalesce(provenance->>'cid','') !~ '^[1-9][0-9]{0,19}$'
   or coalesce(provenance->>'bvid','') !~ '^BV[A-Za-z0-9]{10}$' or report->>'content_id' not in (provenance->>'aid',provenance->>'bvid')
   or provenance->>'raw_subtitle_sha256' is distinct from report->>'asset_sha256' or provenance->>'source_body_sha256' is distinct from report->>'asset_sha256'
   or coalesce(provenance->>'player_response_sha256','') !~ '^[a-f0-9]{64}$'
   or jsonb_typeof(provenance->'first_seconds') is distinct from 'number' or jsonb_typeof(provenance->'last_seconds') is distinct from 'number'
   or provenance->'duration_seconds' is distinct from report->'duration_seconds' then raise exception 'invalid_transcript'; end if;
  if (provenance->>'first_seconds')::numeric<0 or (provenance->>'last_seconds')::numeric<(provenance->>'first_seconds')::numeric
   or (provenance->>'last_seconds')::numeric>(report->>'duration_seconds')::numeric then raise exception 'invalid_transcript'; end if;
 elsif report->>'schema'='crowd-platform-subtitle-report-v1' then
  provenance:=report->'subtitle_provenance';
  if report->>'platform' is distinct from 'douyin' or report->>'subtitle_source_run_id' is distinct from p_payload->>'local_run_id'
   or report->>'entity_ref' is distinct from 'douyin:content:'||(report->>'content_id')
   or report->>'processor' is distinct from 'yt_dlp_native_metadata_subtitle_v1' or report->>'processing_profile' is distinct from 'yt_dlp_native_metadata_subtitle_v1'
   or report->'model_manifest_sha256' is distinct from 'null'::jsonb or report->'diagnostics_sha256' is distinct from 'null'::jsonb or report->'text_revision' is distinct from 'null'::jsonb
   or jsonb_typeof(provenance) is distinct from 'object'
   or not(provenance ?& array['provider','subtitle_kind','language','track_id','coverage','semantic_status','semantic_completeness','source_body_sha256','raw_subtitle_sha256','source_metadata_sha256','extractor_version','extractor_method','content_id','first_seconds','last_seconds','duration_seconds'])
   or provenance-array['provider','subtitle_kind','language','track_id','coverage','semantic_status','semantic_completeness','source_body_sha256','raw_subtitle_sha256','source_metadata_sha256','extractor_version','extractor_method','content_id','first_seconds','last_seconds','duration_seconds']<>'{}'::jsonb
   or provenance->>'provider' is distinct from 'douyin' or coalesce(provenance->>'subtitle_kind','') not in ('human','platform_auto','unknown')
   or provenance->>'coverage' is distinct from 'source_track_full_duration_candidate' or provenance->>'semantic_status' is distinct from 'not_reviewed' or provenance->>'semantic_completeness' is distinct from 'unknown'
   or jsonb_typeof(provenance->'language') is distinct from 'string' or coalesce(provenance->>'language','') !~ '^[A-Za-z0-9_-]{1,30}$'
   or jsonb_typeof(provenance->'track_id') is distinct from 'string' or coalesce(provenance->>'track_id','') !~ '^[A-Za-z0-9_-]{1,80}$'
   or jsonb_typeof(provenance->'content_id') is distinct from 'string'
   or jsonb_typeof(provenance->'source_body_sha256') is distinct from 'string' or jsonb_typeof(provenance->'raw_subtitle_sha256') is distinct from 'string' or jsonb_typeof(provenance->'source_metadata_sha256') is distinct from 'string'
   or provenance->>'content_id' is distinct from report->>'content_id'
   or jsonb_typeof(provenance->'extractor_version') is distinct from 'string' or coalesce(provenance->>'extractor_version','') !~ '^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$'
   or provenance->>'extractor_method' is distinct from 'TikTokBaseIE._get_subtitles'
   or provenance->>'raw_subtitle_sha256' is distinct from report->>'asset_sha256' or provenance->>'source_body_sha256' is distinct from report->>'asset_sha256'
   or coalesce(provenance->>'source_metadata_sha256','') !~ '^[a-f0-9]{64}$'
   or jsonb_typeof(provenance->'first_seconds') is distinct from 'number' or jsonb_typeof(provenance->'last_seconds') is distinct from 'number'
   or provenance->'duration_seconds' is distinct from report->'duration_seconds' then raise exception 'invalid_transcript'; end if;
  if (provenance->>'first_seconds')::numeric<0 or (provenance->>'last_seconds')::numeric<(provenance->>'first_seconds')::numeric
   or (provenance->>'last_seconds')::numeric>(report->>'duration_seconds')::numeric then raise exception 'invalid_transcript'; end if;
 end if;
 if report->>'schema'='crowd-video-ocr-report-v1' then
  provenance:=report->'visual_provenance';
  if jsonb_typeof(report->'platform') is distinct from 'string' or coalesce(report->>'platform','') not in ('xiaohongshu','douyin','kuaishou','bilibili','weibo','tieba','zhihu')
   or jsonb_typeof(report->'content_id') is distinct from 'string' or coalesce(report->>'content_id','') !~ '^[A-Za-z0-9_-]{1,200}$'
   or (report->'entity_ref' is distinct from 'null'::jsonb and jsonb_typeof(report->'entity_ref') is distinct from 'string')
   or jsonb_typeof(report->'video_source_job_id') is distinct from 'string'
   or coalesce(report->>'video_source_job_id','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   or report->>'processor' is distinct from 'apple_vision_sampled_video_text'
   or report->>'processing_profile' is distinct from 'apple_vision_video_hard_text_2fps_v1'
   or report->'model_manifest_sha256' is distinct from 'null'::jsonb or report->'text_revision' is distinct from 'null'::jsonb
   or coalesce(report->>'diagnostics_sha256','') !~ '^[a-f0-9]{64}$'
   or exists(select 1 from unnest(array['asset_sha256','input_hash','full_result_file_sha256','text_sha256','diagnostics_sha256']) key where jsonb_typeof(report->key) is distinct from 'string')
   or jsonb_typeof(provenance) is distinct from 'object'
   or not(provenance ?& array['provider','source_kind','source_video_sha256','source_reference_sha256','source_record_sha256','sampling_fps','sample_start','sample_end','sampled_frames','expected_frames','crop_top_origin','timestamp_kind','timestamp_uncertainty_seconds','frame_evidence_sha256','frame_evidence_format','coverage','spoken_transcript','semantic_completeness','truncated'])
   or provenance-array['provider','source_kind','source_video_sha256','source_reference_sha256','source_record_sha256','sampling_fps','sample_start','sample_end','sampled_frames','expected_frames','crop_top_origin','timestamp_kind','timestamp_uncertainty_seconds','frame_evidence_sha256','frame_evidence_format','coverage','spoken_transcript','semantic_completeness','truncated']<>'{}'::jsonb
   or provenance->>'provider' is distinct from 'apple_vision' or provenance->>'source_kind' is distinct from 'sampled_video_text'
   or exists(select 1 from unnest(array['source_video_sha256','source_reference_sha256','source_record_sha256','frame_evidence_sha256']) key where jsonb_typeof(provenance->key) is distinct from 'string')
   or provenance->>'source_video_sha256' is distinct from report->>'asset_sha256'
   or provenance->>'frame_evidence_sha256' is distinct from report->>'diagnostics_sha256'
   or coalesce(provenance->>'source_reference_sha256','') !~ '^[a-f0-9]{64}$'
   or coalesce(provenance->>'source_record_sha256','') !~ '^[a-f0-9]{64}$'
   or provenance->'sampling_fps' is distinct from '2'::jsonb or provenance->'sample_start' is distinct from '0'::jsonb
   or provenance->'sample_end' is distinct from report->'duration_seconds'
   or jsonb_typeof(provenance->'sampled_frames') is distinct from 'number'
   or jsonb_typeof(provenance->'expected_frames') is distinct from 'number'
   or provenance->'sampled_frames' is distinct from provenance->'expected_frames'
   or provenance->>'timestamp_kind' is distinct from 'resampled_frame_time'
   or provenance->'timestamp_uncertainty_seconds' is distinct from '0.5'::jsonb
   or provenance->>'frame_evidence_format' is distinct from 'gzip_json_array_v1'
   or provenance->>'coverage' is distinct from 'all_scheduled_frames_processed'
   or provenance->'spoken_transcript' is distinct from 'false'::jsonb or provenance->>'semantic_completeness' is distinct from 'unknown'
   or provenance->'truncated' is distinct from 'false'::jsonb
   or jsonb_typeof(provenance->'crop_top_origin') is distinct from 'array' then raise exception 'invalid_transcript'; end if;
  if jsonb_array_length(provenance->'crop_top_origin')<>2
   or jsonb_typeof(provenance->'crop_top_origin'->0) is distinct from 'number'
   or jsonb_typeof(provenance->'crop_top_origin'->1) is distinct from 'number' then raise exception 'invalid_transcript'; end if;
  if (provenance->>'expected_frames')::numeric<=0 or (provenance->>'expected_frames')::numeric<>trunc((provenance->>'expected_frames')::numeric)
   or (provenance->>'expected_frames')::numeric<>ceil((report->>'duration_seconds')::numeric*2)
   or (provenance->>'expected_frames')::numeric>14400
   or (provenance->'crop_top_origin'->>0)::numeric<0
   or (provenance->'crop_top_origin'->>0)::numeric>=(provenance->'crop_top_origin'->>1)::numeric
   or (provenance->'crop_top_origin'->>1)::numeric>1 then raise exception 'invalid_transcript'; end if;
 end if;
 -- Scan decoded values and keys: JSON escaping must never hide a sensitive string.
 if exists(with recursive nodes(value,key) as (
  select report,null::text
  union all
  select child.value,child.key from nodes cross join lateral (
   select value,key from jsonb_each(case when jsonb_typeof(nodes.value)='object' then nodes.value else '{}'::jsonb end)
   union all select value,null::text from jsonb_array_elements(case when jsonb_typeof(nodes.value)='array' then nodes.value else '[]'::jsonb end)
  ) child
 ) select 1 from nodes where key ~* '^(cookie|authorization|password|access_token|refresh_token|private_key|api_key|secret|audio|audio_base64|input_snapshot)$'
  or (jsonb_typeof(value)='string' and value#>>'{}' ~* ('(cookie|authorization|password|access_token|refresh_token|private_key|api_key|secret)['||whitespace||']*[=:]'))
 ) then raise exception 'sensitive_transcript'; end if;
 duration:=(report->>'duration_seconds')::numeric;
 if report->>'platform'='zhihu' and not exists(select 1 from unnest(array['answer','article','zvideo']) kind where report->>'entity_ref'='zhihu:content:'||(report->>'content_id')||':'||kind) then raise exception 'invalid_transcript'; end if;
 if duration<=0 or duration>7200 or jsonb_array_length(report->'segments') not between 1 and 8000 then raise exception 'invalid_transcript'; end if;
 for segment in select value from jsonb_array_elements(report->'segments') loop
  if jsonb_typeof(segment) is distinct from 'object' or not(segment ?& array['start','end','text']) or segment-array['start','end','text','chunk_index']<>'{}'::jsonb
   or jsonb_typeof(segment->'start') is distinct from 'number' or jsonb_typeof(segment->'end') is distinct from 'number' or jsonb_typeof(segment->'text') is distinct from 'string'
   or btrim(segment->>'text',whitespace)=''
   -- JS string.length counts supplementary characters as two UTF-16 code units.
   or length(segment->>'text')+length(regexp_replace(segment->>'text','['||chr(1)||'-'||chr(65535)||']','','g'))>24000 then raise exception 'invalid_transcript'; end if;
  if (segment->>'start')::numeric<0 or (segment->>'end')::numeric<(segment->>'start')::numeric or (segment->>'end')::numeric>duration then raise exception 'invalid_transcript'; end if;
  if segment ? 'chunk_index' and (jsonb_typeof(segment->'chunk_index') is distinct from 'number' or coalesce(segment->>'chunk_index','') !~ '^(0|[1-9][0-9]{0,2})$' or (segment->>'chunk_index')::integer>=512) then raise exception 'invalid_transcript'; end if;
  if report->>'schema' in ('crowd-subtitle-report-v1','crowd-platform-subtitle-report-v1') then
   if (segment->>'start')::numeric<previous_start or (segment->>'end')::numeric<=(segment->>'start')::numeric
    or (segment->>'start')::numeric-subtitle_cursor>greatest(120,duration*.15) then raise exception 'invalid_transcript'; end if;
   previous_start:=(segment->>'start')::numeric;subtitle_cursor:=greatest(subtitle_cursor,(segment->>'end')::numeric);
  end if;
  if report->>'schema'='crowd-video-ocr-report-v1' then
   if segment-array['start','end','text']<>'{}'::jsonb or (segment->>'start')::numeric<subtitle_cursor
    or (segment->>'start')::numeric>=(segment->>'end')::numeric then raise exception 'invalid_transcript'; end if;
   subtitle_cursor:=(segment->>'end')::numeric;
  end if;
  if n>0 then joined:=joined||chr(10); end if;joined:=joined||(segment->>'text');n:=n+1;chars:=chars+length(segment->>'text');
 end loop;
 if report->>'schema' in ('crowd-subtitle-report-v1','crowd-platform-subtitle-report-v1') and ((provenance->>'first_seconds')::numeric is distinct from (report->'segments'->0->>'start')::numeric
  or (provenance->>'last_seconds')::numeric is distinct from subtitle_cursor or (provenance->>'first_seconds')::numeric>greatest(10,duration*.03)
  or duration-subtitle_cursor>greatest(10,duration*.03)) then raise exception 'invalid_transcript'; end if;
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
  if report->>'schema'='crowd-video-ocr-report-v1' and z.envelope->'record'->>'record_hash' is distinct from provenance->>'source_record_sha256' then raise exception 'transcript_source_binding_denied'; end if;
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
