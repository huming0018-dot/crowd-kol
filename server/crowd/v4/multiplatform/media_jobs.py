"""Durable local processing; explicit complete-video downloads have a separate budget."""
import hashlib
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid

from mc_runner import PLATFORMS, uid, write, read

PROCESSOR = Path(__file__).resolve().parent.parent / 'postprocess' / 'evidence.py'
LONG_PROCESSOR = PROCESSOR.parent / 'long_media.py'
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted_unknown'}


class MediaJobs:
    def __init__(self, root, asr_model=None, python=None):
        self.root = Path(root).resolve() / 'media-processing'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.asr_model = Path(asr_model).resolve() if asr_model else None
        self.python = python or sys.executable
        self.mac_asr_model = Path(os.environ['CROWD_MAC_ASR_MODEL']).resolve() if os.environ.get('CROWD_MAC_ASR_MODEL') else None
        self.mac_asr_python = os.environ.get('CROWD_MAC_ASR_PYTHON')
        self.lock = threading.RLock()
        self.processes = {}
        self.threads = {}
        self.cancelled = set()
        self.closed = False

    def _asr_configuration(self, engine='cpu'):
        if engine == 'cpu':
            return self.asr_model, self.python
        if engine != 'mlx':
            raise ValueError('invalid_asr_engine')
        if (sys.platform != 'darwin' or self.mac_asr_model is None or not self.mac_asr_python
                or not (self.mac_asr_model / 'crowd-model.json').is_file()
                or not Path(self.mac_asr_python).is_file() or not os.access(self.mac_asr_python, os.X_OK)):
            raise ValueError('mac_asr_engine_not_configured')
        manifest = self.mac_asr_model / 'crowd-model.json'
        if manifest.is_symlink() or manifest.stat().st_size > 10000:
            raise ValueError('invalid_mac_asr_model_manifest')
        data = read(manifest)
        if not isinstance(data, dict) or data.get('engine') != 'mlx_whisper_local':
            raise ValueError('invalid_mac_asr_model_manifest')
        return self.mac_asr_model, self.mac_asr_python

    def capabilities(self):
        model_ready = self.asr_model is not None and (self.asr_model / 'crowd-model.json').is_file()
        model_name = None
        if model_ready:
            try:
                manifest = self.asr_model / 'crowd-model.json'
                if manifest.stat().st_size <= 10000:
                    model_name = read(manifest).get('repository', '').rsplit('/', 1)[-1]
            except (OSError, ValueError, TypeError, AttributeError):
                model_name = None
        try:
            self._asr_configuration('mlx'); mac_ready = True
        except (ValueError, OSError):
            mac_ready = False
        executable = os.environ.get('CROWD_FFMPEG') or shutil.which('ffmpeg')
        return {'ocr': sys.platform == 'darwin', 'asr': model_ready,
                'asr_engines': ['cpu'] + (['mlx'] if mac_ready else []),
                'mac_asr_state': 'configured_unverified' if mac_ready else 'not_configured',
                'asr_default_engine': 'cpu',
                'asr_model_state': 'configured_unverified' if model_ready else 'local_model_unavailable',
                'asr_model_name': model_name,
                'long_audio': True, 'ffmpeg': bool(executable and Path(executable).is_file()),
                'audio_extraction_state': 'configured_unverified' if executable else 'ffmpeg_unavailable_pcm_wav_only',
                'transcript': True, 'network': False, 'source': 'saved_task_file',
                'limits': {'bytes': 25 * 1024 * 1024, 'seconds': 3600, 'max_audio_seconds': 3600,
                           'long_audio_bytes': 64 * 1024 * 1024, 'long_audio_seconds': 7200,
                           'registered_native_video_asr_bytes': 64 * 1024 * 1024, 'registered_native_video_asr_seconds': 7200,
                           'segment_seconds': 55, 'overlap_seconds': 2, 'concurrency': 1}}

    def status(self, job_id):
        try:
            job_id = uid(job_id)
        except Exception:
            raise ValueError('invalid_media_job_id') from None
        folder = self.root / job_id
        if folder.is_symlink() or not (folder / 'state.json').is_file():
            raise ValueError('media_job_not_found')
        with self.lock:
            state = read(folder / 'state.json')
            if state['state'] not in TERMINAL and (job_id not in self.threads or not self.threads[job_id].is_alive()):
                recovery = self._cancelled_checkpoint(folder, state)
                state = {**state, 'state': 'failed' if recovery else 'interrupted_unknown',
                         'reason': 'processor_interrupted_with_cancelled_checkpoint' if recovery else 'processor_restart_check_existing_output'}
                if recovery is not None:state['interrupted_checkpoint'] = recovery
            if state['state'] == 'completed':
                if state.get('kind')=='complete_video':
                    from complete_video import read_bytes
                    state['result']=json.loads(read_bytes(folder/'result.json',200000))
                else:state['result'] = read(folder / 'result.json')
            progress = folder / 'long-asr' / 'state.json'
            if progress.is_file():
                detail = read(progress)
                for field in ('completed_chunks', 'total_chunks', 'current_chunk'):
                    if field in detail:
                        state[field] = detail[field]
                state['processor_state'] = detail.get('state')
                if state['state'] == 'failed' and detail.get('reason') and 'interrupted_checkpoint' not in state:
                    state['reason'] = detail['reason']
            state['checkpoint_available'] = state.get('kind') == 'asr' and state['state'] in ('failed', 'cancelled') and bool(list(folder.glob('input*')))
            if state.get('kind')=='complete_video' and (folder/'video-progress.json').is_file():
                from complete_video import read_bytes
                detail=json.loads(read_bytes(folder/'video-progress.json',10000))
                if detail.get('phase') in ('downloading_video','checking_source_video','transcoding_video','checking_complete_output'):state['video_phase']=detail['phase']
                for field,limit in (('downloaded_bytes',256*1024*1024),('network_attempts',4)):
                    if type(detail.get(field)) is int and 0<=detail[field]<=limit:state[field]=detail[field]
        return state

    def _cancelled_checkpoint(self, folder, state, process_lock_held=False):
        """Read-only proof for a stopped native child; other unknown outcomes stay blocked."""
        if (state.get('state') != 'running' or state.get('kind') != 'asr'
                or state.get('processing_profile') != 'registered_native_mp4_asr_64mib_7200s'
                or state.get('job_id') != folder.name or (folder / 'result.json').exists() or (folder / 'result.json').is_symlink()
                or type(state.get('processor_pid')) is not int or not 0 < state['processor_pid'] <= 2147483647):
            return None
        descriptors = []
        try:
            try:os.kill(state['processor_pid'], 0)
            except ProcessLookupError:pass
            else:return None
            locks = [folder / 'long-asr' / 'active.lock']
            if not process_lock_held:locks.insert(0, self.root / 'processor.lock')
            from analysis_artifact import _read, _safe_ancestors
            for path in locks:
                _safe_ancestors(path)
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                descriptors.append(descriptor)
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():return None
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            raw, parent_hash = _read(folder / 'state.json', 200000)
            if raw != state:return None
            detail, detail_hash = _read(folder / 'long-asr' / 'state.json', 200000)
            manifest, manifest_hash = _read(folder / 'long-asr' / 'chunks.json', 50000)
            rows = manifest.get('chunks');done = detail.get('completed_chunks');duration = manifest.get('duration_seconds')
            if (detail.get('state') != 'cancelled' or detail.get('reason') != 'long_media_cancelled'
                    or not isinstance(rows, list) or not 1 <= len(rows) <= 136
                    or type(done) is not int or not 1 <= done <= len(rows)
                    or type(detail.get('total_chunks')) is not int or detail['total_chunks'] != len(rows)
                    or type(detail.get('current_chunk')) is not int or detail['current_chunk'] not in (done - 1, done)
                    or type(manifest.get('schema')) is not int or manifest['schema'] != 1 or manifest.get('asset_sha256') != state.get('asset_sha256')
                    or type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 7200
                    or manifest.get('segment_seconds') != 55 or manifest.get('overlap_seconds') != 2):return None
            snapshots = list(folder.glob('input*'))
            if len(snapshots) != 1 or snapshots[0].name != 'input.mp4':return None
            from complete_video import read_bytes
            limit = self._snapshot_limit(state, snapshots[0])
            if hashlib.sha256(read_bytes(snapshots[0], limit)).hexdigest() != state.get('asset_sha256'):return None
            processors = state.get('processor_files', {})
            names = ('long_media.py', 'local_asr.py', 'fetch_model.py', 'audio_result_cache.py')
            if state.get('asr_engine') == 'mlx': names += ('mlx_asr.py',)
            if any(not isinstance(processors.get(name), str) or len(processors[name]) != 64 for name in names):return None
            model_hash = state.get('model_manifest_sha256')
            if not isinstance(model_hash, str) or len(model_hash) != 64:return None
            caches = list((folder / 'long-asr').glob('result-*.json'))
            if {p.name for p in caches} != {'result-%04d.json' % i for i in range(done)}:return None
            cache_hashes = []
            for index, row in enumerate(rows):
                start = index * 53
                if (not isinstance(row, dict) or set(row) != {'index', 'start', 'end', 'file', 'sha256'}
                        or type(row['index']) is not int or row['index'] != index
                        or row['file'] != 'chunk-%04d.wav' % index or row['start'] != start
                        or row['end'] != min(duration, start + 55) or not start < row['end']):return None
                if hashlib.sha256(read_bytes(folder / 'long-asr' / row['file'], 2000000)).hexdigest() != row['sha256']:return None
                if index < done:
                    cache, cache_hash = _read(folder / 'long-asr' / ('result-%04d.json' % index), 2000000)
                    expected = hashlib.sha256((row['sha256'] + model_hash + ''.join(processors[name] for name in names) + '1').encode()).hexdigest()
                    if (set(cache) not in ({'segments', 'input_hash', 'timing_adjustments', 'segment_metrics'},
                            {'segments', 'input_hash', 'timing_adjustments', 'segment_metrics', 'native_alignment'})
                            or cache.get('input_hash') != expected or not isinstance(cache.get('segments'), list)
                            or len(cache['segments']) > 1000):return None
                    for segment in cache['segments']:
                        if (not isinstance(segment, dict) or set(segment) != {'start', 'end', 'text'}
                                or any(type(segment[key]) not in (int, float) or not math.isfinite(segment[key]) for key in ('start', 'end'))
                                or not 0 <= segment['start'] <= segment['end'] <= row['end'] - start + .1
                                or segment['start'] > row['end'] - start or not isinstance(segment['text'], str)
                                or not segment['text'].strip() or len(segment['text']) > 10000):return None
                    cache_hashes.append(cache_hash)
            if rows[-1]['end'] != duration:return None
            history = state.get('recovery_history', [])
            if not isinstance(history, list) or len(history) >= 20:return None
            return {'reason': 'processor_interrupted_with_cancelled_checkpoint', 'trigger_actor': 'unknown',
                    'original_parent_state': 'running', 'original_processor_pid': state['processor_pid'],
                    'parent_state_sha256': parent_hash, 'checkpoint_state_sha256': detail_hash,
                    'chunks_sha256': manifest_hash, 'asset_sha256': state['asset_sha256'],
                    'completed_chunks': done, 'total_chunks': len(rows), 'cache_sha256': cache_hashes}
        except (OSError, ValueError, TypeError, KeyError, AttributeError):return None
        finally:
            for descriptor in reversed(descriptors):os.close(descriptor)

    def _input(self, source, platform, content_id, kind, run_id, entity_ref=None, native_run_folder=None):
        if kind not in ('ocr', 'asr', 'transcript') or platform not in PLATFORMS.values():
            raise ValueError('invalid_media_processor')
        source = Path(source)
        context=None
        if kind=='asr' and source.suffix.lower()=='.mp4' and native_run_folder is not None:
            from media_native import _identity,_relative,_duration
            from analysis_artifact import _read
            folder=Path(native_run_folder)
            if folder.name!=run_id:raise ValueError('media_native_identity_invalid')
            normalized,_=_read(folder/'normalized.json',32*1024*1024)
            matches=[item for item in normalized.get('media',[]) if isinstance(item,dict) and item.get('content_id')==content_id and _relative(folder,item.get('path')).absolute()==source.absolute()]
            if len(matches)!=1:raise ValueError('media_native_source_ambiguous')
            _,binding,body,item,normalized_sha,data=_identity(folder,content_id,matches[0].get('sha256'),entity_ref,native_asr=True)
            if binding['platform']!=platform or binding['local_run_id']!=run_id:raise ValueError('media_native_identity_invalid')
            duration=_duration(data,require_audio=True)
            if len(data)<=25*1024*1024 and duration<=3600000:
                return data,binding['asset_sha256'],'standard_25mib_3600s',None
            context={'schema_version':1,'processing_profile':'registered_native_mp4_asr_64mib_7200s',
                     'run_id':run_id,'platform':platform,'content_id':content_id,'entity_ref':binding['entity_ref'],
                     'asset_sha256':binding['asset_sha256'],'source_record_hash':body['record_hash'],
                     'normalized_sha256':normalized_sha,'audio_duration_ms':duration}
            return data,context['asset_sha256'],context['processing_profile'],context
        limit = 64 * 1024 * 1024 if kind == 'asr' and source.suffix.lower() in ('.m4a', '.mp3', '.aac') else 25 * 1024 * 1024
        if source.is_symlink() or not source.is_file() or source.stat().st_size > limit:
            raise ValueError('media_missing_or_over_processing_limit')
        data=source.read_bytes()
        if len(data)>limit:raise ValueError('media_over_processing_limit')
        digest = hashlib.sha256(data).hexdigest()
        return data,digest,'long_audio_64mib_7200s' if limit==64*1024*1024 else 'standard_25mib_3600s',None

    def preview(self, source, platform, content_id, kind, run_id, entity_ref=None, native_run_folder=None):
        data,digest,profile,context=self._input(source,platform,content_id,kind,run_id,entity_ref,native_run_folder)
        return {'processing_profile':profile,'asset_sha256':digest,'input_bytes':len(data),
                'max_input_bytes':64*1024*1024 if profile!='standard_25mib_3600s' else 25*1024*1024,
                'max_audio_seconds':7200 if profile!='standard_25mib_3600s' else 3600,
                'native_video_verified':kind=='asr' and Path(source).suffix.lower()=='.mp4' and native_run_folder is not None,
                'audio_duration_ms':context['audio_duration_ms'] if context else None,
                'source_requests':0,'model_calls':0}

    def start(self, source, platform, content_id, kind, run_id, entity_ref=None, native_run_folder=None, asr_engine='cpu'):
        selected_model, selected_python = self._asr_configuration(asr_engine) if kind == 'asr' else (None, None)
        if kind == 'asr' and asr_engine == 'cpu' and not self.capabilities()['asr']:
            raise ValueError('local_asr_model_not_configured')
        data,digest,profile,context=self._input(source,platform,content_id,kind,run_id,entity_ref,native_run_folder)
        identity = {'asset_sha256': digest, 'platform': platform, 'content_id': content_id,
                    'processing_profile':profile,
                    'kind': kind, 'processor_schema': 2,
                    'processor_sha256': hashlib.sha256(PROCESSOR.read_bytes()).hexdigest(),
                    'model': str(selected_model) if kind == 'asr' else None}
        if kind == 'asr': identity['asr_engine'] = asr_engine
        if context is not None:
            identity['native_video_context_sha256']=hashlib.sha256(json.dumps(context,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            entity_ref=context['entity_ref']
        identity['processor_files'] = {name: hashlib.sha256((PROCESSOR.parent / name).read_bytes()).hexdigest()
            for name in ('local_asr.py', 'fetch_model.py', 'long_media.py', 'audio_result_cache.py', 'vision.swift', 'speech.swift', 'crowd-vision', 'crowd-speech')
            if (PROCESSOR.parent / name).is_file()}
        if kind == 'asr' and asr_engine == 'mlx':
            identity['processor_files']['mlx_asr.py'] = hashlib.sha256((PROCESSOR.parent/'mlx_asr.py').read_bytes()).hexdigest()
        if context is not None:identity['processor_files']['native_video_asr.py']=hashlib.sha256((PROCESSOR.parent/'native_video_asr.py').read_bytes()).hexdigest()
        if entity_ref is not None:
            from results_store import _entity_selector
            _entity_selector(entity_ref,platform,content_id)
            identity['entity_ref']=entity_ref
        if kind == 'asr':
            manifest = selected_model / 'crowd-model.json'
            if manifest.stat().st_size > 10000:
                raise ValueError('invalid_local_asr_model_manifest')
            identity['model_manifest_sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with self.lock:
            if self.closed:
                raise ValueError('media_processor_closed')
            unknown = False
            for folder in self.root.iterdir():
                if folder.is_dir() and not folder.is_symlink() and (folder / 'state.json').is_file():
                    state = self.status(folder.name)
                    if state.get('input_hash') == key and state['state'] not in ('failed', 'cancelled'):
                        return {**state, 'cached': state['state'] == 'completed', 'reused_existing_job': True}
                    unknown = unknown or state['state'] == 'interrupted_unknown'
            if unknown:
                raise ValueError('media_processor_reconciliation_required')
            if any(thread.is_alive() for thread in self.threads.values()):
                raise ValueError('media_processor_busy')
            process_lock = open(self.root / 'processor.lock', 'a+')
            try:
                fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                process_lock.close()
                raise ValueError('media_processor_busy') from None
            job_id = str(uuid.uuid4()); folder = self.root / job_id
            folder.mkdir(mode=0o700)
            snapshot = folder / ('input' + source.suffix.lower())
            with os.fdopen(os.open(snapshot, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
                stream.write(data)
            if context is not None:write(folder/'native-asr-context.json',context)
            state = {'job_id': job_id, 'state': 'queued', 'input_hash': key, 'asset_sha256': digest,
                     'platform': platform, 'content_id': content_id, 'kind': kind, 'run_id': run_id,
                     'association': 'owner_selected_content', 'created_at': time.time(),
                     'source_kind': 'authorized_local_file', 'review_status': 'unreviewed', 'uploaded': False}
            state['processing_profile']=profile
            if context is not None:state['native_video_context_sha256']=identity['native_video_context_sha256']
            if entity_ref is not None:state['entity_ref']=entity_ref
            state['processor_files']=identity['processor_files']
            if kind == 'asr':
                state['asr_engine'] = asr_engine
                state['asr_model'] = str(selected_model)
                state['model_manifest_sha256'] = identity['model_manifest_sha256']
                state['processor_files'] = identity['processor_files']
            write(folder / 'state.json', state)
            thread = threading.Thread(target=self._execute, args=(state, snapshot, process_lock), daemon=True)
            self.threads[job_id] = thread; thread.start()
            return state

    def playback(self, job_id, asset_sha256):
        try:
            job_id = uid(job_id)
        except Exception:
            raise ValueError('invalid_media_job_id') from None
        folder = self.root / job_id
        if any(parent.is_symlink() for parent in (folder, *folder.parents)) or (folder / 'state.json').is_symlink() or (folder / 'result.json').is_symlink():
            raise ValueError('media_playback_format_or_path_invalid')
        state = self.status(job_id)
        if state.get('job_id') != job_id or state.get('kind') != 'asr' or state['state'] != 'completed' or asset_sha256 != state.get('asset_sha256'):
            raise ValueError('media_playback_identity_mismatch')
        snapshots = list(folder.glob('input*'))
        if len(snapshots) != 1:
            raise ValueError('media_playback_snapshot_missing')
        path = snapshots[0]
        mimes = {'.mp4': 'video/mp4', '.webm': 'video/webm', '.wav': 'audio/wav', '.m4a': 'audio/mp4', '.mp3': 'audio/mpeg', '.aac': 'audio/aac', '.ogg': 'audio/ogg'}
        if path.suffix.lower() not in mimes or path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError('media_playback_format_or_path_invalid')
        limit = self._snapshot_limit(state,path)
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
            data = stream.read(limit + 1)
        if len(data) > limit or hashlib.sha256(data).hexdigest() != state['asset_sha256']:
            raise ValueError('media_playback_snapshot_changed')
        return {'data': data, 'mime': mimes[path.suffix.lower()], 'sha256': state['asset_sha256']}

    def _snapshot_limit(self,state,path):
        if state.get('processing_profile')=='registered_native_mp4_asr_64mib_7200s':
            from analysis_artifact import _read
            context,_=_read(path.parent/'native-asr-context.json',8192)
            import importlib.util
            spec=importlib.util.spec_from_file_location('crowd_native_video_asr',PROCESSOR.parent/'native_video_asr.py')
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module);module.validate_context(context,path,state)
            expected=hashlib.sha256(json.dumps(context,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if (state.get('kind')!='asr' or path.name!='input.mp4' or expected!=state.get('native_video_context_sha256')
                    or any(context.get(key)!=state.get(key) for key in ('asset_sha256','platform','content_id','run_id','entity_ref'))):
                raise ValueError('media_checkpoint_source_changed')
            return 64*1024*1024
        return 64*1024*1024 if state['kind']=='asr' and path.suffix.lower() in ('.m4a','.mp3','.aac') else 25*1024*1024

    def start_video(self, reference):
        from complete_video import safe_folder, safe_url, atomic_json
        safe_url(reference['url']);safe_folder(self.root)
        processor=Path(__file__).parent/'complete_video.py'
        key=hashlib.sha256((reference['reference_sha256']+hashlib.sha256(processor.read_bytes()).hexdigest()).encode()).hexdigest()
        with self.lock:
            if self.closed:raise ValueError('media_processor_closed')
            for folder in self.root.iterdir():
                if folder.is_dir() and not folder.is_symlink() and (folder/'state.json').is_file():
                    state=self.status(folder.name)
                    if state.get('input_hash')==key:return {**state,'reused_existing_job':True,'cached':state['state']=='completed'}
                    if state['state']=='interrupted_unknown':raise ValueError('media_processor_reconciliation_required')
            if any(thread.is_alive() for thread in self.threads.values()):raise ValueError('media_processor_busy')
            process_lock=os.fdopen(os.open(self.root/'processor.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600),'a+')
            try:fcntl.flock(process_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:process_lock.close();raise ValueError('media_processor_busy') from None
            if os.fstat(process_lock.fileno()).st_nlink!=1:process_lock.close();raise ValueError('unsafe_complete_video_path')
            try:
                job_id=str(uuid.uuid4());folder=self.root/job_id;folder.mkdir(mode=0o700)
                atomic_json(folder/'input-ref.json',reference)
                ref_hash=hashlib.sha256((folder/'input-ref.json').read_bytes()).hexdigest()
                state={'job_id':job_id,'state':'queued','kind':'complete_video','platform':'douyin','content_id':reference['content_id'],'run_id':reference['run_id'],'input_hash':key,'source_reference_sha256':reference['reference_sha256'],'created_at':time.time(),'source_kind':'authorized_saved_video_reference','uploaded':False,'network_budget':{'max_request_attempts':4,'input_bytes':256*1024*1024,'output_bytes':64*1024*1024},'collection_budget_changed':False,'model_calls':0}
                write(folder/'state.json',state)
                thread=threading.Thread(target=self._execute_video,args=(state,ref_hash,process_lock),daemon=True);self.threads[job_id]=thread;thread.start()
            except BaseException:
                process_lock.close();raise
            return state

    def _execute_video(self,state,ref_hash,process_lock):
        folder=self.root/state['job_id'];job_id=state['job_id'];proc=None
        try:
            with self.lock:
                if job_id in self.cancelled or self.closed:state.update(state='cancelled');return
                proc=subprocess.Popen([self.python,str(Path(__file__).parent/'complete_video.py'),'--reference',str(folder/'input-ref.json'),'--reference-file-sha256',ref_hash],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,pass_fds=(process_lock.fileno(),))
                self.processes[job_id]=proc;state.update(state='running',processor_pid=proc.pid);write(folder/'state.json',state)
            proc.wait(timeout=920)
            if job_id in self.cancelled:state.update(state='cancelled')
            elif proc.returncode:
                from complete_video import read_bytes,ERROR_CODES
                error=json.loads(read_bytes(folder/'video-error.json',10000)) if (folder/'video-error.json').is_file() else {}
                reason=error.get('reason');state.update(state='failed',reason=reason if reason in ERROR_CODES else 'complete_video_failed')
            else:
                from complete_video import read_bytes
                data=read_bytes(folder/'result.json',200000);rows=json.loads(data)
                evidence=rows[0]['evidence']
                if len(rows)!=1 or rows[0]['kind']!='processed_video' or rows[0]['content_id']!=state['content_id'] or rows[0]['platform']!='douyin' or evidence['source_reference_sha256']!=state['source_reference_sha256'] or hashlib.sha256(read_bytes(folder/'video.mp4',64*1024*1024)).hexdigest()!=evidence['asset_sha256']:
                    raise ValueError('complete_video_identity_mismatch')
                state.update(state='completed',asset_sha256=evidence['asset_sha256'],result_sha256=hashlib.sha256(data).hexdigest())
        except subprocess.TimeoutExpired:
            self._kill(proc);state.update(state='failed',reason='complete_video_timeout')
        except (OSError,ValueError,TypeError,KeyError,IndexError):
            self._kill(proc);state.update(state='failed',reason='complete_video_failed')
        finally:
            with self.lock:
                self.processes.pop(job_id,None)
                if job_id in self.cancelled:state.update(state='cancelled')
                (folder/'input-ref.json').unlink(missing_ok=True)
                write(folder/'state.json',{**state,'finished_at':time.time()})
            process_lock.close()

    def video_file(self,job_id,asset_sha256):
        from complete_video import safe_folder,read_bytes
        try:job_id=uid(job_id)
        except Exception:raise ValueError('invalid_media_job_id') from None
        folder=safe_folder(self.root/job_id);state=json.loads(read_bytes(folder/'state.json',20000))
        if state.get('job_id')!=job_id or state.get('kind')!='complete_video' or state['state']!='completed' or state.get('asset_sha256')!=asset_sha256:raise ValueError('complete_video_identity_mismatch')
        data=read_bytes(folder/'video.mp4',64*1024*1024)
        if hashlib.sha256(data).hexdigest()!=asset_sha256:raise ValueError('complete_video_asset_changed')
        return {'data':data,'mime':'video/mp4','sha256':asset_sha256}

    def list(self, run_id):
        try:
            uid(run_id)
        except Exception:
            raise ValueError('invalid_media_run_id') from None
        jobs = [self.status(p.name) for p in self.root.iterdir()
                if p.is_dir() and not p.is_symlink() and (p / 'state.json').is_file()]
        return {'jobs': sorted((s for s in jobs if s['run_id'] == run_id), key=lambda s: s['created_at'], reverse=True)[:100]}

    def _execute(self, state, snapshot, process_lock):
        folder = snapshot.parent; job_id = state['job_id']; result = folder / 'result.json'
        command = [self.python, str(PROCESSOR), '--kind', state['kind'], '--input', str(snapshot),
                   '--platform', state['platform'], '--content-id', state['content_id'],
                   '--authorization-ref', 'owner-selected-saved-media', '--output', str(result)]
        if state['kind'] == 'asr':
            try:
                selected_model, selected_python = self._asr_configuration(state.get('asr_engine', 'cpu'))
            except (ValueError, OSError):
                state.update(state='failed', reason='asr_engine_configuration_changed')
                write(folder / 'state.json', state)
                process_lock.close()
                return
            processor=PROCESSOR.parent/'native_video_asr.py' if state.get('processing_profile')=='registered_native_mp4_asr_64mib_7200s' else LONG_PROCESSOR
            command = [selected_python, str(processor), '--input', str(snapshot),
                       '--platform', state['platform'], '--content-id', state['content_id'],
                       '--authorization-ref', 'owner-selected-saved-media', '--output', str(result),
                       '--asr-model', str(selected_model), '--work-dir', str(folder / 'long-asr'),
                       '--project-root', str(self.root), '--cache-dir', str(self.root / 'audio-result-cache')]
            if state.get('processing_profile')=='registered_native_mp4_asr_64mib_7200s':
                command+=['--native-video-context',str(folder/'native-asr-context.json')]
        proc = None
        try:
            with self.lock:
                if job_id in self.cancelled or self.closed:
                    state.update(state='cancelled'); return
                proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, start_new_session=True,
                                        pass_fds=(process_lock.fileno(),))
                self.processes[job_id] = proc
                state['processor_pid'] = proc.pid
            write(folder / 'state.json', {**state, 'state': 'running'})
            proc.wait(timeout=3600 if state['kind'] == 'asr' else 180)
            if job_id in self.cancelled:
                state.update(state='cancelled')
            elif proc.returncode != 0:
                state.update(state='failed', reason='local_media_processing_failed')
            elif result.is_symlink() or not result.is_file() or result.stat().st_nlink!=1 or result.stat().st_size > (2_000_000 if state['kind'] == 'asr' else 200000):
                state.update(state='failed', reason='invalid_media_processing_result')
            else:
                result_data=result.read_bytes()
                rows = json.loads(result_data)
                if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict) or not isinstance(rows[0].get('evidence'), dict) or rows[0].get('platform') != state['platform'] or rows[0].get('content_id') != state['content_id'] or rows[0]['evidence'].get('asset_sha256') != state['asset_sha256']:
                    state.update(state='failed', reason='media_result_identity_mismatch')
                else:
                    state.update(state='completed',result_sha256=hashlib.sha256(result_data).hexdigest())
        except subprocess.TimeoutExpired:
            self._kill(proc); state.update(state='failed', reason='local_media_processing_timeout')
        except (OSError, ValueError, TypeError):
            if proc is not None and proc.poll() is None:
                self._kill(proc)
            state.update(state='failed', reason='local_media_processor_unavailable')
        finally:
            process_lock.close()
            with self.lock:
                self.processes.pop(job_id, None)
                if job_id in self.cancelled:
                    state.update(state='cancelled')
                if state['kind'] != 'asr':
                    snapshot.unlink(missing_ok=True)
                write(folder / 'state.json', {**state, 'finished_at': time.time()})

    @staticmethod
    def _kill(proc):
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)

    def cancel(self, job_id):
        state = self.status(job_id)
        with self.lock:
            if state['state'] in TERMINAL:
                return state
            (self.root / job_id / 'cancel.requested').touch(mode=0o600, exist_ok=True)
            self.cancelled.add(job_id); self._kill(self.processes.get(job_id))
        return {**state, 'cancel_requested': True}

    def resume(self, job_id):
        with self.lock:
            if self.closed:
                raise ValueError('media_processor_closed')
            state = self.status(job_id)
            if not state.get('checkpoint_available'):
                raise ValueError('media_checkpoint_not_available')
            if any(thread.is_alive() for thread in self.threads.values()):
                raise ValueError('media_processor_busy')
            selected_model, selected_python = self._asr_configuration(state.get('asr_engine', 'cpu'))
            if state.get('asr_engine', 'cpu') == 'cpu' and not self.capabilities()['asr']:
                raise ValueError('local_asr_model_not_configured')
            for other in self.root.iterdir():
                if other.name != job_id and other.is_dir() and not other.is_symlink() and (other / 'state.json').is_file() and self.status(other.name)['state'] == 'interrupted_unknown':
                    raise ValueError('media_processor_reconciliation_required')
            if (selected_model / 'crowd-model.json').stat().st_size > 10000:
                raise ValueError('invalid_local_asr_model_manifest')
            model_hash = hashlib.sha256((selected_model / 'crowd-model.json').read_bytes()).hexdigest()
            if model_hash != state.get('model_manifest_sha256'):
                raise ValueError('media_checkpoint_model_changed')
            current_processors = {name: hashlib.sha256((PROCESSOR.parent / name).read_bytes()).hexdigest()
                                  for name in state.get('processor_files', {}) if (PROCESSOR.parent / name).is_file()}
            if current_processors != state.get('processor_files'):
                raise ValueError('media_checkpoint_processor_changed')
            folder = self.root / job_id
            recovery = state.get('interrupted_checkpoint')
            snapshots = list(folder.glob('input*'))
            limit = self._snapshot_limit(state,snapshots[0]) if len(snapshots)==1 else 25*1024*1024
            if len(snapshots) != 1 or snapshots[0].is_symlink() or snapshots[0].stat().st_size > limit or hashlib.sha256(snapshots[0].read_bytes()).hexdigest() != state['asset_sha256']:
                raise ValueError('media_checkpoint_source_changed')
            process_lock = os.fdopen(os.open(self.root / 'processor.lock', os.O_RDWR | os.O_NOFOLLOW), 'r+') if recovery else open(self.root / 'processor.lock', 'a+')
            try:
                if recovery:
                    info = os.fstat(process_lock.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                        raise ValueError('media_interrupted_checkpoint_not_verified')
                fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                process_lock.close()
                raise ValueError('media_processor_busy') from None
            except (OSError, ValueError):
                process_lock.close()
                raise
            if recovery:
                from analysis_artifact import _read
                try:raw = _read(folder / 'state.json', 200000)[0]
                except (OSError, ValueError):
                    process_lock.close()
                    raise ValueError('media_interrupted_checkpoint_not_verified') from None
                verified = self._cancelled_checkpoint(folder, raw, process_lock_held=True)
                if verified != recovery:
                    process_lock.close()
                    raise ValueError('media_interrupted_checkpoint_not_verified')
                try:
                    from complete_video import read_bytes
                    original = read_bytes(folder / 'state.json', 200000)
                    if hashlib.sha256(original).hexdigest() != verified['parent_state_sha256']:
                        raise ValueError('media_interrupted_checkpoint_not_verified')
                    backup_name = 'recovery-parent-' + verified['parent_state_sha256'] + '.json'
                    backup = folder / backup_name
                    if backup.exists() or backup.is_symlink():
                        if read_bytes(backup, 200000) != original:raise ValueError('media_interrupted_checkpoint_not_verified')
                    else:
                        with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
                            stream.write(original);stream.flush();os.fsync(stream.fileno())
                except (OSError, ValueError):
                    process_lock.close()
                    raise ValueError('media_interrupted_checkpoint_not_verified') from None
                state['recovery_history'] = [*state.get('recovery_history', []), {**verified, 'parent_backup': backup_name, 'resumed_at': time.time()}]
            (folder / 'cancel.requested').unlink(missing_ok=True)
            (folder / 'result.json').unlink(missing_ok=True)
            self.cancelled.discard(job_id)
            state = {k: v for k, v in state.items() if k not in ('result', 'reason', 'finished_at', 'processor_pid', 'checkpoint_available', 'interrupted_checkpoint')}
            state.update(state='queued', resumed_at=time.time())
            write(folder / 'state.json', state)
            thread = threading.Thread(target=self._execute, args=(state, snapshots[0], process_lock), daemon=True)
            self.threads[job_id] = thread
            thread.start()
            return state

    def close(self):
        with self.lock:
            self.closed = True
            for job_id in list(self.processes):
                self.cancelled.add(job_id); self._kill(self.processes[job_id])
            threads = list(self.threads.values())
        for thread in threads:
            thread.join(timeout=6)
