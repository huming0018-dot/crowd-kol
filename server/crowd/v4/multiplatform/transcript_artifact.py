"""Owner-only immutable full transcript cloud artifact; no remote analysis/inference."""
import hashlib
import importlib.util
import json
from pathlib import Path

from analysis_artifact import _read, _safe_ancestors
from mc_runner import canonical, contains_secret, write, uid as mc_uid, BridgeError
from results_store import _entity_selector, _typed_entity

HERE = Path(__file__).resolve().parent


def uid(value):
    try:
        return mc_uid(value)
    except (BridgeError, ValueError, TypeError, AttributeError):
        raise ValueError('invalid_media_job_id') from None


def load_transcript(jobs, identity):
    identity = uid(identity)
    if (jobs.root.parent / 'subtitle-jobs' / (identity + '.json')).exists():
        from bili_subtitles import subtitle_report
        return subtitle_report(jobs,identity)
    try:header = _read(jobs.root / identity / 'state.json', 65536)[0]
    except ValueError as error:
        if str(error) == 'unsafe_analysis_artifact_file':raise ValueError('unsafe_transcript_quality_path') from None
        raise
    if header.get('kind') == 'video_ocr':
        from video_ocr_jobs import load_video_ocr
        saved = load_video_ocr(jobs, identity)
        state, evidence = saved['state'], saved['evidence']
        segments = [{k: row[k] for k in ('start', 'end', 'text')} for row in evidence['segments']]
        text = '\n'.join(row['text'] for row in segments)
        provenance = {'provider': 'apple_vision', 'source_kind': 'sampled_video_text',
                      'source_video_sha256': state['asset_sha256'],
                      'source_reference_sha256': state['source_reference_sha256'],
                      'source_record_sha256': state['source_record_sha256'],
                      'sampling_fps': evidence['sample_fps'], 'sample_start': evidence['sample_start'],
                      'sample_end': evidence['sample_end'], 'sampled_frames': evidence['sampled_frames'],
                      'expected_frames': evidence['expected_frames'], 'crop_top_origin': evidence['crop_top_origin'],
                      'timestamp_kind': evidence['timestamp_kind'],
                      'timestamp_uncertainty_seconds': evidence['timestamp_uncertainty_seconds'],
                      'frame_evidence_sha256': evidence['frame_evidence_sha256'],
                      'frame_evidence_format': 'gzip_json_array_v1',
                      'coverage': 'all_scheduled_frames_processed', 'spoken_transcript': False,
                      'semantic_completeness': 'unknown', 'truncated': False}
        report = {'schema': 'crowd-video-ocr-report-v1', 'job_id': identity,
                  'video_source_job_id': state['video_source_job_id'], 'local_run_id': state['run_id'],
                  'platform': state['platform'], 'content_id': state['content_id'], 'entity_ref': state['entity_ref'],
                  'asset_sha256': state['asset_sha256'], 'input_hash': state['input_hash'],
                  'full_result_file_sha256': saved['result_sha256'], 'duration_seconds': evidence['duration_seconds'],
                  'segments': segments, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                  'segment_count': len(segments), 'character_count': sum(len(row['text']) for row in segments),
                  'semantic_review': 'not_reviewed', 'cer': None, 'human_groundtruth': False,
                  'diagnostics_sha256': evidence['frame_evidence_sha256'], 'model_manifest_sha256': None,
                  'processing_profile': state['processing_profile'], 'processor': evidence['processor'],
                  'text_revision': None, 'visual_provenance': provenance}
        raw = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(raw.encode()) > 200000 or not segments:raise ValueError('transcript_report_limit')
        if contains_secret(raw):raise ValueError('sensitive_transcript')
        return saved, report, raw
    spec = importlib.util.spec_from_file_location('cloud_transcript_quality', HERE.parent / 'postprocess/transcript_quality.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    saved = module.TranscriptQuality(jobs.root.parent).validate(uid(identity))
    evidence, state = saved['evidence'], saved['state']
    _entity_selector(state.get('entity_ref'), state['platform'], state['content_id'])
    if state['platform'] == 'zhihu' and state.get('entity_ref') not in {'zhihu:content:' + state['content_id'] + ':' + kind for kind in ('answer', 'article', 'zvideo')}:
        raise ValueError('transcript_source_binding_denied')
    segments = evidence['segments']
    text = '\n'.join(row['text'] for row in segments)
    diagnostic = evidence.get('quality_diagnostics')
    report = {'schema': 'crowd-transcript-report-v1', 'job_id': identity,
              'audio_source_job_id': saved['audio_source_job_id'], 'local_run_id': uid(state.get('run_id')),
              'platform': state['platform'], 'content_id': state['content_id'], 'entity_ref': state.get('entity_ref'),
              'asset_sha256': state['asset_sha256'], 'input_hash': state['input_hash'],
              'full_result_file_sha256': saved['result_sha256'], 'duration_seconds': evidence['duration_seconds'],
              'segments': segments, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
              'segment_count': len(segments), 'character_count': sum(len(row['text']) for row in segments),
              'semantic_review': 'not_reviewed', 'cer': None, 'human_groundtruth': False,
              'diagnostics_sha256': hashlib.sha256(json.dumps(diagnostic, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest() if diagnostic is not None else None,
              'model_manifest_sha256': state.get('model_manifest_sha256'),
              'processing_profile': state.get('processing_profile'), 'processor': evidence.get('processor'),
              'text_revision': state.get('text_revision')}
    for key in ('asset_sha256', 'input_hash', 'full_result_file_sha256', 'text_sha256'):
        value = report[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('invalid_transcript')
    raw = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(raw.encode()) > 200000:
        raise ValueError('transcript_report_limit')
    if contains_secret(raw):
        raise ValueError('sensitive_transcript')
    return saved, report, raw


def prepare_transcript_artifact(jobs, client, identity):
    if client is None:
        raise ValueError('cloud_configuration_required')
    saved, report, raw = load_transcript(jobs, identity)
    local = report['local_run_id']
    matches = set()
    for task in client.call('task_list').get('tasks', []):
        for child in task.get('children', []):
            for attempt in child.get('attempts', []):
                if attempt.get('local_run_id') == local:
                    epoch = attempt.get('lease_epoch')
                    if type(epoch) is not int or not 1 <= epoch <= 2147483647:
                        raise ValueError('transcript_source_binding_denied')
                    matches.add((uid(task['task_id']), uid(child['child_id']), uid(attempt['run_id']), epoch))
    if len(matches) != 1:
        raise ValueError('transcript_source_binding_denied')
    task_id, child_id, run_id, epoch = matches.pop()
    refs, types, kinds = [], set(), set()
    for item in client.call('results', {'task_id': task_id}).get('items', []):
        record, receipt = item.get('record', {}), item.get('receipt', {})
        if receipt.get('run_id') != run_id or receipt.get('lease_epoch') != epoch:
            continue
        if record.get('platform') != report['platform'] or record.get('content_id') != report['content_id'] or record.get('kind') not in ('content', 'dynamic'):
            continue
        expected = {'task_id': task_id, 'child_id': child_id, 'run_id': run_id, 'lease_epoch': epoch, 'status': 'received', 'reward_eligible': False}
        if any(canonical(receipt.get(k)) != canonical(v) for k, v in expected.items()) or record.get('origin', {}).get('run_id') != local or record.get('reward_eligible') is not False:
            raise ValueError('transcript_source_binding_denied')
        ref = {'capture_id': uid(receipt.get('capture_id')), 'envelope_hash': receipt.get('envelope_hash')}
        if not isinstance(ref['envelope_hash'], str) or len(ref['envelope_hash']) != 64 or any(c not in '0123456789abcdef' for c in ref['envelope_hash']):
            raise ValueError('transcript_source_binding_denied')
        refs.append(ref)
        known = {record[k] for k in ('content_type', 'source_content_type') if isinstance(record.get(k), str) and record[k]}
        if len(known) > 1:
            raise ValueError('transcript_source_binding_denied')
        types.update(known)
        kinds.add(record['kind'])
    if not refs or len(refs) > 2000 or len({r['capture_id'] for r in refs}) != len(refs) or len(types) > 1 or len(kinds) != 1:
        raise ValueError('transcript_source_binding_denied')
    content_type = next(iter(types), None)
    kind = next(iter(kinds))
    expected_entity = _typed_entity(report['platform'] + ':' + kind + ':' + report['content_id'], {'platform': report['platform'], 'kind': kind, 'content_id': report['content_id'], 'content_type': content_type})
    if report['entity_ref'] is not None and report['entity_ref'] != expected_entity:
        raise ValueError('transcript_source_binding_denied')
    payload = {'idempotency_key': 'transcript:' + identity, 'task_id': task_id, 'child_id': child_id, 'run_id': run_id,
               'lease_epoch': epoch, 'local_run_id': local, 'local_job_id': identity, 'source_refs': sorted(refs, key=lambda r: r['capture_id']),
               'report_sha256': hashlib.sha256(raw.encode()).hexdigest(), 'report_json': raw}
    if len(canonical({'action': 'transcript_put', 'payload': payload}).encode()) > 300000:
        raise ValueError('transcript_report_limit')
    return payload


def verify(payload, receipt):
    expected = {k: payload[k] for k in ('task_id', 'child_id', 'run_id', 'lease_epoch', 'local_run_id', 'local_job_id', 'source_refs', 'report_sha256')}
    digest = hashlib.sha256(('crowd-transcript-artifact-v1\n' + canonical(payload)).encode()).hexdigest()
    if any(canonical(receipt.get(k)) != canonical(v) for k, v in expected.items()) or receipt.get('artifact_hash') != digest or receipt.get('artifact_kind') != 'transcript_report' or receipt.get('status') != 'received' or receipt.get('reward_eligible') is not False:
        raise ValueError('transcript_receipt_mismatch')
    uid(receipt.get('artifact_id'))
    report = json.loads(payload['report_json'])
    for key in ('text_sha256', 'asset_sha256', 'full_result_file_sha256', 'segment_count', 'character_count', 'semantic_review'):
        if canonical(receipt.get(key)) != canonical(report[key]):
            raise ValueError('transcript_receipt_mismatch')


def transcript_cloud(jobs, client, identity, action):
    identity = uid(identity)
    if action not in ('status', 'save', 'get'):
        raise ValueError('invalid_transcript_cloud_request')
    folder = jobs.root.parent / 'transcript-artifact-receipts'
    _safe_ancestors(folder)
    path = folder / (identity + '.json')
    payload = prepare_transcript_artifact(jobs, client, identity)
    if action == 'save':
        response = client.call('transcript_put', payload)
        receipt = response.get('receipt', {})
        verify(payload, receipt)
        folder.mkdir(mode=0o700, exist_ok=True)
        _safe_ancestors(path)
        if path.is_symlink() or path.exists() and path.stat().st_nlink != 1:
            raise ValueError('unsafe_analysis_artifact_file')
        write(path, {'job_id': identity, 'endpoint_sha256': hashlib.sha256(client.endpoint.encode()).hexdigest(), 'receipt': receipt})
        return {'ok': True, 'status': 'received', 'receipt': receipt, 'replayed': response.get('replayed') is True, 'source_requests': 0, 'model_calls': 0}
    if action not in ('status', 'get'):
        raise ValueError('invalid_transcript_cloud_request')
    if path.exists() or path.is_symlink():
        saved, _ = _read(path, 65536)
        if saved.get('job_id') != identity or saved.get('endpoint_sha256') != hashlib.sha256(client.endpoint.encode()).hexdigest():
            raise ValueError('transcript_receipt_mismatch')
        verify(payload, saved.get('receipt', {}))
    try:
        response = client.call('transcript_get', {'local_job_id': identity})
    except ValueError as error:
        if action == 'status' and str(error) == 'transcript_not_found':
            return {'ok': True, 'status': 'not_saved', 'job_id': identity, 'source_requests': 0, 'model_calls': 0}
        raise
    verify(payload, response.get('receipt', {}))
    cloud = response.get('artifact', {})
    if canonical(cloud) != canonical(payload):
        raise ValueError('transcript_receipt_mismatch')
    return {'ok': True, 'status': 'received', 'receipt': response['receipt'], 'report': json.loads(payload['report_json']) if action == 'get' else None, 'source_requests': 0, 'model_calls': 0}
