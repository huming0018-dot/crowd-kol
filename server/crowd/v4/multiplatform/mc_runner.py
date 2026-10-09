#!/usr/bin/env python3
"""Local, separately installed MediaCrawler bridge. No bundled upstream code."""
import argparse
import contextlib
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
MEDIA = {'xhs','dy','ks','bili','wb'}
FINAL = {'completed','failed','stopped','interrupted_unknown','login_required'}
ID_KEYS = {'xhs':'note_id','dy':'aweme_id','ks':'video_id','bili':'video_id','wb':'note_id','tieba':'note_id','zhihu':'content_id'}
SECRET = re.compile(r'(?i)(?:cookie|authorization|access_token|refresh_token|xsec_token|token|password|passwd|secret|sessionid|api_key|x-amz-signature|x-amz-credential)\s*[=:]')

class BridgeError(Exception):
    pass

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

def validate(payload):
    allowed = {'platform','mode','targets','max_items','comments','replies','media','purpose','authorization_ref','session_id','max_api_requests','timeout_seconds','max_comments','headless'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        fail('invalid_request')
    p = dict(payload)
    if not isinstance(p.get('platform'),str) or p.get('platform') not in PLATFORMS or p.get('mode') not in ('search','detail','creator'):
        fail('unsupported_platform_or_mode')
    if p.get('purpose') not in ('noncommercial_research','licensed_use'):
        fail('license_basis_required')
    if p['purpose'] == 'licensed_use' and not isinstance(p.get('authorization_ref'), str):
        fail('authorization_ref_required')
    if 'authorization_ref' in p and (not isinstance(p['authorization_ref'],str) or not p['authorization_ref'] or len(p['authorization_ref']) > 200 or contains_secret(p['authorization_ref'])):
        fail('invalid_authorization_ref')
    targets = p.get('targets')
    if not isinstance(targets,list) or not 1 <= len(targets) <= 10 or any(not isinstance(t,str) or not t.strip() or len(t)>1000 or '\x00' in t or ',' in t for t in targets):
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
        elif not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',target):
            fail('invalid_target_id')
    for field, default, low, high in [('max_items',20,1,100),('max_comments',20,0,200),('max_api_requests',20,1,500),('timeout_seconds',600,30,1800)]:
        v = p.setdefault(field,default)
        if type(v) is not int or not low <= v <= high:
            fail('invalid_' + field)
    if p['mode'] == 'search' and p['max_items'] < 20:
        fail('upstream_search_minimum_20')
    for field, default in [('comments',True),('replies',False),('media',False),('headless',False)]:
        if type(p.setdefault(field, default)) is not bool:
            fail('invalid_' + field)
    if p['replies'] and not p['comments']:
        fail('replies_require_comments')
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
    return {'source':info,'platforms':[{'id':p,'name':name,'label':name,'notes':('creator currently answers only; no source completeness guarantee' if p=='zhihu' else 'source completeness unverified; max_items is upstream configuration'),'modes':['search','detail','creator'],'comments':True,'replies':True,'media':p in MEDIA,'live_verified':False,'limitations':(['creator currently answers only'] if p=='zhihu' else [])} for p,name in PLATFORMS.items()], 'source_kind':'mediacrawler_api','reward_eligible':False,'max_items_semantics':'upstream_configuration_not_hard_source_limit','api_request_limit_scope':'Python httpx/requests attempts, not browser resource requests','coverage':'unverified','media_limits':{'single_file_bytes':26214400,'python_response_bytes':104857600,'output_watchdog_bytes':104857600},'creator_profile_import':False,'login':'visible isolated browser; user completes login/captcha; no automatic credential import'}

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
    manifest = {'run_id':run_id,'request':p,'source':info,'created_at':time.time(),'source_kind':'mediacrawler_api','reward_eligible':False}
    write(run/'manifest.json',manifest)
    write(run/'status.json',{'run_id':run_id,'state':'starting','phase':'starting','session_id':p['session_id'],'platform':p['platform'],'mode':p['mode'],'source_kind':'mediacrawler_api','reward_eligible':False,'updated_at':time.time()})
    proc = subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--root',str(root),'--mc-root',str(mc),'_worker','--run-id',run_id,'--lock-fd',str(lock.fileno())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,pass_fds=(lock.fileno(),))
    lock.close()
    return {'run_id':run_id,'state':'starting','session_id':p['session_id'],'supervisor_pid':proc.pid,'source_kind':'mediacrawler_api','reward_eligible':False}

def argv_for(p, output):
    args = ['--platform',p['platform'],'--type',p['mode'],'--lt','qrcode','--headless',str(p['headless']).lower(),'--save_data_option','jsonl','--save_data_path',str(output),'--crawler_max_notes_count',str(p['max_items']),'--max_concurrency_num','1','--max_comments_count_singlenotes',str(p['max_comments']),'--get_comment',str(p['comments']).lower(),'--get_sub_comment',str(p['replies']).lower(),'--get_media',str(p['media']).lower(),'--enable_ip_proxy','false']
    args += [{'search':'--keywords','detail':'--specified_id','creator':'--creator_id'}[p['mode']],','.join(p['targets'])]
    return args

def status(root, payload):
    run = run_dir(root,payload.get('run_id'))
    state = read(run/'status.json')
    # No inference of success from the supervisor or browser disappearing.
    if state['state'] not in FINAL and time.time()-state['updated_at'] > 8:
        state = {**state,'state':'interrupted_unknown','reason':'supervisor_heartbeat_missing'}
    return state

def stop(root,payload):
    run = run_dir(root,payload.get('run_id'))
    s = status(root,payload)
    if s['state'] in ('completed','failed','stopped','login_required'):
        return s
    write(run/'stop.json',{'requested_at':time.time()})
    return {**s,'stop_requested':True}

def worker(root, mc, run_id, lock_fd):
    run = run_dir(root,run_id)
    manifest = read(run/'manifest.json')
    p = manifest['request']
    state = read(run/'status.json')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1', MPLCONFIGDIR=str(run/'cache/matplotlib'), XDG_CACHE_HOME=str(run/'cache'),CROWD_MC_SUPERVISOR_PID=str(os.getpid()))
    child = subprocess.Popen([str(Path(mc)/'.venv/bin/python'),str(Path(__file__).resolve()),'--root',str(root),'--mc-root',str(mc),'_execute','--run-id',run_id],cwd=run,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,pass_fds=(lock_fd,))
    started = time.monotonic()
    reason = None
    while child.poll() is None:
        output_bytes=sum(f.stat().st_size for f in (run/'output').rglob('*') if f.is_file() and not f.is_symlink())
        if (run/'stop.json').exists() or time.monotonic()-started > p['timeout_seconds'] or output_bytes>104857600:
            reason = 'user_stop' if (run/'stop.json').exists() else 'output_byte_limit' if output_bytes>104857600 else 'wall_timeout'
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL)
                child.wait()
            break
        progress = read(run/'phase.json') if (run/'phase.json').exists() else {'phase':'running','api_attempts':0}
        active_state=progress['phase'] if progress['phase'] in ('running','waiting_login','login_required','collecting','comments','media') else 'running'
        state.update(progress, state=active_state, updated_at=time.time())
        write(run/'status.json',state)
        time.sleep(0.5)
    code = child.wait()
    if (run/'stop.json').exists(): reason='user_stop'
    elif time.monotonic()-started>p['timeout_seconds'] and reason is None: reason='wall_timeout'
    final = 'stopped' if reason=='user_stop' else 'login_required' if code==77 else 'completed' if code==0 and not reason else 'failed'
    progress = read(run/'phase.json') if (run/'phase.json').exists() else {}
    state.update(progress)
    state.update(state=final,phase=final,reason=reason or {0:'executor_finished',72:'dependency_missing',73:'api_request_limit',74:'executor_error',76:'response_byte_limit',77:'login_required'}.get(code,'executor_error'),exit_code=code,updated_at=time.time(),coverage='unverified')
    write(run/'status.json',state)
    os.close(lock_fd)

def execute(root, mc, run_id):
    run = run_dir(root,run_id)
    p = read(run/'manifest.json')['request']
    os.chdir(run)
    sys.path.insert(0,str(Path(mc).resolve()))
    sys.dont_write_bytecode=True
    attempts=0
    response_bytes=0
    resource.setrlimit(resource.RLIMIT_FSIZE,(26214400,26214400))
    phase='running'
    def event(new=None):
        nonlocal phase
        phase = new or phase
        write(run/'phase.json',{'phase':phase,'api_attempts':attempts})
    # Raw upstream logs can contain credential URLs. Only constant phase labels leave here.
    class Sink:
        def write(self, text):
            low=text.lower()
            if any(t in low for t in ('qrcode','scan qr','scan the qr','login required','login by')):
                event('login_required' if p['headless'] else 'waiting_login')
                if p['headless']: raise SystemExit(77)
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
                if os.getpgrp()==os.getpid():
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
            config.CRAWLER_MAX_SLEEP_SEC=30
            config.ENABLE_GET_WORDCLOUD=False
            config.CREATOR_MODE=True
            config.ENABLE_GET_CONTACTS=False
            config.ENABLE_GET_DYNAMICS=False
            if p['platform']=='zhihu' and p['mode']=='creator':
                config.ZHIHU_CREATOR_URL_LIST=p['targets']
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
                return await old_async(self,*a,**kw)
            def sync_send(self,*a,**kw):
                debit()
                return old_sync(self,*a,**kw)
            def requests_send(self,*a,**kw):
                debit()
                return old_requests(self,*a,**kw)
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
                            if response_size>26214400 or response_bytes>104857600:
                                event('response_byte_limit')
                                raise SystemExit(76)
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
            import asyncio
            sys.argv=[str(Path(mc)/'main.py'),*argv_for(p,run/'output')]
            async def crawl():
                try:
                    await asyncio.wait_for(upstream.main(), timeout=p['timeout_seconds'])
                finally:
                    await asyncio.wait_for(upstream.async_cleanup(), timeout=10)
            asyncio.run(crawl())
    except (ModuleNotFoundError,ImportError):
        raise SystemExit(72)
    except SystemExit:
        raise
    except BaseException as exc:
        write(run/'phase.json',{'phase':'failed','api_attempts':attempts,'failure_type':type(exc).__name__[:80]})
        raise SystemExit(74)
    finally:
        finished.set()

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
    cid=opaque(row.get(ID_KEYS[platform]))
    if not cid: fail('missing_content_id')
    result={'platform':PLATFORMS[platform],'content_id':cid,'kind':kind,'source_kind':'mediacrawler_api','reward_eligible':False,'coverage':'unverified','origin':origin}
    if kind=='comment':
        result.update(comment_id=opaque(row.get('comment_id')),parent_comment_id=opaque(row.get('parent_comment_id')),text=safe_text(row.get('content')),reported_reply_count=reported_count(row.get('sub_comment_count')))
        if not result['comment_id']: fail('missing_comment_id')
    else:
        result.update(title=safe_text(row.get('title'),2000),body=safe_text(next((row[k] for k in ('desc','content_text','content','text') if row.get(k) is not None),None)),content_type=safe_text(row.get('content_type') or row.get('type'),80))
    metrics={}
    for key in ('liked_count','like_count','comment_count','share_count','share_count','collected_count','view_count','play_count','video_play_count','video_review_count','voteup_count','forward_count','video_favorite_count','video_share_count','video_coin_count','video_danmaku','video_comment','comment_like_count','total_replay_num'):
        value=row.get(key)
        if type(value) is int and value>=0 or isinstance(value,str) and re.fullmatch(r'[0-9.,万千亿wWkKmM+ ]{1,40}',value):
            metrics[key]={'reported_value':value,'semantics':'upstream_reported_not_independently_verified'}
    result['metrics']=metrics
    result['upstream_transport']='platform_dependent_api_or_browser_html'
    if kind=='comment':
        result['parent_status']='reported' if result['parent_comment_id'] is not None else 'missing_upstream'
        result['reply_count_semantics']='upstream_reported_not_independently_verified'
    result['published_at_reported']=next((row[k] for k in ('time','create_time','created_time','publish_time') if type(row.get(k)) is int or isinstance(row.get(k),str) and len(row[k])<=80 and not contains_secret(row[k])),None)
    result['entity_key']=result['platform']+':'+cid+(':'+result['comment_id'] if kind=='comment' else '')
    text_value = row.get('content') if kind=='comment' else next((row[k] for k in ('desc','content_text','content','text') if row.get(k) is not None),None)
    result['text_status']='withheld_sensitive' if isinstance(text_value,str) and contains_secret(text_value) else 'reported' if isinstance(text_value,str) else 'missing'
    result['text_truncated']=isinstance(text_value,str) and len(text_value)>24000
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
    for path in sorted((output/p/'jsonl').glob('*.jsonl')):
        if path.is_symlink() or not path.resolve().is_relative_to(output.resolve()) or path.stat().st_size>50_000_000: fail('unsafe_output_file')
        kind='comment' if '_comments_' in path.name else 'content' if '_contents_' in path.name else None
        if not kind: continue
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({'path':str(path.relative_to(run)),'sha256':digest})
        with open(path,encoding='utf8') as f:
            for number,line in enumerate(f,1):
                if number>10000 or len(line)>1_000_000: fail('output_limit')
                try:
                    records.append(normalize(p,kind,json.loads(line),{'run_id':manifest['run_id'],'file_sha256':digest,'line':number}))
                except (BridgeError,ValueError):
                    rejected+=1
                if len(records)>10000: fail('output_limit')
    media=[]
    for path in sorted((output/p/'media').rglob('*')):
        if path.is_file() and path.suffix.lower() in ('.jpg','.jpeg','.png','.webp','.gif','.mp4','.m4a','.mp3','.wav','.webm','.flv','.mov') and not path.is_symlink() and path.resolve().is_relative_to(output.resolve()):
            media.append({'path':str(path.relative_to(run)),'bytes':path.stat().st_size,'status':'downloaded_by_external_executor','source_kind':'mediacrawler_api'})
            if len(media)>1000: fail('media_manifest_limit')
    data={'schema':'crowd_mc_import_v1','run_id':manifest['run_id'],'source_kind':'mediacrawler_api','reward_eligible':False,'source':manifest['source'],'records':records,'media':media,'files':files,'rejected_records':rejected,'coverage':'unverified','run_state':s['state']}
    write(run/'normalized.json',data)
    return {**data,'normalized_path':str(run/'normalized.json'),'summary':{'records':len(records),'contents':sum(r['kind']=='content' for r in records),'comments':sum(r['kind']=='comment' for r in records),'media_files':len(media),'rejected_records':rejected,'coverage':'unverified'}}

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
