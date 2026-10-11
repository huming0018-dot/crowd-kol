"""Discover visible homepage/ranking links, then reuse the installed detail pipeline."""
import re
import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode

SUPPORT = {'homefeed': {'xhs', 'bili', 'dy', 'wb', 'tieba', 'zhihu', 'ks'}, 'trending': {'bili'}}
PAGES = {'xhs': 'https://www.xiaohongshu.com/explore',
         'bili': 'https://www.bilibili.com/',
         'dy': 'https://www.douyin.com/', 'wb': 'https://weibo.com/hot/recommend',
         'tieba': 'https://tieba.baidu.com/', 'zhihu': 'https://www.zhihu.com/',
         'ks': 'https://www.kuaishou.com/?isHome=1',
         'bili_trending': 'https://www.bilibili.com/v/popular/all/'}
SELECTORS = {'xhs': 'a[href*="/explore/"],a[href*="/discovery/item/"]',
             'bili': 'a[href*="/video/BV"]',
             'dy': 'a[href*="/video/"],a[href*="modal_id="]',
             'wb': 'a[href]',
             'tieba': 'a[href*="/p/"]',
             'zhihu': 'a[href*="/answer/"],a[href*="zhuanlan.zhihu.com/p/"],a[href*="/zvideo/"]',
             'ks': 'a[href*="/short-video/"]'}


def select_links(platform, links, limit):
    if platform not in SUPPORT['homefeed'] or not isinstance(links, list) or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('invalid_discovery_request')
    selected, seen = [], set()
    for link in links[:200]:
        if not isinstance(link, str) or len(link) > 1500:
            continue
        try:
            url = urlsplit(urljoin(PAGES[platform], link))
            port = url.port
        except ValueError:
            continue
        if url.scheme != 'https' or url.username or url.password or port or url.fragment:
            continue
        if platform == 'xhs':
            if url.hostname != 'www.xiaohongshu.com':
                continue
            match = re.fullmatch(r'/(?:explore|discovery/item)/([a-f0-9]{24})/?', url.path)
            query = dict(parse_qsl(url.query))
            locator = query.get('xsec_token', '')
            if not match or not re.fullmatch(r'[A-Za-z0-9_=+/-]{1,500}', locator):
                continue
            identity = match[1]
            target = 'https://www.xiaohongshu.com/explore/' + identity + '?' + urlencode({'xsec_token': locator, 'xsec_source': 'pc_feed'})
        elif platform == 'bili':
            if url.hostname not in ('www.bilibili.com', 'bilibili.com'):
                continue
            match = re.fullmatch(r'/video/(BV[A-Za-z0-9]{10})/?', url.path)
            if not match:
                continue
            identity = target = match[1]
        elif platform == 'dy':
            if url.hostname not in ('www.douyin.com', 'douyin.com'):
                continue
            match = re.fullmatch(r'/video/([0-9]{5,30})/?', url.path)
            modal = dict(parse_qsl(url.query)).get('modal_id', '') if url.path == '/' else ''
            identity = match[1] if match else modal
            if not re.fullmatch(r'[0-9]{5,30}', identity):
                continue
            target = identity
        elif platform == 'wb':
            if url.hostname == 'm.weibo.cn':
                match = re.fullmatch(r'/(?:detail|status)/([A-Za-z0-9]{5,30})/?', url.path)
            elif url.hostname in ('weibo.com', 'www.weibo.com'):
                match = re.fullmatch(r'/[0-9]{1,20}/([A-Za-z0-9]{5,30})/?', url.path)
            else:
                continue
            if not match:
                continue
            identity = target = match[1]
        elif platform == 'tieba':
            if url.hostname != 'tieba.baidu.com':
                continue
            match = re.fullmatch(r'/p/([0-9]{5,30})/?', url.path)
            if not match:
                continue
            identity = target = match[1]
        elif platform == 'ks':
            if url.hostname not in ('www.kuaishou.com', 'kuaishou.com'):
                continue
            match = re.fullmatch(r'/short-video/([A-Za-z0-9_-]{5,100})/?', url.path)
            if not match:
                continue
            identity = target = match[1]
        else:  # The native Zhihu detail pipeline requires typed URLs, never bare IDs.
            answer = re.fullmatch(r'/question/([0-9]{1,30})/answer/([0-9]{1,30})/?', url.path)
            article = re.fullmatch(r'/p/([0-9]{1,30})/?', url.path)
            video = re.fullmatch(r'/zvideo/([0-9]{1,30})/?', url.path)
            if url.hostname in ('www.zhihu.com', 'zhihu.com') and answer:
                identity = answer[2]
                target = 'https://www.zhihu.com/question/' + answer[1] + '/answer/' + identity
            elif url.hostname == 'zhuanlan.zhihu.com' and article:
                identity = article[1]
                target = 'https://zhuanlan.zhihu.com/p/' + identity
            elif url.hostname in ('www.zhihu.com', 'zhihu.com') and video:
                identity = video[1]
                target = 'https://www.zhihu.com/zvideo/' + identity
            else:
                continue
        key = (zhihu_type(target), identity) if platform == 'zhihu' else identity
        if key not in seen:
            seen.add(key)
            selected.append((identity, target))
        if len(selected) >= limit:
            break
    return selected


def zhihu_type(target):
    return 'answer' if '/answer/' in target else 'article' if 'zhuanlan.zhihu.com/p/' in target else 'zvideo'


def configure_discovery(upstream, request, run):
    mode, platform = request['mode'], request['platform']
    if mode not in SUPPORT:
        return
    if platform not in SUPPORT[mode]:
        raise ValueError('discovery_not_supported_for_platform')
    from mc_runner import write
    crawler = upstream.CrawlerFactory.CRAWLERS[platform]

    async def discover(self):
        page = self.context_page
        source = PAGES['bili_trending'] if mode == 'trending' else PAGES[platform]
        # New platforms may finish login on a search warm-up/desktop page. Navigate
        # their normal homepage explicitly; never relabel that warm-up as a feed.
        if mode == 'trending' or platform not in ('xhs', 'bili'):
            await page.goto(source, wait_until='domcontentloaded', timeout=30000)
        selector = SELECTORS[platform]
        deadline = time.monotonic() + 15
        await page.wait_for_selector(selector, timeout=15000)
        # Navigation anchors can appear before asynchronous content cards. Wait
        # within one bounded observation window for actual legal candidates.
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('discovery_empty_or_unavailable')
            try:
                links = await asyncio.wait_for(page.eval_on_selector_all(selector, '(items) => items.filter(x=>x.getClientRects().length && getComputedStyle(x).visibility!=="hidden").slice(0,200).map(x=>x.href)'), timeout=remaining)
            except asyncio.TimeoutError:
                raise ValueError('discovery_empty_or_unavailable') from None
            chosen = select_links(platform, links, request['max_items'])
            if chosen:
                break
            await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
        observed_at = datetime.now(timezone.utc).isoformat()
        # Public metadata has no XHS navigation locator; it stays in this process only.
        write(run / 'discovery.json', {'discovery_kind': mode, 'source_url': source,
                                      'candidate_ids': [identity for identity, _ in chosen],
                                      'observed_at': observed_at,
                                      'position_basis': 'deduplicated_visible_selection_order',
                                      'candidates': [{'content_id': identity, 'sample_position': index + 1,
                                                      'platform_rank': None,
                                                      **({'source_content_type': zhihu_type(target)} if platform == 'zhihu' else {})}
                                                     for index, (identity, target) in enumerate(chosen)],
                                      'following_feed': False, 'coverage': 'visible_page_sample'})
        targets = [target for _, target in chosen]
        if platform == 'bili':
            await self.get_specified_videos(targets)
        elif platform == 'tieba':
            await self.get_specified_notes(targets)
        else:
            import config
            variable, method = {'xhs': ('XHS_SPECIFIED_NOTE_URL_LIST', 'get_specified_notes'),
                                'dy': ('DY_SPECIFIED_ID_LIST', 'get_specified_awemes'),
                                'wb': ('WEIBO_SPECIFIED_ID_LIST', 'get_specified_notes'),
                                'zhihu': ('ZHIHU_SPECIFIED_ID_LIST', 'get_specified_notes'),
                                'ks': ('KS_SPECIFIED_ID_LIST', 'get_specified_videos')}[platform]
            setattr(config, variable, targets)
            await getattr(self, method)()

    crawler.search = discover
