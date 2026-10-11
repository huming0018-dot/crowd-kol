"""Discover visible homepage/ranking links, then reuse the installed detail pipeline."""
import re
import asyncio
import time
import json
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode

class DiscoveryUnavailable(ValueError):
    """Only the bounded homepage observation found no usable candidate."""
    def __init__(self):
        super().__init__('discovery_empty_or_unavailable')


def failure_metadata(error):
    # Never classify arbitrary upstream errors by their possibly private message.
    if type(error) is DiscoveryUnavailable:
        return {'failure_type':'DiscoveryUnavailable', 'failure_stage':'homepage_observation',
                'failure_reason':'discovery_empty_or_unavailable'}
    return {}


def unavailable_failure(value):
    return (value.get('state') == 'failed' and value.get('exit_code') == 74
            and value.get('reason') == 'discovery_empty_or_unavailable'
            and value.get('failure_type') == 'DiscoveryUnavailable'
            and value.get('failure_stage') == 'homepage_observation'
            and value.get('failure_reason') == 'discovery_empty_or_unavailable')

SUPPORT = {'homefeed': {'xhs', 'bili', 'dy', 'wb', 'tieba', 'zhihu', 'ks'}, 'trending': {'bili'}}
PAGES = {'xhs': 'https://www.xiaohongshu.com/explore',
         'bili': 'https://www.bilibili.com/',
         'dy': 'https://www.douyin.com/', 'wb': 'https://m.weibo.cn/',
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
FEED_PATHS = {'dy': {'/aweme/v1/web/tab/feed/', '/aweme/v1/web/feed/', '/aweme/v2/web/module/feed/'},
              'wb': {'/ajax/feed/hottimeline', '/api/container/getIndex'}}
SAFE_ROUTE_PARTS = set('aweme v1 v2 web tab feed api ajax hottimeline recommend status user profile login passport account check info detail comment comments reply replies list item video search config settings hot trending pc get mblog ad ads recommendation challenge explore container getIndex statuses sso signin module friends'.split())


def safe_observed_location(platform, value):
    """Keep only known route words; dynamic IDs and tokens never enter diagnostics."""
    try:
        parsed = urlsplit(value)
        if value == 'about:blank':
            return {'origin': 'other', 'path': None, 'location_kind': 'blank'}
        if parsed.scheme == 'chrome-error' and parsed.hostname == 'chromewebdata':
            return {'origin': 'other', 'path': None, 'location_kind': 'browser_error'}
        official = urlsplit(PAGES[platform]).hostname
        aliases = ('m.weibo.cn', 'weibo.com', 'www.weibo.com') if platform == 'wb' else (official,)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
            return {'origin': 'other', 'path': None}
        if parsed.hostname not in aliases:
            # This fixed native login destination is known; arbitrary foreign URLs stay hidden.
            if platform == 'wb' and parsed.hostname == 'passport.weibo.com' and parsed.path == '/sso/signin':
                return {'origin': 'other', 'path': None, 'location_kind': 'official_login'}
            return {'origin': 'other', 'path': None}
        parts = parsed.path.split('/')[:20]
        path = '/'.join(part if part in SAFE_ROUTE_PARTS or not part else ':redacted' for part in parts)
        return {'origin': 'https://' + parsed.hostname, 'path': path[:500]}
    except (ValueError, TypeError, KeyError):
        return {'origin': 'other', 'path': None}


def page_diagnostics(value):
    """Reject arbitrary page data; expose bounded counts and fixed signals only."""
    if not isinstance(value, dict):
        return {'state': 'unavailable'}
    result = {'state': 'available'}
    for field in ('visible_anchor_total', 'visible_video_count', 'script_element_count', 'frame_element_count'):
        count = value.get(field)
        result[field] = min(10000, max(0, count)) if type(count) is int else None
    for field in ('title_present', 'login_visible', 'verification_visible'):
        result[field] = value.get(field) if type(value.get(field)) is bool else None
    allowed = {'feed-active-video', 'feed-video', 'video-player', 'search-result', 'login-panel', 'video-detail'}
    result['visible_data_e2e'] = sorted({x for x in value.get('visible_data_e2e', [])[:100] if isinstance(x, str) and x in allowed}) if isinstance(value.get('visible_data_e2e'), list) else []
    result['document_ready_state'] = value.get('document_ready_state') if value.get('document_ready_state') in ('loading','interactive','complete') else 'unknown'
    return result


def response_candidates(platform, payload, limit, path=None):
    """Project IDs from a normal homepage response, never from search results."""
    if platform not in FEED_PATHS or not isinstance(payload, dict):
        return []
    if platform == 'dy':
        if type(payload.get('status_code')) is not int or payload['status_code'] != 0:
            return []
        rows = payload.get('aweme_list')
    else:
        if 'ok' in payload and (type(payload['ok']) is not int or payload['ok'] != 1):
            return []
        data = payload.get('data')
        mobile_cards = path == '/api/container/getIndex'
        if mobile_cards and (type(payload.get('ok')) is not int or payload['ok']!=1 or not isinstance(data,dict) or not isinstance(data.get('cards'),list)):
            return []
        rows = data.get('statuses') if isinstance(data, dict) else None
        if mobile_cards:rows=None
        if not isinstance(rows,list) and isinstance(data,dict) and isinstance(data.get('cards'),list):
            if type(payload.get('ok')) is not int or payload['ok']!=1:return []
            rows=[]
            visited=0
            def cards(values, depth=0):
                nonlocal visited
                for card in values[:200]:
                    if visited>=200:return
                    visited+=1
                    if not isinstance(card,dict):continue
                    if isinstance(card.get('mblog'),dict):rows.append({'mblog':card['mblog']})
                    if depth<2 and isinstance(card.get('card_group'),list):cards(card['card_group'],depth+1)
            cards(data['cards'])
    if not isinstance(rows, list):
        return []
    chosen, seen = [], set()
    for row in rows[:200]:
        if not isinstance(row, dict):
            continue
        if platform == 'dy':
            identity = row.get('aweme_id')
        else:
            record = row.get('mblog', row)
            if not isinstance(record, dict):
                continue
            identity = record.get('idstr') or record.get('mid') or record.get('id')
        if type(identity) is int:
            identity = str(identity)
        if not isinstance(identity, str) or not re.fullmatch(r'[0-9]{5,30}', identity) or identity in seen:
            continue
        seen.add(identity)
        chosen.append((identity, identity))
        if len(chosen) >= limit:
            break
    return chosen


def feed_response_path(platform, value):
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443):
            return None
        if platform=='wb' and url.path=='/api/container/getIndex':
            query=parse_qsl(url.query,keep_blank_values=True)
            containers=[value for key,value in query if key=='containerid']
            # User/search containers are not recommendation feed evidence.
            if url.hostname!='m.weibo.cn' or containers!=['102803'] or any(key=='type' and value=='uid' for key,value in query):return None
            return url.path
        hosts = ('www.douyin.com',) if platform == 'dy' else ('weibo.com', 'www.weibo.com')
        return url.path if url.hostname in hosts and url.path in FEED_PATHS.get(platform, set()) else None
    except (ValueError, TypeError):
        return None


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


async def click_wb_recommendation(page, deadline, signals):
    """One normal click on a real, uniquely visible recommendation navigation item."""
    if not hasattr(page,'get_by_text') or signals['click_state']!='not_attempted':return
    async def bounded(awaitable):
        remaining=deadline-time.monotonic()
        if remaining<=0:
            awaitable.close()
            raise asyncio.TimeoutError
        return await asyncio.wait_for(awaitable,timeout=min(1,remaining))
    candidates={}
    try:
        for label in ('推荐','热门','关注'):
            locator=page.get_by_text(label,exact=True)
            count=await bounded(locator.count())
            if type(count) is not int or not 0<=count<=20:continue
            eligible=[]
            for index in range(count):
                target=locator.nth(index)
                if not await bounded(target.is_visible()):continue
                is_navigation=await bounded(target.evaluate('''el=>{let x=el;
                    for(let i=0;x&&i<6;i++,x=x.parentElement){
                        if(['NAV','HEADER'].includes(x.tagName)||['tab','tablist'].includes(x.getAttribute('role'))||
                           Array.from(x.classList||[]).some(v=>/(?:^|[-_])(nav|tabs?|tabbar|tablist|navigation)(?:$|[-_])/.test(v)))return true;
                    }return false;}'''))
                if is_navigation is True:eligible.append(target)
            signals['visible_labels'][label]=bool(eligible)
            if len(eligible)==1 and label!='关注':candidates[label]=eligible[0]
        label=next((value for value in ('推荐','热门') if value in candidates),None)
        if label:
            # Mark before waiting, so a delayed click cannot be retried in this task.
            signals.update(clicked_label=label,click_state='attempted')
            await bounded(candidates[label].click(timeout=max(1,(deadline-time.monotonic())*1000)))
            signals['click_state']='completed'
    except Exception:
        if signals['click_state']=='attempted':signals['click_state']='failed_or_timeout'


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
        tasks, received, observations, response_paths = set(), [], [], []
        last_links, legal_candidates = [], 0
        load_failures = {'total':0, 'script':0, 'document':0, 'xhr':0, 'fetch':0, 'other':0}
        page_error_count = 0
        document_response_status = None
        navigation={'visible_labels':{'推荐':False,'热门':False,'关注':False},'clicked_label':None,'click_state':'not_attempted'}
        async def observe(response, path):
            limit = 8*1024*1024 if platform=='dy' else 1048576
            summary = {'path':path, 'http_status':response.status, 'candidate_count':0, 'status':'pending',
                       'parser_limit_bytes':limit, 'declared_body_bytes':None, 'actual_body_bytes':None}
            if platform=='wb' and path=='/api/container/getIndex':summary['scope']='mobile_public_hot_channel_102803'
            observations.append(summary)
            if response.status != 200:
                summary['status'] = 'http_failed'
                return
            stage = 'header'
            try:
                length = await response.header_value('content-length')
                if length is not None:
                    if not isinstance(length,str) or not re.fullmatch(r'[0-9]{1,16}',length) or int(length)>9007199254740991:
                        summary.update(status='unreadable',failure_kind='invalid_content_length')
                        return
                    summary['declared_body_bytes']=int(length)
                    if int(length)>limit:
                        summary.update(status='size_rejected',failure_kind='declared_size_exceeds_limit')
                        return
                stage = 'body'
                body = await response.body()  # Reads an already received browser response; no request.
                summary['actual_body_bytes']=len(body)
                if len(body) > limit:
                    summary.update(status='size_rejected',failure_kind='actual_size_exceeds_limit')
                    return
                stage = 'decode'
                candidates = response_candidates(platform, json.loads(body), request['max_items'], path=path)
                summary.update(status='matched' if candidates else 'shape_unmatched', candidate_count=len(candidates))
                for item in candidates:
                    if item not in received:
                        received.append(item)
            except asyncio.CancelledError:
                summary['status'] = 'cancelled_at_observation_end'
                raise
            except UnicodeDecodeError:
                summary.update(status='unreadable',failure_kind='invalid_encoding')
            except json.JSONDecodeError:
                summary.update(status='unreadable',failure_kind='invalid_json')
            except Exception:
                summary.update(status='unreadable',failure_kind={'header':'header_read_failed','body':'body_read_failed','decode':'decode_failed'}[stage])
        def on_response(response):
            nonlocal document_response_status
            location = safe_observed_location(platform, response.url)
            resource_type = getattr(getattr(response, 'request', None), 'resource_type', None)
            if resource_type == 'document' and (location['origin'] != 'other' or location.get('location_kind') == 'official_login'):
                document_response_status = response.status if type(response.status) is int and 100 <= response.status <= 599 else None
            if location['origin'] != 'other' and resource_type in ('xhr', 'fetch') and len(response_paths) < 30:
                status = response.status
                response_paths.append({'path':location['path'], 'http_status':status if type(status) is int and 100 <= status <= 599 else None,
                                       'resource_type':resource_type})
            path = feed_response_path(platform, response.url)
            if path is not None and len(observations) + len(tasks) < 8:
                task = asyncio.create_task(observe(response, path))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        def on_request_failed(request):
            load_failures['total'] = min(10000,load_failures['total']+1)
            kind = getattr(request, 'resource_type', None)
            kind = kind if kind in ('script','document','xhr','fetch') else 'other'
            load_failures[kind] = min(10000,load_failures[kind]+1)
        def on_page_error(_error):
            nonlocal page_error_count
            page_error_count = min(10000,page_error_count+1)
        listening = platform in FEED_PATHS and hasattr(page, 'on')
        if listening:
            page.on('response', on_response)
            page.on('requestfailed', on_request_failed)
            page.on('pageerror', on_page_error)
        # New platforms may finish login on a search warm-up/desktop page. Navigate
        # their normal homepage explicitly; never relabel that warm-up as a feed.
        basis = 'visible_page_sample'
        deadline = time.monotonic() + 15
        try:
            if mode == 'trending' or platform not in ('xhs', 'bili'):
                await asyncio.wait_for(page.goto(source, wait_until='domcontentloaded', timeout=15000), timeout=15)
            selector = SELECTORS[platform]
            if not listening:
                remaining = max(0.001, deadline - time.monotonic())
                await asyncio.wait_for(page.wait_for_selector(selector, timeout=remaining * 1000), timeout=remaining)
        # Navigation anchors can appear before asynchronous content cards. Wait
        # within one bounded observation window for actual legal candidates.
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DiscoveryUnavailable()
                try:
                    links = await asyncio.wait_for(page.eval_on_selector_all(selector, '(items) => items.filter(x=>x.getClientRects().length && getComputedStyle(x).visibility!=="hidden").slice(0,200).map(x=>x.href)'), timeout=remaining)
                except asyncio.TimeoutError:
                    raise DiscoveryUnavailable() from None
                chosen = select_links(platform, links, request['max_items'])
                last_links = links if isinstance(links, list) else []
                legal_candidates = len(select_links(platform, last_links, 100))
                if chosen:
                    break
                if received:
                    chosen = received[:request['max_items']]
                    basis = 'seen_response_sample'
                    break
                if platform=='wb' and navigation['click_state']=='not_attempted':
                    await click_wb_recommendation(page,deadline,navigation)
                await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
        finally:
            if listening:
                page.remove_listener('response', on_response)
                page.remove_listener('requestfailed', on_request_failed)
                page.remove_listener('pageerror', on_page_error)
            for task in list(tasks):
                task.cancel()
            if tasks:
                await asyncio.gather(*list(tasks), return_exceptions=True)
            if listening:
                visible = {'state': 'unavailable'}
                try:
                    raw = await asyncio.wait_for(page.evaluate('''() => {
                        const visible=x=>x.getClientRects().length && getComputedStyle(x).visibility!=="hidden";
                        const count=s=>Array.from(document.querySelectorAll(s)).filter(visible).length;
                        const enums=['feed-active-video','feed-video','video-player','search-result','login-panel','video-detail'];
                        return {visible_anchor_total:count('a[href]'), visible_video_count:count('video'),
                            script_element_count:document.querySelectorAll('script').length,
                            frame_element_count:document.querySelectorAll('iframe,frame').length,
                            document_ready_state:document.readyState,
                            title_present:!!document.title.trim(), login_visible:!!count('[data-e2e="login-panel"], [data-e2e="login-button"]'),
                            verification_visible:!!count('[id*="captcha"], [class*="captcha"], [data-e2e="verify-panel"]'),
                            visible_data_e2e:enums.filter(x=>count('[data-e2e="'+x+'"]'))};
                    }'''), timeout=1)
                    visible = page_diagnostics(raw)
                except Exception:
                    pass
                write(run / 'discovery-observation.json', {'schema':'crowd_homefeed_observation_v1',
                      'platform':platform, 'responses':observations, 'source_requests_added':0,
                      'homepage':safe_observed_location(platform, getattr(page, 'url', None)),
                      'visible_page':visible, 'sampled_selector_link_count':min(200,len(last_links)),
                      'legal_sampled_link_count':legal_candidates, 'official_response_paths':response_paths,
                      'failed_request_counts':load_failures, 'page_error_count':page_error_count,
                      'document_response_status':document_response_status,
                      'homepage_navigation':navigation if platform=='wb' else None,
                      'selection_policy':'visible_DOM_first_then_same_homepage_response'})
        observed_at = datetime.now(timezone.utc).isoformat()
        # Public metadata has no XHS navigation locator; it stays in this process only.
        write(run / 'discovery.json', {'discovery_kind': mode, 'source_url': source,
                                      'candidate_ids': [identity for identity, _ in chosen],
                                      'observed_at': observed_at,
                                      'position_basis': 'deduplicated_visible_selection_order' if basis == 'visible_page_sample' else 'sampled_received_order',
                                      'candidates': [{'content_id': identity, 'sample_position': index + 1,
                                                      'platform_rank': None,
                                                      **({'source_content_type': zhihu_type(target)} if platform == 'zhihu' else {})}
                                                     for index, (identity, target) in enumerate(chosen)],
                                      'following_feed': False, 'coverage': basis})
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
