import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tieba_media
import zhihu_media as media


def response(content, content_id='123', kind='answer'):
    data = {'initialState': {'entities': {media.TYPES[kind]: {
        content_id: {'id': content_id, 'content': content, 'author': {'avatar_url': 'https://pic1.zhimg.com/avatar.jpg'}}},
        'users': {'u': {'avatar_url': 'https://pic1.zhimg.com/avatar-user.jpg'}}}}}
    return '<img src="https://pic1.zhimg.com/outside-avatar.jpg"><script id="js-initialData">' + json.dumps(data) + '</script>'


class Response:
    status_code = 200
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def aiter_bytes(self, size): yield b'\xff\xd8\xff' + b'x' * 20


class Client:
    def __init__(self): self.requests = []
    def stream(self, method, url, headers):
        self.requests.append((method, url, headers)); return Response()


class Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name).resolve() / 'output'
        self.data = response('<img data-original="//pic2.zhimg.com/body.jpg"><img class="Avatar" src="https://pic1.zhimg.com/avatar.jpg"><div class="Avatar"><img src="https://pic2.zhimg.com/nested-avatar.jpg"></div>')

    def test_body_scope_exact_entity_id_and_asset_bound(self):
        assets = media.extract_assets(self.data, '123', 'answer')
        self.assertEqual(assets, [{'url': 'https://pic2.zhimg.com/body.jpg', 'source_post_id': '123', 'source_content_type': 'answer'}])
        with self.assertRaisesRegex(ValueError, 'target_entity_missing'):
            media.extract_assets(self.data, '999', 'answer')
        html = response(''.join('<img src="https://pic1.zhimg.com/%s.jpg">' % i for i in range(20)))
        self.assertEqual(len(media.extract_assets(html, '123', 'answer')), 3)

    def test_article_and_embedded_video_only_allowed_urls(self):
        html = response('<video><source src="https://vdn.vzuu.com/body.mp4"></video>', kind='article')
        self.assertEqual(media.extract_assets(html, '123', 'article')[0]['url'], 'https://vdn.vzuu.com/body.mp4')
        for url in ('https://127.0.0.1/a.jpg', 'https://pic1.zhimg.com.evil/a.jpg',
                    'https://user:pass@pic1.zhimg.com/a', 'https://pic1.zhimg.com/a?token=private',
                    'https://vdn.vzuu.com:443/a.mp4', 'javascript:alert(1)', 'blob:https://www.zhihu.com/a'):
            self.assertIsNone(media.asset_url(url))

    def test_malformed_missing_and_oversized_initial_data(self):
        for data in ('<html></html>', '<script id="js-initialData">bad json</script>',
                     {'initialState': []}, {'initialState': {'entities': []}}):
            with self.assertRaises(ValueError):
                media.extract_assets(data, '123', 'answer')
        with patch.object(media, 'MAX_HTML', 10):
            with self.assertRaisesRegex(ValueError, 'over_limit'):
                media.extract_assets(self.data, '123', 'answer')

    def test_selected_video_playlist_official_shape_preserves_identity_and_allowlist(self):
        data = {'initialState': {'entities': {'zvideos': {
            '123': {'id': '123', 'video': {'playlist': {
                'hd': {'url': 'https://vdn.vzuu.com/selected.mp4'},
                'sd': {'play_url': 'https://vdn.vzuu.com/selected.mp4'},
                'ld': {'play_url': 'https://video.zhihu.com/low.mp4'},
                'foreign': {'url': 'https://evil.invalid/private.mp4'},
                'secret': {'url': 'https://vdn.vzuu.com/a?token=private'},
                'bad': 'not a format'}}},
            '456': {'id': '456', 'video': {'playlist': {
                'hd': {'url': 'https://vdn.vzuu.com/other.mp4'}}}}}}}}
        self.assertEqual(media.extract_assets(data, '123', 'zvideo'), [
            {'url': 'https://vdn.vzuu.com/selected.mp4', 'source_post_id': '123', 'source_content_type': 'zvideo'}])
        playlist = data['initialState']['entities']['zvideos']['123']['video']['playlist']
        del playlist['hd']; del playlist['sd']
        self.assertEqual(media.extract_assets(data, '123', 'zvideo')[0]['url'], 'https://video.zhihu.com/low.mp4')
        del playlist['ld']
        self.assertEqual(media.extract_assets(data, '123', 'zvideo'), [])
        data['initialState']['entities']['zvideos']['123']['video']['playlist'] = []
        self.assertEqual(media.extract_assets(data, '123', 'zvideo'), [])

    async def test_same_response_hook_preserves_native_return_and_skips_other_requests(self):
        data = self.data
        class Native:
            async def get(self, uri, params=None, **kwargs): return data
        calls = []
        async def download(*args): calls.append(args)
        with patch.object(media, 'download_assets', download):
            media.install_hook(Native, self.output)
            native = Native()
            self.assertIs(await native.get('/question/456/answer/123', return_response=True), data)
            await native.get('/question/456/answer/123', return_response=True)
            await native.get('/api/v4/me', return_response=True)
            await native.get('/p/124', return_response=False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1:3], ('123', 'answer'))

    async def test_downloader_namespace_bytes_hash_no_cookie_and_manifest(self):
        client = Client()
        result = await media.download_assets(self.data, '123', 'answer', self.output, client)
        row = result['downloaded'][0]; path = Path(row['path'])
        self.assertEqual(path.parent, self.output / 'zhihu/media/123/answer')
        self.assertEqual(row['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(set(client.requests[0][2]), {'Referer'})
        self.assertFalse(result['credentials_used'])
        self.assertEqual(json.loads((path.parent / 'assets.json').read_text())['downloaded'], result['downloaded'])

    async def test_limits_symlink_hardlink_preservation_and_budget_exit(self):
        with patch.object(tieba_media, 'MAX_FILE', 10):
            result = await media.download_assets(self.data, '123', 'answer', self.output, Client())
        self.assertEqual(result['downloaded'], []); self.assertEqual(result['errors'], ['zhihu_media_size_limit'])
        self.assertFalse(list(self.output.glob('**/.part-*')))
        directory = self.output / 'zhihu/media/456/answer'; directory.mkdir(parents=True)
        victim = Path(self.temp.name) / 'original'; victim.write_text('original unchanged')
        os.link(victim, directory / 'assets.json')
        await media.download_assets(response('', '456'), '456', 'answer', self.output, Client())
        self.assertEqual(victim.read_text(), 'original unchanged')
        linked = self.output / 'zhihu/media/789'; linked.symlink_to(Path(self.temp.name), target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            await media.download_assets(response('', '789'), '789', 'answer', self.output, Client())
        class BudgetExit:
            def stream(self, *args, **kwargs): raise SystemExit(73)
        with self.assertRaises(SystemExit) as error:
            await media.download_assets(response('<img src="https://pic1.zhimg.com/body.jpg">', '999'), '999', 'answer', self.output, BudgetExit())
        self.assertEqual(error.exception.code, 73)

    async def test_bad_detail_html_is_persisted_failure_not_media_support_claim(self):
        result = await media.download_assets('<html>login required</html>', '123', 'answer', self.output, Client())
        self.assertEqual(result['downloaded'], [])
        self.assertEqual(result['errors'], ['zhihu_initial_data_missing'])
        self.assertTrue((self.output / 'zhihu/media/123/answer/assets.json').is_file())

    async def test_search_creator_same_json_body_and_numeric_kind_collision_isolated(self):
        answer = {'id':'123', 'type':'answer', 'content':'<img src="https://pic1.zhimg.com/a.jpg">'}
        article = {'id':'123', 'type':'article', 'content':'<img src="https://pic1.zhimg.com/b.jpg">'}
        data = {'data':[{'type':'search_result','object':answer}, {'type':'search_result','object':article},
                        {'type':'search_result','object':{'id':'456','type':'answer','author':{'avatar_url':'https://pic1.zhimg.com/avatar.jpg'}}}]}
        class Native:
            async def get(self, uri, params=None, **kwargs):return data
        calls = []
        async def download(response, identity, kind, output):
            calls.append((identity, kind, media.extract_assets(response, identity, kind)))
        with patch.object(media, 'download_assets', download):
            media.install_hook(Native, self.output)
            self.assertIs(await Native().get('/api/v4/search_v3'), data)
        self.assertEqual([(row[0],row[1]) for row in calls], [('123','answer'),('123','article')])
        first = await media.download_assets(response(answer['content']), '123','answer',self.output,Client())
        second = await media.download_assets(response(article['content'],kind='article'), '123','article',self.output,Client())
        self.assertEqual(len(first['downloaded']),1);self.assertEqual(len(second['downloaded']),1)
        self.assertNotEqual(first['downloaded'][0]['path'],second['downloaded'][0]['path'])
        self.assertTrue(Path(first['downloaded'][0]['path']).is_file())


if __name__ == '__main__': unittest.main()
