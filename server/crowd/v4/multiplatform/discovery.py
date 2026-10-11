"""Discover visible homepage/ranking links, then reuse the installed detail pipeline."""
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode

SUPPORT = {'homefeed': {'xhs', 'bili'}, 'trending': {'bili'}}
PAGES = {'xhs': 'https://www.xiaohongshu.com/explore',
         'bili': 'https://www.bilibili.com/',
         'bili_trending': 'https://www.bilibili.com/v/popular/all/'}


def select_links(platform, links, limit):
    if platform not in ('xhs', 'bili') or type(limit) is not int or not 1 <= limit <= 100:
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
        else:
            if url.hostname not in ('www.bilibili.com', 'bilibili.com'):
                continue
            match = re.fullmatch(r'/video/(BV[A-Za-z0-9]{10})/?', url.path)
            if not match:
                continue
            identity = target = match[1]
        if identity not in seen:
            seen.add(identity)
            selected.append((identity, target))
        if len(selected) >= limit:
            break
    return selected


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
        if mode == 'trending':
            await page.goto(source, wait_until='domcontentloaded', timeout=30000)
        selector = 'a[href*="/explore/"],a[href*="/discovery/item/"]' if platform == 'xhs' else 'a[href*="/video/BV"]'
        await page.wait_for_selector(selector, timeout=15000)
        links = await page.eval_on_selector_all(selector, '(items) => items.filter(x=>x.getClientRects().length && getComputedStyle(x).visibility!=="hidden").slice(0,200).map(x=>x.href)')
        observed_at = datetime.now(timezone.utc).isoformat()
        chosen = select_links(platform, links, request['max_items'])
        if not chosen:
            raise ValueError('discovery_empty_or_unavailable')
        # Public metadata has no XHS navigation locator; it stays in this process only.
        write(run / 'discovery.json', {'discovery_kind': mode, 'source_url': source,
                                      'candidate_ids': [identity for identity, _ in chosen],
                                      'observed_at': observed_at,
                                      'position_basis': 'deduplicated_visible_selection_order',
                                      'candidates': [{'content_id': identity, 'sample_position': index + 1,
                                                      'platform_rank': None}
                                                     for index, (identity, _) in enumerate(chosen)],
                                      'following_feed': False, 'coverage': 'visible_page_sample'})
        targets = [target for _, target in chosen]
        if platform == 'xhs':
            import config
            config.XHS_SPECIFIED_NOTE_URL_LIST = targets
            await self.get_specified_notes()
        else:
            await self.get_specified_videos(targets)

    crawler.search = discover
