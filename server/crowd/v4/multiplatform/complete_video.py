"""Explicit one-download video processing, separate from collector budgets."""
import argparse
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

INPUT_LIMIT=256*1024*1024
OUTPUT_LIMIT=64*1024*1024
MAX_SECONDS=7200
TIMEOUT=900
MAX_REQUESTS=4
HOSTS=('douyinvod.com','douyincdn.com','bytecdn.cn','ibytedtos.com','pstatp.com')
ERROR_CODES={'video_source_url_denied','unsafe_complete_video_path','complete_video_existing_asset','complete_video_cancelled','complete_video_timeout','video_redirect_limit','video_source_http_error','video_source_network_error','video_source_length_invalid','video_source_input_limit','video_source_incomplete','video_ffmpeg_unavailable','video_decode_failed','video_duration_unavailable','video_duration_limit','video_output_duration_mismatch','complete_video_failed'}

def safe_url(value):
    if not isinstance(value,str) or len(value)>4096 or any(ord(c)<32 for c in value):raise ValueError('video_source_url_denied')
    try:u=urllib.parse.urlsplit(value);port=u.port
    except ValueError:raise ValueError('video_source_url_denied') from None
    if u.scheme!='https' or u.username is not None or u.password is not None or port not in (None,443) or u.fragment or not u.hostname or not (u.hostname=='www.douyin.com' or any(u.hostname==host or u.hostname.endswith('.'+host) for host in HOSTS)):
        raise ValueError('video_source_url_denied')
    return value

def safe_folder(folder):
    folder=Path(folder)
    if any(p.is_symlink() for p in (folder,*folder.parents)) or not folder.is_dir():raise ValueError('unsafe_complete_video_path')
    return folder

def read_bytes(path,limit):
    path=Path(path);safe_folder(path.parent)
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>limit:raise ValueError('unsafe_complete_video_path')
        value=stream.read(limit+1)
    if len(value)>limit:raise ValueError('video_source_reference_limit')
    return value

def atomic_json(path,value):
    path=Path(path);safe_folder(path.parent)
    if path.is_symlink():raise ValueError('unsafe_complete_video_path')
    temp=path.parent/('tmp-'+uuid.uuid4().hex)
    try:
        with os.fdopen(os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
            json.dump(value,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)

def source_reference(run,run_id,content_id):
    if str(uuid.UUID(run_id))!=run_id or not isinstance(content_id,str) or not re.fullmatch(r'[0-9]{1,30}',content_id):raise ValueError('invalid_video_source_identity')
    run=safe_folder(run);output=safe_folder(run/'output'/'douyin'/'jsonl');matches=[]
    files=list(itertools.islice(output.glob('*contents*.jsonl'),33))
    if len(files)>32:raise ValueError('video_source_reference_limit')
    for path in sorted(files):
        data=read_bytes(path,10*1024*1024)
        for index,line in enumerate(data.splitlines(),1):
            if not line.strip():continue
            row=json.loads(line)
            if not isinstance(row,dict):raise ValueError('invalid_video_source_record')
            if str(row.get('aweme_id'))==content_id:
                url=safe_url(row.get('video_download_url'));matches.append((url,hashlib.sha256(data).hexdigest(),index))
    if not matches or len({m[0] for m in matches})!=1:raise ValueError('video_source_reference_ambiguous_or_missing')
    url,file_hash,row=matches[0]
    identity={'run_id':run_id,'platform':'douyin','content_id':content_id,'source_file_sha256':file_hash,'source_record_index':row,'url_sha256':hashlib.sha256(url.encode()).hexdigest()}
    native=run/'output'/'douyin'/'video-references'/(content_id+'.json')
    if native.exists() or native.is_symlink():
        data=read_bytes(native,10000);saved=json.loads(data)
        if native.stat().st_mode & 0o777!=0o600 or set(saved)!={'schema_version','run_id','platform','content_id','source_kind','reported_bytes','reported_bitrate','url'} or type(saved['schema_version']) is not int or saved['schema_version']!=1 or saved['run_id']!=run_id or saved['platform']!='douyin' or saved['content_id']!=content_id or saved['source_kind']!='same_native_aweme_detail' or type(saved['reported_bytes']) is not int or not 0<saved['reported_bytes']<=INPUT_LIMIT or saved['reported_bitrate'] is not None and (type(saved['reported_bitrate']) is not int or not 0<saved['reported_bitrate']<=10**12):
            raise ValueError('video_reference_identity_mismatch')
        url=safe_url(saved['url']);identity.update(url_sha256=hashlib.sha256(url.encode()).hexdigest(),native_reference_sha256=hashlib.sha256(data).hexdigest(),reported_bytes=saved['reported_bytes'],source_reference_kind='same_native_aweme_detail_lower_rendition')
    elif (run/'phase.json').is_file():
        phase=json.loads(read_bytes(run/'phase.json',100000));catalog=phase.get('media_processing_reference')
        if isinstance(catalog,dict) and catalog.get('state')=='no_fitting_processing_rendition':raise ValueError('video_source_no_fitting_processing_rendition')
        if isinstance(catalog,dict):raise ValueError('video_processing_reference_unavailable')
    reference_hash=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    return {**identity,'reference_sha256':reference_hash,'url':url}

def public_reference(ref):
    return {k:v for k,v in ref.items() if k!='url'}|{'source_kind':'saved_native_video_reference','network_input_limit_bytes':INPUT_LIMIT,'output_limit_bytes':OUTPUT_LIMIT,'max_request_attempts':MAX_REQUESTS,'max_duration_seconds':MAX_SECONDS,'timeout_seconds':TIMEOUT,'collection_budget_changed':False,'model_calls':0}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def run(reference,folder,opener=None):
    folder=safe_folder(folder);safe_url(reference['url'])
    for name in ('source.mp4','source.part','video.mp4','video.partial.mp4'):
        if (folder/name).exists() or (folder/name).is_symlink():raise ValueError('complete_video_existing_asset')
    started=time.monotonic();attempts=0;downloaded=0
    def check():
        if (folder/'cancel.requested').exists():raise ValueError('complete_video_cancelled')
        if time.monotonic()-started>TIMEOUT:raise ValueError('complete_video_timeout')
    def progress(phase,**fields):
        atomic_json(folder/'video-progress.json',{'phase':phase,'network_attempts':attempts,'downloaded_bytes':downloaded,**fields})
    opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    url=reference['url'];response=None
    for redirect in range(MAX_REQUESTS):
        check();attempts+=1;progress('downloading_video')
        request=urllib.request.Request(safe_url(url),headers={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36','Referer':'https://www.douyin.com/'})
        try:response=opener.open(request,timeout=20)
        except urllib.error.HTTPError as error:
            if error.code in (301,302,303,307,308):
                location=error.headers.get('Location');error.close()
                if not location or redirect==MAX_REQUESTS-1:raise ValueError('video_redirect_limit') from None
                url=safe_url(urllib.parse.urljoin(url,location));continue
            raise ValueError('video_source_http_error') from None
        except (OSError,urllib.error.URLError):raise ValueError('video_source_network_error') from None
        break
    if response is None:raise ValueError('video_redirect_limit')
    part=folder/'source.part';digest=hashlib.sha256()
    with response:
        if getattr(response,'status',200)!=200 or response.headers.get('Content-Range'):raise ValueError('video_source_http_error')
        length=response.headers.get('Content-Length');declared=None
        if length is not None:
            if not re.fullmatch(r'[0-9]{1,10}',length):raise ValueError('video_source_length_invalid')
            declared=int(length)
            if declared>INPUT_LIMIT:raise ValueError('video_source_input_limit')
        with os.fdopen(os.open(part,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as stream:
            while True:
                check()
                try:chunk=response.read(128*1024)
                except (OSError,urllib.error.URLError):raise ValueError('video_source_network_error') from None
                if not chunk:break
                downloaded+=len(chunk)
                if downloaded>INPUT_LIMIT:raise ValueError('video_source_input_limit')
                digest.update(chunk);stream.write(chunk);progress('downloading_video')
            stream.flush();os.fsync(stream.fileno())
        if not downloaded or declared is not None and declared!=downloaded:raise ValueError('video_source_incomplete')
    os.replace(part,folder/'source.mp4');progress('checking_source_video',source_sha256=digest.hexdigest())
    ffmpeg=os.environ.get('CROWD_FFMPEG') or shutil.which('ffmpeg')
    if not ffmpeg or not Path(ffmpeg).is_file():raise ValueError('video_ffmpeg_unavailable')
    def process(args,probe=False):
        check()
        with subprocess.Popen([ffmpeg,*args],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,umask=0o077) as proc:
            try:
                while True:
                    check()
                    try:_,error=proc.communicate(timeout=.2);break
                    except subprocess.TimeoutExpired:continue
            except BaseException:
                proc.kill();proc.wait();raise
        if len(error)>1024*1024:raise ValueError('video_decode_failed')
        if not probe and proc.returncode:raise ValueError('video_decode_failed')
        return error.decode('utf8',errors='replace')
    def duration(path):
        info=process(['-hide_banner','-protocol_whitelist','file,pipe','-f','mov','-i',str(path)],probe=True)
        matched=re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)',info)
        if not matched:raise ValueError('video_duration_unavailable')
        value=int(matched[1])*3600+int(matched[2])*60+float(matched[3])
        if not math.isfinite(value) or not 0<value<=MAX_SECONDS:raise ValueError('video_duration_limit')
        return value
    original_duration=duration(folder/'source.mp4')
    process(['-v','error','-xerror','-protocol_whitelist','file,pipe','-f','mov','-i',str(folder/'source.mp4'),'-map','0:v:0','-map','0:a?','-f','null','-'])
    progress('transcoding_video',source_duration_seconds=original_duration,source_sha256=digest.hexdigest())
    bitrate=max(32000,min(2500000,int(OUTPUT_LIMIT*8*.80/original_duration)-24000))
    process(['-v','error','-xerror','-protocol_whitelist','file,pipe','-f','mov','-i',str(folder/'source.mp4'),'-map','0:v:0','-map','0:a:0?','-vf','scale=-2:min(480\\,ih)','-c:v','libx264','-preset','veryfast','-b:v',str(bitrate),'-maxrate',str(bitrate),'-bufsize',str(bitrate*2),'-pix_fmt','yuv420p','-c:a','aac','-b:a','24000','-movflags','+faststart','-fs',str(OUTPUT_LIMIT),'-f','mp4',str(folder/'video.partial.mp4')])
    output=folder/'video.partial.mp4';data=read_bytes(output,OUTPUT_LIMIT)
    output_duration=duration(output)
    if abs(output_duration-original_duration)>.25:raise ValueError('video_output_duration_mismatch')
    progress('checking_complete_output',source_duration_seconds=original_duration,output_duration_seconds=output_duration)
    process(['-v','error','-xerror','-protocol_whitelist','file,pipe','-f','mov','-i',str(output),'-map','0:v:0','-map','0:a?','-f','null','-'])
    os.replace(output,folder/'video.mp4')
    return [{'kind':'processed_video','platform':reference['platform'],'content_id':reference['content_id'],'evidence':{'source_kind':'authorized_saved_video_reference','source_run_id':reference['run_id'],'source_reference_sha256':reference['reference_sha256'],'source_file_sha256':reference['source_file_sha256'],'source_asset_sha256':digest.hexdigest(),'source_bytes':downloaded,'asset_sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'duration_seconds':output_duration,'source_duration_seconds':original_duration,'full_source_decode':True,'full_output_decode':True,'network_attempts':attempts,'input_limit_bytes':INPUT_LIMIT,'output_limit_bytes':OUTPUT_LIMIT,'collection_budget_changed':False,'processor':'bounded_public_video_download_ffmpeg','model_calls':0,'semantic_review':'not_reviewed','derivative':True}}]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--reference',required=True);parser.add_argument('--reference-file-sha256',required=True);args=parser.parse_args()
    path=Path(args.reference);folder=safe_folder(path.parent);data=read_bytes(path,10000)
    if hashlib.sha256(data).hexdigest()!=args.reference_file_sha256:raise ValueError('video_reference_changed')
    reference=json.loads(data)
    try:atomic_json(folder/'result.json',run(reference,folder))
    except Exception as error:
        atomic_json(folder/'video-error.json',{'reason':str(error) if type(error) is ValueError and str(error) in ERROR_CODES else 'complete_video_failed'})
        raise SystemExit(1)

if __name__=='__main__':main()
