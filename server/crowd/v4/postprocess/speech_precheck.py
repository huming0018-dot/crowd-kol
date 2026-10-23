"""Optional whole-input Silero observation. No audio removal or implicit downloads."""
import argparse
import hashlib
import importlib.metadata
import json
import math
import re
import os
from pathlib import Path
import subprocess
import time
import wave

PROFILE='silero_whole_input_precheck_v1'
CACHE_SUFFIX='silero-whole-input-precheck-v1'
MODEL_SHA='4cbf549b8326f60f80f2536d9eefeb450a9abe83365a098031c89719f1be17d2'
VAD_SOURCE_SHA='37a9c774aefdd3162d936b896c8dcf5571b2ed938d65bffecfd631770049a18d'
PACKAGES={'faster-whisper':'1.2.1','onnxruntime':'1.19.2','numpy':'2.0.2'}
OPTIONS={'threshold':.5,'neg_threshold':None,'min_speech_duration_ms':0,
         'min_silence_duration_ms':2000,'speech_pad_ms':400}


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):h.update(data)
    return h.hexdigest()


def intervals(value,samples):
    if type(samples) is not int or not 0<samples<=960000 or not isinstance(value,list) or len(value)>512:
        raise ValueError('invalid_speech_precheck_intervals')
    last=0;total=0
    for row in value:
        if (not isinstance(row,dict) or set(row)!={'start','end'}
                or type(row['start']) is not int or type(row['end']) is not int
                or not last<=row['start']<row['end']<=samples):raise ValueError('invalid_speech_precheck_intervals')
        last=row['end'];total+=row['end']-row['start']
    return total


def read_json(path,limit):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:raise ValueError('invalid_speech_precheck_file')
    return json.loads(path.read_text(),parse_constant=lambda _:(_ for _ in ()).throw(ValueError('invalid_speech_precheck_file')))


def validate_manifest(manifest):
    fields={'schema','asset_sha256','duration_seconds','segment_seconds','overlap_seconds','chunks','source_kind','network'}
    if (not isinstance(manifest,dict) or set(manifest)!=fields or type(manifest['schema']) is not int or manifest['schema']!=1
            or not isinstance(manifest['asset_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',manifest['asset_sha256'])
            or type(manifest['duration_seconds']) not in (int,float) or not math.isfinite(manifest['duration_seconds'])
            or not 0<manifest['duration_seconds']<=7200
            or type(manifest['segment_seconds']) is not int or manifest['segment_seconds']!=55
            or type(manifest['overlap_seconds']) is not int or manifest['overlap_seconds']!=2
            or manifest['source_kind']!='authorized_local_file' or manifest['network'] is not False
            or not isinstance(manifest['chunks'],list) or not 1<=len(manifest['chunks'])<=136):
        raise ValueError('invalid_speech_precheck_manifest')
    duration=manifest['duration_seconds'];chunks=manifest['chunks']
    for index,row in enumerate(chunks):
        start=index*53
        if (not isinstance(row,dict) or set(row)!={'index','start','end','file','sha256'}
                or type(row['index']) is not int or row['index']!=index
                or type(row['start']) not in (int,float) or row['start']!=start
                or type(row['end']) not in (int,float) or row['end']!=min(duration,start+55) or not start<row['end']
                or row['file']!='chunk-%04d.wav'%index or not isinstance(row['sha256'],str)
                or not re.fullmatch('[a-f0-9]{64}',row['sha256'])
                or index<len(chunks)-1 and row['end']==duration):
            raise ValueError('invalid_speech_precheck_manifest')
    if chunks[-1]['end']!=duration:raise ValueError('invalid_speech_precheck_manifest')
    return manifest


def validate_report(report,manifest):
    validate_manifest(manifest)
    fields={'profile','state','asset_sha256','model_sha256','vad_source_sha256','packages','options',
            'semantic_status','audio_was_cut','windows'}
    if (not isinstance(report,dict) or set(report)!=fields or report['profile']!=PROFILE
            or report['state']!='completed' or report['asset_sha256']!=manifest['asset_sha256']
            or report['model_sha256']!=MODEL_SHA or report['vad_source_sha256']!=VAD_SOURCE_SHA
            or report['packages']!=PACKAGES or report['options']!=OPTIONS
            or report['semantic_status']!='not_reviewed' or report['audio_was_cut'] is not False
            or not isinstance(report['windows'],list) or len(report['windows'])!=len(manifest['chunks'])):
        raise ValueError('invalid_speech_precheck_report')
    total=0
    for chunk,row in zip(manifest['chunks'],report['windows']):
        samples=round((chunk['end']-chunk['start'])*16000)
        if (not isinstance(row,dict) or set(row)!={'index','pcm_sha256','samples','intervals','speech_samples'}
                or type(row['index']) is not int or row['index']!=chunk['index']
                or row['pcm_sha256']!=chunk['sha256'] or type(row['samples']) is not int or row['samples']!=samples):
            raise ValueError('invalid_speech_precheck_report')
        actual=intervals(row['intervals'],samples)
        if type(row['speech_samples']) is not int or row['speech_samples']!=actual:raise ValueError('invalid_speech_precheck_report')
        total+=actual
    return {'profile':PROFILE,'state':'completed','total_windows':len(manifest['chunks']),
            'processed_windows':len(report['windows']),'speech_samples':total,'has_speech':total>0,
            'model_sha256':MODEL_SHA,'audio_asset_sha256':manifest['asset_sha256'],'semantic_status':'not_reviewed'}


def observe(manifest,work):
    validate_manifest(manifest)
    import numpy as np
    import faster_whisper.vad as vad
    from faster_whisper.utils import get_assets_path
    for name,version in PACKAGES.items():
        if importlib.metadata.version(name)!=version:raise ValueError('speech_precheck_dependencies_changed')
    model=Path(get_assets_path())/'silero_vad_v6.onnx'
    if model.is_symlink() or digest(model)!=MODEL_SHA or digest(vad.__file__)!=VAD_SOURCE_SHA:
        raise ValueError('speech_precheck_dependencies_changed')
    chunks=manifest.get('chunks')
    if not isinstance(chunks,list) or not 1<=len(chunks)<=136:raise ValueError('invalid_speech_precheck_manifest')
    report={'profile':PROFILE,'state':'completed','asset_sha256':manifest['asset_sha256'],
        'model_sha256':MODEL_SHA,'vad_source_sha256':VAD_SOURCE_SHA,'packages':PACKAGES,'options':OPTIONS,
        'semantic_status':'not_reviewed','audio_was_cut':False,'windows':[]}
    for index,chunk in enumerate(chunks):
        if chunk.get('index')!=index or chunk.get('file')!='chunk-%04d.wav'%index:raise ValueError('invalid_speech_precheck_manifest')
        path=work/chunk['file']
        if path.is_symlink() or not path.is_file() or path.stat().st_size>2_000_000 or digest(path)!=chunk['sha256']:
            raise ValueError('speech_precheck_pcm_changed')
        with wave.open(str(path),'rb') as audio:
            if (audio.getnchannels(),audio.getsampwidth(),audio.getframerate())!=(1,2,16000):raise ValueError('speech_precheck_pcm_invalid')
            samples=audio.getnframes()
            if not 0<samples<=960000:raise ValueError('speech_precheck_pcm_invalid')
            data=audio.readframes(samples)
        if len(data)!=samples*2:raise ValueError('speech_precheck_pcm_invalid')
        array=np.frombuffer(data,dtype='<i2').astype(np.float32)/32768.
        rows=vad.get_speech_timestamps(array,vad_options=vad.VadOptions(**OPTIONS),sampling_rate=16000)
        report['windows'].append({'index':index,'pcm_sha256':chunk['sha256'],'samples':samples,
            'intervals':rows,'speech_samples':intervals(rows,samples)})
    validate_report(report,manifest)
    return report


def check(manifest,work,cancel=None):
    import long_media
    work=Path(work);output=work/'speech-check.json'
    if output.exists():
        report=read_json(output,2_000_000)
    else:
        python=os.environ.get('CROWD_SPEECH_CHECK_PYTHON')
        if not python or not Path(python).is_file():raise ValueError('speech_precheck_not_configured')
        long_media.check_cancel(cancel)
        env={**os.environ,'HF_HUB_OFFLINE':'1','HF_HUB_DISABLE_IMPLICIT_TOKEN':'1'}
        process=subprocess.Popen([python,str(Path(__file__).resolve()),'--manifest',str((work/'chunks.json').resolve()),
            '--output',str(output.resolve())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env)
        deadline=time.monotonic()+30+5*len(manifest['chunks'])
        try:
            while process.poll() is None:
                long_media.check_cancel(cancel)
                if time.monotonic()>deadline:raise ValueError('speech_precheck_timeout')
                time.sleep(.1)
            if process.returncode!=0:raise ValueError('speech_precheck_failed')
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        report=read_json(output,2_000_000)
    summary=validate_report(report,manifest)
    summary['diagnostic_sha256']=digest(output)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    try:
        import long_media
        if args.manifest.name!='chunks.json' or args.output!=args.manifest.parent/'speech-check.json':raise ValueError('invalid_speech_precheck_file')
        if any(p.is_symlink() for p in (args.manifest.parent,*args.manifest.parent.parents)):raise ValueError('invalid_speech_precheck_file')
        report=observe(read_json(args.manifest,50000),args.manifest.parent)
        if args.output.exists() or args.output.is_symlink():raise ValueError('invalid_speech_precheck_file')
        long_media.save(args.output,report)
        return 0
    except (ValueError,OSError,ImportError,RuntimeError,KeyError,TypeError):return 1

if __name__=='__main__':raise SystemExit(main())
