"""Offline protocol/import tests. No credential read, browser or source request."""
import asyncio
from contextvars import ContextVar
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
import uuid

import mc_runner as m
import pro_executor as pro
from results_store import ResultsStore
from cloud_sync import CloudOutbox


class ProTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rid = str(uuid.uuid4())
        self.run = self.root/'runs'/self.rid
        (self.run/'output').mkdir(parents=True)
        self.request = m.validate({'platform':'bili','mode':'detail','targets':['BV1ocaW6rETo'],
                                  'max_items':1,'max_comments':20,'comments':True,'replies':True,
                                  'purpose':'noncommercial_research'})
        self.manifest = {'run_id':self.rid,'request':self.request,'source':{'executor':'mediacrawler_pro'},
                         'executor':{'backend':'pro'},'discovery_contract_version':1}
        m.write(self.run/'manifest.json', self.manifest)
        m.write(self.run/'status.json', {'state':'completed','updated_at':time.time()})
        self.db = sqlite3.connect(self.run/pro.DB_NAME)
        self.db.execute('CREATE TABLE vox_crawl_observation(operation_id TEXT,platform TEXT,kind TEXT,entity_id TEXT,payload TEXT,PRIMARY KEY(operation_id,kind,entity_id))')
        self.body = {'video_id':'123','bvid':'BV1ocaW6rETo','title':'离线样本','desc':'全文' * 501,
                     'video_url':'https://www.bilibili.com/video/BV1ocaW6rETo',
                     'video_cover_url':'https://i0.hdslb.com/cover.jpg','duration':'431',
                     'creator_hash':'abc123','nickname':'甲*'}
        self.row('topic','123',self.body)
        self.row('comment','10',{'video_id':'123','comment_id':'10','parent_comment_id':'0',
                                'content':'第一页根评论','sub_comment_count':'2','pictures':'https://i0.hdslb.com/comment.jpg'})
        self.row('comment','11',{'video_id':'123','comment_id':'11','parent_comment_id':'10',
                                'content':'第二页回复','sub_comment_count':'0'})
        self.row('comment','12',{'video_id':'123','comment_id':'12','parent_comment_id':'10','content':'第三页回复'})
        self.cp = {'id':self.rid,'platform':'bili','mode':'detail','acquisition_committed':True,'is_completed':True,
                   'failed_search_pages':[],'crawled_note_list':[{'note_id':'123','is_success_crawled':True,
                   'is_success_crawled_comments':True,'current_note_comment_cursor':'page-3','saved_comment_count':3}]}
        (self.run/'data/checkpoints').mkdir(parents=True)
        m.write(self.run/'data/checkpoints'/(self.rid+'.json'), self.cp)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def row(self, kind, entity, value, operation=None, platform='bili'):
        self.db.execute('INSERT OR REPLACE INTO vox_crawl_observation VALUES(?,?,?,?,?)',
                        (operation or self.rid,platform,kind,entity,m.canonical(value)))
        self.db.commit()

    def summary(self):
        return {'operation_id':self.rid,'platform':'bili','crawler_type':'detail','status':'completed'}

    def test_optional_selection_preserves_all_existing_features(self):
        self.assertEqual(pro.selection(self.request,{})['backend'],'mc')
        env = {'CROWD_EXECUTOR':'pro','CROWD_PRO_ROOT':str(self.root)}
        self.assertEqual(pro.selection(self.request,env)['backend'],'pro')
        for changes in ({'platform':'zhihu'},{'platform':'ks'},{'platform':'wb'},{'platform':'tieba'},
                        {'mode':'homefeed'},{'mode':'trending'},{'media':True},{'wordcloud':True},
                        {'platform_options':{'transcript_only':True}}, {'max_comments':0}):
            result=pro.selection({**self.request,**changes},env)
            self.assertEqual(result['backend'],'mc');self.assertIn('fallback_reason',result)
        with self.assertRaisesRegex(m.BridgeError,'pro_root_missing'):
            pro.selection(self.request,{'CROWD_EXECUTOR':'pro'})

    def test_binding_never_uses_first_available_or_remote_service(self):
        folder=self.root/'sessions'/self.request['session_id'];folder.mkdir(parents=True)
        with self.assertRaisesRegex(m.BridgeError,'binding_required'):pro.binding_for(self.root,self.request)
        good={'platform':'bili','client_id':'fixture-client','cookiebridge_url':'http://127.0.0.1:8274','sign_url':'http://127.0.0.1:8989'}
        for delta in ({'platform':'xhs'},{'client_id':''},{'cookiebridge_url':'https://example.com'},
                      {'cookiebridge_url':'http://name:password@localhost:80'}, {'sign_url':'http://localhost:8989/sign'},
                      {'cookies':'must-not-import'}):
            m.write(folder/'pro-binding.json',{**good,**delta})
            with self.assertRaises(m.BridgeError):pro.binding_for(self.root,self.request)
        m.write(folder/'pro-binding.json',good)
        self.assertEqual(pro.binding_for(self.root,self.request),good)
        m.write(folder/'pro-binding.json',{**good,'sign_url':'http://[::1]:8989'})
        with self.assertRaisesRegex(m.BridgeError,'pro_sign_ipv6_unsupported'):
            pro.binding_for(self.root,self.request)
        # CookieBridge consumes the complete URL and retains valid loopback IPv6.
        m.write(folder/'pro-binding.json',{**good,'cookiebridge_url':'http://[::1]:8274'})
        self.assertEqual(pro.binding_for(self.root,self.request)['cookiebridge_url'],'http://[::1]:8274')

    def test_checkpoint_and_operation_completion_not_cloud_ack(self):
        committed=pro.completion(self.run,self.manifest,self.summary())
        self.assertTrue(committed['local_committed']);self.assertFalse(committed['cloud_ack'])
        self.assertEqual((committed['content_count'],committed['comment_count']),(1,3))
        for delta in ({'operation_id':str(uuid.uuid4())},{'status':'failed'},{'platform':'xhs'},{}):
            if not delta:continue
            with self.assertRaises(m.BridgeError):pro.completion(self.run,self.manifest,{**self.summary(),**delta})
        for delta in ({'acquisition_committed':False},{'is_completed':False},{'failed_search_pages':[1]},
                      {'crawled_note_list':[]},{'id':'other'},
                      {'crawled_note_list':[{'note_id':'123','is_success_crawled':True,'is_success_crawled_comments':False}]}):
            m.write(self.run/'data/checkpoints'/(self.rid+'.json'),{**self.cp,**delta})
            with self.assertRaises(m.BridgeError):pro.completion(self.run,self.manifest,self.summary())

    def test_observation_scope_and_source_identity_rejects_cross_platform(self):
        self.row('topic','other',{'video_id':'other'},operation='another-operation')
        self.assertEqual(len(pro.observations(self.run,self.manifest)),4)
        self.row('comment','99',{'comment_id':'99','video_id':'123'},platform='xhs')
        with self.assertRaisesRegex(m.BridgeError,'identity_mismatch'):pro.observations(self.run,self.manifest)

    def test_import_export_and_pending_outbox_keep_reply_media_contract(self):
        imported=m.import_output(self.root,{'run_id':self.rid})
        records=imported['records']
        self.assertEqual(len(records),4)
        content=next(r for r in records if r['kind']=='content')
        self.assertEqual(content['body'],self.body['desc']);self.assertEqual(content['platform_fields']['bvid'],'BV1ocaW6rETo')
        self.assertNotIn('upstream_truncation_risk',content)
        replies={r['comment_id']:r['parent_comment_id'] for r in records if r['kind']=='comment'}
        self.assertEqual(replies,{'10':'0','11':'10','12':'10'})
        self.assertEqual(len(imported['media']),2)
        self.assertTrue(all(i['status']=='reference_only' and 'sha256' not in i and 'bytes' not in i for i in imported['media']))
        self.assertFalse(imported['pro_acquisition']['raw_response_pages_available'])
        store=ResultsStore(self.root)
        first=store.ingest(imported);self.assertEqual(first['added_versions'],6)
        self.assertTrue(store.ingest(imported)['duplicate_import'])
        exported={}
        for fmt in ('json','jsonl','csv'):
            exported[fmt]=store.export(fmt)
            self.assertTrue(exported[fmt]['data'])
        class NoNetwork:
            def call(self,*_):raise AssertionError('No cloud call authorized')
        outbox=CloudOutbox(self.root,NoNetwork())
        lease={key:str(uuid.uuid4()) for key in ('task_id','child_id','run_id')}
        lease.update(lease_epoch=1,platform='bili',delivery_basis='live_capture')
        ids=outbox.stage_imported(records,lease)
        self.assertEqual(len(ids),4);self.assertEqual(ids,outbox.stage_imported(records,lease))
        self.assertEqual(outbox.stats()['pending'],4)
        self.assertEqual(outbox.stats()['acknowledged'],0)

    def test_public_reference_secret_never_exports(self):
        self.body['video_cover_url']='https://example.com/a?access_token=private'
        self.row('topic','123',self.body)
        records,media,_=pro.import_records(self.run,self.manifest)
        self.assertNotIn('private',m.canonical(records));self.assertEqual(len(media),1)

    def test_duplicate_page_observations_are_upserted_and_partial_stays_partial(self):
        self.row('comment','11',{'video_id':'123','comment_id':'11','parent_comment_id':'10','content':'同页重访新观测'})
        rows,_,_=pro.import_records(self.run,self.manifest)
        self.assertEqual(sum(r['kind']=='comment' for r in rows),3)
        self.assertEqual(next(r for r in rows if r.get('comment_id')=='11')['text'],'同页重访新观测')
        cp=deepcopy(self.cp);cp['acquisition_committed']=False;cp['crawled_note_list'][0]['is_success_crawled_comments']=False
        m.write(self.run/'data/checkpoints'/(self.rid+'.json'),cp)
        imported=m.import_output(self.root,{'run_id':self.rid})
        self.assertFalse(imported['pro_acquisition']['local_committed'])

    def test_protocol_progress_ignores_other_ops_and_logs(self):
        sink=pro.ProgressSink(self.run,self.manifest)
        sink.write('Cookie: never saved\n@@MCPRO_EVENT@@'+json.dumps({'operation_id':'other','schema_version':pro.PROTOCOL,'platform':'bili','item_count':900})+'\n')
        self.assertFalse((self.run/'phase.json').exists())
        event={'operation_id':self.rid,'schema_version':pro.PROTOCOL,'platform':'bili','status':'running','item_count':1,'comment_count':3,'cookies':'secret'}
        sink.write('@@MCPRO_EVENT@@'+json.dumps(event)+'\n')
        state=m.read(self.run/'phase.json');self.assertEqual(state['comment_count'],3);self.assertNotIn('secret',m.canonical(state))
        sink.write('---CRAWL_SUMMARY: '+json.dumps({**self.summary(),'error':'private payload'})+'---\n')
        self.assertEqual(sink.summary,self.summary())

    def test_exact_pro_cli_does_not_use_legacy_flags(self):
        args=pro.argv_for(self.request)
        self.assertIn('--urls',args);self.assertIn('--enable_sub_comments',args)
        self.assertNotIn('--lt',args);self.assertNotIn('--get_media',args)
        self.assertEqual(args[-1],'BV1ocaW6rETo')

    def test_transport_hard_budget_and_auth_stop_before_retry(self):
        class AsyncClient:
            async def send(self,*a,**kw):return SimpleNamespace(status_code=200)
        class SyncClient:
            def send(self,*a,**kw):return SimpleNamespace(status_code=401)
        class Response:
            async def aiter_bytes(self):yield b'a'
        http=SimpleNamespace(AsyncClient=AsyncClient,Client=SyncClient,Response=Response)
        sink=pro.ProgressSink(self.run,self.manifest)
        pro.install_transport_limits(http,{'max_api_requests':2},sink)
        asyncio.run(AsyncClient().send())
        with self.assertRaises(SystemExit) as rejected:SyncClient().send()
        self.assertEqual(rejected.exception.code,77)
        with self.assertRaises(SystemExit) as limited:asyncio.run(AsyncClient().send())
        self.assertEqual(limited.exception.code,73);self.assertEqual(sink.attempts,2)
        self.assertEqual(m.read(self.run/'phase.json')['failure_reason'],'api_request_limit')

    def test_bound_cookiebridge_exact_client_validation_no_enumeration(self):
        calls=[]
        payload={'isok':True,'data':{'client_id':'chosen','platform':'bili','cookies':'synthetic_fixture_only'}}
        class HTTP:
            def __init__(self,**kw):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
            async def get(self,url,params):
                calls.append((url,params))
                return SimpleNamespace(raise_for_status=lambda:None,json=lambda:payload)
        class Pool:
            _platform_name='bili'
            def __init__(self):self.accounts=[]
            def add_account(self,a):self.accounts.append(a)
        bound={'client_id':'chosen','cookiebridge_url':'http://127.0.0.1:8274'}
        model=SimpleNamespace(AccountInfoModel=lambda **kw:kw,AccountStatusEnum=SimpleNamespace(NORMAL=SimpleNamespace(value=0)))
        with patch.dict('sys.modules',{'pkg.account_pool.pool':model}):
            pro.install_bound_account(Pool,bound,'bili',SimpleNamespace(AsyncClient=HTTP))
            pool=Pool();asyncio.run(pool.load_accounts_from_cookie_bridge())
            self.assertEqual(len(pool.accounts),1)
            self.assertEqual(calls,[('http://127.0.0.1:8274/api/cookies/bili',{'client_id':'chosen'})])
            payload['data']['client_id']='another'
            with self.assertRaises(SystemExit) as changed:asyncio.run(Pool().load_accounts_from_cookie_bridge())
            self.assertEqual(changed.exception.code,78)
            payload['data']['client_id']='chosen';payload['data']['valid']=False
            with self.assertRaises(SystemExit) as invalid:asyncio.run(Pool().load_accounts_from_cookie_bridge())
            self.assertEqual(invalid.exception.code,77)

    def test_supervisor_pro_failure_never_launches_mc_fallback(self):
        manifest={**self.manifest,'executor':{'backend':'pro','python':'/fixture/pro/python'}}
        m.write(self.run/'manifest.json',manifest)
        child=Mock();child.poll.return_value=74;child.wait.return_value=74
        with patch.object(m.subprocess,'Popen',return_value=child) as launched,patch.object(m.os,'close'):
            m.worker(self.root,Path('/fixture/mc'),self.rid,99)
        self.assertEqual(launched.call_count,1)
        self.assertEqual(launched.call_args.args[0][0],'/fixture/pro/python')
        self.assertEqual(m.status(self.root,{'run_id':self.rid})['state'],'failed')

    def test_known_challenge_and_frequency_exit_cannot_be_caught_by_retry_exception(self):
        m.write(self.run/'manifest.json',{**self.manifest,'executor':{'backend':'pro','python':'/fixture/pro/python'}})
        for status,code,expected in [(461,None,80),(471,None,80),(429,None,79),(200,300013,79),
                                      (200,-100,77),(200,300012,81),(200,300015,82)]:
            calls=[]
            class Client:
                async def send(self,*a,**kw):
                    calls.append('source')
                    return SimpleNamespace(status_code=status,json=lambda:{'code':code})
            class Response:
                async def aiter_bytes(self):yield b'a'
            http=SimpleNamespace(AsyncClient=Client,Client=type('Sync',(),{'send':lambda *_:None}),Response=Response)
            pro.install_transport_limits(http,{'max_api_requests':20,'platform':'xhs'},pro.ProgressSink(self.run,self.manifest))
            async def upstream_retry():
                for _ in range(5):
                    try:return await Client().send()
                    except Exception:continue
            with self.assertRaises(SystemExit) as stopped:asyncio.run(upstream_retry())
            self.assertEqual(stopped.exception.code,expected);self.assertEqual(calls,['source'])
            child=Mock();child.poll.return_value=expected;child.wait.return_value=expected
            with patch.object(m.subprocess,'Popen',return_value=child),patch.object(m.os,'close'):
                m.worker(self.root,Path('/fixture/mc'),self.rid,99)
            self.assertIn(m.status(self.root,{'run_id':self.rid})['reason'],
                          ('captcha_required','rate_limited','login_required','platform_blocked','platform_signature_rejected'))


class UpstreamLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def probe(self, main, close_error=None):
        self.context = ContextVar('fixture_database', default=None)
        self.closed = 0
        self.database = SimpleNamespace(_conn=object())
        async def close():
            self.closed += 1
            if close_error:
                raise close_error
            self.context.get()._conn = None
        async def entry():
            self.context.set(self.database)
            return await main(close)
        with patch.dict('sys.modules', {'var':SimpleNamespace(media_crawler_db_var=self.context),
                                      'db':SimpleNamespace(close=close)}):
            return await pro.run_upstream(SimpleNamespace(main=entry))

    async def test_successful_upstream_close_is_not_repeated(self):
        async def main(close):
            await close()
            return 'committed'
        self.assertEqual(await self.probe(main),'committed')
        self.assertEqual(self.closed,1)

    async def test_budget_baseexception_is_preserved_and_connection_closed(self):
        error=SystemExit(73)
        async def main(close):raise error
        with self.assertRaises(SystemExit) as caught:await self.probe(main)
        self.assertIs(caught.exception,error)
        self.assertEqual(self.closed,1);self.assertIsNone(self.database._conn)

    async def test_cancellation_preserves_cause_and_closes_in_original_context(self):
        async def main(close):raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):await self.probe(main)
        self.assertEqual(self.closed,1);self.assertIsNone(self.database._conn)

    async def test_wait_for_timeout_closes_before_return(self):
        async def main(close):await asyncio.sleep(60)
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(self.probe(main),timeout=.02)
        self.assertEqual(self.closed,1);self.assertIsNone(self.database._conn)

    async def test_cleanup_failure_does_not_replace_original_exit(self):
        error=SystemExit(73)
        async def main(close):raise error
        with self.assertRaises(SystemExit) as caught:
            await self.probe(main,close_error=OSError('fixture close failure'))
        self.assertIs(caught.exception,error);self.assertEqual(self.closed,1)

    async def test_cleanup_failure_on_success_is_not_false_completion(self):
        async def main(close):return 'not-yet-closed'
        with self.assertRaises(OSError):
            await self.probe(main,close_error=OSError('fixture close failure'))
        self.assertEqual(self.closed,1)


if __name__ == '__main__': unittest.main()
