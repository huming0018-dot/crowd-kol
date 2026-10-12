#!/usr/bin/env python3
"""Opt-in offline MLX Whisper provider. No Hub names or implicit downloads."""
import hashlib
import json
import os
import stat
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
    return _transcribe_verified(source, model, manifest)


def _transcribe_verified(source, model, manifest, timing_mode='word'):
    if timing_mode not in ('word','segment'):
        raise ValueError('invalid_mlx_timing_mode')
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
        word_timestamps=timing_mode=='word', condition_on_previous_text=False, temperature=0.0, verbose=None)
    mx.synchronize()
    return {'engine': 'mlx_whisper_local', 'model_repository': manifest['repository'],
            'model_revision': manifest['revision'], 'package_version': manifest['package_version'],
            'decoding': 'greedy_temperature_zero', 'duration_seconds': count / 16000,
            'result': result, 'timing_mode': timing_mode, 'quality_review_status': 'not_reviewed'}


def validate_alignment(value, rows, duration):
    import math
    if isinstance(value,dict) and value.get('method')=='mlx_whisper_decoder_timestamps':
        return _validate_decoder_timestamps(value,rows,duration)
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
    return _provider_result(transcribe(source, model_dir))


def _provider_result(native):
    import local_asr
    raw=native['result'];duration=native['duration_seconds']
    segments=raw.get('segments')
    if not isinstance(segments,list) or len(segments)>1000:
        raise ValueError('invalid_mlx_output')
    rows=[];metrics=[];words=[];tokens=[]
    mode=native.get('timing_mode','word')
    if mode not in ('word','segment'):
        raise ValueError('invalid_mlx_timing_mode')
    for segment in segments:
        text=segment['text'].strip()
        if not text:continue
        rows.append({'start':float(segment['start']),'end':float(segment['end']),'text':text})
        metrics.append({'segment_index':len(metrics),**{f:segment.get(f) for f in local_asr.METRIC_FIELDS}})
        if mode=='word':
            words.append({'segment_index':len(words),'words':[{'start':float(w['start']),'end':float(w['end']),'text':w['word']} for w in segment.get('words',[])]})
        else:
            seek=segment.get('seek')
            if type(seek) is not int:
                raise ValueError('invalid_native_asr_alignment')
            tokens.append({**rows[-1],'seek_frames':seek,'padding_end':seek/100+30})
    rows,adjustments=local_asr.normalize_timestamps(rows,duration,
        provider_padding_ends=[row['padding_end'] for row in tokens] if mode=='segment' else None)
    if mode=='word':
        alignment=validate_alignment({'method':'mlx_whisper_word_timestamps','source':'mlx_native_output_with_word_timestamps',
            'pcm_duration_seconds':duration,'aligned_estimates':rows,'word_estimates':words,'semantic_status':'not_reviewed'},rows,duration)
    else:
        alignment=validate_alignment({'method':'mlx_whisper_decoder_timestamps','source':'mlx_native_decode_without_word_alignment',
            'pcm_duration_seconds':duration,'token_estimates':tokens,'normalized_segments':rows,'semantic_status':'not_reviewed'},rows,duration)
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
        'timing_policy':'mlx_decoder_segment_timestamps_with_retained_padding' if mode=='segment' else 'mlx_native_word_timestamps_no_pre_alignment_token_receipt'}



def _model_fingerprint(model):
    fingerprint=[]
    for name in ('crowd-model.json','config.json','weights.safetensors'):
        path=model/name
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(descriptor,'rb') as stream:
            info=os.fstat(stream.fileno())
            limit=1_700_000_000 if name=='weights.safetensors' else 10000
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>limit:
                raise ValueError('mlx_model_file_invalid')
            small_hash=None if name=='weights.safetensors' else hashlib.sha256(stream.read(10001)).hexdigest()
            fingerprint.append((name,info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns,small_hash))
    if any((model/name).exists() or (model/name).is_symlink() for name in ('model.safetensors','weights.npz')):
        raise ValueError('mlx_model_unverified_alternate')
    return tuple(fingerprint)


class VerifiedSession:
    """One job, lazy verified weights; upstream ModelHolder already caches the model."""
    def __init__(self, model_dir, timing_mode='word'):
        if timing_mode not in ('word','segment'):
            raise ValueError('invalid_mlx_timing_mode')
        self.timing_mode=timing_mode
        self.model_dir=Path(model_dir).resolve()
        self.verified=None
        self.fingerprint=None

    def __call__(self, source):
        os.environ['HF_HUB_OFFLINE']='1'
        os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
        if self.verified is None:
            before=_model_fingerprint(self.model_dir)
            self.verified=verify_model(self.model_dir)
            self.fingerprint=_model_fingerprint(self.model_dir)
            if before!=self.fingerprint:
                self.verified=None
                raise ValueError('mlx_model_changed_during_job')
        elif _model_fingerprint(self.model_dir)!=self.fingerprint:
            raise ValueError('mlx_model_changed_during_job')
        try:
            native=_transcribe_verified(source,*self.verified,timing_mode=self.timing_mode)
        except ValueError:
            raise
        except Exception:
            raise ValueError('mac_native_asr_unavailable') from None
        if _model_fingerprint(self.model_dir)!=self.fingerprint:
            raise ValueError('mlx_model_changed_during_job')
        return _provider_result(native)



def _validate_decoder_timestamps(value, rows, duration):
    import math
    fields={'method','source','pcm_duration_seconds','token_estimates','normalized_segments','semantic_status'}
    def finite(number):
        try:return type(number) in (int,float) and math.isfinite(number)
        except OverflowError:return False
    if (set(value)!=fields or value['source']!='mlx_native_decode_without_word_alignment'
            or value['semantic_status']!='not_reviewed' or not finite(value['pcm_duration_seconds'])
            or not math.isclose(value['pcm_duration_seconds'],duration,rel_tol=0,abs_tol=1e-6)
            or value['normalized_segments']!=rows or not isinstance(value['token_estimates'],list)
            or len(value['token_estimates'])!=len(rows) or len(rows)>1000):
        raise ValueError('invalid_native_asr_alignment')
    for raw,row in zip(value['token_estimates'],rows):
        if (not isinstance(raw,dict) or set(raw)!={'start','end','text','seek_frames','padding_end'}
                or any(not finite(raw[k]) for k in ('start','end','padding_end'))
                or type(raw['seek_frames']) is not int or not 0<=raw['seek_frames']<=math.ceil(duration*100)
                or not math.isclose(raw['padding_end'],raw['seek_frames']/100+30,rel_tol=0,abs_tol=1e-6)
                or not 0<=raw['start']<=raw['end']<=raw['padding_end']
                or not isinstance(raw['text'],str) or raw['text']!=row['text']
                or raw['start']!=row['start'] or min(raw['end'],duration)!=row['end']
                or (raw['end']>duration+.5 and not (duration<raw['padding_end']<=duration+30 and raw['end']<duration+1))):
            raise ValueError('invalid_native_asr_alignment')
    if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode())>200000:
        raise ValueError('invalid_native_asr_alignment')
    return value
