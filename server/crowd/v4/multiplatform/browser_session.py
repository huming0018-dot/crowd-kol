"""Explicit existing-browser binding; no profile export or user-browser cleanup."""
import asyncio
import contextlib
import hashlib
import importlib
import json
import re
import os
import stat
import signal
import time
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

HOSTS={'xhs':{'www.xiaohongshu.com'},'dy':{'www.douyin.com','douyin.com'},
       'bili':{'www.bilibili.com','bilibili.com'},'wb':{'weibo.com','www.weibo.com','m.weibo.cn'},
       'ks':{'www.kuaishou.com','kuaishou.com'},'tieba':{'tieba.baidu.com'},
       'zhihu':{'www.zhihu.com','zhihu.com','zhuanlan.zhihu.com'}}
COOKIE_DOMAINS={'xhs':{'xiaohongshu.com'},'dy':{'douyin.com'},'bili':{'bilibili.com'},
                'wb':{'weibo.com','weibo.cn'},'ks':{'kuaishou.com'},'tieba':{'baidu.com'},'zhihu':{'zhihu.com'}}


class BrowserSessionError(ValueError):
    pass


def existing_browser_session(root, session_id):
    """Metadata only; never inspect browser credential files."""
    from account_sessions import AccountSessions
    return AccountSessions(root).status(session_id).get('browser_connection',{}).get('mode')=='existing_cdp'


def terminate_executor(pid, borrowed):
    # Keep Playwright's child driver alive until owned-page cleanup has run.
    if borrowed:os.kill(pid,signal.SIGTERM)
    else:os.killpg(pid,signal.SIGTERM)


class ExecutorCancellation:
    """SIGTERM cancels the executor task; supervisor retains the hard deadline."""
    def __init__(self):
        self.requested=False
        self.loop=None
        self.task=None
        self.previous=None

    def request(self,*unused):
        if self.requested:return
        self.requested=True
        if self.loop is not None and self.task is not None:
            self.loop.call_soon_threadsafe(self.task.cancel)

    def install(self):
        self.previous=signal.signal(signal.SIGTERM,self.request)

    def restore(self):
        if self.previous is not None:signal.signal(signal.SIGTERM,self.previous)

    async def run(self, coroutine):
        self.loop=asyncio.get_running_loop()
        self.task=asyncio.create_task(coroutine)
        if self.requested:self.task.cancel()
        try:return await self.task
        finally:self.task=None;self.loop=None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise BrowserSessionError('browser_endpoint_redirect_rejected')


def validate_port(port):
    if type(port) is not int or not 1024<=port<=65535:
        raise BrowserSessionError('invalid_browser_port')
    return port


def target_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Fa-f0-9]{32}',value):
        raise BrowserSessionError('invalid_browser_target')
    return value


def platform_page(platform,value):
    try:
        parsed=urlsplit(value)
        return parsed.scheme=='https' and not parsed.username and not parsed.password and parsed.port in (None,443) and parsed.hostname in HOSTS[platform]
    except (TypeError,ValueError,KeyError):
        return False


def ordinary_page(value):
    try:
        parsed=urlsplit(value)
        return parsed.scheme=='https' and bool(parsed.hostname) and not parsed.username and not parsed.password and parsed.port in (None,443)
    except (TypeError,ValueError):return False


def metadata(port,path):
    validate_port(port)
    if path not in ('/json/version','/json/list'):
        raise BrowserSessionError('invalid_browser_metadata_route')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open('http://127.0.0.1:'+str(port)+path,timeout=3) as response:
            body=response.read(262145)
        if len(body)>262144:
            raise BrowserSessionError('browser_metadata_too_large')
        return json.loads(body)
    except BrowserSessionError:
        raise
    except urllib.error.HTTPError as error:
        raise BrowserSessionError('browser_metadata_endpoint_unavailable' if error.code==404 else 'browser_unreachable') from None
    except Exception:
        raise BrowserSessionError('browser_unreachable') from None


def active_socket_path(port):
    """Read only Chrome's public endpoint metadata, never its profile state."""
    validate_port(port)
    base=Path.home()/'Library/Application Support'
    paths=[base/'Google/Chrome/DevToolsActivePort',base/'Google/Chrome Canary/DevToolsActivePort',base/'Chromium/DevToolsActivePort']
    found=set()
    for path in paths:
        try:
            if any(parent.is_symlink() for parent in [path,*path.parents]):continue
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        except (FileNotFoundError,OSError):continue
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or not 1<=info.st_size<=512:continue
            raw=os.read(fd,513)
            after=os.fstat(fd)
            if (info.st_size,info.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):continue
            try:lines=raw.decode('ascii').splitlines()
            except UnicodeError:continue
            if len(lines)!=2 or lines[0]!=str(port) or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]{16,100}',lines[1]):continue
            found.add(lines[1])
        finally:os.close(fd)
    if len(found)>1:raise BrowserSessionError('browser_endpoint_ambiguous')
    if not found:raise BrowserSessionError('browser_metadata_endpoint_unavailable')
    return found.pop()


def socket_metadata(port,path,deadline_seconds=10,on_ready=None,hold=None):
    """Bounded metadata-only CDP; Chrome retains its native consent prompt."""
    validate_port(port)
    if not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]{16,100}',path):raise BrowserSessionError('invalid_browser_identity')
    try:from websockets.sync.client import connect
    except ImportError:raise BrowserSessionError('browser_transport_dependency_missing') from None
    deadline=time.monotonic()+deadline_seconds
    try:
        with connect('ws://127.0.0.1:'+str(port)+path,proxy=None,open_timeout=deadline_seconds,close_timeout=1,max_size=262144,max_queue=4) as channel:
            responses=[];count=0;size=0
            for identity,method in enumerate(('Browser.getVersion','Target.getTargets'),1):
                channel.send(json.dumps({'id':identity,'method':method}))
                while True:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError
                    raw=channel.recv(timeout=remaining);count+=1;size+=len(raw.encode('utf8') if isinstance(raw,str) else raw)
                    if count>64 or size>262144:raise BrowserSessionError('browser_metadata_too_large')
                    value=json.loads(raw)
                    if not isinstance(value,dict):raise BrowserSessionError('invalid_browser_metadata')
                    if type(value.get('id')) is int and value['id']==identity:
                        if 'error' in value or not isinstance(value.get('result'),dict):raise BrowserSessionError('invalid_browser_metadata')
                        responses.append(value['result']);break
            if not isinstance(responses[0].get('product'),str) or not re.fullmatch(r'(?:Chrome|Chromium)/[0-9.]+',responses[0]['product']):raise BrowserSessionError('invalid_browser_identity')
            rows=responses[1].get('targetInfos')
            if not isinstance(rows,list) or len(rows)>200:raise BrowserSessionError('invalid_browser_target_list')
            rows=[{**row,'id':row.get('targetId')} if isinstance(row,dict) else row for row in rows]
            if on_ready is not None:on_ready(rows)
            if hold is not None:
                refresh=getattr(hold,'refresh',None);identity=3
                while time.monotonic()<deadline and not hold.is_set():
                    if refresh is None:hold.wait(max(0,deadline-time.monotonic()));break
                    if not refresh.wait(min(.25,max(0,deadline-time.monotonic()))):continue
                    refresh.clear()
                    channel.send(json.dumps({'id':identity,'method':'Target.getTargets'}))
                    while True:
                        remaining=deadline-time.monotonic()
                        if remaining<=0:raise TimeoutError
                        raw=channel.recv(timeout=remaining);count+=1;size+=len(raw.encode('utf8') if isinstance(raw,str) else raw)
                        if count>64 or size>262144:raise BrowserSessionError('browser_metadata_too_large')
                        value=json.loads(raw)
                        if not isinstance(value,dict):raise BrowserSessionError('invalid_browser_metadata')
                        if type(value.get('id')) is int and value['id']==identity:
                            if 'error' in value or not isinstance(value.get('result'),dict):raise BrowserSessionError('invalid_browser_metadata')
                            targets=value['result'].get('targetInfos')
                            if not isinstance(targets,list) or len(targets)>200:raise BrowserSessionError('invalid_browser_target_list')
                            rows=[{**row,'id':row.get('targetId')} if isinstance(row,dict) else row for row in targets]
                            if on_ready is not None:on_ready(rows)
                            identity+=1;break
            return rows
    except BrowserSessionError:raise
    except TimeoutError:raise BrowserSessionError('browser_connection_pending') from None
    except Exception:raise BrowserSessionError('browser_connection_failed') from None


_metadata_waiters={}
_metadata_waiters_lock=threading.Lock()
METADATA_WAIT_SECONDS=120


def retained_socket_metadata(port,path,restart_connection=False,refresh_targets=False):
    """One bounded native-consent connection; polling never opens another socket."""
    validate_port(port)
    if type(restart_connection) is not bool:raise BrowserSessionError('invalid_browser_restart')
    if type(refresh_targets) is not bool or restart_connection and refresh_targets:raise BrowserSessionError('invalid_browser_refresh')
    if not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]{16,100}',path):raise BrowserSessionError('invalid_browser_identity')
    key=(port,path)
    with _metadata_waiters_lock:
        state=_metadata_waiters.get(key)
        if refresh_targets and state is None:raise BrowserSessionError('browser_connection_pending')
        if restart_connection:
            if state is None or time.monotonic()<state['deadline']:raise BrowserSessionError('browser_connection_active')
            state['hold'].set();state=None
        if state is None:
            if key not in _metadata_waiters and len(_metadata_waiters)>=4:raise BrowserSessionError('browser_connection_busy')
            state={'state':'pending','deadline':time.monotonic()+METADATA_WAIT_SECONDS,'rows':None,'hold':threading.Event(),'refresh_count':0}
            state['hold'].refresh=threading.Event()
            _metadata_waiters[key]=state
            def ready(rows):
                with _metadata_waiters_lock:state.update(state='ready',rows=rows)
            def run():
                try:socket_metadata(port,path,METADATA_WAIT_SECONDS,ready,state['hold'])
                except BrowserSessionError as error:
                    with _metadata_waiters_lock:state.update(state='failed',error=str(error))
                finally:
                    with _metadata_waiters_lock:
                        if state['state'] in ('pending','ready'):state.update(state='expired',rows=None)
            threading.Thread(target=run,name='crowd-browser-metadata',daemon=True).start()
        if time.monotonic()>=state['deadline']:raise BrowserSessionError('browser_connection_expired')
        if refresh_targets:
            if state['state']=='failed':raise BrowserSessionError(state['error'])
            if state['state']!='ready':raise BrowserSessionError('browser_connection_pending')
            if state['refresh_count']>=8:raise BrowserSessionError('browser_refresh_limit')
            state.update(state='pending',rows=None,refresh_count=state['refresh_count']+1)
            state['hold'].refresh.set()
        if state['state']=='ready':return state['rows']
        if state['state']=='failed':raise BrowserSessionError(state['error'])
        if state['state']=='expired':raise BrowserSessionError('browser_connection_expired')
        raise BrowserSessionError('browser_connection_pending')


def inspect_browser(port,platform,retain_connection=False,restart_connection=False,refresh_targets=False):
    if platform not in HOSTS:
        raise BrowserSessionError('invalid_browser_platform')
    try:version=metadata(port,'/json/version')
    except BrowserSessionError as error:
        if str(error)!='browser_metadata_endpoint_unavailable':raise
        path=active_socket_path(port)
        rows=retained_socket_metadata(port,path,restart_connection,refresh_targets) if retain_connection else socket_metadata(port,path)
        version={'webSocketDebuggerUrl':'ws://127.0.0.1:'+str(port)+path}
    else:rows=metadata(port,'/json/list')
    try:
        socket=urlsplit(version['webSocketDebuggerUrl'])
        if socket.scheme!='ws' or socket.hostname not in ('127.0.0.1','localhost') or socket.port!=port or socket.username or socket.password or socket.query or socket.fragment or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]{16,100}',socket.path):
            raise ValueError
    except (KeyError,TypeError,ValueError):
        raise BrowserSessionError('invalid_browser_identity') from None
    fingerprint=hashlib.sha256(socket.path.encode()).hexdigest()
    if not isinstance(rows,list) or len(rows)>200:
        raise BrowserSessionError('invalid_browser_target_list')
    choices=[];anchors=[]
    for row in rows:
        if isinstance(row,dict) and row.get('type')=='page' and ordinary_page(row.get('url')):
            try:identity=target_id(row.get('id'))
            except BrowserSessionError:continue
            item={'target_id':identity,'platform':platform,'selection_kind':'platform_page' if platform_page(platform,row.get('url')) else 'context_anchor'}
            anchors.append(item)
            if item['selection_kind']=='platform_page':choices.append(item)
    if len({row['target_id'] for row in anchors})!=len(anchors):
        raise BrowserSessionError('browser_target_ambiguous')
    selected=choices or anchors
    return {'port':port,'browser_fingerprint':fingerprint,'targets':[{**item,'page_number':index+1} for index,item in enumerate(selected)],'_socket_path':socket.path,'_all_targets':anchors}


def validate_binding(value,platform):
    if not isinstance(value,dict) or set(value)!={'mode','port','target_id','browser_fingerprint','selection_kind'} or value['mode']!='existing_cdp' or value['selection_kind'] not in ('platform_page','context_anchor'):
        raise BrowserSessionError('invalid_browser_binding')
    validate_port(value['port']);target_id(value['target_id'])
    if not isinstance(value['browser_fingerprint'],str) or not re.fullmatch(r'[a-f0-9]{64}',value['browser_fingerprint']):
        raise BrowserSessionError('invalid_browser_identity')
    if platform not in HOSTS:raise BrowserSessionError('invalid_browser_platform')
    return value


class BorrowedContext:
    """MC gets its own pages, while native cookie reads stay in the selected context."""
    def __init__(self,context,platform):
        self._context=context;self.platform=platform;self.owned_pages=[];self.scripts=[]
    @property
    def pages(self):return list(self.owned_pages)
    async def add_init_script(self,*args,**kwargs):
        self.scripts.append((args,kwargs))
        for page in self.owned_pages:await page.add_init_script(*args,**kwargs)
    async def new_page(self):
        page=await self._context.new_page();self.owned_pages.append(page)
        for args,kwargs in self.scripts:await page.add_init_script(*args,**kwargs)
        return page
    async def close(self):
        for page in self.owned_pages:
            with contextlib.suppress(Exception):await page.close()
        self.owned_pages=[]
    @contextlib.asynccontextmanager
    async def expect_page(self,*args,**kwargs):
        context=self
        async with self._context.expect_page(*args,**kwargs) as pending:
            class OwnedEvent:
                @property
                def value(self):
                    async def resolve():
                        page=await pending.value
                        if await page.opener() not in context.owned_pages:
                            raise BrowserSessionError('browser_popup_not_owned')
                        if page not in context.owned_pages:context.owned_pages.append(page)
                        return page
                    return resolve()
            yield OwnedEvent()
    async def cookies(self,urls=None):
        values=['https://'+host+'/' for host in sorted(HOSTS[self.platform])] if urls is None else ([urls] if isinstance(urls,str) else urls)
        if not isinstance(values,(list,tuple)) or len(values)>50:raise BrowserSessionError('invalid_cookie_scope')
        allowed=[]
        for value in values:
            if not ordinary_page(value):raise BrowserSessionError('invalid_cookie_scope')
            host=urlsplit(value).hostname
            if not any(host==domain or host.endswith('.'+domain) for domain in COOKIE_DOMAINS[self.platform]):raise BrowserSessionError('invalid_cookie_scope')
            allowed.append(value)
        if not allowed:return []
        result=await self._context.cookies(urls=allowed)
        return [row for row in result if isinstance(row,dict) and isinstance(row.get('domain'),str) and
                any(row['domain'].lstrip('.').lower()==domain or row['domain'].lstrip('.').lower().endswith('.'+domain) for domain in COOKIE_DOMAINS[self.platform])]


async def connect_context(chromium,binding,platform):
    validate_binding(binding,platform)
    # Modern Chrome exposes its direct socket while the HTTP metadata routes return 404.
    try:
        await asyncio.to_thread(metadata,binding['port'],'/json/version')
    except BrowserSessionError as error:
        if str(error)!='browser_metadata_endpoint_unavailable':raise
        path=await asyncio.to_thread(active_socket_path,binding['port'])
        current={'browser_fingerprint':hashlib.sha256(path.encode()).hexdigest(),'_socket_path':path}
    else:current=await asyncio.to_thread(inspect_browser,binding['port'],platform)
    if current['browser_fingerprint']!=binding['browser_fingerprint']:
        raise BrowserSessionError('browser_identity_changed')
    if '_all_targets' in current and binding['target_id'] not in {row['target_id'] for row in current['_all_targets']}:
        raise BrowserSessionError('browser_selected_page_unavailable')
    try:
        browser=await chromium.connect_over_cdp('ws://127.0.0.1:'+str(binding['port'])+current['_socket_path'],timeout=5000)
        if sum(len(context.pages) for context in browser.contexts)>200:raise BrowserSessionError('browser_target_limit')
        deadline=time.monotonic()+5
        matched=[]
        for context in browser.contexts:
            for page in context.pages:
                if not (platform_page(platform,page.url) if binding['selection_kind']=='platform_page' else ordinary_page(page.url)):continue
                protocol=None
                try:
                    protocol=await asyncio.wait_for(context.new_cdp_session(page),timeout=max(.001,deadline-time.monotonic()))
                    info=await asyncio.wait_for(protocol.send('Target.getTargetInfo'),timeout=max(.001,deadline-time.monotonic()))
                    if info.get('targetInfo',{}).get('targetId')==binding['target_id']:matched.append(context)
                finally:
                    if protocol:
                        with contextlib.suppress(Exception):await asyncio.wait_for(protocol.detach(),timeout=.5)
        if len(matched)!=1:raise BrowserSessionError('browser_selected_page_unavailable')
        return BorrowedContext(matched[0],platform)
    except BrowserSessionError:raise
    except Exception:raise BrowserSessionError('browser_connection_failed') from None


class BorrowedDriver:
    def __init__(self,manager,contexts):self.manager=manager;self.contexts=contexts
    async def __aenter__(self):return await self.manager.__aenter__()
    async def __aexit__(self,*args):
        try:
            for context in self.contexts:
                with contextlib.suppress(Exception):await asyncio.wait_for(context.close(),timeout=2)
        finally:result=await self.manager.__aexit__(*args)
        return result


def install_browser_reuse(store,session_id,platform,browser_type,crawler_class=None):
    """No binding means the existing persistent-profile path remains untouched."""
    binding=store.status(session_id,platform).get('browser_connection')
    if not binding:return False
    validate_binding(binding,platform)
    contexts=[]
    async def persistent(chromium,*args,**kwargs):
        try:
            if chromium.name!='chromium':raise BrowserSessionError('browser_type_not_supported')
            context=await connect_context(chromium,binding,platform)
            contexts.append(context)
            return context
        except BrowserSessionError as error:
            store.observe(session_id,platform,'check_failed')
            store._update(session_id,platform,lambda value:value.update(browser_connection_error=str(error),login_verified=False))
            raise
    browser_type.launch_persistent_context=persistent
    if crawler_class:
        module=importlib.import_module(crawler_class.__module__)
        manager=module.async_playwright
        module.async_playwright=lambda *args,**kwargs:BorrowedDriver(manager(*args,**kwargs),contexts)
    return True
