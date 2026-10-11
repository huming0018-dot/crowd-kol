#!/usr/bin/env python3
"""Explicit offline ASR. Requires a local CTranslate2 model; never downloads it."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
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
    return {**diagnostic_summary(entries, len(rows)), 'time_basis': 'local_file_seconds'}


def normalize_timestamps(rows, duration):
    """Allow only a small provider tail overrun; retain the original estimate."""
    timeline, adjustments = [], []
    for row in rows:
        start, end, text = row['start'], row['end'], row['text']
        if (not math.isfinite(start) or not math.isfinite(end)
                or not 0 <= start <= end or start >= duration or end > duration + 0.5):
            raise ValueError('asr_provider_timestamp_out_of_bounds')
        if end > duration:
            adjustments.append({'segment_index': len(timeline), 'provider_start': start,
                                'provider_end': end, 'adjusted_end': duration,
                                'reason': 'provider_tail_overrun', 'text': text})
        timeline.append({'start': start, 'end': min(end, duration), 'text': text})
    return timeline, adjustments


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


def transcribe(source, model_dir):
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
    segments, _ = model.transcribe(audio, language='zh', beam_size=3, vad_filter=False,
                                   condition_on_previous_text=False)
    raw_timeline, metrics = [], []
    for segment in segments:
        value = segment.text.strip()
        if value:
            raw_timeline.append({'start': float(segment.start), 'end': float(segment.end), 'text': value})
            metrics.append({'segment_index': len(metrics), **{
                field: getattr(segment, field, None) for field in METRIC_FIELDS}})
    timeline, adjustments = normalize_timestamps(raw_timeline, count / 16000)
    metrics = normalize_metrics(metrics, len(timeline))
    lines = ['[%.2f–%.2f] %s' % (row['start'], row['end'], row['text']) for row in timeline]
    text = '\n'.join(lines)
    if not text.strip():
        raise ValueError('speech_empty')
    return {'raw_text': text[:24000], 'truncated': len(text) > 24000,
            'processor': 'faster_whisper_local', 'segments': timeline,
            'duration_seconds': count / 16000,
            'model': name, 'model_repository': profile['repository'], 'model_revision': profile['revision'],
            'segment_metrics': metrics, 'quality_diagnostics': quality_diagnostics(timeline, metrics),
            'timing_adjustments': adjustments, 'timing_policy': 'tail_overrun_at_most_0.5s'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-dir', required=True, type=Path)
    p.add_argument('input', type=Path)
    a = p.parse_args()
    try:
        if not a.input.is_file() or a.input.stat().st_size > 25 * 1024 * 1024:
            raise ValueError('audio_missing_or_over_25mb')
        print(json.dumps(transcribe(a.input, a.model_dir), ensure_ascii=False))
    except Exception as e:
        # External library errors may disclose local paths or model internals.
        p.exit(1, (str(e) if isinstance(e, ValueError) and str(e).replace('_', '').isalnum()
                   else 'local_asr_failed') + '\n')


if __name__ == '__main__':
    main()
