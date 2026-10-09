#!/usr/bin/env python3
"""No source-site access. Fake process lifecycle + real installed CLI wiring."""
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
        (self.mc/'config.py').write_text('')
        (self.mc/'playwright/__init__.py').write_text('')
        (self.mc/'playwright/async_api.py').write_text('class BrowserType:\n async def launch(self,*a,**kw): return None\n async def launch_persistent_context(self,*a,**kw): return None\n')
        (self.mc/'.venv/bin/python').symlink_to(PYTHON if PYTHON.exists() else sys.executable)
        (self.mc/'httpx.py').write_text('class Response:\n async def aiter_bytes(self,*a,**kw):\n  for _ in range(30): yield b"x"*1048576\nclass AsyncClient:\n async def send(self,*a,**kw): return {}\nclass Client:\n def send(self,*a,**kw): return {}\n')
        (self.mc/'requests.py').write_text('class Session:\n def send(self,*a,**kw): return {}\nclass sessions:\n Session=Session\n')
        (self.mc/'main.py').write_text('''import asyncio,json,pathlib,sys
import config,httpx
async def main():
 args=dict(zip(sys.argv[1::2],sys.argv[2::2]))
 p=args['--platform']; mode=args['--type']; target=args.get('--keywords',args.get('--specified_id',args.get('--creator_id')))
 assert config.ENABLE_CDP_MODE is False and config.COOKIES==''
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
 out=pathlib.Path(args['--save_data_path'])/p/'jsonl';out.mkdir(parents=True)
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

    def test_validation_and_secrets(self):
        for kwargs,code in [({'platform':[]},'unsupported_platform_or_mode'),({'platform':'no'},'unsupported_platform_or_mode'),({'max_items':2},'upstream_search_minimum_20'),({'platform':'zhihu','media':True},'media_not_supported_by_upstream'),({'replies':True,'comments':False},'replies_require_comments')]:
            p=self.payload();p.update(kwargs)
            self.assertEqual(self.invoke('start',p)['error'],code)
        p=self.payload(mode='detail',target='https://www.xiaohongshu.com/explore/id?access_token=hidden')
        self.assertEqual(self.invoke('start',p)['error'],'credential_target_not_allowed')
        locator=m.validate(self.payload(mode='detail',target='https://www.xiaohongshu.com/explore/id?xsec_token=local&xsec_source=pc_search'))
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

class InstalledCLI(unittest.TestCase):
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
   request=bridge.validate({'platform':p,'mode':mode,'targets':['abc123'],'purpose':'noncommercial_research','comments':True,'replies':True,'media':p in bridge.MEDIA})
   if p=='zhihu' and mode=='creator': config.ZHIHU_CREATOR_URL_LIST=request['targets']
   await cmd_arg.parse_cmd(bridge.argv_for(request,Path.cwd()/'output'))
   assert config.PLATFORM==p and config.CRAWLER_TYPE==mode
   assert config.ENABLE_GET_COMMENTS and config.ENABLE_GET_SUB_COMMENTS
   assert config.ENABLE_GET_MEDIA==(p in bridge.MEDIA)
   assert config.MAX_CONCURRENCY_NUM==1
   name=main.CrawlerFactory.CRAWLERS[p].__name__
   assert hasattr(main.CrawlerFactory.CRAWLERS[p],'start')
   if mode=='creator':
    attr={'xhs':'XHS_CREATOR_ID_LIST','dy':'DY_CREATOR_ID_LIST','ks':'KS_CREATOR_ID_LIST','bili':'BILI_CREATOR_ID_LIST','wb':'WEIBO_CREATOR_ID_LIST','tieba':'TIEBA_CREATOR_URL_LIST','zhihu':'ZHIHU_CREATOR_URL_LIST'}[p]
    assert 'abc123' in getattr(config,attr)[0]
   out.append({'platform':p,'mode':mode,'class':name})
 print(json.dumps(out))
asyncio.run(check())
'''
            proc=subprocess.run([str(PYTHON),'-B','-c',code,str(MC),str(HERE)],cwd=run,capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',MPLCONFIGDIR=str(run/'cache/matplotlib'),XDG_CACHE_HOME=str(run/'cache')),timeout=90)
            self.assertEqual(proc.returncode,0,proc.stderr[-2000:])
            rows=json.loads(proc.stdout)
            self.assertEqual(len(rows),21)
            self.assertEqual(len({r['class'] for r in rows}),7)

if __name__=='__main__': unittest.main(verbosity=2)
