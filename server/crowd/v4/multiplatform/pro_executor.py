"""Optional adapter for a separately licensed Pro installation; no vendored code.

The existing runner owns locks, stop, deadlines and delivery. This module maps
the upstream durable acquisition protocol to its existing import contract.
"""
import asyncio
import contextlib
from contextvars import ContextVar
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import resource
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from pro_cursor_pages import CursorStalled

PROTOCOL = 'vox-acquisition-v1'
PINNED_COMMIT = 'd32dd565277116ba4880c28ccd417a7c376cb62d'
SUPPORTED = ('xhs', 'dy', 'bili')
DB_NAME = 'pro-observations.sqlite3'
MAX_DB_BYTES = 104857600
MAX_ROWS = 10000


def bridge():
    import mc_runner
    return mc_runner


def selection(request, environ=None):
    """Only fall back BEFORE creating a run; an uncertain Pro run never reruns MC."""
    env = os.environ if environ is None else environ
    requested = env.get('CROWD_EXECUTOR', 'mc')
    if requested not in ('mc', 'pro'):
        bridge().fail('invalid_executor_selection')
    if requested == 'mc':
        return {'backend': 'mc', 'requested_backend': 'mc'}
    reason = None
    if request['platform'] not in SUPPORTED:
        reason = 'pro_operation_platform_not_adapted'
    elif request['mode'] not in ('search', 'detail', 'creator'):
        reason = 'discovery_retains_original_executor'
    elif request.get('media'):
        reason = 'media_bytes_and_subtitles_retain_original_executor'
    elif request.get('wordcloud') or request.get('platform_options'):
        reason = 'requested_option_retains_original_executor'
    elif request.get('comments') and request.get('max_comments') == 0:
        reason = 'pro_zero_comments_means_unlimited'
    if reason:
        return {'backend': 'mc', 'requested_backend': 'pro', 'fallback_reason': reason}
    if not env.get('CROWD_PRO_ROOT'):
        bridge().fail('pro_root_missing')
    return {'backend': 'pro', 'requested_backend': 'pro', 'root': str(Path(env['CROWD_PRO_ROOT']).resolve())}


def probe(root, python=sys.executable):
    """The pinned upstream early capability exit does not load accounts or DBs."""
    m = bridge()
    root = Path(root).resolve()
    info = m.source_info(root)
    if info['commit'] != PINNED_COMMIT or info['dirty']:
        m.fail('pro_source_not_reviewed')
    result = subprocess.run([str(python), '-B', str(root/'main.py'), '--acquisition-capabilities'],
                            cwd=root, capture_output=True, timeout=10,
                            env={'PATH': os.environ.get('PATH', ''), 'PYTHONDONTWRITEBYTECODE': '1'})
    try:
        caps = json.loads(result.stdout) if len(result.stdout) <= 4096 else None
    except ValueError:
        caps = None
    if result.returncode or not isinstance(caps, dict) or caps.get('schema_version') != PROTOCOL or not set(SUPPORTED) <= set(caps.get('platforms', [])):
        m.fail('pro_protocol_incompatible')
    return {**info, 'executor': 'mediacrawler_pro', 'protocol': PROTOCOL}


def binding_for(root, request):
    """A local operator binds ONE client explicitly; never select the first account."""
    m = bridge()
    path = Path(root)/'sessions'/request['session_id']/'pro-binding.json'
    if not path.is_file() or path.is_symlink():
        m.fail('pro_account_binding_required')
    value = m.read(path)
    if not isinstance(value, dict) or set(value) != {'platform', 'client_id', 'cookiebridge_url', 'sign_url'} or value.get('platform') != request['platform']:
        m.fail('pro_account_binding_invalid')
    if not isinstance(value['client_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value['client_id']):
        m.fail('pro_account_binding_invalid')
    for field in ('cookiebridge_url', 'sign_url'):
        try:
            url = urlsplit(value[field])
            valid = url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost', '::1') and url.port and not url.username and not url.password and url.path in ('', '/') and not url.query and not url.fragment
        except (TypeError, ValueError):
            valid = False
        if not valid:
            m.fail('pro_service_must_be_explicit_loopback')
        # This pinned SignSrv client interpolates host:port without IPv6 brackets.
        if field == 'sign_url' and url.hostname == '::1':
            m.fail('pro_sign_ipv6_unsupported')
        value[field] = value[field].rstrip('/')
    return value


def prepare(root, mc, request, chosen):
    m = bridge()
    if chosen['backend'] != 'pro':
        return chosen, m.source_info(mc), Path(mc)/'.venv/bin/python'
    source = probe(chosen['root'])
    external = Path(chosen['root'])
    runtime = Path(root).resolve()
    if runtime == external or external in runtime.parents:
        m.fail('runtime_must_be_outside_upstream')
    # No secrets in this binding (client reference only); cookies stay in memory.
    bound = binding_for(root, request)
    python = Path(os.environ.get('CROWD_PRO_PYTHON', str(external/'.venv/bin/python')))
    if not python.is_absolute() or not python.is_file():
        m.fail('pro_python_missing')
    return {**chosen, 'python': str(python), 'protocol': PROTOCOL, 'binding': bound}, source, python


def argv_for(request):
    m = bridge()
    args = ['--platform', request['platform'], '--type', request['mode'], '--enable_checkpoint',
            '--max_notes_count', str(request['max_items']), '--max_comments_count', str(request['max_comments']),
            '--enable_comments' if request['comments'] else '--no-enable_comments',
            '--enable_sub_comments' if request['replies'] else '--no-enable_sub_comments']
    targets = [m.execution_target(request['platform'], request['mode'], target) for target in request['targets']]
    return args + ['--keywords' if request['mode'] == 'search' else '--urls', ','.join(targets)]


def checkpoint(run, manifest):
    m = bridge()
    run = Path(run)
    paths = [run/'data/checkpoints/vox'/(manifest['run_id']+'.json'),
             run/'data/checkpoints'/(manifest['run_id']+'.json')]
    values = []
    for path in paths:
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != run and run in parent.parents):
            m.fail('unsafe_pro_checkpoint')
        if not path.exists():
            continue
        if not path.is_file() or not path.resolve().is_relative_to(run.resolve()) or path.stat().st_size > 10_000_000:
            m.fail('unsafe_pro_checkpoint')
        values.append(m.read(path))
    if not values:
        return None
    if len(values) == 2 and m.canonical(values[0]) != m.canonical(values[1]):
        m.fail('pro_checkpoint_path_conflict')
    value = values[0]
    p = manifest['request']
    if not isinstance(value, dict) or value.get('id') != manifest['run_id'] or value.get('platform') != p['platform'] or value.get('mode') != p['mode']:
        m.fail('pro_checkpoint_identity_mismatch')
    if not isinstance(value.get('crawled_note_list'), list) or len(value['crawled_note_list']) > MAX_ROWS:
        m.fail('pro_checkpoint_invalid')
    return value


def observations(run, manifest):
    m = bridge()
    run = Path(run)
    path = run/DB_NAME
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(run.resolve()):
        m.fail('pro_observation_database_missing')
    if path.stat().st_size > MAX_DB_BYTES or any(p.is_symlink() for p in (run/(DB_NAME+'-wal'), run/(DB_NAME+'-shm'))):
        m.fail('unsafe_pro_database')
    rows = []
    with contextlib.closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        for platform, kind, entity, raw in db.execute('SELECT platform,kind,entity_id,payload FROM vox_crawl_observation WHERE operation_id=? ORDER BY kind,entity_id', (manifest['run_id'],)):
            if len(rows) >= MAX_ROWS or not isinstance(raw, str) or len(raw) > 1_000_000:
                m.fail('pro_observation_limit')
            row = json.loads(raw)
            key = 'comment_id' if kind == 'comment' else m.ID_KEYS.get(platform)
            if platform != manifest['request']['platform'] or kind not in ('topic', 'comment') or not isinstance(row, dict) or m.opaque(row.get(key)) != entity:
                m.fail('pro_observation_identity_mismatch')
            rows.append((kind, entity, row))
    return rows


def completion(run, manifest, summary):
    """Local commit is checked separately from delivery; it is NEVER a cloud ACK."""
    m = bridge()
    cp = checkpoint(run, manifest)
    rows = observations(run, manifest)
    p = manifest['request']
    topics = {entity for kind, entity, _ in rows if kind == 'topic'}
    if not isinstance(summary, dict) or summary.get('status') != 'completed' or summary.get('operation_id') != manifest['run_id'] or summary.get('platform') != p['platform'] or summary.get('crawler_type') != p['mode']:
        m.fail('pro_final_summary_unconfirmed')
    if not cp or cp.get('acquisition_committed') is not True or cp.get('is_completed') is not True or cp.get('failed_search_pages'):
        m.fail('pro_checkpoint_not_committed')
    notes = cp['crawled_note_list']
    if any(not isinstance(n, dict) or n.get('is_success_crawled') is not True or (p['comments'] and n.get('is_success_crawled_comments') is not True) for n in notes):
        m.fail('pro_checkpoint_partial')
    checkpoint_topics = topics
    if p['platform'] == 'bili':
        mapping = {}
        for kind, entity, row in rows:
            if kind != 'topic':
                continue
            bvid = row.get('bvid')
            if (not isinstance(bvid, str) or not re.fullmatch(r'BV[A-Za-z0-9]{10}', bvid) or
                    page_id(entity) is None or str(row.get('video_id')) != entity or bvid in mapping):
                m.fail('pro_bili_checkpoint_mapping_invalid')
            mapping[bvid] = entity
        checkpoint_topics = set(mapping)
    if len(notes) != len(checkpoint_topics) or {str(n.get('note_id')) for n in notes} != checkpoint_topics:
        m.fail('pro_checkpoint_observation_mismatch')
    return {'operation_id': manifest['run_id'], 'local_committed': True, 'cloud_ack': False,
            'content_count': len(topics), 'comment_count': sum(k == 'comment' for k, _, _ in rows),
            'checkpoint_id': manifest['run_id'], 'coverage': 'unverified'}


def public_url(value):
    if not isinstance(value, str) or len(value) > 4000 or bridge().contains_secret(value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            return None
    except ValueError:
        return None
    return value


def import_records(run, manifest):
    """Reuse the established normalizer and retain Pro-specific public fields."""
    m = bridge()
    p = manifest['request']['platform']
    cp = checkpoint(run, manifest)
    rows = observations(run, manifest)
    records, media = [], []
    fields = ('bvid', 'duration', 'aweme_type', 'is_ai_generated', 'tag_list', 'last_update_time',
              'target_comment_id', 'reply_to_reply_id')
    url_fields = ('video_url', 'video_cover_url', 'aweme_url', 'cover_url', 'video_download_url', 'note_url')
    for kind, entity, row in rows:
        row_sha = hashlib.sha256(m.canonical(row).encode()).hexdigest()
        record = m.normalize(p, 'content' if kind == 'topic' else 'comment', row,
                             {'run_id': manifest['run_id'], 'operation_id': manifest['run_id'],
                              'executor': 'mediacrawler_pro', 'observation_sha256': row_sha})
        # This Pro version preserves full Bili descriptions; the MC 500-char warning does not apply.
        record.pop('upstream_truncation_risk', None)
        record['platform_fields'].update({key: value for key in fields if (value := row.get(key)) is not None and
                                         (type(value) is int or isinstance(value, str) and m.safe_text(value, 4000) == value)})
        record['platform_fields'].update({key: url for key in url_fields if (url := public_url(row.get(key)))})
        references = []
        for key, media_kind in (('image_list', 'image'), ('pictures', 'comment_image'),
                                ('video_cover_url', 'cover'), ('cover_url', 'cover'),
                                ('video_download_url', 'video'), ('video_url', 'video')):
            values = row.get(key) or ''
            if not isinstance(values, str):
                m.fail('pro_media_reference_invalid')
            # Bili video_url is the watch page, never a downloaded-video reference.
            if p == 'bili' and key == 'video_url':
                continue
            for value in values.split(','):
                url = public_url(value.strip())
                if not url:
                    continue
                item = {'media_id': hashlib.sha256(m.canonical([p, kind, entity, key, url]).encode()).hexdigest(),
                        'platform': m.PLATFORMS[p], 'content_id': record['content_id'],
                        'kind': media_kind, 'url': url, 'status': 'reference_only',
                        'source_kind': 'mediacrawler_api', 'reward_eligible': False}
                if kind == 'comment': item['comment_id'] = entity
                references.append(item)
                if len(media) >= 1000: m.fail('media_manifest_limit')
                media.append(item)
        record['media'] = references
        record['discovery_kind'] = manifest['request']['mode']
        record['record_hash'] = hashlib.sha256(m.canonical({k: v for k, v in record.items() if k != 'record_hash'}).encode()).hexdigest()
        records.append(record)
    topics = {r['content_id'] for r in records if r['kind'] == 'content'}
    if any(r['content_id'] not in topics for r in records if r['kind'] == 'comment'):
        m.fail('pro_comment_content_missing')
    evidence = {'executor': 'mediacrawler_pro', 'protocol': PROTOCOL,
                'operation_id': manifest['run_id'], 'local_committed': bool(cp and cp.get('acquisition_committed') is True),
                'cloud_ack': False, 'raw_response_pages_available': False,
                'pagination_evidence': 'upstream_checkpoint_only',
                'media_evidence': 'references_only_no_download_or_transcript'}
    if p in SUPPORTED:
        evidence['pagination'] = pagination_summary(run, manifest)
    return records, media, evidence


def page_number(value):
    if type(value) is int and 0 <= value <= 10**18:
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,19}', value):
        return int(value)
    return None


def page_id(value):
    value = str(value)
    return value if re.fullmatch(r'[0-9]{1,30}', value) else None


def reply_belongs_to(entity, root, rows, content_id):
    seen = set()
    while entity in rows and entity not in seen and len(seen) < MAX_ROWS:
        seen.add(entity)
        if str(rows[entity].get('video_id')) != content_id:
            return False
        parent = str(rows[entity].get('parent_comment_id'))
        if parent == root:
            return root in rows and str(rows[root].get('video_id')) == content_id and is_root_comment(rows[root])
        entity = parent
    return False


def is_root_comment(row):
    return 'parent_comment_id' in row and row['parent_comment_id'] in ('', '0')


def pinned_comments(value, depth=0):
    """Recognize explicit empty slots and roots; malformed shapes stay unknown."""
    if depth > 8:
        return [], False
    if value is None:
        return [], True
    if isinstance(value, dict):
        if 'rpid' in value:
            entity = page_id(value['rpid'])
            return ([value], True) if entity is not None else ([], False)
        if set(value) != {'admin', 'upper', 'vote'}:
            return [], False
        value = list(value.values())
    if isinstance(value, list):
        if len(value) > MAX_ROWS:
            return [], False
        comments = []
        for child in value:
            child_comments, valid = pinned_comments(child, depth+1)
            if not valid:
                return [], False
            comments.extend(child_comments)
        return comments, True
    return [], False


def pinned_ids(value):
    comments, valid = pinned_comments(value)
    return {page_id(c['rpid']) for c in comments}, valid


def pagination_summary(run, manifest):
    """Coverage evidence is separate from upstream commit and cloud delivery."""
    if manifest['request']['platform'] in ('xhs','dy'):
        import pro_cursor_pages
        return pro_cursor_pages.summary(run,manifest,sys.modules[__name__])
    unknown = {'coverage': 'unknown', 'reason': 'pagination_evidence_missing'}
    path = Path(run)/'pro-pagination.json'
    if not path.exists():
        return unknown
    try:
        if path.is_symlink() or path.stat().st_size > 3_000_000:
            raise ValueError()
        doc = bridge().read(path)
        digest = doc.pop('sha256')
        if (digest != hashlib.sha256(bridge().canonical(doc).encode()).hexdigest() or
                doc['operation_id'] != manifest['run_id'] or doc['schema_version'] != 1 or
                not isinstance(doc['pages'], list) or not 0 < len(doc['pages']) <= 1000):
            raise ValueError()
        pages = doc['pages']
        rows = observations(run, manifest)
        topics = {entity: row for kind, entity, row in rows if kind == 'topic'}
        saved = {entity: row for kind, entity, row in rows if kind == 'comment'}
        if doc['invalid'] or any(p['invalid'] or p['pinned_gap'] for p in pages):
            return {'coverage': 'unknown', 'reason': 'pagination_fields_or_pinned_gap'}
        for p in pages:
            if p['content_id'] not in topics or not isinstance(p['ids'], list) or len(p['ids']) != len(set(p['ids'])):
                raise ValueError()
            if p['saved'] and any(i not in saved or str(saved[i].get('video_id')) != p['content_id'] or
                    (p['scope'] == 'root' and not is_root_comment(saved[i])) or
                    (p['scope'] == 'reply' and not reply_belongs_to(i, p['parent_id'], saved, p['content_id'])) for i in p['ids']):
                raise ValueError()
        if any(not p['saved'] for p in pages):
            return {'coverage': 'partial', 'reason': 'response_not_fully_saved'}
        cp = checkpoint(run, manifest)
        notes = {str(n['note_id']): n for n in (cp or {}).get('crawled_note_list', [])}
        exhausted = True
        for aid, topic in topics.items():
            roots = [p for p in pages if p['scope'] == 'root' and p['content_id'] == aid]
            if not roots or roots[0]['cursor_in'] != 0:
                return {'coverage': 'unknown', 'reason': 'root_chain_origin_unknown'}
            seen = set()
            root_ids = set()
            for index, p in enumerate(roots):
                if p['cursor_in'] in seen or index and (roots[index-1]['is_end'] or p['cursor_in'] != roots[index-1]['cursor_out']):
                    return {'coverage': 'unknown', 'reason': 'root_chain_invalid'}
                seen.add(p['cursor_in'])
                if root_ids.intersection(p['ids']):
                    return {'coverage': 'unknown', 'reason': 'repeated_root_ids'}
                root_ids.update(p['ids'])
                if manifest['request']['replies']:
                    for parent, count in p['reply_roots'].items():
                        replies = [r for r in pages if r['scope'] == 'reply' and r['content_id'] == aid and r['parent_id'] == parent]
                        if count == 0:
                            if replies:
                                return {'coverage': 'unknown', 'reason': 'unexpected_replies_for_zero_count'}
                            continue
                        if not replies or any(r['pn'] != j+1 or j and not replies[j-1]['has_more'] for j, r in enumerate(replies)) or replies[-1]['has_more']:
                            return {'coverage': 'partial', 'reason': 'reply_chain_incomplete'}
                        if any(r['declared_count'] != count or r['ps'] != replies[0]['ps'] for r in replies):
                            return {'coverage': 'unknown', 'reason': 'reply_count_or_page_size_changed'}
                        reply_ids = [entity for r in replies for entity in r['ids']]
                        if len(reply_ids) != len(set(reply_ids)):
                            return {'coverage': 'unknown', 'reason': 'repeated_reply_ids'}
                        if len(reply_ids) != count:
                            return {'coverage': 'partial', 'reason': 'declared_replies_not_fully_saved'}
            if any(r['parent_id'] not in root_ids for r in pages if r['scope'] == 'reply' and r['content_id'] == aid):
                return {'coverage': 'unknown', 'reason': 'reply_root_not_observed'}
            note = notes.get(str(topic.get('bvid')))
            if not note or str(note.get('current_note_comment_cursor')) != str(roots[-1]['cursor_out']) or not roots[-1]['checkpoint_committed']:
                return {'coverage': 'partial', 'reason': 'parent_checkpoint_unconfirmed'}
            exhausted = exhausted and roots[-1]['is_end']
        if exhausted:
            return {'coverage': 'exhausted', 'reason': 'accessible_page_chain_ended'}
        limit = manifest['request']['max_comments']
        if cp and cp.get('acquisition_committed') is True and limit and all(
                n.get('is_success_crawled_comments') is True and type(n.get('saved_comment_count')) is int and
                n['saved_comment_count'] >= limit for n in notes.values()):
            return {'coverage': 'limit_reached', 'reason': 'upstream_batch_limit'}
        return {'coverage': 'partial', 'reason': 'root_chain_incomplete'}
    except (ValueError, TypeError, KeyError, AttributeError, OSError, sqlite3.Error, bridge().BridgeError):
        return {'coverage': 'unknown', 'reason': 'pagination_evidence_invalid'}


class BiliPagination:
    """Observe pinned upstream methods without replacing their loops or results."""
    def __init__(self, run, manifest):
        self.run, self.manifest = Path(run), manifest
        self.current = ContextVar('pro_bili_page', default=None)
        self.pages, self.invalid = [], False
        self.lock = threading.RLock()

    def persist(self):
        with self.lock:
            doc = {'schema_version': 1, 'operation_id': self.manifest['run_id'],
                   'pages': self.pages, 'invalid': self.invalid}
            text = bridge().canonical(doc)
            if len(text.encode()) > 2_900_000:
                self.invalid = True
                raise SystemExit(76)
            bridge().write(self.run/'pro-pagination.json', {**doc, 'sha256': hashlib.sha256(text.encode()).hexdigest()})

    def response(self, scope, aid, comments, data, cursor=0, parent=None, pn=None, ps=None):
        if len(self.pages) >= 1000:
            raise SystemExit(76)
        ids = [page_id(c.comment_id) for c in comments]
        page = {'scope': scope, 'content_id': page_id(aid), 'parent_id': page_id(parent) if parent is not None else None,
                'ids': ids, 'saved': False, 'checkpoint_committed': False, 'invalid': None in ids or len(ids) != len(set(ids)) or page_id(aid) is None,
                'pinned_gap': False}
        if scope == 'root':
            info = data.get('cursor', {}) if isinstance(data, dict) else {}
            info = info if isinstance(info, dict) else {}
            end = info.get('is_end')
            page.update(cursor_in=page_number(cursor), cursor_out=page_number(info.get('next')), is_end=end if type(end) is bool else None,
                        reply_roots={page_id(c.comment_id): page_number(c.sub_comment_count) for c in comments})
            page['invalid'] |= page['cursor_in'] is None or page['cursor_out'] is None or type(end) is not bool or None in page['reply_roots'].values()
            for key in ('top', 'top_replies'):
                entries, valid = pinned_ids(data.get(key) if isinstance(data, dict) else None)
                if not valid or not entries.issubset(set(ids)):
                    page['pinned_gap'] = True
        else:
            info = data.get('page', {}) if isinstance(data, dict) else {}
            info = info if isinstance(info, dict) else {}
            count = page_number(info.get('count'))
            pn, ps = page_number(pn), page_number(ps)
            page.update(pn=pn, ps=ps, declared_count=count, has_more=count > pn*ps if count is not None and pn and ps else None)
            page['invalid'] |= count is None or not pn or not ps or page['parent_id'] is None
            for field, expected in (('pn', pn), ('num', pn), ('ps', ps), ('size', ps)):
                if field in info and page_number(info[field]) != expected:
                    page['invalid'] = True
        self.pages.append(page)
        self.current.set(page)
        self.persist()

    def install(self, client_type, store, manager_type):
        root, reply = client_type.get_video_comments, client_type.get_video_sub_comments
        callback, commit = store.batch_update_bilibili_video_comments, manager_type.update_note_comment_cursor
        async def roots(*args, **kwargs):
            bound = inspect.signature(root).bind(*args, **kwargs)
            bound.apply_defaults()
            value = await root(*args, **kwargs)
            value = self.merge_pinned(bound.arguments[next(iter(bound.signature.parameters))], bound.arguments['video_id'], value)
            self.response('root', bound.arguments['video_id'], *value, cursor=bound.arguments['next_page'])
            return value
        async def replies(*args, **kwargs):
            bound = inspect.signature(reply).bind(*args, **kwargs)
            bound.apply_defaults()
            value = await reply(*args, **kwargs)
            self.response('reply', bound.arguments['video_id'], *value, parent=bound.arguments['root_comment_id'],
                          pn=bound.arguments['pn'], ps=bound.arguments['ps'])
            return value
        async def saved(video_id, comments):
            result = await callback(video_id, comments)
            page = self.current.get()
            if page is None or page['content_id'] != page_id(video_id) or page['ids'] != [page_id(c.comment_id) for c in comments]:
                self.invalid = True
            else:
                rows = {entity: row for kind, entity, row in observations(self.run, self.manifest) if kind == 'comment'}
                page['saved'] = all(i in rows and str(rows[i].get('video_id')) == page['content_id'] and
                    (is_root_comment(rows[i]) if page['scope'] == 'root' else
                     reply_belongs_to(i, page['parent_id'], rows, page['content_id'])) for i in page['ids'])
            self.persist()
            return result
        async def committed(manager, checkpoint_id, note_id, comment_cursor, is_success_crawled_comments=False, saved_comment_count=None):
            result = await commit(manager, checkpoint_id, note_id, comment_cursor, is_success_crawled_comments, saved_comment_count)
            cp = checkpoint(self.run, self.manifest)
            topic_ids = {entity for kind, entity, row in observations(self.run, self.manifest) if kind == 'topic' and str(row.get('bvid')) == str(note_id)}
            matches = [p for p in self.pages if p['scope'] == 'root' and p['content_id'] in topic_ids and str(p['cursor_out']) == str(comment_cursor)]
            notes = [n for n in (cp or {}).get('crawled_note_list', []) if str(n.get('note_id')) == str(note_id)]
            if (checkpoint_id == self.manifest['run_id'] and result is True and matches and notes and
                    str(notes[0].get('current_note_comment_cursor')) == str(comment_cursor) and
                    notes[0].get('is_success_crawled_comments') is is_success_crawled_comments and
                    (saved_comment_count is None or notes[0].get('saved_comment_count') == saved_comment_count)):
                matches[-1]['checkpoint_committed'] = True
            self.persist()
            return result
        client_type.get_video_comments, client_type.get_video_sub_comments = roots, replies
        store.batch_update_bilibili_video_comments = saved
        manager_type.update_note_comment_cursor = committed

    def merge_pinned(self, client, aid, value):
        comments, data = value
        raw = []
        for key in ('top', 'top_replies'):
            pinned, valid = pinned_comments(data.get(key) if isinstance(data, dict) else None)
            if not valid:
                return value  # The observer keeps malformed pinned structures unknown.
            raw.extend(pinned)
        if not raw:
            return value
        try:
            parsed = client._extractor.extract_comments_from_dict(video_id=aid, comments_data=raw)
            if len(parsed) != len(raw):
                raise ValueError()
            known = {page_id(c.comment_id): c for c in comments}
            added = []
            for original, comment in zip(raw, parsed):
                entity = page_id(comment.comment_id)
                if (entity != page_id(original['rpid']) or str(comment.video_id) != str(aid) or
                        not is_root_comment(comment.model_dump()) or page_number(comment.sub_comment_count) is None):
                    raise ValueError()
                if entity in known:
                    if bridge().canonical(known[entity].model_dump()) != bridge().canonical(comment.model_dump()):
                        raise ValueError()
                else:
                    known[entity] = comment
                    added.append(comment)
            return (comments+added, data) if added else value
        except (AttributeError, TypeError, ValueError, KeyError):
            self.invalid = True
            return value


class ProgressSink:
    """Discard upstream logs; persist only allowlisted protocol progress."""
    def __init__(self, run, manifest):
        self.run, self.manifest, self.buffer, self.summary = Path(run), manifest, '', None
        self.attempts = 0
        self.lock = threading.RLock()

    def update(self, **fields):
        with self.lock:
            path = self.run/'phase.json'
            previous = bridge().read(path) if path.exists() else {}
            bridge().write(path, {**previous, 'phase': 'running', 'executor': 'mediacrawler_pro',
                                  'api_attempts': self.attempts, **fields})

    def write(self, text):
        with self.lock:
            self.buffer = (self.buffer + text)[-65536:]
            while '\n' in self.buffer:
                line, self.buffer = self.buffer.split('\n', 1)
                try:
                    if line.startswith('@@MCPRO_EVENT@@'):
                        event = json.loads(line[len('@@MCPRO_EVENT@@'):])
                        if event.get('schema_version') != PROTOCOL or event.get('operation_id') != self.manifest['run_id'] or event.get('platform') != self.manifest['request']['platform']:
                            continue
                        fields = {k: event[k] for k in ('item_count', 'comment_count') if type(event.get(k)) is int and 0 <= event[k] <= MAX_ROWS}
                        self.update(**fields, operation_id=event['operation_id'],
                                    upstream_status=event.get('status') if event.get('status') in ('running', 'completed', 'failed') else 'unknown',
                                    checkpoint_created=event.get('checkpoint_created') is True)
                    elif line.startswith('---CRAWL_SUMMARY: ') and line.endswith('---'):
                        value = json.loads(line[len('---CRAWL_SUMMARY: '):-3])
                        self.summary = {k: value.get(k) for k in ('operation_id', 'platform', 'crawler_type', 'status')}
                except (ValueError, TypeError, AttributeError):
                    continue
        return len(text)

    def flush(self): pass
    def isatty(self): return False


def install_transport_limits(httpx, request, sink, self_observer=None):
    """Count every attempt including CookieBridge/signing; stop before overflow."""
    original_async, original_sync = httpx.AsyncClient.send, httpx.Client.send
    original_bytes = httpx.Response.aiter_bytes
    total = 0
    def debit():
        if sink.attempts >= request['max_api_requests']:
            sink.update(phase='stopping', failure_reason='api_request_limit')
            raise SystemExit(73)
        sink.attempts += 1
        sink.update()
    def check_response(response):
        if self_observer is not None:self_observer(response)
        if response.status_code in (401, 403): raise SystemExit(77)
        if response.status_code == 429: raise SystemExit(79)
        if request.get('platform') == 'xhs':
            # Fixed upstream client retries Exception five times, including these
            # known challenges. BaseException stops BEFORE that retry wrapper.
            if response.status_code in (461, 471): raise SystemExit(80)
            try: data = response.json()
            except (ValueError, AttributeError): data = None
            code = data.get('code') if isinstance(data, dict) else None
            if code == -100: raise SystemExit(77)
            if code == 300013: raise SystemExit(79)
            if code == 300012: raise SystemExit(81)
            if code == 300015: raise SystemExit(82)
        if request.get('platform') == 'dy' and getattr(response, 'text', None) == 'blocked':
            raise SystemExit(81)
    async def send(client, *a, **kw):
        debit()
        response = await original_async(client, *a, **kw)
        check_response(response)
        return response
    def sync(client, *a, **kw):
        debit()
        response = original_sync(client, *a, **kw)
        check_response(response)
        return response
    async def chunks(response, *a, **kw):
        nonlocal total
        async for chunk in original_bytes(response, *a, **kw):
            total += len(chunk)
            if total > MAX_DB_BYTES: raise SystemExit(76)
            yield chunk
    httpx.AsyncClient.send, httpx.Client.send, httpx.Response.aiter_bytes = send, sync, chunks
    return debit


def install_bound_account(pool_class, bound, platform, httpx):
    """Use the upstream account model, but never import its all-clients fallback."""
    async def load(pool):
        from pkg.account_pool.pool import AccountInfoModel, AccountStatusEnum
        if pool._platform_name != platform: raise SystemExit(78)
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = await client.get(bound['cookiebridge_url']+'/api/cookies/'+platform,
                                        params={'client_id': bound['client_id']})
            response.raise_for_status()
            payload = response.json()
        data = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(data, dict) or payload.get('isok') is not True or data.get('valid') is False or not isinstance(data.get('cookies'), str) or not data['cookies']:
            raise SystemExit(77)
        if data.get('client_id') != bound['client_id'] or data.get('platform') != platform:
            raise SystemExit(78)
        # Native upstream account validation still runs. Cookie presence is not login proof.
        pool.add_account(AccountInfoModel(id=1, account_name='bound-local-client', cookies=data['cookies'],
                                         status=AccountStatusEnum.NORMAL.value, platform_name=platform))
    pool_class.load_accounts_from_cookie_bridge = load


async def run_upstream(upstream):
    """Close the pinned SQLite connection before asyncio tears down its loop."""
    failed = False
    try:
        return await upstream.main()
    except BaseException:
        failed = True
        raise
    finally:
        # Upstream's tail close is skipped by SystemExit/cancellation. Its context
        # belongs to this task, and an unclosed aiosqlite thread prevents exit.
        from var import media_crawler_db_var
        database = media_crawler_db_var.get(None)
        if database is not None and getattr(database, '_conn', None) is not None:
            try:
                import db
                await db.close()
            except BaseException:
                if not failed:
                    raise


async def run_upstream_bounded(upstream,timeout):
    # Carry deliberate process exits out of wait_for's child task before raising.
    async def attempt():
        try:return True,await run_upstream(upstream)
        except (SystemExit,CursorStalled) as error:return False,error
    succeeded,value=await asyncio.wait_for(attempt(),timeout=timeout)
    if not succeeded:raise value
    return value


def execute(run, manifest):
    """Runs in the runner-owned child process, never in the dashboard process."""
    m = bridge()
    run = Path(run).resolve()
    selected, request = manifest['executor'], manifest['request']
    root = Path(selected['root'])
    # Recheck provenance immediately before code execution, not only at selection.
    probe(root)
    os.chdir(run)
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_DB_BYTES, MAX_DB_BYTES))
    os.environ.update(VOX_ACQUISITION_ID=manifest['run_id'], VOX_ACQUISITION_PLATFORM=request['platform'],
                      VOX_CRAWLER_PARENT_PID=os.environ['CROWD_MC_SUPERVISOR_PID'],
                      VOX_ACQUISITION_RESUME='0', DB_TYPE='sqlite', SQLITE_DB_PATH=str(run/DB_NAME),
                      SAVE_DATA_OPTION='db', ACCOUNT_POOL_SAVE_TYPE='cookie_bridge', ENABLE_LOG_FILE='false')
    sink = ProgressSink(run, manifest)
    parent = int(os.environ['CROWD_MC_SUPERVISOR_PID'])
    account_hook=None
    finished = threading.Event()
    def watch_parent():
        while not finished.wait(.5):
            if os.getppid() != parent:
                os._exit(74)  # Never leave an orphan issuing requests before upstream initialization.
    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            import config
            # Pinned clients capture this value at import, before main parses CLI.
            config.PER_NOTE_MAX_COMMENTS_COUNT = request['max_comments']
            config.SAVE_DATA_OPTION = 'db'
            config.DB_TYPE, config.SQLITE_DB_PATH = 'sqlite', str(run/DB_NAME)
            config.USE_CACHE_TYPE, config.CHECKPOINT_STORAGE_TYPE = 'memory', 'file'
            config.ACCOUNT_POOL_SAVE_TYPE = 'cookie_bridge'
            config.COOKIE_BRIDGE_URL = selected['binding']['cookiebridge_url']
            config.ENABLE_IP_PROXY, config.ENABLE_LOG_FILE = False, False
            config.MAX_CONCURRENCY_NUM, config.START_PAGE = 1, request['start_page']
            config.SPECIFIED_CHECKPOINT_ID = manifest['run_id']
            if 'interval_seconds' in request: config.CRAWLER_TIME_SLEEP = request['interval_seconds']
            sign = urlsplit(selected['binding']['sign_url'])
            config.SIGN_SRV_HOST, config.SIGN_SRV_PORT = sign.hostname, str(sign.port)
            import httpx
            debit = install_transport_limits(httpx, request, sink, lambda response: account_hook.observe_response(response) if account_hook else None)
            # SignSrv uses aiohttp, so include those attempts in the same fixed budget.
            import aiohttp
            old_aio = aiohttp.ClientSession._request
            async def bounded_aio(client, *a, **kw):
                debit()
                return await old_aio(client, *a, **kw)
            aiohttp.ClientSession._request = bounded_aio
            from pkg.account_pool.pool import AccountPoolManager
            install_bound_account(AccountPoolManager, selected['binding'], request['platform'], httpx)
            import main as upstream
            clients = {'xhs': ('media_platform.xhs.client', 'XiaoHongShuClient'),
                       'bili': ('media_platform.bilibili.client', 'BilibiliClient'),
                       'dy': ('media_platform.douyin.client', 'DouYinApiClient')}
            import importlib
            module, name = clients[request['platform']]
            client_type = getattr(importlib.import_module(module), name)
            if request['platform'] == 'bili' and request['comments']:
                from repo.platform_save_data import bilibili as store
                from repo.checkpoint.checkpoint_store import CheckpointRepoManager
                BiliPagination(run, manifest).install(client_type, store, CheckpointRepoManager)
            elif request['platform'] in ('xhs','dy') and request['comments']:
                from pro_cursor_pages import CursorPagination
                store=importlib.import_module('repo.platform_save_data.'+('xhs' if request['platform']=='xhs' else 'douyin'))
                from repo.checkpoint.checkpoint_store import CheckpointRepoManager
                CursorPagination(run,manifest,sys.modules[__name__]).install(client_type,store,CheckpointRepoManager)
            from pro_account_sessions import install_pro_account_hooks
            def account_event(account_state,account):
                unsupported=account.get('identity_status')=='pro_self_check_unsupported'
                phase='failed' if unsupported else 'waiting_login' if account_state in ('logged_out','waiting_login','identity_unverified','account_changed','check_failed') else 'running'
                fields={'phase':phase,'account_state':account_state,
                        'account_generation':account.get('generation',0),
                        'account_identity_status':account.get('identity_status','unverified')}
                if unsupported:fields['failure_reason']='pro_self_check_unsupported'
                sink.update(**fields)
            from account_sessions import AccountSessions
            prior_account=AccountSessions(run.parent.parent).status(request['session_id'],request['platform'])
            if prior_account.get('pending_run_id') not in (None,manifest['run_id']) and not prior_account.get('account_ref'):
                sink.update(phase='failed',account_state='identity_unverified',account_identity_status='baseline_unverified',
                            failure_reason='pro_pending_run_resolution_required')
                raise SystemExit(85)
            account_hook=install_pro_account_hooks(run.parent.parent,request['session_id'],request['platform'],
                manifest['run_id'],account_event,httpx,client_type)
            sys.argv = [str(root/'main.py'), *argv_for(request)]
            asyncio.run(run_upstream_bounded(upstream,request['timeout_seconds']))
            result = completion(run, manifest, sink.summary)
            m.write(run/'pro-completion.json', result)
            sink.update(**result)
    except CursorStalled:
        sink.update(phase='failed',failure_reason='pro_pagination_cursor_stalled')
        raise SystemExit(74)
    except (ModuleNotFoundError, ImportError):
        sink.update(phase='failed', failure_reason='dependency_missing')
        raise SystemExit(72)
    except SystemExit as error:
        if error.code==77:
            progress=m.safe_phase_progress(run)
            if isinstance(progress,dict) and progress.get('account_identity_status')=='pro_self_check_unsupported':
                raise SystemExit(84)
        raise
    except Exception as exc:
        sink.update(phase='failed', failure_reason=str(exc) if isinstance(exc, m.BridgeError) else 'pro_executor_error')
        raise SystemExit(74)
    finally:
        if account_hook is not None:account_hook.restore()
        finished.set()
