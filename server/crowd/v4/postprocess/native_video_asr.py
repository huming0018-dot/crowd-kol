"""Server-bound native MP4 ASR; scope is confined to this separate local process."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

PROFILE='registered_native_mp4_asr_64mib_7200s'
MAX_BYTES=64*1024*1024
MAX_SECONDS=7200

def read_private(path,limit):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('unsafe_native_asr_snapshot')
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(descriptor,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>limit:raise ValueError('unsafe_native_asr_snapshot')
        data=stream.read(limit+1)
    if len(data)>limit:raise ValueError('unsafe_native_asr_snapshot')
    return data

def validate_context(context,source,state=None,data=None):
    fields={'schema_version','processing_profile','run_id','platform','content_id','entity_ref',
            'asset_sha256','source_record_hash','normalized_sha256','audio_duration_ms'}
    if (not isinstance(context,dict) or set(context)!=fields or type(context.get('schema_version')) is not int
            or context['schema_version']!=1 or context.get('processing_profile')!=PROFILE
            or Path(source).suffix.lower()!='.mp4'
            or context.get('platform') not in ('xiaohongshu','douyin','kuaishou','bilibili','weibo','tieba','zhihu')
            or not isinstance(context.get('content_id'),str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',context['content_id'])
            or type(context.get('audio_duration_ms')) is not int or not 1<=context['audio_duration_ms']<=7200000
            or any(not isinstance(context.get(k),str) or not re.fullmatch('[a-f0-9]{64}',context[k]) for k in ('asset_sha256','source_record_hash','normalized_sha256'))):
        raise ValueError('invalid_native_video_asr_context')
    try:valid_id=str(uuid.UUID(context['run_id']))==context['run_id']
    except (ValueError,TypeError,AttributeError):valid_id=False
    ref=context.get('entity_ref');allowed={context['platform']+':content:'+context['content_id']}
    if context['platform']=='bilibili':allowed.add('bilibili:dynamic:'+context['content_id'])
    if context['platform']=='zhihu':allowed={value+':'+kind for value in allowed for kind in ('answer','article','zvideo')}
    if not valid_id or ref not in allowed:raise ValueError('invalid_native_video_asr_context')
    digest=hashlib.sha256(json.dumps(context,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if state is not None and (state.get('kind')!='asr' or state.get('processing_profile')!=PROFILE
            or state.get('native_video_context_sha256')!=digest
            or any(state.get(key)!=context[key] for key in ('run_id','platform','content_id','entity_ref','asset_sha256'))):
        raise ValueError('invalid_native_video_asr_context')
    if data is not None and (len(data)>MAX_BYTES or len(data)<12 or data[4:8]!=b'ftyp' or hashlib.sha256(data).hexdigest()!=context['asset_sha256']):
        raise ValueError('native_video_asr_snapshot_changed')
    return digest

def prepare(source,model_dir,work_dir,context,cancel=None):
    import long_media
    # Validate/hash once, then use an exclusive frozen byte snapshot for metadata-free extraction.
    data=read_private(source,MAX_BYTES);context_hash=validate_context(context,source,data=data)
    work=long_media.safe_work_directory(source,work_dir)
    previous=work/'native-context.json'
    if previous.exists():
        if json.loads(read_private(previous,8192)).get('context_sha256')!=context_hash:raise ValueError('native_video_asr_checkpoint_changed')
    else:long_media.save(previous,{'context_sha256':context_hash})
    old_bytes,old_seconds=long_media.MAX_BYTES,long_media.MAX_SECONDS
    try:
        long_media.MAX_BYTES=MAX_BYTES;long_media.MAX_SECONDS=MAX_SECONDS
        with tempfile.TemporaryDirectory(prefix='crowd-native-asr-') as directory:
            snapshot=Path(directory)/'input.mp4'
            with os.fdopen(os.open(snapshot,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as stream:stream.write(data)
            evidence=long_media.transcribe_long(snapshot,model_dir,work,cancel=cancel)
    finally:long_media.MAX_BYTES=old_bytes;long_media.MAX_SECONDS=old_seconds
    evidence.update(source_kind='authorized_local_file',asset_sha256=context['asset_sha256'],
                    coverage='local_file_all_audio_windows_processed',processing_profile=PROFILE,
                    native_video_context_sha256=context_hash)
    return evidence

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('input','asr-model','work-dir','output','native-video-context'):parser.add_argument('--'+name,required=True,type=Path)
    for name in ('platform','content-id','authorization-ref'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();cancelled=False
    import signal
    def stop(*_):
        nonlocal cancelled
        cancelled=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        if args.input.name!='input.mp4' or args.native_video_context!=args.input.parent/'native-asr-context.json':raise ValueError('invalid_native_video_asr_context')
        context=json.loads(read_private(args.native_video_context,8192));state=json.loads(read_private(args.input.parent/'state.json',200000))
        if state.get('job_id')!=args.input.parent.name or str(uuid.UUID(args.input.parent.name))!=args.input.parent.name:raise ValueError('invalid_native_video_asr_context')
        validate_context(context,args.input,state)
        if context['platform']!=args.platform or context['content_id']!=args.content_id:raise ValueError('invalid_native_video_asr_context')
        evidence=prepare(args.input,args.asr_model,args.work_dir,context,cancel=lambda:cancelled or (args.input.parent/'cancel.requested').exists())
        encoded=json.dumps([{'platform':args.platform,'content_id':args.content_id,'authorization_ref':args.authorization_ref,
                             'kind':'transcript','evidence':evidence}],ensure_ascii=False).encode()
        if len(encoded)>2000000:raise ValueError('long_media_result_over_2mb')
        with os.fdopen(os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as stream:stream.write(encoded)
        return 0
    except (ValueError,OSError,TypeError):return 1

if __name__=='__main__':raise SystemExit(main())
