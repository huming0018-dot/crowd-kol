"""Durable Bili audio-only postprocessing, separate from collection leases."""
import os
from pathlib import Path
import tempfile
import threading
import time

from analysis_artifact import _read, _safe_ancestors
from mc_runner import read, uid, write, PLATFORMS
from media_native import _identity, _duration

WAITING = {'media_processor_busy', 'media_processor_reconciliation_required'}


class LightTranscripts:
    def __init__(self, root, jobs, run_folder):
        self.root = Path(root) / 'light-transcripts'
        _safe_ancestors(self.root)
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.jobs, self.run_folder = jobs, run_folder
        self.lock = threading.Lock()

    def _path(self, run_id):
        return self.root / (uid(run_id) + '.json')

    def enqueue(self, run_id):
        folder = self.run_folder(uid(run_id))
        manifest, _ = _read(folder / 'manifest.json', 200000)
        request = manifest.get('request', {})
        if request.get('platform_options', {}).get('transcript_only') is not True:
            return None
        status, _ = _read(folder / 'status.json', 200000)
        if (manifest.get('run_id') != run_id or request.get('platform') not in PLATFORMS
                or request.get('platform')=='bili' and request.get('platform_options', {}).get('long_audio') is not True
                or request.get('media') is not True or status.get('run_id') != run_id
                or status.get('state') != 'completed'):
            raise ValueError('light_transcript_source_not_completed')
        normalized, normalized_sha = _read(folder / 'normalized.json', 32 * 1024 * 1024)
        platform=PLATFORMS[request['platform']]
        subtitle_jobs=[]
        caption_folder=folder/('output/bili/subtitles' if platform=='bilibili' else 'output/douyin/subtitles')
        if platform not in ('bilibili','douyin'):
            from declared_subtitles import register
            for body in normalized.get('records',[]):
                if body.get('kind')!='content' or body.get('platform')!=platform:continue
                cid=body.get('content_id');ctype=body.get('content_type') if platform=='zhihu' else None
                stem=cid+('.'+ctype if ctype else '')
                if not (folder/'output'/platform/'declared-subtitles'/(stem+'.json')).is_file():continue
                job=register(self.jobs,folder,cid,ctype)
                subtitle_jobs.append({'content_id':cid,'entity_ref':job['entity_ref'],'job_id':job['job_id'],'state':'completed','kind':'subtitle'})
        if platform in ('bilibili','douyin') and caption_folder.exists():
            import hashlib,uuid
            for caption_path in sorted(caption_folder.glob('*.json')):
                if caption_path.name.endswith('.source.json'):continue
                caption,caption_sha=_read(caption_path,200000)
                if caption.get('status')!='available':continue
                cid=caption.get('content_id')
                if not isinstance(cid,str) or not cid.isdecimal() or caption_path.name!=cid+'.json':raise ValueError('subtitle_source_invalid')
                bodies=[r for r in normalized.get('records',[]) if r.get('platform')==platform and r.get('kind')=='content' and r.get('content_id')==cid]
                if len(bodies)!=1:raise ValueError('subtitle_source_ambiguous')
                identity=str(uuid.uuid5(uuid.UUID(run_id),'subtitle:'+cid+':'+caption_sha))
                directory=self.root.parent/'subtitle-jobs';_safe_ancestors(directory);directory.mkdir(mode=0o700,exist_ok=True)
                state={'job_id':identity,'run_id':run_id,'kind':'subtitle','state':'completed','platform':platform,
                    'content_id':cid,'entity_ref':platform+':content:'+cid,'source_record_hash':bodies[0]['record_hash'],
                    'asset_sha256':caption['subtitle_provenance']['source_body_sha256'],'result_sha256':caption_sha,
                    'input_hash':hashlib.sha256((run_id+':'+cid+':'+caption_sha).encode()).hexdigest(),
                    'processing_profile':'native_bilibili_subtitle_json_v1' if platform=='bilibili' else 'yt_dlp_native_metadata_subtitle_v1','created_at':time.time()}
                target=directory/(identity+'.json')
                created=not target.exists()
                if created:write(target,state)
                if platform=='bilibili':from bili_subtitles import load_job
                else:from native_subtitles import load_job
                try:load_job(self.jobs,identity)
                except (ValueError,KeyError,TypeError,OSError):
                    if created:target.unlink()
                    continue
                subtitle_jobs.append({'content_id':cid,'job_id':identity,'state':'completed','kind':'subtitle'})
        def media_ref(row):
            cid=row.get('content_id');ctype=row.get('source_content_type') if platform=='zhihu' else None
            if not isinstance(cid,str) or platform=='zhihu' and ctype not in ('answer','article','zvideo'):raise ValueError('light_transcript_source_ambiguous')
            return platform+':content:'+cid+(':'+ctype if ctype else '')
        saved_refs={j.get('entity_ref',platform+':content:'+j['content_id']) for j in subtitle_jobs}
        candidates = [r for r in normalized.get('media', []) if isinstance(r, dict) and (r.get('kind') == 'audio' if platform=='bilibili' else r.get('platform')==platform and str(r.get('path','')).endswith('.mp4')) and media_ref(r) not in saved_refs]
        if len(candidates) > 200:raise ValueError('light_transcript_source_ambiguous')
        assets = []
        preferred_engine='mlx' if candidates and 'mlx' in self.jobs.capabilities().get('asr_engines',[]) else 'cpu'
        for row in candidates:
            from media_native import CID, HEX
            if (not isinstance(row.get('content_id'), str) or not CID.fullmatch(row['content_id'])
                    or not isinstance(row.get('sha256'), str) or not HEX.fullmatch(row['sha256'])
                    or type(row.get('bytes')) is not int or not 12 <= row['bytes'] <= 64 * 1024 * 1024):
                raise ValueError('light_transcript_source_ambiguous')
            bodies = [body for body in normalized.get('records', []) if isinstance(body, dict)
                      and body.get('platform') == platform and body.get('kind') == 'content'
                      and body.get('content_id') == row.get('content_id') and (platform!='zhihu' or body.get('content_type')==row.get('source_content_type'))]
            if len(bodies) != 1 or not isinstance(bodies[0].get('record_hash'), str) or not HEX.fullmatch(bodies[0]['record_hash']):raise ValueError('light_transcript_source_ambiguous')
            # Handoff reads metadata only; tick verifies one audio asset before any model start.
            entity_ref=platform+':content:'+row['content_id']
            if platform=='zhihu':
                if bodies[0].get('content_type') not in ('answer','article','zvideo'):raise ValueError('light_transcript_source_ambiguous')
                entity_ref+=':'+bodies[0]['content_type']
            assets.append({'content_id': row.get('content_id'), 'entity_ref': entity_ref,
                           'asset_sha256': row.get('sha256'), 'source_record_hash': bodies[0].get('record_hash'),
                           'normalized_sha256': normalized_sha, 'bytes': row.get('bytes'), 'duration_ms': None,
                           'state': 'waiting', 'job_id': None, 'asr_engine':preferred_engine})
        if len({(r['entity_ref'], r['asset_sha256']) for r in assets}) != len(assets):
            raise ValueError('light_transcript_source_ambiguous')
        path = self._path(run_id)
        with self.lock:
            if path.exists() or path.is_symlink():
                old, _ = _read(path, 200000)
                def bindings(value):return [(r['entity_ref'], r['asset_sha256'], r['source_record_hash']) for r in value]
                if old.get('run_id') != run_id or bindings(old.get('assets', [])) != bindings(assets):
                    raise ValueError('light_transcript_source_changed')
                if not old.get('fallback_assets'):
                    from light_audio_fallback import prepare
                    if prepare(old,folder,self.jobs):write(path,old)
                return old
            state = {'schema_version': 1, 'run_id': run_id, 'platform': platform, 'created_at': time.time(),
                     'mode': 'transcript_only', 'subtitle_state': 'available' if subtitle_jobs else 'not_available_or_partial',
                     'state': 'waiting' if assets else 'completed' if subtitle_jobs else 'audio_unavailable', 'assets': assets, 'subtitle_jobs':subtitle_jobs,
                     'source_requests': 0, 'remote_model_calls': 0}
            if platform=='douyin' and not assets and not subtitle_jobs:
                phase,_=_read(folder/'phase.json',200000) if (folder/'phase.json').exists() else ({},None)
                if phase.get('media_reason')=='single_response_byte_limit':
                    state.update(state='needs_attention',reason='native_video_over_collection_limit',
                        media_status='limited',media_single_file_limit_bytes=64*1024*1024)
            from light_audio_fallback import prepare
            prepare(state,folder,self.jobs)
            write(path, state)
            return state

    def status(self, run_id):
        path = self._path(run_id)
        if not path.exists() and not path.is_symlink():return None
        state=_read(path, 200000)[0]
        if state.get('platform')=='douyin' and not state.get('assets') and not state.get('subtitle_jobs') and not state.get('fallback_assets'):
            folder=self.run_folder(uid(run_id));phase_path=folder/'phase.json'
            if phase_path.exists():
                phase,_=_read(phase_path,200000)
                if phase.get('media_reason')=='single_response_byte_limit':
                    return {**state,'state':'needs_attention','reason':'native_video_over_collection_limit',
                            'media_status':'limited','media_single_file_limit_bytes':64*1024*1024,
                            'diagnostics_source':'saved_collection_phase'}
        return state

    def tick(self):
        if not self.lock.acquire(blocking=False):return
        try:
            for path in sorted(self.root.glob('*.json')):
                state, _ = _read(path, 200000)
                if state.get('run_id') != path.stem or type(state.get('schema_version')) is not int or state['schema_version'] != 1:
                    raise ValueError('light_transcript_queue_invalid')
                if state.get('platform')=='douyin':
                    from light_audio_fallback import tick as tick_fallback,prepare
                    folder=self.run_folder(uid(state['run_id']))
                    if prepare(state,folder,self.jobs):write(path,state)
                    if tick_fallback(state,path,folder,self.jobs):continue
                platform=state.get('platform','bilibili')
                if platform not in PLATFORMS.values():raise ValueError('light_transcript_queue_invalid')
                for asset in state['assets']:
                    if asset['state'] == 'dispatching' and not asset.get('job_id'):
                        matches = [job for job in self.jobs.list(state['run_id']).get('jobs', [])
                                   if job.get('run_id') == state['run_id'] and job.get('kind') == 'asr'
                                   and job.get('platform') == platform and job.get('content_id') == asset['content_id']
                                   and job.get('entity_ref') == asset['entity_ref'] and job.get('asset_sha256') == asset['asset_sha256']
                                   and type(job.get('created_at')) in (int, float) and job['created_at'] >= asset['dispatch_at']]
                        if len(matches) == 1:asset.update(job_id=matches[0]['job_id'], asr_run_id=matches[0]['run_id'])
                        else:asset.update(state='interrupted_unknown', reason='light_transcript_dispatch_unknown')
                        write(path, state)
                    if asset.get('job_id'):
                        job = self.jobs.status(asset['job_id'])
                        if (job.get('job_id') != asset['job_id'] or job.get('entity_ref') != asset['entity_ref']
                                or job.get('run_id') != asset['asr_run_id']
                                or job.get('asset_sha256') != asset['asset_sha256'] or job.get('platform') != platform
                                or job.get('content_id') != asset['content_id'] or job.get('kind') != 'asr'):
                            raise ValueError('light_transcript_job_changed')
                        asset.update(state=job['state'], asr_run_id=job['run_id'])
                        if job['state'] in ('queued', 'running', 'interrupted_unknown'):
                            state['state'] = 'needs_attention' if job['state'] == 'interrupted_unknown' else 'processing'
                            write(path, state)
                            return
                    elif asset['state'] == 'waiting':
                        if not self.jobs.capabilities().get('asr'):
                            state['reason'] = 'local_asr_model_not_configured';write(path, state);return
                        try:
                            folder = self.run_folder(state['run_id'])
                            _, binding, body, media, _, data = _identity(folder, asset['content_id'], asset['asset_sha256'], asset['entity_ref'], native_audio=platform=='bilibili',native_asr=platform!='bilibili')
                            if body['record_hash'] != asset['source_record_hash'] or len(data) != asset['bytes']:
                                raise ValueError('light_transcript_source_changed')
                            asset['duration_ms'] = _duration(data, audio_only=True) if platform=='bilibili' else _duration(data,require_audio=True)
                            asset.update(state='dispatching', dispatch_at=time.time())
                            write(path, state)
                            if platform!='bilibili':
                                from media_native import _relative
                                source=_relative(folder,media['path']);del data
                                job=self.jobs.start(source,platform,asset['content_id'],'asr',state['run_id'],entity_ref=asset['entity_ref'],native_run_folder=folder,**({'asr_engine':'mlx'} if asset.get('asr_engine')=='mlx' else {}))
                            else:
                                # MediaJobs copies this verified snapshot; the original run audio remains untouched.
                                with tempfile.TemporaryDirectory(prefix='snapshot-', dir=self.root) as directory:
                                    snapshot = Path(directory) / 'audio.m4a'
                                    with os.fdopen(os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:stream.write(data)
                                    job = self.jobs.start(snapshot, 'bilibili', asset['content_id'], 'asr', state['run_id'], entity_ref=asset['entity_ref'],**({'asr_engine':'mlx'} if asset.get('asr_engine')=='mlx' else {}))
                            asset.update(job_id=job['job_id'], state=job['state'], asr_run_id=job['run_id'])
                        except ValueError as error:
                            if str(error) in WAITING:
                                asset['state'] = 'waiting'
                                state['reason'] = str(error);write(path, state);return
                            asset.update(state='failed', reason='light_transcript_processing_failed')
                        except OSError:
                            asset.update(state='interrupted_unknown', reason='light_transcript_dispatch_unknown')
                        write(path, state)
                        return
                if not state['assets'] and not state.get('subtitle_jobs') and state.get('reason')=='native_video_over_collection_limit':
                    state['state']='needs_attention';write(path,state);continue
                states = [a['state'] for a in state['assets']]
                state['state'] = ('completed' if states and all(v == 'completed' for v in states)
                                  else 'needs_attention' if any(v in ('failed', 'cancelled', 'interrupted_unknown') for v in states)
                                  else 'processing' if states else 'completed' if state.get('subtitle_jobs') else 'audio_unavailable')
                write(path, state)
        finally:self.lock.release()
