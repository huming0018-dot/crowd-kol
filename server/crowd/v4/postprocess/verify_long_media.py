#!/usr/bin/env python3
"""Reproducible self-generated 70s video extraction/merge evidence; no real ASR."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

import long_media as lm
from test_long_media import audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    root = args.output_dir
    root.mkdir(parents=True, exist_ok=True)
    executable = lm.ffmpeg_path()
    if executable is None:
        raise ValueError('explicit_full_ffmpeg_required')
    wav = root / 'self-generated-70s.wav'
    video = root / 'self-generated-70s.mp4'
    if not video.exists():
        audio(wav)
        subprocess.run([executable, '-nostdin', '-loglevel', 'error', '-y',
                        '-f', 'lavfi', '-i', 'color=c=black:s=32x32:r=1', '-i', str(wav),
                        '-t', '70', '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(video)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    original_hash = lm.digest(video)
    manifest = lm.prepare_chunks(video, root / 'prepared')
    assert manifest['duration_seconds'] > 60 and len(manifest['chunks']) == 2
    rows = [{'segments': [{'start': 0, 'end': 1, 'text': '合成开头'},
                          {'start': 53, 'end': 55, 'text': '重叠测试句'}]},
            {'segments': [{'start': 0, 'end': 2, 'text': '重叠测试句。'},
                          {'start': 3, 'end': 5, 'text': '合成结尾'}]}]
    merged = lm.merge_chunks(manifest, rows)
    assert merged['deduplicated_overlap_segments'] == 1
    assert merged['segments'][-1]['start'] == 56
    assert lm.merge_chunks(manifest, rows) == merged
    # Each verification must exercise cancellation, even when run a second time.
    # Older receipts and chunk results remain available for comparison.
    checkpoint_dir = root / ('cancel-resume-' + uuid.uuid4().hex)
    cancelled = False
    calls = []

    def provider(path):
        nonlocal cancelled
        index = int(path.stem.split('-')[1])
        calls.append(index)
        cancelled = index == 0
        return {**rows[index], 'truncated': False}

    if not (checkpoint_dir / 'result-0000.json').is_file():
        try:
            lm.transcribe_long(video, None, checkpoint_dir, lambda: cancelled, provider)
        except ValueError as error:
            assert str(error) == 'long_media_cancelled'
    cancel_state = json.loads((checkpoint_dir / 'state.json').read_text())
    calls_before_resume = list(calls)
    cancelled = False
    resumed = lm.transcribe_long(video, None, checkpoint_dir, transcriber=provider)
    assert resumed['deduplicated_overlap_segments'] == 1
    cached = lm.transcribe_long(video, None, checkpoint_dir,
                                transcriber=lambda _: (_ for _ in ()).throw(AssertionError('cached chunk must not invoke provider')))
    assert cached == resumed
    assert lm.digest(video) == original_hash
    try:
        lm.transcribe_long(video, None, root / 'missing-model')
    except ValueError as error:
        assert str(error) == 'local_asr_model_not_configured'
    model_state = json.loads((root / 'missing-model/state.json').read_text())['state']
    version = subprocess.run([executable, '-version'], check=True, capture_output=True, text=True).stdout.splitlines()[0]
    output = {'schema': 'crowd_long_media_self_generated_evidence_v1', 'source_kind': 'self_generated_tone_video',
              'source_sha256': original_hash, 'source_bytes': video.stat().st_size,
              'duration_seconds': manifest['duration_seconds'], 'chunks': manifest['chunks'],
              'ffmpeg_version': version, 'ffmpeg_sha256': lm.digest(executable),
              'merge': merged, 'cancel_checkpoint': cancel_state,
              'checkpoint_directory': checkpoint_dir.name,
              'calls_before_resume': calls_before_resume, 'offline_injected_provider_calls': calls,
              'cached_repeat_identical': True, 'source_unchanged': True,
              'local_model_state': model_state, 'actual_model_inference': False,
              'model_downloads': 0, 'source_requests': 0, 'external_material_transfers': 0,
              'code_sha256': {name: lm.digest(Path(__file__).parent / name)
                              for name in ('long_media.py', 'local_asr.py', 'evidence.py', 'verify_long_media.py')}}
    lm.save(root / 'evidence.json', output)
    print(json.dumps({'ok': True, 'seconds': manifest['duration_seconds'], 'chunks': len(manifest['chunks']),
                      'deduplicated': merged['deduplicated_overlap_segments'], 'actual_model_inference': False}))


if __name__ == '__main__':
    main()
