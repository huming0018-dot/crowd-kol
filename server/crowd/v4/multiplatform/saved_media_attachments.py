"""Owned image attachments for immutable completed Pro runs. No network or cloud."""
import fcntl
import hashlib
import json
import io
import os
from pathlib import Path
import re
import tempfile
import uuid
from urllib.parse import urlsplit,urlunsplit
from results_store import _record

LIMIT=2*1024*1024
WB_LIMIT=25*1024*1024
HEX=re.compile(r'[a-f0-9]{64}')
SCHEMA='crowd-saved-media-attachment-v1'
MIMES={'JPEG':('image/jpeg','.jpg'),'PNG':('image/png','.png'),'WEBP':('image/webp','.webp')}


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def sha(value):
    return hashlib.sha256(value if isinstance(value,bytes) else canonical(value).encode()).hexdigest()


def safe_path(value,root=None):
    path=Path(value).absolute()
    if path.resolve()!=path or path.is_symlink():raise ValueError('attachment_unsafe_path')
    if root is not None and root.resolve() not in path.parents:raise ValueError('attachment_outside_root')
    return path


def read(path,limit):
    path=safe_path(path)
    if not path.is_file() or path.stat().st_size>limit:raise ValueError('attachment_file_invalid')
    data=path.read_bytes()
    if len(data)>limit:raise ValueError('attachment_file_invalid')
    return data



def parse_json_object(data):
    try:
        value=json.loads(data.decode('utf8'))
    except (ValueError,UnicodeError,RecursionError):raise ValueError('attachment_json_invalid') from None
    if not isinstance(value,dict):raise ValueError('attachment_json_object_required')
    stack=[(value,0)]
    while stack:
        item,depth=stack.pop()
        if depth>32:raise ValueError('attachment_json_depth_limit')
        if isinstance(item,dict):stack.extend((v,depth+1) for v in item.values())
        elif isinstance(item,list):stack.extend((v,depth+1) for v in item)
    return value


def read_json_object(path,limit):
    return parse_json_object(read(path,limit))


def _decode(data):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in MIMES or image.width*image.height>16_000_000 or max(image.width,image.height)>16384 or getattr(image,'n_frames',1)!=1:raise ValueError('attachment_decode_limit')
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return {'format':image.format,'width':image.width,'height':image.height,'frames':1,
                'pixel_sha256':sha(image.convert('RGBA').tobytes())}


def decode_bytes(data):
    from PIL import Image
    try:return _decode(data)
    except (OSError,SyntaxError,ValueError,Image.DecompressionBombError):raise ValueError('attachment_decode_failed') from None


def decode(data_path):
    return decode_bytes(read(data_path,LIMIT))


def verify_source(run,media_id):
    run=safe_path(run);rid=run.name
    if str(uuid.UUID(rid))!=rid or not isinstance(media_id,str) or not HEX.fullmatch(media_id):raise ValueError('attachment_identity_invalid')
    files={name:read(run/name,32*1024*1024 if name=='normalized.json' else 1024*1024) for name in ('manifest.json','status.json','normalized.json')}
    manifest,status,norm=(parse_json_object(files[n]) for n in ('manifest.json','status.json','normalized.json'))
    if not isinstance(manifest.get('executor'),dict) or not isinstance(manifest.get('request'),dict) or not isinstance(norm.get('media'),list) or not isinstance(norm.get('records'),list):raise ValueError('attachment_source_shape_invalid')
    terminal_verified=status.get('state')=='completed' and norm.get('run_state')=='completed'
    if not terminal_verified and manifest['request'].get('platform')=='wb':
        from public_source_progress import known_partial_media
        terminal_verified=known_partial_media(run,manifest,status,norm)
    if any(row.get('run_id')!=rid for row in (manifest,status,norm)) or not terminal_verified or manifest.get('executor',{}).get('backend')!='pro' or manifest.get('request',{}).get('platform') not in ('xhs','wb') or norm.get('source_kind')!='mediacrawler_api' or norm.get('reward_eligible') is not False:raise ValueError('attachment_source_not_verified')
    refs=[r for r in norm.get('media',[]) if isinstance(r,dict) and r.get('media_id')==media_id]
    if len(refs)!=1:raise ValueError('attachment_reference_ambiguous')
    ref=refs[0]
    if ref.get('kind') not in ('image','comment_image','cover') or ref.get('platform')!=('weibo' if manifest['request']['platform']=='wb' else 'xiaohongshu') or ref.get('status')!='reference_only' or ref.get('source_kind')!='mediacrawler_api' or ref.get('reward_eligible') is not False:raise ValueError('attachment_reference_invalid')
    if not isinstance(ref.get('url'),str):raise ValueError('attachment_reference_url_invalid')
    parsed=urlsplit(ref['url'])
    host=parsed.hostname or ''
    if parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.fragment or parsed.port not in ((None,80) if parsed.scheme=='http' else (None,443)) or not any(host==domain or host.endswith('.'+domain) for domain in (('sinaimg.cn',) if ref['platform']=='weibo' else ('xhscdn.com','xhsimg.com'))):raise ValueError('attachment_reference_url_invalid')
    if ref['platform']=='weibo' and (ref.get('kind')!='image' or ref.get('comment_id') is not None or manifest['request'].get('media') is not True):raise ValueError('attachment_reference_invalid')
    rows=[r for r in norm.get('records',[]) if isinstance(r,dict) and r.get('content_id')==ref.get('content_id') and r.get('platform')==ref['platform'] and r.get('kind')==('comment' if ref.get('comment_id') else 'content') and (not ref.get('comment_id') or r.get('comment_id')==ref['comment_id']) and isinstance(r.get('media'),list) and ref in r['media']]
    if len(rows)!=1:raise ValueError('attachment_source_ambiguous')
    body=rows[0];origin=body.get('origin',{})
    if not isinstance(origin,dict):raise ValueError('attachment_source_shape_invalid')
    expected_source_run=rid
    if manifest.get('source_continuation') is not None:
        from continuation_media import reused_body_context
        context=reused_body_context(run,manifest,norm,body)
        expected_source_run=__import__('source_continuation_chain').seed_source(context)
    if body.get('record_hash')!=sha({k:v for k,v in body.items() if k!='record_hash'}) or origin.get('run_id')!=expected_source_run or origin.get('operation_id')!=expected_source_run or origin.get('executor')!='mediacrawler_pro' or not isinstance(origin.get('observation_sha256'),str) or not HEX.fullmatch(origin['observation_sha256']):raise ValueError('attachment_source_hash_invalid')
    return ref,body,{name:sha(data) for name,data in files.items()}



def reference_limit(ref):return WB_LIMIT if ref.get('platform')=='weibo' else LIMIT

def reference_transport(ref):
    url=urlsplit(ref['url'])
    if ref['platform']=='weibo':
        parts=[x for x in url.path.split('/') if x]
        if parts:parts[0]='large'
        return 'https://i1.wp.com/'+url.netloc+('/'+'/'.join(parts) if parts else url.path)
    return urlunsplit(('https',url.hostname,url.path,url.query,'')) if url.scheme=='http' else ref['url']


def _sidecar(run_id,media_id,ref,body,files,data,decoded):
    transport=reference_transport(ref)
    identity={'run_id':run_id,'media_id':media_id,'normalized_sha256':files['normalized.json'],'asset_sha256':sha(data)}
    aid=sha(identity);mime,suffix=MIMES[decoded['format']];filename=sha(data)+suffix
    return {'schema':SCHEMA,**identity,'path':'attachments/'+aid+'/'+filename,'asset_file':filename,
            'bytes':len(data),'content_type':mime,'decoded':decoded,'reference_sha256':sha(ref),
            'source_record_hash':body['record_hash'],'source_observation_sha256':body['origin']['observation_sha256'],
            'source_url_sha256':sha(ref['url']),'transport_url_sha256':sha(transport),'protected_files_sha256':files,
            'platform':ref['platform'],'content_id':ref['content_id'],'comment_id':ref.get('comment_id'),
            'media_kind':ref['kind'],'cloud_ack':False,'reward_eligible':False}


def _media_record(sidecar,ref,body):
    return {'media_id':sidecar['media_id'],'platform':ref['platform'],'content_id':ref['content_id'],'comment_id':ref.get('comment_id'),'media_kind':ref['kind'],'url':ref['url'],'path':sidecar['path'],'sha256':sidecar['asset_sha256'],'bytes':sidecar['bytes'],'content_type':sidecar['content_type'],'width':sidecar['decoded']['width'],'height':sidecar['decoded']['height'],'status':'local_bytes_verified','attachment_id':sha({'run_id':sidecar['run_id'],'media_id':sidecar['media_id'],'normalized_sha256':sidecar['normalized_sha256'],'asset_sha256':sidecar['asset_sha256']}),'attachment_schema':SCHEMA,'source_kind':'mediacrawler_api','reward_eligible':False,'origin':{'run_id':sidecar['run_id'],'source_record_hash':body['record_hash'],'source_observation_sha256':body['origin']['observation_sha256'],'reference_sha256':sha(ref)}}


class SavedMediaAttachments:
    """Caller resolves registered runs; no arbitrary run path comes from HTTP input."""
    def __init__(self,root,registered_run,results_store):
        self.root=safe_path(Path(root)/'media-attachments');self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.registered_run,self.results=registered_run,results_store

    def _run(self,run_id):
        if not isinstance(run_id,str) or str(uuid.UUID(run_id))!=run_id:raise ValueError('attachment_run_invalid')
        path=safe_path(self.registered_run(run_id))
        if path.name!=run_id:raise ValueError('attachment_run_binding_invalid')
        return path

    def _publish(self,path,data):
        path=safe_path(path,self.root)
        if path.exists():
            if read(path,max(len(data),LIMIT))!=data:raise ValueError('attachment_existing_asset_changed')
            return
        fd,name=tempfile.mkstemp(prefix='.attachment-',dir=path.parent)
        temporary=Path(name)
        try:
            with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
            os.link(temporary,path)
        finally:temporary.unlink(missing_ok=True)

    def attach(self,run_id,media_id,asset_path,receipt):
        if verify_source(self._run(run_id),media_id)[0]['platform']=='weibo':raise ValueError('attachment_native_proof_required')
        return self._attach_verified(run_id,media_id,asset_path,receipt)

    def attach_native(self,run_id,media_id):
        # No source request: re-verify the committed original SDK child result.
        from pro_media_integration import summary
        run=self._run(run_id);ref,body,files=verify_source(run,media_id)
        if ref['platform'] not in ('weibo','xiaohongshu'):raise ValueError('attachment_native_platform_invalid')
        manifest=read_json_object(run/'manifest.json',1024*1024)
        info=summary(run,manifest)
        if not isinstance(info,dict) or info.get('state')!='completed' or not isinstance(info.get('assets'),list):raise ValueError('attachment_native_incomplete')
        assets=[a for a in info['assets'] if isinstance(a,dict) and a.get('original_url')==ref['url'] and a.get('content_id')==ref['content_id']]
        if ref['platform']=='xiaohongshu':assets=[a for a in assets if a.get('source_media_id')==media_id and a.get('media_engine')=='native_pro_downloader']
        if len(assets)!=1:raise ValueError('attachment_native_ambiguous')
        a=assets[0];asset=safe_path(run/a['path'],run);data=read(asset,reference_limit(ref));decoded=decode_bytes(data)
        if a.get('transport_url')!=reference_transport(ref) or a.get('sha256')!=sha(data) or a.get('bytes')!=len(data):raise ValueError('attachment_native_binding_invalid')
        receipt={'state':'downloaded_not_imported_or_cloud_saved','source_files_unchanged':True,'run_id':run_id,'media_id':media_id,'platform_http_requests':None,'native_stage_verified':True,'cloud_ack':False,'reference_sha256':sha(ref),'source_record_hash':body['record_hash'],'asset_file':asset.name,'asset_sha256':sha(data),'bytes':len(data),'url_sha256':sha(ref['url']),'transport_url_sha256':sha(reference_transport(ref)),'normalized_sha256':files['normalized.json'],'manifest_sha256':files['manifest.json'],'status_sha256':files['status.json'],'content_type':MIMES[decoded['format']][0]}
        return self._attach_verified(run_id,media_id,asset,receipt,native_verified=True)

    def _attach_verified(self,run_id,media_id,asset_path,receipt,*,native_verified=False):
        run=self._run(run_id);ref,body,files=verify_source(run,media_id)
        if not isinstance(receipt,dict):raise ValueError('attachment_receipt_invalid')
        asset=safe_path(asset_path);data=read(asset,reference_limit(ref))
        if not data or receipt.get('state')!='downloaded_not_imported_or_cloud_saved' or receipt.get('source_files_unchanged') is not True or receipt.get('run_id')!=run_id or receipt.get('media_id')!=media_id or not ((native_verified is True and ref['platform'] in ('weibo','xiaohongshu') and receipt.get('native_stage_verified') is True and receipt.get('platform_http_requests') is None) or (ref['platform']!='weibo' and type(receipt.get('platform_http_requests')) is int and receipt['platform_http_requests']==1)) or receipt.get('cloud_ack') is not False or receipt.get('reference_sha256')!=sha(ref) or receipt.get('source_record_hash')!=body['record_hash'] or receipt.get('asset_file')!=asset.name or receipt.get('asset_sha256')!=sha(data) or type(receipt.get('bytes')) is not int or receipt['bytes']!=len(data):raise ValueError('attachment_receipt_invalid')
        transport=reference_transport(ref)
        if receipt.get('url_sha256')!=sha(ref['url']) or receipt.get('transport_url_sha256')!=sha(transport):raise ValueError('attachment_transport_binding_invalid')
        if any(receipt.get(field)!=files[name] for name,field in [('normalized.json','normalized_sha256'),('manifest.json','manifest_sha256'),('status.json','status_sha256')]):raise ValueError('attachment_source_changed')
        decoded=decode_bytes(data)
        mime,suffix=MIMES[decoded['format']]
        if receipt.get('content_type')!=mime:raise ValueError('attachment_mime_mismatch')
        identity={'run_id':run_id,'media_id':media_id,'normalized_sha256':files['normalized.json'],'asset_sha256':sha(data)}
        aid=sha(identity);folder=safe_path(self.root/run_id);folder.mkdir(mode=0o700,exist_ok=True)
        lock=safe_path(folder/(media_id+'.lock'));fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            target=safe_path(folder/aid);target.mkdir(mode=0o700,exist_ok=True)
            filename=sha(data)+suffix;virtual='attachments/'+aid+'/'+filename
            sidecar=_sidecar(run_id,media_id,ref,body,files,data,decoded)
            self._publish(target/filename,data);self._publish(target/'attachment.json',(canonical(sidecar)+'\n').encode())
            # Recheck all immutable originals before the local results transaction.
            if verify_source(run,media_id)[2]!=files:raise ValueError('attachment_source_changed')
            media=_media_record(sidecar,ref,body)
            result=self.results.ingest({'run_id':run_id,'source':{'executor':'saved_media_attachments','schema':SCHEMA},'source_kind':'mediacrawler_api','reward_eligible':False,'records':[],'media':[media]})
            revision=result.get('import_revision',result.get('results_revision'))
            if type(revision) is not int or revision<1:raise ValueError('attachment_registration_unverified')
            registration={'schema':'crowd-saved-media-registration-v1','state':'locally_registered',
                          'attachment_id':aid,'sidecar_sha256':sha(sidecar),'version_hash':_record({**media,'kind':'media'})[3],'import_revision':revision,'cloud_ack':False}
            self._publish(target/'registration.json',(canonical(registration)+'\n').encode())
            return {'attachment_id':aid,'run_id':run_id,'media':media,'results':result,'cloud_ack':False,'original_source_files_unchanged':True}
        finally:os.close(fd)

    def resolve(self,run_id,virtual):
        run=self._run(run_id)
        if not isinstance(virtual,str) or not re.fullmatch(r'attachments/[a-f0-9]{64}/[a-f0-9]{64}\.(jpg|png|webp)',virtual):raise ValueError('attachment_path_invalid')
        _,aid,filename=virtual.split('/');folder=safe_path(self.root/run_id/aid,self.root)
        sidecar=read_json_object(folder/'attachment.json',1024*1024);ref,body,files=verify_source(run,sidecar.get('media_id'))
        asset=safe_path(folder/filename,self.root);data=read(asset,reference_limit(ref));actual_decode=decode_bytes(data)
        expected=_sidecar(run_id,sidecar['media_id'],ref,body,files,data,actual_decode)
        if canonical(sidecar)!=canonical(expected) or expected['path']!=virtual:
            raise ValueError('attachment_binding_changed')
        try:registration=read_json_object(folder/'registration.json',65536)
        except (OSError,ValueError):raise ValueError('attachment_not_registered') from None
        revision=registration.get('import_revision')
        media=_media_record(expected,ref,body);version_hash=_record({**media,'kind':'media'})[3]
        expected_registration={'schema':'crowd-saved-media-registration-v1','state':'locally_registered',
            'attachment_id':aid,'sidecar_sha256':sha(expected),'version_hash':version_hash,'import_revision':revision,'cloud_ack':False}
        if type(revision) is not int or revision<1 or canonical(registration)!=canonical(expected_registration):
            raise ValueError('attachment_not_registered')
        saved=self.results.saved_version(ref['platform'],ref['content_id'],'media',version_hash,revision=revision)
        if saved.get('attachment_id')!=aid or saved.get('path')!=virtual or saved.get('first_version_revision')!=revision:raise ValueError('attachment_registration_unverified')
        return asset
