import asyncio
import contextlib
import fcntl
import json
import sys
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
import urllib.error
import urllib.request

from account_sessions import AccountSessions
from browser_session import (BrowserSessionError, BorrowedContext, connect_context,
                             inspect_browser, install_browser_reuse, validate_binding, BorrowedDriver,
                             existing_browser_session, terminate_executor, ExecutorCancellation)
from dashboard import Application

TARGET='a'*32
SOCKET='/devtools/browser/00000000-0000-4000-8000-000000000001'


def metadata(port,path):
    if path=='/json/version':return {'webSocketDebuggerUrl':'ws://127.0.0.1:'+str(port)+SOCKET}
    return [{'id':TARGET,'type':'page','url':'https://www.bilibili.com/video/BV1Vs411j7cX?secret=PRIVATE','title':'PRIVATE'},
            {'id':'b'*32,'type':'page','url':'https://evil.invalid/private','title':'PRIVATE'}]


class BrowserTests(unittest.TestCase):
    def test_isolated_executor_sigterm_cleans_before_driver_disconnect(self):
        import os,signal,subprocess
        code='''import asyncio
from browser_session import ExecutorCancellation,BorrowedContext,BorrowedDriver
class Page:
 async def close(self):
  await asyncio.sleep(.1)
  print("owned_close",flush=True)
class Context:pass
class Manager:
 async def __aenter__(self):return self
 async def __aexit__(self,*args):print("driver_disconnect",flush=True)
gate=ExecutorCancellation();gate.install()
context=BorrowedContext(Context(),"bili");context.owned_pages.append(Page())
async def crawl():
 async with BorrowedDriver(Manager(),[context]):
  print("ready",flush=True)
  await asyncio.sleep(60)
try:asyncio.run(gate.run(crawl()))
except asyncio.CancelledError:print("cancelled",flush=True)
finally:gate.restore()
'''
        child=subprocess.Popen([sys.executable,'-B','-c',code],cwd=Path(__file__).parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            os.kill(child.pid,signal.SIGTERM);os.kill(child.pid,signal.SIGTERM)
            output,errors=child.communicate(timeout=3)
            self.assertEqual(child.returncode,0,errors)
            self.assertEqual(output.splitlines(),['owned_close','driver_disconnect','cancelled'])
        finally:
            if child.poll() is None:child.kill();child.wait()

    def test_termination_preserves_driver_for_borrowed_only(self):
        import signal
        with patch('browser_session.os.kill') as single,patch('browser_session.os.killpg') as group:
            terminate_executor(4321,True);single.assert_called_once_with(4321,signal.SIGTERM);group.assert_not_called()
            terminate_executor(4321,False);group.assert_called_once_with(4321,signal.SIGTERM)

    def test_signal_cancels_running_task_and_owned_cleanup_precedes_disconnect(self):
        import os,signal
        events=[]
        class Page:
            async def close(self):events.append('owned_close')
        class Context:pass
        class Manager:
            async def __aenter__(self):return object()
            async def __aexit__(self,*args):events.append('driver_disconnect')
        context=BorrowedContext(Context(),'bili');context.owned_pages.append(Page())
        gate=ExecutorCancellation();gate.install()
        async def crawl():
            async with BorrowedDriver(Manager(),[context]):
                asyncio.get_running_loop().call_soon(os.kill,os.getpid(),signal.SIGTERM)
                await asyncio.sleep(30)
        try:
            with self.assertRaises(asyncio.CancelledError):asyncio.run(gate.run(crawl()))
        finally:gate.restore()
        self.assertEqual(events,['owned_close','driver_disconnect'])

    def test_early_signal_cancels_before_crawl_has_started(self):
        events=[];gate=ExecutorCancellation();gate.request()
        async def crawl():events.append('started')
        with self.assertRaises(asyncio.CancelledError):asyncio.run(gate.run(crawl()))
        self.assertEqual(events,[])

    def test_existing_mode_uses_only_account_metadata(self):
        with patch('account_sessions.AccountSessions.status',return_value={'browser_connection':{'mode':'existing_cdp'}}):
            self.assertTrue(existing_browser_session('/tmp','session'))
        with patch('account_sessions.AccountSessions.status',return_value={}):
            self.assertFalse(existing_browser_session('/tmp','session'))
    def test_shared_context_cookie_calls_stay_on_platform_no_storage_delegate(self):
        calls=[]
        class Context:
            async def cookies(self,urls=None):
                calls.append(urls)
                return [{'domain':'.bilibili.com','value':'OWN'}, {'domain':'.weibo.com','value':'OTHER'}, {'domain':'evilbilibili.com','value':'OTHER'}]
        borrowed=BorrowedContext(Context(),'bili')
        self.assertEqual(asyncio.run(borrowed.cookies()),[{'domain':'.bilibili.com','value':'OWN'}])
        self.assertTrue(all('bilibili.com' in url for url in calls[0]))
        self.assertEqual(asyncio.run(borrowed.cookies('https://api.bilibili.com/x/web-interface/nav')),[{'domain':'.bilibili.com','value':'OWN'}])
        before=len(calls)
        with self.assertRaisesRegex(BrowserSessionError,'invalid_cookie_scope'):asyncio.run(borrowed.cookies('https://weibo.com/'))
        self.assertEqual(len(calls),before)
        for name in ['storage_state','add_cookies','browser','route']:
            self.assertFalse(hasattr(borrowed,name))

    def test_driver_closes_owned_context_before_disconnect_and_keeps_cancel(self):
        events=[]
        class Manager:
            async def __aenter__(self):return 'driver'
            async def __aexit__(self,*args):events.append('disconnect');return False
        class Context:
            async def close(self):events.append('owned_cleanup')
        async def execute():
            async with BorrowedDriver(Manager(),[Context()]) as value:self.assertEqual(value,'driver')
        asyncio.run(execute());self.assertEqual(events,['owned_cleanup','disconnect'])
        events.clear()
        class Cancel:
            async def close(self):raise asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):asyncio.run(BorrowedDriver(Manager(),[Cancel()]).__aexit__(None,None,None))
        self.assertEqual(events,['disconnect'])

    def test_common_installer_native_driver_lifetime_cleanup(self):
        events=[]
        class BrowserType:
            name='chromium'
            async def launch_persistent_context(self,*args,**kwargs):raise AssertionError('must not launch new profile')
        class Manager:
            async def __aenter__(self):return 'driver'
            async def __aexit__(self,*args):events.append('driver_disconnect');return False
        class Owned:
            async def close(self):events.append('owned_pages_closed')
        binding={'mode':'existing_cdp','selection_kind':'platform_page','port':9222,'target_id':TARGET,'browser_fingerprint':'0'*64}
        store=SimpleNamespace(status=lambda *args:{'browser_connection':binding})
        native=SimpleNamespace(async_playwright=lambda:Manager())
        crawler=type('Crawler',(),{'__module__':'isolated_native_crawler'})
        with patch.dict(sys.modules,{'isolated_native_crawler':native}),patch('browser_session.connect_context',return_value=Owned()):
            install_browser_reuse(store,'sid','bili',BrowserType,crawler)
            async def execute():
                async with native.async_playwright():await BrowserType().launch_persistent_context('untouched')
            asyncio.run(execute())
        self.assertEqual(events,['owned_pages_closed','driver_disconnect'])

    def test_no_platform_tab_offers_explicit_https_anchor_not_special_pages(self):
        def anchor_metadata(port,path):
            if path=='/json/version':return metadata(port,path)
            return [{'id':TARGET,'type':'page','url':'https://example.org/?PRIVATE','title':'PRIVATE'},
                    {'id':'b'*32,'type':'page','url':'chrome://extensions/'},
                    {'id':'c'*32,'type':'page','url':'about:blank'},
                    {'id':'d'*32,'type':'page','url':'http://example.org/'}]
        with patch('browser_session.metadata',side_effect=anchor_metadata):
            value=inspect_browser(9222,'bili')
        self.assertEqual(value['targets'],[{'target_id':TARGET,'platform':'bili','selection_kind':'context_anchor','page_number':1}])
        self.assertNotIn('PRIVATE',json.dumps(value))

    def test_context_anchor_attaches_exact_user_choice_even_when_new_platform_tab_exists(self):
        events=[]
        class Context:
            def __init__(self,identity,url):self.pages=[SimpleNamespace(identity=identity,url=url)]
            async def new_cdp_session(self,page):
                class Protocol:
                    async def send(self,method):return {'targetInfo':{'targetId':page.identity}}
                    async def detach(self):events.append(page.identity)
                return Protocol()
        decoy=Context('b'*32,'https://www.bilibili.com/')
        chosen=Context(TARGET,'https://example.org/')
        class Chromium:
            async def connect_over_cdp(self,*args,**kwargs):return SimpleNamespace(contexts=[decoy,chosen])
        def data(port,path):
            if path=='/json/version':return metadata(port,path)
            return [{'id':TARGET,'type':'page','url':'https://example.org/'},
                    {'id':'b'*32,'type':'page','url':'https://www.bilibili.com/'}]
        with patch('browser_session.metadata',side_effect=data):
            value=inspect_browser(9222,'bili')
            self.assertEqual(value['targets'][0]['target_id'],'b'*32)
            bound={'mode':'existing_cdp','selection_kind':'context_anchor','port':9222,'target_id':TARGET,'browser_fingerprint':value['browser_fingerprint']}
            context=asyncio.run(connect_context(Chromium(),bound,'bili'))
            self.assertIs(context._context,chosen)
    def test_native_popup_cleanup_checks_our_opener_and_never_closes_user_popup(self):
        events=[];owned=object();user=object()
        class Page:
            def __init__(self,opener):self.parent=opener
            async def opener(self):return self.parent
            async def close(self):events.append(self.parent)
        for parent in [owned,user]:
            with self.subTest(ours=parent is owned):
                popup=Page(parent)
                class Context:
                    @contextlib.asynccontextmanager
                    async def expect_page(self):
                        async def received():return popup
                        yield SimpleNamespace(value=received())
                borrowed=BorrowedContext(Context(),'bili');borrowed.owned_pages=[owned]
                async def execute():
                    async with borrowed.expect_page() as pending:
                        pass
                    if parent is owned:self.assertIs(await pending.value,popup)
                    else:
                        with self.assertRaisesRegex(BrowserSessionError,'browser_popup_not_owned'):await pending.value
                    borrowed.owned_pages=[page for page in borrowed.owned_pages if page is not owned]
                    await borrowed.close()
                asyncio.run(execute())
        self.assertEqual(events,[owned])
    def test_candidates_only_selected_platform_and_no_urls_or_titles(self):
        with patch('browser_session.metadata',side_effect=metadata):
            value=inspect_browser(9222,'bili')
        self.assertEqual(value['targets'],[{'target_id':TARGET,'platform':'bili','selection_kind':'platform_page','page_number':1}])
        self.assertNotIn('PRIVATE',json.dumps(value))
        for version in [{'webSocketDebuggerUrl':'ws://evil.invalid:9222'+SOCKET},
                        {'webSocketDebuggerUrl':'ws://127.0.0.1:9223'+SOCKET},
                        {'webSocketDebuggerUrl':'ws://127.0.0.1:9222'+SOCKET+'?PRIVATE'}]:
            with patch('browser_session.metadata',return_value=version),self.assertRaisesRegex(BrowserSessionError,'invalid_browser_identity'):
                inspect_browser(9222,'bili')

    def test_explicit_context_and_cleanup_only_owned_pages(self):
        events=[]
        class Page:
            url='https://www.bilibili.com/'
            def __init__(self,identity):self.identity=identity
            async def close(self):events.append(('page_close',self.identity))
            async def add_init_script(self,*args,**kwargs):events.append(('script',self.identity))
        class Context:
            def __init__(self,identity):self.pages=[Page(identity)];self.identity=identity
            async def close(self):raise AssertionError('must not close original context')
            async def new_page(self):return Page('owned')
            async def new_cdp_session(self,page):
                class Protocol:
                    async def send(self,method):return {'targetInfo':{'targetId':page.identity}}
                    async def detach(self):events.append(('detach',page.identity))
                return Protocol()
        contexts=[Context('b'*32),Context(TARGET)]
        class Chromium:
            async def connect_over_cdp(self,url,**kwargs):events.append(('connect',url));return SimpleNamespace(contexts=contexts)
        with patch('browser_session.metadata',side_effect=metadata):
            candidate=inspect_browser(9222,'bili')
            binding={'mode':'existing_cdp','selection_kind':'platform_page','port':9222,'target_id':TARGET,'browser_fingerprint':candidate['browser_fingerprint']}
            async def execute():
                context=await connect_context(Chromium(),binding,'bili')
                self.assertIs(context._context,contexts[1])
                await context.add_init_script(path='local-existing-script')
                await context.new_page();await context.close();await context.close()
            asyncio.run(execute())
        self.assertEqual([row for row in events if row[0]=='page_close'],[('page_close','owned')])
        self.assertEqual([row for row in events if row[0]=='script'],[('script','owned')])
        self.assertEqual(events[0],('connect','ws://127.0.0.1:9222'+SOCKET))

    def test_changed_browser_or_missing_explicit_target_never_connects(self):
        class Chromium:
            async def connect_over_cdp(self,*args,**kwargs):raise AssertionError('must not attach')
        with patch('browser_session.metadata',side_effect=metadata):
            candidate=inspect_browser(9222,'bili')
            binding={'mode':'existing_cdp','selection_kind':'platform_page','port':9222,'target_id':TARGET,'browser_fingerprint':'0'*64}
            with self.assertRaisesRegex(BrowserSessionError,'browser_identity_changed'):asyncio.run(connect_context(Chromium(),binding,'bili'))
            binding.update(browser_fingerprint=candidate['browser_fingerprint'],target_id='c'*32)
            with self.assertRaisesRegex(BrowserSessionError,'browser_selected_page_unavailable'):asyncio.run(connect_context(Chromium(),binding,'bili'))
        for port in [True,1.0,80,65536]:
            with self.assertRaises(BrowserSessionError):validate_binding({**binding,'port':port},'bili')

    def test_binding_original_scope_needs_same_account_proof_and_busy_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sid=str(uuid.uuid4());rid=str(uuid.uuid4())
            session=root/'sessions'/sid;session.mkdir(parents=True)
            (session/'identity.json').write_text(json.dumps({'platform':'bili'}))
            store=AccountSessions(root)
            store.observe(sid,'bili','checking',rid)
            before=store.observe(sid,'bili','authenticated',rid,'original-account')
            with patch('browser_session.metadata',side_effect=metadata):
                choices=store.browser_candidates(sid)
                self.assertNotIn('_socket_path',choices)
                with open(session/'active.lock','a+') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    with self.assertRaisesRegex(ValueError,'session_busy'):
                        store.bind_browser(sid,9222,TARGET,choices['browser_fingerprint'],before['generation'])
                bound=store.bind_browser(sid,9222,TARGET,choices['browser_fingerprint'],before['generation'])
            self.assertIsNone(bound['authorized_for_run']);self.assertFalse(bound['login_verified'])
            self.assertEqual(bound['verified_at'],0)
            restored=store.observe(sid,'bili','authenticated',account_id='original-account')
            self.assertEqual(restored['state'],'resumed');self.assertEqual(restored['authorized_for_run'],rid)
            changed=store.observe(sid,'bili','authenticated',account_id='other-account')
            self.assertEqual(changed['state'],'account_changed');self.assertIsNone(changed['authorized_for_run'])

    def test_dedicated_registration_replays_without_changing_original_profile_or_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sid=str(uuid.uuid4());rid=str(uuid.uuid4())
            original=root/'sessions'/sid;original.mkdir(parents=True)
            (original/'identity.json').write_text(json.dumps({'platform':'bili'}))
            profile=original/'browser_data';profile.mkdir();(profile/'untouched').write_bytes(b'PRIVATE ORIGINAL')
            store=AccountSessions(root);store.observe(sid,'bili','checking',rid)
            before=store.observe(sid,'bili','authenticated',rid,'original-account')
            oldstate=(root/'accounts'/sid/'state.json').read_bytes()
            with patch('browser_session.metadata',side_effect=metadata):
                choices=store.browser_candidates(sid)
                bound=store.create_browser_session('bili',9222,TARGET,choices['browser_fingerprint'])
                replay=store.create_browser_session('bili',9222,TARGET,choices['browser_fingerprint'])
            self.assertNotEqual(bound['session_id'],sid);self.assertEqual(replay['session_id'],bound['session_id'])
            self.assertTrue(replay['registration_replayed'])
            self.assertIsNone(bound['authorized_for_run']);self.assertFalse(bound['login_verified'])
            self.assertEqual((root/'accounts'/sid/'state.json').read_bytes(),oldstate)
            self.assertEqual((profile/'untouched').read_bytes(),b'PRIVATE ORIGINAL')
            new=store.observe(bound['session_id'],'bili','authenticated',account_id='selected-account')
            self.assertEqual(new['state'],'authenticated');self.assertIsNone(new['authorized_for_run'])
            unbound=store.use_persistent_browser(bound['session_id'],new['generation'])
            self.assertNotIn('browser_connection',unbound);self.assertFalse(unbound['login_verified'])
            self.assertEqual(store.status(sid)['authorized_for_run'],before['authorized_for_run'])

    def test_disconnection_is_check_failed_not_logout_and_default_unchanged(self):
        class BrowserType:
            name='chromium'
            async def launch_persistent_context(self,*args,**kwargs):return 'original'
        class Store:
            def __init__(self,binding):self.binding=binding;self.events=[]
            def status(self,*args):return {'browser_connection':self.binding}
            def observe(self,*args):self.events.append(args[-1])
            def _update(self,sid,platform,change):
                value={};change(value);self.events.append(value)
        store=Store(None);old=BrowserType.launch_persistent_context
        self.assertFalse(install_browser_reuse(store,'sid','bili',BrowserType));self.assertIs(old,BrowserType.launch_persistent_context)
        binding={'mode':'existing_cdp','selection_kind':'platform_page','port':9222,'target_id':TARGET,'browser_fingerprint':'0'*64}
        store=Store(binding)
        try:
            install_browser_reuse(store,'sid','bili',BrowserType)
            with patch('browser_session.inspect_browser',side_effect=BrowserSessionError('browser_unreachable')):
                with self.assertRaisesRegex(BrowserSessionError,'browser_unreachable'):asyncio.run(BrowserType().launch_persistent_context('ignored'))
            self.assertEqual(store.events[0],'check_failed');self.assertFalse(store.events[1]['login_verified'])
        finally:BrowserType.launch_persistent_context=old

    def test_application_route_and_existing_cli_contract(self):
        from workbench_cli import ROUTES
        self.assertIn('bind_browser',ROUTES['accounts'])
        with tempfile.TemporaryDirectory() as folder:
            app=Application(Path(folder));app.owner_tasks.close()
            sid=str(uuid.uuid4());root=app._roots()[0]
            session=root/'sessions'/sid;session.mkdir(parents=True)
            (session/'identity.json').write_text(json.dumps({'platform':'bili'}))
            with patch('browser_session.metadata',side_effect=metadata):
                choices=app.accounts('browser_candidates',{'session_id':sid})
                bound=app.accounts('bind_browser',{'session_id':sid,'port':9222,'target_id':TARGET,'browser_fingerprint':choices['browser_fingerprint'],'expected_generation':0})
            self.assertEqual(bound['state'],'checking');self.assertFalse(bound['login_verified'])
            with self.assertRaises(ValueError):app.accounts('bind_browser',{'session_id':sid,'url':'http://evil.invalid'})

    def test_real_http_route_lists_and_binds_only_selected_session_no_source(self):
        import dashboard
        with tempfile.TemporaryDirectory() as folder:
            app=Application(Path(folder));app.owner_tasks.close()
            sid=str(uuid.uuid4());session=app._roots()[0]/'sessions'/sid;session.mkdir(parents=True)
            (session/'identity.json').write_text(json.dumps({'platform':'bili'}))
            server=dashboard.make_server(app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            origin='http://127.0.0.1:'+str(server.server_port)
            def post(action,payload):
                req=urllib.request.Request(origin+'/api/accounts',data=json.dumps({'action':action,'payload':payload}).encode(),headers={'Content-Type':'application/json','Origin':origin,'X-Crowd-CSRF':app.token})
                return urllib.request.urlopen(req)
            try:
                with patch('browser_session.metadata',side_effect=metadata),patch.object(app,'run',side_effect=AssertionError('source must not run')):
                    choices=json.load(post('browser_candidates',{'session_id':sid}))
                    self.assertNotIn('PRIVATE',json.dumps(choices))
                    self.assertNotIn('_socket_path',choices)
                    payload={'session_id':sid,'port':9222,'target_id':TARGET,'browser_fingerprint':choices['browser_fingerprint'],'expected_generation':0}
                    bound=json.load(post('bind_browser',payload));self.assertEqual(bound['state'],'checking')
                    with self.assertRaises(urllib.error.HTTPError) as caught:post('bind_browser',{**payload,'expected_generation':True})
                    self.assertEqual(caught.exception.code,400)
                    with self.assertRaises(urllib.error.HTTPError):post('bind_browser',{**payload,'endpoint':'http://evil.invalid'})
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
