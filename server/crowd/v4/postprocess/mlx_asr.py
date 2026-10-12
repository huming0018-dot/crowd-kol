#!/usr/bin/env python3
"""Opt-in offline MLX Whisper provider. No Hub names or implicit downloads."""
import hashlib
import json
import os
from pathlib import Path
import wave


def verify_model(model_dir):
    model = Path(model_dir).resolve()
    manifest = model / 'crowd-model.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 10000:
        raise ValueError('verified_local_mlx_model_required')
    value = json.loads(manifest.read_text())
    if (not isinstance(value,dict) or value.get('engine') != 'mlx_whisper_local' or value.get('package_version') != '0.4.3' or value.get('mlx_version') != '0.32.3'
            or value.get('repository') != 'mlx-community/whisper-large-v3-turbo'
            or value.get('revision') != 'a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb'
            or set(value.get('sha256', {})) != {'config.json', 'weights.safetensors'}
            or value['sha256']['config.json'] != 'b34fc29e4e11e0a25e812775dd67f4dd16fc2c8eb43d28ae25ff7d660ecb6379'
            or value.get('precision') != 'fp16'
            or value['sha256']['weights.safetensors'] != '951ed3fc1203e6a62467abb2144a96ce7eafca8fa77e3704fdb8635ff3e7f8a6'):
        raise ValueError('mlx_model_manifest_invalid')
    for filename, expected in value['sha256'].items():
        path = model / filename
        limit = 10000 if filename == 'config.json' else 1_700_000_000
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > limit:
            raise ValueError('mlx_model_file_invalid')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError('mlx_model_hash_mismatch')
    # Prevent upstream preference for an unverified alternate filename.
    if any((model / name).exists() or (model / name).is_symlink()
           for name in ('model.safetensors', 'weights.npz')):
        raise ValueError('mlx_model_unverified_alternate')
    return model, value


def transcribe(source, model_dir):
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
    model, manifest = verify_model(model_dir)
    import importlib.metadata
    if (importlib.metadata.version('mlx-whisper') != manifest['package_version']
            or importlib.metadata.version('mlx') != manifest['mlx_version']):
        raise ValueError('mlx_package_version_changed')
    import numpy as np
    import mlx.core as mx
    import mlx_whisper
    # Caller supplies already bounded PCM windows; do not execute ffmpeg/protocols.
    with wave.open(str(source), 'rb') as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
            raise ValueError('mlx_pcm16_mono_16khz_required')
        count = stream.getnframes()
        if not 0 < count <= 60 * 16000:
            raise ValueError('mlx_audio_empty_or_over_60_seconds')
        data = stream.readframes(count)
        if len(data) != count * 2:
            raise ValueError('mlx_audio_truncated')
    audio = np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0
    result = mlx_whisper.transcribe(audio, path_or_hf_repo=str(model), language='zh',
        word_timestamps=True, condition_on_previous_text=False, temperature=0.0, verbose=None)
    mx.synchronize()
    return {'engine': 'mlx_whisper_local', 'model_repository': manifest['repository'],
            'model_revision': manifest['revision'], 'package_version': manifest['package_version'],
            'decoding': 'greedy_temperature_zero', 'duration_seconds': count / 16000,
            'result': result, 'quality_review_status': 'not_reviewed'}


def validate_alignment(value, rows, duration):
    import math
    fields={'method','source','pcm_duration_seconds','aligned_estimates','word_estimates','semantic_status'}
    if (not isinstance(value,dict) or set(value)!=fields
            or value['method']!='mlx_whisper_word_timestamps'
            or value['source']!='mlx_native_output_with_word_timestamps'
            or value['semantic_status']!='not_reviewed'
            or type(value['pcm_duration_seconds']) not in (int,float)
            or not math.isclose(value['pcm_duration_seconds'],duration,rel_tol=0,abs_tol=1e-6)
            or value['aligned_estimates']!=rows or not isinstance(value['word_estimates'],list)
            or len(value['word_estimates'])!=len(rows)):
        raise ValueError('invalid_native_asr_alignment')
    total=0
    for index,group in enumerate(value['word_estimates']):
        if (not isinstance(group,dict) or set(group)!={'segment_index','words'}
                or group['segment_index']!=index or type(group['segment_index']) is not int
                or not isinstance(group['words'],list) or not 1<=len(group['words'])<=1000):
            raise ValueError('invalid_native_asr_alignment')
        total+=len(group['words'])
        for word in group['words']:
            if (not isinstance(word,dict) or set(word)!={'start','end','text'}
                    or any(type(word[k]) not in (int,float) or not math.isfinite(word[k]) for k in ('start','end'))
                    or not 0<=word['start']<=word['end']<=duration+.5
                    or not isinstance(word['text'],str) or not 1<=len(word['text'])<=1000):
                raise ValueError('invalid_native_asr_alignment')
        if ''.join(w['text'] for w in group['words']).strip()!=rows[index]['text']:
            raise ValueError('invalid_native_asr_alignment')
    if total>10000 or len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode())>200000:
        raise ValueError('invalid_native_asr_alignment')
    return value


def provider(source, model_dir):
    import local_asr
    native=transcribe(source,model_dir);raw=native['result'];duration=native['duration_seconds']
    segments=raw.get('segments')
    if not isinstance(segments,list) or len(segments)>1000:
        raise ValueError('invalid_mlx_output')
    rows=[];metrics=[];words=[]
    for segment in segments:
        text=segment['text'].strip()
        if not text:continue
        rows.append({'start':float(segment['start']),'end':float(segment['end']),'text':text})
        metrics.append({'segment_index':len(metrics),**{f:segment.get(f) for f in local_asr.METRIC_FIELDS}})
        words.append({'segment_index':len(words),'words':[{'start':float(w['start']),'end':float(w['end']),'text':w['word']} for w in segment.get('words',[])]})
    rows,adjustments=local_asr.normalize_timestamps(rows,duration)
    alignment=validate_alignment({'method':'mlx_whisper_word_timestamps','source':'mlx_native_output_with_word_timestamps',
        'pcm_duration_seconds':duration,'aligned_estimates':rows,'word_estimates':words,'semantic_status':'not_reviewed'},rows,duration)
    metrics=local_asr.normalize_metrics(metrics,len(rows))
    if not rows:
        error=ValueError('speech_empty');error.native_alignment=alignment;raise error
    text='\n'.join('[%.2f–%.2f] %s'%(r['start'],r['end'],r['text']) for r in rows)
    return {'processor':'mlx_whisper_local','raw_text':text[:24000],'truncated':len(text)>24000,
        'segments':rows,'duration_seconds':duration,'model':'whisper-large-v3-turbo-fp16',
        'model_repository':native['model_repository'],'model_revision':native['model_revision'],
        'package_version':native['package_version'],'decoding':native['decoding'],
        'segment_metrics':metrics,'quality_diagnostics':local_asr.quality_diagnostics(rows,metrics),
        'native_alignment':alignment,'timing_adjustments':adjustments,
        'timing_policy':'mlx_native_word_timestamps_no_pre_alignment_token_receipt'}
