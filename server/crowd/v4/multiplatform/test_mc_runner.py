#!/usr/bin/env python3
"""No source-site access. Fake process lifecycle + real installed CLI wiring."""
import ast
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('mc_bridge',HERE/'mc_runner.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
MC=Path(os.environ.get('MC_EXTERNAL_ROOT','/Users/hubowen/WorkBuddy/2026-10-08-22-53-19/MediaCrawler'))
PYTHON=MC/'.venv/bin/python'

class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='crowd-mc-test-')
        self.base=Path(self.tmp.name)
        self.mc=self.base/'executor'
        for p in ['cmd_arg','libs','media_platform/kuaishou/graphql','.venv/bin','playwright']:
            (self.mc/p).mkdir(parents=True,exist_ok=True)
        (self.mc/'LICENSE').write_text('Synthetic test executor, no upstream code')
        (self.mc/'cmd_arg/arg.py').write_text('# fixture')
        (self.mc/'config.py').write_text('CRAWLER_MAX_SLEEP_SEC=2\n')
        (self.mc/'playwright/__init__.py').write_text('')
        (self.mc/'playwright/async_api.py').write_text('class BrowserType:\n async def launch(self,*a,**kw): return None\n async def launch_persistent_context(self,*a,**kw): return None\n')
        (self.mc/'.venv/bin/python').symlink_to(PYTHON if PYTHON.exists() else sys.executable)
        (self.mc/'httpx.py').write_text('from types import SimpleNamespace\nclass Response:\n request=SimpleNamespace(url="https://fixture.invalid")\n status_code=200\n async def aiter_bytes(self,*a,**kw):\n  for _ in range(30): yield b"x"*1048576\nclass AsyncClient:\n async def send(self,*a,**kw): return Response()\nclass Client:\n def send(self,*a,**kw): return Response()\n')
        (self.mc/'requests.py').write_text('import httpx\nclass Session:\n def send(self,*a,**kw): return httpx.Response()\nclass sessions:\n Session=Session\n')
        from account_sessions import CLIENTS
        for module, name in CLIENTS.values():
            folder=self.mc/'media_platform'/module;folder.mkdir(parents=True,exist_ok=True)
            (folder/'client.py').write_text('import config\nclass '+name+':\n async def pong(self,*a,**kw): return config.FAKE_AUTH_LOGGED_IN\n async def update_cookies(self,*a,**kw): return None\n')
        (self.mc/'main.py').write_text('''import asyncio,json,pathlib,sys
import config,httpx
async def main():
 args=dict(zip(sys.argv[1::2],sys.argv[2::2]))
 p=args['--platform']; mode=args['--type']; target=args.get('--keywords',args.get('--specified_id',args.get('--creator_id')))
 config.FAKE_AUTH_LOGGED_IN=target!='slow'
 import importlib
 from account_sessions import CLIENTS
 module,name=CLIENTS[p]
 await getattr(importlib.import_module('media_platform.'+module+'.client'),name)().pong()
 assert config.ENABLE_CDP_MODE is False and config.COOKIES==''
 assert config.CRAWLER_MAX_SLEEP_SEC==2
 assert config.USER_DATA_DIR=='%s_bridge_profile'
 assert pathlib.Path('libs').is_dir() and pathlib.Path('media_platform/kuaishou/graphql').is_dir()
 if p=='zhihu' and mode=='creator': assert config.ZHIHU_CREATOR_URL_LIST==[target]
 if target=='slow':
  print('qrcode please scan TOKEN_SECRET_SENTINEL access_token=foo')
  await asyncio.sleep(30)
 for i in range(5 if target=='budget' else 1): await httpx.AsyncClient().send(None)
 if target=='large':
  async for chunk in httpx.Response().aiter_bytes(): pass
 key={'xhs':'note_id','dy':'aweme_id','ks':'video_id','bili':'video_id','wb':'note_id','tieba':'note_id','zhihu':'content_id'}[p]
 writer_platform={'dy':'douyin','ks':'kuaishou','wb':'weibo'}.get(p,p)
 out=pathlib.Path(args['--save_data_path'])/writer_platform/'jsonl';out.mkdir(parents=True)
 rows=[{key:'id123','title':'fixture','desc':'body','like_count':0},{key:'bad?id','desc':'reject'}]
 (out/(mode+'_contents_today.jsonl')).write_text('\\n'.join(json.dumps(r) for r in rows)+'\\n')
 (out/(mode+'_comments_today.jsonl')).write_text(json.dumps({key:'id123','comment_id':'c1','parent_comment_id':'c0','content':'reply'})+'\\n')
 if args['--get_media']=='true':
  import base64
  media=pathlib.Path(args['--save_data_path'])/p/'media'/'id123';media.mkdir(parents=True)
  (media/'image.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1cAAAAASUVORK5CYII='))
 print('access_token=SECRET_SENTINEL')
async def async_cleanup(): pass
''')
        self.root=self.base/'runtime'
    def tearDown(self):
        self.tmp.cleanup()
    def payload(self,p='xhs',mode='search',target='fixture',**kw):
        if mode!='search' and target=='fixture':
            target={'xhs':'66fad51c000000001b0224b8','dy':'123' if mode=='detail' else 'fixture','ks':'fixture','bili':'BV1Vs411j7cX' if mode=='detail' else '123','wb':'123','tieba':'123' if mode=='detail' else 'fixture','zhihu':'https://www.zhihu.com/zvideo/123' if mode=='detail' else 'fixture'}[p]
        return dict(platform=p,mode=mode,targets=[target],purpose='noncommercial_research',**kw)
    def invoke(self,action,payload):
        proc=subprocess.run([sys.executable,str(HERE/'mc_runner.py'),'--root',str(self.root),'--mc-root',str(self.mc),action],input=json.dumps(payload),text=True,capture_output=True)
        self.assertNotIn('SECRET_SENTINEL',proc.stdout+proc.stderr)
        return json.loads(proc.stdout)
    def wait(self,run):
        for _ in range(80):
            result=self.invoke('status',{'run_id':run})['result']
            if result['state'] in m.FINAL: return result
            time.sleep(.1)
        self.fail('worker did not finish')
    def test_21_platform_mode_process_and_import(self):
        for platform in m.PLATFORMS:
            for mode in ('search','detail','creator'):
                with self.subTest(platform=platform,mode=mode):
                    started=self.invoke('start',self.payload(platform,mode))
                    self.assertTrue(started['ok'],started)
                    run=started['result']['run_id']
                    self.assertEqual(self.wait(run)['state'],'completed')
                    result=self.invoke('import',{'run_id':run})['result']
                    self.assertEqual(result['summary']['contents'],1)
                    self.assertEqual(result['summary']['comments'],1)
                    self.assertEqual(result['summary']['rejected_records'],1)
                    self.assertEqual(result['records'][0]['platform'],m.PLATFORMS[platform])
                    self.assertEqual(next(r for r in result['records'] if r['kind']=='comment')['parent_comment_id'],'c0')
                    self.assertFalse(result['reward_eligible'])
                    self.assertEqual(result['source_kind'],'mediacrawler_api')
                    self.assertTrue(all('SECRET_SENTINEL' not in f.read_text(errors='ignore') for f in (self.root/'runs'/run).glob('*.json')))
    def test_jsonl_real_names_legacy_aliases_and_no_double_import(self):
        for platform, name in [('dy','douyin'),('ks','kuaishou'),('wb','weibo')]:
            with self.subTest(platform=platform):
                rid=str(uuid.uuid4());run=self.root/'runs'/rid
                output=run/'output';long=output/name/'jsonl';short=output/platform/'jsonl'
                long.mkdir(parents=True);short.mkdir(parents=True)
                m.write(run/'status.json',{'state':'completed'})
                m.write(run/'manifest.json',{'run_id':rid,'request':{'platform':platform},'source':{}})
                key=m.ID_KEYS[platform]
                row={key:'first','desc':'real writer output'}
                (long/'detail_contents_today.jsonl').write_text((json.dumps(row)+'\n')*2)
                (short/'detail_contents_today.jsonl').write_text(json.dumps(row)+'\n'+json.dumps({key:'second','desc':'legacy unique row'})+'\n')
                result=m.import_output(self.root,{'run_id':rid})
                self.assertEqual([r['content_id'] for r in result['records']],['first','first','second'])
                self.assertEqual(len(result['files']),2)
                self.assertEqual(result['summary']['contents'],3)
                self.assertTrue(all(r['source_kind']=='mediacrawler_api' for r in result['records']))
                # Old short-code-only runs remain readable.
                (long/'detail_contents_today.jsonl').unlink()
                self.assertEqual(m.import_output(self.root,{'run_id':rid})['summary']['contents'],2)
                long.rmdir();long.symlink_to(short,target_is_directory=True)
                with self.assertRaisesRegex(m.BridgeError,'unsafe_output_file'):
                    m.import_output(self.root,{'run_id':rid})

    def test_stop_lock_reuse_and_platform_binding(self):
        p=self.payload(target='slow')
        run=self.invoke('start',p)['result']
        p['session_id']=run['session_id']
        self.assertEqual(self.invoke('start',p)['error'],'session_busy')
        self.assertTrue(self.invoke('stop',{'run_id':run['run_id']})['result']['stop_requested'])
        self.assertEqual(self.wait(run['run_id'])['state'],'stopped')
        p['targets']=['fixture']
        reused=self.invoke('start',p)['result']
        self.assertEqual(reused['session_id'],run['session_id'])
        from account_sessions import AccountSessions
        store=AccountSessions(self.root)
        for _ in range(80):
            if store.status(run['session_id'])['state']=='identity_unverified':break
            time.sleep(.1)
        account=store.status(run['session_id'])
        self.assertEqual(account['state'],'identity_unverified')
        self.assertEqual(account['generation'],0)
        self.assertIsNone(account['authorized_for_run'])
        store.confirm_same_account(run['session_id'],0,True)
        self.assertEqual(self.wait(reused['run_id'])['state'],'completed')
        p['platform']='bili'
        self.assertEqual(self.invoke('start',p)['error'],'session_platform_mismatch')
    def test_request_budget_fail_closed(self):
        result=self.invoke('start',self.payload(target='budget',max_api_requests=2))['result']
        finished=self.wait(result['run_id'])
        self.assertEqual(finished['reason'],'api_request_limit')
        phase=m.read(self.root/'runs'/result['run_id']/'phase.json')
        self.assertEqual(phase['api_attempts'],2)
    def test_response_size_and_media_manifest(self):
        result=self.invoke('start',self.payload(target='large'))['result']
        self.assertEqual(self.wait(result['run_id'])['reason'],'response_byte_limit')
        result=self.invoke('start',self.payload(media=True))['result']
        self.assertEqual(self.wait(result['run_id'])['state'],'completed')
        data=self.invoke('import',{'run_id':result['run_id']})['result']
        self.assertEqual(len(data['media']),1)
        self.assertEqual(data['media'][0]['path'],'output/xhs/media/id123/image.png')

    def test_headless_session_login_required(self):
        first=self.invoke('start',self.payload())['result']
        self.assertEqual(self.wait(first['run_id'])['state'],'completed')
        headless=self.invoke('start',self.payload(target='slow',headless=True,session_id=first['session_id']))['result']
        result=self.wait(headless['run_id'])
        self.assertEqual(result['state'],'login_required')
        self.assertEqual(result['reason'],'login_required')

    def test_weibo_detail_urls_to_cli_ids(self):
        cases={
            'https://weibo.com/7798269830/5264010640887796':'5264010640887796',
            'https://www.weibo.com/7798269830/AbC123?from=page':'AbC123',
            'https://m.weibo.cn/detail/5264010640887796':'5264010640887796',
            'https://m.weibo.cn/status/AbC123/':'AbC123',
            '5264010640887796':'5264010640887796','AbC123':'AbC123',
        }
        for target,expected in cases.items():
            with self.subTest(target=target):
                p=m.validate(self.payload('wb','detail',target))
                args=m.argv_for(p,self.base/'out')
                self.assertEqual(args[args.index('--specified_id')+1],expected)
                self.assertEqual(p['targets'],[target])
        for target in ['https://weibo.com/u/7798269830','https://weibo.com/','https://weibo.com/cctvxinwen','https://weibo.com/search/foo','https://m.weibo.cn/profile/7798269830','https://m.weibo.cn/status/a/b','https://evil.weibo.com/1/AbC','https://weibo.com/1/%2fabc']:
            with self.subTest(target=target),self.assertRaisesRegex(m.BridgeError,'invalid_weibo_detail_url'):
                m.validate(self.payload('wb','detail',target))
        with self.assertRaisesRegex(m.BridgeError,'credential_target_not_allowed'):
            m.validate(self.payload('wb','detail','https://weibo.com/1/AbC?access_token=hidden'))
        creator=m.validate(self.payload('wb','creator','https://weibo.com/u/7798269830'))
        self.assertEqual(m.argv_for(creator,self.base/'out')[-1],'7798269830')
        search=m.validate(self.payload('wb','search','普通搜索关键词'))
        self.assertEqual(m.argv_for(search,self.base/'out')[-1],'普通搜索关键词')
        xhs=m.validate(self.payload('xhs','detail','https://www.xiaohongshu.com/explore/66fad51c000000001b0224b8?xsec_token=local'))
        self.assertEqual(m.argv_for(xhs,self.base/'out')[-1],xhs['targets'][0])

    def test_validation_and_secrets(self):
        for kwargs,code in [({'platform':[]},'unsupported_platform_or_mode'),({'platform':'no'},'unsupported_platform_or_mode'),({'max_items':2},'upstream_search_minimum_20'),({'media':1},'invalid_media'),({'replies':True,'comments':False},'replies_require_comments')]:
            p=self.payload();p.update(kwargs)
            self.assertEqual(self.invoke('start',p)['error'],code)
        p=self.payload(mode='detail',target='https://www.xiaohongshu.com/explore/id?access_token=hidden')
        self.assertEqual(self.invoke('start',p)['error'],'credential_target_not_allowed')
        locator=m.validate(self.payload(mode='detail',target='https://www.xiaohongshu.com/explore/66fad51c000000001b0224b8?xsec_token=local&xsec_source=pc_search'))
        self.assertIn('xsec_token=local',locator['targets'][0])
        self.assertEqual(self.invoke('start',self.payload(headless=True))['error'],'headless_requires_existing_session')
        self.assertIsNone(m.safe_text('https://a.test/?ACCESS%5FTOKEN=secret'))
        self.assertIsNone(m.safe_text('https://user:password@a.test/'))
        self.assertEqual(m.reported_count('12'),12)
        self.assertIsNone(m.reported_count('-1'))
        record=m.normalize('xhs','content',{'note_id':'abc','desc':'safe','likes':None},{})
        self.assertEqual(record['metrics'],{})
        self.assertEqual(record['text_status'],'reported')
        self.assertFalse(record['reward_eligible'])
        with self.assertRaises(m.BridgeError): m.uid('../elsewhere')

    def test_bounded_options_and_executor_configuration(self):
        p=m.validate(self.payload('bili','creator','123',max_items=7,start_page=3,interval_seconds=0.5,platform_options={'creator_sections':['dynamics'],'quality':64}))
        self.assertFalse(p['comments'])
        config=SimpleNamespace(CRAWLER_MAX_SLEEP_SEC=2)
        m.configure_executor(config,p)
        self.assertFalse(config.CREATOR_MODE)
        self.assertEqual(config.CRAWLER_MAX_DYNAMICS_COUNT_SINGLENOTES,7)
        self.assertEqual(config.CRAWLER_MAX_SLEEP_SEC,.5)
        self.assertEqual(config.BILI_QN,64)
        args=m.argv_for(p,self.base/'out')
        self.assertEqual(args[args.index('--start')+1],'3')
        self.assertEqual(args[args.index('--max_concurrency_num')+1],'1')
        search=m.validate(self.payload('bili',platform_options={'search_mode':'all_in_time_range','start_day':'2026-10-01','end_day':'2026-10-02'}))
        m.configure_executor(config,search)
        self.assertEqual((config.START_DAY,config.END_DAY),('2026-10-01','2026-10-02'))
        invalid=[{'start_page':True},{'interval_seconds':True},{'interval_seconds':float('nan')},{'interval_seconds':-1},{'platform_options':{'followers':True}},{'platform_options':{'creator_sections':['dynamics']},'comments':True},{'platform_options':{'creator_sections':['videos','videos']}},{'platform_options':{'quality':True}},{'platform_options':[]},{'platform_options':{'search_mode':'all_in_time_range','start_day':'2026-10-03','end_day':'2026-10-01'}}]
        for values in invalid:
            with self.subTest(values=values),self.assertRaises(m.BridgeError): m.validate(self.payload('bili','creator','123',**values))
        with self.assertRaisesRegex(m.BridgeError,'unsupported_platform_options'): m.validate(self.payload('xhs',platform_options={'quality':64}))

    def test_explicit_xhs_comment_root_preserved_and_missing_parent_unknown(self):
        base={'note_id':'note1','comment_id':'comment1','content':'first-level'}
        root=m.normalize('xhs','comment',{**base,'parent_comment_id':''},{})
        self.assertEqual((root['parent_comment_id'],root['parent_status']),('','reported_root'))
        missing=m.normalize('xhs','comment',base,{})
        self.assertEqual((missing['parent_comment_id'],missing['parent_status']),(None,'missing_upstream'))
        reply=m.normalize('xhs','comment',{**base,'parent_comment_id':'parent1'},{})
        self.assertEqual((reply['parent_comment_id'],reply['parent_status']),('parent1','reported'))
        dy=m.normalize('dy','comment',{'aweme_id':'1','comment_id':'2','content':'root','parent_comment_id':'0'},{})
        self.assertEqual((dy['parent_comment_id'],dy['parent_status']),('0','reported'))
        self.assertNotEqual(root['record_hash'],missing['record_hash'])

    def test_tieba_explicit_root_and_weibo_self_parent_preserve_source_identity(self):
        tieba={'note_id':'thread1','comment_id':'comment1','content':'root'}
        root=m.normalize('tieba','comment',{**tieba,'parent_comment_id':''},{})
        self.assertEqual((root['parent_comment_id'],root['parent_status']),('','reported_root'))
        missing=m.normalize('tieba','comment',tieba,{})
        self.assertEqual((missing['parent_comment_id'],missing['parent_status']),(None,'missing_upstream'))
        wb={'note_id':'status1','comment_id':'comment1','content':'root'}
        self_root=m.normalize('wb','comment',{**wb,'parent_comment_id':'comment1'},{})
        self.assertEqual((self_root['parent_comment_id'],self_root['parent_status']),('comment1','reported_root'))
        reply=m.normalize('wb','comment',{**wb,'comment_id':'reply1','parent_comment_id':'comment1'},{})
        self.assertEqual((reply['parent_comment_id'],reply['parent_status']),('comment1','reported'))
        unknown=m.normalize('wb','comment',wb,{})
        self.assertEqual((unknown['parent_comment_id'],unknown['parent_status']),(None,'missing_upstream'))
        other=m.normalize('dy','comment',{'aweme_id':'1','comment_id':'2','content':'self','parent_comment_id':'2'},{})
        self.assertEqual(other['parent_status'],'reported')

    def test_target_shapes_normalize_before_executor_and_keep_private_locators(self):
        cases=[('xhs','detail','https://www.xiaohongshu.com/explore/66fad51c000000001b0224b8/?xsec_token=local','https://www.xiaohongshu.com/explore/66fad51c000000001b0224b8?xsec_token=local'),('xhs','creator','https://www.xiaohongshu.com/user/profile/5eb8e1d400000000010075ae/','https://www.xiaohongshu.com/user/profile/5eb8e1d400000000010075ae'),('dy','detail','https://www.douyin.com/user/fixture?modal_id=123','123'),('dy','creator','https://www.douyin.com/user/MS4wLjABAAAAexample/','MS4wLjABAAAAexample'),('ks','detail','https://www.kuaishou.com/short-video/3xexample/','3xexample'),('ks','creator','https://www.kuaishou.com/profile/3xexample/','3xexample'),('bili','detail','https://www.bilibili.com/video/BV1Vs411j7cX/?spm=fixture','BV1Vs411j7cX'),('bili','creator','https://space.bilibili.com/123/','123'),('wb','detail','https://weibo.com/123/AbCd','AbCd'),('wb','creator','https://weibo.com/u/123/','123'),('tieba','detail','https://tieba.baidu.com/p/123?pn=2','123'),('tieba','creator','https://tieba.baidu.com/home/main?id=tb.1.example_portrait','tb.1.example_portrait'),('tieba','creator','tb.1.example_portrait','tb.1.example_portrait'),('zhihu','detail','https://www.zhihu.com/question/123/answer/456/?tab=fixture','https://www.zhihu.com/question/123/answer/456'),('zhihu','creator','https://www.zhihu.com/people/alice/?tab=answers','alice')]
        for platform,mode,target,expected in cases:
            with self.subTest(platform=platform,mode=mode,target=target):
                p=m.validate(self.payload(platform,mode,target,max_items=1))
                self.assertEqual(m.argv_for(p,self.base/'output')[-1],expected)
                self.assertEqual(p['targets'][0],target)
                if platform=='zhihu' and mode=='creator':
                    config=SimpleNamespace();m.configure_executor(config,p)
                    self.assertEqual(config.ZHIHU_CREATOR_URL_LIST,[expected])
        invalid=[('xhs','detail','https://www.xiaohongshu.com/user/profile/66fad51c000000001b0224b8'),('xhs','creator','abc'),('dy','detail','abc'),('dy','creator','https://www.douyin.com/video/123'),('ks','detail','https://v.kuaishou.cn/AbCd'),('ks','creator','https://www.kuaishou.com/short-video/id'),('bili','detail','av123'),('bili','detail','123'),('bili','creator','https://www.bilibili.com/video/BV1Vs411j7cX'),('wb','creator','https://weibo.com/namedprofile'),('tieba','detail','https://tieba.baidu.com/f?kw=fixture'),('tieba','creator','https://tieba.baidu.com/home/main'),('tieba','creator','https://tieba.baidu.com/home/main?un=fixture'),('zhihu','detail','123'),('zhihu','detail','https://www.zhihu.com/question/123'),('zhihu','creator','https://www.zhihu.com/org/fixture')]
        for platform,mode,target in invalid:
            with self.subTest(invalid=target),self.assertRaises(m.BridgeError): m.validate(self.payload(platform,mode,target,max_items=1))

    def test_bilibili_both_sections_reuses_live_creator_context(self):
        calls=[]
        class Crawler:
            async def get_creator_videos(self,creator_id): calls.append(('videos',creator_id))
            async def get_all_creator_details(self,targets): calls.append(('dynamics',targets))
        upstream=SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'bili':Crawler}))
        p=m.validate(self.payload('bili','creator','123',platform_options={'creator_sections':['dynamics','videos']}))
        m.configure_platform_hooks(upstream,p)
        asyncio.run(Crawler().get_creator_videos(123))
        self.assertEqual(calls,[('videos',123),('dynamics',['123'])])

    def test_tieba_media_uses_own_hook_without_native_flag(self):
        from unittest.mock import patch
        import tieba_media
        class Native: pass
        p=m.validate(self.payload('tieba','detail','123',max_items=1,media=True))
        args=m.argv_for(p,self.base/'output')
        self.assertEqual(args[args.index('--get_media')+1],'false')
        module=SimpleNamespace(BaiduTieBaClient=Native)
        with patch.dict(sys.modules,{'media_platform.tieba.client':module}),patch.object(tieba_media,'install_hook') as hook:
            m.configure_platform_hooks(None,p)
            hook.assert_called_once_with(Native,Path.cwd()/'output')
            p['media']=False
            m.configure_platform_hooks(None,p)
            self.assertEqual(hook.call_count,1)
        info=next(x for x in m.capabilities(self.mc)['platforms'] if x['id']=='tieba')
        self.assertTrue(info['media'])
        self.assertEqual(next(x for x in info['platform_features'] if x['id']=='public_post_media')['live_verified'],False)

    def test_bili_single_response_media_limit_preserves_comments_and_hard_stops(self):
        from unittest.mock import patch
        work=self.base.resolve()/'bili-run';folder=work/'output/bili/media';folder.mkdir(parents=True)
        old=folder/'old.part';old.write_bytes(b'old immutable partial')
        calls=[]
        class Crawler:
            failure=m.SingleResponseLimit()
            async def download_media(self,*args):
                (folder/'new.part').write_bytes(b'limited partial')
                raise self.failure
            async def comments(self):calls.append('comments')
        upstream=SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'bili':Crawler}))
        p=m.validate(self.payload('bili','detail',media=True,max_items=1))
        with patch.object(m.Path,'cwd',return_value=work):
            m.configure_platform_hooks(upstream,p)
            async def collect():
                await Crawler().download_media()
                await Crawler().comments()
            asyncio.run(collect())
            self.assertEqual(calls,['comments'])
            self.assertEqual(m.read(work/'phase.json')['media_status'],'limited')
            self.assertFalse((folder/'new.part').exists())
            self.assertEqual(old.read_bytes(),b'old immutable partial')
            for code in (73,76,77):
                Crawler.failure=SystemExit(code)
                with self.assertRaises(SystemExit) as stopped:asyncio.run(Crawler().download_media())
                self.assertEqual(stopped.exception.code,code)

    def test_zhihu_media_all_modes_use_own_hook_without_native_flag(self):
        from unittest.mock import patch
        import zhihu_media
        class Native:pass
        for mode in ('search','detail','creator'):
            p=m.validate(self.payload('zhihu',mode,media=True))
            args=m.argv_for(p,self.base/'output')
            self.assertEqual(args[args.index('--get_media')+1],'false')
            with patch.dict(sys.modules,{'media_platform.zhihu.client':SimpleNamespace(ZhiHuClient=Native)}),patch.object(zhihu_media,'install_hook') as hook:
                m.configure_platform_hooks(None,p)
                hook.assert_called_once_with(Native,Path.cwd()/'output')
        self.assertEqual(m.MEDIA,set(m.PLATFORMS))
        self.assertNotIn('zhihu',m.NATIVE_MEDIA)

    def test_field_fidelity_dynamic_identity_and_upstream_partiality(self):
        wb=m.normalize('wb','content',{'note_id':'note','comments_count':'12','shared_count':'3','desc':'正文'},{})
        self.assertEqual(wb['metrics']['comments_count']['reported_value'],'12')
        self.assertEqual(wb['metrics']['shared_count']['reported_value'],'3')
        bili=m.normalize('bili','content',{'video_id':'123','video_type':'video','desc':'x'*500,'nickname':'匿名UP','creator_hash':'abc'},{})
        self.assertEqual(bili['content_type'],'video')
        self.assertEqual(bili['canonical_id_scheme'],'bilibili.aid.v1')
        self.assertFalse(bili['text_truncated'])
        self.assertEqual(bili['text_completeness'],'unknown')
        self.assertEqual(bili['upstream_truncation_risk']['limit_chars'],500)
        dynamic=m.normalize('bili','dynamic',{'dynamic_id':'123','text':'动态','type':'WORD','pub_ts':1234,'total_comments':4,'total_forwards':3,'total_liked':2},{})
        self.assertEqual(dynamic['canonical_id_scheme'],'bilibili.dynamic.v1')
        self.assertNotEqual(dynamic['entity_key'],bili['entity_key'])
        self.assertEqual(dynamic['published_at_reported'],1234)
        self.assertEqual(dynamic['metrics']['total_comments']['reported_value'],4)
        secret=m.normalize('bili','content',{'video_id':'123','creator_hash':'access_token=hidden','desc':'safe'},{})
        self.assertNotIn('creator_hash',secret['platform_fields'])
        self.assertNotIn('author',secret)
        self.assertEqual(bili['author']['author_id'],'abc')
        self.assertEqual(bili['author']['identity_status'],'anonymized_upstream')
        public=m.normalize('wb','content',{'note_id':'note','user_id':123,'title':'access_token=hidden','desc':'safe'},{})
        self.assertEqual(public['author']['author_id'],'123')
        self.assertEqual(public['author']['identity_status'],'reported_upstream')
        self.assertEqual(public['title_status'],'withheld_sensitive')
        self.assertIsNone(public['title'])
        long_title=m.normalize('xhs','content',{'note_id':'note','title':'x'*2001,'desc':'safe'},{})
        self.assertTrue(long_title['title_truncated'])
        self.assertEqual(len(long_title['title']),2000)

    def test_optional_wordcloud_requires_comments_and_local_resources(self):
        p=m.validate(self.payload(wordcloud=True))
        config=SimpleNamespace(CRAWLER_MAX_SLEEP_SEC=2)
        m.configure_executor(config,p)
        self.assertTrue(config.ENABLE_GET_WORDCLOUD)
        with self.assertRaisesRegex(m.BridgeError,'wordcloud_requires_comments'): m.validate(self.payload(wordcloud=True,comments=False))
        with self.assertRaisesRegex(m.BridgeError,'invalid_wordcloud'): m.validate(self.payload(wordcloud=1))
        run=self.base/'wordcloud-run';run.mkdir()
        config.FONT_PATH='missing.ttf';config.STOP_WORDS_FILE='missing.txt'
        upstream=SimpleNamespace()
        m.configure_wordcloud(upstream,config,p,self.mc,run)
        self.assertFalse(config.ENABLE_GET_WORDCLOUD)
        asyncio.run(upstream._generate_wordcloud_if_needed())
        self.assertEqual(m.read(run/'phase.json')['wordcloud_status'],'resource_missing')
        (self.mc/'config.py').write_text('CRAWLER_MAX_SLEEP_SEC=2\nFONT_PATH="missing.ttf"\nSTOP_WORDS_FILE="missing.txt"\n')
        started=self.invoke('start',self.payload(wordcloud=True))['result']
        self.assertEqual(self.wait(started['run_id'])['state'],'completed')
        saved=self.invoke('import',{'run_id':started['run_id']})['result']
        self.assertEqual(saved['summary']['contents'],1)
        self.assertEqual(saved['wordcloud_status'],'resource_missing')

    def test_media_import_retains_reported_identity_type_hash_and_bounds(self):
        import hashlib
        rid=str(uuid.uuid4());run=self.root/'runs'/rid
        for kind in ('answer','article'):
            folder=run/'output/zhihu/media/123'/kind;folder.mkdir(parents=True)
            (folder/'001.jpg').write_bytes(('fake '+kind).encode())
        m.write(run/'manifest.json',{'run_id':rid,'request':{'platform':'zhihu'},'source':{}})
        m.write(run/'status.json',{'state':'completed'})
        result=m.import_output(self.root,{'run_id':rid})
        self.assertEqual(len(result['media']),2)
        for item in result['media']:
            self.assertEqual(item['content_id'],'123')
            self.assertEqual(item['platform'],'zhihu')
            self.assertEqual(item['sha256'],hashlib.sha256((run/item['path']).read_bytes()).hexdigest())
            self.assertIn(item['source_content_type'],('answer','article'))
            self.assertFalse(item['reward_eligible'])
        with open(run/'output/zhihu/media/123/answer/too_large.mp4','wb') as stream:stream.truncate(26214401)
        with self.assertRaisesRegex(m.BridgeError,'media_import_byte_limit'):m.import_output(self.root,{'run_id':rid})

    def test_long_audio_option_and_same_dash_response_hook(self):
        from unittest.mock import patch,AsyncMock
        import bili_audio
        p=m.validate(self.payload('bili','detail',media=True,max_items=1,platform_options={'long_audio':True}))
        for invalid in ({'long_audio':1},{'long_audio':'true'}):
            with self.assertRaises(m.BridgeError):m.validate(self.payload('bili','detail',media=True,platform_options=invalid))
        with self.assertRaises(m.BridgeError):m.validate(self.payload('bili','detail',media=False,platform_options={'long_audio':True}))
        with self.assertRaises(m.BridgeError):m.validate(self.payload('dy','detail',media=True,platform_options={'long_audio':True}))
        calls=[]
        class Crawler:
            async def download_media(self,*args):raise AssertionError('native video path must not run')
            async def get_video_play_url_task(self,*args,**kw):
                calls.append((args,kw));return {'dash':{'audio':[]}}
        upstream=SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'bili':Crawler}))
        work=self.base.resolve()/'audio-hook';work.mkdir()
        downloaded=AsyncMock(return_value={'status':'unavailable','reason':'dash_audio_unavailable'})
        with patch.dict(sys.modules,{'media_platform.bilibili.media':SimpleNamespace(DASH_FNVAL=16)}),patch.object(bili_audio,'download_audio',downloaded),patch.object(m.Path,'cwd',return_value=work):
            m.configure_platform_hooks(upstream,p)
            video={'View':{'aid':1,'cid':2,'bvid':'BV123','duration':4915.9}}
            asyncio.run(Crawler().download_media(video,object()))
        self.assertEqual(len(calls),1);self.assertEqual(calls[0][1],{'fnval':16})
        self.assertEqual(downloaded.await_count,1)
        self.assertEqual(m.read(work/'phase.json')['media_reason'],'dash_audio_unavailable')
        self.assertEqual(m.read(work/'phase.json')['media_kind'],'audio')
        with patch.object(m.Path,'cwd',return_value=work):
            downloaded.side_effect=ValueError('private-url-must-not-be-logged')
            asyncio.run(Crawler().download_media(video,object()))
            self.assertEqual(m.read(work/'phase.json')['media_reason'],'audio_adapter_failed')
            downloaded.side_effect=SystemExit(73)
            with self.assertRaises(SystemExit):asyncio.run(Crawler().download_media(video,object()))

    def test_long_audio_import_requires_explicit_scope(self):
        rid=str(uuid.uuid4());run=self.root/'runs'/rid;folder=run/'output/bili/media/BV123';folder.mkdir(parents=True)
        asset=folder/'audio.m4a'
        with asset.open('wb') as stream:stream.truncate(26214401)
        manifest={'run_id':rid,'request':{'platform':'bili','platform_options':{}},'source':{}}
        m.write(run/'manifest.json',manifest);m.write(run/'status.json',{'state':'completed'})
        with self.assertRaisesRegex(m.BridgeError,'media_import_byte_limit'):m.import_output(self.root,{'run_id':rid})
        manifest['request']['platform_options']={'long_audio':True};m.write(run/'manifest.json',manifest)
        item=m.import_output(self.root,{'run_id':rid})['media'][0]
        self.assertEqual(item['kind'],'audio');self.assertEqual(item['single_file_limit_bytes'],67108864)
        asset.rename(folder/'video.mp4')
        with self.assertRaisesRegex(m.BridgeError,'media_import_byte_limit'):m.import_output(self.root,{'run_id':rid})

    def test_dynamic_and_long_directory_media_import(self):
        for platform,folder in [('dy','douyin'),('ks','kuaishou'),('wb','weibo'),('bili','bili')]:
            with self.subTest(platform=platform):
                rid=str(uuid.uuid4());run=self.root/'runs'/rid
                jsonl=run/'output'/folder/'jsonl';jsonl.mkdir(parents=True)
                media=run/'output'/folder/'media';media.mkdir()
                (media/'sample.mp4').write_bytes(b'fixture bytes, format not verified')
                m.write(run/'manifest.json',{'run_id':rid,'request':{'platform':platform},'source':{}})
                m.write(run/'status.json',{'state':'completed'})
                if platform=='bili': (jsonl/'creator_dynamics_today.jsonl').write_text(json.dumps({'dynamic_id':'123','text':'already saved dynamic'})+'\n')
                words=run/'output'/folder/'words';words.mkdir()
                (words/'detail_comments_today_word_freq.json').write_text('{"fixture":1}')
                result=m.import_output(self.root,{'run_id':rid})
                self.assertEqual(result['summary']['media_files'],1)
                if platform=='bili': self.assertEqual(result['summary']['dynamics'],1)
                self.assertEqual(result['media'][0]['status'],'downloaded_by_external_executor')
                self.assertEqual(result['artifacts'][0]['kind'],'word_frequency')
                self.assertEqual(result['artifacts'][0]['source_kind'],'derived_local')
                with open(words/'oversized_word_cloud.png','wb') as too_large: too_large.truncate(26214401)
                with self.assertRaisesRegex(m.BridgeError,'wordcloud_artifact_limit'): m.import_output(self.root,{'run_id':rid})
        capability=m.capabilities(self.mc)
        self.assertEqual(capability['execution_limits']['session_concurrency'],1)
        self.assertTrue(all(p['live_verified'] is False for p in capability['platforms']))
        feature=next(p for p in capability['platforms'] if p['id']=='bili')['platform_features']
        self.assertEqual(next(f for f in feature if f['id']=='creator_relations')['support_state'],'unsupported')

class InstalledCLI(unittest.TestCase):
    @unittest.skipUnless(MC.exists(),'external executor not installed')
    def test_installed_jsonl_writer_directory_contract(self):
        sources={'xhs':('xhs','XhsJsonlStoreImplement'),'dy':('douyin','DouyinJsonlStoreImplement'),'ks':('kuaishou','KuaishouJsonlStoreImplement'),'bili':('bilibili','BiliJsonlStoreImplement'),'wb':('weibo','WeiboJsonlStoreImplement'),'tieba':('tieba','TieBaJsonlStoreImplement'),'zhihu':('zhihu','ZhihuJsonlStoreImplement')}
        for platform,(folder,class_name) in sources.items():
            tree=ast.parse((MC/'store'/folder/'_store_impl.py').read_text())
            cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==class_name)
            names={k.value.value for n in ast.walk(cls) if isinstance(n,ast.Call) for k in n.keywords if k.arg=='platform' and isinstance(k.value,ast.Constant)}
            self.assertEqual(names,{m.JSONL_DIRS.get(platform,(platform,))[0]},platform)

    @unittest.skipUnless(PYTHON.exists(),'external executor not installed')
    def test_actual_21_cli_bindings_without_network(self):
        with tempfile.TemporaryDirectory(prefix='crowd-mc-cli-') as temp:
            run=Path(temp)
            (run/'libs').symlink_to(MC/'libs',target_is_directory=True)
            (run/'media_platform/kuaishou').mkdir(parents=True)
            (run/'media_platform/kuaishou/graphql').symlink_to(MC/'media_platform/kuaishou/graphql',target_is_directory=True)
            code='''import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2])
import mc_runner as bridge,config,cmd_arg,main
async def check():
 out=[]
 for p in bridge.PLATFORMS:
  for mode in ['search','detail','creator']:
   target='abc123' if mode=='search' else {'xhs':'66fad51c000000001b0224b8','dy':'123' if mode=='detail' else 'fixture','ks':'fixture','bili':'BV1Vs411j7cX' if mode=='detail' else '123','wb':'123','tieba':'123' if mode=='detail' else 'fixture','zhihu':'https://www.zhihu.com/zvideo/123' if mode=='detail' else 'fixture'}[p]
   request=bridge.validate({'platform':p,'mode':mode,'targets':[target],'purpose':'noncommercial_research','comments':True,'replies':True,'media':p in bridge.MEDIA})
   if p=='zhihu' and mode=='creator': config.ZHIHU_CREATOR_URL_LIST=request['targets']
   await cmd_arg.parse_cmd(bridge.argv_for(request,Path.cwd()/'output'))
   assert config.PLATFORM==p and config.CRAWLER_TYPE==mode
   assert config.ENABLE_GET_COMMENTS and config.ENABLE_GET_SUB_COMMENTS
   assert config.ENABLE_GET_MEDIA==(p in bridge.NATIVE_MEDIA)
   assert config.MAX_CONCURRENCY_NUM==1
   name=main.CrawlerFactory.CRAWLERS[p].__name__
   assert hasattr(main.CrawlerFactory.CRAWLERS[p],'start')
   if mode=='creator':
    attr={'xhs':'XHS_CREATOR_ID_LIST','dy':'DY_CREATOR_ID_LIST','ks':'KS_CREATOR_ID_LIST','bili':'BILI_CREATOR_ID_LIST','wb':'WEIBO_CREATOR_ID_LIST','tieba':'TIEBA_CREATOR_URL_LIST','zhihu':'ZHIHU_CREATOR_URL_LIST'}[p]
    assert bridge.execution_target(p,mode,target) in getattr(config,attr)[0]
   out.append({'platform':p,'mode':mode,'class':name})
 for target,expected in [('https://weibo.com/7798269830/5264010640887796','5264010640887796'),('https://m.weibo.cn/detail/5264010640887796','5264010640887796'),('https://m.weibo.cn/status/AbC123','AbC123'),('AbC123','AbC123')]:
  request=bridge.validate({'platform':'wb','mode':'detail','targets':[target],'purpose':'noncommercial_research'})
  await cmd_arg.parse_cmd(bridge.argv_for(request,Path.cwd()/'output'))
  assert config.WEIBO_SPECIFIED_ID_LIST==[expected]
 request=bridge.validate({'platform':'bili','mode':'creator','targets':['123'],'max_items':3,'start_page':4,'interval_seconds':0.5,'platform_options':{'creator_sections':['dynamics'],'quality':64},'purpose':'noncommercial_research'})
 bridge.configure_executor(config,request)
 await cmd_arg.parse_cmd(bridge.argv_for(request,Path.cwd()/'output'))
 assert config.START_PAGE==4 and config.CRAWLER_MAX_SLEEP_SEC==0.5 and config.BILI_QN==64
 assert config.CREATOR_MODE is False and config.CRAWLER_MAX_DYNAMICS_COUNT_SINGLENOTES==3
 crawler=main.CrawlerFactory.CRAWLERS['bili']
 assert hasattr(crawler,'get_creator_videos') and hasattr(crawler,'get_all_creator_details') and hasattr(crawler,'get_dynamics')
 print(json.dumps(out))
asyncio.run(check())
'''
            proc=subprocess.run([str(PYTHON),'-B','-c',code,str(MC),str(HERE)],cwd=run,capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',MPLCONFIGDIR=str(run/'cache/matplotlib'),XDG_CACHE_HOME=str(run/'cache')),timeout=90)
            self.assertEqual(proc.returncode,0,proc.stderr[-2000:])
            rows=json.loads(proc.stdout)
            self.assertEqual(len(rows),21)
            self.assertEqual(len({r['class'] for r in rows}),7)

if __name__=='__main__': unittest.main(verbosity=2)
