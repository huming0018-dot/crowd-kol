import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from account_sessions import AccountSessions
from browser_session import BrowserSessionError, active_socket_path, inspect_browser, socket_metadata, connect_context

SOCKET='/devtools/browser/00000000-0000-4000-8000-000000000001'
TARGET='a'*32


class MetadataTransportTests(unittest.TestCase):
    def write_endpoint(self, home, text, browser='Google/Chrome'):
        path=Path(home)/'Library/Application Support'/browser/'DevToolsActivePort'
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        return path

    def test_exact_public_metadata_only_port_shape_and_inode(self):
        with tempfile.TemporaryDirectory() as home,patch('browser_session.Path.home',return_value=Path(home).resolve()):
            path=self.write_endpoint(home,'9222\n'+SOCKET+'\n')
            self.assertEqual(active_socket_path(9222),SOCKET)
            for value in ['9223\n'+SOCKET, '9222\nws://evil.invalid/secret', '9222\n'+SOCKET+'\nPRIVATE', 'x'*513]:
                path.write_text(value)
                with self.assertRaisesRegex(BrowserSessionError,'endpoint_unavailable'):active_socket_path(9222)
            path.write_text('9222\n'+SOCKET);os.link(path,path.with_name('hardlink'))
            with self.assertRaisesRegex(BrowserSessionError,'endpoint_unavailable'):active_socket_path(9222)
            path.with_name('hardlink').unlink();path.rename(path.with_name('actual'));path.symlink_to(path.with_name('actual'))
            with self.assertRaisesRegex(BrowserSessionError,'endpoint_unavailable'):active_socket_path(9222)

    def test_metadata_ambiguity_never_selects_first_browser(self):
        with tempfile.TemporaryDirectory() as home,patch('browser_session.Path.home',return_value=Path(home).resolve()):
            self.write_endpoint(home,'9222\n'+SOCKET)
            self.write_endpoint(home,'9222\n'+SOCKET[:-1]+'2','Google/Chrome Canary')
            with self.assertRaisesRegex(BrowserSessionError,'endpoint_ambiguous'):active_socket_path(9222)

    def channel(self, values):
        calls=[]
        class Channel:
            def __enter__(self):return self
            def __exit__(self,*args):calls.append('disconnect')
            def send(self,value):calls.append(json.loads(value))
            def recv(self,timeout):
                value=values.pop(0)
                if isinstance(value,Exception):raise value
                return json.dumps(value)
        return Channel(),calls

    def test_direct_socket_only_two_safe_methods_and_no_proxy(self):
        channel,calls=self.channel([{'id':1,'result':{'product':'Chrome/144.0.0.0'}}, {'id':2,'result':{'targetInfos':[{'type':'page','targetId':TARGET,'url':'https://www.bilibili.com/?SECRET','title':'SECRET'}]}}])
        with patch('websockets.sync.client.connect',return_value=channel) as connect:
            rows=socket_metadata(9222,SOCKET)
        self.assertEqual([item['method'] for item in calls[:-1]],['Browser.getVersion','Target.getTargets'])
        self.assertEqual(rows[0]['id'],TARGET)
        self.assertEqual(connect.call_args.kwargs['proxy'],None)
        self.assertEqual(connect.call_args.kwargs['max_size'],262144)

    def test_pending_permission_and_bad_response_never_logged_out(self):
        for values,code in [([TimeoutError()],'browser_connection_pending'),([{'id':1,'error':{'message':'PRIVATE'}}],'invalid_browser_metadata')]:
            channel,calls=self.channel(values)
            with patch('websockets.sync.client.connect',return_value=channel):
                with self.assertRaisesRegex(BrowserSessionError,code):socket_metadata(9222,SOCKET)
            self.assertEqual(calls[-1],'disconnect')
        events=[{'method':'event','params':{}}]*65
        channel,_=self.channel(events)
        with patch('websockets.sync.client.connect',return_value=channel):
            with self.assertRaisesRegex(BrowserSessionError,'metadata_too_large'):socket_metadata(9222,SOCKET)

    def test_http404_falls_back_but_invalid_http_identity_does_not(self):
        with patch('browser_session.metadata',side_effect=BrowserSessionError('browser_metadata_endpoint_unavailable')),patch('browser_session.active_socket_path',return_value=SOCKET),patch('browser_session.socket_metadata',return_value=[{'id':TARGET,'type':'page','url':'https://www.bilibili.com/?SECRET','title':'SECRET'}]) as direct:
            value=inspect_browser(9222,'bili')
            self.assertNotIn('SECRET',json.dumps(value));direct.assert_called_once_with(9222,SOCKET)
        with patch('browser_session.metadata',return_value={'webSocketDebuggerUrl':'ws://evil.invalid/devtools/browser/'+TARGET}),patch('browser_session.active_socket_path') as active:
            with self.assertRaisesRegex(BrowserSessionError,'invalid_browser_identity'):inspect_browser(9222,'bili')
            active.assert_not_called()

    def test_registration_uses_one_observation_keeps_old_session(self):
        with tempfile.TemporaryDirectory() as root:
            store=AccountSessions(root)
            candidate={'port':9222,'browser_fingerprint':hashlib.sha256(SOCKET.encode()).hexdigest(),'targets':[{'target_id':TARGET,'selection_kind':'platform_page'}]}
            with patch('browser_session.inspect_browser',return_value=candidate) as inspect:
                value=store.create_browser_session('bili',9222,TARGET,candidate['browser_fingerprint'])
                self.assertEqual(inspect.call_count,1)
                self.assertEqual(value['state'],'checking');self.assertFalse(value['login_verified'])
                repeat=store.create_browser_session('bili',9222,TARGET,candidate['browser_fingerprint'])
                self.assertTrue(repeat['registration_replayed']);self.assertEqual(value['session_id'],repeat['session_id'])

    def test_direct_runtime_exact_target_no_second_metadata_socket(self):
        sent=[]
        class Context:
            pages=[SimpleNamespace(url='https://www.bilibili.com/')]
            async def new_cdp_session(self,page):
                class Protocol:
                    async def send(self,method):sent.append(method);return {'targetInfo':{'targetId':TARGET}}
                    async def detach(self):sent.append('detach')
                return Protocol()
        context=Context()
        class Chromium:
            async def connect_over_cdp(self,url,timeout):sent.append('connect');return SimpleNamespace(contexts=[context])
        binding={'mode':'existing_cdp','port':9222,'target_id':TARGET,'selection_kind':'platform_page','browser_fingerprint':hashlib.sha256(SOCKET.encode()).hexdigest()}
        with patch('browser_session.metadata',side_effect=BrowserSessionError('browser_metadata_endpoint_unavailable')),patch('browser_session.active_socket_path',return_value=SOCKET),patch('browser_session.socket_metadata') as probe:
            borrowed=asyncio.run(connect_context(Chromium(),binding,'bili'))
            self.assertIs(borrowed._context,context);probe.assert_not_called()
            binding['browser_fingerprint']='0'*64
            with self.assertRaisesRegex(BrowserSessionError,'identity_changed'):asyncio.run(connect_context(Chromium(),binding,'bili'))
        self.assertEqual(sent,['connect','Target.getTargetInfo','detach'])


if __name__=='__main__':unittest.main()
