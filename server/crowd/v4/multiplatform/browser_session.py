"""Explicit existing-browser binding; no profile export or user-browser cleanup."""
import asyncio
import contextlib
import hashlib
import importlib
import json
import re
import os
import signal
import time
import urllib.request
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
    except Exception:
        raise BrowserSessionError('browser_unreachable') from None


def inspect_browser(port,platform):
    if platform not in HOSTS:
        raise BrowserSessionError('invalid_browser_platform')
    version=metadata(port,'/json/version')
    try:
        socket=urlsplit(version['webSocketDebuggerUrl'])
        if socket.scheme!='ws' or socket.hostname not in ('127.0.0.1','localhost') or socket.port!=port or socket.username or socket.password or socket.query or socket.fragment or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]{16,100}',socket.path):
            raise ValueError
    except (KeyError,TypeError,ValueError):
        raise BrowserSessionError('invalid_browser_identity') from None
    fingerprint=hashlib.sha256(socket.path.encode()).hexdigest()
    rows=metadata(port,'/json/list')
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
    current=await asyncio.to_thread(inspect_browser,binding['port'],platform)
    if current['browser_fingerprint']!=binding['browser_fingerprint']:
        raise BrowserSessionError('browser_identity_changed')
    if binding['target_id'] not in {row['target_id'] for row in current['_all_targets']}:
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
