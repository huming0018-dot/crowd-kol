"""Publish completed full analysis separately from source captures; no model/source work."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from analysis_contract import _hash
from mc_runner import canonical, contains_secret, uid, write

HEX=re.compile(r'[a-f0-9]{64}')


def _safe_ancestors(path):
    path=Path(path).absolute()
    aliases={'/tmp':'/private/tmp','/var':'/private/var'}
    for part in (path,*path.parents):
        if part.is_symlink() and not (str(part) in aliases and str(part.resolve())==aliases[str(part)]):
            raise ValueError('unsafe_analysis_artifact_file')


def _read(path,limit):
    _safe_ancestors(path)
    if path.is_symlink():raise ValueError('unsafe_analysis_artifact_file')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid() or info.st_size>limit:raise ValueError('unsafe_analysis_artifact_file')
        raw=os.read(fd,limit+1)
        after=os.fstat(fd)
        if len(raw)>limit or (info.st_size,info.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('analysis_artifact_changed')
        return json.loads(raw),hashlib.sha256(raw).hexdigest()
    finally:os.close(fd)


def prepare_analysis_artifact(jobs,client,job_id):
    if client is None:raise ValueError('analysis_artifact_cloud_not_configured')
    if getattr(client,'role',None)!='owner':raise ValueError('principal_denied')
    folder=jobs.folder(uid(job_id))
    state,_=_read(folder/'state.json',65536)
    result,result_sha=_read(folder/'result.json',8*1024*1024)
    snapshot,_=_read(folder/'snapshot.json',8*1024*1024)
    if state.get('state')!='completed' or state.get('job_id')!=job_id:raise ValueError('analysis_artifact_not_completed')
    if snapshot.get('platform')!=state.get('platform') or snapshot.get('content_id')!=state.get('content_id'):raise ValueError('analysis_artifact_snapshot_changed')
    if result.get('input_snapshot')!=snapshot or result.get('snapshot_hash')!=state.get('snapshot_hash') or snapshot.get('snapshot_hash')!=state.get('snapshot_hash') or _hash({k:v for k,v in snapshot.items() if k!='snapshot_hash'})!=state.get('snapshot_hash'):raise ValueError('analysis_artifact_snapshot_changed')
    if result.get('provider')!=state.get('provider') or result.get('provider_version')!=state.get('provider_version'):raise ValueError('analysis_artifact_provider_changed')
    coverage=result.get('full_analysis_coverage')
    derived=snapshot.get('derived_inputs',[])
    refs=['derived:'+item['job_id']+':'+str(index) for item in derived for index in range(len(item['segments']))]
    characters=sum(len(segment['text']) for item in derived for segment in item['segments'])
    if not isinstance(coverage,dict) or coverage.get('state')!='all_selected_segments_analyzed' or not refs or len(set(refs))!=len(refs) or coverage.get('source_refs')!=refs or coverage.get('selected_segments')!=len(refs) or coverage.get('selected_characters')!=characters or coverage.get('semantic_review')!='not_reviewed' or coverage.get('automatic_retry') is not False or coverage.get('batches_completed')!=len(snapshot.get('analysis_batches',[])) or coverage.get('batches_total')!=len(snapshot.get('analysis_batches',[])) or state.get('completed_batches')!=coverage.get('batches_completed') or state.get('total_batches')!=coverage.get('batches_total'):raise ValueError('analysis_artifact_coverage_incomplete')
    local_run=uid(state.get('run_id'))
    listing=client.call('task_list')
    matches=set()
    for task in listing.get('tasks',[]):
        for child in task.get('children',[]):
            attempts=child.get('attempts',[])
            for attempt in attempts:
                if attempt.get('local_run_id')==local_run:
                    matches.add((task['task_id'],child['child_id'],attempt['run_id'],attempt['lease_epoch']))
    if len(matches)!=1:raise ValueError('analysis_artifact_source_ambiguous')
    task_id,child_id,run_id,epoch=matches.pop()
    if type(epoch) is not int or not 1<=epoch<=2147483647:raise ValueError('analysis_artifact_source_binding_denied')
    source=client.call('results',{'task_id':task_id})
    source_refs=[];records=[]
    for item in source.get('items',[]):
        record=item.get('record',{});receipt=item.get('receipt',{})
        if receipt.get('run_id')!=run_id or receipt.get('lease_epoch')!=epoch:continue
        if record.get('platform')!=state.get('platform') or record.get('content_id')!=state.get('content_id') or record.get('kind') not in ('content','dynamic','comment'):continue
        if record.get('origin',{}).get('run_id')!=local_run or type(receipt.get('lease_epoch')) is not int or receipt.get('reward_eligible') is not False or any(receipt.get(k)!=v for k,v in {'task_id':task_id,'child_id':child_id,'run_id':run_id,'lease_epoch':epoch,'status':'received'}.items()):raise ValueError('analysis_artifact_source_binding_denied')
        capture_id=uid(receipt.get('capture_id'));envelope_hash=receipt.get('envelope_hash')
        if not isinstance(envelope_hash,str) or not HEX.fullmatch(envelope_hash):raise ValueError('analysis_artifact_source_binding_denied')
        source_refs.append({'capture_id':capture_id,'envelope_hash':envelope_hash});records.append(record)
    if not source_refs or len(source_refs)>2000 or len({ref['capture_id'] for ref in source_refs})!=len(source_refs):raise ValueError('analysis_artifact_source_binding_denied')
    content=snapshot['content']
    identities=set();types=set()
    for row in records:
        row_types={row[key] for key in ('content_type','source_content_type') if isinstance(row.get(key),str) and row[key]}
        if len(row_types)>1:raise ValueError('analysis_artifact_source_binding_denied')
        types.update(row_types)
        if row.get('kind') in ('content','dynamic'):identities.add((row['kind'],next(iter(row_types),None)))
    if len(identities)!=1 or len(types)>1:raise ValueError('analysis_artifact_source_binding_denied')
    kind,content_type=next(iter(identities))
    if kind!=content.get('kind','content') or content.get('content_type') is not None and content_type!=content['content_type']:raise ValueError('analysis_artifact_source_binding_denied')
    if not any(row.get('kind') in ('content','dynamic') and row.get('title','')==content['title'] and row.get('body','')==content['text'] for row in records):raise ValueError('analysis_artifact_source_binding_denied')
    for comment in snapshot.get('comments',[]):
        if not any(row.get('kind')=='comment' and row.get('comment_id')==comment['comment_id'] and hashlib.sha256(row.get('text','').encode()).hexdigest()==comment['text_sha256'] for row in records):raise ValueError('analysis_artifact_source_binding_denied')
    report={k:v for k,v in result.items() if k!='input_snapshot'}
    report_json=json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    if len(report_json.encode())>200000:raise ValueError('artifact_report_limit')
    if contains_secret(report_json):raise ValueError('sensitive_artifact')
    return {'idempotency_key':'analysis:'+job_id,'task_id':task_id,'child_id':child_id,'run_id':run_id,'lease_epoch':epoch,'local_run_id':local_run,
            'source_refs':sorted(source_refs,key=lambda row:row['capture_id']),'local_job_id':job_id,'input_snapshot_hash':state['snapshot_hash'],
            'full_result_file_sha256':result_sha,'report_sha256':hashlib.sha256(report_json.encode()).hexdigest(),
            'provider':state['provider'],'provider_version':state['provider_version'],'model_version':None,'model_version_status':'not_recorded_by_local_provider','coverage':coverage,'report_json':report_json}


def publish_analysis_artifact(jobs,client,job_id):
    payload=prepare_analysis_artifact(jobs,client,job_id)
    _safe_ancestors(jobs.root.parent/'analysis-artifact-receipts')
    response=client.call('artifact_put',payload)
    receipt=response.get('receipt',{})
    artifact_hash=hashlib.sha256(('crowd-analysis-artifact-v1\n'+canonical(payload)).encode()).hexdigest()
    expected={k:payload[k] for k in ('task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','source_refs','input_snapshot_hash','full_result_file_sha256','report_sha256','coverage')}
    if any(canonical(receipt.get(k))!=canonical(value) for k,value in expected.items()) or receipt.get('artifact_hash')!=artifact_hash or receipt.get('status')!='received' or receipt.get('artifact_kind')!='analysis_report' or receipt.get('reward_eligible') is not False:raise ValueError('analysis_artifact_receipt_mismatch')
    uid(receipt.get('artifact_id'))
    folder=jobs.root.parent/'analysis-artifact-receipts'
    _safe_ancestors(folder)
    if folder.is_symlink():raise ValueError('unsafe_analysis_artifact_file')
    folder.mkdir(mode=0o700,exist_ok=True)
    path=folder/(job_id+'.json')
    if path.is_symlink() or path.exists() and path.stat().st_nlink!=1:raise ValueError('unsafe_analysis_artifact_file')
    write(path,{'schema':'crowd-analysis-artifact-local-receipt-v1','job_id':job_id,'endpoint_sha256':hashlib.sha256(client.endpoint.encode()).hexdigest(),'receipt':receipt})
    return {'ok':True,'receipt':receipt,'replayed':response.get('replayed') is True,'source_requests':0,'model_calls':0,'artifact_kind':'analysis_report'}
