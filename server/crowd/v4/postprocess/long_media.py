#!/usr/bin/env python3
"""Bounded local audio extraction and resumable ASR; never downloads models."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
import unicodedata
import wave

RATE = 16000
SEGMENT_SECONDS = 55
OVERLAP_SECONDS = 2
MAX_SECONDS = 3600
MAX_BYTES = 25 * 1024 * 1024
LONG_AUDIO_SUFFIXES = frozenset(('.m4a', '.mp3', '.aac'))
LONG_AUDIO_BYTES = 64 * 1024 * 1024
LONG_AUDIO_SECONDS = 7200
SCHEMA = 1


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def ffmpeg_path():
    value = os.environ.get('CROWD_FFMPEG') or shutil.which('ffmpeg')
    return str(Path(value).resolve()) if value and Path(value).is_file() else None


def check_cancel(cancel=None):
    if cancel and cancel():
        raise ValueError('long_media_cancelled')


def safe_work_directory(source, work_dir):
    work = Path(work_dir).absolute()
    # macOS system aliases are canonicalized; user-created ancestor links are not.
    for alias, canonical in (('/var', '/private/var'), ('/tmp', '/private/tmp')):
        if (Path(alias).is_symlink() and Path(alias).resolve() == Path(canonical)
                and (work == Path(alias) or Path(alias) in work.parents)):
            work = Path(canonical) / work.relative_to(alias)
    if any(path.is_symlink() for path in (work, *work.parents)):
        raise ValueError('unsafe_long_media_work_directory')
    if Path(source).resolve().is_relative_to(work):
        raise ValueError('unsafe_long_media_work_directory')
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in work.iterdir():
        if path.is_symlink():
            raise ValueError('unsafe_long_media_work_file')
    return work


def exclusive_audio_file(work, prefix):
    path = work / (prefix + '.' + uuid.uuid4().hex + '.wav')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    return path, descriptor


def prepare_chunks(source, work_dir, cancel=None):
    source = Path(source)
    long_audio = source.suffix.lower() in LONG_AUDIO_SUFFIXES
    max_bytes = LONG_AUDIO_BYTES if long_audio else MAX_BYTES
    max_seconds = LONG_AUDIO_SECONDS if long_audio else MAX_SECONDS
    if source.is_symlink() or not source.is_file() or source.stat().st_size > max_bytes:
        raise ValueError('media_missing_or_over_processing_limit')
    work = safe_work_directory(source, work_dir)
    source_hash = digest(source)
    manifest_path = work / 'chunks.json'
    if manifest_path.is_file():
        if manifest_path.is_symlink() or manifest_path.stat().st_size > 50000:
            raise ValueError('invalid_long_media_checkpoint')
        existing = json.loads(manifest_path.read_text())
        if not isinstance(existing, dict) or existing.get('asset_sha256') != source_hash or existing.get('schema') != SCHEMA:
            raise ValueError('long_media_checkpoint_identity_mismatch')
        rows = existing.get('chunks')
        duration = existing.get('duration_seconds')
        if not isinstance(rows, list) or not 1 <= len(rows) <= math.ceil(max_seconds / (SEGMENT_SECONDS - OVERLAP_SECONDS)) or type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= max_seconds:
            raise ValueError('invalid_long_media_checkpoint')
        for index, row in enumerate(rows):
            start = index * (SEGMENT_SECONDS - OVERLAP_SECONDS)
            if (not isinstance(row, dict) or set(row) != {'index', 'start', 'end', 'file', 'sha256'}
                    or type(row['index']) is not int or row['index'] != index or row['file'] != 'chunk-%04d.wav' % index
                    or row['start'] != start or row['end'] != min(duration, start + SEGMENT_SECONDS)
                    or not isinstance(row['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', row['sha256'])):
                raise ValueError('invalid_long_media_checkpoint')
        if rows[-1]['end'] != duration:
            raise ValueError('incomplete_long_media_checkpoint')
        if all((work / row['file']).is_file() and not (work / row['file']).is_symlink()
               and digest(work / row['file']) == row['sha256'] for row in rows):
            check_cancel(cancel)
            return existing
        raise ValueError('long_media_checkpoint_audio_corrupt')
    check_cancel(cancel)
    audio = work / 'audio.wav'
    # WAV PCM already has a seekable, bounded decoder in the standard library.
    try:
        with wave.open(str(source), 'rb') as handle:
            compatible = handle.getnchannels() == 1 and handle.getsampwidth() == 2 and handle.getframerate() == RATE
        if compatible:
            temporary, descriptor = exclusive_audio_file(work, 'audio-copy')
            try:
                with source.open('rb') as original, os.fdopen(descriptor, 'wb') as output:
                    shutil.copyfileobj(original, output)
                    output.flush(); os.fsync(output.fileno())
                os.replace(temporary, audio)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            compatible = False
    except (wave.Error, EOFError):
        compatible = False
    if not compatible:
        executable = ffmpeg_path()
        if executable is None:
            raise ValueError('audio_ffmpeg_unavailable')
        temporary, descriptor = exclusive_audio_file(work, 'audio-partial')
        os.close(descriptor)
        command = [executable, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                   '-protocol_whitelist', 'file,pipe', '-format_whitelist',
                   'wav,mp3,aac,mov,aiff,caf,ogg,matroska,webm,flac',
                   *(['-enable_drefs','0'] if source.suffix.lower() in ('.mov','.mp4','.m4a','.m4v') else []),
                   '-i', str(source.resolve()), '-map', '0:a:0', '-vn', '-t', str(max_seconds + 1),
                   '-ac', '1', '-ar', str(RATE), '-c:a', 'pcm_s16le', str(temporary)]
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 180
        try:
            while proc.poll() is None:
                check_cancel(cancel)
                if time.monotonic() >= deadline:
                    raise ValueError('audio_extraction_timeout')
                time.sleep(0.05)
            check_cancel(cancel)
            if proc.returncode:
                raise ValueError('audio_extraction_failed')
            os.replace(temporary, audio)
            os.chmod(audio, 0o600)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            temporary.unlink(missing_ok=True)
    with wave.open(str(audio), 'rb') as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2 or handle.getframerate() != RATE:
            raise ValueError('invalid_extracted_audio')
        frames = handle.getnframes()
        duration = frames / RATE
        if not frames or duration > max_seconds:
            raise ValueError('audio_empty_or_over_duration_limit')
        chunks = []
        step = (SEGMENT_SECONDS - OVERLAP_SECONDS) * RATE
        for index, start in enumerate(range(0, frames, step)):
            check_cancel(cancel)
            end = min(frames, start + SEGMENT_SECONDS * RATE)
            handle.setpos(start)
            target = work / ('chunk-%04d.wav' % index)
            temporary, descriptor = exclusive_audio_file(work, 'chunk-partial')
            try:
                with os.fdopen(descriptor, 'wb') as stream, wave.open(stream, 'wb') as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(RATE)
                    output.writeframes(handle.readframes(end - start))
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            chunks.append({'index': index, 'start': start / RATE, 'end': end / RATE,
                           'file': target.name, 'sha256': digest(target)})
            if end == frames:
                break
    manifest = {'schema': SCHEMA, 'asset_sha256': source_hash, 'duration_seconds': duration,
                'segment_seconds': SEGMENT_SECONDS, 'overlap_seconds': OVERLAP_SECONDS,
                'chunks': chunks, 'source_kind': 'authorized_local_file', 'network': False}
    save(manifest_path, manifest)
    return manifest


def validate_segments(rows, duration):
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError('invalid_asr_segments')
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'start', 'end', 'text'}:
            raise ValueError('invalid_asr_segment')
        start, end, text = row['start'], row['end'], row['text']
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end <= duration + 0.1
                or start > duration
                or not isinstance(text, str) or not text.strip() or len(text) > 4000):
            raise ValueError('invalid_asr_segment')
        result.append({'start': float(start), 'end': min(float(end), duration), 'text': text.strip()})
    return result


def validate_adjustments(adjustments, rows, duration):
    if not isinstance(adjustments, list) or len(adjustments) > len(rows):
        raise ValueError('invalid_asr_timing_adjustments')
    seen = set()
    for item in adjustments:
        fields = {'segment_index', 'provider_start', 'provider_end', 'adjusted_end', 'reason', 'text'}
        padding = isinstance(item, dict) and item.get('reason') == 'provider_padding_tail'
        if not isinstance(item, dict) or set(item) != fields | ({'provider_padding_end'} if padding else set()):
            raise ValueError('invalid_asr_timing_adjustments')
        index = item['segment_index']
        if type(index) is not int or index in seen or not 0 <= index < len(rows):
            raise ValueError('invalid_asr_timing_adjustments')
        seen.add(index)
        start, end, adjusted = item['provider_start'], item['provider_end'], item['adjusted_end']
        if (any(type(value) not in (int, float) or not math.isfinite(value) for value in (start,end,adjusted))
                or not 0 <= start < duration < end
                or (not padding and end > duration + .5)
                or (padding and not duration + .5 < end < duration + 1.)
                or (padding and (type(item['provider_padding_end']) not in (int,float)
                    or not math.isfinite(item['provider_padding_end'])
                    or not duration < item['provider_padding_end'] <= duration + 30
                    or end > item['provider_padding_end']))
                or not math.isclose(adjusted, duration, rel_tol=0, abs_tol=1e-6)
                or rows[index]['start'] != start
                or not math.isclose(rows[index]['end'], adjusted, rel_tol=0, abs_tol=1e-6)
                or rows[index]['text'] != item['text']
                or item['reason'] not in ('provider_tail_overrun','provider_padding_tail')):
            raise ValueError('invalid_asr_timing_adjustments')
    return adjustments


def merge_chunks(manifest, results):
    import local_asr
    if len(results) != len(manifest['chunks']):
        raise ValueError('incomplete_asr_chunk_results')
    merged, removed, adjustments, decisions, diagnostics = [], 0, [], [], []
    total_segments = 0
    native_alignment_windows = []
    windows = {chunk['index']: chunk for chunk in manifest['chunks']}

    def normalized(text):
        return ''.join(char for char in unicodedata.normalize('NFKC', text).casefold()
                       if not char.isspace() and not unicodedata.category(char).startswith('P'))

    def edge_match(short, longer):
        if len(short) < 6:
            return None
        return 'prefix' if longer.startswith(short) else 'suffix' if longer.endswith(short) else None
    for chunk, result in zip(manifest['chunks'], results):
        rows = validate_segments(result['segments'], chunk['end'] - chunk['start'])
        alignment=local_asr.validate_native_alignment(result.get('native_alignment'),rows,chunk['end']-chunk['start'])
        native_alignment_windows.append({'chunk_index':chunk['index'],'chunk_start_seconds':chunk['start'],
            'status':'recorded' if alignment is not None else 'unknown',
            'time_basis':'chunk_local_seconds','receipt':alignment})
        total_segments += len(rows)
        quality = local_asr.quality_diagnostics(rows, result.get('segment_metrics'))
        # Scores belong to the original window text, including fragments later removed.
        for entry in quality['segments']:
            diagnostics.append({**entry, 'chunk_index': chunk['index'],
                                'chunk_start_seconds': chunk['start'],
                                'local_start': entry['start'], 'local_end': entry['end'],
                                'start': min(round(chunk['start'] + entry['start'], 3), manifest['duration_seconds']),
                                'end': min(round(chunk['start'] + entry['end'], 3), manifest['duration_seconds'])})
        for adjustment in validate_adjustments(result.get('timing_adjustments', []), rows, chunk['end'] - chunk['start']):
            adjustments.append({**adjustment, 'chunk_index': chunk['index'],
                                'chunk_start_seconds': chunk['start'],
                                'provider_time_basis': 'chunk_local_seconds',
                                'provider_absolute_end': chunk['start'] + adjustment['provider_end'],
                                'adjusted_absolute_end': chunk['start'] + adjustment['adjusted_end']})
        for row in rows:
            value = {**row, 'start': min(round(chunk['start'] + row['start'], 3), manifest['duration_seconds']),
                     'end': min(round(chunk['start'] + row['end'], 3), manifest['duration_seconds']),
                     'chunk_index': chunk['index']}
            normal = normalized(value['text'])
            drop = False
            for old in reversed(merged[-100:]):
                if (old['chunk_index'] == value['chunk_index']
                        or max(old['start'], value['start']) >= min(old['end'], value['end'])):
                    continue
                other = windows[old['chunk_index']]
                overlap_start, overlap_end = max(other['start'], chunk['start']), min(other['end'], chunk['end'])
                if overlap_start >= overlap_end:
                    continue
                previous = normalized(old['text'])
                if previous == normal:
                    decisions.append({'action': 'merge_exact_overlap', 'original_segments': [dict(old), dict(value)],
                                      'overlap_start': overlap_start, 'overlap_end': overlap_end,
                                      'normalization': 'NFKC/casefold/no_unicode_punctuation_or_whitespace'})
                    old['start'], old['end'] = min(old['start'], value['start']), max(old['end'], value['end'])
                    removed += 1
                    drop = True
                    break
                shorter, longer = (old, value) if len(previous) < len(normal) else (value, old)
                short_text, long_text = (previous, normal) if shorter is old else (normal, previous)
                match = edge_match(short_text, long_text)
                short_window = windows[shorter['chunk_index']]
                # A short word group may be clipped inside a longer sentence at the window cut.
                if (not match and len(short_text) >= 3 and short_text in long_text
                        and long_text.find(short_text) == long_text.rfind(short_text)
                        and longer['start'] <= shorter['start'] <= shorter['end'] <= longer['end']
                        and (shorter['start'] == short_window['start']
                             or shorter['end'] == min(round(short_window['end'], 3), manifest['duration_seconds']))):
                    match = 'unique_window_cut_substring'
                # Only a whole fragment inside the actual two-window overlap is removable.
                if (not match or len(short_text) >= len(long_text)
                        or shorter['start'] < overlap_start or shorter['end'] > overlap_end):
                    continue
                decisions.append({'action': 'remove_contained_overlap_fragment', 'match': match,
                                  'removed_segment': dict(shorter), 'retained_segment': dict(longer),
                                  'overlap_start': overlap_start, 'overlap_end': overlap_end,
                                  'normalization': 'NFKC/casefold/no_unicode_punctuation_or_whitespace'})
                removed += 1
                if shorter is old:
                    merged.remove(old)
                else:
                    drop = True
                    break
            if not drop:
                merged.append(value)
    merged.sort(key=lambda x: (x['start'], x['end'], x['chunk_index']))
    raw = '\n'.join('[%.2f–%.2f] %s' % (r['start'], r['end'], r['text']) for r in merged)
    return {'raw_text': raw[:24000], 'segments': merged, 'truncated': len(raw) > 24000,
            'duration_seconds': manifest['duration_seconds'], 'processor': 'faster_whisper_local_segmented',
            'deduplicated_overlap_segments': removed, 'timeline': 'absolute_seconds',
            'overlap_decisions': decisions,
            'timing_adjustments': adjustments,
            'native_alignment_windows':native_alignment_windows,
            'quality_diagnostics': {**local_asr.diagnostic_summary(diagnostics, total_segments),
                                    'time_basis': 'original_audio_seconds'},
            'segment_seconds': SEGMENT_SECONDS, 'overlap_seconds': OVERLAP_SECONDS}


def transcribe_long(source, model_dir, work_dir, cancel=None, transcriber=None):
    # Gate before lock creation and before any error-state receipt can be written.
    work = safe_work_directory(source, work_dir)
    descriptor = os.open(work / 'active.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'r+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('long_media_busy') from None
        state = {'state': 'preparing', 'completed_chunks': 0, 'total_chunks': 0}
        try:
            manifest = prepare_chunks(source, work, cancel)
            state['total_chunks'] = len(manifest['chunks'])
            if transcriber is None:
                model_dir = Path(model_dir) if model_dir is not None else None
                if model_dir is None or not (model_dir / 'crowd-model.json').is_file():
                    raise ValueError('local_asr_model_not_configured')
                import local_asr
                transcriber = lambda path: local_asr.transcribe(path, model_dir)
                model_hash = digest(model_dir / 'crowd-model.json')
            else:
                # Test injection never claims an actual model provider.
                model_hash = 'injected-offline-test-provider'
            results = []
            for chunk in manifest['chunks']:
                check_cancel(cancel)
                state.update(state='transcribing', current_chunk=chunk['index'])
                save(work / 'state.json', state)
                target = work / ('result-%04d.json' % chunk['index'])
                if target.is_symlink() or target.exists() and target.stat().st_size > 2_000_000:
                    raise ValueError('invalid_long_media_chunk_cache')
                processor_hash = (digest(Path(__file__)) + digest(Path(__file__).with_name('local_asr.py'))
                                  + digest(Path(__file__).with_name('fetch_model.py')))
                key = hashlib.sha256((chunk['sha256'] + model_hash + processor_hash + str(SCHEMA)).encode()).hexdigest()
                result = json.loads(target.read_text()) if target.is_file() else None
                if result is not None and (not isinstance(result, dict) or set(result) not in ({'segments', 'input_hash', 'timing_adjustments', 'segment_metrics'},
                                            {'segments', 'input_hash', 'timing_adjustments', 'segment_metrics', 'native_alignment'}) or result.get('input_hash') != key):
                    raise ValueError('long_media_chunk_cache_identity_mismatch')
                if result is None:
                    try:
                        result = transcriber(work / chunk['file'])
                    except ValueError as error:
                        if str(error) != 'speech_empty':
                            raise
                        result = {'segments': [], 'truncated': False,'native_alignment':getattr(error,'native_alignment',None)}
                    except ImportError:
                        raise ValueError('local_asr_dependencies_unavailable') from None
                    except RuntimeError:
                        raise ValueError('local_asr_provider_failed') from None
                    if not isinstance(result, dict) or result.get('truncated'):
                        raise ValueError('asr_chunk_incomplete')
                    # The existing local provider now supplies structured seconds.
                    rows = validate_segments(result.get('segments'), chunk['end'] - chunk['start'])
                    adjustments = result.get('timing_adjustments', [])
                    validate_adjustments(adjustments, rows, chunk['end'] - chunk['start'])
                    import local_asr
                    metrics = local_asr.normalize_metrics(result.get('segment_metrics'), len(rows))
                    result = {'segments': rows, 'input_hash': key, 'timing_adjustments': adjustments,
                              'segment_metrics': metrics,
                              'native_alignment': local_asr.validate_native_alignment(result.get('native_alignment'),rows,chunk['end']-chunk['start'])}
                    save(target, result)
                import local_asr
                local_asr.validate_native_alignment(result.get('native_alignment'),
                    validate_segments(result['segments'],chunk['end']-chunk['start']),chunk['end']-chunk['start'])
                results.append(result)
                state['completed_chunks'] += 1
                save(work / 'state.json', state)
            result = merge_chunks(manifest, results)
            result['audio_windows_processed'] = len(results)
            result['no_text_windows'] = sum(not row['segments'] for row in results)
            result['transcript_completeness'] = 'not_independently_verified'
            if not result['segments']:
                raise ValueError('speech_empty')
            state.update(state='completed')
            save(work / 'state.json', state)
            return result
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            reason = str(error) if isinstance(error, ValueError) and re.fullmatch('[a-z0-9_]{1,100}', str(error)) else 'long_media_processing_failed'
            state.update(state='cancelled' if reason == 'long_media_cancelled' else
                         'model_unavailable' if reason == 'local_asr_model_not_configured' else 'failed', reason=reason)
            save(work / 'state.json', state)
            raise ValueError(reason) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--asr-model', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--platform', required=True)
    parser.add_argument('--content-id', required=True)
    parser.add_argument('--authorization-ref', required=True)
    args = parser.parse_args()
    cancelled = False

    def stop(*_):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        import evidence
        row = evidence.prepare('asr', args.input, args.platform, args.content_id, args.authorization_ref,
                               asr_model=args.asr_model, work_dir=args.work_dir,
                               cancel=lambda: cancelled or (args.work_dir.parent / 'cancel.requested').exists())
        encoded = json.dumps([row], ensure_ascii=False).encode()
        if len(encoded) > 2_000_000:
            raise ValueError('long_media_result_over_2mb')
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
            output.write(encoded)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError):
        return 1


if __name__ == '__main__':
    sys.exit(main())
