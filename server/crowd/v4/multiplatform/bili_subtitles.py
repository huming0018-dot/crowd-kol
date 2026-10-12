"""Bounded native Bili caption discovery. Captions are never ASR or danmaku."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from mc_runner import canonical, write
from tieba_media import safe_directory

MAX_BYTES = 200000


def subtitle_url(value):
    if not isinstance(value, str) or len(value) > 4000:return None
    if value.startswith('//'):value = 'https:' + value
    try:
        url = urlsplit(value);host = url.hostname or ''
        if (url.scheme != 'https' or url.username or url.password or url.port not in (None,443)
                or url.fragment or not (host == 'hdslb.com' or host.endswith('.hdslb.com'))):return None
        return value
    except ValueError:return None


def parse_caption(player, body, identity, raw_sha, player_sha):
    duration = identity.get('duration')
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 0 < duration <= 7200:
        raise ValueError('subtitle_duration_invalid')
    rows = body.get('body') if isinstance(body,dict) else None
    if not isinstance(rows,list) or not 1 <= len(rows) <= 8000:raise ValueError('subtitle_body_invalid')
    segments = [];previous = -1;cursor = 0;gaps = []
    for row in rows:
        if not isinstance(row,dict):raise ValueError('subtitle_body_invalid')
        start,end,text = row.get('from'),row.get('to'),row.get('content')
        if (any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,end))
                or not 0 <= start < end <= duration or start < previous
                or not isinstance(text,str) or not text.strip() or len(text)>24000):raise ValueError('subtitle_segment_invalid')
        if start > cursor:gaps.append(start-cursor)
        cursor=max(cursor,end);previous=start
        segments.append({'start':start,'end':end,'text':text})
    first,last=segments[0]['start'],max(r['end'] for r in segments)
    # Track coverage is a conservative candidate test, never proof every spoken word was captioned.
    coverage=(first<=max(10,duration*.03) and duration-last<=max(10,duration*.03)
              and max(gaps or [0])<=max(120,duration*.15))
    kind=player.get('type')
    kind='platform_auto' if str(player.get('lan','')).startswith('ai-') else 'unknown'
    return {'schema':'crowd-bili-caption-source-v1','platform':'bilibili','content_id':str(identity['aid']),
            'aid':str(identity['aid']),'cid':str(identity['cid']),'bvid':identity['bvid'],
            'duration_seconds':duration,'segments':segments,'native_track':{k:player.get(k) for k in ('id','id_str','lan','type')},
            'subtitle_provenance':{'provider':'bilibili','subtitle_kind':kind,'language':player['lan'],
                'track_id':str(player.get('id_str') or player.get('id') or ''),
                'coverage':'source_track_full_duration_candidate' if coverage else 'partial_or_unknown',
                'semantic_status':'not_reviewed','semantic_completeness':'unknown',
                'source_body_sha256':raw_sha,'raw_subtitle_sha256':raw_sha,'player_response_sha256':player_sha,
                'aid':str(identity['aid']),'cid':str(identity['cid']),'bvid':identity['bvid'],
                'first_seconds':first,'last_seconds':last,'duration_seconds':duration},
            'status':'available' if coverage else 'partial','source_requests':2,'model_calls':0}


async def _bounded_json(client,url,headers,params=None):
    async with client.stream('GET',url,headers=headers,params=params) as response:
        if response.status_code != 200:raise ValueError('subtitle_http_failed')
        chunks=[];size=0
        async for chunk in response.aiter_bytes(65536):
            size+=len(chunk)
            if size>MAX_BYTES:raise ValueError('subtitle_response_limit')
            chunks.append(chunk)
    raw=b''.join(chunks)
    return json.loads(raw),hashlib.sha256(raw).hexdigest(),raw


async def fetch_subtitles(view,headers,output,client=None):
    identity={k:view.get(k) for k in ('aid','cid','bvid','duration')}
    if (any(type(identity[k]) is not int or not 0<identity[k]<=9007199254740991 for k in ('aid','cid'))
            or not isinstance(identity['bvid'],str) or not re.fullmatch('BV[A-Za-z0-9]{10}',identity['bvid'])):
        return {'status':'unavailable','reason':'subtitle_identity_invalid','source_requests':0}
    if client is None:
        import httpx
        async with httpx.AsyncClient(timeout=30,follow_redirects=False,trust_env=False) as own:
            return await fetch_subtitles(view,headers,output,own)
    requests=0
    try:
        requests=1
        # Session headers stay in memory and only go to Bili's API; never to the caption CDN.
        player,player_sha,_=await _bounded_json(client,'https://api.bilibili.com/x/player/wbi/v2',
            {**headers,'Referer':'https://www.bilibili.com/'}, {'aid':identity['aid'],'cid':identity['cid']})
        data=player.get('data') if isinstance(player,dict) and player.get('code')==0 else None
        if not isinstance(data,dict):return {'status':'unavailable','reason':'subtitle_player_failed','source_requests':requests}
        if data.get('need_login_subtitle'):return {'status':'login_required','reason':'subtitle_login_required','source_requests':requests}
        rows=data.get('subtitle',{}).get('subtitles',[]) if isinstance(data.get('subtitle'),dict) else []
        eligible=[r for r in rows[:100] if isinstance(r,dict) and r.get('lan') in ('zh-CN','zh-Hans','zh','ai-zh') and subtitle_url(r.get('subtitle_url'))] if isinstance(rows,list) else []
        if not eligible:return {'status':'unavailable','reason':'chinese_subtitle_unavailable','source_requests':requests}
        track=min(eligible,key=lambda r:(str(r['lan']).startswith('ai-'),str(r.get('id_str') or r.get('id'))))
        requests=2
        body,raw_sha,raw=await _bounded_json(client,subtitle_url(track['subtitle_url']),{'Referer':'https://www.bilibili.com/'})
        result=parse_caption(track,body,identity,raw_sha,player_sha)
        folder=safe_directory(Path(output)/'bili/subtitles');target=folder/(str(identity['aid'])+'.json')
        if target.exists() or target.is_symlink():raise ValueError('subtitle_already_saved')
        raw_target=folder/(str(identity['aid'])+'.source.json')
        with os.fdopen(os.open(raw_target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as stream:stream.write(raw)
        write(target,result)
        return {'status':result['status'],'reason':None if result['status']=='available' else 'subtitle_coverage_unknown',
                'source_requests':requests,'content_id':result['content_id']}
    except Exception:return {'status':'failed','reason':'subtitle_fetch_failed','source_requests':requests}


def load_job(jobs,job_id):
    from analysis_artifact import _read
    from mc_runner import uid
    path=jobs.root.parent/'subtitle-jobs'/(uid(job_id)+'.json')
    state,state_sha=_read(path,200000)
    if state.get('job_id')!=job_id or state.get('kind')!='subtitle':raise ValueError('subtitle_job_invalid')
    cid=state.get('content_id')
    if (not isinstance(cid,str) or not re.fullmatch('[1-9][0-9]{0,15}',cid) or state.get('platform')!='bilibili'
            or state.get('entity_ref')!='bilibili:content:'+cid or state.get('state')!='completed'
            or any(not isinstance(state.get(k),str) or not re.fullmatch('[a-f0-9]{64}',state[k]) for k in ('asset_sha256','input_hash','result_sha256','source_record_hash'))):raise ValueError('subtitle_job_invalid')
    folder=jobs.subtitle_run_folder(uid(state['run_id']))
    manifest,_=_read(folder/'manifest.json',200000);status,_=_read(folder/'status.json',200000)
    if manifest.get('run_id')!=state['run_id'] or status.get('run_id')!=state['run_id'] or status.get('state')!='completed' or manifest.get('request',{}).get('platform')!='bili':raise ValueError('subtitle_source_changed')
    normalized,_=_read(folder/'normalized.json',32*1024*1024)
    if normalized.get('run_id')!=state['run_id']:raise ValueError('subtitle_source_changed')
    rows=[r for r in normalized['records'] if r.get('platform')=='bilibili' and r.get('kind')=='content' and r.get('content_id')==state['content_id']]
    if len(rows)!=1 or rows[0]['record_hash']!=state['source_record_hash']:raise ValueError('subtitle_source_changed')
    body=rows[0];origin=body.get('origin',{});file_sha=origin.get('file_sha256')
    if (normalized.get('source_kind')!='mediacrawler_api' or normalized.get('reward_eligible') is not False
            or body.get('source_kind')!='mediacrawler_api' or body.get('reward_eligible') is not False
            or body.get('record_hash')!=hashlib.sha256(canonical({k:v for k,v in body.items() if k not in ('record_hash','discovery_kind')}).encode()).hexdigest()
            or origin.get('run_id')!=state['run_id'] or not isinstance(file_sha,str) or not re.fullmatch('[a-f0-9]{64}',file_sha)):
        raise ValueError('subtitle_source_changed')
    sources=[r for r in normalized.get('files',[]) if isinstance(r,dict) and r.get('sha256')==file_sha]
    if len(sources)!=1:raise ValueError('subtitle_source_changed')
    from media_native import _relative
    from complete_video import read_bytes
    source_path=_relative(folder,sources[0].get('path'))
    if source_path.suffix!='.jsonl' or hashlib.sha256(read_bytes(source_path,50*1024*1024)).hexdigest()!=file_sha:
        raise ValueError('subtitle_source_changed')
    caption,caption_sha=_read(folder/'output/bili/subtitles'/(state['content_id']+'.json'),200000)
    if caption_sha!=state['result_sha256'] or caption['subtitle_provenance']['coverage']!='source_track_full_duration_candidate':raise ValueError('subtitle_source_changed')
    from analysis_artifact import _safe_ancestors
    raw_path=folder/'output/bili/subtitles'/(state['content_id']+'.source.json')
    _safe_ancestors(raw_path)
    import stat
    info=raw_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_BYTES:raise ValueError('subtitle_source_invalid')
    if hashlib.sha256(raw_path.read_bytes()).hexdigest()!=state['asset_sha256']:raise ValueError('subtitle_source_changed')
    if state['input_hash']!=hashlib.sha256((state['run_id']+':'+cid+':'+caption_sha).encode()).hexdigest():raise ValueError('subtitle_source_changed')
    provenance=caption['subtitle_provenance']
    if provenance.get('aid')!=cid or caption.get('content_id')!=cid:raise ValueError('subtitle_source_changed')
    source,_=_read(raw_path,MAX_BYTES)
    checked=parse_caption(caption['native_track'],source,
        {'aid':int(provenance['aid']),'cid':int(provenance['cid']),'bvid':provenance['bvid'],'duration':provenance['duration_seconds']},state['asset_sha256'],provenance['player_response_sha256'])
    if checked!=caption:raise ValueError('subtitle_source_changed')
    identities,_=_read(folder/'output/bili/media-identities.json',200000)
    if not any(r.get('aid')==state['content_id'] and r.get('bvid')==caption['bvid'] and r.get('cid')==caption['cid'] for r in identities.get('bindings',[])):raise ValueError('subtitle_source_changed')
    if state['asset_sha256']!=caption['subtitle_provenance']['source_body_sha256']:raise ValueError('subtitle_source_changed')
    state['result']=[{'platform':'bilibili','content_id':state['content_id'],'kind':'transcript','evidence':{
        'asset_sha256':state['asset_sha256'],'segments':caption['segments'],'duration_seconds':caption['duration_seconds'],
        'processor':'native_bilibili_subtitle_json_v1','subtitle_provenance':caption['subtitle_provenance'],
        'semantic_review':'not_reviewed','timeline':'absolute_seconds'}}]
    return state


def subtitle_report(jobs,job_id):
    state=load_job(jobs,job_id);evidence=state['result'][0]['evidence'];segments=evidence['segments']
    report={'schema':'crowd-subtitle-report-v1','job_id':job_id,'subtitle_source_run_id':state['run_id'],
            'local_run_id':state['run_id'],'platform':'bilibili','content_id':state['content_id'],'entity_ref':state['entity_ref'],
            'asset_sha256':state['asset_sha256'],'input_hash':state['input_hash'],'full_result_file_sha256':state['result_sha256'],
            'duration_seconds':evidence['duration_seconds'],'segments':segments,
            'text_sha256':hashlib.sha256('\n'.join(r['text'] for r in segments).encode()).hexdigest(),
            'segment_count':len(segments),'character_count':sum(len(r['text']) for r in segments),
            'semantic_review':'not_reviewed','cer':None,'human_groundtruth':False,'diagnostics_sha256':None,
            'model_manifest_sha256':None,'processing_profile':'native_bilibili_subtitle_json_v1',
            'processor':'native_bilibili_subtitle_json_v1','text_revision':None,'subtitle_provenance':evidence['subtitle_provenance']}
    raw=json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    from mc_runner import contains_secret
    from results_store import _entity_selector
    _entity_selector(report['entity_ref'],report['platform'],report['content_id'])
    if len(raw.encode())>200000:raise ValueError('transcript_report_limit')
    if contains_secret(raw):raise ValueError('sensitive_transcript')
    return {'state':state},report,raw
