import asyncio
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from native_media_scope import (install_hook, NATIVE_VIDEO_MEDIA_ACTIVE,
                                NATIVE_VIDEO_MEDIA_BYTES, response_limit)


class SingleLimit(SystemExit):
    pass


class NativeMediaScopeTests(unittest.TestCase):
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
