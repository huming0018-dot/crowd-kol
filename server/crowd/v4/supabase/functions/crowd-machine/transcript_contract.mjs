import {assert,canonical,hex,sha,uuid} from './contract.mjs';
import {artifactCanonical} from './artifact_contract.mjs';

const plain=value=>value&&typeof value==='object'&&!Array.isArray(value);
const keys=(value,list)=>plain(value)&&Object.keys(value).length===list.length&&list.every(key=>Object.hasOwn(value,key));
const positive=value=>Number.isSafeInteger(value)&&value>0;
const sensitive=/(?:cookie|authorization|password|access_token|refresh_token|private_key|api_key|secret)\s*[=:]/i;
const fields=['idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','source_refs','report_sha256','report_json'];
const reportFields=['schema','job_id','audio_source_job_id','local_run_id','platform','content_id','entity_ref','asset_sha256','input_hash','full_result_file_sha256','duration_seconds','segments','text_sha256','segment_count','character_count','semantic_review','cer','human_groundtruth','diagnostics_sha256','model_manifest_sha256','processing_profile','processor','text_revision'];
const subtitleFields=reportFields.filter(key=>key!=='audio_source_job_id').concat('subtitle_source_run_id','subtitle_provenance');
const provenanceFields=['provider','subtitle_kind','language','track_id','coverage','semantic_status','semantic_completeness','source_body_sha256','raw_subtitle_sha256','player_response_sha256','aid','cid','bvid','first_seconds','last_seconds','duration_seconds'];

function subtitleReport(report,input){
  const p=report.subtitle_provenance;
  assert(keys(report,subtitleFields)&&report.subtitle_source_run_id===input.local_run_id&&report.platform==='bilibili'
    &&report.entity_ref==='bilibili:content:'+report.content_id
    &&report.processor==='native_bilibili_subtitle_json_v1'&&report.processing_profile==='native_bilibili_subtitle_json_v1'
    &&report.model_manifest_sha256===null&&report.diagnostics_sha256===null&&report.text_revision===null,'invalid_transcript');
  assert(keys(p,provenanceFields)&&p.provider==='bilibili'&&['human','platform_auto','unknown'].includes(p.subtitle_kind)
    &&typeof p.language==='string'&&/^[A-Za-z0-9_-]{1,30}$/.test(p.language)
    &&typeof p.track_id==='string'&&/^[0-9]{1,40}$/.test(p.track_id)
    &&p.coverage==='source_track_full_duration_candidate'&&p.semantic_status==='not_reviewed'&&p.semantic_completeness==='unknown'
    &&['source_body_sha256','raw_subtitle_sha256','player_response_sha256'].every(k=>hex(p[k]))
    &&p.raw_subtitle_sha256===report.asset_sha256&&p.source_body_sha256===report.asset_sha256
    &&/^BV[A-Za-z0-9]{10}$/.test(p.bvid)&&[p.aid,p.bvid].includes(report.content_id)
    &&['aid','cid'].every(k=>typeof p[k]==='string'&&/^[1-9][0-9]{0,19}$/.test(p[k]))
    &&Number.isFinite(p.first_seconds)&&Number.isFinite(p.last_seconds)&&p.first_seconds>=0&&p.first_seconds<=p.last_seconds
    &&p.last_seconds<=report.duration_seconds&&p.duration_seconds===report.duration_seconds,'invalid_transcript');
}

const platformProvenanceFields=['provider','subtitle_kind','language','track_id','coverage','semantic_status','semantic_completeness','source_body_sha256','raw_subtitle_sha256','source_metadata_sha256','extractor_version','extractor_method','content_id','first_seconds','last_seconds','duration_seconds'];
function platformSubtitleReport(report,input){
 const p=report.subtitle_provenance;
 assert(keys(report,subtitleFields)&&report.subtitle_source_run_id===input.local_run_id&&report.platform==='douyin'
  &&report.entity_ref==='douyin:content:'+report.content_id
  &&report.processor==='yt_dlp_native_metadata_subtitle_v1'&&report.processing_profile==='yt_dlp_native_metadata_subtitle_v1'
  &&report.model_manifest_sha256===null&&report.diagnostics_sha256===null&&report.text_revision===null,'invalid_transcript');
 assert(keys(p,platformProvenanceFields)&&p.provider==='douyin'&&p.content_id===report.content_id
  &&['human','platform_auto','unknown'].includes(p.subtitle_kind)
  &&typeof p.language==='string'&&/^[A-Za-z0-9_-]{1,30}$/.test(p.language)
  &&typeof p.track_id==='string'&&/^[A-Za-z0-9_-]{1,80}$/.test(p.track_id)
  &&p.coverage==='source_track_full_duration_candidate'&&p.semantic_status==='not_reviewed'&&p.semantic_completeness==='unknown'
  &&['source_body_sha256','raw_subtitle_sha256','source_metadata_sha256'].every(k=>hex(p[k]))
  &&p.raw_subtitle_sha256===report.asset_sha256&&p.source_body_sha256===report.asset_sha256
  &&typeof p.extractor_version==='string'&&/^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$/.test(p.extractor_version)
  &&p.extractor_method==='TikTokBaseIE._get_subtitles'
  &&Number.isFinite(p.first_seconds)&&Number.isFinite(p.last_seconds)&&p.first_seconds>=0&&p.first_seconds<=p.last_seconds
  &&p.last_seconds<=report.duration_seconds&&p.duration_seconds===report.duration_seconds,'invalid_transcript');
}

const videoOcrFields=reportFields.filter(key=>key!=='audio_source_job_id').concat('video_source_job_id','visual_provenance');
const visualFields=['provider','source_kind','source_video_sha256','source_reference_sha256','source_record_sha256','sampling_fps','sample_start','sample_end','sampled_frames','expected_frames','crop_top_origin','timestamp_kind','timestamp_uncertainty_seconds','frame_evidence_sha256','frame_evidence_format','coverage','spoken_transcript','semantic_completeness','truncated'];
function videoOcrReport(report){
 const p=report.visual_provenance;
 assert(keys(report,videoOcrFields)&&uuid(report.video_source_job_id)
  &&report.processor==='apple_vision_sampled_video_text'&&report.processing_profile==='apple_vision_video_hard_text_2fps_v1'
  &&report.model_manifest_sha256===null&&report.text_revision===null&&hex(report.diagnostics_sha256),'invalid_transcript');
 assert(keys(p,visualFields)&&p.provider==='apple_vision'&&p.source_kind==='sampled_video_text'
  &&['source_video_sha256','source_reference_sha256','source_record_sha256','frame_evidence_sha256'].every(key=>hex(p[key]))
  &&p.source_video_sha256===report.asset_sha256&&p.frame_evidence_sha256===report.diagnostics_sha256
  &&p.sampling_fps===2&&p.sample_start===0&&p.sample_end===report.duration_seconds
  &&positive(p.sampled_frames)&&positive(p.expected_frames)&&p.sampled_frames===p.expected_frames
  &&p.expected_frames===Math.ceil(report.duration_seconds*2)&&p.expected_frames<=14400
  &&Array.isArray(p.crop_top_origin)&&p.crop_top_origin.length===2&&p.crop_top_origin.every(Number.isFinite)
  &&0<=p.crop_top_origin[0]&&p.crop_top_origin[0]<p.crop_top_origin[1]&&p.crop_top_origin[1]<=1
  &&p.timestamp_kind==='resampled_frame_time'&&p.timestamp_uncertainty_seconds===.5
  &&p.frame_evidence_format==='gzip_json_array_v1'&&p.coverage==='all_scheduled_frames_processed'
  &&p.spoken_transcript===false&&p.semantic_completeness==='unknown'&&p.truncated===false,'invalid_transcript');
}

const declaredFields=['provider','content_id','content_type','subtitle_kind','language','track_id','source_body_sha256','raw_subtitle_sha256','source_projection_sha256','native_detail_canonical_sha256','source_record_sha256','source_file_sha256','source_format','extractor_version','extractor_method','discovery_method','coverage','semantic_status','semantic_completeness','first_seconds','last_seconds','duration_seconds'];
function declaredSubtitleReport(report,input){
 const p=report.subtitle_provenance;
 assert(keys(report,subtitleFields)&&report.subtitle_source_run_id===input.local_run_id
  &&report.processor==='yt_dlp_declared_track_v1'&&report.processing_profile==='yt_dlp_declared_track_v1'
  &&report.model_manifest_sha256===null&&report.diagnostics_sha256===null&&report.text_revision===null,'invalid_transcript');
 assert(keys(p,declaredFields)&&p.provider===report.platform&&p.content_id===report.content_id
  &&(report.platform==='zhihu'?['answer','article','zvideo'].includes(p.content_type):p.content_type===null)
  &&report.entity_ref===report.platform+':content:'+report.content_id+(report.platform==='zhihu'?':'+p.content_type:'')
  &&['human','platform_auto','unknown'].includes(p.subtitle_kind)&&typeof p.language==='string'&&/^[A-Za-z0-9_-]{1,30}$/.test(p.language)
  &&hex(p.track_id)&&['source_body_sha256','raw_subtitle_sha256','source_projection_sha256','native_detail_canonical_sha256','source_record_sha256','source_file_sha256'].every(k=>hex(p[k]))
  &&p.source_body_sha256===report.asset_sha256&&p.raw_subtitle_sha256===report.asset_sha256
  &&['vtt','srt'].includes(p.source_format)&&p.extractor_version==='2026.08.19'&&p.extractor_method==='yt_dlp.webvtt.parse_fragment'
  &&['html_track_v1','yt_dlp_subtitles_v1'].includes(p.discovery_method)
  &&p.coverage==='source_track_full_duration_candidate'&&p.semantic_status==='not_reviewed'&&p.semantic_completeness==='unknown'
  &&Number.isFinite(p.first_seconds)&&Number.isFinite(p.last_seconds)&&p.first_seconds>=0&&p.first_seconds<=p.last_seconds
  &&p.last_seconds<=report.duration_seconds&&p.duration_seconds===report.duration_seconds,'invalid_transcript');
}

export async function transcriptPayload(input){
  assert(keys(input,fields),'invalid_transcript');
  assert(['task_id','child_id','run_id','local_run_id','local_job_id'].every(key=>uuid(input[key]))&&positive(input.lease_epoch)&&input.lease_epoch<=2147483647&&hex(input.report_sha256),'invalid_transcript');
  assert(input.idempotency_key==='transcript:'+input.local_job_id&&Array.isArray(input.source_refs)&&input.source_refs.length>=1&&input.source_refs.length<=2000&&input.source_refs.every(ref=>keys(ref,['capture_id','envelope_hash'])&&uuid(ref.capture_id)&&hex(ref.envelope_hash))&&new Set(input.source_refs.map(ref=>ref.capture_id)).size===input.source_refs.length,'invalid_transcript');
  assert(typeof input.report_json==='string'&&new TextEncoder().encode(input.report_json).length<=200000&&!sensitive.test(input.report_json),'transcript_report_limit');
  let report;try{report=JSON.parse(input.report_json);}catch{throw Error('invalid_transcript');}
  if(report.schema==='crowd-declared-subtitle-report-v1')declaredSubtitleReport(report,input);
  else if(report.schema==='crowd-video-ocr-report-v1')videoOcrReport(report);
  else if(report.schema==='crowd-subtitle-report-v1')subtitleReport(report,input);
  else if(report.schema==='crowd-platform-subtitle-report-v1')platformSubtitleReport(report,input);
  else assert(keys(report,reportFields)&&report.schema==='crowd-transcript-report-v1'&&uuid(report.audio_source_job_id),'invalid_transcript');
  assert(report.job_id===input.local_job_id&&report.local_run_id===input.local_run_id&&['xiaohongshu','douyin','kuaishou','bilibili','weibo','tieba','zhihu'].includes(report.platform)&&typeof report.content_id==='string'&&/^[A-Za-z0-9_-]{1,200}$/.test(report.content_id),'invalid_transcript');
  const entities=[report.platform+':content:'+report.content_id,report.platform+':dynamic:'+report.content_id];if(report.platform==='zhihu')entities.push(...['answer','article','zvideo'].map(kind=>'zhihu:content:'+report.content_id+':'+kind));
  assert(report.platform!=='zhihu'||['answer','article','zvideo'].some(kind=>report.entity_ref==='zhihu:content:'+report.content_id+':'+kind),'invalid_transcript');
  assert(['asset_sha256','input_hash','full_result_file_sha256','text_sha256'].every(key=>hex(report[key]))&&(report.diagnostics_sha256===null||hex(report.diagnostics_sha256))&&(report.model_manifest_sha256===null||hex(report.model_manifest_sha256))&&(report.entity_ref===null||entities.includes(report.entity_ref)),'invalid_transcript');
  assert(report.semantic_review==='not_reviewed'&&report.cer===null&&report.human_groundtruth===false&&Number.isFinite(report.duration_seconds)&&report.duration_seconds>0&&report.duration_seconds<=7200&&positive(report.segment_count)&&report.segment_count<=8000&&positive(report.character_count)&&report.character_count<=240000&&Array.isArray(report.segments)&&report.segments.length===report.segment_count,'invalid_transcript');
  let characters=0;
  for(const row of report.segments){assert(plain(row)&&Object.keys(row).every(key=>['start','end','text','chunk_index'].includes(key))&&['start','end','text'].every(key=>Object.hasOwn(row,key))&&Number.isFinite(row.start)&&Number.isFinite(row.end)&&row.start>=0&&row.start<=row.end&&row.end<=report.duration_seconds&&typeof row.text==='string'&&row.text.trim()&&row.text.length<=24000&&(!Object.hasOwn(row,'chunk_index')||Number.isSafeInteger(row.chunk_index)&&row.chunk_index>=0&&row.chunk_index<512),'invalid_transcript');characters+=[...row.text].length;}
  if(['crowd-subtitle-report-v1','crowd-platform-subtitle-report-v1','crowd-declared-subtitle-report-v1'].includes(report.schema)){
    let previous=-1,cursor=0;
    for(const row of report.segments){assert(row.start>=previous&&row.start<row.end&&row.start-cursor<=Math.max(120,report.duration_seconds*.15),'invalid_transcript');previous=row.start;cursor=Math.max(cursor,row.end);}
    const p=report.subtitle_provenance,edge=Math.max(10,report.duration_seconds*.03);
    assert(p.first_seconds===report.segments[0].start&&p.last_seconds===cursor&&p.first_seconds<=edge&&report.duration_seconds-cursor<=edge,'invalid_transcript');
  }
  if(report.schema==='crowd-declared-subtitle-report-v1')assert(report.segments.every(row=>keys(row,['start','end','text'])),'invalid_transcript');
  if(report.schema==='crowd-video-ocr-report-v1'){
    let cursor=0;
    for(const row of report.segments){assert(keys(row,['start','end','text'])&&row.start<row.end&&row.start>=cursor,'invalid_transcript');cursor=row.end;}
  }
  assert(characters===report.character_count&&await sha(report.segments.map(row=>row.text).join('\n'))===report.text_sha256,'transcript_hash_conflict');
  let nodes=0;
  function scan(value,depth=0){assert(depth<=12&&++nodes<=20000,'transcript_report_limit');if(typeof value==='string')assert(!sensitive.test(value)&&!/[\uD800-\uDFFF]/u.test(value),'sensitive_transcript');else if(typeof value==='number')assert(Number.isFinite(value),'invalid_transcript');else if(Array.isArray(value))value.forEach(row=>scan(row,depth+1));else if(plain(value))for(const[key,row]of Object.entries(value)){assert(!/^(cookie|authorization|password|access_token|refresh_token|private_key|api_key|secret|audio|audio_base64|input_snapshot)$/i.test(key),'sensitive_transcript');scan(row,depth+1);}else assert(value===null||typeof value==='boolean','invalid_transcript');}
  scan(report);assert(await sha(input.report_json)===input.report_sha256,'transcript_hash_conflict');
  const normalized={...input,source_refs:[...input.source_refs].sort((a,b)=>a.capture_id.localeCompare(b.capture_id))};
  const canonical_transcript=artifactCanonical(normalized);
  return {...normalized,canonical_transcript,artifact_hash:await sha('crowd-transcript-artifact-v1\n'+canonical_transcript)};
}
