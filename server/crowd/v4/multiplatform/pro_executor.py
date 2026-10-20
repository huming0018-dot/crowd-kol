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
from pro_tieba_adapter import TiebaStop
import re
import resource
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from pro_cursor_pages import CursorStalled
from pro_douyin_entry import DouyinStop
from pro_session_identity import SessionScopeError
from pro_weibo_adapter import WeiboAdapterStop
from managed_pro_signer import SignerError

PROTOCOL = 'vox-acquisition-v1'
PINNED_COMMIT = 'd32dd565277116ba4880c28ccd417a7c376cb62d'
from pro_zhihu_adapter import ZhihuStop

NATIVE_SUPPORTED = ('xhs', 'dy', 'bili')
SUPPORTED = NATIVE_SUPPORTED + ('wb','zhihu')
DB_NAME = 'pro-observations.sqlite3'
MAX_DB_BYTES = 104857600
MAX_ROWS = 10000
_BRIDGE_FETCH = ContextVar('crowd_pro_bound_bridge_fetch',default=None)


def bridge():
    import mc_runner
    return mc_runner


def supports_bili_audio_request(request):
    """Exact first fully wired media scope; activation requires cloud/adoption gates."""
    options=request.get('platform_options')
    return (request.get('platform')=='bili' and request.get('mode')=='detail'
            and type(request.get('max_items')) is int and request['max_items']==1
            and request.get('media') is True and request.get('wordcloud',False) is False
            and isinstance(options,dict) and set(options)=={'quality','long_audio'}
            and type(options.get('quality')) is int and options['quality']==16
            and options.get('long_audio') is True)


def explicit_unsupported(request, environ=None, *, native_comments=None):
    """Explicit task engines never silently substitute a different collector."""
    if request.get('platform')=='dy' and request.get('mode') in ('homefeed','trending'):
        if not dy_scope_enabled(request,environ):return 'pro_dy_discovery_disabled'
    if request.get('platform')=='zhihu' and (request.get('mode')!='detail' or request.get('max_items')!=1 or request.get('media') is not False or request.get('platform_options')!={}):
        return 'pro_zhihu_candidate_scope_unsupported'
    if request.get('platform') not in SUPPORTED:
        return 'pro_operation_platform_not_adapted'
    if request.get('mode') not in ('search','detail','creator') and not (request.get('platform')=='dy' and request.get('mode') in ('homefeed','trending')):
        return 'pro_mode_unsupported'
    audio_supported=supports_bili_audio_request(request)
    from pro_hybrid_media import supports_weibo_images
    wb_images_supported=supports_weibo_images(request)
    if request.get('media') and not (audio_supported or wb_images_supported or dy_scope_enabled(request,environ)):
        return 'pro_media_pipeline_unavailable'
    if request.get('wordcloud') or request.get('platform_options') and not audio_supported:
        return 'pro_options_unsupported'
    if request.get('comments') and request.get('max_comments') == 0 and native_comments is None:
        return 'pro_zero_comments_means_unlimited'
    return None



def owner_task_capabilities():
    """Code-level exact Pro task support, not upstream factory support or login proof."""
    platforms=[]
    for platform in bridge().PLATFORMS:
        modes=[]
        for mode in ('search','detail','creator'):
            request={'platform':platform,'mode':mode,'max_items':1 if mode=='detail' else 20,
                     'comments':False,'replies':False,'media':False,'wordcloud':False,'platform_options':{}}
            reason=explicit_unsupported(request)
            modes.append({'id':mode,'adapted':reason is None,'reason':reason})
        platforms.append({'id':platform,'adapter_state':'adapted' if platform in SUPPORTED else 'not_adapted',
                          'modes':modes,'upstream_support':'not_inferred_from_adapter'})
    return {'schema':'crowd-owner-pro-capabilities-v1','default_new_owner_executor':'pro',
            'platforms':platforms,'scope':'body_without_media_or_options',
            'exact_request_validation_required':True,'account_verified':False,'source_actions_started':0}


def task_installation(root, request):
    """Operator installation metadata only; no process-wide executor mutation."""
    if request.get('source_executor') != 'pro':
        return None
    m=bridge();path=Path(root)/'pro-executor.json'
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except OSError:m.fail('pro_task_installation_missing')
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                or info.st_uid != os.getuid() or not 0 < info.st_size <= 16384):
            m.fail('pro_task_installation_invalid')
        raw=os.read(fd,16385)
        after=os.fstat(fd)
        if (len(raw)!=info.st_size or len(raw)>16384 or
                (info.st_size,info.st_mtime_ns,info.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns)):
            m.fail('pro_task_installation_invalid')
        value=json.loads(raw.decode('utf-8'))
    except (OSError,ValueError,UnicodeError,RecursionError):m.fail('pro_task_installation_invalid')
    finally:os.close(fd)
    if not isinstance(value,dict) or set(value)!={'root','python'}:
        m.fail('pro_task_installation_invalid')
    for field in ('root','python'):
        if not isinstance(value[field],str) or not value[field] or len(value[field])>4096:
            m.fail('pro_task_installation_invalid')
        p=Path(value[field])
        if not p.is_absolute() or (field=='root' and p.is_symlink()) or (not p.is_dir() if field=='root' else not p.is_file() or not os.access(p,os.X_OK)):
            m.fail('pro_task_installation_invalid')
    return value


def resolved_comment_options(runtime_root):
    """Read only the installed Pro config, with its own Python. No account/source call."""
    installation=task_installation(runtime_root,{'source_executor':'pro'})
    info=bridge().source_info(Path(installation['root']))
    if info.get('commit')!=PINNED_COMMIT or info.get('dirty'):bridge().fail('pro_source_changed')
    script="import sys,json;sys.path.insert(0,sys.argv[1]);import config;print(json.dumps({k:getattr(config,n)for k,n in [('comments','ENABLE_GET_COMMENTS'),('replies','ENABLE_GET_SUB_COMMENTS'),('max_comments','PER_NOTE_MAX_COMMENTS_COUNT')]}))"
    result=subprocess.run([installation['python'],'-c',script,installation['root']],cwd=installation['root'],capture_output=True,text=True,timeout=15)
    if result.returncode or len(result.stdout.encode())>4096:bridge().fail('pro_native_options_unavailable')
    try:
        from participant_pro_comments import options
        return options(json.loads(result.stdout))
    except (ValueError,TypeError):bridge().fail('pro_native_options_unavailable')

def selection(request, environ=None, installation=None, *, native_comments=None):
    """Only fall back BEFORE creating a run; an uncertain Pro run never reruns MC."""
    env = os.environ if environ is None else environ
    explicit = 'source_executor' in request
    requested = request.get('source_executor', env.get('CROWD_EXECUTOR', 'mc'))
    if requested not in ('mc', 'pro'):
        bridge().fail('invalid_executor_selection')
    if requested == 'mc':
        return {'backend': 'mc', 'requested_backend': 'mc'}
    if explicit:
        reason=explicit_unsupported(request,env,native_comments=native_comments)
        if reason:bridge().fail(reason)
        if not installation:bridge().fail('pro_task_installation_missing')
        return {'backend':'pro','requested_backend':'pro','root':str(Path(installation['root']).resolve()),'python':installation['python'],**({'session_identity_mode':'fixed_original_session_v1','dy_sign_mode':'installed_pure_js_v1'} if dy_scope_enabled(request,env) else {})}
    reason = None
    if request['platform']=='zhihu':
        reason='pro_zhihu_adapter_explicit_only'
    elif request['platform'] == 'wb' and env.get('CROWD_PRO_WEIBO_ENABLED') != '1':
        reason = 'pro_weibo_adapter_not_enabled'
    elif request['platform'] not in SUPPORTED:
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
    if result.returncode or not isinstance(caps, dict) or caps.get('schema_version') != PROTOCOL or not set(NATIVE_SUPPORTED) <= set(caps.get('platforms', [])):
        m.fail('pro_protocol_incompatible')
    return {**info, 'executor': 'mediacrawler_pro', 'protocol': PROTOCOL,
            'native_protocol_platforms': sorted(caps['platforms']),
            'local_adapter_platforms': ['wb']}


def binding_for(root, request):
    """A local operator binds ONE client explicitly; never select the first account."""
    m = bridge()
    path = Path(root)/'sessions'/request['session_id']/'pro-binding.json'
    if not path.is_file() or path.is_symlink():
        m.fail('pro_account_binding_required')
    value = m.read(path)
    if isinstance(value,dict) and set(value)=={'platform','provider'} and value.get('provider')=='existing_cdp':
        if value.get('platform')!='bili' or request['platform']!='bili':m.fail('pro_native_provider_platform_unsupported')
        return value
    if isinstance(value,dict) and set(value)=={'platform','provider'} and value.get('provider')=='native_persistent':
        if value.get('platform') not in ('wb','zhihu','bili') or request['platform']!=value.get('platform'):m.fail('pro_native_provider_platform_unsupported')
        return value
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
    python = Path(chosen.get('python') or os.environ.get('CROWD_PRO_PYTHON', str(external/'.venv/bin/python')))
    if not python.is_absolute() or not python.is_file():
        m.fail('pro_python_missing')
    extra={}
    from pro_bili_wbi import bridge_local_mode,LOCAL_MODE
    if bridge_local_mode(root,request,bound):extra['bili_wbi_mode']=LOCAL_MODE
    return {**chosen, 'python': str(python), 'protocol': PROTOCOL, 'binding': bound,**extra}, source, python


def dy_scope_enabled(request, environ=None):
    # New audited scope is opt-in. Preserve existing search/detail/creator path.
    from pro_douyin_entry import supports
    env=os.environ if environ is None else environ
    from dy_task_scope import supports as owner_supported
    return ((owner_supported(request) or env.get('CROWD_PRO_DY_DISCOVERY_ENABLED')=='1') and supports(request)
            and request.get('comments') is True and request.get('replies') is True and request.get('media') is True)


def dy_scope_bound(manifest):
    # Readback follows the durable selected engine, independent of later flag changes.
    from pro_douyin_entry import supports
    selected=manifest.get('executor',{});request=manifest['request']
    return (selected.get('session_identity_mode')=='fixed_original_session_v1'
            and selected.get('dy_sign_mode')=='installed_pure_js_v1' and supports(request)
            and request.get('comments') is True and request.get('replies') is True and request.get('media') is True)


def upstream_mode(request):
    # Keep the canonical task mode; only the upstream protocol uses hot_search.
    return 'hot_search' if request['mode']=='trending' else request['mode']


def argv_for(request):
    m = bridge()
    args = ['--platform', request['platform'], '--type', upstream_mode(request), '--enable_checkpoint',
            '--max_notes_count', str(request['max_items']), '--max_comments_count', str(request['max_comments']),
            '--enable_comments' if request['comments'] else '--no-enable_comments',
            '--enable_sub_comments' if request['replies'] else '--no-enable_sub_comments']
    if request['mode']=='trending':
        # Native hot-search ignores max_notes_count; constrain both native axes.
        args += ['--hot_search_max_items', '1', '--hot_search_per_item_count', str(request['max_items'])]
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
    if not isinstance(value, dict) or value.get('id') != manifest['run_id'] or value.get('platform') != p['platform'] or value.get('mode') != upstream_mode(p):
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
    if manifest['request']['platform']=='tieba':
        from pro_tieba_entry import read_scope
        scope=read_scope(run,manifest,sys.modules[__name__])
        return {'operation_id':manifest['run_id'],'local_committed':True,'task_scope_committed':True,'platform_exhausted':scope['platform_exhausted'],'cloud_ack':False,'content_count':1,'comment_count':scope['source_rows']-1,'coverage':scope['coverage']['coverage']}
    m = bridge()
    cp = checkpoint(run, manifest)
    rows = observations(run, manifest)
    p = manifest['request']
    topics = {entity for kind, entity, _ in rows if kind == 'topic'}
    if not isinstance(summary, dict) or summary.get('status') != 'completed' or summary.get('operation_id') != manifest['run_id'] or summary.get('platform') != p['platform'] or summary.get('crawler_type') != upstream_mode(p):
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
    if (p['platform'] in ('wb','zhihu') or dy_scope_bound(manifest)) and p['comments']:
        coverage=pagination_summary(run,manifest)
        if coverage.get('coverage') not in ('exhausted','limit_reached'):
            m.fail('pro_zhihu_pagination_partial' if p['platform']=='zhihu' else 'pro_weibo_pagination_partial' if p['platform']=='wb' else 'run_failure_unclassified')
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
    wb_targets={}
    if p=='wb' and manifest['request']['comments']:
        from pro_weibo_adapter import WeiboPagination
        pages=WeiboPagination(run,manifest,m).pages
        comments={identity:row for kind,identity,row in rows if kind=='comment'}
        for page in pages:
            targets=page.get('targets',{})
            if not isinstance(targets,dict):m.fail('pro_weibo_reply_target_invalid')
            for identity,target in targets.items():
                row=comments.get(identity,{})
                if (page.get('scope')!='reply' or page.get('saved') is not True or identity not in page.get('ids',[]) or
                    type(target) is not str or not re.fullmatch(r'[1-9][0-9]{0,29}',target) or
                    str(row.get('note_id'))!=page.get('content_id') or str(row.get('parent_comment_id'))!=page.get('parent_id') or
                    target!=page.get('parent_id') and (target not in comments or str(comments[target].get('parent_comment_id'))!=page.get('parent_id'))):
                    m.fail('pro_weibo_reply_target_invalid')
                if identity in wb_targets and wb_targets[identity]!=target:m.fail('pro_weibo_reply_target_conflict')
                wb_targets[identity]=target
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
        if p=='wb' and kind=='comment' and entity in wb_targets:record['platform_fields']['target_comment_id']=wb_targets[entity]
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
    if manifest['request'].get('media') and manifest['request'].get('source_executor')=='pro':
        from pro_media_integration import summary
        result=summary(run,manifest)
        evidence['media_evidence']='hybrid_result_verified_at_import' if result else 'hybrid_missing_or_failed_source_preserved'
        evidence['media_state']=result['state'] if result else 'failed_or_unknown'
    if p=='tieba':
        from pro_tieba_entry import read_scope
        if (Path(run)/'tieba-task-scope.json').exists():
            scope=read_scope(run,manifest,sys.modules[__name__]);evidence.update(local_committed=True,task_scope_committed=True,platform_exhausted=scope['platform_exhausted'],pagination_evidence='typed_journal_original_checkpoint_reread')
        evidence['pagination']=pagination_summary(run,manifest)
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
    if manifest['request']['platform']=='tieba':
        from pro_tieba_entry import summary
        return summary(run,manifest,sys.modules[__name__])
    """Coverage evidence is separate from upstream commit and cloud delivery."""
    if manifest['request']['platform']=='zhihu':
        from pro_zhihu_adapter import pagination_summary as zhihu_summary
        return zhihu_summary(run,manifest,sys.modules[__name__])
    if manifest['request']['platform']=='wb':
        import pro_weibo_adapter
        return pro_weibo_adapter.pagination_summary(run,manifest,sys.modules[__name__])
    if dy_scope_bound(manifest):
        from pro_douyin_entry import summary as dy_summary
        return dy_summary(run,manifest,sys.modules[__name__])
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


def sync_request_budget(run,manifest,sink):
    # Media owns the same durable ledger in another process. Its debits do not
    # update this parent's in-memory sink; publish the ledger at every exit.
    request=manifest['request']
    if request.get('source_executor')!='pro':return
    current=bridge().safe_phase_progress(run);fields={'phase':current.get('phase','failed')}
    try:
        if (not (run/'request-budget.json').exists() and getattr(sink,'request_budget_setup_started',None)is False and type(sink.attempts)is int and sink.attempts==0 and type(current.get('api_attempts'))is int and current['api_attempts']==0):
            # The pinned executor installs this guard before any source/bridge/signer HTTP.
            # A pre-install import/config failure has made no transport attempt.
            fields['api_attempts_unverified']=False
            sink.update(**fields)
            return
        from shared_request_budget import RunRequestBudget,request_fingerprint
        sink.attempts=RunRequestBudget(run/'request-budget.json',manifest['run_id'],request_fingerprint(request),request['max_api_requests']).snapshot()['used']
        fields['api_attempts_unverified']=False
    except (OSError,ValueError,KeyError,TypeError):
        fields.update(api_attempts=None,api_attempts_unverified=True)
    try:sink.update(**fields)
    except (OSError,ValueError):pass  # Preserve original control exit/cancellation.

class ProgressSink:
    """Discard upstream logs; persist only allowlisted protocol progress."""
    def __init__(self, run, manifest):
        self.run, self.manifest, self.buffer, self.summary = Path(run), manifest, '', None
        self.attempts = 0
        self.request_budget_setup_started = None
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
                        if self.manifest['request']['platform']=='tieba':self.summary['tieba_expected_limit_failure']=value.get('error')=='部分评论未采集成功，已保留断点'
                except (ValueError, TypeError, AttributeError):
                    continue
        return len(text)

    def flush(self): pass
    def isatty(self): return False


def _observe_transport(steps, stage, attempt, status=0, sink=None):
    if steps is None:
        return
    try:
        steps.emit(stage, api_attempts=attempt, http_status=status if type(status) is int else 0)
    except Exception:
        # Monitoring must never issue another source request or suppress delivery.
        steps.error = 'pro_transport_monitor_failed'
    if steps.error and sink is not None:
        try:
            sink.update(source_monitor_error='pro_steps_observation_failed')
        except Exception:
            pass  # A failed diagnostic write must not retry or cancel the source.


def install_aio_transport(aiohttp, request, debit, native_steps=None, sink=None):
    original = aiohttp.ClientSession._request
    async def bounded(client, *args, **kwargs):
        if request.get('source_executor') == 'pro':
            kwargs['allow_redirects'] = False
            if hasattr(client, '_retry_connection'):
                client._retry_connection = False
        attempt = debit()
        _observe_transport(native_steps, 'request_started', attempt, sink=sink)
        try:
            response = await original(client, *args, **kwargs)
        except BaseException:
            _observe_transport(native_steps, 'request_failed', attempt, sink=sink)
            raise
        _observe_transport(native_steps, 'response_received', attempt, response.status, sink=sink)
        if request.get('source_executor') == 'pro' and type(response.status) is int and 300 <= response.status <= 399:
            from shared_request_budget import BudgetError
            raise BudgetError('request_budget_redirect_forbidden')
        return response
    aiohttp.ClientSession._request = bounded


def install_transport_limits(httpx, request, sink, self_observer=None, debit_callback=None, native_steps=None):
    """Count every attempt including CookieBridge/signing; stop before overflow."""
    original_async, original_sync = httpx.AsyncClient.send, httpx.Client.send
    original_bytes = httpx.Response.aiter_bytes
    total = 0
    shared=None
    if request.get('source_executor') == 'pro' and debit_callback is None:
        from shared_request_budget import RunRequestBudget,request_fingerprint
        sink.request_budget_setup_started=True
        shared=RunRequestBudget(sink.run/'request-budget.json',sink.manifest['run_id'],request_fingerprint(request),request['max_api_requests'],create=True)
        sink.attempts=shared.snapshot()['used']
    def debit():
        if debit_callback is not None:
            return debit_callback()
        if shared is not None:
            try:sink.attempts=shared.debit('pro')
            except SystemExit:
                sink.update(phase='stopping',failure_reason='api_request_limit');raise
            sink.update();return sink.attempts
        if sink.attempts >= request['max_api_requests']:
            sink.update(phase='stopping', failure_reason='api_request_limit')
            raise SystemExit(73)
        sink.attempts += 1
        sink.update()
        return sink.attempts
    def check_response(response):
        if _is_bound_bridge_response(response):return  # Bound loader classifies local availability, never platform logout.
        if (shared is not None or debit_callback is not None) and type(response.status_code) is int and 300<=response.status_code<=399:
            from shared_request_budget import BudgetError
            raise BudgetError('request_budget_redirect_forbidden')
        if self_observer is not None:self_observer(response)
        if request.get('platform')=='zhihu' and response.status_code==403:
            from login_recovery_freshness import zhihu_content_denied
            if zhihu_content_denied(response):
                sink.update(phase='failed',failure_reason='pro_content_access_denied')
                raise SystemExit(87)
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
        if shared is not None or debit_callback is not None:kw['follow_redirects']=False
        attempt = debit()
        _observe_transport(native_steps, 'request_started', attempt, sink=sink)
        try:
            response = await original_async(client, *a, **kw)
        except BaseException:
            _observe_transport(native_steps, 'request_failed', attempt, sink=sink)
            raise
        _observe_transport(native_steps, 'response_received', attempt, response.status_code, sink=sink)
        check_response(response)
        return response
    def sync(client, *a, **kw):
        if shared is not None or debit_callback is not None:kw['follow_redirects']=False
        attempt = debit()
        _observe_transport(native_steps, 'request_started', attempt, sink=sink)
        try:
            response = original_sync(client, *a, **kw)
        except BaseException:
            _observe_transport(native_steps, 'request_failed', attempt, sink=sink)
            raise
        _observe_transport(native_steps, 'response_received', attempt, response.status_code, sink=sink)
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


def _is_bound_bridge_response(response):
    bound=_BRIDGE_FETCH.get()
    if bound is None:return False
    try:
        u=urlsplit(str(response.request.url));base=urlsplit(bound['cookiebridge_url'])
        return (u.scheme==base.scheme and u.hostname==base.hostname and u.port==base.port
                and not u.username and not u.password and not u.fragment
                and u.path==base.path.rstrip('/')+'/api/cookies/'+bound['platform']
                and list(response.request.url.params.multi_items())==[('client_id',bound['client_id'])])
    except (TypeError,ValueError,AttributeError):return False


def install_bound_account(pool_class, bound, platform, httpx, *, sink=None):
    """Bridge availability is distinct from the native official login proof."""
    def unavailable(reason, response=None, payload=None):
        fields={'phase':'failed','failure_reason':'pro_cookiebridge_unavailable',
                'bridge_stage':'bound_cookie_fetch','bridge_reason':reason}
        if response is not None and type(response.status_code) is int and 100<=response.status_code<=599:
            fields['bridge_http_status']=response.status_code
        code=payload.get('biz_code') if isinstance(payload,dict) else None
        if type(code) is int and code in (0,1,2,3,4,100,101,102,103):fields['bridge_business_code']=code
        try:
            if sink is not None:sink.update(**fields)
        except Exception:pass  # Best-effort failure diagnostics cannot turn bridge refusal into a different ordinary error.
        raise SystemExit(86)
    async def load(pool):
        from pkg.account_pool.pool import AccountInfoModel, AccountStatusEnum
        if pool._platform_name != platform:raise SystemExit(78)
        token=_BRIDGE_FETCH.set({**bound,'platform':platform})
        try:
            try:
                async with httpx.AsyncClient(timeout=10,follow_redirects=False,trust_env=False) as client:
                    response=await client.get(bound['cookiebridge_url']+'/api/cookies/'+platform,
                                              params={'client_id':bound['client_id']})
            except httpx.RequestError:unavailable('transport_error')
            if response.status_code!=200:unavailable('http_error',response)
            try:payload=response.json()
            except (ValueError,UnicodeError,RecursionError):unavailable('invalid_response',response)
            if not isinstance(payload,dict):unavailable('invalid_response',response)
            if payload.get('isok') is not True:
                code=payload.get('biz_code')
                reason={100:'extension_disconnected',101:'cookies_missing',102:'bridge_request_timeout',103:'bound_account_missing'}.get(code,'business_error') if type(code) is int else 'business_error'
                unavailable(reason,response,payload)
            data=payload.get('data')
            if not isinstance(data,dict):unavailable('invalid_response',response,payload)
            if not isinstance(data.get('client_id'),str) or not data['client_id'] or not isinstance(data.get('platform'),str) or not data['platform']:unavailable('invalid_response',response,payload)
            if data.get('client_id')!=bound['client_id'] or data.get('platform')!=platform:raise SystemExit(78)
            if data.get('valid') is False:unavailable('bridge_cookie_marked_invalid',response,payload)
            if not isinstance(data.get('cookies'),str) or not data['cookies']:unavailable('cookies_missing',response,payload)
            # Cookie presence is transport readiness only; original official self still runs.
            pool.add_account(AccountInfoModel(id=1,account_name='bound-local-client',cookies=data['cookies'],
                status=AccountStatusEnum.NORMAL.value,platform_name=platform))
        finally:_BRIDGE_FETCH.reset(token)
    pool_class.load_accounts_from_cookie_bridge=load


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
        except (SystemExit,CursorStalled,WeiboAdapterStop,TiebaStop,DouyinStop,SessionScopeError) as error:return False,error
    succeeded,value=await asyncio.wait_for(attempt(),timeout=timeout)
    if not succeeded:raise value
    return value


def execute(run, manifest, *, mc_root=None):
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
    sink.request_budget_setup_started = False  # Only this execute invocation may prove pre-install zero.
    from mc_source_steps import NativeSteps
    native_steps = NativeSteps(run, manifest['run_id'], request['platform'])
    parent = int(os.environ['CROWD_MC_SUPERVISOR_PID'])
    account_hook=None
    participant_hook=None
    tieba_curl=None
    bili_wbi=None
    seed_hook=None
    dy_sign=None
    from pro_media_integration import MediaStage
    media_stage=MediaStage(request)
    execution_deadline=time.monotonic()+request['timeout_seconds']
    pagination_hook=None
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
            import config.base_config as base_config
            base_config.PER_NOTE_MAX_COMMENTS_COUNT = request['max_comments']
            config.SAVE_DATA_OPTION = 'db'
            config.DB_TYPE, config.SQLITE_DB_PATH = 'sqlite', str(run/DB_NAME)
            config.USE_CACHE_TYPE, config.CHECKPOINT_STORAGE_TYPE = 'memory', 'file'
            config.ACCOUNT_POOL_SAVE_TYPE = 'cookie_bridge'
            native_provider=selected['binding'].get('provider') in ('native_persistent','existing_cdp')
            if not native_provider:config.COOKIE_BRIDGE_URL = selected['binding']['cookiebridge_url']
            config.ENABLE_IP_PROXY, config.ENABLE_LOG_FILE = False, False
            config.MAX_CONCURRENCY_NUM, config.START_PAGE = 1, request['start_page']
            config.SPECIFIED_CHECKPOINT_ID = manifest['run_id']
            if manifest.get('participant_pro') is not None:
                if manifest['participant_pro'].get('search_sort')!='time_descending':raise SystemExit(78)
                config.SORT_TYPE='time_descending'  # Original XHS SearchSortType.LATEST.
            if 'interval_seconds' in request: config.CRAWLER_TIME_SLEEP = request['interval_seconds']
            if not native_provider:
                sign = urlsplit(selected['binding']['sign_url'])
                config.SIGN_SRV_HOST, config.SIGN_SRV_PORT = sign.hostname, str(sign.port)
            if native_provider and request['platform']=='zhihu':
                config.SIGN_SRV_HOST,config.SIGN_SRV_PORT='127.0.0.1','8990'
            import httpx
            if request['platform']=='bili' and (native_provider or selected.get('bili_wbi_mode') is not None):
                if not native_provider:
                    from pro_bili_wbi import bridge_local_mode,LOCAL_MODE
                    if selected.get('bili_wbi_mode')!=LOCAL_MODE or not bridge_local_mode(run.parent.parent,request,selected['binding']):raise SystemExit(86)
                from pro_bili_wbi import BiliWbi
                from pkg.rpc.sign_srv_client import SignServerClient
                try:bili_wbi=BiliWbi(run,request,sink);bili_wbi.install(SignServerClient);media_stage.bili_wbi=bili_wbi
                except ValueError:
                    sink.update(phase='failed',failure_reason='pro_bili_wbi_unavailable');raise SystemExit(86) from None
            def observe_response(response):
                if account_hook:account_hook.observe_response(response)
                if bili_wbi:
                    try:bili_wbi.observe(response)
                    except ValueError:
                        sink.update(phase='failed',failure_reason='pro_bili_wbi_unavailable');raise SystemExit(86) from None
                media_stage.observe(response)
            debit = install_transport_limits(httpx, request, sink, observe_response, native_steps=native_steps)
            # SignSrv uses aiohttp, so include those attempts in the same fixed budget.
            import aiohttp
            install_aio_transport(aiohttp, request, debit, native_steps, sink)
            from pkg.account_pool.pool import AccountPoolManager
            if native_provider:
                if request['platform'] not in ('wb','zhihu','bili'):raise SystemExit(78)
                if selected['binding'].get('provider')=='existing_cdp':
                    from pro_cdp_credentials import install_cdp_account,expected_from_state
                    expected=expected_from_state(run.parent.parent,request['session_id'])
                    install_cdp_account(AccountPoolManager,run.parent.parent,request['session_id'],mc_root,expected,run=run,sink=sink)
                else:
                    from pro_native_credentials import install_native_account
                    install_native_account(AccountPoolManager,run.parent.parent,request['session_id'],mc_root,run=run,sink=sink,**({'platform':request['platform']} if request['platform']!='wb' else {}))
            else:
                install_bound_account(AccountPoolManager, selected['binding'], request['platform'], httpx,sink=sink)
            if request['platform']=='zhihu':
                import acquisition_protocol
                from pro_zhihu_adapter import register_observations
                register_observations(acquisition_protocol)
            if request['platform']=='wb':
                import acquisition_protocol
                from pro_weibo_adapter import prepare as prepare_weibo
                prepare_weibo(config,acquisition_protocol,request)
            if request['platform']=='tieba':
                import acquisition_protocol
                from pro_tieba_adapter import register_observations
                register_observations(acquisition_protocol)
            import main as upstream
            clients = {'xhs': ('media_platform.xhs.client', 'XiaoHongShuClient'),
                       'bili': ('media_platform.bilibili.client', 'BilibiliClient'),
                       'dy': ('media_platform.douyin.client', 'DouYinApiClient'),
                       'wb': ('media_platform.weibo.client','WeiboClient'),
                       'zhihu':('media_platform.zhihu.client','ZhiHuClient'),
                       'tieba':('media_platform.tieba.client','BaiduTieBaClient')}
            import importlib
            module, name = clients[request['platform']]
            client_type = getattr(importlib.import_module(module), name)
            if request['platform'] == 'bili' and request['comments']:
                from repo.platform_save_data import bilibili as store
                from repo.checkpoint.checkpoint_store import CheckpointRepoManager
                BiliPagination(run, manifest).install(client_type, store, CheckpointRepoManager)
            elif request['platform'] in ('xhs','dy') and not dy_scope_bound(manifest) and request['comments']:
                from pro_cursor_pages import CursorPagination
                store=importlib.import_module('repo.platform_save_data.'+('xhs' if request['platform']=='xhs' else 'douyin'))
                from repo.checkpoint.checkpoint_store import CheckpointRepoManager
                CursorPagination(run,manifest,sys.modules[__name__]).install(client_type,store,CheckpointRepoManager)
            if request['platform']=='zhihu':
                from pro_zhihu_adapter import install_detail
                from media_platform.zhihu.handlers.detail_handler import DetailHandler
                pagination_hook=install_detail(run,manifest,sys.modules[__name__],DetailHandler)
            from pro_account_sessions import install_pro_account_hooks
            def account_event(account_state,account):
                unsupported=account.get('identity_status')=='pro_self_check_unsupported'
                phase='failed' if unsupported or account_state=='check_failed' else 'waiting_login' if account_state in ('logged_out','waiting_login','identity_unverified','account_changed') else 'running'
                fields={'phase':phase,'account_state':account_state,
                        'account_generation':account.get('generation',0),
                        'account_identity_status':account.get('identity_status','unverified')}
                if unsupported:fields['failure_reason']='pro_self_check_unsupported'
                elif account_state=='check_failed':fields['failure_reason']='pro_login_verification_failed'
                sink.update(**fields)
            from account_sessions import AccountSessions
            prior_account=AccountSessions(run.parent.parent).status(request['session_id'],request['platform'])
            if prior_account.get('pending_run_id') not in (None,manifest['run_id']) and not prior_account.get('account_ref'):
                sink.update(phase='failed',account_state='identity_unverified',account_identity_status='baseline_unverified',
                            failure_reason='pro_pending_run_resolution_required')
                raise SystemExit(85)
            if dy_scope_bound(manifest):
                from pro_douyin_entry import install_scope,DouyinPagination
                account_hook=install_scope(run.parent.parent,run,manifest,sink,client_type,httpx)
                if selected.get('dy_sign_mode')=='installed_pure_js_v1':
                    from pro_douyin_sign import LocalDouyinSign
                    from pkg.rpc.sign_srv_client import SignServerClient
                    dy_sign=LocalDouyinSign(run,account_hook).install(SignServerClient)
                if request['comments']:
                    from media_platform.douyin.processors.comment_processor import CommentProcessor
                    from repo.platform_save_data import douyin as dy_store
                    pagination_hook=DouyinPagination(run,manifest,sys.modules[__name__],account_hook).install(CommentProcessor,dy_store)
            elif request['platform']=='tieba':
                from pro_tieba_entry import Identity,install_detail
                from pro_tieba_adapter import CurlBudget
                from shared_request_budget import RunRequestBudget,request_fingerprint
                from media_platform.tieba.handlers.detail_handler import DetailHandler
                account_hook=Identity(run.parent.parent,request['session_id'],manifest['run_id'],account_event).install(client_type)
                ledger=RunRequestBudget(run/'request-budget.json',manifest['run_id'],request_fingerprint(request),request['max_api_requests'])
                tieba_curl=CurlBudget(importlib.import_module(module),ledger,native_steps,account_hook.observe_response,sink=sink).install()
                pagination_hook=install_detail(run,manifest,sys.modules[__name__],DetailHandler)
            elif request['platform']=='wb':
                from pro_weibo_adapter import WeiboIdentity,WeiboPagination
                account_hook=WeiboIdentity(run.parent.parent,request['session_id'],manifest['run_id'],account_event).install(client_type,httpx)
                if request['comments']:
                    from media_platform.weibo.processors.comment_processor import CommentProcessor
                    pagination_hook=WeiboPagination(run,manifest,m).install(CommentProcessor)
            else:
                account_hook=install_pro_account_hooks(run.parent.parent,request['session_id'],request['platform'],
                    manifest['run_id'],account_event,httpx,client_type)
            if manifest.get('participant_pro') is not None:
                if request['platform']!='xhs':raise SystemExit(78)
                from participant_pro_hooks import from_context
                participant_hook=from_context(manifest['participant_pro'],client_type,run=run,timeout_seconds=request['timeout_seconds'])
                account_hook.principal_validator=participant_hook.identity
            if manifest.get('source_continuation') is not None:
                if request['platform']!='wb':raise SystemExit(78)
                from pro_weibo_seed import install_seed
                from repo.platform_save_data import weibo as seed_store
                seed_hook=install_seed(run,manifest,sys.modules[__name__],client_type,seed_store)
            sys.argv = [str(root/'main.py'), *argv_for(request)]
            from managed_pro_signer import owned_signer
            # Installed pure DY signing already owns its worker lifecycle; no listener is used.
            signer = contextlib.nullcontext() if dy_sign is not None else owned_signer(run,request,{'platform':'zhihu','sign_url':'http://127.0.0.1:8990'} if native_provider and request['platform']=='zhihu' else selected['binding'])
            with signer:
                asyncio.run(run_upstream_bounded(upstream,request['timeout_seconds']))
            if dy_scope_bound(manifest) and pagination_hook is not None:pagination_hook.rethrow()
            if request['platform']=='tieba':
                from pro_tieba_entry import summary as tieba_summary,finalize_scope
                known=tieba_summary(run,manifest,sys.modules[__name__])
                if known.get('coverage') not in ('exhausted','limit_reached','not_requested'):raise TiebaStop('tieba_task_scope_partial')
                if known['coverage']=='limit_reached' and (not isinstance(sink.summary,dict) or sink.summary.get('status')!='failed' or sink.summary.get('tieba_expected_limit_failure') is not True):raise TiebaStop('tieba_upstream_outcome_unknown')
                if media_stage.enabled:media_stage.run(run,manifest,observations(run,manifest),mc_root=mc_root,remaining=execution_deadline-time.monotonic())
                media_result=__import__('pro_media_integration').summary(run,manifest) if media_stage.enabled else None
                finalize_scope(run,manifest,sys.modules[__name__],media_result['assets'] if media_result else [])
                sink.attempts=RunRequestBudget(run/'request-budget.json',manifest['run_id'],request_fingerprint(request),request['max_api_requests']).snapshot()['used']
                result=completion(run,manifest,sink.summary);m.write(run/'pro-completion.json',result);sink.update(**result);return
            if request['platform']=='wb' and request['comments']:
                accessible=pagination_summary(run,manifest)
                if accessible.get('coverage')=='partial' and accessible.get('reason')=='wb_reply_terminal_incomplete' and accessible.get('independent_selected_roots_visited') is True:
                    # An accessible terminal cannot prove the declared population. Keep
                    # parent checkpoint uncommitted, but finish independent media work.
                    if media_stage.enabled:
                        sink.update(phase='running',media_stage='running',coverage='partial',content_committed=False)
                        media_stage.run(run,manifest,observations(run,manifest),mc_root=mc_root,remaining=execution_deadline-time.monotonic())
                        sink.update(media_stage='completed',content_committed=False)
                    raise WeiboAdapterStop('wb_reply_terminal_incomplete')
            result = completion(run, manifest, sink.summary)
            m.write(run/'pro-completion.json', result)
            # Preserve committed source before media: failed media still imports/ACKs source.
            if media_stage.enabled:
                sink.update(phase='running',media_stage='running',content_committed=True)
                try:
                    media_stage.run(run,manifest,observations(run,manifest),mc_root=mc_root,remaining=execution_deadline-time.monotonic())
                except BaseException:
                    try:sink.update(phase='failed',media_stage='failed_or_unknown',content_committed=True)
                    except (OSError,ValueError):pass
                    raise
                sink.update(media_stage='completed',content_committed=True)
            sink.update(**result)
    except SessionScopeError:
        sink.update(phase='failed',failure_reason='pro_account_changed');raise SystemExit(85)
    except DouyinStop as error:
        sink.update(phase='failed',failure_reason=error.reason,coverage='partial');raise SystemExit(74)
    except TiebaStop as error:
        denied=error.reason=='tieba_content_access_denied'
        sink.update(phase='failed',failure_reason='pro_content_access_denied' if denied else error.reason if re.fullmatch(r'tieba_[a-z_]{1,80}',error.reason) else 'tieba_task_scope_partial',coverage='partial');raise SystemExit(87 if denied else 74)
    except ZhihuStop as error:
        sink.update(phase='failed',failure_reason=error.reason if re.fullmatch(r'zhihu_[a-z_]{1,80}',error.reason) else 'pro_zhihu_pagination_partial',coverage='partial')
        raise SystemExit(74)
    except WeiboAdapterStop as error:
        sink.update(phase='failed',failure_reason=error.reason if re.fullmatch(r'wb_[a-z_]{1,80}',error.reason) else 'pro_weibo_pagination_partial',coverage='partial')
        raise SystemExit(74)
    except CursorStalled:
        sink.update(phase='failed',failure_reason='pro_pagination_cursor_stalled')
        raise SystemExit(74)
    except SignerError as error:
        reason=str(error)
        sink.update(phase='failed',failure_reason=reason if re.fullmatch(r'pro_signer_[a-z_]{1,80}',reason) else 'pro_signer_unavailable')
        raise SystemExit(86)
    except (ModuleNotFoundError, ImportError):
        sink.update(phase='failed', failure_reason='dependency_missing')
        raise SystemExit(72)
    except SystemExit as error:
        if participant_hook is not None and participant_hook.events:
            last=participant_hook.events[-1]
            if last['outcome'] in ('denied','rpc_unknown','deadline','principal_unverified'):
                sink.update(phase='failed',failure_reason='participant_'+last['outcome'],participant_guard_reason=last.get('reason'))
        if error.code==77:
            progress=m.safe_phase_progress(run)
            if isinstance(progress,dict) and progress.get('account_identity_status')=='pro_self_check_unsupported':
                raise SystemExit(84)
        raise
    except Exception as exc:
        sink.update(phase='failed', failure_reason=str(exc) if isinstance(exc, m.BridgeError) else 'pro_executor_error')
        raise SystemExit(74)
    finally:
        sync_request_budget(run,manifest,sink)
        if dy_sign is not None:dy_sign.restore()
        if tieba_curl is not None:tieba_curl.restore()
        if bili_wbi is not None:bili_wbi.restore()
        if seed_hook is not None:seed_hook.restore()
        if pagination_hook is not None:pagination_hook.restore()
        if participant_hook is not None:participant_hook.restore()
        if account_hook is not None:account_hook.restore()
        finished.set()
