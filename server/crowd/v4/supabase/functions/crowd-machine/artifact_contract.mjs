import {assert,canonical,hex,sha,uuid} from './contract.mjs';

const plain=v=>v&&typeof v==='object'&&!Array.isArray(v);
const integer=(v,low,high)=>Number.isSafeInteger(v)&&v>=low&&v<=high;
const keys=(v,list)=>plain(v)&&Object.keys(v).length===list.length&&list.every(k=>Object.hasOwn(v,k));
const sensitive=/(?:cookie|authorization|password|access_token|refresh_token|private_key|api_key|secret)\s*[=:]/i;
const sensitiveKey=/^(cookie|authorization|password|access_token|refresh_token|private_key|api_key|secret|input_snapshot|analysis_batches|batch_snapshot|audio|audio_base64)$/i;
const fields=['idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','source_refs','local_job_id','input_snapshot_hash','full_result_file_sha256','report_sha256','provider','provider_version','model_version','model_version_status','coverage','report_json'];
const coverageFields=['state','batches_completed','batches_total','selected_segments','selected_characters','source_refs','semantic_review','automatic_retry'];

export function artifactCanonical(value,depth=0,budget={nodes:0}){
  assert(depth<=12&&++budget.nodes<=20000,'artifact_report_limit');
  if(value===null||typeof value!=='object')return canonical(value);
  if(Array.isArray(value))return '['+value.map(row=>artifactCanonical(row,depth+1,budget)).join(',')+']';
  assert(plain(value),'invalid_artifact');
  return '{'+Object.keys(value).sort().map(key=>canonical(key)+':'+artifactCanonical(value[key],depth+1,budget)).join(',')+'}';
}

export function validateArtifactCoverage(value){
  assert(keys(value,coverageFields),'invalid_artifact_coverage');
  assert(value.state==='all_selected_segments_analyzed'&&value.semantic_review==='not_reviewed'&&value.automatic_retry===false&&integer(value.batches_total,1,16)&&value.batches_completed===value.batches_total&&integer(value.selected_segments,1,8000)&&integer(value.selected_characters,1,240000),'invalid_artifact_coverage');
  assert(Array.isArray(value.source_refs)&&value.source_refs.length===value.selected_segments&&new Set(value.source_refs).size===value.source_refs.length,'invalid_artifact_coverage');
  const groups=new Map();
  for(const ref of value.source_refs){
    const match=typeof ref==='string'&&/^derived:([a-f0-9-]{36}):(0|[1-9][0-9]{0,3})$/.exec(ref);
    assert(match&&uuid(match[1])&&Number(match[2])<8000,'invalid_artifact_coverage');
    if(!groups.has(match[1]))groups.set(match[1],[]);groups.get(match[1]).push(Number(match[2]));
  }
  assert(groups.size<=5&&[...groups.values()].every(values=>values.sort((a,b)=>a-b).every((value,index)=>value===index)),'invalid_artifact_coverage');
}

export async function artifactPayload(input){
  assert(keys(input,fields),'invalid_artifact');
  assert(['task_id','child_id','run_id','local_run_id','local_job_id'].every(k=>uuid(input[k]))&&integer(input.lease_epoch,1,2147483647)&&['input_snapshot_hash','full_result_file_sha256','report_sha256'].every(k=>hex(input[k])),'invalid_artifact');
  assert(typeof input.idempotency_key==='string'&&/^[A-Za-z0-9_.:-]{1,160}$/.test(input.idempotency_key)&&input.provider==='codex_cli'&&typeof input.provider_version==='string'&&input.provider_version.length>=1&&input.provider_version.length<=200&&!/[\x00-\x1f]/.test(input.provider_version)&&!sensitive.test(input.provider_version),'invalid_artifact');
  assert(input.model_version===null&&input.model_version_status==='not_recorded_by_local_provider','invalid_artifact');
  assert(Array.isArray(input.source_refs)&&input.source_refs.length>=1&&input.source_refs.length<=2000&&input.source_refs.every(ref=>keys(ref,['capture_id','envelope_hash'])&&uuid(ref.capture_id)&&hex(ref.envelope_hash))&&new Set(input.source_refs.map(ref=>ref.capture_id)).size===input.source_refs.length,'invalid_artifact');
  validateArtifactCoverage(input.coverage);
  assert(typeof input.report_json==='string'&&new TextEncoder().encode(input.report_json).length<=200000&&!sensitive.test(input.report_json),'artifact_report_limit');
  let report;try{report=JSON.parse(input.report_json);}catch{throw new Error('invalid_artifact_report');}
  const allowed=['content_analysis','comment_statistics','comment_labels','labeler','label_schema','review_status','full_analysis_coverage','snapshot_hash','prompt_version','provider','provider_version'];
  assert(plain(report)&&Object.keys(report).every(k=>allowed.includes(k))&&plain(report.content_analysis)&&typeof report.content_analysis.summary==='string'&&report.content_analysis.summary.trim()&&report.snapshot_hash===input.input_snapshot_hash&&report.provider===input.provider&&report.provider_version===input.provider_version&&report.review_status==='unreviewed_model_analysis','invalid_artifact_report');
  validateArtifactCoverage(report.full_analysis_coverage);
  assert(artifactCanonical(report.full_analysis_coverage)===artifactCanonical(input.coverage),'invalid_artifact_coverage');
  let nodes=0;
  function walk(value,depth=0){
    assert(depth<=12&&++nodes<=20000,'artifact_report_limit');
    if(typeof value==='string')assert(value.length<=200000&&!sensitive.test(value)&&!/[\uD800-\uDFFF]/u.test(value),'sensitive_artifact');
    else if(typeof value==='number')assert(Number.isFinite(value),'invalid_artifact_report');
    else if(Array.isArray(value))value.forEach(row=>walk(row,depth+1));
    else if(plain(value))for(const [key,row]of Object.entries(value)){assert(!sensitiveKey.test(key),'sensitive_artifact');walk(row,depth+1);}
    else assert(value===null||typeof value==='boolean','invalid_artifact_report');
  }
  walk(report);
  assert(await sha(input.report_json)===input.report_sha256,'artifact_hash_conflict');
  const normalized={...input,source_refs:[...input.source_refs].sort((a,b)=>a.capture_id.localeCompare(b.capture_id))};
  const canonical_artifact=artifactCanonical(normalized);
  return {...normalized,canonical_artifact,artifact_hash:await sha('crowd-analysis-artifact-v1\n'+canonical_artifact)};
}
