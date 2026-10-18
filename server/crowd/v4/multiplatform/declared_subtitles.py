"""One bounded caption request on a declared same-response track, then a source-bound job."""
import hashlib,json,math,os,re,time,uuid
from pathlib import Path
from analysis_artifact import _read,_safe_ancestors
from mc_runner import read,write,uid,canonical,contains_secret,normalize,BridgeError
from complete_video import read_bytes
from subtitle_discovery import discover,parse_saved_track,encoded,PLATFORMS,track_url,CID

MAX_BYTES=200000
PROFILE='yt_dlp_declared_track_v1'

def _paths(output,platform,cid,ctype=None):
    if platform not in PLATFORMS.values() or not isinstance(cid,str) or not CID.fullmatch(cid) or ctype not in (None,'answer','article','zvideo'):raise ValueError('subtitle_identity_invalid')
    from tieba_media import safe_directory
    folder=safe_directory(Path(output)/platform/'declared-subtitles');stem=cid+('.'+ctype if ctype else '')
    paths={key:folder/(stem+suffix) for key,suffix in [('ledger','.dispatch.json'),('metadata','.metadata.json'),('raw','.source'),('result','.json')]}
    for path in paths.values():_safe_ancestors(path)
    return paths

async def fetch(platform,detail,output,cid,duration,ctype=None,client=None):
    """Runs inside the normal runner httpx budget. No retries, redirects, cookies import or model."""
    output=Path(output);run=output.parent;run_id=uid(run.name)
    manifest,_=_read(run/'manifest.json',200000);phase,_=_read(run/'phase.json',200000);status,_=_read(run/'status.json',200000)
    if status.get('run_id')!=run_id or status.get('state')!='running':raise ValueError('subtitle_not_active_native_run')
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<duration<=7200:raise ValueError('subtitle_duration_invalid')
    if client is not None and (any(re.search('authorization|cookie|token|secret|api[-_]key',k,re.I) for k in getattr(client,'headers',{})) or bool(getattr(client,'cookies',None))):raise ValueError('subtitle_client_credentials_rejected')

    request=manifest.get('request',{});attempts=phase.get('api_attempts');limit=request.get('max_api_requests')
    if (manifest.get('run_id')!=run_id or PLATFORMS.get(request.get('platform'))!=platform or request.get('media') is not True
        or type(attempts) is not int or type(limit) is not int or not 0<=attempts<=limit):raise ValueError('subtitle_budget_invalid')
    paths=_paths(output,platform,cid,ctype)
    if paths['ledger'].exists():return read(paths['ledger']) # Unknown/failed dispatch never triggers another request.
    projection,candidates=discover(platform,detail,cid,ctype);projection['local_run_id']=run_id
    eligible=[r for r in candidates if r['language'] in ('zh','zh-CN','zh-Hans','cmn')]
    if not eligible:return {'status':'unavailable','reason':'declared_chinese_track_unavailable','source_requests':0}
    if attempts>=limit:return {'status':'unavailable','reason':'subtitle_request_budget_exhausted','source_requests':0}
    chosen=eligible[0];track={k:v for k,v in chosen.items() if k!='url'}
    if track_url(platform,chosen['url'])!=chosen['url']:raise ValueError('subtitle_track_invalid')
    ledger={'schema':'crowd-declared-subtitle-dispatch-v1','run_id':run_id,'platform':platform,'content_id':cid,'content_type':ctype,
        'status':'dispatch_unknown','reason':'subtitle_dispatch_in_progress','source_requests':None,'reserved_requests':1,
        'track_url_sha256':track['track_url_sha256'],'source_projection_sha256':hashlib.sha256(encoded(projection)).hexdigest()}
    # Permanent dispatch reservation survives transport failure/process loss; never auto-retry.
    with os.fdopen(os.open(paths['ledger'],os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as stream:stream.write(encoded(ledger))
    downloaded=False
    try:
        if client is None:
            import httpx
            async with httpx.AsyncClient(timeout=30,follow_redirects=False,trust_env=False) as own:
                raw=await _download(own,chosen['url'])
        else:raw=await _download(client,chosen['url'])
        downloaded=True
        parsed=parse_saved_track(raw,track,duration,projection)
        if len(encoded(parsed))>MAX_BYTES:raise ValueError('subtitle_result_limit')
        if contains_secret(encoded(parsed).decode()):raise ValueError('sensitive_subtitle')
        for key,value in [('metadata',encoded(projection)),('raw',raw),('result',encoded(parsed))]:
            with os.fdopen(os.open(paths[key],os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as stream:stream.write(value)
        ledger.update(status=parsed['status'],reason=None if parsed['status']=='available' else 'subtitle_coverage_unknown',source_requests=1)
    except Exception:
        # A dispatch was attempted; lack of a transport receipt cannot be reported as zero wire requests.
        ledger.update(status='failed',reason='declared_subtitle_fetch_failed',source_requests=1 if downloaded else None)
    write(paths['ledger'],ledger)
    return ledger

async def _download(client,url):
    raw=b''
    async with client.stream('GET',url,follow_redirects=False) as response:
        if response.status_code!=200:raise ValueError('subtitle_http_failed')
        async for part in response.aiter_bytes(65536):
            if len(raw)+len(part)>MAX_BYTES:raise ValueError('subtitle_response_limit')
            raw+=part
    return raw


def _load_source(folder,cid,ctype=None):
    from media_native import _relative
    run_id=uid(Path(folder).name);manifest,_=_read(Path(folder)/'manifest.json',200000);status,_=_read(Path(folder)/'status.json',200000)
    normalized,_=_read(Path(folder)/'normalized.json',32*1024*1024);platform=PLATFORMS.get(manifest.get('request',{}).get('platform'))
    if (platform is None or manifest.get('run_id')!=run_id or status.get('run_id')!=run_id or status.get('state')!='completed'
        or manifest.get('request',{}).get('media') is not True or normalized.get('run_id')!=run_id
        or normalized.get('source_kind')!='mediacrawler_api' or normalized.get('reward_eligible') is not False):raise ValueError('subtitle_source_changed')
    bodies=[r for r in normalized.get('records',[]) if r.get('kind')=='content' and r.get('platform')==platform and r.get('content_id')==cid and (platform!='zhihu' or r.get('content_type')==ctype)]
    if len(bodies)!=1:raise ValueError('subtitle_source_ambiguous')
    body=bodies[0];origin=body.get('origin',{});record_sha=hashlib.sha256(canonical({k:v for k,v in body.items() if k not in ('record_hash','discovery_kind')}).encode()).hexdigest()
    if body.get('record_hash')!=record_sha or origin.get('run_id')!=run_id or body.get('reward_eligible') is not False or body.get('source_kind')!='mediacrawler_api':raise ValueError('subtitle_source_changed')
    files=[r for r in normalized.get('files',[]) if r.get('sha256')==origin.get('file_sha256')]
    if len(files)!=1:raise ValueError('subtitle_source_changed')
    raw_source=_relative(folder,files[0]['path'])
    if raw_source.suffix!='.jsonl' or type(origin.get('line')) is not int or origin['line']<1:raise ValueError('subtitle_source_changed')
    original=read_bytes(raw_source,50*1024*1024);lines=original.splitlines()
    if hashlib.sha256(original).hexdigest()!=origin.get('file_sha256') or origin['line']>len(lines):raise ValueError('subtitle_source_changed')
    # Rebuild from the exact native JSONL line: a recomputed hash on forged normalized text is not evidence.
    try:replay=normalize(manifest['request']['platform'],body['kind'],json.loads(lines[origin['line']-1]),origin)
    except (ValueError,TypeError,KeyError,BridgeError):raise ValueError('subtitle_source_changed') from None
    if replay['record_hash']!=body['record_hash']:raise ValueError('subtitle_source_changed')
    paths=_paths(Path(folder)/'output',platform,cid,ctype);projection,_=_read(paths['metadata'],MAX_BYTES);result,result_sha=_read(paths['result'],MAX_BYTES)
    raw=read_bytes(paths['raw'],MAX_BYTES);ledger,_=_read(paths['ledger'],MAX_BYTES)
    if (projection.get('local_run_id')!=run_id or projection.get('provider')!=platform or projection.get('content_id')!=cid or projection.get('content_type')!=ctype
        or ledger.get('status')!='available' or ledger.get('source_requests')!=1 or ledger.get('reserved_requests')!=1
        or ledger.get('run_id')!=run_id or ledger.get('platform')!=platform or ledger.get('content_id')!=cid or ledger.get('content_type')!=ctype
        or ledger.get('source_projection_sha256')!=hashlib.sha256(encoded(projection)).hexdigest()
        or hashlib.sha256(raw).hexdigest()!=result.get('raw_subtitle_sha256')
        or result.get('status')!='available' or result.get('track',{}).get('track_url_sha256')!=ledger.get('track_url_sha256')):raise ValueError('subtitle_source_changed')
    checked=parse_saved_track(raw,result.get('track'),result.get('duration_seconds'),projection)
    if checked!=result:raise ValueError('subtitle_source_changed')
    entity=platform+':content:'+cid+(':'+ctype if platform=='zhihu' else '')
    return platform,body,result,result_sha,entity


def register(jobs,folder,cid,ctype=None):
    platform,body,result,result_sha,entity=_load_source(Path(folder),cid,ctype);run_id=uid(Path(folder).name)
    job_id=str(uuid.uuid5(uuid.UUID(run_id),'declared-subtitle:'+entity+':'+result_sha))
    state={'job_id':job_id,'run_id':run_id,'kind':'subtitle','state':'completed','platform':platform,'content_id':cid,'entity_ref':entity,'content_type':ctype,
        'source_record_hash':body['record_hash'],'asset_sha256':result['raw_subtitle_sha256'],'result_sha256':result_sha,
        'input_hash':hashlib.sha256((run_id+':'+entity+':'+result_sha).encode()).hexdigest(),'processing_profile':PROFILE,'created_at':time.time()}
    target=jobs.root.parent/'subtitle-jobs'/(job_id+'.json');_safe_ancestors(target);target.parent.mkdir(mode=0o700,exist_ok=True)
    if not target.exists():write(target,state)
    return load_job(jobs,job_id)


def load_job(jobs,job_id):
    job_id=uid(job_id);state,_=_read(jobs.root.parent/'subtitle-jobs'/(job_id+'.json'),MAX_BYTES);run_id=uid(state.get('run_id'))
    folder=Path(jobs.subtitle_run_folder(run_id))
    if folder.name!=run_id:raise ValueError('subtitle_source_changed')
    platform,body,result,result_sha,entity=_load_source(folder,state.get('content_id'),state.get('content_type'))
    expected=str(uuid.uuid5(uuid.UUID(run_id),'declared-subtitle:'+entity+':'+result_sha))
    if (job_id!=expected or state.get('job_id')!=job_id or state.get('kind')!='subtitle' or state.get('state')!='completed'
        or state.get('processing_profile')!=PROFILE or state.get('platform')!=platform or state.get('entity_ref')!=entity
        or state.get('asset_sha256')!=result['raw_subtitle_sha256'] or state.get('source_record_hash')!=body['record_hash'] or state.get('result_sha256')!=result_sha
        or state.get('input_hash')!=hashlib.sha256((run_id+':'+entity+':'+result_sha).encode()).hexdigest()):raise ValueError('subtitle_source_changed')
    state['result']=[{'platform':platform,'content_id':state['content_id'],'kind':'transcript','evidence':{'asset_sha256':state['asset_sha256'],
        'segments':result['segments'],'duration_seconds':result['duration_seconds'],'processor':PROFILE,'semantic_review':'not_reviewed','timeline':'absolute_seconds',
        'declared_subtitle_provenance':{'track':result['track'],'source_projection_sha256':result['source_projection_sha256'],'raw_subtitle_sha256':result['raw_subtitle_sha256'],
            'source_record_sha256':body['record_hash'],'semantic_completeness':'unknown'}}}]
    return state


def subtitle_report(jobs,job_id):
    from native_subtitles import VERSION
    state=load_job(jobs,job_id);folder=jobs.subtitle_run_folder(state['run_id'])
    platform,body,result,result_sha,entity=_load_source(folder,state['content_id'],state.get('content_type'))
    paths=_paths(Path(folder)/'output',platform,state['content_id'],state.get('content_type'));projection,_=_read(paths['metadata'],MAX_BYTES)
    rows=result['segments'];track=result['track']
    provenance={'provider':platform,'content_id':state['content_id'],'content_type':state.get('content_type'),'subtitle_kind':track['subtitle_kind'],
        'language':track['language'],'track_id':track['track_url_sha256'],'source_body_sha256':state['asset_sha256'],'raw_subtitle_sha256':state['asset_sha256'],
        'source_projection_sha256':result['source_projection_sha256'],'native_detail_canonical_sha256':projection['native_detail_canonical_sha256'],
        'source_record_sha256':body['record_hash'],'source_file_sha256':body['origin']['file_sha256'],'source_format':track['ext'],
        'extractor_version':VERSION,'extractor_method':'yt_dlp.webvtt.parse_fragment','discovery_method':track['source_kind'],
        'coverage':'source_track_full_duration_candidate','semantic_status':'not_reviewed','semantic_completeness':'unknown',
        'first_seconds':rows[0]['start'],'last_seconds':max(r['end'] for r in rows),'duration_seconds':result['duration_seconds']}
    report={'schema':'crowd-declared-subtitle-report-v1','job_id':job_id,'subtitle_source_run_id':state['run_id'],'local_run_id':state['run_id'],
        'platform':platform,'content_id':state['content_id'],'entity_ref':entity,'asset_sha256':state['asset_sha256'],'input_hash':state['input_hash'],
        'full_result_file_sha256':result_sha,'duration_seconds':result['duration_seconds'],'segments':rows,'text_sha256':hashlib.sha256('\n'.join(r['text'] for r in rows).encode()).hexdigest(),
        'segment_count':len(rows),'character_count':sum(len(r['text']) for r in rows),'semantic_review':'not_reviewed','cer':None,'human_groundtruth':False,
        'diagnostics_sha256':None,'model_manifest_sha256':None,'processing_profile':PROFILE,'processor':PROFILE,'text_revision':None,'subtitle_provenance':provenance}
    raw=encoded(report).decode()
    if len(raw.encode())>MAX_BYTES:raise ValueError('transcript_report_limit')
    if contains_secret(raw):raise ValueError('sensitive_transcript')
    return {'state':state},report,raw
