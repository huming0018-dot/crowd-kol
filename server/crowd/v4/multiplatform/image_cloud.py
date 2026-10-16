"""Image-object contract preparation/readback. No upload, RPC or task execution.

Deliberately separate from native MP4. Central image RPC/storage/decoder adoption
is still required before any manifest prepared here can become a cloud receipt.
"""
import hashlib
import json
import os
import stat
import re
import uuid
from urllib.parse import urlsplit,urlunsplit
from types import SimpleNamespace
from media_cloud import _url as existing_storage_url
from saved_media_attachments import verify_source,read,decode_bytes,canonical,sha,MIMES,safe_path,parse_json_object,_sidecar,_media_record
from results_store import _record

BUCKET='crowd-machine-media'
LIMIT=2*1024*1024
WB_LIMIT=25*1024*1024
def image_limit(value):return WB_LIMIT if isinstance(value,dict) and value.get('schema') in ('crowd-image-object-v2','crowd-image-object-v3') and value.get('platform')=='weibo' else LIMIT
FIELDS=('schema','manifest_version','idempotency_key','task_id','child_id','run_id','lease_epoch',
 'local_run_id','local_job_id','capture_id','envelope_hash','platform','content_kind','content_id',
 'comment_id','entity_ref','media_id','attachment_id','asset_sha256','asset_bytes','content_mime',
 'width','height','frames','pixel_sha256','source_record_hash','source_observation_sha256',
 'source_reference_sha256','source_url_sha256','transport_url_sha256','normalized_sha256','canonical_reference','source_record_canonical')
CONTINUATION_FIELDS=('continuation_id','continuation_run_id','continuation_lease_epoch','source_local_run_id')
HASH_FIELDS=('envelope_hash','media_id','attachment_id','asset_sha256','pixel_sha256','source_record_hash',
 'source_observation_sha256','source_reference_sha256','source_url_sha256','transport_url_sha256','normalized_sha256')
HEX=re.compile(r'[a-f0-9]{64}')
ID=re.compile(r'[A-Za-z0-9_.:-]{1,200}')


def uid(value):
    try:return isinstance(value,str) and str(uuid.UUID(value))==value
    except (ValueError,AttributeError):return False


def validate_manifest(value):
    continuation=isinstance(value,dict) and value.get('schema')=='crowd-image-object-v3'
    if not isinstance(value,dict) or set(value)!=set(FIELDS+CONTINUATION_FIELDS if continuation else FIELDS):raise ValueError('invalid_image_manifest')
    version=3 if continuation else 2 if value['schema']=='crowd-image-object-v2' and value['platform']=='weibo' else 1
    if continuation and (not all(uid(value[k]) for k in ('continuation_id','continuation_run_id','source_local_run_id')) or type(value['continuation_lease_epoch']) is not int or value['continuation_lease_epoch']-value['lease_epoch'] not in (1,2) or value['continuation_run_id']==value['run_id'] or value['source_local_run_id']==value['local_run_id']):raise ValueError('invalid_image_manifest')
    if value['schema']!=('crowd-image-object-v'+str(version)) or type(value['manifest_version']) is not int or value['manifest_version']!=version:raise ValueError('invalid_image_manifest')
    if not all(uid(value[k]) for k in ('task_id','child_id','run_id','local_run_id','local_job_id','capture_id')):raise ValueError('invalid_image_manifest')
    if not all(isinstance(value[k],str) and HEX.fullmatch(value[k]) for k in HASH_FIELDS):raise ValueError('invalid_image_manifest')
    if value['idempotency_key']!='image:'+value['local_job_id'] or value['platform']!=('weibo' if version in (2,3) else 'xiaohongshu') or value['content_kind'] not in (('content',) if version in (2,3) else ('content','comment')) or not isinstance(value['content_id'],str) or not ID.fullmatch(value['content_id']):raise ValueError('invalid_image_manifest')
    if value['content_kind']=='comment':
        if not isinstance(value['comment_id'],str) or not ID.fullmatch(value['comment_id']):raise ValueError('invalid_image_manifest')
    elif value['comment_id'] is not None:raise ValueError('invalid_image_manifest')
    entity=value['platform']+':'+value['content_kind']+':'+value['content_id']+(':'+value['comment_id'] if value['comment_id'] else '')
    if value['entity_ref']!=entity:raise ValueError('invalid_image_manifest')
    if any(type(value[k]) is not int for k in ('lease_epoch','asset_bytes','width','height','frames')):raise ValueError('invalid_image_manifest')
    if not 1<=value['lease_epoch']<=2147483647 or not 1<=value['asset_bytes']<=image_limit(value) or not 1<=value['width']<=16384 or not 1<=value['height']<=16384 or value['width']*value['height']>16_000_000 or value['frames']!=1 or value['content_mime'] not in ('image/jpeg','image/png','image/webp'):raise ValueError('invalid_image_manifest')
    try:
        if not isinstance(value['canonical_reference'],str) or len(value['canonical_reference'])>16000:raise ValueError()
        ref=json.loads(value['canonical_reference'])
        if not isinstance(ref,dict) or canonical(ref)!=value['canonical_reference'] or sha(ref)!=value['source_reference_sha256'] or ref.get('media_id')!=value['media_id'] or ref.get('platform')!=value['platform'] or ref.get('content_id')!=value['content_id'] or ref.get('comment_id')!=value['comment_id'] or ref.get('kind') not in (('image',) if version in (2,3) else ('image','comment_image','cover')) or ref.get('status')!='reference_only' or ref.get('source_kind')!='mediacrawler_api' or ref.get('reward_eligible') is not False or not isinstance(ref.get('url'),str) or any(ord(c)<=32 for c in ref['url']):raise ValueError()
        url=urlsplit(ref['url']);host=url.hostname or ''
        if url.scheme not in ('http','https') or url.username or url.password or url.fragment or url.port not in ((None,80) if url.scheme=='http' else (None,443)) or not any(host==d or host.endswith('.'+d) for d in (('sinaimg.cn',) if version in (2,3) else ('xhscdn.com','xhsimg.com'))):raise ValueError()
        transport=urlunsplit(('https',host,url.path,url.query,'')) if url.scheme=='http' else ref['url']
        if version in (2,3):
            parts=[x for x in url.path.split('/') if x]
            if parts:parts[0]='large'
            transport='https://i1.wp.com/'+url.netloc+('/'+'/'.join(parts) if parts else url.path)
        if value['source_url_sha256']!=sha(ref['url']) or value['transport_url_sha256']!=sha(transport):raise ValueError()
    except (ValueError,TypeError,UnicodeError,RecursionError):raise ValueError('invalid_image_manifest') from None
    try:
        source_text=value['source_record_canonical']
        if not isinstance(source_text,str) or len(source_text.encode('utf8'))>128*1024:raise ValueError()
        source=json.loads(source_text)
        if not isinstance(source,dict) or 'record_hash' in source or canonical(source)!=source_text or sha(source)!=value['source_record_hash']:raise ValueError()
        if any(canonical(source.get(k))!=canonical(value[k]) for k in ('platform','content_id')) or source.get('kind')!=value['content_kind'] or source.get('comment_id')!=value['comment_id']:raise ValueError()
        origin=source.get('origin',{})
        if not isinstance(origin,dict) or origin.get('run_id')!=value.get('source_local_run_id',value['local_run_id']) or origin.get('operation_id')!=value.get('source_local_run_id',value['local_run_id']) or origin.get('executor')!='mediacrawler_pro' or origin.get('observation_sha256')!=value['source_observation_sha256']:raise ValueError()
        if not isinstance(source.get('media'),list) or sum(canonical(x)==canonical(ref) for x in source['media'])!=1:raise ValueError()
    except (ValueError,TypeError,UnicodeError,RecursionError):raise ValueError('invalid_image_manifest') from None
    return {'canonical_manifest':canonical(value),'manifest_hash':hashlib.sha256(('crowd-media-image-v'+str(version)+'\n'+canonical(value)).encode()).hexdigest()}



def _generation(value):
    return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)


def _unchanged_generation(path,expected):
    try:
        path=safe_path(path);current=os.stat(path,follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or _generation(current)!=expected:raise ValueError()
    except (OSError,ValueError):raise ValueError('image_attachment_generation_changed') from None


def _snapshot(path,limit):
    path=safe_path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=limit:raise ValueError('image_attachment_snapshot_invalid')
        chunks=[];count=0
        while True:
            chunk=os.read(fd,min(65536,limit+1-count))
            if not chunk:break
            chunks.append(chunk);count+=len(chunk)
            if count>limit:raise ValueError('image_attachment_snapshot_invalid')
        if _generation(os.fstat(fd))!=_generation(before):raise ValueError('image_attachment_generation_changed')
        _unchanged_generation(path,_generation(before))
        return b''.join(chunks),_generation(before)
    finally:os.close(fd)


def prepare_image(adapter,run_id,virtual_path,capture):
    asset=adapter.resolve(run_id,virtual_path)
    # This is a registered attachment, not a bare user-selected file or MIME claim.
    sidecar_path=asset.parent/'attachment.json';registration_path=asset.parent/'registration.json'
    sidecar_bytes,sidecar_generation=_snapshot(sidecar_path,1024*1024)
    registration_bytes,registration_generation=_snapshot(registration_path,65536)
    sidecar=parse_json_object(sidecar_bytes);registration=parse_json_object(registration_bytes)
    run=adapter._run(run_id);ref,body,files=verify_source(run,sidecar.get('media_id'))
    if not isinstance(capture,dict) or set(capture)!={'record','receipt'} or not isinstance(capture['record'],dict) or not isinstance(capture['receipt'],dict):raise ValueError('image_source_binding_denied')
    record,receipt=capture['record'],capture['receipt']
    source={k:v for k,v in body.items() if k!='record_hash'}
    projected={k:v for k,v in record.items() if k!='record_hash'}
    if 'record_hash' in record and record['record_hash']!=body['record_hash']:raise ValueError('image_source_binding_denied')
    if set(projected)-set(source)=={'author_id'}:
        if not isinstance(source.get('author'),dict) or canonical(projected['author_id'])!=canonical(source['author'].get('author_id')):raise ValueError('image_source_binding_denied')
        projected.pop('author_id')
    if canonical(projected)!=canonical(source):raise ValueError('image_source_binding_denied')
    if receipt.get('status')!='received' or receipt.get('reward_eligible') is not False or record.get('reward_eligible') is not False or record.get('origin',{}).get('run_id')!=body.get('origin',{}).get('run_id'):raise ValueError('image_source_binding_denied')
    if not all(uid(receipt.get(k)) for k in ('task_id','child_id','run_id','capture_id')) or type(receipt.get('lease_epoch')) is not int or not 1<=receipt['lease_epoch']<=2147483647 or not isinstance(receipt.get('envelope_hash'),str) or not HEX.fullmatch(receipt['envelope_hash']):raise ValueError('image_source_binding_denied')
    data,asset_generation=_snapshot(asset,WB_LIMIT if ref['platform']=='weibo' else LIMIT);decoded=decode_bytes(data);mime,_=MIMES[decoded['format']]
    expected_sidecar=_sidecar(run_id,sidecar['media_id'],ref,body,files,data,decoded)
    if canonical(sidecar)!=canonical(expected_sidecar) or expected_sidecar['path']!=virtual_path or sidecar.get('asset_file')!=asset.name:
        raise ValueError('image_attachment_binding_changed')
    media=_media_record(expected_sidecar,ref,body);version_hash=_record({**media,'kind':'media'})[3]
    revision=registration.get('import_revision');aid=sidecar['path'].split('/')[1]
    expected_registration={'schema':'crowd-saved-media-registration-v1','state':'locally_registered',
        'attachment_id':aid,'sidecar_sha256':sha(expected_sidecar),'version_hash':version_hash,
        'import_revision':revision,'cloud_ack':False}
    if type(revision) is not int or revision<1 or canonical(registration)!=canonical(expected_registration):
        raise ValueError('image_attachment_registration_changed')
    saved=adapter.results.saved_version(ref['platform'],ref['content_id'],'media',version_hash,revision=revision)
    if saved.get('attachment_id')!=aid or saved.get('path')!=virtual_path or saved.get('first_version_revision')!=revision:
        raise ValueError('image_attachment_registration_changed')
    identity={k:receipt[k] for k in ('task_id','child_id','run_id','lease_epoch','capture_id','envelope_hash')}
    context=None
    source_manifest=parse_json_object(read(run/'manifest.json',1024*1024))
    if source_manifest.get('source_continuation') is not None:
        from continuation_media import reused_body_context
        source_norm=parse_json_object(read(run/'normalized.json',32*1024*1024))
        context=reused_body_context(run,source_manifest,source_norm,body)
    version=3 if context is not None else 2 if ref['platform']=='weibo' else 1
    schema='crowd-image-object-v'+str(version)
    local_job=str(uuid.uuid5(uuid.NAMESPACE_URL,schema+':'+canonical({**identity,'attachment_id':sidecar['path'].split('/')[1],'local_run_id':run_id})))
    value={'schema':schema,'manifest_version':version,'idempotency_key':'image:'+local_job,
           **identity,'local_run_id':run_id,'local_job_id':local_job,'platform':ref['platform'],
           'content_kind':body['kind'],'content_id':ref['content_id'],'comment_id':ref.get('comment_id'),
           'entity_ref':ref['platform']+':'+body['kind']+':'+ref['content_id']+(':'+ref['comment_id'] if ref.get('comment_id') else ''),
           'media_id':ref['media_id'],'attachment_id':sidecar['path'].split('/')[1],'asset_sha256':sha(data),'asset_bytes':len(data),
           'content_mime':mime,'width':decoded['width'],'height':decoded['height'],'frames':decoded['frames'],'pixel_sha256':decoded['pixel_sha256'],
           'source_record_hash':body['record_hash'],'source_observation_sha256':body['origin']['observation_sha256'],'source_record_canonical':canonical(source),
           'source_reference_sha256':sha(ref),'canonical_reference':canonical(ref),'source_url_sha256':sidecar['source_url_sha256'],
           'transport_url_sha256':sidecar['transport_url_sha256'],'normalized_sha256':files['normalized.json']}
    if context is not None:
        continuation=source_manifest.get('source_continuation_lease')
        if not isinstance(continuation,dict) or continuation.get('run_id')==receipt['run_id'] or continuation.get('lease_epoch')!=context['source_lease_epoch']+1 or continuation.get('lease_epoch')-receipt['lease_epoch']!=(2 if context.get('proof',{}).get('chain') is not None else 1):raise ValueError('image_source_binding_denied')
        value.update(continuation_id=context['continuation_id'],continuation_run_id=continuation['run_id'],continuation_lease_epoch=continuation['lease_epoch'],source_local_run_id=__import__('source_continuation_chain').seed_source(context))
    validate_manifest(value)
    if verify_source(run,sidecar.get('media_id'))[2]!=files:raise ValueError('image_source_changed')
    for path,generation in ((asset,asset_generation),(sidecar_path,sidecar_generation),(registration_path,registration_generation)):
        _unchanged_generation(path,generation)
    return value,data


def verify_receipt(receipt,manifest):
    expected=validate_manifest(manifest)
    if not isinstance(receipt,dict) or not uid(receipt.get('artifact_id')):raise ValueError('image_receipt_mismatch')
    suffix={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}[manifest['content_mime']]
    path='crowd-owner-main/'+receipt['artifact_id']+'/'+manifest['asset_sha256']+suffix
    fixed={'artifact_kind':'image_object','status':'received','verification':'server_storage_bytes_sha256_decode',
           'bucket_id':BUCKET,'object_path':path,'manifest_hash':expected['manifest_hash'],'manifest':manifest,'reward_eligible':False}
    if any(k not in receipt or canonical(receipt[k])!=canonical(v) for k,v in fixed.items()):raise ValueError('image_receipt_mismatch')
    return receipt


def signed_url(endpoint,url,receipt,manifest,kind='sign'):
    verify_receipt(receipt,manifest)
    try:base=urlsplit(endpoint);value=urlsplit(url)
    except (ValueError,TypeError):raise ValueError('image_storage_url_denied') from None
    if kind not in ('sign','upload/sign') or base.scheme!='https' or not base.hostname or base.username or base.password or base.port is not None:raise ValueError('image_storage_url_denied')
    try:existing_storage_url(SimpleNamespace(endpoint=endpoint),url,kind,receipt)
    except (ValueError,TypeError):raise ValueError('image_storage_url_denied') from None
    return url


def verify_retrieved(data,receipt,manifest):
    verify_receipt(receipt,manifest)
    if not isinstance(data,bytes) or len(data)!=manifest['asset_bytes'] or len(data)>image_limit(manifest) or sha(data)!=manifest['asset_sha256']:raise ValueError('image_object_mismatch')
    decoded=decode_bytes(data);mime,_=MIMES[decoded['format']]
    if mime!=manifest['content_mime'] or any(canonical(decoded[k])!=canonical(manifest[k]) for k in ('width','height','frames','pixel_sha256')):raise ValueError('image_object_mismatch')
    return {'state':'downloaded_and_decoded','bytes':len(data),'sha256':sha(data),'decoded':decoded,'receipt_contract_verified':True,'authoritative_receipt_origin_verified':False}
