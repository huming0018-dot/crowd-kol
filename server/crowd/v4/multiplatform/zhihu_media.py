"""Observe body assets in the same native Zhihu HTML response; no extra detail fetch."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import tieba_media

HOSTS = {'pic1.zhimg.com', 'pic2.zhimg.com', 'pic3.zhimg.com', 'pic4.zhimg.com',
         'pica.zhimg.com', 'picb.zhimg.com', 'picx.zhimg.com', 'picd.zhimg.com',
         'vdn.vzuu.com', 'video.zhihu.com'}
TYPES = {'answer': 'answers', 'article': 'articles', 'zvideo': 'zvideos'}
MAX_HTML = 2_000_000


def asset_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    if value.startswith('//'):
        value = 'https:' + value
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or parsed.hostname not in HOSTS
                or parsed.username or parsed.password or parsed.port or parsed.fragment):
            return None
        if any(re.search(r'(?i)(token|cookie|authorization|credential|session|password|secret|x-amz)', key)
               for key, _value in parse_qsl(parsed.query)):
            return None
        return urlunsplit(('https', parsed.netloc, parsed.path, parsed.query, ''))
    except ValueError:
        return None


class InitialData(HTMLParser):
    def __init__(self):
        super().__init__(); self.collect = False; self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.collect = dict(attrs).get('id') == 'js-initialData'

    def handle_endtag(self, tag):
        if tag == 'script':
            self.collect = False

    def handle_data(self, data):
        if self.collect:
            self.parts.append(data)


class BodyAssets(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls = []; self.stack = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        blocked = (any(item[1] for item in self.stack) or 'avatar' in attrs.get('class', '').lower()
                   or '头像' in attrs.get('alt', ''))
        if tag not in ('img', 'br', 'hr', 'meta', 'input', 'source', 'link', 'area', 'embed', 'param', 'track', 'wbr'):
            self.stack.append((tag, blocked))
        if tag not in ('img', 'video', 'source') or blocked:
            return
        for key in ('data-original', 'data-actualsrc', 'data-src', 'src'):
            value = asset_url(attrs.get(key))
            if value:
                if value not in self.urls:
                    self.urls.append(value)
                break

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def extract_assets(data, content_id, content_type):
    if content_type not in TYPES or not re.fullmatch('[0-9]{1,30}', str(content_id)):
        raise ValueError('zhihu_content_identity_invalid')
    if isinstance(data, str):
        if len(data.encode('utf8')) > MAX_HTML:
            raise ValueError('zhihu_html_over_limit')
        parser = InitialData(); parser.feed(data)
        if not parser.parts:
            raise ValueError('zhihu_initial_data_missing')
        try:
            data = json.loads(''.join(parser.parts))
        except (ValueError, TypeError):
            raise ValueError('zhihu_initial_data_invalid') from None
    if not isinstance(data, dict):
        raise ValueError('zhihu_initial_data_invalid')
    state = data.get('initialState')
    if not isinstance(state, dict):
        raise ValueError('zhihu_initial_data_invalid')
    entities = state.get('entities', {})
    rows = entities.get(TYPES[content_type], {}) if isinstance(entities, dict) else {}
    entity = rows.get(str(content_id)) if isinstance(rows, dict) else None
    if not isinstance(entity, dict) or str(entity.get('id', content_id)) != str(content_id):
        raise ValueError('zhihu_target_entity_missing')
    content = entity.get('content', '')
    if not isinstance(content, str) or len(content.encode('utf8')) > MAX_HTML:
        raise ValueError('zhihu_body_html_invalid')
    parser = BodyAssets(); parser.feed(content)
    urls = parser.urls
    # These keys belong only to the selected entity's video, never author/user data.
    video = entity.get('video') or {}
    if isinstance(video, dict):
        for key in ('play_url', 'playUrl', 'url'):
            value = asset_url(video.get(key))
            if value and value not in urls:
                urls.append(value)
        # Official zvideo formats live in the selected entity's video.playlist.
        playlist = video.get('playlist') if not any(asset_url(video.get(k)) for k in ('play_url', 'playUrl', 'url')) else None
        for row in list(playlist.values())[:100] if isinstance(playlist, dict) else []:
            if not isinstance(row, dict):
                continue
            value = asset_url(row.get('url')) or asset_url(row.get('play_url'))
            if value:
                if value not in urls:
                    urls.append(value)
                break  # One rendition, not three copies of the same video.
    return [{'url': value, 'source_post_id': str(content_id), 'source_content_type': content_type}
            for value in urls[:tieba_media.MAX_ASSETS]]


async def download_assets(data, content_id, content_type, output_dir, client=None):
    return await tieba_media.download_assets(data, str(content_id), output_dir, client,
            platform='zhihu', extractor=lambda value: extract_assets(value, str(content_id), content_type),
            content_type=content_type)


def install_hook(client_class, output_dir):
    original = client_class.get
    seen = set()

    async def wrapped(self, uri, params=None, **kwargs):
        data = await original(self, uri, params, **kwargs)
        target = None
        if kwargs.get('return_response') is True and isinstance(uri, str):
            answer = re.fullmatch(r'/question/[0-9]{1,30}/answer/([0-9]{1,30})', uri)
            article = re.fullmatch(r'/p/([0-9]{1,30})', uri)
            video = re.fullmatch(r'/zvideo/([0-9]{1,30})', uri)
            for kind, match in (('answer', answer), ('article', article), ('zvideo', video)):
                if match:
                    target = (kind, match.group(1)); break
        observed = []
        if target is not None:
            observed.append((target, data))
        elif (isinstance(data, dict) and isinstance(uri, str)
              and (uri == '/api/v4/search_v3' or re.fullmatch(r'/api/v4/members/[A-Za-z0-9_-]{1,100}/(?:answers|articles|zvideos)', uri))):
            entries = data.get('data')
            for entry in entries[:100] if isinstance(entries, list) else []:
                if not isinstance(entry, dict):
                    continue
                entity = entry.get('object', entry)
                if not isinstance(entity, dict):
                    continue
                kind, identity = entity.get('type'), str(entity.get('id', ''))
                if (kind not in TYPES or not re.fullmatch('[0-9]{1,30}', identity)
                        or not (isinstance(entity.get('content'), str) or isinstance(entity.get('video'), dict))):
                    continue
                observed.append(((kind, identity), {'initialState': {'entities': {TYPES[kind]: {identity: entity}}}}))
        for target, response in observed:
            if target not in seen:
                seen.add(target)
                await download_assets(response, target[1], target[0], Path(output_dir))
        return data

    client_class.get = wrapped
