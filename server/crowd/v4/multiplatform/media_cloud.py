"""Private cloud video receipts bound to an existing completed local job and capture."""
import fcntl
import stat
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from analysis_artifact import _read,_safe_ancestors
from cloud_sync import canonical,CloudError
from complete_video import read_bytes
from mc_runner import uid,write

LIMIT=50*1024*1024
FIELDS=('idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','platform','content_id','capture_id','envelope_hash','asset_sha256','asset_bytes','duration_ms','source_duration_ms','source_asset_sha256','source_file_sha256','source_reference_sha256','result_file_sha256')

def _job_id(value):
    try:return uid(value)
    except Exception:raise ValueError('invalid_media_job_id') from None

def _hash(value):
    version=2 if type(value.get('manifest_version')) is int and value['manifest_version']==2 else 1
    return hashlib.sha256((f'crowd-media-video-v{version}\n'+canonical(value)).encode()).hexdigest()
def _receipt_folder(jobs):
    folder=jobs.root.parent/'media-cloud-receipts';_safe_ancestors(folder);folder.mkdir(mode=0o700,exist_ok=True)
    if folder.stat().st_mode&0o077:raise ValueError('unsafe_media_cloud_file')
    return folder

def _local_job(jobs,job_id):
    job_id=_job_id(job_id);folder=jobs.root/job_id;_safe_ancestors(folder)
    state,_=_read(folder/'state.json',65536)
    if state.get('state')!='completed' or state.get('kind')!='complete_video' or state.get('job_id')!=job_id or state.get('platform')!='douyin':raise ValueError('media_cloud_not_completed')
    rows,result_sha=_read(folder/'result.json',200000)
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict) or rows[0].get('kind')!='processed_video' or rows[0].get('platform')!=state['platform'] or rows[0].get('content_id')!=state.get('content_id'):raise ValueError('media_cloud_identity_mismatch')
    e=rows[0].get('evidence',{})
    if state.get('result_sha256')!=result_sha or e.get('asset_sha256')!=state.get('asset_sha256') or e.get('source_reference_sha256')!=state.get('source_reference_sha256') or e.get('source_run_id')!=state.get('run_id') or e.get('full_source_decode') is not True or e.get('full_output_decode') is not True or e.get('derivative') is not True:raise ValueError('media_cloud_identity_mismatch')
    _safe_ancestors(folder/'video.mp4')
    data=read_bytes(folder/'video.mp4',LIMIT)
    if type(e.get('bytes')) is not int or e['bytes']!=len(data) or len(data)<12 or data[4:8]!=b'ftyp' or hashlib.sha256(data).hexdigest()!=state['asset_sha256']:raise ValueError('media_cloud_asset_changed')
    for k in ('duration_seconds','source_duration_seconds'):
        if type(e.get(k)) not in (int,float) or not math.isfinite(e[k]) or not 0<e[k]<=7200:raise ValueError('media_cloud_identity_mismatch')
    if abs(e['duration_seconds']-e['source_duration_seconds'])>.25:raise ValueError('media_cloud_identity_mismatch')
    return state,e,result_sha,data

def prepare_media_video(jobs,client,job_id,binding=None):
    if client is None or getattr(client,'role',None) not in ('owner','worker'):raise ValueError('principal_denied')
    state,e,result_sha,data=_local_job(jobs,job_id)
    if client.role=='worker':
        fields={'task_id','child_id','run_id','lease_epoch','local_run_id','capture_id','envelope_hash'}
        if not isinstance(binding,dict) or set(binding)!=fields or binding['local_run_id']!=state['run_id'] or type(binding['lease_epoch']) is not int or not 1<=binding['lease_epoch']<=2147483647:raise ValueError('media_cloud_identity_mismatch')
        task,child,run,epoch=(binding[k] for k in ('task_id','child_id','run_id','lease_epoch'));receipt=binding
    else:
        matches=set()
        for task in client.call('task_list').get('tasks',[]):
            for child in task.get('children',[]):
                for attempt in child.get('attempts',[]):
                    if attempt.get('local_run_id')==state['run_id']:matches.add((task['task_id'],child['child_id'],attempt['run_id'],attempt['lease_epoch']))
        if len(matches)!=1:raise ValueError('media_cloud_source_ambiguous')
        task,child,run,epoch=matches.pop()
        if type(epoch) is not int or not 1<=epoch<=2147483647:raise ValueError('media_cloud_identity_mismatch')
        sources=[]
        for item in client.call('results',{'task_id':task}).get('items',[]):
            r=item.get('record',{});receipt=item.get('receipt',{})
            if r.get('kind')!='content' or r.get('platform')!='douyin' or r.get('content_id')!=state['content_id'] or r.get('origin',{}).get('run_id')!=state['run_id']:continue
            expected={'task_id':task,'child_id':child,'run_id':run,'lease_epoch':epoch,'status':'received','reward_eligible':False}
            if any(canonical(receipt.get(k))!=canonical(v) for k,v in expected.items()) or r.get('origin',{}).get('file_sha256')!=e.get('source_file_sha256'):raise ValueError('media_cloud_identity_mismatch')
            sources.append(receipt)
        if len(sources)!=1:raise ValueError('media_cloud_source_ambiguous')
        receipt=sources[0]
    payload={'idempotency_key':'video:'+job_id,'task_id':task,'child_id':child,'run_id':run,'lease_epoch':epoch,'local_run_id':state['run_id'],'local_job_id':job_id,'platform':'douyin','content_id':state['content_id'],'capture_id':receipt['capture_id'],'envelope_hash':receipt['envelope_hash'],'asset_sha256':state['asset_sha256'],'asset_bytes':len(data),'duration_ms':round(e['duration_seconds']*1000),'source_duration_ms':round(e['source_duration_seconds']*1000),'source_asset_sha256':e['source_asset_sha256'],'source_file_sha256':e['source_file_sha256'],'source_reference_sha256':e['source_reference_sha256'],'result_file_sha256':result_sha}
    return payload,data

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*_a,**_k):raise ValueError('media_cloud_redirect_denied')

def _url(client,value,kind,receipt=None):
    try:base=urllib.parse.urlsplit(client.endpoint);url=urllib.parse.urlsplit(value)
    except (ValueError,TypeError):raise ValueError('media_cloud_url_denied') from None
    prefix='/storage/v1/object/'+kind+'/crowd-machine-media/crowd-owner-main/'
    if url.scheme!='https' or url.hostname!=base.hostname or url.port is not None or url.username or url.password or url.fragment or not url.path.startswith(prefix) or len(value)>4096:raise ValueError('media_cloud_url_denied')
    if receipt is not None and url.path!=('/storage/v1/object/'+kind+'/'+receipt['bucket_id']+'/'+receipt['object_path']):raise ValueError('media_cloud_url_denied')
    return value

def _receipt(response,payload):
    r=response.get('receipt',{})
    if r.get('artifact_kind')!='video_object' or r.get('status')!='received' or r.get('verification')!='server_storage_bytes_sha256' or r.get('reward_eligible') is not False or canonical(r.get('manifest'))!=canonical(payload) or r.get('manifest_hash')!=_hash(payload) or r.get('bucket_id')!='crowd-machine-media':raise ValueError('media_cloud_receipt_mismatch')
    aid=uid(r.get('artifact_id'))
    if r.get('object_path')!='crowd-owner-main/'+aid+'/'+payload['asset_sha256']+'.mp4':raise ValueError('media_cloud_receipt_mismatch')
    return r

@contextmanager
def _job_lock(jobs,job_id):
    folder=_receipt_folder(jobs);path=folder/(_job_id(job_id)+'.lock');_safe_ancestors(path)
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid():raise ValueError('unsafe_media_cloud_file')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('media_cloud_busy') from None
        yield
    finally:os.close(fd)

def publish_media_video(jobs,client,job_id,opener=None,binding=None):
    with _job_lock(jobs,job_id):return _publish_media_video(jobs,client,job_id,opener,binding)

def _publish_media_video(jobs,client,job_id,opener=None,binding=None):
    payload,data=prepare_media_video(jobs,client,job_id,binding)
    return _publish_prepared(jobs,client,payload,data,opener)

def _publish_prepared(jobs,client,payload,data,opener=None):
    job_id=_job_id(payload['local_job_id']);folder=_receipt_folder(jobs);path=folder/(job_id+'.json');_safe_ancestors(path)
    journal={'manifest':payload,'attempted':False,'endpoint_sha256':hashlib.sha256(client.endpoint.encode()).hexdigest()}
    if path.exists():
        saved,_=_read(path,65536)
        if saved.get('endpoint_sha256')!=journal['endpoint_sha256'] or canonical(saved.get('manifest'))!=canonical(payload):raise ValueError('media_cloud_identity_mismatch')
        journal=saved
    prepared=client.call('media_prepare',payload);aid=uid(prepared.get('artifact_id'))
    if prepared.get('manifest_hash')!=_hash(payload):raise ValueError('media_cloud_receipt_mismatch')
    try:finished=client.call('media_commit',{'artifact_id':aid})
    except CloudError as error:
        if str(error)!='media_object_missing':raise
        if journal.get('attempted') is not False:raise ValueError('media_upload_outcome_unknown') from None
        url=_url(client,prepared.get('upload_url'),'upload/sign',{'bucket_id':'crowd-machine-media','object_path':'crowd-owner-main/'+aid+'/'+payload['asset_sha256']+'.mp4'});journal={**journal,'artifact_id':aid,'attempted':True,'state':'uploading'};write(path,journal)
        request=urllib.request.Request(url,data=data,method='PUT',headers={'Content-Type':'video/mp4','Content-Length':str(len(data)),'x-upsert':'false'})
        opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        try:
            with opener.open(request,timeout=120) as response:
                if response.status not in (200,201):raise ValueError('media_upload_outcome_unknown')
                response.read(10000)
        except (OSError,ValueError,urllib.error.URLError):
            # Outcome may already be committed remotely. Inspect the same object only.
            try:finished=client.call('media_commit',{'artifact_id':aid})
            except Exception:raise ValueError('media_upload_outcome_unknown') from None
        else:finished=client.call('media_commit',{'artifact_id':aid})
    receipt=_receipt(finished,payload);write(path,{**journal,'artifact_id':aid,'state':'received','receipt':receipt})
    return {'ok':True,'receipt':receipt,'replayed':finished.get('replayed') is True,'source_requests':0,'model_calls':0}

def download_media_video(jobs,client,job_id,opener=None):
    job_id=_job_id(job_id);folder=_receipt_folder(jobs);saved,_=_read(folder/(job_id+'.json'),65536)
    if saved.get('endpoint_sha256')!=hashlib.sha256(client.endpoint.encode()).hexdigest() or saved.get('manifest',{}).get('local_job_id')!=job_id:raise ValueError('media_cloud_identity_mismatch')
    payload=saved['manifest'];receipt=_receipt({'receipt':saved.get('receipt')},payload)
    response=client.call('media_get',{'artifact_id':receipt['artifact_id']});_receipt(response,payload);url=_url(client,response.get('download_url'),'sign',receipt)
    opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(urllib.request.Request(url,headers={'Accept':'video/mp4'}),timeout=120) as stream:
            if stream.status!=200 or stream.headers.get('Content-Range'):raise ValueError('media_cloud_download_mismatch')
            data=stream.read(LIMIT+1)
    except (OSError,urllib.error.URLError):raise ValueError('media_cloud_download_failed') from None
    if len(data)!=payload['asset_bytes'] or hashlib.sha256(data).hexdigest()!=payload['asset_sha256']:raise ValueError('media_cloud_download_mismatch')
    return {'data':data,'mime':'video/mp4','sha256':payload['asset_sha256'],'receipt':receipt}


def media_video_cloud_status(jobs,client,job_id):
    job_id=_job_id(job_id);folder=_receipt_folder(jobs);path=folder/(job_id+'.json')
    if not path.exists():return {'state':'not_saved','receipt':None}
    saved,_=_read(path,65536)
    if client is None or saved.get('endpoint_sha256')!=hashlib.sha256(client.endpoint.encode()).hexdigest() or saved.get('manifest',{}).get('local_job_id')!=job_id:raise ValueError('media_cloud_identity_mismatch')
    receipt=saved.get('receipt')
    if receipt is not None:return {'state':'received','receipt':_receipt({'receipt':receipt},saved['manifest'])}
    return {'state':'outcome_unknown' if saved.get('attempted') is True else 'not_saved','receipt':None}
