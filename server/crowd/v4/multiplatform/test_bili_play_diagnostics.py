"""Actual runner hook, fake native SDK only; no source requests."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location('bili_diagnostic_runner',HERE/'mc_runner.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
import bili_audio


class PlayDiagnosticsTest(unittest.TestCase):
    def exercise(self,response=None,error=None,adapter=None,view=None):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        work=Path(temporary.name)
        m.write(work/'phase.json',{'api_attempts':5,'phase':'comments'})
        client=SimpleNamespace(get_video_play_url=AsyncMock(return_value=response,side_effect=error))
        class Crawler:
            bili_client=client
            async def download_media(self,*args):raise AssertionError('native download must not run')
            async def get_video_play_url_task(self,*args,**kwargs):raise AssertionError('error-swallowing wrapper must not run')
        native=SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'bili':Crawler}))
        p={'platform':'bili','media':True,'mode':'detail','platform_options':{'long_audio':True}}
        module=SimpleNamespace(DASH_FNVAL=16)
        downloader=adapter or AsyncMock(return_value={'status':'unavailable','reason':'dash_audio_unavailable'})
        async def run_media():
            await Crawler().download_media({'View':view if view is not None else {'aid':123,'cid':456,'bvid':'BV1popx6zEe1','duration':60}},asyncio.Semaphore(1))
        with patch.dict(sys.modules,{'media_platform.bilibili.media':module}),patch.object(m.Path,'cwd',return_value=work),patch.object(bili_audio,'download_audio',downloader):
            m.configure_platform_hooks(native,p)
            asyncio.run(run_media())
        return m.read(work/'phase.json'),client,downloader

    def test_request_error_cannot_be_reported_as_audio_absence(self):
        for error in (RuntimeError('private signed URL'),KeyError('private response'),OSError('private transport')):
            with self.subTest(error=type(error).__name__):
                phase,client,download=self.exercise(error=error)
                self.assertEqual(phase['media_status'],'failed')
                self.assertEqual(phase['media_reason'],'audio_play_request_failed')
                self.assertEqual(phase['media_play_response']['status'],'request_failed')
                client.get_video_play_url.assert_awaited_once_with(aid=123,cid=456,fnval=16)
                download.assert_not_awaited()
                self.assertNotIn('private',str(phase))

    def test_non_mapping_response_is_invalid_not_audio_absence(self):
        for value in (None,[],True):
            with self.subTest(value=value):
                phase,client,download=self.exercise(response=value)
                self.assertEqual(phase['media_reason'],'audio_play_response_invalid')
                self.assertEqual(phase['media_play_response']['status'],'response_invalid')
                self.assertEqual(client.get_video_play_url.await_count,1)
                download.assert_not_awaited()

    def test_native_success_has_safe_shape_evidence_without_urls(self):
        play={'dash':{'audio':[{'baseUrl':'https://private.invalid/token','bandwidth':123}]},'durl':[{'url':'private'}]}
        phase,client,download=self.exercise(response=play)
        self.assertEqual(phase['media_play_response'],{'status':'native_success','source':'native_bilibili_client','dash_present':True,'audio_list_present':True,'audio_entries':1,'durl_present':True})
        self.assertNotIn('private',str(phase));self.assertNotIn('baseUrl',str(phase))
        self.assertEqual(download.await_args.args[0],play)
        self.assertEqual(client.get_video_play_url.await_count,1)
        self.assertEqual(phase['api_attempts'],5);self.assertEqual(phase['phase'],'comments')

    def test_successful_empty_or_durl_response_is_unavailable_without_fallback(self):
        for play in ({},{'durl':[{'url':'https://private.invalid/token'}]},{'dash':{'audio':[]}}):
            with self.subTest(play=play):
                async def actual_selector(data,content_id,output_dir,duration):
                    try:bili_audio.select_audio(data,duration)
                    except ValueError as exc:return {'status':'unavailable','reason':str(exc)}
                    raise AssertionError('unexpected audio')
                phase,client,_=self.exercise(response=play,adapter=actual_selector)
                self.assertEqual(phase['media_reason'],'dash_audio_unavailable')
                self.assertEqual(phase['media_play_response']['status'],'native_success')
                self.assertEqual(client.get_video_play_url.await_count,1)

    def test_adapter_failure_is_distinct_from_request_failure(self):
        phase,_,_=self.exercise(response={'dash':{}},adapter=AsyncMock(side_effect=ValueError('private URL')))
        self.assertEqual(phase['media_reason'],'audio_adapter_failed')
        self.assertEqual(phase['media_play_response']['status'],'native_success')
        self.assertNotIn('private',str(phase))

    def test_request_budget_exit_propagates(self):
        for code in (73,76):
            with self.subTest(code=code):
                with self.assertRaises(SystemExit) as caught:self.exercise(error=SystemExit(code))
                self.assertEqual(caught.exception.code,code)

    def test_single_response_limit_retains_outer_limited_classification(self):
        phase,_,download=self.exercise(error=m.SingleResponseLimit())
        self.assertEqual(phase['media_status'],'limited')
        self.assertEqual(phase['media_reason'],'single_response_byte_limit')
        download.assert_not_awaited()

    def test_adapter_budget_exit_propagates(self):
        with self.assertRaises(SystemExit) as caught:self.exercise(response={},adapter=AsyncMock(side_effect=SystemExit(73)))
        self.assertEqual(caught.exception.code,73)

    def test_missing_identity_does_not_request(self):
        phase,client,download=self.exercise(view={'aid':123})
        self.assertEqual(phase['media_reason'],'audio_identity_missing')
        self.assertEqual(phase['media_play_response']['status'],'not_requested')
        client.get_video_play_url.assert_not_awaited();download.assert_not_awaited()


if __name__=='__main__':unittest.main()
