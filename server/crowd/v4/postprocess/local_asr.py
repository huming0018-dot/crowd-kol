#!/usr/bin/env python3
"""Explicit offline ASR. Requires a local CTranslate2 model; never downloads it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def transcribe(source, model_dir):
    # A local path and offline mode prevent implicit Hub fetches or auth access.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
    model_dir = Path(model_dir).resolve()
    manifest_path = model_dir / 'crowd-model.json'
    if not manifest_path.is_file() or manifest_path.stat().st_size > 10000:
        raise ValueError('verified_local_model_required')
    manifest = json.loads(manifest_path.read_text())
    required = {'model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'}
    if set(manifest.get('sha256', {})) != required:
        raise ValueError('model_manifest_invalid')
    for name in required:
        path = model_dir / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 100_000_000:
            raise ValueError('model_file_invalid')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != manifest['sha256'][name]:
            raise ValueError('model_hash_mismatch')
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
    lines = []
    for segment in segments:
        lines.append('[%.2f–%.2f] %s' % (segment.start, segment.end, segment.text.strip()))
    text = '\n'.join(lines)
    if not text.strip():
        raise ValueError('speech_empty')
    return {'raw_text': text[:24000], 'truncated': len(text) > 24000,
            'processor': 'faster_whisper_local'}


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
