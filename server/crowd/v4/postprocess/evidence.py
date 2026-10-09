#!/usr/bin/env python3
"""Prepare explicitly authorized local evidence for import in the KOL controller.
No network, credentials, automatic media downloads, or inference of fan demographics.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def prepare(kind, source, platform, content_id, authorization_ref, runner=subprocess.run, asr_model=None):
    if platform not in ('xiaohongshu', 'bilibili') or not re.fullmatch(
            r'[a-f0-9]{24}' if platform == 'xiaohongshu' else r'BV[A-Za-z0-9]{10}', content_id):
        raise ValueError('invalid_content_identity')
    if not authorization_ref.strip() or len(authorization_ref) > 200:
        raise ValueError('authorization_reference_required')
    source = Path(source)
    if not source.is_file() or source.stat().st_size > 25 * 1024 * 1024:
        raise ValueError('file_missing_or_over_25mb')
    with source.open('rb') as stream:
        data = stream.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise ValueError('file_over_25mb')
    evidence = {'source_kind': 'authorized_local_file', 'asset_sha256': hashlib.sha256(data).hexdigest(),
                'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'coverage': 'local_file_bounded', 'truncated': False}
    if kind == 'ocr':
        if sys.platform != 'darwin':
            raise ValueError('macos_vision_required')
        if source.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.heic', '.tif', '.tiff', '.webp'):
            raise ValueError('image_file_required')
        # Freeze the bytes that were hashed; never OCR a file changing beneath us.
        with tempfile.TemporaryDirectory(prefix='crowd-authorized-ocr-') as directory:
            image = Path(directory) / ('input' + source.suffix.lower())
            image.write_bytes(data)
            native = ROOT / 'crowd-vision'
            command = [str(native), str(image)] if native.is_file() and os.access(native, os.X_OK) else [
                'swift', '-module-cache-path', str(Path(tempfile.gettempdir()) / 'crowd-vision-module-cache'),
                str(ROOT / 'vision.swift'), str(image)]
            result = runner(command, check=True, capture_output=True, timeout=180)
        parsed = json.loads(result.stdout)
        blocks = parsed['blocks']
        if not isinstance(blocks, list) or len(blocks) > 200:
            raise ValueError('invalid_ocr_output')
        raw = '\n'.join(x['text'] for x in blocks)
        evidence.update(blocks=blocks, raw_text=raw[:24000], truncated=bool(parsed['truncated'] or len(raw) > 24000))
    elif kind == 'asr':
        if source.suffix.lower() not in ('.wav', '.m4a', '.mp3', '.caf', '.aiff', '.mp4', '.webm', '.ogg'):
            raise ValueError('audio_file_required')
        native = ROOT / 'crowd-speech'
        if asr_model is None and (sys.platform != 'darwin' or not native.is_file() or not os.access(native, os.X_OK)):
            raise ValueError('packaged_speech_tool_required')
        with tempfile.TemporaryDirectory(prefix='crowd-authorized-speech-') as directory:
            audio = Path(directory) / ('input' + source.suffix.lower())
            audio.write_bytes(data)
            command = [sys.executable, str(ROOT / 'local_asr.py'), '--model-dir', str(Path(asr_model).resolve()), str(audio)] if asr_model else [str(native), str(audio)]
            result = runner(command, check=True, capture_output=True, timeout=150)
        parsed = json.loads(result.stdout)
        if not isinstance(parsed.get('raw_text'), str) or not parsed['raw_text'].strip() or len(parsed['raw_text']) > 24000 or type(parsed.get('truncated')) is not bool:
            raise ValueError('invalid_asr_output')
        evidence.update(raw_text=parsed['raw_text'], truncated=parsed['truncated'], processor='faster_whisper_local' if asr_model else 'apple_speech_ondevice')
    elif kind == 'transcript':
        if source.suffix.lower() not in ('.txt', '.vtt', '.srt'):
            raise ValueError('authorized_txt_vtt_srt_required')
        text = data.decode('utf-8-sig')
        if len(text) > 24000:
            raise ValueError('transcript_over_24000_characters')
        evidence['raw_text'] = text
    elif kind == 'demographics':
        value = json.loads(data)
        required = {'population', 'dimension', 'sample_size', 'coverage_period', 'aggregate_values'}
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError('aggregate_fields_only_no_individual_rows')
        for key in ('population', 'dimension', 'coverage_period'):
            if not isinstance(value[key], str) or not 1 <= len(value[key]) <= 200:
                raise ValueError('aggregate_metadata_required')
        if type(value['sample_size']) is not int or not 0 <= value['sample_size'] <= 2147483647:
            raise ValueError('invalid_sample_size')
        values = value['aggregate_values']
        if not isinstance(values, dict) or not 1 <= len(values) <= 100 or any(
                not isinstance(k, str) or not 1 <= len(k) <= 100 or type(v) not in (int, float)
                or not math.isfinite(v) or v < 0 for k, v in values.items()):
            raise ValueError('invalid_aggregate_values')
        evidence.update(value)
    else:
        raise ValueError('unsupported_evidence_kind')
    return {'platform': platform, 'content_id': content_id, 'authorization_ref': authorization_ref.strip(),
            'kind': 'transcript' if kind == 'asr' else kind, 'evidence': evidence}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('ocr', 'transcript', 'demographics', 'asr'), required=True)
    parser.add_argument('--input', type=Path, nargs='+', required=True)
    parser.add_argument('--platform', choices=('xiaohongshu', 'bilibili'), required=True)
    parser.add_argument('--content-id', required=True)
    parser.add_argument('--authorization-ref', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--asr-model', type=Path, help='Explicit verified local Faster Whisper model; no automatic download')
    args = parser.parse_args()
    if not 1 <= len(args.input) <= (2 if args.kind == 'ocr' else 1):
        parser.error('最多2张图片，其他类型每次1份文件')
    try:
        output = [prepare(args.kind, path, args.platform, args.content_id, args.authorization_ref, asr_model=args.asr_model) for path in args.input]
        encoded = json.dumps(output, ensure_ascii=False, indent=2).encode('utf-8')
        if len(encoded) > 200000:
            raise ValueError('evidence_over_200kb')
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
        print(json.dumps({'prepared': len(output), 'kind': args.kind, 'uploaded': False,
                          'authorization': 'user_declared_not_independently_verified'}))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        # Native tool stderr may contain a local file path; keep failures categorical.
        parser.exit(1, '准备失败：' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__) + '\n')


if __name__ == '__main__':
    main()
