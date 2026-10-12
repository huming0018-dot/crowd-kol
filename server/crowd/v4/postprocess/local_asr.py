#!/usr/bin/env python3
"""Explicit offline ASR. Requires a local CTranslate2 model; never downloads it."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import unicodedata
from fetch_model import FILES, model_profile


METRIC_FIELDS = ('avg_logprob', 'compression_ratio', 'no_speech_prob')


def normalize_metrics(metrics, count):
    if metrics is None:
        return None
    if not isinstance(metrics, list) or len(metrics) != count or count > 1000:
        raise ValueError('invalid_asr_segment_metrics')
    result = []
    for index, metric in enumerate(metrics):
        if (not isinstance(metric, dict) or set(metric) != {'segment_index', *METRIC_FIELDS}
                or type(metric['segment_index']) is not int or metric['segment_index'] != index):
            raise ValueError('invalid_asr_segment_metrics')
        row = {'segment_index': index}
        for field in METRIC_FIELDS:
            value = metric[field]
            try:
                valid = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                valid = False
            if valid and field == 'no_speech_prob':
                valid = 0 <= value <= 1
            if valid and field == 'compression_ratio':
                valid = value >= 0
            row[field] = float(value) if valid else None
        result.append(row)
    return result


def diagnostic_summary(entries, total):
    recorded = sum(row[field] is not None for row in entries for field in METRIC_FIELDS)
    return {'schema_version': 1, 'status': 'available' if total and recorded == total * 3 else
            'partial' if recorded else 'unknown', 'review_status': 'not_reviewed',
            'policy': 'native_metrics_review_hints_v1', 'total_segments': total,
            'association': 'original_window_segments_not_merged_text', 'segments': entries}


def repeated_text_indices(rows):
    """Review candidate only: three adjacent equal phrases within one short window."""
    flagged, streak, previous = set(), [], None
    for index, row in enumerate(rows):
        text, start, end = row.get('text'), row.get('start'), row.get('end')
        chunk = row.get('chunk_index')
        try:
            valid = (isinstance(text, str) and type(start) in (int, float)
                     and type(end) in (int, float) and math.isfinite(start) and math.isfinite(end)
                     and 0 <= start <= end and (chunk is None or type(chunk) is int and chunk >= 0))
        except OverflowError:
            valid = False
        normal = ''.join(char for char in unicodedata.normalize('NFKC', text).lower()
                         if not char.isspace() and not unicodedata.category(char).startswith('P')) if valid else ''
        if not 2 <= len(normal) <= 200:
            streak, previous = [], None
            continue
        key = (chunk, normal)
        if (previous is not None and key == previous[0]
                and previous[1] <= start <= previous[2] + 1
                and end - rows[streak[0]]['start'] <= 15):
            streak.append(index)
        else:
            streak = [index]
        previous = (key, start, end)
        if len(streak) >= 3:
            flagged.update(streak)
    return flagged


def quality_diagnostics(rows, metrics=None):
    metrics = normalize_metrics(metrics, len(rows))
    entries = []
    for row, metric in zip(rows, metrics or []):
        flags = []
        low = metric['avg_logprob'] is not None and metric['avg_logprob'] < -1.
        if low:
            flags.append('low_logprob')
        if metric['compression_ratio'] is not None and metric['compression_ratio'] > 2.4:
            flags.append('high_compression')
        if low and metric['no_speech_prob'] is not None and metric['no_speech_prob'] > .6:
            flags.append('possible_no_speech')
        entries.append({**row, **metric, 'flags': flags})
    for index in repeated_text_indices(entries):
        entries[index]['flags'].append('repeated_adjacent_text')
    return {**diagnostic_summary(entries, len(rows)), 'time_basis': 'local_file_seconds'}


def normalize_timestamps(rows, duration, provider_padding_ends=None):
    """Allow only a small provider tail overrun; retain the original estimate."""
    timeline, adjustments = [], []
    if provider_padding_ends is not None and len(provider_padding_ends) != len(rows):
        raise ValueError('invalid_asr_padding_evidence')
    for index, row in enumerate(rows):
        start, end, text = row['start'], row['end'], row['text']
        padding_end = provider_padding_ends[index] if provider_padding_ends is not None else None
        padded_tail = (type(padding_end) in (int, float) and math.isfinite(padding_end)
                       and duration < padding_end <= duration + 30
                       and end <= padding_end and end < duration + 1.)
        if (not math.isfinite(start) or not math.isfinite(end)
                or not 0 <= start <= end or start >= duration
                or end > duration + 0.5 and not padded_tail):
            raise ValueError('asr_provider_timestamp_out_of_bounds')
        if end > duration:
            adjustments.append({'segment_index': len(timeline), 'provider_start': start,
                                'provider_end': end, 'adjusted_end': duration,
                                'reason': 'provider_padding_tail' if end > duration + .5 else 'provider_tail_overrun', 'text': text,
                                **({'provider_padding_end': padding_end} if end > duration + .5 else {})})
        timeline.append({'start': start, 'end': min(end, duration), 'text': text})
    return timeline, adjustments


def validate_native_alignment(value, rows, duration):
    if isinstance(value, dict) and value.get('method') in ('mlx_whisper_word_timestamps','mlx_whisper_decoder_timestamps'):
        from mlx_asr import validate_alignment
        return validate_alignment(value, rows, duration)
    if value is None:
        return None  # Old caches did not record native alignment provenance.
    def finite(value):
        try:return type(value) in (int,float) and math.isfinite(value)
        except OverflowError:return False
    fields = {'method','source','pcm_duration_seconds','token_candidates','aligned_estimates','text_sequence_equal','semantic_status'}
    if (not isinstance(value,dict) or set(value)!=fields
            or value['method']!='faster_whisper_word_timestamps'
            or value['source']!='same_native_decode_before_word_alignment'
            or value['semantic_status']!='not_reviewed'
            or type(value['text_sequence_equal']) is not bool
            or not finite(value['pcm_duration_seconds'])
            or not math.isclose(value['pcm_duration_seconds'],duration,rel_tol=0,abs_tol=1e-6)):
        raise ValueError('invalid_native_asr_alignment')
    raw, aligned = value['token_candidates'],value['aligned_estimates']
    if not isinstance(raw,list) or len(raw)>1000 or not isinstance(aligned,list) or len(aligned)!=len(rows):
        raise ValueError('invalid_native_asr_alignment')
    chars=0
    for group in (raw,aligned):
        for index,row in enumerate(group):
            keys={'start','end','text'} | ({'seek_frames','padding_end'} if group is raw else set())
            if (not isinstance(row,dict) or set(row)!=keys
                    or any(not finite(row[k]) for k in ('start','end'))
                    or not 0<=row['start']<=row['end']<=duration+30
                    or not isinstance(row['text'],str) or not row['text'] or len(row['text'])>24000):
                raise ValueError('invalid_native_asr_alignment')
            chars+=len(row['text'])
            if group is raw:
                if (type(row['seek_frames']) is not int or not 0<=row['seek_frames']<=math.ceil(duration*100)
                        or not finite(row['padding_end'])
                        or not math.isclose(row['padding_end'],row['seek_frames']/100+30,rel_tol=0,abs_tol=1e-6)
                        or row['end']>row['padding_end']):
                    raise ValueError('invalid_native_asr_alignment')
            elif (row['text']!=rows[index]['text'] or row['start']!=rows[index]['start']
                  or not rows[index]['end']<=row['end']<=rows[index]['end']+.5):
                raise ValueError('invalid_native_asr_alignment')
    if (chars>48000 or len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode())>200000
            or value['text_sequence_equal']!=([r['text'] for r in raw]==[r['text'] for r in aligned])):
        raise ValueError('invalid_native_asr_alignment')
    return value


def verify_model(model_dir):
    model_dir = Path(model_dir).resolve()
    manifest_path = model_dir / 'crowd-model.json'
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 10000:
        raise ValueError('verified_local_model_required')
    manifest = json.loads(manifest_path.read_text())
    name, profile = model_profile(manifest)
    required = set(profile.get('files', FILES)) - {'README.md'}
    if set(manifest.get('sha256', {})) != required:
        raise ValueError('model_manifest_invalid')
    total = 0
    for filename in required:
        path = model_dir / filename
        if not path.is_file() or path.is_symlink() or path.stat().st_size > profile['limit']:
            raise ValueError('model_file_invalid')
        total += path.stat().st_size
        if total > profile['limit']:
            raise ValueError('model_file_invalid')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != manifest['sha256'][filename]:
            raise ValueError('model_hash_mismatch')
    return model_dir, name, profile


def transcribe(source, model_dir, asr_timing_mode='word'):
    if asr_timing_mode not in ('word','segment'):
        raise ValueError('invalid_asr_timing_mode')
    manifest = Path(model_dir) / 'crowd-model.json'
    if manifest.is_file() and not manifest.is_symlink() and manifest.stat().st_size <= 10000:
        if json.loads(manifest.read_text()).get('engine') == 'mlx_whisper_local':
            from mlx_asr import provider, VerifiedSession
            try:
                return VerifiedSession(model_dir, timing_mode='segment')(source) if asr_timing_mode=='segment' else provider(source, model_dir)
            except ValueError:
                raise
            except Exception:
                raise ValueError('mac_native_asr_unavailable') from None
    if asr_timing_mode!='word':
        raise ValueError('segment_timing_requires_mlx_provider')
    # A local path and offline mode prevent implicit Hub fetches or auth access.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
    model_dir, name, profile = verify_model(model_dir)
    from faster_whisper import WhisperModel
    import av
    import numpy as np
    samples = []
    count = 0
    resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
    # Decode at most 60 seconds rather than loading an arbitrarily long compressed file.
    # Custom IO plus no external protocols prevents disguised HLS/concat files
    # from making network requests or reading an unrelated local media reference.
    with Path(source).open('rb') as stream, av.open(stream, options={
            'protocol_whitelist': '', 'format_whitelist': 'wav,mp3,mov,aiff,caf,ogg,matroska,webm,flac',
            'enable_drefs': '0'}) as container:
        if not container.streams.audio:
            raise ValueError('audio_stream_missing')
        for frame in container.decode(audio=0):
            for decoded in resampler.resample(frame):
                value = decoded.to_ndarray().reshape(-1)
                count += value.size
                if count > 60 * 16000:
                    raise ValueError('audio_over_60_seconds')
                samples.append(value)
        for decoded in resampler.resample(None):
            value = decoded.to_ndarray().reshape(-1)
            count += value.size
            if count > 60 * 16000:
                raise ValueError('audio_over_60_seconds')
            samples.append(value)
    if not count:
        raise ValueError('audio_empty')
    audio = np.concatenate(samples).astype(np.float32) / 32768.0
    model = WhisperModel(str(model_dir), device='cpu', compute_type='int8', cpu_threads=2,
                         num_workers=1, local_files_only=True)
    extractor=getattr(model,'feature_extractor',None)
    if getattr(extractor,'time_per_frame',None)!=.01 or getattr(extractor,'nb_max_frames',None)!=3000:
        raise ValueError('native_asr_alignment_unavailable')
    original_split=getattr(model,'_split_segments_by_timestamps',None)
    if not callable(original_split):raise ValueError('native_asr_alignment_unavailable')
    had_split_override='_split_segments_by_timestamps' in vars(model)
    token_candidates=[]
    def observe_split(*args,**kwargs):
        result=original_split(*args,**kwargs)
        tokenizer=kwargs.get('tokenizer') or args[0]
        for item in result[0]:
            text=tokenizer.decode(item['tokens']).strip()
            if text:
                token_candidates.append({'start':float(item['start']),'end':float(item['end']),'text':text,
                    'seek_frames':item['seek'],'padding_end':item['seek']/100+30})
                if len(token_candidates)>1000:raise ValueError('invalid_native_asr_alignment')
        return result
    model._split_segments_by_timestamps=observe_split
    raw_timeline, metrics = [], []
    try:
        segments, _ = model.transcribe(audio, language='zh', beam_size=3, vad_filter=False,
                                       condition_on_previous_text=False,word_timestamps=True)
        for segment in segments:
            value = segment.text.strip()
            if value:
                raw_timeline.append({'start': float(segment.start), 'end': float(segment.end), 'text': value})
                metrics.append({'segment_index': len(metrics), **{
                    field: getattr(segment, field, None) for field in METRIC_FIELDS}})
    finally:
        # Remove the observer cycle so each long-file window can release its model.
        if had_split_override:model._split_segments_by_timestamps=original_split
        else:del model._split_segments_by_timestamps
    timeline, adjustments = normalize_timestamps(raw_timeline, count / 16000)
    alignment=validate_native_alignment({'method':'faster_whisper_word_timestamps',
        'source':'same_native_decode_before_word_alignment','pcm_duration_seconds':count/16000,
        'token_candidates':token_candidates,'aligned_estimates':raw_timeline,
        'text_sequence_equal':[r['text'] for r in token_candidates]==[r['text'] for r in raw_timeline],
        'semantic_status':'not_reviewed'},timeline,count/16000)
    metrics = normalize_metrics(metrics, len(timeline))
    lines = ['[%.2f–%.2f] %s' % (row['start'], row['end'], row['text']) for row in timeline]
    text = '\n'.join(lines)
    if not text.strip():
        error=ValueError('speech_empty');error.native_alignment=alignment
        raise error
    return {'raw_text': text[:24000], 'truncated': len(text) > 24000,
            'processor': 'faster_whisper_local', 'segments': timeline,
            'duration_seconds': count / 16000,
            'model': name, 'model_repository': profile['repository'], 'model_revision': profile['revision'],
            'segment_metrics': metrics, 'quality_diagnostics': quality_diagnostics(timeline, metrics),
            'timing_adjustments': adjustments, 'native_alignment': alignment,
            'timing_policy': 'native_word_alignment_with_retained_token_candidates'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-dir', required=True, type=Path)
    p.add_argument('input', type=Path)
    p.add_argument('--asr-timing-mode', choices=('word','segment'), default='word')
    a = p.parse_args()
    try:
        if not a.input.is_file() or a.input.stat().st_size > 25 * 1024 * 1024:
            raise ValueError('audio_missing_or_over_25mb')
        print(json.dumps(transcribe(a.input, a.model_dir, **({'asr_timing_mode':a.asr_timing_mode} if a.asr_timing_mode!='word' else {})), ensure_ascii=False))
    except Exception as e:
        # External library errors may disclose local paths or model internals.
        p.exit(1, (str(e) if isinstance(e, ValueError) and str(e).replace('_', '').isalnum()
                   else 'local_asr_failed') + '\n')


if __name__ == '__main__':
    main()
