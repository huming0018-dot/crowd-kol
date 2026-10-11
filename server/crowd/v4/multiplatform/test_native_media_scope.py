import asyncio
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from native_media_scope import (install_hook, NATIVE_VIDEO_MEDIA_ACTIVE,
                                NATIVE_VIDEO_MEDIA_BYTES, response_limit,select_douyin_stream)


class SingleLimit(SystemExit):
    pass


class NativeMediaScopeTests(unittest.TestCase):
    def rendition(self,size,rate,url='https://v3-web.douyinvod.com/video.mp4?native_signature=PRIVATE'):
        return {'bit_rate':rate,'play_addr':{'data_size':size,'url_list':[url]}}

    def test_select_native_complete_low_rendition_without_mutating_original(self):
        high=self.rendition(90*1024*1024,4000000);low=self.rendition(20*1024*1024,700000)
        source={'aweme_id':'123','desc':'original body','video':{'duration':120000,
                'play_addr_h264':high['play_addr'],'bit_rate':[high,low],
                'cover':{'url_list':['https://example.invalid/original-cover.jpg']}}}
        before=json.dumps(source,sort_keys=True);selected,info=select_douyin_stream(source)
        self.assertEqual(selected['video']['play_addr_h264'],low['play_addr'])
        self.assertEqual(selected['video']['cover'],source['video']['cover'])
        self.assertEqual(selected['desc'],'original body');self.assertEqual(json.dumps(source,sort_keys=True),before)
        self.assertEqual(info['reported_bytes'],20*1024*1024);self.assertEqual(info['fitting_candidate_count'],1)
        self.assertNotIn('PRIVATE',json.dumps(info));self.assertNotIn('url',json.dumps(info))

    def test_selector_bounds_malformed_data_all_large_and_unknown_size(self):
        large=self.rendition(NATIVE_VIDEO_MEDIA_BYTES+1,900000)
        source={'aweme_id':'123','video':{'play_addr_h264':large['play_addr'],'bit_rate':[large]}}
        selected,info=select_douyin_stream(source);self.assertIs(selected,source)
        self.assertEqual(info['selection_status'],'no_fitting_reported_rendition')
        source['video']['bit_rate']=[self.rendition(None,800000),self.rendition(None,500000)]
        selected,info=select_douyin_stream(source);self.assertEqual(info['reported_bitrate'],500000)
        self.assertIsNone(info['reported_bytes'])
        for invalid in ('http://v3-web.douyinvod.com/video','https://127.0.0.1/video',
                        'https://private.invalid/video','https://PRIVATE@v3-web.douyinvod.com/video',
                        'https://v3-web.douyinvod.com:444/video',{},1,None):
            candidate=self.rendition(1,500000,invalid)
            selected,info=select_douyin_stream({'video':{'bit_rate':[candidate]}})
            self.assertEqual(info['candidate_count'],0)
        selected,info=select_douyin_stream({'video':{'bit_rate':[self.rendition(1,500000)]*1000}})
        self.assertEqual(info['candidate_count'],32)
        for invalid in [None,[],{'video':None},{'images':[{}],'video':{}}]:
            self.assertIs(select_douyin_stream(invalid)[0],invalid);self.assertIsNone(select_douyin_stream(invalid)[1])

    def test_actual_hook_passes_selected_detail_once_and_keeps_other_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'output';output.mkdir();received=[]
            def read(path):return json.loads(path.read_text())
            def write(path,value):path.write_text(json.dumps(value))
            class Crawler:
                async def download_media(self,aweme_item):received.append(aweme_item)
            low=self.rendition(1234,1000);source={'aweme_id':'123','video':{'bit_rate':[low]}}
            original=json.dumps(source)
            install_hook(Crawler,'dy',output,SingleLimit,read,write)
            asyncio.run(Crawler().download_media(aweme_item=source))
            asyncio.run(Crawler().download_media(source))
            self.assertEqual(len(received),2);self.assertEqual(received[0]['video']['play_addr'],low['play_addr'])
            self.assertEqual(received[1]['video']['play_addr'],low['play_addr'])
            self.assertEqual(json.dumps(source),original)
            self.assertEqual(read(output.parent/'phase.json')['media_video_selection']['reported_bytes'],1234)
            self.assertFalse(NATIVE_VIDEO_MEDIA_ACTIVE.get())
            class Other:
                async def download_media(self,aweme_item):received.append(aweme_item)
            install_hook(Other,'ks',output,SingleLimit,read,write)
            asyncio.run(Other().download_media(source));self.assertIs(received[-1],source)

    def test_media_scope_keeps_comments_and_previous_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            folder = output / 'dy/media'
            folder.mkdir(parents=True)
            (folder / 'old.part').write_bytes(b'old')
            events = []

            class Crawler:
                failure = SingleLimit(76)

                async def download_media(self):
                    events.append(response_limit('dy'))
                    (folder / 'new.part').write_bytes(b'partial')
                    raise self.failure

                async def comments(self):
                    events.append('comments')

            def read(path):
                return json.loads(path.read_text())

            def write(path, value):
                path.write_text(json.dumps(value))

            install_hook(Crawler, 'dy', output, SingleLimit, read, write)

            async def run():
                await Crawler().download_media()
                await Crawler().comments()

            asyncio.run(run())
            self.assertEqual(events, [NATIVE_VIDEO_MEDIA_BYTES, 'comments'])
            self.assertEqual((folder / 'old.part').read_bytes(), b'old')
            self.assertFalse((folder / 'new.part').exists())
            self.assertEqual(read(output.parent / 'phase.json')['media_reason'],
                             'single_response_byte_limit')
            self.assertFalse(NATIVE_VIDEO_MEDIA_ACTIVE.get())
            for code in (73, 76, 77):
                Crawler.failure = SystemExit(code)
                with self.assertRaises(SystemExit) as stopped:
                    asyncio.run(run())
                self.assertEqual(stopped.exception.code, code)
                self.assertFalse(NATIVE_VIDEO_MEDIA_ACTIVE.get())

    def test_response_budget_is_local_to_native_media_context(self):
        async def run():
            entered = asyncio.Event()
            finish = asyncio.Event()

            async def download():
                token = NATIVE_VIDEO_MEDIA_ACTIVE.set(True)
                try:
                    entered.set()
                    await finish.wait()
                    return response_limit('ks')
                finally:
                    NATIVE_VIDEO_MEDIA_ACTIVE.reset(token)

            task = asyncio.create_task(download())
            await entered.wait()
            self.assertEqual(response_limit('ks'), 25 * 1024 * 1024)
            finish.set()
            self.assertEqual(await task, 64 * 1024 * 1024)
            self.assertEqual(response_limit('ks'), 25 * 1024 * 1024)

        asyncio.run(run())
        token = NATIVE_VIDEO_MEDIA_ACTIVE.set(True)
        try:
            for platform in ('xhs', 'wb', 'bili', 'tieba', 'zhihu'):
                self.assertEqual(response_limit(platform), 25 * 1024 * 1024)
        finally:
            NATIVE_VIDEO_MEDIA_ACTIVE.reset(token)

    def test_media_import_accepts_native_video_without_widening_other_platforms(self):
        import mc_runner
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for platform, enabled in [('dy', True), ('ks', True), ('dy', False), ('wb', True)]:
                run_id = str(uuid.uuid4())
                run = root / 'runs' / run_id
                folder = run / 'output' / platform / 'media' / '123'
                folder.mkdir(parents=True)
                media = folder / 'video.mp4'
                with media.open('wb') as stream:
                    stream.truncate(25 * 1024 * 1024 + 1)
                mc_runner.write(run / 'manifest.json', {'run_id': run_id,
                                'request': {'platform': platform, 'media': enabled}, 'source': {}})
                mc_runner.write(run / 'status.json', {'state': 'completed'})
                if platform in ('dy', 'ks') and enabled:
                    result = mc_runner.import_output(root, {'run_id': run_id})
                    self.assertEqual(result['media'][0]['bytes'], 25 * 1024 * 1024 + 1)
                    with media.open('wb') as stream:
                        stream.truncate(64 * 1024 * 1024 + 1)
                with self.assertRaisesRegex(mc_runner.BridgeError, 'media_import_byte_limit'):
                    mc_runner.import_output(root, {'run_id': run_id})


if __name__ == '__main__':
    unittest.main()
