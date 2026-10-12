"""Build optimization evidence from registered saved sources, never client dictionaries."""
import hashlib
import json
import re
from pathlib import Path
from analysis_artifact import _read, _safe_ancestors
from mc_runner import canonical, uid, normalize, PLATFORMS


def context(application, saved):
    state=saved['state'];run=uid(state['run_id']);cid=state['content_id'];platform=state['platform']
    folder=application._registered_run_root(run)/'runs'/run
    source,_=_read(folder/'normalized.json',32*1024*1024)
    rows=[r for r in source.get('records',[]) if r.get('platform')==platform and r.get('content_id')==cid and r.get('kind') in ('content','dynamic')]
    if len(rows)!=1:raise ValueError('transcript_optimization_source_ambiguous')
    row=rows[0]
    if (row.get('source_kind')!='mediacrawler_api' or row.get('reward_eligible') is not False
        or row.get('origin',{}).get('run_id')!=run
        or row.get('record_hash')!=hashlib.sha256(canonical({k:v for k,v in row.items() if k not in ('record_hash','discovery_kind')}).encode()).hexdigest()):
        raise ValueError('transcript_optimization_source_changed')
    origin=row['origin'];files=[r for r in source.get('files',[]) if r.get('sha256')==origin.get('file_sha256')]
    if len(files)!=1 or type(origin.get('line')) is not int or origin['line']<1:raise ValueError('transcript_optimization_source_changed')
    source_path=Path(files[0]['path'])
    if source_path.is_absolute() or '..' in source_path.parts or not str(source_path).startswith('output/'):raise ValueError('transcript_optimization_source_changed')
    original=folder/source_path;_safe_ancestors(original)
    if original.is_symlink() or not original.is_file() or original.stat().st_size>32*1024*1024:raise ValueError('transcript_optimization_source_changed')
    raw=original.read_bytes();lines=raw.splitlines()
    if hashlib.sha256(raw).hexdigest()!=origin['file_sha256'] or origin['line']>len(lines):raise ValueError('transcript_optimization_source_changed')
    code=next((key for key,name in PLATFORMS.items() if name==platform),None)
    replay=normalize(code,row['kind'],json.loads(lines[origin['line']-1]),origin)
    if replay['record_hash']!=row['record_hash']:raise ValueError('transcript_optimization_source_changed')
    value={'title':row.get('title',''),'body':row.get('body',''),'asset_sha256':state['asset_sha256'],'source_sha256':row['record_hash']}
    directory=application.root/'transcript-references'/state['asset_sha256'];manifest=directory/'reference.json'
    if not manifest.exists():return value,None
    references,_=_read(manifest,100000)
    ref_run=uid(references['source_run_id']);ref_folder=application._registered_run_root(ref_run)/'runs'/ref_run
    ref_source,_=_read(ref_folder/'normalized.json',32*1024*1024)
    audio=[r for r in source.get('media',[]) if r.get('sha256')==state['asset_sha256'] and r.get('content_id')==cid]
    video=[r for r in ref_source.get('media',[]) if r.get('sha256')==references.get('source_asset_sha256') and r.get('content_id')==cid]
    if (platform!='bilibili' or len(audio)!=1 or len(video)!=1
        or any(r.get('platform')!=platform or r.get('content_identity_basis')!='same_native_bilibili_view' for r in audio+video)
        or audio[0].get('source_media_id')!=video[0].get('source_media_id')
        or not audio[0].get('bilibili_view_cid') or audio[0]['bilibili_view_cid']!=video[0].get('bilibili_view_cid')):
        raise ValueError('transcript_optimization_reference_binding_denied')
    from media_native import _identity
    _,_,_,verified_audio,_,_=_identity(folder,cid,state['asset_sha256'],state.get('entity_ref'),native_audio=True)
    _,_,_,verified_video,_,_=_identity(ref_folder,cid,references['source_asset_sha256'],state.get('entity_ref'),native_asr=True)
    if verified_audio!=audio[0] or verified_video!=video[0]:raise ValueError('transcript_optimization_reference_binding_denied')
    path=Path(video[0]['path'])
    if path.is_absolute() or '..' in path.parts or not str(path).startswith('output/'):raise ValueError('transcript_optimization_reference_binding_denied')
    asset=ref_folder/path;_safe_ancestors(asset)
    if asset.is_symlink() or not asset.is_file() or asset.stat().st_size>64*1024*1024 or hashlib.sha256(asset.read_bytes()).hexdigest()!=references['source_asset_sha256']:
        raise ValueError('transcript_optimization_reference_changed')
    samples=references.get('samples')
    if not isinstance(samples,list) or len(samples)>100:raise ValueError('transcript_optimization_reference_changed')
    for sample in samples:
        name=sample.get('frame_file','')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}\.png',name):raise ValueError('transcript_optimization_reference_changed')
        frame=directory/name;_safe_ancestors(frame)
        if frame.is_symlink() or not frame.is_file() or frame.stat().st_size>4*1024*1024 or hashlib.sha256(frame.read_bytes()).hexdigest()!=sample.get('frame_sha256'):
            raise ValueError('transcript_optimization_reference_changed')
    # Different MP4/M4A bytes, matched native content/CID; never claim equal asset hashes.
    value['reference_source_asset_sha256']=references['source_asset_sha256']
    return value,{'source_asset_sha256':references['source_asset_sha256'],'samples':[{k:v for k,v in sample.items() if k!='frame_file'} for sample in samples]}
