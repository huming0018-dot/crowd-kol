"""Cloud-save an existing MP4 by exact run, typed content and asset identity."""
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import uuid

from analysis_artifact import _read,_safe_ancestors
from cloud_sync import canonical
from complete_video import read_bytes
from mc_runner import PLATFORMS,FINAL,canonical as record_canonical,read
from media_cloud import LIMIT,_job_id,_job_lock,_publish_prepared,download_media_video,media_video_cloud_status

HEX=re.compile(r'[a-f0-9]{64}')
CID=re.compile(r'[A-Za-z0-9_.:-]{1,200}')

def _identity(run_folder,content_id,asset_sha256,entity_ref,*,native_asr=False):
    if type(native_asr) is not bool:raise ValueError('media_native_identity_invalid')
    run_folder=Path(run_folder);_safe_ancestors(run_folder);run_id=_job_id(run_folder.name)
    if not isinstance(content_id,str) or not CID.fullmatch(content_id) or not isinstance(asset_sha256,str) or not HEX.fullmatch(asset_sha256):raise ValueError('media_native_identity_invalid')
    manifest,_=_read(run_folder/'manifest.json',200000);status,_=_read(run_folder/'status.json',200000)
    p=manifest.get('request',{}).get('platform');platform=PLATFORMS.get(p)
    if platform is None or manifest.get('run_id')!=run_id or status.get('run_id')!=run_id or status.get('state') not in FINAL:raise ValueError('media_native_not_terminal')
    normalized,normalized_sha=_read(run_folder/'normalized.json',32*1024*1024)
    if normalized.get('run_id')!=run_id or normalized.get('source_kind')!='mediacrawler_api' or normalized.get('reward_eligible') is not False:raise ValueError('media_native_identity_invalid')
    bodies=[r for r in normalized.get('records',[]) if isinstance(r,dict) and r.get('platform')==platform and r.get('content_id')==content_id and r.get('kind') in ('content','dynamic')]
    identities={}
    for row in bodies:
        kind=row['kind'];ctype=row.get('content_type') if platform=='zhihu' else None
        if platform=='zhihu' and (kind!='content' or ctype not in ('answer','article','zvideo')):raise ValueError('media_native_source_ambiguous')
        ref=platform+':'+kind+':'+content_id+(':'+ctype if ctype else '')
        identities.setdefault(ref,[]).append(row)
    if entity_ref is None:
        if len(identities)!=1 or platform=='zhihu':raise ValueError('media_native_source_ambiguous')
        entity_ref=next(iter(identities))
    if not isinstance(entity_ref,str) or entity_ref not in identities:raise ValueError('media_native_source_ambiguous')
    chosen=identities[entity_ref]
    if len({canonical(r) for r in chosen})!=1:raise ValueError('media_native_source_ambiguous')
    body=chosen[0];origin=body.get('origin',{});file_sha=origin.get('file_sha256')
    if body['kind']=='dynamic' and platform!='bilibili':raise ValueError('media_native_identity_invalid')
    if body.get('record_hash')!=hashlib.sha256(record_canonical({k:v for k,v in body.items() if k not in ('record_hash','discovery_kind')}).encode()).hexdigest():raise ValueError('media_native_identity_invalid')
    if origin.get('run_id')!=run_id or not isinstance(file_sha,str) or not HEX.fullmatch(file_sha):raise ValueError('media_native_identity_invalid')
    sources=[r for r in normalized.get('files',[]) if isinstance(r,dict) and r.get('sha256')==file_sha]
    if len(sources)!=1:raise ValueError('media_native_source_ambiguous')
    source_path=_relative(run_folder,sources[0].get('path'))
    if source_path.suffix!='.jsonl' or hashlib.sha256(read_bytes(source_path,50*1024*1024)).hexdigest()!=file_sha:raise ValueError('media_native_asset_changed')
    media=[r for r in normalized.get('media',[]) if isinstance(r,dict) and r.get('platform')==platform and r.get('content_id')==content_id and r.get('sha256')==asset_sha256]
    if len(media)!=1:raise ValueError('media_native_source_ambiguous')
    item=media[0];ctype=body.get('content_type') if platform=='zhihu' else None
    if item.get('source_kind')!='mediacrawler_api' or item.get('reward_eligible') is not False or item.get('content_identity_status')!='reported_directory_id' or item.get('kind')=='audio':raise ValueError('media_native_identity_invalid')
    if platform=='zhihu' and item.get('source_content_type')!=ctype or platform!='zhihu' and len(identities)!=1:raise ValueError('media_native_source_ambiguous')
    directory_id=content_id
    if platform=='bilibili' and item.get('content_identity_basis')=='same_native_bilibili_view':
        from native_media_scope import bilibili_identity_map
        pairs,identity_sha=bilibili_identity_map(run_folder/'output',run_id,[body],read)
        pair=pairs.get(item.get('source_media_id'))
        if not pair or pair['aid']!=content_id or pair['cid']!=item.get('bilibili_view_cid') or identity_sha!=item.get('bilibili_media_identity_sha256'):raise ValueError('media_native_source_ambiguous')
        directory_id=pair['bvid']
    path=_relative(run_folder,item.get('path'));parts=path.relative_to(run_folder).parts
    from native_media_scope import temporary_media_path
    if temporary_media_path(parts):raise ValueError('media_native_uncommitted_asset')
    if len(parts)<5 or parts[0]!='output' or parts[1] not in (p,platform) or parts[2]!='media' or parts[3]!=directory_id or path.suffix.lower()!='.mp4':raise ValueError('media_native_identity_invalid')
    if platform=='zhihu' and (len(parts)<6 or parts[4]!=ctype):raise ValueError('media_native_source_ambiguous')
    data=read_bytes(path,64*1024*1024 if native_asr else LIMIT)
    if type(item.get('bytes')) is not int or len(data)!=item['bytes'] or len(data)<12 or data[4:8]!=b'ftyp' or hashlib.sha256(data).hexdigest()!=asset_sha256:raise ValueError('media_native_asset_changed')
    identity={'local_run_id':run_id,'platform':platform,'content_id':content_id,'entity_ref':entity_ref,'asset_sha256':asset_sha256}
    reference_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'crowd-native-video-v2:'+canonical(identity)))
    return reference_id,identity,body,item,normalized_sha,data

def _relative(folder,value):
    if not isinstance(value,str) or '\\' in value:raise ValueError('media_native_identity_invalid')
    parts=PurePosixPath(value)
    if parts.is_absolute() or any(x in ('.','..') for x in value.split('/')):raise ValueError('media_native_identity_invalid')
    path=folder/parts;_safe_ancestors(path)
    return path

def _duration(data,*,require_audio=False):
    ffmpeg=os.environ.get('CROWD_FFMPEG') or shutil.which('ffmpeg')
    if not ffmpeg:raise ValueError('media_native_ffmpeg_unavailable')
    with tempfile.TemporaryDirectory(prefix='crowd-native-video-') as directory:
        path=Path(directory)/'input.mp4'
        with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as stream:stream.write(data)
        try:result=subprocess.run([ffmpeg,'-hide_banner','-protocol_whitelist','file,pipe','-f','mov','-i',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=15)
        except (OSError,subprocess.TimeoutExpired):raise ValueError('media_native_metadata_unavailable') from None
    text=result.stderr.decode('utf-8','replace');match=re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)',text)
    if not match or not re.search(r'Stream #[^\n]*: Video:',text):raise ValueError('media_native_video_track_missing')
    if require_audio and not re.search(r'Stream #[^\n]*: Audio:',text):raise ValueError('media_native_audio_track_missing')
    duration=int(match[1])*3600+int(match[2])*60+float(match[3])
    if not math.isfinite(duration) or not 1<=round(duration*1000)<=7200000:raise ValueError('media_native_duration_invalid')
    return round(duration*1000)

def prepare_native_video(jobs,client,run_folder,content_id,asset_sha256,entity_ref=None,binding=None):
    if client is None or getattr(client,'role',None) not in ('owner','worker'):raise ValueError('principal_denied')
    ref,identity,body,item,normalized_sha,data=_identity(run_folder,content_id,asset_sha256,entity_ref)
    duration=_duration(data);local=identity['local_run_id']
    if client.role=='worker':
        if not isinstance(binding,dict) or set(binding)!={'task_id','child_id','run_id','lease_epoch','local_run_id','capture_id','envelope_hash'} or binding.get('local_run_id')!=local:raise ValueError('media_cloud_identity_mismatch')
        if not isinstance(binding.get('envelope_hash'),str) or not HEX.fullmatch(binding['envelope_hash']):raise ValueError('media_cloud_identity_mismatch')
        for key in ('task_id','child_id','run_id','capture_id'):_job_id(binding[key])
        task,child,run,epoch=(binding[k] for k in ('task_id','child_id','run_id','lease_epoch'));receipt=binding
    else:
        matches={(t['task_id'],c['child_id'],a['run_id'],a['lease_epoch']) for t in client.call('task_list').get('tasks',[]) for c in t.get('children',[]) for a in c.get('attempts',[]) if a.get('local_run_id')==local}
        if len(matches)!=1:raise ValueError('media_cloud_source_ambiguous')
        task,child,run,epoch=matches.pop();sources=[]
        for value in client.call('results',{'task_id':task}).get('items',[]):
            row=value.get('record',{});r=value.get('receipt',{})
            if row.get('kind')!=body['kind'] or row.get('platform')!=identity['platform'] or row.get('content_id')!=content_id or row.get('origin',{}).get('run_id')!=local:continue
            if identity['platform']=='zhihu' and row.get('content_type')!=body['content_type']:continue
            expected={'task_id':task,'child_id':child,'run_id':run,'lease_epoch':epoch,'status':'received','reward_eligible':False}
            if row.get('origin',{}).get('file_sha256')!=body['origin']['file_sha256'] or row.get('record_hash')!=body['record_hash'] or any(canonical(r.get(k))!=canonical(v) for k,v in expected.items()):raise ValueError('media_cloud_identity_mismatch')
            sources.append(r)
        if len(sources)!=1:raise ValueError('media_cloud_source_ambiguous')
        receipt=sources[0]
    if type(epoch) is not int or not 1<=epoch<=2147483647:raise ValueError('media_cloud_identity_mismatch')
    payload={'idempotency_key':'native:'+ref,'task_id':task,'child_id':child,'run_id':run,'lease_epoch':epoch,'local_run_id':local,'local_job_id':ref,'platform':identity['platform'],'content_id':content_id,'capture_id':receipt['capture_id'],'envelope_hash':receipt['envelope_hash'],'asset_sha256':asset_sha256,'asset_bytes':len(data),'duration_ms':duration,'source_duration_ms':duration,'source_asset_sha256':asset_sha256,'source_file_sha256':body['origin']['file_sha256'],'source_reference_sha256':hashlib.sha256(canonical({**identity,'media_path':item['path'],'source_file_sha256':body['origin']['file_sha256']}).encode()).hexdigest(),'result_file_sha256':normalized_sha,'manifest_version':2,'representation':'native_collected','completeness':'saved_asset_not_full_length_verified','content_kind':body['kind'],'content_type':body.get('content_type') if identity['platform']=='zhihu' else None,'entity_ref':identity['entity_ref'],'container':'mp4','video_track_present':True}
    payload['source_record_hash']=body['record_hash']
    return payload,data

def publish_native_video(jobs,client,run_folder,content_id,asset_sha256,entity_ref=None,opener=None,binding=None):
    payload,data=prepare_native_video(jobs,client,run_folder,content_id,asset_sha256,entity_ref,binding)
    with _job_lock(jobs,payload['local_job_id']):return _publish_prepared(jobs,client,payload,data,opener)

def native_video_cloud_status(jobs,client,run_folder,content_id,asset_sha256,entity_ref=None):
    reference_id=_identity(run_folder,content_id,asset_sha256,entity_ref)[0]
    return {'reference_id':reference_id,**media_video_cloud_status(jobs,client,reference_id)}

def download_native_video(jobs,client,run_folder,content_id,asset_sha256,entity_ref=None,opener=None):
    reference_id=_identity(run_folder,content_id,asset_sha256,entity_ref)[0]
    return download_media_video(jobs,client,reference_id,opener)
