"""Reuse yt-dlp caption extraction on the native detail already fetched by this task."""
import hashlib,json,math,os,re,sys,time,uuid
from pathlib import Path
from urllib.parse import urlsplit
from mc_runner import canonical,write,contains_secret,uid
from analysis_artifact import _read,_safe_ancestors
from tieba_media import safe_directory
MAX_BYTES=200000
VERSION='2026.08.19'


def toolkit():
    runtime=os.environ.get('CROWD_YTDLP_RUNTIME')
    if runtime:
        path=Path(runtime)
        if not path.is_absolute():raise ValueError('subtitle_toolkit_path_invalid')
        _safe_ancestors(path)
        if str(path) not in sys.path:sys.path.insert(0,str(path))
    from yt_dlp.version import __version__
    if __version__!=VERSION:raise ValueError('subtitle_toolkit_version_mismatch')
    from yt_dlp.extractor.tiktok import TikTokBaseIE
    from yt_dlp.webvtt import parse_fragment,CueBlock
    return TikTokBaseIE,parse_fragment,CueBlock


def caption_url(value):
    if not isinstance(value,str) or len(value)>4000:return None
    try:
        parsed=urlsplit(value);host=parsed.hostname or ''
        if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.fragment:return None
        if not any(host==domain or host.endswith('.'+domain) for domain in ('douyin.com','douyincdn.com','douyinvod.com','bytecdn.cn','bytedance.com','byteimg.com','bytedance.net','ibytedtos.com')):return None
        return value
    except ValueError:return None


def discover(detail,payloads=None):
    base,_,_=toolkit();requests=[]
    class Offline(base):
        def _download_json(self,url,*args,**kwargs):
            requests.append(url)
            return (payloads or {}).get(url)
        def _extract_web_data_and_status(self,*args,**kwargs):raise ValueError('subtitle_unexpected_source_request')
    # Explicit None disables yt-dlp's secondary webpage traversal and any browser/cookie importer.
    tracks=Offline()._get_subtitles(detail,str(detail['aweme_id']),None)
    return tracks,requests


def parse_text(text,format):
    _,parse_fragment,CueBlock=toolkit()
    if format=='srt':
        text='WEBVTT\n\n'+re.sub(r'(\d{2}:\d{2}:\d{2}),(\d{3})(?=\s|$)',r'\1.\2',text)
    elif format!='vtt':raise ValueError('subtitle_format_unsupported')
    blocks=list(parse_fragment(text.encode('utf-8')))
    return [{'start':r.start/90000,'end':r.end/90000,'text':r.text.strip()} for r in blocks if isinstance(r,CueBlock)]


def normalize_source(raw,format,cid,language):
    if format!='json':return parse_text(raw.decode('utf-8-sig'),format)
    # Run both fetch and reload through the same official conversion and 90 kHz parser.
    placeholder='https://v.douyincdn.com/native-caption.json'
    detail={'aweme_id':cid,'interaction_stickers':[{'auto_video_caption_info':{'auto_captions':[
        {'language':language,'url':{'url_list':[placeholder]}}]}}]}
    rows,_=discover(detail,{placeholder:json.loads(raw)})
    selected=next((track for track in rows.get(language,[]) if track.get('data')),None)
    if selected is None:raise ValueError('subtitle_invalid')
    return parse_text(selected['data'],selected['ext'])


def validate_segments(rows,duration):
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<duration<=7200 or not isinstance(rows,list) or not 1<=len(rows)<=8000:raise ValueError('subtitle_invalid')
    previous=-1;cursor=0;gap=0
    for row in rows:
        start,end,text=row.get('start'),row.get('end'),row.get('text')
        if (any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,end)) or not 0<=start<end<=duration
                or start<previous or not isinstance(text,str) or not text.strip() or len(text)>24000):raise ValueError('subtitle_invalid')
        gap=max(gap,start-cursor);cursor=max(cursor,end);previous=start
    return rows[0]['start']<=max(10,duration*.03) and duration-cursor<=max(10,duration*.03) and gap<=max(120,duration*.15)


async def fetch_douyin_subtitles(detail,output,client=None):
    cid=detail.get('aweme_id') if isinstance(detail,dict) else None
    if not isinstance(cid,str) or not re.fullmatch('[0-9]{1,30}',cid):return {'status':'unavailable','reason':'subtitle_identity_invalid','source_requests':0}
    duration=detail.get('video',{}).get('duration') if isinstance(detail.get('video'),dict) else None
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<duration<=7200000:return {'status':'unavailable','reason':'subtitle_duration_missing','source_requests':0}
    duration/=1000
    if client is None:
        import httpx
        async with httpx.AsyncClient(timeout=30,follow_redirects=False,trust_env=False) as own:return await fetch_douyin_subtitles(detail,output,own)
    attempted=0
    try:
        tracks,pending=discover(detail)
        # Official extractor requests these JSON caption bodies. Retain one Chinese candidate, not every language.
        chinese_json=[]
        for sticker in detail.get('interaction_stickers',[]) or []:
            info=sticker.get('auto_video_caption_info',{}) if isinstance(sticker,dict) else {}
            for track in info.get('auto_captions',[]) or []:
                if isinstance(track,dict) and track.get('language') in ('zh','zh-CN','zh-Hans','cmn'):
                    urls=track.get('url',{}).get('url_list',[]) if isinstance(track.get('url'),dict) else []
                    chinese_json.extend(url for url in urls if url in pending and caption_url(url))
        eligible=[(lang,track) for lang,rows in tracks.items() if lang in ('zh','zh-CN','zh-Hans','cmn') for track in rows if isinstance(track,dict) and caption_url(track.get('url')) and track.get('ext') in ('srt','vtt')]
        if chinese_json:language='zh';url=chinese_json[0];format='json'
        elif eligible:language,selected=eligible[0];url=selected['url'];format=selected['ext']
        else:return {'status':'unavailable','reason':'native_chinese_subtitle_unavailable','source_requests':0}
        attempted=1
        async with client.stream('GET',url,headers={'Referer':'https://www.douyin.com/'}) as response:
            if response.status_code!=200:raise ValueError('subtitle_http_failed')
            raw=b''
            async for chunk in response.aiter_bytes(65536):
                if len(raw)+len(chunk)>MAX_BYTES:raise ValueError('subtitle_response_limit')
                raw+=chunk
        segments=normalize_source(raw,format,cid,language)
        metadata={'schema':'crowd-native-caption-projection-v1','provider':'douyin','content_id':cid,
            'native_duration_ms':detail['video']['duration'],'language':language,'source_format':format,
            'track_url_sha256':hashlib.sha256(url.encode()).hexdigest(),'origin':'same_native_aweme_detail'}
        metadata_raw=canonical(metadata).encode()
        available=validate_segments(segments,duration);raw_sha=hashlib.sha256(raw).hexdigest()
        provenance={'provider':'douyin','subtitle_kind':'unknown','language':language,'track_id':hashlib.sha256(url.encode()).hexdigest(),
            'coverage':'source_track_full_duration_candidate' if available else 'partial_or_unknown','semantic_status':'not_reviewed','semantic_completeness':'unknown',
            'source_body_sha256':raw_sha,'raw_subtitle_sha256':raw_sha,'source_metadata_sha256':hashlib.sha256(metadata_raw).hexdigest(),
            'extractor_version':VERSION,'extractor_method':'TikTokBaseIE._get_subtitles','content_id':cid,'first_seconds':segments[0]['start'],
            'last_seconds':max(r['end'] for r in segments),'duration_seconds':duration}
        result={'schema':'crowd-native-caption-source-v1','platform':'douyin','content_id':cid,'duration_seconds':duration,'segments':segments,
                'subtitle_provenance':provenance,'status':'available' if available else 'partial','source_requests':1,'model_calls':0,'source_format':format}
        if contains_secret(canonical(result)):raise ValueError('sensitive_subtitle')
        folder=safe_directory(Path(output)/'douyin/subtitles');target=folder/(cid+'.json');raw_target=folder/(cid+'.source.json')
        if target.exists() or target.is_symlink():raise ValueError('subtitle_already_saved')
        with os.fdopen(os.open(raw_target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as stream:stream.write(raw)
        metadata_target=folder/(cid+'.metadata.json')
        with os.fdopen(os.open(metadata_target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as stream:stream.write(metadata_raw)
        write(target,result)
        return {'status':result['status'],'reason':None if available else 'subtitle_coverage_unknown','source_requests':1,'content_id':cid}
    except ImportError:return {'status':'unavailable','reason':'subtitle_toolkit_not_configured','source_requests':attempted}
    except Exception:return {'status':'failed','reason':'subtitle_fetch_failed','source_requests':attempted}


def load_job(jobs,job_id):
    from complete_video import read_bytes
    from media_native import _relative
    job_id=uid(job_id);state,_=_read(jobs.root.parent/'subtitle-jobs'/(job_id+'.json'),200000)
    cid=state.get('content_id');run_id=uid(state.get('run_id'))
    if (state.get('job_id')!=job_id or state.get('kind')!='subtitle' or state.get('state')!='completed' or state.get('platform')!='douyin'
            or not isinstance(cid,str) or not re.fullmatch('[0-9]{1,30}',cid) or state.get('entity_ref')!='douyin:content:'+cid
            or any(not isinstance(state.get(k),str) or not re.fullmatch('[a-f0-9]{64}',state[k]) for k in ('asset_sha256','input_hash','result_sha256','source_record_hash'))):raise ValueError('subtitle_job_invalid')
    folder=jobs.subtitle_run_folder(run_id);manifest,_=_read(folder/'manifest.json',200000);status,_=_read(folder/'status.json',200000)
    normalized,_=_read(folder/'normalized.json',32*1024*1024)
    if (manifest.get('run_id')!=run_id or status.get('run_id')!=run_id or status.get('state')!='completed'
            or manifest.get('request',{}).get('platform')!='dy' or normalized.get('run_id')!=run_id
            or normalized.get('source_kind')!='mediacrawler_api' or normalized.get('reward_eligible') is not False):raise ValueError('subtitle_source_changed')
    rows=[r for r in normalized.get('records',[]) if isinstance(r,dict) and r.get('platform')=='douyin' and r.get('kind')=='content' and r.get('content_id')==cid]
    if len(rows)!=1:raise ValueError('subtitle_source_changed')
    body=rows[0];origin=body.get('origin',{});file_sha=origin.get('file_sha256')
    if (body.get('source_kind')!='mediacrawler_api' or body.get('reward_eligible') is not False
            or body.get('record_hash')!=state['source_record_hash']
            or body['record_hash']!=hashlib.sha256(canonical({k:v for k,v in body.items() if k not in ('record_hash','discovery_kind')}).encode()).hexdigest()
            or origin.get('run_id')!=run_id or not isinstance(file_sha,str) or not re.fullmatch('[a-f0-9]{64}',file_sha)):raise ValueError('subtitle_source_changed')
    files=[r for r in normalized.get('files',[]) if isinstance(r,dict) and r.get('sha256')==file_sha]
    if len(files)!=1:raise ValueError('subtitle_source_changed')
    source=_relative(folder,files[0]['path'])
    if source.suffix!='.jsonl' or hashlib.sha256(read_bytes(source,50*1024*1024)).hexdigest()!=file_sha:raise ValueError('subtitle_source_changed')
    caption,result_sha=_read(folder/'output/douyin/subtitles'/(cid+'.json'),MAX_BYTES)
    raw=read_bytes(folder/'output/douyin/subtitles'/(cid+'.source.json'),MAX_BYTES)
    if result_sha!=state['result_sha256'] or hashlib.sha256(raw).hexdigest()!=state['asset_sha256'] or state['input_hash']!=hashlib.sha256((run_id+':'+cid+':'+result_sha).encode()).hexdigest():raise ValueError('subtitle_source_changed')
    provenance=caption.get('subtitle_provenance',{})
    if (caption.get('platform')!='douyin' or caption.get('content_id')!=cid or provenance.get('provider')!='douyin'
            or provenance.get('content_id')!=cid or provenance.get('source_body_sha256')!=state['asset_sha256']
            or provenance.get('raw_subtitle_sha256')!=state['asset_sha256'] or provenance.get('extractor_version')!=VERSION
            or provenance.get('coverage')!='source_track_full_duration_candidate'):raise ValueError('subtitle_source_changed')
    metadata,metadata_sha=_read(folder/'output/douyin/subtitles'/(cid+'.metadata.json'),10000)
    if (set(metadata)!={'schema','provider','content_id','native_duration_ms','language','source_format','track_url_sha256','origin'}
            or metadata['schema']!='crowd-native-caption-projection-v1' or metadata['provider']!='douyin'
            or metadata['content_id']!=cid or metadata['origin']!='same_native_aweme_detail'
            or metadata_sha!=provenance.get('source_metadata_sha256')
            or metadata['language']!=provenance.get('language') or metadata['source_format']!=caption.get('source_format')
            or metadata['track_url_sha256']!=provenance.get('track_id')
            or type(metadata['native_duration_ms']) not in (int,float) or not math.isfinite(metadata['native_duration_ms'])
            or metadata['native_duration_ms']/1000!=caption.get('duration_seconds')
            or provenance.get('duration_seconds')!=caption.get('duration_seconds')):raise ValueError('subtitle_source_changed')
    segments=normalize_source(raw,metadata['source_format'],cid,metadata['language'])
    if segments!=caption.get('segments') or not validate_segments(segments,caption.get('duration_seconds')):raise ValueError('subtitle_source_changed')
    state['result']=[{'platform':'douyin','content_id':cid,'kind':'transcript','evidence':{'asset_sha256':state['asset_sha256'],
        'segments':segments,'duration_seconds':caption['duration_seconds'],'processor':'yt_dlp_native_metadata_subtitle_v1',
        'subtitle_provenance':provenance,'semantic_review':'not_reviewed','timeline':'absolute_seconds'}}]
    return state


def subtitle_report(jobs,job_id):
    state=load_job(jobs,job_id);evidence=state['result'][0]['evidence'];segments=evidence['segments']
    report={'schema':'crowd-platform-subtitle-report-v1','job_id':job_id,'subtitle_source_run_id':state['run_id'],
        'local_run_id':state['run_id'],'platform':'douyin','content_id':state['content_id'],'entity_ref':state['entity_ref'],
        'asset_sha256':state['asset_sha256'],'input_hash':state['input_hash'],'full_result_file_sha256':state['result_sha256'],
        'duration_seconds':evidence['duration_seconds'],'segments':segments,'text_sha256':hashlib.sha256('\n'.join(r['text'] for r in segments).encode()).hexdigest(),
        'segment_count':len(segments),'character_count':sum(len(r['text']) for r in segments),'semantic_review':'not_reviewed','cer':None,'human_groundtruth':False,
        'diagnostics_sha256':None,'model_manifest_sha256':None,'processing_profile':'yt_dlp_native_metadata_subtitle_v1',
        'processor':'yt_dlp_native_metadata_subtitle_v1','text_revision':None,'subtitle_provenance':evidence['subtitle_provenance']}
    raw=json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    if len(raw.encode())>MAX_BYTES:raise ValueError('transcript_report_limit')
    if contains_secret(raw):raise ValueError('sensitive_transcript')
    return {'state':state},report,raw
