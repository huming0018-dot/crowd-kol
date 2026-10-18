"""Native DASH staging only; no source requests, browser, or model calls."""
import ast
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from types import SimpleNamespace

import mc_runner as m
import native_media_scope as n

SDK=Path('/Users/hubowen/WorkBuddy/2026-10-08-22-53-19/MediaCrawler')
MIB=1024*1024
BVID='BV1popx6zEe1'

class BiliStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.rid=str(uuid.uuid4());self.run=self.root/'runs'/self.rid
        self.output=self.run/'output';self.folder=self.output/'bili/media'/BVID
        self.folder.mkdir(parents=True);self.pid=12345
        self.stage=self.folder/f'.tmp-{self.pid}-12345678';self.stage.mkdir()
        self.request={'platform':'bili','media':True}
        n.save_bilibili_identity({'View':{'aid':123,'cid':456,'bvid':BVID}},self.output,m.read,m.write)
    def tearDown(self):self.temp.cleanup()
    def file(self,path,size):
        path.parent.mkdir(parents=True,exist_ok=True)
        with open(path,'wb') as stream:stream.truncate(size)
    def usage(self,request=None,pid=None):return n.output_byte_usage(self.output,request or self.request,self.pid if pid is None else pid)
    def test_actual_observed_peak_and_complete_cleanup(self):
        self.file(self.stage/'video.m4s',27321399);self.file(self.stage/'audio.m4s',40914354)
        self.file(self.stage/'merged.mp4',66118572);self.file(self.folder/'cover.jpg',134366)
        value=self.usage();self.assertEqual(value['staging_input_bytes'],68235753)
        self.assertGreater(value['total_bytes'],100*MIB);self.assertFalse(value['limited'])
        os.replace(self.stage/'merged.mp4',self.folder/'video.mp4');shutil.rmtree(self.stage)
        value=self.usage();self.assertEqual(value['staging_input_bytes'],0);self.assertFalse(value['limited'])
    def test_actual_worker_does_not_stop_native_peak_but_stops_final_over_limit(self):
        from unittest.mock import Mock,patch
        import browser_session
        self.file(self.stage/'video.m4s',27321399);self.file(self.stage/'audio.m4s',40914354)
        self.file(self.stage/'merged.mp4',66118572)
        for exceed in (False,True):
            if exceed:self.file(self.folder/'outside.bin',100*MIB)
            m.write(self.run/'manifest.json',{'request':{**self.request,'timeout_seconds':180}})
            m.write(self.run/'status.json',{'state':'running','updated_at':0})
            child=Mock(pid=self.pid);child.poll.side_effect=[None,0];child.wait.return_value=0
            fd=os.open(os.devnull,os.O_RDONLY)
            with patch.object(m.subprocess,'Popen',return_value=child),patch.object(m.time,'sleep'),patch.object(browser_session,'terminate_executor') as stop:
                m.worker(self.root,SDK,self.rid,fd)
            state=m.read(self.run/'status.json')
            self.assertEqual(state['state'],'failed' if exceed else 'completed')
            if exceed:stop.assert_called_once_with(self.pid,False);self.assertEqual(state['reason'],'output_byte_limit')
            else:stop.assert_not_called();self.assertEqual(state['reason'],'executor_finished')
    def test_input_final_and_total_boundaries(self):
        (self.output/'bili/media-identities.json').unlink() # No proof, no staging exemption.
        self.file(self.stage/'video.m4s',60*MIB);self.file(self.stage/'audio.m4s',40*MIB)
        self.assertFalse(self.usage()['limited']);self.assertEqual(self.usage()['staging_input_bytes'],0)
        self.file(self.stage/'audio.m4s',40*MIB+1);self.assertTrue(self.usage()['limited'])
    def test_exact_budget_with_metadata_accounted(self):
        metadata=(self.output/'bili/media-identities.json').stat().st_size
        self.file(self.stage/'video.m4s',60*MIB);self.file(self.stage/'audio.m4s',40*MIB)
        self.file(self.stage/'merged.mp4',64*MIB);self.file(self.folder/'other.bin',36*MIB-metadata)
        self.assertEqual(self.usage()['total_bytes'],200*MIB);self.assertFalse(self.usage()['limited'])
        self.file(self.folder/'extra.bin',1);self.assertTrue(self.usage()['limited'])
        (self.folder/'extra.bin').unlink();self.file(self.stage/'audio.m4s',40*MIB+1)
        self.assertTrue(self.usage()['limited'])
        self.file(self.stage/'audio.m4s',40*MIB);self.file(self.stage/'merged.mp4',64*MIB+1)
        with self.assertRaisesRegex(ValueError,'output_byte_limit'):self.usage()
    def test_other_request_pid_directory_and_file_no_exemption(self):
        self.file(self.stage/'video.m4s',60*MIB);self.file(self.stage/'audio.m4s',41*MIB)
        for request in ({'platform':'dy','media':True},{'platform':'bili','media':False},
                        {'platform':'bili','media':True,'platform_options':{'long_audio':True}}):
            self.assertTrue(self.usage(request)['limited']);self.assertEqual(self.usage(request)['staging_input_bytes'],0)
        self.assertEqual(self.usage(pid=999)['staging_input_bytes'],0)
        self.file(self.stage/'unknown.mp4',1);self.assertGreater(self.usage()['final_bytes'],0)
        wrong=self.folder/'.tmp-12345-xyz';self.file(wrong/'video.m4s',1)
        self.assertGreaterEqual(self.usage()['final_bytes'],2)
    def test_symlink_hardlink_and_nested_staging_not_exempt(self):
        external=self.root/'outside';external.write_bytes(b'original')
        link=self.stage/'video.m4s';link.symlink_to(external)
        with self.assertRaisesRegex(ValueError,'unsafe_output_file'):self.usage()
        link.unlink();os.link(external,link)
        with self.assertRaisesRegex(ValueError,'unsafe_output_file'):self.usage()
        link.unlink();self.file(self.stage/'nested/video.m4s',101*MIB)
        self.assertTrue(self.usage()['limited']);self.assertEqual(external.read_bytes(),b'original')
    def prepare_import(self):
        raw=self.output/'bili/jsonl';raw.mkdir();(raw/'detail_contents_fixture.jsonl').write_text(json.dumps({'video_id':'123','title':'native','desc':'body'})+'\n')
        m.write(self.run/'manifest.json',{'run_id':self.rid,'request':self.request,'source':{}})
        m.write(self.run/'status.json',{'run_id':self.rid,'state':'failed'})
    def test_import_excludes_tmp_partial_then_imports_only_final(self):
        self.prepare_import();self.file(self.stage/'merged.mp4',20*MIB)
        self.file(self.folder/'unknown.tmp/partial.mp4',10);self.file(self.folder/'old.part/video.mp4',10)
        self.assertEqual(m.import_output(self.root,{'run_id':self.rid})['media'],[])
        os.replace(self.stage/'merged.mp4',self.folder/'video.mp4');shutil.rmtree(self.stage)
        result=m.import_output(self.root,{'run_id':self.rid});self.assertEqual(len(result['media']),1)
        self.assertEqual(result['media'][0]['content_id'],'123')
        self.assertEqual(result['media'][0]['bytes'],20*MIB)
    def test_legacy_normalized_temporary_asset_rejected_by_cloud_identity(self):
        from media_native import _identity
        self.prepare_import();data=b'\0\0\0\x10ftypisom'+b'x'*100
        final=self.folder/'video.mp4';final.write_bytes(data)
        normalized=m.import_output(self.root,{'run_id':self.rid})
        tmp=self.stage/'merged.mp4';os.replace(final,tmp)
        normalized['media'][0]['path']=str(tmp.relative_to(self.run));m.write(self.run/'normalized.json',normalized)
        before=hashlib.sha256((self.run/'normalized.json').read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'media_native_uncommitted_asset'):_identity(self.run,'123',hashlib.sha256(data).hexdigest(),None)
        self.assertEqual(hashlib.sha256((self.run/'normalized.json').read_bytes()).hexdigest(),before)
    def test_installed_sdk_dash_lifecycle_counts_merge_before_commit(self):
        source=(SDK/'media_downloader/downloader.py').read_text();tree=ast.parse(source)
        node=next(v for v in ast.walk(tree) if isinstance(v,ast.AsyncFunctionDef) and v.name=='_download_dash')
        observed=[]
        async def merge(video,audio,merged):
            self.file(merged,66118572)
            value=self.usage(pid=os.getpid());observed.append(value);self.assertFalse(value['limited'])
        namespace={'os':os,'uuid':uuid,'shutil':shutil,'merge_audio_video':merge,
                   'ensure_within':lambda base,path:path,'logger':SimpleNamespace(info=lambda *a:None,error=lambda *a:None),
                   'redact_url':lambda _:None,'MediaDownloadError':type('MediaDownloadError',(Exception,),{})}
        exec('from __future__ import annotations\n'+ast.unparse(node),namespace)
        async def single(client,item,directory,url,backup,stem,extension):
            path=directory/(stem+extension);self.file(path,27321399 if stem=='video' else 40914354);return path
        owner=SimpleNamespace(base_dir=self.output,_download_single=single,build_path=lambda item,ext:self.folder/('video'+ext))
        item=SimpleNamespace(url='not-requested',backup_urls=(),audio_url='not-requested',audio_backup_urls=())
        result=asyncio.run(namespace['_download_dash'](owner,None,item,self.folder))
        self.assertEqual(result,self.folder/'video.mp4');self.assertEqual(result.stat().st_size,66118572)
        self.assertEqual(len(observed),1);self.assertGreater(observed[0]['total_bytes'],100*MIB)
        self.assertEqual(list(self.folder.glob(f'.tmp-{os.getpid()}-*')),[])
        self.assertFalse(self.usage(pid=os.getpid())['limited'])
    def test_runner_q16_calls_same_native_selector_without_more_requests(self):
        from unittest.mock import Mock,patch
        import sys
        async def original(self,video,semaphore):return native.pick_audio_stream(video)
        class Crawler:download_media=original
        default=Mock(return_value={'id':9,'bandwidth':999,'base_url':'not-used'})
        native=SimpleNamespace(pick_audio_stream=default)
        packages={'media_platform.bilibili':SimpleNamespace(media=native)}
        request={**self.request,'mode':'detail','comments':False,'platform_options':{'quality':16}}
        rows=[{'id':2,'bandwidth':200,'base_url':'private-never-logged'},
              {'id':1,'bandwidth':100,'base_url':'private-never-logged'}]
        with patch.dict(sys.modules,packages),patch.dict(os.environ,{'CROWD_FFMPEG':''}),patch.object(m.Path,'cwd',return_value=self.run):
            m.configure_platform_hooks(SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'bili':Crawler})),request)
            async def run():return await Crawler().download_media({'dash':{'audio':rows}},asyncio.Semaphore(1))
            result=asyncio.run(run())
        self.assertIs(result,rows[1]);default.assert_not_called()
        phase=m.read(self.run/'phase.json');self.assertEqual(phase['media_audio_selection']['bandwidth'],100)
        self.assertNotIn('private',json.dumps(phase));self.assertFalse(n.NATIVE_VIDEO_MEDIA_ACTIVE.get())

if __name__=='__main__':unittest.main()
