"""Separate native video media limits from JSON responses and total task limits."""
from contextvars import ContextVar
from urllib.parse import urlsplit

NATIVE_VIDEO_MEDIA_ACTIVE = ContextVar('crowd_native_video_media_active', default=False)
DEFAULT_RESPONSE_BYTES = 25 * 1024 * 1024
NATIVE_VIDEO_MEDIA_BYTES = 64 * 1024 * 1024

def install_ffmpeg_path(package, module, configured=None):
    """Use the already configured executable through the installed SDK's own merge."""
    import os,stat
    from pathlib import Path
    from analysis_artifact import _safe_ancestors
    value=os.environ.get('CROWD_FFMPEG') if configured is None else configured
    if not value:return False
    if not isinstance(value,str) or not Path(value).is_absolute():raise ValueError('invalid_native_ffmpeg_path')
    path=Path(value);_safe_ancestors(path)
    try:info=path.stat()
    except OSError:raise ValueError('invalid_native_ffmpeg_path') from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_mode & 0o022 or not os.access(path,os.X_OK):raise ValueError('invalid_native_ffmpeg_path')
    executable=str(path)
    def configured_path():return executable
    module.ffmpeg_path=configured_path
    package.ffmpeg_path=configured_path
    return True

def save_bilibili_identity(item,output,read,write):
    """Keep the IDs from the same View consumed by the native media method."""
    import re,uuid,stat
    from analysis_artifact import _safe_ancestors,_read
    try:run_id=str(uuid.UUID(output.parent.name))
    except (ValueError,AttributeError):return
    if run_id!=output.parent.name:return
    view=item.get('View') if isinstance(item,dict) else None
    if not isinstance(view,dict):return
    def numeric(value):
        if type(value) is int and 0<value<=9007199254740991:return str(value)
        if isinstance(value,str) and re.fullmatch(r'[1-9][0-9]{0,15}',value) and int(value)<=9007199254740991:return value
        return None
    aid,cid,bvid=numeric(view.get('aid')),numeric(view.get('cid')),view.get('bvid')
    if not aid or not cid or not isinstance(bvid,str) or not re.fullmatch(r'BV[A-Za-z0-9]{10}',bvid):return
    folder=output/'bili';_safe_ancestors(folder);folder.mkdir(exist_ok=True)
    path=folder/'media-identities.json';_safe_ancestors(path)
    value={'schema_version':1,'run_id':run_id,'platform':'bilibili','bindings':[]}
    if path.exists():
        info=path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>200000:raise ValueError('unsafe_bilibili_media_identity')
        value,_=_read(path,200000)
        if not isinstance(value,dict) or set(value)!={'schema_version','run_id','platform','bindings'} or type(value.get('schema_version')) is not int or value['schema_version']!=1 or value.get('run_id')!=run_id or value.get('platform')!='bilibili' or not isinstance(value.get('bindings'),list) or len(value['bindings'])>1000:raise ValueError('invalid_bilibili_media_identity')
    pair={'aid':aid,'bvid':bvid,'cid':cid,'source':'same_native_bilibili_view'}
    if pair not in value['bindings']:
        if len(value['bindings'])>=1000:raise ValueError('bilibili_media_identity_limit')
        value['bindings'].append(pair);write(path,value)

def bilibili_identity_map(output,run_id,records,read):
    import hashlib,re,stat
    from analysis_artifact import _safe_ancestors,_read
    path=output/'bili/media-identities.json'
    if not path.exists() and not path.is_symlink():return {},None
    _safe_ancestors(path);info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>200000:raise ValueError('unsafe_bilibili_media_identity')
    value,sidecar_sha=_read(path,200000)
    if not isinstance(value,dict) or set(value)!={'schema_version','run_id','platform','bindings'} or type(value.get('schema_version')) is not int or value['schema_version']!=1 or value.get('run_id')!=run_id or value.get('platform')!='bilibili' or not isinstance(value.get('bindings'),list) or len(value['bindings'])>1000:raise ValueError('invalid_bilibili_media_identity')
    pairs={};ambiguous=set();contents={r['content_id'] for r in records if r.get('kind')=='content' and r.get('canonical_id_scheme')=='bilibili.aid.v1'}
    for pair in value['bindings']:
        if not isinstance(pair,dict) or set(pair)!={'aid','cid','bvid','source'} or pair.get('source')!='same_native_bilibili_view' or not isinstance(pair.get('bvid'),str) or not re.fullmatch(r'BV[A-Za-z0-9]{10}',pair['bvid']) or any(not isinstance(pair.get(k),str) or not re.fullmatch(r'[1-9][0-9]{0,15}',pair[k]) or int(pair[k])>9007199254740991 for k in ('aid','cid')):raise ValueError('invalid_bilibili_media_identity')
        bvid=pair['bvid']
        if bvid in pairs and pairs[bvid]!=pair:ambiguous.add(bvid)
        pairs[bvid]=pair
    return {k:v for k,v in pairs.items() if k not in ambiguous and v['aid'] in contents},sidecar_sha

def _douyin_candidates(item):
    if not isinstance(item,dict) or not isinstance(item.get('video'),dict) or item.get('images'):
        return []
    video=item['video'];rows=[]
    def number(value):
        return value if type(value) is int and 0<value<=10**12 else None
    def add(address,rate=None):
        if not isinstance(address,dict):return
        raw=address.get('url_list')
        if not isinstance(raw,list):return
        urls=[]
        for value in raw[:3]:
            if not isinstance(value,str) or len(value)>4096:continue
            try:
                u=urlsplit(value)
                host=u.hostname or ''
                if (u.scheme=='https' and not u.username and not u.password and u.port in (None,443)
                        and (host=='www.douyin.com' or host.endswith(('.douyinvod.com','.bytecdn.cn','.ibytedtos.com','.pstatp.com')))):
                    urls.append(value)
            except (TypeError,ValueError):pass
        if not urls:return
        size=number(address.get('data_size'));rate=number(rate)
        rows.append({'address':{**address,'url_list':urls},'size':size,'rate':rate})
    for key in ('play_addr_h264','play_addr_256','play_addr'):add(video.get(key))
    rates=video.get('bit_rate')
    if isinstance(rates,list):
        for row in rates[:32]:
            if isinstance(row,dict):add(row.get('play_addr'),row.get('bit_rate'))
    return rows

def select_douyin_stream(item):
    """Select a complete native rendition before downloading, without probing URLs."""
    if not isinstance(item,dict) or not isinstance(item.get('video'),dict) or item.get('images'):return item,None
    video=item['video'];rows=_douyin_candidates(item)
    fitting=[row for row in rows if row['size'] is not None and row['size']<=NATIVE_VIDEO_MEDIA_BYTES]
    unknown=[row for row in rows if row['size'] is None and row['rate'] is not None]
    chosen=min(fitting,key=lambda row:row['size']) if fitting else min(unknown,key=lambda row:row['rate']) if unknown else None
    summary={'strategy':'native_complete_rendition_under_limit','source':'same_native_aweme_detail',
             'candidate_count':len(rows),'fitting_candidate_count':len(fitting),
             'single_file_limit_bytes':NATIVE_VIDEO_MEDIA_BYTES,
             'selection_status':'selected' if chosen else 'no_fitting_reported_rendition',
             'reported_bytes':chosen['size'] if chosen else None,
             'reported_bitrate':chosen['rate'] if chosen else None}
    if chosen is None:return item,summary
    # The installed SDK prioritizes these fields; keep the original detail and cover intact.
    return {**item,'video':{**video,'play_addr_h264':chosen['address'],
                           'play_addr_256':chosen['address'],'play_addr':chosen['address']}},summary


def save_processing_reference(item,output):
    """Save one same-detail lower rendition privately; no URL probing or collector quota change."""
    import hashlib,json,os,re,uuid
    from pathlib import Path
    from complete_video import INPUT_LIMIT,safe_folder,safe_url,read_bytes
    output=Path(output);run_id=output.parent.name
    if str(uuid.UUID(run_id))!=run_id:raise ValueError('invalid_video_reference_context')
    cid=item.get('aweme_id') if isinstance(item,dict) else None
    if not isinstance(cid,str) or not re.fullmatch(r'[0-9]{1,30}',cid):raise ValueError('invalid_video_reference_context')
    candidates=[row for row in _douyin_candidates(item) if row['size'] is not None and row['size']<=INPUT_LIMIT]
    if not candidates:return {'state':'no_fitting_processing_rendition','candidate_count':0,'input_limit_bytes':INPUT_LIMIT}
    chosen=min(candidates,key=lambda row:row['size']);url=safe_url(chosen['address']['url_list'][0])
    safe_folder(output)
    parent=output/'douyin';parent.mkdir(exist_ok=True);safe_folder(parent)
    folder=parent/'video-references';folder.mkdir(mode=0o700,exist_ok=True);safe_folder(folder)
    if folder.stat().st_mode & 0o777 != 0o700:raise ValueError('unsafe_video_reference_directory')
    value={'schema_version':1,'run_id':run_id,'platform':'douyin','content_id':cid,
           'source_kind':'same_native_aweme_detail','reported_bytes':chosen['size'],
           'reported_bitrate':chosen['rate'],'url':url}
    path=folder/(cid+'.json');temp=folder/('tmp-'+uuid.uuid4().hex)
    try:
        with os.fdopen(os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
            json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
        try:os.link(temp,path)
        except FileExistsError:
            previous=json.loads(read_bytes(path,10000))
            if previous.get('run_id')!=run_id or previous.get('content_id')!=cid or previous.get('platform')!='douyin':raise ValueError('video_reference_identity_mismatch')
    finally:temp.unlink(missing_ok=True)
    data=read_bytes(path,10000)
    if path.stat().st_mode & 0o777 != 0o600:raise ValueError('unsafe_video_reference_file')
    return {'state':'saved_private_processing_reference','candidate_count':len(candidates),
            'input_limit_bytes':INPUT_LIMIT,'reference_file_sha256':hashlib.sha256(data).hexdigest()}


def response_limit(platform, content_type=None, response_host=None, audio_response_active=False):
    mime=content_type.split(';',1)[0].strip().lower() if isinstance(content_type,str) else ''
    if mime=='application/json' or mime.endswith('+json') or platform=='bili' and response_host=='api.bilibili.com':
        return DEFAULT_RESPONSE_BYTES
    if (platform=='bili' and audio_response_active is True) or (platform in ('dy', 'ks', 'bili') and NATIVE_VIDEO_MEDIA_ACTIVE.get()):
        return NATIVE_VIDEO_MEDIA_BYTES
    return DEFAULT_RESPONSE_BYTES


def install_hook(crawler, platform, output, limit_exception, read, write):
    original = crawler.download_media

    async def bounded_media(self, *args, **kwargs):
        folder = output / ('douyin' if platform=='dy' else 'kuaishou' if platform=='ks' else platform) / 'media'
        previous_parts = set(folder.rglob('*.part')) if folder.exists() else set()
        token = NATIVE_VIDEO_MEDIA_ACTIVE.set(True)
        try:
            if platform=='dy':
                source=kwargs.get('aweme_item') if 'aweme_item' in kwargs else args[0] if args else None
                selected,selection=select_douyin_stream(source)
                if isinstance(source,dict):
                    try:reference=save_processing_reference(source,output)
                    except (OSError,ValueError,TypeError):reference={'state':'processing_reference_unavailable'}
                    phase=output.parent/'phase.json';previous=read(phase) if phase.exists() else {}
                    write(phase,{**previous,'media_processing_reference':reference})
                if selection is not None:
                    phase=output.parent/'phase.json';previous=read(phase) if phase.exists() else {}
                    write(phase,{**previous,'media_video_selection':selection})
                    if 'aweme_item' in kwargs:kwargs={**kwargs,'aweme_item':selected}
                    elif args:args=(selected,*args[1:])
            return await original(self, *args, **kwargs)
        except limit_exception:
            # A single oversized media file must not abort the remaining comments.
            for path in set(folder.rglob('*.part')) - previous_parts:
                path.unlink(missing_ok=True)
            phase = output.parent / 'phase.json'
            previous = read(phase) if phase.exists() else {}
            write(phase, {**previous, 'media_status': 'limited',
                          'media_reason': 'single_response_byte_limit',
                          'media_single_file_limit_bytes': NATIVE_VIDEO_MEDIA_BYTES})
        finally:
            NATIVE_VIDEO_MEDIA_ACTIVE.reset(token)

    crawler.download_media = bounded_media
