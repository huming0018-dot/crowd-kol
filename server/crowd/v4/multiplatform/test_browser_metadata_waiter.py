"""Native consent keeps one socket; fixture channels never connect to Chrome."""
import threading
import time
import unittest
from unittest.mock import patch

import browser_session as browser
from test_browser_metadata_transport import SOCKET,TARGET


class WaiterTests(unittest.TestCase):
    def setUp(self):
        self.old=browser._metadata_waiters
        browser._metadata_waiters={}

    def tearDown(self):
        for state in browser._metadata_waiters.values():state['hold'].set()
        time.sleep(.02)
        browser._metadata_waiters=self.old

    def test_pending_repeated_poll_one_live_connection_ready_without_new_probe(self):
        allowed=threading.Event();live=threading.Event();ended=threading.Event();calls=[]
        def transport(port,path,seconds,on_ready,hold):
            calls.append((port,path,seconds));live.set();allowed.wait(2)
            on_ready([{'id':TARGET,'type':'page','url':'https://www.bilibili.com/'}])
            hold.wait(2);ended.set()
        with patch.object(browser,'socket_metadata',side_effect=transport):
            for _ in range(3):
                with self.assertRaisesRegex(browser.BrowserSessionError,'connection_pending'):browser.retained_socket_metadata(9222,SOCKET)
            self.assertTrue(live.wait(1));self.assertEqual(len(calls),1);self.assertFalse(ended.is_set())
            allowed.set()
            deadline=time.monotonic()+1
            while browser._metadata_waiters[(9222,SOCKET)]['state']!='ready' and time.monotonic()<deadline:time.sleep(.001)
            for _ in range(2):self.assertEqual(browser.retained_socket_metadata(9222,SOCKET)[0]['id'],TARGET)
            self.assertEqual(len(calls),1);self.assertFalse(ended.is_set())
            browser._metadata_waiters[(9222,SOCKET)]['deadline']=0
            with self.assertRaisesRegex(browser.BrowserSessionError,'connection_expired'):browser.retained_socket_metadata(9222,SOCKET)
            self.assertEqual(len(calls),1)

    def test_failed_and_expired_do_not_automatically_open_again(self):
        with patch.object(browser,'socket_metadata',side_effect=browser.BrowserSessionError('browser_connection_failed')) as transport:
            with self.assertRaises(browser.BrowserSessionError):browser.retained_socket_metadata(9222,SOCKET)
            time.sleep(.02)
            for _ in range(2):
                with self.assertRaisesRegex(browser.BrowserSessionError,'connection_failed'):browser.retained_socket_metadata(9222,SOCKET)
            self.assertEqual(transport.call_count,1)

    def test_restart_requires_expired_original_and_explicit_boolean(self):
        started=threading.Event();calls=[]
        def transport(port,path,seconds,on_ready,hold):calls.append(port);started.set();hold.wait(2)
        with patch.object(browser,'socket_metadata',side_effect=transport):
            with self.assertRaisesRegex(browser.BrowserSessionError,'connection_active'):browser.retained_socket_metadata(9222,SOCKET,True)
            with self.assertRaisesRegex(browser.BrowserSessionError,'connection_pending'):browser.retained_socket_metadata(9222,SOCKET)
            self.assertTrue(started.wait(1))
            with self.assertRaisesRegex(browser.BrowserSessionError,'connection_active'):browser.retained_socket_metadata(9222,SOCKET,True)
            browser._metadata_waiters[(9222,SOCKET)]['deadline']=0
            with self.assertRaisesRegex(browser.BrowserSessionError,'connection_expired'):browser.retained_socket_metadata(9222,SOCKET)
            self.assertEqual(len(calls),1)
            with self.assertRaisesRegex(browser.BrowserSessionError,'connection_pending'):browser.retained_socket_metadata(9222,SOCKET,True)
            deadline=time.monotonic()+1
            while len(calls)<2 and time.monotonic()<deadline:time.sleep(.001)
            self.assertEqual(len(calls),2)
            with self.assertRaisesRegex(browser.BrowserSessionError,'invalid_browser_restart'):browser.retained_socket_metadata(9222,SOCKET,1)

    def test_account_pending_state_retains_platform_identity_without_login_change(self):
        from account_sessions import AccountSessions
        from pathlib import Path
        import tempfile,json,uuid
        with tempfile.TemporaryDirectory() as root:
            store=AccountSessions(root);session_id=str(uuid.uuid4());folder=Path(root)/'sessions'/session_id;folder.mkdir(parents=True)
            (folder/'identity.json').write_text(json.dumps({'platform':'bili'}))
            before=store.status(session_id)
            for code in ('browser_connection_pending','browser_connection_expired'):
                with patch.object(browser,'inspect_browser',side_effect=browser.BrowserSessionError(code)):
                    result=store.browser_candidates(session_id)
                    self.assertTrue(result['ok']);self.assertEqual(result['targets'],[]);self.assertEqual(result['reason_code'],code)
                    self.assertEqual(before,store.status(session_id))

    def test_same_live_socket_explicit_target_refresh_without_extending_deadline(self):
        import json
        calls=[];queue=[];closed=threading.Event()
        class Channel:
            def __enter__(self):return self
            def __exit__(self,*args):closed.set()
            def send(self,raw):
                value=json.loads(raw);calls.append(value['method'])
                result={'product':'Chrome/144.0'} if value['method']=='Browser.getVersion' else {'targetInfos':[] if value['id']==2 else [{'targetId':TARGET,'type':'page','url':'https://www.bilibili.com/'}]}
                queue.append(json.dumps({'id':value['id'],'result':result}))
            def recv(self,timeout):return queue.pop(0)
        def ready():
            deadline=time.monotonic()+1
            while browser._metadata_waiters[(9222,SOCKET)]['state']!='ready' and time.monotonic()<deadline:time.sleep(.001)
        with patch('websockets.sync.client.connect',return_value=Channel()) as connect:
            with self.assertRaisesRegex(browser.BrowserSessionError,'connection_pending'):browser.retained_socket_metadata(9222,SOCKET,refresh_targets=True)
            connect.assert_not_called()
            with self.assertRaisesRegex(browser.BrowserSessionError,'connection_pending'):browser.retained_socket_metadata(9222,SOCKET)
            ready();state=browser._metadata_waiters[(9222,SOCKET)];deadline=state['deadline']
            self.assertEqual(browser.retained_socket_metadata(9222,SOCKET),[])
            for _ in range(8):
                with self.assertRaisesRegex(browser.BrowserSessionError,'connection_pending'):browser.retained_socket_metadata(9222,SOCKET,refresh_targets=True)
                ready();self.assertEqual(browser.retained_socket_metadata(9222,SOCKET)[0]['id'],TARGET)
            with self.assertRaisesRegex(browser.BrowserSessionError,'refresh_limit'):browser.retained_socket_metadata(9222,SOCKET,refresh_targets=True)
            self.assertEqual(connect.call_count,1);self.assertEqual(state['deadline'],deadline);self.assertFalse(closed.is_set())
            self.assertEqual(calls,['Browser.getVersion']+['Target.getTargets']*9)
            state['hold'].set()
            self.assertTrue(closed.wait(1))


if __name__=='__main__':unittest.main()
