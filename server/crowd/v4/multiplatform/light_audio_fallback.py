"""Durable no-caption fallback, bound to a completed source and its remaining budget."""
import hashlib,time
from mc_runner import canonical,uid,write
from analysis_artifact import _read
from complete_video import source_reference,read_bytes
from media_native import _relative
WAITING={'media_processor_busy','media_processor_reconciliation_required'}


def reference(folder,run_id,cid):
    normalized,_=_read(folder/'normalized.json',32*1024*1024)
    if normalized.get('run_id')!=run_id or normalized.get('source_kind')!='mediacrawler_api' or normalized.get('reward_eligible') is not False:raise ValueError('light_fallback_source_changed')
    rows=[r for r in normalized.get('records',[]) if isinstance(r,dict) and r.get('platform')=='douyin' and r.get('kind')=='content' and r.get('content_id')==cid]
    if len(rows)!=1:raise ValueError('light_fallback_source_changed')
    body=rows[0];origin=body.get('origin',{});digest=hashlib.sha256(canonical({k:v for k,v in body.items() if k not in ('record_hash','discovery_kind')}).encode()).hexdigest()
    if body.get('record_hash')!=digest or body.get('source_kind')!='mediacrawler_api' or body.get('reward_eligible') is not False or origin.get('run_id')!=run_id:raise ValueError('light_fallback_source_changed')
    files=[r for r in normalized.get('files',[]) if isinstance(r,dict) and r.get('sha256')==origin.get('file_sha256')]
    if len(files)!=1:raise ValueError('light_fallback_source_changed')
    path=_relative(folder,files[0]['path'])
    if path.suffix!='.jsonl' or hashlib.sha256(read_bytes(path,50*1024*1024)).hexdigest()!=origin.get('file_sha256'):raise ValueError('light_fallback_source_changed')
    result=source_reference(folder,run_id,cid)
    if result.get('source_file_sha256')!=origin['file_sha256']:raise ValueError('light_fallback_source_changed')
    return result,digest


def prepare(state,folder,jobs):
    if (state.get('platform')!='douyin' or state.get('assets') or state.get('subtitle_jobs') or 'fallback_assets' in state
            or state.get('state') not in ('audio_unavailable','needs_attention')
            or type(state.get('source_requests')) is not int or state['source_requests']!=0
            or type(state.get('remote_model_calls')) is not int or state['remote_model_calls']!=0):return False
    phase,_=_read(folder/'phase.json',200000) if (folder/'phase.json').exists() else ({},None)
    if phase.get('media_reason')!='single_response_byte_limit':return False
    manifest,_=_read(folder/'manifest.json',200000);status,_=_read(folder/'status.json',200000)
    request=manifest.get('request',{})
    if request.get('platform')!='dy' or request.get('media') is not True or request.get('platform_options',{}).get('transcript_only') is not True:return False
    limit=manifest.get('request',{}).get('max_api_requests');spent=status.get('api_attempts')
    if (manifest.get('run_id')!=state['run_id'] or status.get('run_id')!=state['run_id'] or status.get('state')!='completed'
            or type(limit) is not int or type(spent) is not int or not 0<=spent<=limit<=500):
        state.update(state='needs_attention',fallback_reason='light_fallback_budget_unverified');return True
    if limit-spent<4:
        state.update(state='needs_attention',fallback_reason='light_fallback_insufficient_request_budget');return True
    normalized,_=_read(folder/'normalized.json',32*1024*1024)
    contents=[r for r in normalized.get('records',[]) if isinstance(r,dict) and r.get('kind')=='content' and r.get('platform')=='douyin']
    # One four-attempt reservation per source; do not multiply a remaining per-run quota.
    if len(contents)!=1:
        state.update(state='needs_attention',fallback_reason='light_fallback_source_ambiguous');return True
    cid=contents[0].get('content_id')
    try:ref,bodyhash=reference(folder,state['run_id'],cid)
    except (ValueError,KeyError,TypeError,OSError):
        state.update(state='needs_attention',fallback_reason='light_fallback_reference_unavailable');return True
    engine='mlx' if 'mlx' in jobs.capabilities().get('asr_engines',[]) else 'cpu'
    state.update(state='waiting',reason=None,fallback_reason=None,fallback_assets=[{'content_id':cid,'entity_ref':'douyin:content:'+cid,
        'source_reference_sha256':ref['reference_sha256'],'source_record_hash':bodyhash,'asr_engine':engine,
        'phase':'waiting_audio','state':'waiting','audio_job_id':None,'job_id':None,
        'budget':{'source_limit':limit,'source_attempts':spent,'remaining':limit-spent,'reserved_audio_attempts':4}}])
    return True


def previous_attempts(asset):
    return sum(row['network_attempts'] for row in asset.get('audio_attempt_chain',[]) if row.get('role','previous')=='previous')


def counts(state,asset,job=None):
    attempts=(job or {}).get('network_attempts')
    previous=previous_attempts(asset)
    allowance=asset['budget']['reserved_audio_attempts']-previous
    known=type(attempts) is int and 0<=attempts<=allowance
    state['source_requests']=previous+attempts if known else None
    state['source_requests_known_minimum']=previous
    state['source_requests_upper_bound']=asset['budget']['reserved_audio_attempts']
    asset['audio_network_attempts']=attempts if known else None
    asset['audio_network_attempts_status']='recorded' if known else 'unknown'
    if asset.get('audio_reference_variant') and job is not None:
        prior=[row for row in asset.get('audio_attempt_chain',[]) if row.get('role','previous')=='previous']
        asset['audio_attempt_chain']=prior+[{'role':'current','job_id':job['job_id'],
            'source_reference_sha256':asset['active_reference_sha256'],'network_attempts':attempts if known else None,'state':job['state']}]


def recover_variant(state,asset,folder,jobs,job):
    if (asset.get('variant_checked') or asset.get('audio_reference_variant') or job.get('state')!='failed'
            or job.get('reason') not in ('complete_audio_stream_missing','complete_audio_codec_not_supported')
            or type(job.get('network_attempts')) is not int or job['network_attempts']!=1):return False
    asset['variant_checked']=True
    try:ref=jobs.recover_audio_reference_after_no_audio(asset['audio_job_id'],folder)
    except (ValueError,OSError,KeyError,TypeError):return False
    if (ref.get('variant')!='native_default_after_verified_no_audio' or ref.get('previous_job_id')!=asset['audio_job_id']
            or ref.get('max_request_attempts')!=3 or ref.get('reference_sha256')==asset['source_reference_sha256']):return False
    asset.update(audio_attempt_chain=[{'role':'previous','job_id':asset['audio_job_id'],'source_reference_sha256':asset['source_reference_sha256'],
        'network_attempts':1,'state':'failed','reason':job['reason']}],previous_audio_job_id=asset['audio_job_id'],
        audio_reference_variant=ref['variant'],active_reference_sha256=ref['reference_sha256'],
        audio_job_id=None,phase='waiting_audio',state='waiting',reason=None,audio_network_attempts=None)
    state.update(state='waiting',reason=None,fallback_reason=None,source_requests=1,
        source_requests_known_minimum=1,source_requests_upper_bound=4)
    return True


def _matches(jobs,state,asset,kind,timestamp,parent=None):
    rows=jobs.list(state['run_id']).get('jobs',[])
    return [job for job in rows if job.get('run_id')==state['run_id'] and job.get('platform')=='douyin'
        and job.get('content_id')==asset['content_id'] and job.get('kind')==kind
        and type(job.get('created_at')) in (int,float) and job['created_at']>=timestamp
        and (job.get('source_reference_sha256')==asset.get('active_reference_sha256',asset['source_reference_sha256']) if parent is None else job.get('audio_reference_binding',{}).get('source_job_id')==parent)]


def tick(state,path,folder,jobs):
    assets=state.get('fallback_assets')
    if not assets:return False
    if len(assets)!=1:raise ValueError('light_fallback_source_ambiguous')
    asset=assets[0]
    may_recover=(asset['state']=='failed' and asset.get('phase')=='audio_processing' and not asset.get('variant_checked')
        and asset.get('reason') in ('complete_audio_stream_missing','complete_audio_codec_not_supported'))
    if asset['state'] in ('completed','failed','cancelled','interrupted_unknown') and not may_recover and not (asset['state']=='interrupted_unknown' and asset.get('phase') in ('dispatching_audio','dispatching_asr')):
        state['state']='completed' if asset['state']=='completed' else 'needs_attention';write(path,state);return True
    try:
        ref,bodyhash=reference(folder,state['run_id'],asset['content_id'])
        if ref['reference_sha256']!=asset['source_reference_sha256'] or bodyhash!=asset['source_record_hash']:raise ValueError('light_fallback_source_changed')
        if asset['phase']=='dispatching_audio' and not asset.get('audio_job_id'):
            matches=_matches(jobs,state,asset,'complete_audio',asset['audio_dispatch_at'])
            if len(matches)!=1:raise OSError('light_fallback_audio_dispatch_unknown')
            asset.update(audio_job_id=matches[0]['job_id'],phase='audio_processing',state='processing',reason=None)
        if asset['phase']=='waiting_audio':
            if asset.get('audio_reference_variant'):
                ref=jobs.recover_audio_reference_after_no_audio(asset['previous_audio_job_id'],folder)
                if (ref.get('reference_sha256')!=asset['active_reference_sha256'] or ref.get('max_request_attempts')!=3
                        or ref.get('previous_job_id')!=asset['previous_audio_job_id']):raise ValueError('light_fallback_source_changed')
            manifest,_=_read(folder/'manifest.json',200000);status,_=_read(folder/'status.json',200000)
            if manifest.get('request',{}).get('max_api_requests')!=asset['budget']['source_limit'] or status.get('api_attempts')!=asset['budget']['source_attempts']:raise ValueError('light_fallback_budget_changed')
            asset.update(phase='dispatching_audio',audio_dispatch_at=time.time());counts(state,asset);write(path,state)
            try:job=jobs.start_audio_reference(ref)
            except ValueError as error:
                if str(error) in WAITING:asset['phase']='waiting_audio';state['source_requests']=previous_attempts(asset);state['fallback_reason']=str(error);write(path,state);return True
                raise
            asset.update(audio_job_id=uid(job['job_id']),phase='audio_processing');counts(state,asset,job)
            write(path,state);return True
        if asset['phase']=='audio_processing':
            job=jobs.status(asset['audio_job_id'])
            if (job.get('kind')!='complete_audio' or job.get('run_id')!=state['run_id'] or job.get('platform')!='douyin'
                    or job.get('content_id')!=asset['content_id'] or job.get('source_reference_sha256')!=asset.get('active_reference_sha256',asset['source_reference_sha256'])):raise ValueError('light_fallback_job_changed')
            if asset.get('audio_reference_variant') and (job.get('audio_reference_variant')!=asset['audio_reference_variant']
                    or job.get('previous_audio_job_id')!=asset['previous_audio_job_id']
                    or job.get('network_budget',{}).get('max_request_attempts')!=3):raise ValueError('light_fallback_budget_unverified')
            counts(state,asset,job)
            if job['state'] in ('failed','cancelled','interrupted_unknown'):
                asset.update(state=job['state'],reason=job.get('reason','light_fallback_audio_failed'))
                state.update(state='needs_attention',fallback_reason=asset['reason'])
                recover_variant(state,asset,folder,jobs,job)
            elif job['state']=='completed':
                attempts=job.get('network_attempts')
                if type(attempts) is not int or not 0<=attempts<=asset['budget']['reserved_audio_attempts']-previous_attempts(asset):raise ValueError('light_fallback_budget_unverified')
                asset.update(phase='waiting_asr',audio_asset_sha256=job['asset_sha256'],audio_network_attempts=attempts)
            else:state['state']='processing'
            write(path,state);return True
        if asset['phase']=='dispatching_asr' and not asset.get('job_id'):
            matches=_matches(jobs,state,asset,'asr',asset['asr_dispatch_at'],asset['audio_job_id'])
            if len(matches)!=1:raise OSError('light_fallback_asr_dispatch_unknown')
            asset.update(job_id=matches[0]['job_id'],asr_run_id=matches[0]['run_id'],phase='asr_processing',state='processing',reason=None)
        if asset['phase']=='waiting_asr':
            asset.update(phase='dispatching_asr',asr_dispatch_at=time.time());write(path,state)
            try:job=jobs.start_asr_from_audio_job(asset['audio_job_id'],folder,entity_ref=asset['entity_ref'],asr_engine=asset['asr_engine'])
            except ValueError as error:
                if str(error) in WAITING:asset['phase']='waiting_asr';state['fallback_reason']=str(error);write(path,state);return True
                raise
            asset.update(job_id=uid(job['job_id']),asr_run_id=job['run_id'],phase='asr_processing',state='processing')
            write(path,state);return True
        if asset['phase']=='asr_processing':
            job=jobs.status(asset['job_id'])
            if (job.get('kind')!='asr' or job.get('run_id')!=state['run_id'] or job.get('platform')!='douyin' or job.get('content_id')!=asset['content_id']
                    or job.get('audio_reference_binding',{}).get('source_job_id')!=asset['audio_job_id'] or job.get('asset_sha256')!=asset['audio_asset_sha256']):raise ValueError('light_fallback_job_changed')
            asset.update(state=job['state'])
            if job['state'] in ('failed','cancelled','interrupted_unknown'):state['fallback_reason']=job.get('reason','light_fallback_asr_failed')
            state['state']='completed' if job['state']=='completed' else 'needs_attention' if job['state'] in ('failed','cancelled','interrupted_unknown') else 'processing'
    except (OSError,ValueError,KeyError,TypeError):
        asset.update(state='interrupted_unknown',reason='light_fallback_dispatch_or_binding_unknown');state['state']='needs_attention';state['fallback_reason']=asset['reason']
    write(path,state);return True
