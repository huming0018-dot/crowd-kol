"""Versioned analysis of saved text through the already installed Codex CLI."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

from analysis_contract import build_snapshot, make_prompt, validate_result, MODEL_SCHEMA, _platform, _typed_entity, finite_number, _hash, _paragraphs
from full_analysis import build_analysis_snapshot, combine_results, MAX_SEGMENTS, MAX_CHARACTERS, PROMPT_VERSION as FULL_PROMPT_VERSION, ASSEMBLY_VERSION
from mc_runner import BridgeError, canonical, read, uid, write, contains_secret as mc_contains_secret

PROMPT_VERSION = 'content-comments-v1'
TIMEOUT_SECONDS = 180


class AnalysisJobs:
    def __init__(self, root, executable=None):
        self.root = Path(root).resolve() / 'analysis'
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.executable = executable or shutil.which('codex')
        self.mutex = threading.RLock()
        self.running = {}
        self.closed = False
        self.provider_version = 'unavailable'
        if self.executable:
            try:
                value = subprocess.run([self.executable, '--version'], capture_output=True,
                                       timeout=5, check=True)
                self.provider_version = value.stdout[:200].decode().strip()
            except (OSError, subprocess.SubprocessError, UnicodeError):
                self.executable = None

    def folder(self, job_id):
        try:
            folder = self.root / uid(job_id)
        except BridgeError:
            raise ValueError('invalid_analysis_job_id') from None
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError('analysis_not_found')
        return folder

    def status(self, job_id):
        folder = self.folder(job_id)
        with self.mutex:
            # Pair the durable snapshot with ownership. The worker writes its terminal
            # state before removing ownership; reading outside this lock could combine
            # an old running snapshot with a newly removed record and report unknown.
            state = read(folder / 'state.json')
            if state['state'] in ('queued', 'running') and job_id not in self.running:
                # A restarted UI never repeats a possibly billed request automatically.
                state = {**state, 'state': 'interrupted_unknown', 'error': 'analysis_interrupted_check_before_retry'}
            if state['state'] == 'completed':
                state['result'] = read(folder / 'result.json')
        return {'ok': True, **state}

    def media_inputs(self, imported, snapshot, run_id, refs=None):
        """Read only completed, explicitly associated local results; never infer or transfer."""
        try:run_id=uid(run_id)
        except BridgeError:raise ValueError('invalid_analysis_media_reference') from None
        if imported.get('run_id') not in (None,run_id):raise ValueError('analysis_media_identity_mismatch')
        refs=[] if refs is None else refs
        if not isinstance(refs,list) or len(refs)>5:raise ValueError('invalid_analysis_media_reference')
        chosen={}
        for ref in refs:
            if not isinstance(ref,dict) or set(ref)!={'job_id','result_sha256','asset_sha256'}:
                raise ValueError('invalid_analysis_media_reference')
            try:job_id=uid(ref['job_id'])
            except BridgeError:raise ValueError('invalid_analysis_media_reference') from None
            if job_id in chosen or any(not isinstance(ref[k],str) or len(ref[k])!=64 or any(c not in '0123456789abcdef' for c in ref[k]) for k in ('result_sha256','asset_sha256')):
                raise ValueError('invalid_analysis_media_reference')
            chosen[job_id]=ref
        base=self.root.parent/'media-processing'; options=[];loaded={};excluded=0
        if base.exists():
            if any(p.is_symlink() for p in (base,*base.parents)):raise ValueError('unsafe_analysis_media_path')
            for folder in sorted(base.iterdir()):
                if folder.is_symlink() or not folder.is_dir():
                    if folder.name in chosen:raise ValueError('analysis_media_selection_invalid')
                    continue
                try:
                    job_id=uid(folder.name)
                    def bounded(path,limit):
                        if path.is_symlink():raise ValueError('unsafe_analysis_media_path')
                        with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
                            info=os.fstat(stream.fileno())
                            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>limit:raise ValueError('unsafe_analysis_media_path')
                            data=stream.read(limit+1)
                        if len(data)>limit:raise ValueError('analysis_media_size_limit')
                        return data
                    state=json.loads(bounded(folder/'state.json',64000))
                    if state.get('state')!='completed' or state.get('run_id')!=run_id or state.get('platform')!=snapshot['platform'] or state.get('content_id')!=snapshot['content_id'] or state.get('kind') not in ('asr','ocr'):continue
                    if state.get('job_id')!=job_id:raise ValueError('analysis_media_identity_mismatch')
                    entity=snapshot['content'].get('entity_ref')
                    if entity is None:
                        primary=imported['records'][int(snapshot['content']['source_ref'].split(':')[1])-1]
                        entity=_typed_entity(snapshot['platform']+':'+primary['kind']+':'+snapshot['content_id'],primary)
                    ambiguous=any(r.get('kind')=='dynamic' and r.get('content_id')==snapshot['content_id'] for r in imported['records'])
                    if (snapshot['platform']=='zhihu' or ambiguous) and (not entity or state.get('entity_ref')!=entity):
                        raise ValueError('analysis_media_identity_unconfirmed')
                    if state.get('entity_ref') is not None and entity is not None and state['entity_ref']!=entity:raise ValueError('analysis_media_identity_mismatch')
                    data=bounded(folder/'result.json',2_000_000);digest=hashlib.sha256(data).hexdigest()
                    if state.get('result_sha256') is not None and state['result_sha256']!=digest:raise ValueError('analysis_media_result_changed')
                    rows=json.loads(data)
                    if not isinstance(rows,list) or len(rows)!=1:raise ValueError('invalid_analysis_media_result')
                    record=rows[0];evidence=record.get('evidence',{})
                    asset=state.get('asset_sha256')
                    # raw_text is a display preview. Completed segmented ASR carries
                    # its whole candidate text in segments; do not rewrite that preview.
                    full_segments=(state['kind']=='asr' and evidence.get('processor') in ('faster_whisper_local_segmented','mlx_whisper_local_segmented')
                        and evidence.get('coverage')=='local_file_all_audio_windows_processed'
                        and type(state.get('total_chunks')) is int and 0<state['total_chunks']<=512
                        and type(evidence.get('audio_windows_processed')) is int
                        and evidence['audio_windows_processed']==state['total_chunks'])
                    if full_segments:
                        checkpoint_folder=folder/'long-asr'
                        if checkpoint_folder.is_symlink():raise ValueError('unsafe_analysis_media_path')
                        checkpoint=json.loads(bounded(checkpoint_folder/'state.json',64000))
                        full_segments=(checkpoint.get('state')=='completed'
                            and type(checkpoint.get('completed_chunks')) is int
                            and type(checkpoint.get('total_chunks')) is int
                            and checkpoint['completed_chunks']==checkpoint['total_chunks']==state['total_chunks'])
                    if record.get('kind')!=('transcript' if state['kind']=='asr' else 'ocr') or record.get('platform')!=snapshot['platform'] or record.get('content_id')!=snapshot['content_id'] or evidence.get('asset_sha256')!=asset or evidence.get('source_kind')!='authorized_local_file' or (evidence.get('truncated') is not False and not (evidence.get('truncated') is True and full_segments)):
                        raise ValueError('analysis_media_identity_mismatch')
                    if not isinstance(asset,str) or len(asset)!=64 or any(c not in '0123456789abcdef' for c in asset):raise ValueError('analysis_media_identity_mismatch')
                    inputs=list(folder.glob('input*'))
                    if len(inputs)>1:raise ValueError('analysis_media_asset_unverified')
                    def matching_media(media):
                        if not isinstance(media,dict) or media.get('sha256')!=asset or media.get('content_id')!=snapshot['content_id']:return False
                        try:
                            if _platform(media.get('platform'))!=snapshot['platform']:return False
                        except ValueError:return False
                        if snapshot['platform']=='zhihu' and media.get('source_content_type')!=entity.rsplit(':',1)[-1]:return False
                        if ambiguous and media.get('entity_ref')!=entity:return False
                        return True
                    verified_asset=any(matching_media(m) for m in imported.get('media',[]))
                    if len(inputs)==1:
                        verified_asset=hashlib.sha256(bounded(inputs[0],64*1024*1024)).hexdigest()==asset
                    if state.get('text_revision') is not None:
                        # Revisions retain a verified parent audio identity without
                        # copying or linking the original input into a new job.
                        import importlib.util
                        spec=importlib.util.spec_from_file_location('crowd_transcript_quality',Path(__file__).resolve().parent.parent/'postprocess/transcript_quality.py')
                        quality_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(quality_module)
                        proof=quality_module.TranscriptQuality(self.root.parent).validate(job_id)
                        if proof['result_sha256']!=digest or proof['state']['asset_sha256']!=asset:raise ValueError('analysis_media_asset_unverified')
                        verified_asset=True
                    if not verified_asset:raise ValueError('analysis_media_asset_unverified')
                    kind=state['kind'];segments=evidence.get('segments') if kind=='asr' else [{'text':evidence.get('raw_text')}]
                    if not isinstance(segments,list) or not 1<=len(segments)<=(MAX_SEGMENTS if full_segments else 1000):raise ValueError('analysis_media_segment_limit')
                    projected=[];characters=0
                    duration=evidence.get('duration_seconds')
                    for segment in segments:
                        text=segment.get('text')
                        if not isinstance(text,str) or not text.strip() or len(text)>24000 or mc_contains_secret(text):raise ValueError('invalid_analysis_media_text')
                        characters+=len(text)
                        if characters>(MAX_CHARACTERS if full_segments else 24000):raise ValueError('analysis_media_text_limit')
                        value={'text':text}
                        if kind=='asr':
                            if evidence.get('timeline') not in (None,'absolute_seconds'):raise ValueError('analysis_media_time_invalid')
                            start,end=segment.get('start'),segment.get('end')
                            if any(not finite_number(v) for v in (start,end,duration)) or not 0<=start<=end<=duration:raise ValueError('analysis_media_time_invalid')
                            value.update(start=start,end=end)
                        projected.append(value)
                    processor=evidence.get('processor') or ('apple_vision_local' if kind=='ocr' else None)
                    if processor not in ('faster_whisper_local','faster_whisper_local_segmented','mlx_whisper_local','mlx_whisper_local_segmented','apple_speech_ondevice','apple_vision_local'):raise ValueError('analysis_media_processor_unknown')
                    files=state.get('processor_files',{})
                    if not isinstance(files,dict) or any(k not in ('local_asr.py','fetch_model.py','long_media.py','audio_result_cache.py','native_video_asr.py','mlx_asr.py','speech_precheck.py','vision.swift','speech.swift','crowd-vision','crowd-speech') or not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for k,v in files.items()):raise ValueError('invalid_analysis_media_processor')
                    model=state.get('model_manifest_sha256')
                    if model is not None and (not isinstance(model,str) or len(model)!=64 or any(c not in '0123456789abcdef' for c in model)):raise ValueError('invalid_analysis_media_processor')
                    item={'job_id':job_id,'kind':kind,'result_sha256':digest,'asset_sha256':asset,'processor':processor,'model_manifest_sha256':model,'processor_files':files,'review_status':'not_reviewed','segments':projected}
                    if job_id in chosen and any(chosen[job_id][k]!=item[k] for k in ('result_sha256','asset_sha256')):raise ValueError('analysis_media_result_changed')
                    loaded[job_id]=item
                    if len(options)<20:options.append(item)
                except (ValueError,TypeError,KeyError,OSError,BridgeError,AttributeError):
                    if folder.name in chosen:raise ValueError('analysis_media_selection_invalid') from None
                    excluded+=1
        if set(chosen)-set(loaded):raise ValueError('analysis_media_selection_invalid')
        return {'options':options,'selected':[loaded[k] for k in sorted(chosen)],'excluded':excluded}

    def start(self, imported, platform, content_id, entity_ref=None, derived_inputs=None):
        snapshot = build_analysis_snapshot(imported, platform, content_id, entity_ref=entity_ref,derived_inputs=derived_inputs)
        prompt_version = FULL_PROMPT_VERSION if 'analysis_batches' in snapshot else PROMPT_VERSION
        if not self.executable:
            raise ValueError('analysis_provider_missing')
        cache_key = hashlib.sha256(canonical({
            'snapshot': snapshot['snapshot_hash'], 'prompt': prompt_version,
            'provider_version': self.provider_version,
            **({'assembly_version': ASSEMBLY_VERSION} if 'analysis_batches' in snapshot else {}),
        }).encode()).hexdigest()
        with self.mutex:
            if self.closed:
                raise ValueError('analysis_service_closed')
            for folder in self.root.iterdir():
                if not folder.is_dir() or folder.is_symlink() or not (folder / 'state.json').is_file():
                    continue
                state = read(folder / 'state.json')
                if state.get('cache_key') == cache_key and state.get('state') == 'completed':
                    return {**self.status(state['job_id']), 'cached': True}
                if state.get('state') in ('queued', 'running'):
                    pid = state.get('provider_pid')
                    if state['job_id'] in self.running or self._alive(pid):
                        raise ValueError('analysis_busy')
            lock = (self.root / 'active.lock').open('a+')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock.close()
                raise ValueError('analysis_busy')
            job_id = str(uuid.uuid4())
            folder = self.root / job_id
            try:
                folder.mkdir(mode=0o700)
                write(folder / 'snapshot.json', snapshot)
                write(folder / 'schema.json', MODEL_SCHEMA)
                state = {'job_id': job_id, 'state': 'queued', 'cache_key': cache_key,
                         'snapshot_hash': snapshot['snapshot_hash'], 'run_id': imported.get('run_id'),
                         'platform': platform, 'content_id': content_id,
                         'prompt_version': prompt_version, 'provider': 'codex_cli',
                         'provider_version': self.provider_version, 'created_at': time.time(),
                         'review_status': 'unreviewed_model_analysis'}
                if 'analysis_batches' in snapshot:
                    state.update(total_batches=len(snapshot['analysis_batches']), completed_batches=0)
                if entity_ref is not None:
                    state['entity_ref'] = entity_ref
                write(folder / 'state.json', state)
                record = {'cancel': threading.Event(), 'process': None}
                self.running[job_id] = record
                thread = threading.Thread(target=self._work, args=(folder, state, snapshot, lock, record), daemon=True)
                record['thread'] = thread
                thread.start()
            except BaseException:
                self.running.pop(job_id, None)
                lock.close()
                raise
            return {'ok': True, **state, 'cached': False}

    def reassemble(self, job_id):
        """Create a new report from verified saved batches; never call a provider."""
        try:
            return self._reassemble(job_id)
        except (KeyError, TypeError, IndexError, OSError) as error:
            raise ValueError('analysis_reassembly_saved_files_invalid') from error

    def _reassemble(self, job_id):
        from analysis_artifact import _read, _safe_ancestors
        with self.mutex:
            if self.closed:
                raise ValueError('analysis_service_closed')
            folder = self.folder(job_id)
            state, _ = _read(folder / 'state.json', 65536)
            if state.get('state') != 'completed' or state.get('job_id') != job_id:
                raise ValueError('analysis_reassembly_not_completed')
            snapshot, snapshot_sha = _read(folder / 'snapshot.json', 8 * 1024 * 1024)
            original, result_sha = _read(folder / 'result.json', 8 * 1024 * 1024)
            batches = snapshot.get('analysis_batches')
            if (not isinstance(batches, list) or not 2 <= len(batches) <= 16
                    or type(state.get('total_batches')) is not int or state['total_batches'] != len(batches)
                    or type(state.get('completed_batches')) is not int or state['completed_batches'] != len(batches)):
                raise ValueError('analysis_reassembly_requires_full_batches')
            if (snapshot.get('snapshot_hash') != state.get('snapshot_hash')
                    or _hash({k:v for k,v in snapshot.items() if k != 'snapshot_hash'}) != state.get('snapshot_hash')
                    or snapshot.get('paragraphs') != _paragraphs(snapshot)
                    or original.get('input_snapshot') != snapshot
                    or original.get('snapshot_hash') != state['snapshot_hash']
                    or _platform(state.get('platform')) != snapshot.get('platform')
                    or state.get('content_id') != snapshot.get('content_id')
                    or state.get('entity_ref') is not None and state['entity_ref'] != snapshot['content'].get('entity_ref')
                    or any(original.get(key) != state.get(key) for key in ('provider', 'provider_version', 'prompt_version'))):
                raise ValueError('analysis_reassembly_snapshot_changed')
            results, proofs, saved_batches = [], [], []
            for index, batch in enumerate(batches):
                piece = batch['snapshot']
                saved, saved_sha = _read(folder / ('batch-%04d.json' % index), 8 * 1024 * 1024)
                if (saved.get('snapshot_hash') != piece.get('snapshot_hash')
                        or _hash({k:v for k,v in piece.items() if k != 'snapshot_hash'}) != piece.get('snapshot_hash')
                        or piece.get('paragraphs') != _paragraphs(piece)
                        or piece.get('content') != snapshot['content']
                        or piece.get('platform') != snapshot['platform']
                        or piece.get('content_id') != snapshot['content_id']
                        or piece.get('comments') != (snapshot['comments'] if index == 0 else [])):
                    raise ValueError('analysis_reassembly_batch_changed')
                checked = saved['result']
                analysis = checked['content_analysis']
                fields = {'segments': ('paragraph', 'role', 'observation'),
                          'claims': ('paragraph', 'claim', 'verification'),
                          'reusable_methods': ('paragraph', 'method')}
                raw = {'content_analysis': {'summary': analysis['summary'], 'limitations': analysis['limitations'],
                        **{key:[{field:row[field] for field in selected} for row in analysis[key]]
                           for key, selected in fields.items()}},
                       'comment_labels': [{key:row[key] for key in ('comment_id', 'text_sha256', 'sentiment', 'intent', 'aspects', 'rationale')}
                                          for row in checked['comment_labels']]}
                if canonical(validate_result(piece, raw)) != canonical(checked):
                    raise ValueError('analysis_reassembly_result_changed')
                results.append(checked); saved_batches.append(saved)
                proofs.append({'batch_index': index, 'file_sha256': saved_sha, 'snapshot_hash': piece['snapshot_hash']})
            assembled = combine_results(snapshot, results)
            if (original.get('full_analysis_coverage') != assembled['full_analysis_coverage']
                    or any(original.get(key) != results[0].get(key) for key in ('comment_labels', 'comment_statistics', 'label_schema', 'labeler', 'review_status'))):
                raise ValueError('analysis_reassembly_coverage_changed')
            provenance = {'source_job_id': job_id, 'source_result_sha256': result_sha,
                          'source_snapshot_file_sha256': snapshot_sha, 'batches': proofs,
                          'assembly_version': ASSEMBLY_VERSION, 'model_calls': 0, 'source_requests': 0}
            cache_key = _hash(provenance)
            assembled.update(snapshot_hash=state['snapshot_hash'], prompt_version=state['prompt_version'],
                             provider=state['provider'], provider_version=state['provider_version'], input_snapshot=snapshot)
            _safe_ancestors(self.root)
            for candidate in self.root.iterdir():
                if candidate.is_symlink() or not candidate.is_dir():
                    continue
                if not (candidate / 'state.json').exists():
                    continue
                cached, _ = _read(candidate / 'state.json', 65536)
                if cached.get('cache_key') == cache_key and cached.get('state') == 'completed':
                    cached_result, _ = _read(candidate / 'result.json', 8 * 1024 * 1024)
                    cached_snapshot, _ = _read(candidate / 'snapshot.json', 8 * 1024 * 1024)
                    if (canonical(cached.get('reassembly')) != canonical(provenance)
                            or canonical(cached_result) != canonical(assembled)
                            or canonical(cached_snapshot) != canonical(snapshot) or cached.get('job_id') != candidate.name):
                        raise ValueError('analysis_reassembly_result_changed')
                    return {'ok': True, **cached, 'result': cached_result, 'cached': True, 'model_calls': 0, 'source_requests': 0}
            new_id = str(uuid.uuid4())
            new_folder = self.root / new_id
            new_folder.mkdir(mode=0o700)
            now = time.time()
            new_state = {key:state[key] for key in ('snapshot_hash', 'run_id', 'platform', 'content_id',
                         'prompt_version', 'provider', 'provider_version', 'review_status', 'total_batches', 'completed_batches')}
            if 'entity_ref' in state:
                new_state['entity_ref'] = state['entity_ref']
            new_state.update(job_id=new_id, state='completed', created_at=now, completed_at=now,
                             cache_key=cache_key, reassembly=provenance)
            try:
                write(new_folder / 'snapshot.json', snapshot)
                for index, saved in enumerate(saved_batches):
                    write(new_folder / ('batch-%04d.json' % index), saved)
                write(new_folder / 'result.json', assembled)
                write(new_folder / 'state.json', new_state)
            except BaseException:
                shutil.rmtree(new_folder)
                raise
            return {'ok': True, **new_state, 'result': assembled, 'cached': False, 'model_calls': 0, 'source_requests': 0}

    @staticmethod
    def _alive(pid):
        if type(pid) is not int or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def _terminate(process):
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            except ProcessLookupError:
                pass

    def command(self, folder):
        command = [self.executable, '-a', 'never', 'exec', '--sandbox', 'read-only',
                   '--ephemeral', '--ignore-user-config', '--skip-git-repo-check',
                   '--enable', 'skip_host_skill_discovery', '-c', 'project_doc_max_bytes=0',
                   '-c', 'suppress_unstable_features_warning=true',
                   '-c', 'web_search="disabled"', '--output-schema', str(folder / 'schema.json'),
                   '--output-last-message', str(folder / 'model-output.json'), '--json', '--color', 'never']
        for feature in ('shell_tool', 'apps', 'plugins', 'hooks', 'memories', 'multi_agent',
                        'browser_use', 'computer_use', 'image_generation', 'code_mode_host',
                        'view_image', 'sleep_tool', 'workspace_dependencies'):
            command.extend(['--disable', feature])
        return command + ['-']

    def _work(self, folder, state, snapshot, lock, record):
        process = None
        try:
            # Existing auth is handled by Codex; this process never opens credential files.
            for name in ('model-output.json', 'events.jsonl'):
                with os.fdopen(os.open(folder / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w'):
                    pass
            batches = snapshot.get('analysis_batches') or [{'snapshot': snapshot}]
            results = []
            for index, batch in enumerate(batches):
                with (folder / 'events.jsonl').open('wb') as events:
                    with self.mutex:
                        if record['cancel'].is_set():
                            raise ValueError('analysis_cancelled')
                        # Never accept an output file left by an earlier batch.
                        (folder / 'model-output.json').write_text('')
                        process = subprocess.Popen(self.command(folder), cwd=folder, stdin=subprocess.PIPE,
                                                   stdout=events, stderr=subprocess.PIPE,
                                                   start_new_session=True, pass_fds=(lock.fileno(),))
                        record['process'] = process
                        state.update(state='running', provider_pid=process.pid, started_at=state.get('started_at', time.time()))
                        write(folder / 'state.json', state)
                    try:
                        _, diagnostic = process.communicate(make_prompt(batch['snapshot']).encode(), timeout=TIMEOUT_SECONDS)
                    except subprocess.TimeoutExpired:
                        self._terminate(process)
                        raise ValueError('analysis_timeout')
                if record['cancel'].is_set():
                    raise ValueError('analysis_cancelled')
                if process.returncode:
                    state['provider_returncode'] = process.returncode
                    raise ValueError(self._failure_code(diagnostic))
                if (folder / 'model-output.json').stat().st_size > 512 * 1024 or (folder / 'events.jsonl').stat().st_size > 2 * 1024 * 1024:
                    raise ValueError('analysis_output_limit')
                # The same strict output and tool-event checks apply to each call.
                turn_started = False
                for line in (folder / 'events.jsonl').read_text().splitlines():
                    event = json.loads(line)
                    if event.get('type') == 'turn.started':
                        turn_started = True
                    item = event.get('item', {})
                    # CLI 0.153 emits this startup notice as an error item even
                    # when the tool-free model turn succeeds. Accept only this
                    # exact notice; tool events and actual provider errors fail.
                    if (not turn_started and set(event) == {'type', 'item'}
                            and set(item) <= {'id', 'type', 'message'}
                            and event.get('type') == 'item.completed' and item.get('type') == 'error'
                            and item.get('message') == 'Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.'):
                        continue
                    if item and item.get('type') not in ('agent_message', 'reasoning'):
                        raise ValueError('analysis_unexpected_tool_event')
                checked = validate_result(batch['snapshot'], read(folder / 'model-output.json'))
                results.append(checked)
                if 'analysis_batches' in snapshot:
                    write(folder / ('batch-%04d.json' % index), {'snapshot_hash': batch['snapshot']['snapshot_hash'], 'result': checked})
                    with self.mutex:
                        state['completed_batches'] = index + 1
                        write(folder / 'state.json', state)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
            result = combine_results(snapshot, results) if 'analysis_batches' in snapshot else results[0]
            result.update(snapshot_hash=snapshot['snapshot_hash'], prompt_version=state['prompt_version'],
                          provider='codex_cli', provider_version=self.provider_version,
                          input_snapshot=snapshot)
            with self.mutex:
                if record['cancel'].is_set():
                    raise ValueError('analysis_cancelled')
                write(folder / 'result.json', result)
                state.update(state='completed', completed_at=time.time())
        except (ValueError, OSError, subprocess.SubprocessError, TypeError, KeyError) as error:
            self._terminate(process)
            state.update(state='cancelled' if record['cancel'].is_set() else 'failed',
                         error=str(error) if type(error) is ValueError and str(error).replace('_', '').isalnum()
                         else 'analysis_invalid_result', completed_at=time.time())
        finally:
            try:
                if process is not None:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None and not stream.closed:
                            stream.close()
                for name in ('model-output.json', 'events.jsonl'):
                    (folder / name).unlink(missing_ok=True)
                # Publish a terminal state only after private intermediate files are removed.
                write(folder / 'state.json', state)
            finally:
                with self.mutex:
                    self.running.pop(state['job_id'], None)
                lock.close()

    @staticmethod
    def _failure_code(diagnostic):
        # Classify in memory; never expose a raw provider message or credential in logs.
        text = diagnostic[:65536].decode('utf8', errors='replace').lower()
        for code, words in (
            ('analysis_environment_denied', ('operation not permitted', 'permission denied')),
            ('analysis_login_required', ('unauthorized', 'authentication required', '401 unauthorized')),
            ('analysis_quota_exceeded', ('quota exceeded', 'rate limit', '429 too many')),
            ('analysis_network_unavailable', ('error sending request', 'failed to connect', 'connection refused', 'stream disconnected')),
            ('analysis_provider_incompatible', ('unknown feature', 'unrecognized', 'invalid schema')),
        ):
            if any(word in text for word in words):
                return code
        return 'analysis_provider_failed'

    def cancel(self, job_id):
        self.folder(job_id)
        with self.mutex:
            record = self.running.get(job_id)
            if record:
                record['cancel'].set()
                process = record['process']
            else:
                process = None
        self._terminate(process)
        return self.status(job_id)

    def close(self):
        with self.mutex:
            self.closed = True
            records = list(self.running.values())
            for record in records:
                record['cancel'].set()
        for record in records:
            self._terminate(record['process'])
        for record in records:
            record['thread'].join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--platform', required=True)
    parser.add_argument('--content-id', required=True)
    parser.add_argument('--entity-ref', help='Exact saved content/dynamic identity; optional for legacy callers')
    parser.add_argument('--allow-model-transfer', action='store_true')
    args = parser.parse_args()
    if not args.allow_model_transfer:
        parser.error('analysis_transfer_authorization_required')
    manager = AnalysisJobs(args.root)
    try:
        job = manager.start(read(args.input), args.platform, args.content_id, entity_ref=args.entity_ref)
        while job['state'] in ('queued', 'running'):
            time.sleep(0.5)
            job = manager.status(job['job_id'])
        print(json.dumps(job, ensure_ascii=False))
    finally:
        manager.close()


if __name__ == '__main__':
    main()
