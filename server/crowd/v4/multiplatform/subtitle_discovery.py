"""Observe same-task native media metadata; parse only declared timed-text schemas."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from analysis_artifact import _safe_ancestors
from tieba_media import safe_directory
from mc_runner import read,write

PLATFORMS={'ks':'kuaishou','wb':'weibo','xhs':'xiaohongshu','zhihu':'zhihu','tieba':'tieba','dy':'douyin','bili':'bilibili'}
MAX_BYTES=2_000_000
MAX_NODES=20000
LANG=re.compile('[A-Za-z0-9_-]{1,30}')
CID=re.compile('[A-Za-z0-9_-]{1,200}')
HOSTS={'kuaishou':('kuaishou.com','kwaicdn.com','ksapisrv.com'), 'weibo':('weibo.com','weibo.cn','sinaimg.cn','weibocdn.com'),
 'xiaohongshu':('xiaohongshu.com','xhscdn.com'), 'zhihu':('zhihu.com','zhimg.com','vzuu.com'),
 'tieba':('baidu.com','bdstatic.com'), 'douyin':('douyin.com','douyincdn.com','douyinvod.com'), 'bilibili':('bilibili.com','hdslb.com')}

def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def digest(value):return hashlib.sha256(value).hexdigest()

def track_url(platform,value):
    if not isinstance(value,str) or len(value)>4000:return None
    try:
        p=urlsplit(value)
        if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or p.fragment:return None
        host=p.hostname or ''
        if not any(host==h or host.endswith('.'+h) for h in HOSTS[platform]):return None
        return value
    except ValueError:return None

class TimedTracks(HTMLParser):
    def __init__(self):super().__init__();self.media=0;self.rows=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('video','audio'):self.media+=1
        if tag=='track' and self.media:
            a=dict(attrs)
            # Chapters, descriptions and metadata are not subtitles.
            if a.get('kind','subtitles') in ('subtitles','captions') and LANG.fullmatch(a.get('srclang','')):
                self.rows.append({'url':a.get('src'),'ext':'vtt','language':a['srclang'],'source_kind':'html_track_v1','subtitle_kind':'unknown'})
    def handle_endtag(self,tag):
        if tag in ('video','audio'):self.media=max(0,self.media-1)


def discover(platform,detail,content_id,content_type=None):
    if content_type not in (None,'answer','article','zvideo'):raise ValueError('subtitle_discovery_identity_invalid')
    if platform not in HOSTS or not isinstance(content_id,str) or not CID.fullmatch(content_id):raise ValueError('subtitle_discovery_identity_invalid')
    if platform=='zhihu' and content_type in ('answer','article','zvideo'):
        if not isinstance(detail,dict) and isinstance(getattr(detail,'text',None),str):
            from zhihu_media import InitialData
            parser=InitialData();parser.feed(detail.text[:MAX_BYTES]);detail={'initialState':json.loads(''.join(parser.parts)).get('initialState',{})}
        if isinstance(detail,dict) and 'initialState' in detail:
            entities=detail.get('initialState',{}).get('entities',{})
            bucket={'answer':'answers','article':'articles','zvideo':'zvideos'}[content_type]
            selected=entities.get(bucket,{}).get(content_id)
            if not isinstance(selected,dict) or str(selected.get('id',content_id))!=content_id:raise ValueError('subtitle_discovery_identity_invalid')
            detail=selected
    if isinstance(detail,dict):
        native_id=(detail.get('photo') or {}).get('id') if platform=='kuaishou' else detail.get('note_id',detail.get('id',detail.get('idstr')))
        if native_id is not None and str(native_id)!=content_id:raise ValueError('subtitle_discovery_identity_invalid')
    raw=encoded(detail)
    if len(raw)>MAX_BYTES:raise ValueError('subtitle_discovery_limit')
    tracks=[];fields=[];codecs=[];nodes=0;video_seen=False
    def walk(value,path='',depth=0):
        nonlocal nodes,video_seen
        nodes+=1
        if nodes>MAX_NODES or depth>12:raise ValueError('subtitle_discovery_limit')
        if isinstance(value,dict):
            for k,v in value.items():
                if not isinstance(k,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',k):continue
                where=path+'.'+k
                if re.search('subtitle|caption|utterance',k,re.I):fields.append(where)
                # Only the documented yt-dlp result schema is interpreted here.
                if k in ('subtitles','automatic_captions') and path in ('','.page_info.media_info','.video') and isinstance(v,dict):
                    for language,rows in v.items():
                        if not isinstance(language,str) or not LANG.fullmatch(language) or not isinstance(rows,list):continue
                        for row in rows[:100]:
                            if isinstance(row,dict) and row.get('ext') in ('vtt','srt'):
                                tracks.append({'url':row.get('url'),'ext':row['ext'],'language':language,'source_kind':'yt_dlp_subtitles_v1',
                                    'subtitle_kind':'platform_auto' if k=='automatic_captions' else 'unknown'})
                if k.lower() in ('videocodec','audiocodec','video_codecs','audio_codecs','vcodec','acodec') and isinstance(v,str) and re.fullmatch('[A-Za-z0-9_.-]{1,80}',v):codecs.append({'field':where,'value':v})
                if k in ('photoUrl','video_url','video_play_url','play_url','playUrl','masterUrl') and isinstance(v,str) and bool(v):video_seen=True
                if k=='type' and v in ('video','zvideo'):video_seen=True
                walk(v,where,depth+1)
        elif isinstance(value,list):
            for v in value:walk(v,path+'[]',depth+1)
        elif isinstance(value,str) and (path in ('.content','.content_text','.text') or re.fullmatch(r'\.(?:first_floor|post_list\[\])\.content',path)) and '<' in value and ('<video' in value.lower() or '<audio' in value.lower()):
            parser=TimedTracks();parser.feed(value);tracks.extend(parser.rows);video_seen=True
    walk(detail)
    if platform=='weibo' and isinstance(detail,dict) and isinstance(detail.get('page_info'),dict):
        from native_subtitles import toolkit
        toolkit() # Fixed package version, no extractor webpage/download entry point.
        from yt_dlp.extractor.weibo import WeiboBaseIE
        class Offline(WeiboBaseIE):
            def _download_webpage(self,*args,**kwargs):raise ValueError('subtitle_unexpected_source_request')
            def _download_json(self,*args,**kwargs):raise ValueError('subtitle_unexpected_source_request')
        formats=Offline()._extract_formats(detail)
        video_seen=video_seen or bool(formats)
        for item in formats[:100]:
            for key in ('vcodec','acodec'):
                v=item.get(key)
                if isinstance(v,str) and re.fullmatch('[A-Za-z0-9_.-]{1,80}',v):codecs.append({'field':'.yt_dlp.formats[].'+key,'value':v})
    public=[];private=[];seen=set()
    for row in tracks:
        url=track_url(platform,row['url'])
        if not url:continue
        sha=digest(url.encode());key=(sha,row['language'],row['ext'])
        if key in seen:continue
        if len(public)>=100:raise ValueError('subtitle_discovery_limit')
        seen.add(key);projection={k:v for k,v in row.items() if k!='url'};projection['track_url_sha256']=sha
        public.append(projection);private.append({**projection,'url':url})
    explicitly_nonvideo=isinstance(detail,dict) and platform=='xiaohongshu' and detail.get('type')=='normal' and not video_seen
    status='track_candidate' if public else 'not_video' if explicitly_nonvideo else 'unavailable'
    result={'schema':'crowd-native-subtitle-discovery-v1','provider':platform,'content_id':content_id,'content_type':content_type,
        'native_detail_canonical_sha256':digest(raw),'canonical_encoding':'sorted_json_utf8_v1','status':status,
        'reason':'declared_timed_text_track_requires_bounded_fetch' if public else 'selected_response_explicitly_nonvideo' if explicitly_nonvideo else 'no_declared_timed_text_track' if video_seen else 'video_presence_unknown',
        'track_candidates':public,'unparsed_field_paths':sorted(set(fields))[:100],'reported_codec_fields':codecs[:100],
        'semantic_completeness':'unknown','source_requests':0,'model_calls':0}
    return result,private


def parse_saved_track(raw,track,duration,source):
    """Offline parser contract. Source identity and declared track are supplied by the same-task observer."""
    from native_subtitles import parse_text,validate_segments,MAX_BYTES
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:raise ValueError('subtitle_response_limit')
    if not isinstance(source,dict) or source.get('schema')!='crowd-native-subtitle-discovery-v1' or source.get('status')!='track_candidate':raise ValueError('subtitle_source_invalid')
    if track not in source.get('track_candidates',[]) or set(track)!={'ext','language','source_kind','subtitle_kind','track_url_sha256'}:raise ValueError('subtitle_source_invalid')
    if track['source_kind'] not in ('html_track_v1','yt_dlp_subtitles_v1') or track['ext'] not in ('vtt','srt'):raise ValueError('subtitle_format_unsupported')
    rows=parse_text(raw.decode('utf-8-sig'),track['ext']);full=validate_segments(rows,duration)
    return {'schema':'crowd-discovered-subtitle-body-v1','platform':source['provider'],'content_id':source['content_id'],'content_type':source['content_type'],
        'source_projection_sha256':digest(encoded(source)),'raw_subtitle_sha256':digest(raw),'track':track,'duration_seconds':duration,'segments':rows,
        'status':'available' if full else 'partial','semantic_completeness':'unknown','spoken_transcript':False,'source_requests':0,'model_calls':0}


def observe(output,platform,detail,content_id,content_type=None):
    projection,_=discover(platform,detail,str(content_id),content_type)
    folder=safe_directory(Path(output)/platform/'subtitle-discovery');run_id=Path(output).parent.name
    # Immutable first observation is not a fetched/validated subtitle body or a cloud receipt.
    path=folder/(str(content_id)+(('.'+content_type) if content_type else '')+'.json')
    _safe_ancestors(path)
    if not path.exists():write(path,{**projection,'local_run_id':run_id})
    return projection


def observation_error(output):
    try:
        path=Path(output).parent/'phase.json';previous=read(path) if path.exists() else {}
        write(path,{**previous,'subtitle_discovery_status':'failed','subtitle_discovery_reason':'native_metadata_observation_failed','subtitle_discovery_source_requests':0})
    except (ValueError,TypeError,OSError):pass


def install_hooks(crawlers,platform,output):
    if platform in ('ks','wb','xhs'):
        cls=crawlers[platform];original=cls.download_media
        async def media(self,*args,**kwargs):
            names={'ks':'video_item','wb':'mblog','xhs':'note_detail'}
            detail=kwargs.get(names[platform],args[0] if args else None)
            if isinstance(detail,dict):
                cid=(detail.get('photo') or {}).get('id') if platform=='ks' else detail.get('note_id',detail.get('id',detail.get('idstr')))
                if cid is not None:
                    try:observe(output,PLATFORMS[platform],detail,cid)
                    except (ValueError,TypeError,OverflowError,ImportError,OSError):observation_error(output) # Preserve original media/body.
            return await original(self,*args,**kwargs)
        cls.download_media=media
    elif platform in ('zhihu','tieba'):
        import importlib
        module=importlib.import_module(platform+'_media');original=module.download_assets
        async def assets(data,cid,*args,**kwargs):
            ctype=(args[0] if args else kwargs.get('content_type')) if platform=='zhihu' else kwargs.get('content_type')
            # Shared Tieba downloader also receives Zhihu calls; only own original response is observed here.
            own=platform!='tieba' or kwargs.get('platform','tieba')=='tieba'
            if own:
                try:observe(output,platform,data,cid,ctype)
                except (ValueError,TypeError,OverflowError,ImportError,OSError):observation_error(output)
            return await original(data,cid,*args,**kwargs)
        module.download_assets=assets
