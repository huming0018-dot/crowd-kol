#!/usr/bin/env python3
"""Local, separately installed MediaCrawler bridge. No bundled upstream code."""
import argparse
import contextlib
from datetime import date
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time
import threading
import uuid
from urllib.parse import unquote, urlsplit, parse_qsl

PLATFORMS = {'xhs':'xiaohongshu','dy':'douyin','ks':'kuaishou','bili':'bilibili','wb':'weibo','tieba':'tieba','zhihu':'zhihu'}
NATIVE_MEDIA = {'xhs','dy','ks','bili','wb'}
MEDIA = NATIVE_MEDIA | {'tieba','zhihu'}
# JSONL writer names differ from CLI platform codes; retain older bridge output aliases.
JSONL_DIRS = {'dy':('douyin','dy'),'ks':('kuaishou','ks'),'wb':('weibo','wb')}
DISCOVERY_KINDS = frozenset(('search','detail','creator','homefeed','trending'))
FINAL = {'completed','failed','stopped','interrupted_unknown','login_required'}
STOP_REASONS = {'user': {'user_stop'}, 'cloud_worker': {'cloud_controller_error','cloud_dispatch_denied','cloud_worker_shutdown','owner_stop_requested'},
                'docker_worker': {'worker_shutdown'}}
STOP_ERRORS = {'cloud_outcome_unknown','invalid_cloud_lease','runner_outcome_unknown','invalid_runner_result',
               'worker_revoked','principal_denied','cloud_worker_failed'}
ID_KEYS = {'xhs':'note_id','dy':'aweme_id','ks':'video_id','bili':'video_id','wb':'note_id','tieba':'note_id','zhihu':'content_id'}
SECRET = re.compile(r'(?i)(?:cookie|authorization|access_token|refresh_token|xsec_token|token|password|passwd|secret|sessionid|api_key|x-amz-signature|x-amz-credential)\s*[=:]')

class BridgeError(Exception):
    pass

class SingleResponseLimit(SystemExit):
    """A per-response cap; total response/API limits remain hard process stops."""
    def __init__(self): super().__init__(76)

def contains_secret(value):
    for _ in range(3):
        if SECRET.search(value) or re.search(r'https?://[^/\s]+@',value,re.I):
            return True
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return False

def fail(code):
    raise BridgeError(code)

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'), allow_nan=False)

def write(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with open(tmp, 'x', encoding='utf8') as f:
        os.chmod(tmp, 0o600)
        f.write(canonical(value))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def read(path):
    with open(path, encoding='utf8') as f:
        return json.load(f)

def uid(value):
    try:
        result = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        fail('invalid_uuid')
    if value != result:
        fail('invalid_uuid')
    return result

def weibo_detail_id(value):
    # The upstream Weibo client appends its argument to /detail/ without URL parsing.
    # Preserve numeric IDs and alphanumeric bids; no unsupported base62 conversion.
    if '://' not in value:
        return value
    url=urlsplit(value)
    host=url.hostname or ''
    pattern=r'/[0-9]{1,20}/([A-Za-z0-9]{1,200})/?' if host in ('weibo.com','www.weibo.com') else r'/(?:detail|status)/([A-Za-z0-9]{1,200})/?' if host=='m.weibo.cn' else None
    match=re.fullmatch(pattern,url.path) if pattern else None
    if not match:
        fail('invalid_weibo_detail_url')
    return match.group(1)

def execution_target(platform,mode,value):
    if mode=='search': return value
    url=urlsplit(value) if '://' in value else None
    path=url.path.rstrip('/') if url else ''
    host=url.hostname if url else ''
    query=dict(parse_qsl(url.query,keep_blank_values=True)) if url else {}
    if platform=='wb' and mode=='detail': return weibo_detail_id(value)
    patterns={
        ('xhs','detail'):r'[0-9a-f]{24}',('xhs','creator'):r'[0-9a-f]{24}',
        ('dy','detail'):r'[0-9]{1,20}',('dy','creator'):r'[A-Za-z0-9_-]{1,200}',
        ('ks','detail'):r'[A-Za-z0-9_-]{1,200}',('ks','creator'):r'[A-Za-z0-9_-]{1,200}',
        ('bili','detail'):r'BV[A-Za-z0-9]{10}',('bili','creator'):r'[0-9]{1,20}',
        ('wb','creator'):r'[0-9]{1,20}',('tieba','detail'):r'[0-9]{1,20}',
        ('tieba','creator'):r'[A-Za-z0-9_.-]{1,200}',('zhihu','creator'):r'[A-Za-z0-9_-]{1,200}' }
    if url is None:
        if platform=='zhihu' and mode=='detail': fail('zhihu_detail_requires_typed_url')
        if not re.fullmatch(patterns[platform,mode],value): fail('invalid_'+platform+'_'+mode+'_target')
        return value
    target=None
    if platform=='xhs' and host in ('xiaohongshu.com','www.xiaohongshu.com'):
        match=re.fullmatch(r'/(?:explore|discovery/item)/([0-9a-f]{24})' if mode=='detail' else r'/user/profile/([0-9a-f]{24})',path)
        if match: return url._replace(path=path).geturl()
    elif platform=='dy' and host in ('douyin.com','www.douyin.com'):
        match=re.fullmatch(r'/video/([0-9]{1,20})' if mode=='detail' else r'/user/([A-Za-z0-9_-]{1,200})',path)
        target=query.get('modal_id') if mode=='detail' and query.get('modal_id') else match.group(1) if match else None
    elif platform=='dy' and mode=='detail' and host=='v.douyin.com' and re.fullmatch(r'/[A-Za-z0-9_-]+',path): return url._replace(path=path+'/').geturl()
    elif platform=='ks' and host in ('kuaishou.com','www.kuaishou.com'):
        match=re.fullmatch(r'/short-video/([A-Za-z0-9_-]{1,200})' if mode=='detail' else r'/profile/([A-Za-z0-9_-]{1,200})',path)
        target=match.group(1) if match else None
        if mode=='detail' and re.fullmatch(r'/f/[A-Za-z0-9_-]+',path): return url._replace(path=path).geturl()
    elif platform=='bili':
        match=re.fullmatch(r'/video/(BV[A-Za-z0-9]{10})',path) if mode=='detail' and host in ('www.bilibili.com','bilibili.com') else re.fullmatch(r'/([0-9]{1,20})',path) if mode=='creator' and host=='space.bilibili.com' else None
        target=match.group(1) if match else None
    elif platform=='wb' and mode=='creator':
        match=re.fullmatch(r'/(?:u/)?([0-9]{1,20})',path) if host in ('www.weibo.com','weibo.com') else re.fullmatch(r'/profile/([0-9]{1,20})',path) if host=='m.weibo.cn' else None
        target=match.group(1) if match else None
    elif platform=='tieba' and host=='tieba.baidu.com':
        match=re.fullmatch(r'/p/([0-9]{1,20})',path) if mode=='detail' else None
        if match: target=match.group(1)
        elif mode=='creator' and path=='/home/main':
            choices=[query[k] for k in ('id','portrait') if query.get(k)]
            if len(choices)==1: target=choices[0]
    elif platform=='zhihu':
        if mode=='detail':
            valid=host in ('www.zhihu.com','zhihu.com') and (re.fullmatch(r'/question/[0-9]+/answer/[0-9]+',path) or re.fullmatch(r'/zvideo/[0-9]+',path)) or host=='zhuanlan.zhihu.com' and re.fullmatch(r'/p/[0-9]+',path)
            if valid: return url._replace(path=path,query='').geturl()
        else:
            match=re.fullmatch(r'/people/([A-Za-z0-9_-]{1,200})',path) if host in ('www.zhihu.com','zhihu.com') else None
            target=match.group(1) if match else None
    if target is None or not re.fullmatch(patterns[platform,mode],target): fail('invalid_'+platform+'_'+mode+'_target')
    return target

def validate_options(p):
    options=p.setdefault('platform_options',{})
    if not isinstance(options,dict): fail('invalid_platform_options')
    if p['platform']!='bili':
        if options: fail('unsupported_platform_options')
        return
    if set(options)-{'creator_sections','search_mode','start_day','end_day','quality','long_audio'}: fail('unsupported_platform_options')
    sections=options.get('creator_sections',['videos'])
    if not isinstance(sections,list) or not sections or any(s not in ('videos','dynamics') for s in sections) or len(set(sections))!=len(sections): fail('invalid_creator_sections')
    if 'creator_sections' in options and p['mode']!='creator': fail('creator_options_require_creator_mode')
    if options.get('search_mode','normal') not in ('normal','all_in_time_range','daily_limit_in_time_range'): fail('invalid_bilibili_search_mode')
    if any(k in options for k in ('search_mode','start_day','end_day')) and p['mode']!='search': fail('search_options_require_search_mode')
    if options.get('search_mode','normal')!='normal':
        try:
            start=date.fromisoformat(options['start_day']);end=date.fromisoformat(options['end_day'])
        except (KeyError,TypeError,ValueError): fail('invalid_bilibili_date_range')
        if start>end: fail('invalid_bilibili_date_range')
    elif 'start_day' in options or 'end_day' in options: fail('date_range_requires_search_mode')
    if 'long_audio' in options and type(options['long_audio']) is not bool: fail('invalid_long_audio')
    if options.get('long_audio') and not p.get('media',False): fail('long_audio_requires_media')
    if 'quality' in options and (type(options['quality']) is not int or options['quality'] not in (16,32,64,80,112,116,120)): fail('invalid_bilibili_quality')
    if p['mode']=='creator' and sections==['dynamics']:
        for field in ('comments','replies','media'):
            if p.get(field,False): fail('bilibili_dynamics_'+field+'_unavailable')
            p.setdefault(field,False)

def validate(payload):
    allowed = {'platform','mode','targets','max_items','comments','replies','media','purpose','authorization_ref','session_id','max_api_requests','timeout_seconds','max_comments','headless','start_page','interval_seconds','platform_options','wordcloud'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        fail('invalid_request')
    p = dict(payload)
    if not isinstance(p.get('platform'),str) or p.get('platform') not in PLATFORMS or p.get('mode') not in ('search','detail','creator','homefeed','trending'):
        fail('unsupported_platform_or_mode')
    from discovery import SUPPORT
    discovery_mode = p['mode'] in SUPPORT
    if discovery_mode and p['platform'] not in SUPPORT[p['mode']]:
        fail('discovery_not_supported_for_platform')
    if p.get('purpose') not in ('noncommercial_research','licensed_use'):
        fail('license_basis_required')
    if p['purpose'] == 'licensed_use' and not isinstance(p.get('authorization_ref'), str):
        fail('authorization_ref_required')
    if 'authorization_ref' in p and (not isinstance(p['authorization_ref'],str) or not p['authorization_ref'] or len(p['authorization_ref']) > 200 or contains_secret(p['authorization_ref'])):
        fail('invalid_authorization_ref')
    targets = p.get('targets')
    if not isinstance(targets,list) or (targets != [] if discovery_mode else not 1 <= len(targets) <= 10) or any(not isinstance(t,str) or not t.strip() or len(t)>1000 or '\x00' in t or ',' in t for t in targets):
        fail('invalid_targets')
    hosts={'xhs':('xiaohongshu.com',),'dy':('douyin.com','iesdouyin.com'),'ks':('kuaishou.com','kuaishou.cn'),'bili':('bilibili.com',),'wb':('weibo.com','weibo.cn'),'tieba':('tieba.baidu.com',),'zhihu':('zhihu.com',)}
    for target in targets:
        if p['mode']=='search':
            if contains_secret(target): fail('credential_target_not_allowed')
        elif '://' in target:
            try:
                url=urlsplit(target)
                host=url.hostname or ''
                if url.scheme!='https' or url.username or url.password or url.port or url.fragment or not any(host==h or host.endswith('.'+h) for h in hosts[p['platform']]):
                    fail('invalid_platform_url')
            except ValueError:
                fail('invalid_platform_url')
            for key,value in parse_qsl(url.query,keep_blank_values=True):
                # XHS navigation locator stays only in the local 0600 manifest, never export/logs.
                if p['platform']=='xhs' and key.lower()=='xsec_token':
                    if not re.fullmatch(r'[A-Za-z0-9_=+/-]{1,500}',value): fail('invalid_navigation_locator')
                    continue
                if contains_secret(key+'='+value): fail('credential_target_not_allowed')
        elif not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}' if p['platform']=='tieba' and p['mode']=='creator' else r'[A-Za-z0-9_-]{1,200}',target):
            fail('invalid_target_id')
    for target in targets: execution_target(p['platform'],p['mode'],target)
    validate_options(p)
    for field, default, low, high in [('max_items',20,1,100),('max_comments',20,0,200),('max_api_requests',20,1,500),('timeout_seconds',600,30,1800),('start_page',1,1,10000)]:
        v = p.setdefault(field,default)
        if type(v) is not int or not low <= v <= high:
            fail('invalid_' + field)
    if 'interval_seconds' in p and (type(p['interval_seconds']) not in (int,float) or not 0 <= p['interval_seconds'] <= 300): fail('invalid_interval_seconds')
    if p['mode'] == 'search' and p['max_items'] < 20:
        fail('upstream_search_minimum_20')
    for field, default in [('comments',True),('replies',False),('media',False),('headless',False),('wordcloud',False)]:
        if type(p.setdefault(field, default)) is not bool:
            fail('invalid_' + field)
    if p['replies'] and not p['comments']:
        fail('replies_require_comments')
    if p['wordcloud'] and not p['comments']: fail('wordcloud_requires_comments')
    if p['media'] and p['platform'] not in MEDIA:
        fail('media_not_supported_by_upstream')
    if p['headless'] and not p.get('session_id'): fail('headless_requires_existing_session')
    p['session_id'] = uid(p['session_id']) if p.get('session_id') else str(uuid.uuid4())
    return p

def source_info(mc):
    mc = Path(mc).resolve()
    if not (mc/'main.py').is_file() or not (mc/'cmd_arg/arg.py').is_file() or not (mc/'LICENSE').is_file():
        fail('external_executor_missing')
    def git(*args):
        r = subprocess.run(['git','-C',str(mc),*args],capture_output=True,text=True,env=dict(os.environ,GIT_OPTIONAL_LOCKS='0'))
        return r.stdout.strip() if r.returncode == 0 else None
    return {'path':str(mc),'commit':git('rev-parse','HEAD'),'dirty':bool(git('status','--porcelain')),'license_sha256':hashlib.sha256((mc/'LICENSE').read_bytes()).hexdigest(),'license':'NON-COMMERCIAL LEARNING LICENSE 1.1; commercial written permission required'}

def capabilities(mc):
    info = source_info(mc)
    platforms=[]
    for p,name in PLATFORMS.items():
        features=[{'id':'comment_wordcloud','support_state':'implemented','live_verified':False,'notes':'optional upstream local generator; output presence checked separately'}]
        from discovery import SUPPORT
        discovery_modes = [mode for mode, platforms in SUPPORT.items() if p in platforms]
        features.extend({'id':mode,'support_state':'implemented','live_verified':False,'notes':'visible-page sample from normal homepage/ranking navigation; not following feed'} for mode in discovery_modes)
        if p=='bili':
            features.append({'id':'long_audio','support_state':'implemented','live_verified':False,'notes':'explicit audio-only DASH option; lowest available bandwidth, fixed 64MiB single audio/100MiB total, at most 2h; DURL-only responses do not trigger another request'})
            features.extend([{'id':'creator_dynamics','support_state':'implemented','live_verified':False,'notes':'separate dynamic identity; no dynamic comments or media download'}, {'id':'creator_relations','support_state':'unsupported','live_verified':False,'notes':'installed upstream callbacks do not persist followers/following'}, {'id':'video_quality','support_state':'implemented','live_verified':False,'notes':'requested quality is subject to session and source availability'}])
        if p=='tieba': features.append({'id':'public_post_media','support_state':'implemented','live_verified':False,'notes':'own adapter downloads at most three public CDN assets from the same native page response; not upstream media support'})
        if p=='zhihu': features.extend([{'id':'public_body_media','support_state':'implemented','live_verified':False,'notes':'own adapter observes at most three public body assets from the same native detail HTML or search/creator JSON; excerpt and CDN availability may limit coverage'}, {'id':'creator_articles','support_state':'planned','live_verified':False,'notes':'installed creator traversal is commented out'}, {'id':'creator_videos','support_state':'planned','live_verified':False,'notes':'installed creator traversal is commented out'}])
        platforms.append({'id':p,'name':name,'label':name,'notes':'source completeness unverified; max_items is upstream configuration','modes':['search','detail','creator',*discovery_modes],'support_state':'implemented','comments':True,'replies':True,'media':p in MEDIA,'live_verified':False,'limitations':(['creator currently answers only'] if p=='zhihu' else ['stored title/description may be truncated at 500 characters'] if p=='bili' else []),'platform_features':features})
    return {'schema':'crowd_mc_capabilities_v2','source':info,'platforms':platforms, 'source_kind':'mediacrawler_api','reward_eligible':False,'max_items_semantics':'upstream_configuration_not_hard_source_limit','api_request_limit_scope':'Python httpx/requests attempts, not browser resource requests','coverage':'unverified','execution_limits':{'session_concurrency':1,'start_page':[1,10000],'interval_seconds':[0,300],'interval_default':'installed_upstream_default'},'media_limits':{'single_file_bytes':26214400,'native_video_platforms':['dy','ks','bili'],'native_video_single_file_bytes':67108864,'python_response_bytes':104857600,'output_watchdog_bytes':104857600},'creator_profile_import':False,'login':'persistent profile by default; explicit selected existing loopback browser supported; native account verification; no credential import or debug-port launch'}

def configure_executor(config,p):
    config.CREATOR_MODE=True
    config.ENABLE_GET_WORDCLOUD=p.get('wordcloud',False)
    if p['platform']=='zhihu' and p['mode']=='creator': config.ZHIHU_CREATOR_URL_LIST=[execution_target(p['platform'],p['mode'],t) for t in p['targets']]
    if 'interval_seconds' in p: config.CRAWLER_MAX_SLEEP_SEC=p['interval_seconds']
    if p['platform']=='bili':
        options=p.get('platform_options',{})
        config.CREATOR_MODE='videos' in options.get('creator_sections',['videos'])
        config.CRAWLER_MAX_DYNAMICS_COUNT_SINGLENOTES=p['max_items']
        config.BILI_SEARCH_MODE=options.get('search_mode','normal')
        if config.BILI_SEARCH_MODE!='normal':
            config.START_DAY=options['start_day'];config.END_DAY=options['end_day']
        if 'quality' in options: config.BILI_QN=options['quality']

def configure_platform_hooks(upstream,p):
    if p['platform']=='ks' and p['comments']:
        from media_platform.kuaishou.client import KuaiShouClient
        from store.kuaishou import KuaishouStoreFactory
        from kuaishou_comments import install_hook as install_comment_hook
        install_comment_hook(KuaiShouClient,KuaishouStoreFactory)
    if p['platform'] in ('dy','ks') and p['media']:
        from native_media_scope import install_hook
        install_hook(upstream.CrawlerFactory.CRAWLERS[p['platform']],p['platform'],Path.cwd()/'output',SingleResponseLimit,read,write)
    if p['platform']=='zhihu' and p['media']:
        from media_platform.zhihu.client import ZhiHuClient
        from zhihu_media import install_hook
        install_hook(ZhiHuClient,Path.cwd()/'output')
    if p['platform']=='bili' and p['media']:
        from native_media_scope import NATIVE_VIDEO_MEDIA_ACTIVE,install_ffmpeg_path,save_bilibili_identity
        crawler=upstream.CrawlerFactory.CRAWLERS['bili']
        original_media=crawler.download_media
        options=p.get('platform_options',{})
        if options.get('long_audio') is not True and type(options.get('quality')) is int and options['quality']==16:
            from media_platform.bilibili import media as bili_media
            from bili_media_selection import install_low_audio_selection
            def audio_selection(value):
                phase=Path.cwd()/'phase.json';previous=read(phase) if phase.exists() else {}
                write(phase,{**previous,'media_audio_selection':value})
            install_low_audio_selection(bili_media,16,audio_selection)
        if not p.get('platform_options',{}).get('long_audio') and os.environ.get('CROWD_FFMPEG'):
            import media_downloader
            import media_downloader.ffmpeg as native_ffmpeg
            install_ffmpeg_path(media_downloader,native_ffmpeg)
        if p.get('platform_options',{}).get('long_audio'):
            from bili_audio import download_audio
            from media_platform.bilibili.media import DASH_FNVAL
            async def audio_only(self,video_item,semaphore):
                view=video_item.get('View') or {}
                aid=view.get('aid');cid=view.get('cid');content_id=view.get('bvid') or (str(aid) if aid else '')
                play_evidence={'status':'not_requested','source':'native_bilibili_client'}
                if not aid or not cid or not content_id:
                    result={'status':'unavailable','reason':'audio_identity_missing'}
                else:
                    try:
                        # Native task wrapper swallows request failures; use its same SDK call once.
                        async with semaphore:
                            play=await self.bili_client.get_video_play_url(aid=aid,cid=cid,fnval=DASH_FNVAL)
                    except Exception:
                        play_evidence['status']='request_failed'
                        result={'status':'failed','reason':'audio_play_request_failed'}
                    else:
                        if not isinstance(play,dict):
                            play_evidence['status']='response_invalid'
                            result={'status':'failed','reason':'audio_play_response_invalid'}
                        else:
                            dash=play.get('dash');audio=dash.get('audio') if isinstance(dash,dict) else None
                            play_evidence.update({'status':'native_success','dash_present':isinstance(dash,dict),
                                                 'audio_list_present':isinstance(audio,list),
                                                 'audio_entries':min(len(audio),1000) if isinstance(audio,list) else 0,
                                                 'durl_present':isinstance(play.get('durl'),list) and bool(play['durl'])})
                            try:
                                client_headers=getattr(self.bili_client,'headers',{})
                                user_agent=client_headers.get('User-Agent') if isinstance(client_headers,dict) else None
                                result=await download_audio(play,content_id,Path.cwd()/'output',view.get('duration'),user_agent=user_agent)
                            except Exception:
                                result={'status':'failed','reason':'audio_adapter_failed'}
                phase=Path.cwd()/'phase.json';previous=read(phase) if phase.exists() else {}
                write(phase,{**previous,'media_status':result['status'],'media_reason':result.get('reason'),
                             'media_play_response':play_evidence,
                             'media_audio_selection':result.get('selection_diagnostics'),
                             'media_http_status':result.get('http_status'),
                             'media_native_user_agent_used':result.get('native_user_agent_used'),
                             'media_kind':'audio','media_single_file_limit_bytes':67108864,
                             'media_duration_seconds_reported':result.get('duration_seconds_reported')})
            original_media=audio_only
        async def bounded_media(self,*args,**kwargs):
            folder=Path.cwd()/'output/bili/media'
            before=set(folder.rglob('*.part')) if folder.exists() else set()
            token=NATIVE_VIDEO_MEDIA_ACTIVE.set(p.get('platform_options',{}).get('long_audio') is not True)
            try:
                save_bilibili_identity(kwargs.get('video_item') if 'video_item' in kwargs else args[0] if args else None,Path.cwd()/'output',read,write)
                return await original_media(self,*args,**kwargs)
            except SingleResponseLimit:
                for path in set(folder.rglob('*.part'))-before:
                    path.unlink(missing_ok=True)
                phase=Path.cwd()/'phase.json'
                previous=read(phase) if phase.exists() else {}
                write(phase,{**previous,'media_status':'limited','media_reason':'single_response_byte_limit',
                             'media_single_file_limit_bytes':67108864})
            finally:
                NATIVE_VIDEO_MEDIA_ACTIVE.reset(token)
        crawler.download_media=bounded_media
    if p['platform']=='tieba':
        from media_platform.tieba.client import BaiduTieBaClient
        from media_platform.tieba.help import TieBaExtractor
        from tieba_body import install_hook as install_body_hook
        install_body_hook(BaiduTieBaClient,TieBaExtractor,Path.cwd())
    if p['platform']=='tieba' and p['media']:
        from media_platform.tieba.client import BaiduTieBaClient
        from tieba_media import install_hook
        install_hook(BaiduTieBaClient,Path.cwd()/'output')
    if p['mode'] in ('homefeed','trending'):
        from discovery import configure_discovery
        configure_discovery(upstream,p,Path.cwd())
    if p['platform']=='bili' and p['mode']=='creator' and set(p.get('platform_options',{}).get('creator_sections',[]))=={'videos','dynamics'}:
        crawler=upstream.CrawlerFactory.CRAWLERS['bili']
        original=crawler.get_creator_videos
        async def videos_and_dynamics(self,creator_id):
            await original(self,creator_id)
            await self.get_all_creator_details([str(creator_id)])
        crawler.get_creator_videos=videos_and_dynamics

def configure_wordcloud(upstream,config,p,mc,run):
    if not p.get('wordcloud'): return
    def outcome(state):
        phase=read(run/'phase.json') if (run/'phase.json').exists() else {'phase':'running','api_attempts':0}
        write(run/'phase.json',{**phase,'wordcloud_status':state})
    for field in ('FONT_PATH','STOP_WORDS_FILE'):
        resource_path=Path(getattr(config,field,''))
        if not resource_path.is_absolute(): resource_path=Path(mc)/resource_path
        if not resource_path.is_file():
            config.ENABLE_GET_WORDCLOUD=False
            async def unavailable(): outcome('resource_missing')
            upstream._generate_wordcloud_if_needed=unavailable
            outcome('resource_missing')
            return
        setattr(config,field,str(resource_path.resolve()))
    async def generate():
        try:
            from tools.async_file_writer import AsyncFileWriter
            await AsyncFileWriter(platform=JSONL_DIRS.get(p['platform'],(p['platform'],))[0],crawler_type=p['mode']).generate_wordcloud_from_comments()
            folder=run/'output'/JSONL_DIRS.get(p['platform'],(p['platform'],))[0]/'words'
            generated=any(folder.glob('*_word_cloud.png')) and any(folder.glob('*_word_freq.json'))
            state='generated' if generated else 'no_output'
        except (ModuleNotFoundError,ImportError): state='dependency_missing'
        except Exception: state='generation_failed'
        outcome(state)
    upstream._generate_wordcloud_if_needed=generate

def run_dir(root, run_id):
    folder = Path(root).resolve()/'runs'/uid(run_id)
    if not folder.is_dir():
        fail('run_not_found')
    return folder

def start(root, mc, payload):
    p = validate(payload)
    info = source_info(mc)
    root = Path(root).resolve()
    mc = Path(mc).resolve()
    python = mc/'.venv/bin/python'
    if not python.is_file():
        fail('external_python_missing')
    if root == mc or mc in root.parents:
        fail('runtime_must_be_outside_upstream')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    session = root/'sessions'/p['session_id']
    if p['headless'] and not (session/'identity.json').is_file():
        fail('headless_requires_existing_session')
    session.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(session/'active.lock','a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        fail('session_busy')
    identity = session/'identity.json'
    if identity.exists() and read(identity)['platform'] != p['platform']:
        lock.close()
        fail('session_platform_mismatch')
    write(identity, {'platform':p['platform']})
    run_id = str(uuid.uuid4())
    run = root/'runs'/run_id
    run.mkdir(parents=True,mode=0o700)
    (run/'output').mkdir(mode=0o700)
    # Reference only immutable runtime resources; upstream is not copied or edited.
    (run/'libs').symlink_to(mc/'libs',target_is_directory=True)
    (run/'media_platform/kuaishou').mkdir(parents=True)
    (run/'media_platform/kuaishou/graphql').symlink_to(mc/'media_platform/kuaishou/graphql',target_is_directory=True)
    (run/'browser_data').symlink_to(session/'browser_data',target_is_directory=True)
    (session/'browser_data').mkdir(exist_ok=True,mode=0o700)
    manifest = {'run_id':run_id,'request':p,'source':info,'created_at':time.time(),'source_kind':'mediacrawler_api','reward_eligible':False,'discovery_contract_version':1}
    write(run/'manifest.json',manifest)
    write(run/'status.json',{'run_id':run_id,'state':'starting','phase':'starting','session_id':p['session_id'],'platform':p['platform'],'mode':p['mode'],'source_kind':'mediacrawler_api','reward_eligible':False,'updated_at':time.time()})
    proc = subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--root',str(root),'--mc-root',str(mc),'_worker','--run-id',run_id,'--lock-fd',str(lock.fileno())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,pass_fds=(lock.fileno(),))
    lock.close()
    return {'run_id':run_id,'state':'starting','session_id':p['session_id'],'supervisor_pid':proc.pid,'source_kind':'mediacrawler_api','reward_eligible':False}

def argv_for(p, output):
    args = ['--platform',p['platform'],'--type','search' if p['mode'] in ('homefeed','trending') else p['mode'],'--lt','qrcode','--headless',str(p['headless']).lower(),'--save_data_option','jsonl','--save_data_path',str(output),'--crawler_max_notes_count',str(p['max_items']),'--max_concurrency_num','1','--start',str(p.get('start_page',1)),'--max_comments_count_singlenotes',str(p['max_comments']),'--get_comment',str(p['comments']).lower(),'--get_sub_comment',str(p['replies']).lower(),'--get_media',str(p['media'] and p['platform'] in NATIVE_MEDIA).lower(),'--enable_ip_proxy','false']
    if p['mode'] in ('homefeed','trending'):
        return args
    targets=[execution_target(p['platform'],p['mode'],t) for t in p['targets']]
    args += [{'search':'--keywords','detail':'--specified_id','creator':'--creator_id'}[p['mode']],','.join(targets)]
    return args

def stop_metadata(payload):
    origin=payload.get('origin','user');reason=payload.get('reason','user_stop')
    if not isinstance(origin,str) or not isinstance(reason,str) or reason not in STOP_REASONS.get(origin,set()):
        fail('invalid_stop_request')
    value={'origin':origin,'reason':reason}
    for key in ('lease_epoch','heartbeat_sequence'):
        if key in payload:
            number=payload[key]
            if origin!='cloud_worker' or type(number) is not int or not (1 if key=='lease_epoch' else 0)<=number<=9007199254740991:
                fail('invalid_stop_request')
            value[key]=number
    if 'error_code' in payload:
        if reason!='cloud_controller_error' or not isinstance(payload['error_code'],str) or payload['error_code'] not in STOP_ERRORS:
            fail('invalid_stop_request')
        value['error_code']=payload['error_code']
    if 'desired_state' in payload:
        if origin!='cloud_worker' or payload['desired_state'] not in ('running','paused','stopped'):fail('invalid_stop_request')
        value['desired_state']=payload['desired_state']
    return value

def safe_stop_context(marker):
    try:
        value=stop_metadata(marker) if isinstance(marker,dict) and 'origin' in marker and 'reason' in marker else {'origin':'unknown','reason':'legacy_stop_requested'}
        requested=marker.get('requested_at') if isinstance(marker,dict) else None
        if type(requested) in (int,float) and 0<=requested<=9007199254740991:value['requested_at']=requested
        return value
    except (BridgeError,ValueError,OSError,TypeError):
        return {'origin':'unknown','reason':'legacy_stop_requested'}

def stop_context(run):
    path=Path(run)/'stop.json'
    if not path.exists():return {}
    if path.is_symlink():fail('unsafe_stop_marker')
    try:return safe_stop_context(read(path))
    except (ValueError,OSError):return {'origin':'unknown','reason':'legacy_stop_requested'}

def status(root, payload):
    run = run_dir(root,payload.get('run_id'))
    state = read(run/'status.json')
    context=stop_context(run)
    if context:
        state={**state,'stop_context':context,'stop_origin':context['origin']}
        if state['state']=='stopped':state['reason']=context['reason']
    # No inference of success from the supervisor or browser disappearing.
    if state['state'] not in FINAL and time.time()-state['updated_at'] > 8:
        state = {**state,'state':'interrupted_unknown','reason':'supervisor_heartbeat_missing'}
    return state

def stop(root,payload):
    run = run_dir(root,payload.get('run_id'))
    if set(payload)-{'run_id','origin','reason','lease_epoch','heartbeat_sequence','error_code','desired_state'}:fail('invalid_stop_request')
    metadata=stop_metadata(payload)
    s = status(root,payload)
    if s['state'] in ('completed','failed','stopped','login_required'):
        return s
    marker=run/'stop.json'
    if marker.is_symlink():fail('unsafe_stop_marker')
    # Link a complete private snapshot exclusively: the first stop cause is immutable.
    temp=run/('stop.'+uuid.uuid4().hex+'.tmp')
    try:
        with open(temp,'x',encoding='utf8') as stream:
            os.chmod(temp,0o600);stream.write(canonical({'requested_at':time.time(),**metadata}));stream.flush();os.fsync(stream.fileno())
        try:os.link(temp,marker)
        except FileExistsError:pass
    finally:
        if temp.exists():temp.unlink()
    context=stop_context(run)
    return {**s,'stop_requested':True,'stop_context':context,'stop_origin':context['origin']}

def worker(root, mc, run_id, lock_fd):
    run = run_dir(root,run_id)
    manifest = read(run/'manifest.json')
    p = manifest['request']
    state = read(run/'status.json')
    from browser_session import existing_browser_session, terminate_executor
    # Legacy supervisors have no browser binding metadata: keep their owned-process shutdown.
    borrowed=existing_browser_session(root,p['session_id']) if 'session_id' in p else False
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1', MPLCONFIGDIR=str(run/'cache/matplotlib'), XDG_CACHE_HOME=str(run/'cache'),CROWD_MC_SUPERVISOR_PID=str(os.getpid()))
    child = subprocess.Popen([str(Path(mc)/'.venv/bin/python'),str(Path(__file__).resolve()),'--root',str(root),'--mc-root',str(mc),'_execute','--run-id',run_id],cwd=run,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,pass_fds=(lock_fd,))
    started = time.monotonic()
    reason = None
    from native_media_scope import output_byte_usage
    while child.poll() is None:
        try:output_limited=output_byte_usage(run/'output',p,child.pid)['limited']
        except (OSError,ValueError):output_limited=True
        if (run/'stop.json').exists() or time.monotonic()-started > p['timeout_seconds'] or output_limited:
            reason = stop_context(run)['reason'] if (run/'stop.json').exists() else 'output_byte_limit' if output_limited else 'wall_timeout'
            terminate_executor(child.pid,borrowed)
            try:
                child.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL)
                child.wait()
            break
        progress = read(run/'phase.json') if (run/'phase.json').exists() else {'phase':'running','api_attempts':0}
        active_state=progress.get('phase') if progress.get('phase') in ('running','waiting_login','login_required','collecting','comments','media') else 'running'
        state.update(progress, state=active_state, updated_at=time.time())
        write(run/'status.json',state)
        time.sleep(0.5)
    code = child.wait()
    if (run/'stop.json').exists():
        context=stop_context(run);reason=context['reason'];state.update(stop_context=context,stop_origin=context['origin'])
    elif time.monotonic()-started>p['timeout_seconds'] and reason is None: reason='wall_timeout'
    final = 'stopped' if (run/'stop.json').exists() else 'login_required' if code in (77,78) else 'completed' if code==0 and not reason else 'failed'
    progress = read(run/'phase.json') if (run/'phase.json').exists() else {}
    state.update(progress)
    if (reason is None and code == 74 and p.get('mode') in ('homefeed','trending')
            and progress.get('failure_type') == 'DiscoveryUnavailable'
            and progress.get('failure_stage') == 'homepage_observation'
            and progress.get('failure_reason') == 'discovery_empty_or_unavailable'):
        reason='discovery_empty_or_unavailable'
    state.update(state=final,phase=final,reason=reason or {0:'executor_finished',72:'dependency_missing',73:'api_request_limit',74:'executor_error',76:'response_byte_limit',77:'login_required',78:'account_changed'}.get(code,'executor_error'),exit_code=code,updated_at=time.time(),coverage='unverified')
    write(run/'status.json',state)
    os.close(lock_fd)

def execute(root, mc, run_id):
    run = run_dir(root,run_id)
    p = read(run/'manifest.json')['request']
    os.chdir(run)
    sys.path.insert(0,str(Path(mc).resolve()))
    sys.dont_write_bytecode=True
    attempts=0
    account_store=None
    response_bytes=0
    native_media=p['platform'] in ('dy','ks','bili') and p.get('media') is True
    file_limit=67108864 if native_media or p['platform']=='bili' and p.get('platform_options',{}).get('long_audio') else 26214400
    resource.setrlimit(resource.RLIMIT_FSIZE,(file_limit,file_limit))
    phase='running'
    def event(new=None):
        nonlocal phase
        phase = new or phase
        previous=read(run/'phase.json') if (run/'phase.json').exists() else {}
        write(run/'phase.json',{**previous,'phase':phase,'api_attempts':attempts})
    # Raw upstream logs can contain credential URLs. Only constant phase labels leave here.
    class Sink:
        def write(self, text):
            low=text.lower()
            if any(t in low for t in ('qrcode','scan qr','scan the qr','login required','login by')):
                event('login_required' if p['headless'] else 'waiting_login')
            elif 'comment' in low:
                event('comments')
            elif 'download' in low or 'media file' in low:
                event('media')
            elif 'search' in low or 'get_specified' in low or 'note detail' in low:
                event('collecting')
            return len(text)
        def flush(self): pass
        def isatty(self): return False
    parent_pid=int(os.environ.get('CROWD_MC_SUPERVISOR_PID','0'))
    if parent_pid<=1:
        raise SystemExit(74)
    deadline=time.monotonic()+p['timeout_seconds']
    finished=threading.Event()
    from browser_session import existing_browser_session, terminate_executor, ExecutorCancellation
    borrowed=existing_browser_session(root,p['session_id'])
    cancellation=ExecutorCancellation() if borrowed else None
    if cancellation is not None:cancellation.install()
    def child_watchdog():
        while not finished.wait(.25):
            orphaned=os.getppid()!=parent_pid
            stopped=(run/'stop.json').exists()
            timed_out=time.monotonic()>deadline
            if orphaned or stopped or timed_out:
                if orphaned:
                    try:
                        state=read(run/'status.json')
                        state.update(state='interrupted_unknown',phase='interrupted_unknown',reason='supervisor_lost',updated_at=time.time())
                        write(run/'status.json',state)
                    except (OSError,ValueError):
                        pass
                # Only the freshly created executor's own process group, never a recovered PID.
                if borrowed:
                    terminate_executor(os.getpid(),True)
                    # Orphaned executors also retain a bounded cleanup grace.
                    if not finished.wait(5) and os.getpgrp()==os.getpid():
                        os.killpg(os.getpgrp(),signal.SIGKILL)
                elif os.getpgrp()==os.getpid():
                    os.killpg(os.getpgrp(),signal.SIGTERM)
                else:
                    os.kill(os.getpid(),signal.SIGTERM)
                return
    threading.Thread(target=child_watchdog,daemon=True).start()
    try:
        with contextlib.redirect_stdout(Sink()),contextlib.redirect_stderr(Sink()):
            import config
            config.ENABLE_CDP_MODE=False
            config.CDP_CONNECT_EXISTING=False
            config.COOKIES=''
            config.ENABLE_IP_PROXY=False
            config.SAVE_LOGIN_STATE=True
            config.USER_DATA_DIR='%s_bridge_profile'
            configure_executor(config,p)
            config.ENABLE_GET_CONTACTS=False
            config.ENABLE_GET_DYNAMICS=False
            import httpx
            import requests
            budget_lock=threading.Lock()
            def debit():
                nonlocal attempts
                with budget_lock:
                    if attempts>=p['max_api_requests']:
                        event('api_request_limit')
                        raise SystemExit(73)
                    attempts+=1
                    event()
            old_async=httpx.AsyncClient.send
            old_sync=httpx.Client.send
            old_requests=requests.sessions.Session.send
            async def async_send(self,*a,**kw):
                debit()
                response=await old_async(self,*a,**kw)
                if account_store is not None:
                    guard_auth_response(account_store,p['session_id'],p['platform'],run_id,account_event,response)
                return response
            def sync_send(self,*a,**kw):
                debit()
                response=old_sync(self,*a,**kw)
                if account_store is not None:
                    guard_auth_response(account_store,p['session_id'],p['platform'],run_id,account_event,response)
                return response
            def requests_send(self,*a,**kw):
                debit()
                response=old_requests(self,*a,**kw)
                if account_store is not None:
                    guard_auth_response(account_store,p['session_id'],p['platform'],run_id,account_event,response)
                return response
            httpx.AsyncClient.send=async_send
            httpx.Client.send=sync_send
            requests.sessions.Session.send=requests_send
            if hasattr(httpx,'Response'):
                old_bytes=httpx.Response.aiter_bytes
                async def bounded_bytes(self,*a,**kw):
                    nonlocal response_bytes
                    response_size=0
                    async for chunk in old_bytes(self,*a,**kw):
                        response_size+=len(chunk)
                        with budget_lock:
                            response_bytes+=len(chunk)
                            if response_bytes>104857600:
                                event('response_byte_limit')
                                raise SystemExit(76)
                            from bili_audio import AUDIO_RESPONSE_ACTIVE
                            from native_media_scope import response_limit as native_response_limit
                            try:response_host=self.request.url.host
                            except (AttributeError,RuntimeError):response_host=None
                            response_limit=native_response_limit(p['platform'],getattr(self,'headers',{}).get('content-type'),response_host,
                                audio_response_active=p['platform']=='bili' and p.get('platform_options',{}).get('long_audio') is True and AUDIO_RESPONSE_ACTIVE.get())
                            if response_size>response_limit:
                                event('response_byte_limit')
                                raise SingleResponseLimit()
                        yield chunk
                httpx.Response.aiter_bytes=bounded_bytes
            from playwright.async_api import BrowserType
            old_launch=BrowserType.launch
            old_persistent=BrowserType.launch_persistent_context
            def browser_options(browser,kwargs):
                if browser.name=='chromium' and not Path(browser.executable_path).is_file() and not kwargs.get('executable_path'):
                    chrome=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
                    if not chrome.is_file(): raise ModuleNotFoundError('browser_binary_missing')
                    kwargs['executable_path']=str(chrome)
                return kwargs
            async def launch(browser,*a,**kw):
                return await old_launch(browser,*a,**browser_options(browser,kw))
            async def persistent(browser,*a,**kw):
                return await old_persistent(browser,*a,**browser_options(browser,kw))
            BrowserType.launch=launch
            BrowserType.launch_persistent_context=persistent
            import main as upstream
            from account_sessions import install_hooks, guard_auth_response
            def account_event(account_state, account):
                nonlocal phase
                phase='waiting_login' if account_state in ('logged_out','waiting_login','identity_unverified','account_changed','check_failed') else 'running'
                current=read(run/'phase.json') if (run/'phase.json').exists() else {}
                # Publish account and phase together so the supervisor never reads a partial event.
                write(run/'phase.json',{**current,'phase':phase,'api_attempts':attempts,'account_state':account_state,
                    'account_generation':account.get('generation',0),
                    'account_identity_status':account.get('identity_status','unverified')})
            account_store=install_hooks(root,p['session_id'],p['platform'],run_id,account_event,p['headless'])
            from browser_session import install_browser_reuse
            install_browser_reuse(account_store,p['session_id'],p['platform'],BrowserType,upstream.CrawlerFactory.CRAWLERS[p['platform']])
            configure_platform_hooks(upstream,p)
            configure_wordcloud(upstream,config,p,mc,run)
            import asyncio
            sys.argv=[str(Path(mc)/'main.py'),*argv_for(p,run/'output')]
            async def crawl():
                try:
                    await asyncio.wait_for(upstream.main(), timeout=p['timeout_seconds'])
                finally:
                    await asyncio.wait_for(upstream.async_cleanup(), timeout=10)
            asyncio.run(cancellation.run(crawl()) if cancellation is not None else crawl())
    except (ModuleNotFoundError,ImportError):
        raise SystemExit(72)
    except SystemExit:
        raise
    except BaseException as exc:
        from discovery import failure_metadata
        write(run/'phase.json',{'phase':'failed','api_attempts':attempts,
                               'failure_type':type(exc).__name__[:80],**failure_metadata(exc)})
        raise SystemExit(74)
    finally:
        finished.set()
        if cancellation is not None:cancellation.restore()

# This is a bounded output projection, not a DOM evidence adapter or a universal DLP.
def safe_text(value, limit=24000):
    if value is None: return None
    if not isinstance(value,str): return None
    if contains_secret(value): return None
    return value[:limit]

def opaque(value):
    if isinstance(value,int) and not isinstance(value,bool): value=str(value)
    return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',value) and value not in ('None','null') else None

def reported_count(value):
    if type(value) is int and 0<=value<=9007199254740991: return value
    if isinstance(value,str) and re.fullmatch(r'[0-9]{1,16}',value) and int(value)<=9007199254740991: return int(value)
    return None

def normalize(platform, kind, row, origin):
    if not isinstance(row,dict): fail('invalid_output_record')
    if kind not in ('content','comment','dynamic') or kind=='dynamic' and platform!='bili': fail('unsupported_output_kind')
    cid=opaque(row.get('dynamic_id') if kind=='dynamic' else row.get(ID_KEYS[platform]))
    if not cid: fail('missing_content_id')
    result={'platform':PLATFORMS[platform],'content_id':cid,'kind':kind,'source_kind':'mediacrawler_api','reward_eligible':False,'coverage':'unverified','origin':origin}
    if kind=='comment':
        result.update(comment_id=opaque(row.get('comment_id')),parent_comment_id=opaque(row.get('parent_comment_id')),text=safe_text(row.get('content')),reported_reply_count=reported_count(row.get('sub_comment_count')))
        # These stores explicitly use an empty parent for a root; absent stays unknown.
        if platform in ('xhs','tieba') and row.get('parent_comment_id')=='':
            result['parent_comment_id']=''
        if platform=='ks' and row.get('parent_relation_basis') in ('reported_root_endpoint','reported_subcomment_root_scope'):
            result['parent_relation_basis']=row['parent_relation_basis']
        if not result['comment_id']: fail('missing_comment_id')
    else:
        result.update(title=safe_text(row.get('title'),2000),body=safe_text(next((row[k] for k in ('desc','content_text','content','text') if row.get(k) is not None),None)),content_type=safe_text(row.get('content_type') or row.get('video_type') or row.get('type'),80))
    result['canonical_id_scheme']='bilibili.dynamic.v1' if kind=='dynamic' else 'bilibili.aid.v1' if platform=='bili' and cid.isdecimal() else 'bilibili.bvid.v1' if platform=='bili' and re.fullmatch(r'BV[A-Za-z0-9]{10}',cid) else PLATFORMS[platform]+'.source_id.v1'
    result['platform_fields']={k:v for k in ('video_type','type','content_type','creator_hash','nickname','user_name') if (v:=safe_text(row.get(k),2000)) is not None}
    author_hash=opaque(safe_text(row.get('creator_hash'),200))
    author_id=author_hash or next((value for key in ('author_id','creator_id','user_id') if (value:=opaque(row.get(key))) is not None),None)
    if author_id:
        result['author']={'author_id':author_id,'identity_status':'anonymized_upstream' if author_hash else 'reported_upstream','id_scheme':'upstream_anonymous_hash' if author_hash else PLATFORMS[platform]+'.creator_id.v1','display_name':safe_text(row.get('nickname') or row.get('user_name'),2000)}
    if kind!='comment':
        title=row.get('title')
        result['title_status']='withheld_sensitive' if isinstance(title,str) and contains_secret(title) else 'reported' if isinstance(title,str) else 'missing'
        result['title_truncated']=isinstance(title,str) and len(title)>2000
    metrics={}
    for key in ('liked_count','like_count','disliked_count','comment_count','comments_count','share_count','shared_count','collected_count','view_count','play_count','video_play_count','video_review_count','voteup_count','forward_count','video_favorite_count','video_share_count','video_coin_count','video_danmaku','video_comment','comment_like_count','total_replay_num','total_comments','total_forwards','total_liked'):
        value=row.get(key)
        if type(value) is int and value>=0 or isinstance(value,str) and re.fullmatch(r'[0-9.,万千亿wWkKmM+ ]{1,40}',value):
            metrics[key]={'reported_value':value,'semantics':'upstream_reported_not_independently_verified'}
    result['metrics']=metrics
    result['upstream_transport']='platform_dependent_api_or_browser_html'
    if kind=='comment':
        reported_root=(platform in ('xhs','tieba') and result['parent_comment_id']=='') or (platform=='wb' and result['parent_comment_id']==result['comment_id']) or (platform=='ks' and result.get('parent_relation_basis')=='reported_root_endpoint' and result['parent_comment_id']=='0')
        result['parent_status']='reported_root' if reported_root else 'reported' if result['parent_comment_id'] is not None else 'missing_upstream'
        result['reply_count_semantics']='upstream_reported_not_independently_verified'
    result['published_at_reported']=next((row[k] for k in ('time','create_time','created_time','publish_time','pub_ts') if type(row.get(k)) is int or isinstance(row.get(k),str) and len(row[k])<=80 and not contains_secret(row[k])),None)
    result['entity_key']=result['platform']+':'+cid+(':'+result['comment_id'] if kind=='comment' else '')
    if kind=='dynamic': result['entity_key']=result['platform']+':dynamic:'+cid
    text_value = row.get('content') if kind=='comment' else next((row[k] for k in ('desc','content_text','content','text') if row.get(k) is not None),None)
    result['text_status']='withheld_sensitive' if isinstance(text_value,str) and contains_secret(text_value) else 'reported' if isinstance(text_value,str) else 'missing'
    result['text_truncated']=isinstance(text_value,str) and len(text_value)>24000
    result['text_completeness']='partial' if result['text_truncated'] else 'unknown'
    if platform=='bili' and kind=='content':
        result['upstream_truncation_risk']={'fields':['title','body'],'limit_chars':500,'reason':'installed_upstream_store_slices_title_and_description'}
    result['record_hash']=hashlib.sha256(canonical(result).encode()).hexdigest()
    return result

def import_output(root,payload):
    run=run_dir(root,payload.get('run_id'))
    s=status(root,payload)
    if s['state'] not in FINAL: fail('run_not_finished')
    manifest=read(run/'manifest.json')
    if s['state']=='interrupted_unknown':
        session=Path(root).resolve()/'sessions'/uid(manifest['request']['session_id'])
        with open(session/'active.lock','a+') as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                fail('executor_still_active')
    p=manifest['request']['platform']
    output=run/'output'
    records=[]
    files=[]
    rejected=0
    paths=[]
    for name in JSONL_DIRS.get(p,(p,)):
        folder=output/name/'jsonl'
        if folder.is_symlink() or folder.parent.is_symlink(): fail('unsafe_output_file')
        paths.extend(sorted(folder.glob('*.jsonl')))
    seen_rows={}
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(output.resolve()) or path.stat().st_size>50_000_000: fail('unsafe_output_file')
        kind='comment' if '_comments_' in path.name else 'content' if '_contents_' in path.name else 'dynamic' if p=='bili' and '_dynamics_' in path.name else None
        if not kind: continue
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({'path':str(path.relative_to(run)),'sha256':digest})
        with open(path,encoding='utf8') as f:
            for number,line in enumerate(f,1):
                if number>10000 or len(line)>1_000_000: fail('output_limit')
                try:
                    row=json.loads(line)
                    record=normalize(p,kind,row,{'run_id':manifest['run_id'],'file_sha256':digest,'line':number})
                    key=(kind,hashlib.sha256(canonical(row).encode()).hexdigest())
                    directory=path.parent.parent.name
                    if key not in seen_rows or seen_rows[key]==directory:
                        records.append(record)
                        seen_rows[key]=directory
                except (BridgeError,ValueError):
                    rejected+=1
                if len(records)>10000: fail('output_limit')
    media=[]
    media_bytes=0
    artifacts=[]
    artifact_bytes=0
    bili_identities,bili_identity_sha=({},None)
    from native_media_scope import temporary_media_path
    if p=='bili':
        from native_media_scope import bilibili_identity_map
        bili_identities,bili_identity_sha=bilibili_identity_map(output,manifest['run_id'],records,read)
    for name in JSONL_DIRS.get(p,(p,)):
        folder=output/name/'media'
        if folder.is_symlink() or folder.parent.is_symlink(): fail('unsafe_output_file')
        for path in sorted(folder.rglob('*')):
            if temporary_media_path(path.relative_to(folder).parts):continue
            if path.is_file() and path.suffix.lower() in ('.jpg','.jpeg','.png','.webp','.gif','.mp4','.m4a','.mp3','.aac','.wav','.webm','.flv','.mov') and not path.is_symlink() and path.resolve().is_relative_to(output.resolve()):
                size=path.stat().st_size
                media_bytes+=size
                audio_only=p=='bili' and manifest['request'].get('platform_options',{}).get('long_audio') and path.name=='audio.m4a'
                native_media=p in ('dy','ks','bili') and manifest['request'].get('media') is True
                file_limit=67108864 if audio_only or native_media else 26214400
                if size>file_limit or media_bytes>104857600: fail('media_import_byte_limit')
                parts=path.relative_to(folder).parts
                content_id=opaque(parts[0]) if len(parts)>1 else None
                item={'path':str(path.relative_to(run)),'bytes':size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                      'content_id':content_id,'platform':PLATFORMS[p],'status':'downloaded_by_external_executor',
                      'source_kind':'mediacrawler_api','reward_eligible':False,'content_identity_status':'reported_directory_id' if content_id else 'missing'}
                if p=='bili' and content_id in bili_identities:
                    pair=bili_identities[content_id]
                    item.update(content_id=pair['aid'],source_media_id=content_id,
                                content_identity_basis='same_native_bilibili_view',bilibili_view_cid=pair['cid'],
                                bilibili_media_identity_sha256=bili_identity_sha)
                if audio_only:item.update({'kind':'audio','single_file_limit_bytes':67108864,'max_duration_seconds':7200})
                if p=='zhihu' and len(parts)>2 and parts[1] in ('answer','article','zvideo'):item['source_content_type']=parts[1]
                media.append(item)
                if len(media)>1000: fail('media_manifest_limit')
        words=output/name/'words'
        if words.is_symlink(): fail('unsafe_output_file')
        for path in sorted(words.glob('*')):
            if path.name.endswith(('_word_cloud.png','_word_freq.json')) and path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(output.resolve()):
                size=path.stat().st_size
                artifact_bytes+=size
                if len(artifacts)>=1000 or size>26214400 or artifact_bytes>104857600: fail('wordcloud_artifact_limit')
                artifacts.append({'kind':'wordcloud_image' if path.suffix=='.png' else 'word_frequency','path':str(path.relative_to(run)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':size,'source_kind':'derived_local','status':'generated_by_external_executor'})
    discovery = read(run/'discovery.json') if (run/'discovery.json').is_file() else None
    from discovery import SUPPORT as discovery_support
    discovery_version = manifest.get('discovery_contract_version')
    discovery_kind = manifest['request'].get('mode') if type(discovery_version) is int and discovery_version == 1 else None
    if discovery:
        discovery_kind = discovery.get('discovery_kind')
        if discovery_kind not in discovery_support or discovery_kind != manifest['request'].get('mode') or p not in discovery_support[discovery_kind]:
            fail('invalid_discovery_provenance')
    if discovery_kind is not None:
        if discovery_kind not in DISCOVERY_KINDS or discovery_kind in discovery_support and p not in discovery_support[discovery_kind]:
            fail('invalid_discovery_provenance')
        for record in records:
            # Metadata is outside the established normalized record_hash; the capture hash covers it.
            record['discovery_kind'] = discovery_kind
    data={'schema':'crowd_mc_import_v1','run_id':manifest['run_id'],'source_kind':'mediacrawler_api','reward_eligible':False,'source':manifest['source'],'records':records,'media':media,'artifacts':artifacts,'discovery':discovery,'wordcloud_status':s.get('wordcloud_status','not_requested' if not manifest['request'].get('wordcloud') else 'unverified'),'files':files,'rejected_records':rejected,'coverage':'unverified','run_state':s['state']}
    write(run/'normalized.json',data)
    return {**data,'normalized_path':str(run/'normalized.json'),'summary':{'records':len(records),'contents':sum(r['kind']=='content' for r in records),'comments':sum(r['kind']=='comment' for r in records),'dynamics':sum(r['kind']=='dynamic' for r in records),'media_files':len(media),'rejected_records':rejected,'coverage':'unverified'}}

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--mc-root',required=True)
    parser.add_argument('action',choices=['capabilities','start','status','stop','import','list','_worker','_execute'])
    parser.add_argument('--run-id')
    parser.add_argument('--lock-fd',type=int)
    args=parser.parse_args()
    if args.action=='_worker': return worker(args.root,args.mc_root,args.run_id,args.lock_fd)
    if args.action=='_execute': return execute(args.root,args.mc_root,args.run_id)
    try:
        raw=sys.stdin.read(65537)
        if len(raw)>65536: fail('request_too_large')
        payload=json.loads(raw) if raw.strip() else {}
        if not isinstance(payload,dict): fail('invalid_request')
        if args.action=='capabilities': result=capabilities(args.mc_root)
        elif args.action=='start': result=start(args.root,args.mc_root,payload)
        elif args.action=='status': result=status(args.root,payload)
        elif args.action=='stop': result=stop(args.root,payload)
        elif args.action=='import': result=import_output(args.root,payload)
        else:
            folders=sorted((Path(args.root)/'runs').glob('*'),key=lambda x:x.stat().st_mtime,reverse=True)[:100]
            result={'runs':[status(args.root,{'run_id':p.name}) for p in folders if (p/'status.json').is_file()]}
        print(canonical({'ok':True,'result':result}))
    except (BridgeError,ValueError,OSError) as exc:
        print(canonical({'ok':False,'error':str(exc) if isinstance(exc,BridgeError) else 'bridge_io_or_json_error'}))
        return 1
    return 0

if __name__=='__main__':
    sys.exit(main() or 0)
