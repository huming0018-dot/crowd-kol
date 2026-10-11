"""Bounded audio-only download from one existing native Bilibili DASH response."""
from contextvars import ContextVar
import hashlib
import math
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

from tieba_media import safe_directory

MAX_AUDIO_BYTES=64*1024*1024
MAX_DURATION_SECONDS=7200
AUDIO_RESPONSE_ACTIVE=ContextVar('crowd_bili_audio_response',default=False)


def public_audio_url(value):
    if not isinstance(value,str) or len(value)>4000:return None
    try:
        parsed=urlsplit(value);host=parsed.hostname or ''
        if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port or parsed.fragment:return None
        if not any(host==domain or host.endswith('.'+domain) for domain in ('bilivideo.com','bilivideo.cn','akamaized.net')):return None
        return value
    except ValueError:return None


def select_audio(play_info,duration_seconds=None):
    if not isinstance(play_info,dict):raise ValueError('audio_play_response_invalid')
    dash=play_info.get('dash')
    if not isinstance(dash,dict):raise ValueError('dash_audio_unavailable')
    if duration_seconds is None:duration_seconds=dash.get('duration')
    if type(duration_seconds) not in (int,float) or not math.isfinite(duration_seconds) or not 0<duration_seconds<=MAX_DURATION_SECONDS:raise ValueError('audio_duration_unverified_or_over_limit')
    selected=[]
    for row in dash.get('audio',[]) if isinstance(dash.get('audio'),list) else []:
        if not isinstance(row,dict):continue
        rate=row.get('bandwidth');url=public_audio_url(row.get('baseUrl') or row.get('base_url'))
        if type(rate) is int and rate>0 and url:selected.append((rate,url))
    if not selected:raise ValueError('dash_audio_unavailable')
    rate,url=min(selected,key=lambda row:row[0])
    if math.ceil(duration_seconds*rate/8)>MAX_AUDIO_BYTES:raise ValueError('audio_estimated_size_over_limit')
    return {'url':url,'bandwidth_reported':rate,'duration_seconds_reported':duration_seconds}


async def download_audio(play_info,content_id,output_dir,duration_seconds=None,client=None):
    if not isinstance(content_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,200}',content_id):raise ValueError('audio_content_id_invalid')
    folder=safe_directory(Path(output_dir)/'bili/media'/content_id)
    try:stream=select_audio(play_info,duration_seconds)
    except ValueError as error:return {'status':'unavailable','reason':str(error),'kind':'audio','content_id':content_id}
    if client is None:
        import httpx
        async with httpx.AsyncClient(timeout=30,follow_redirects=False,trust_env=False) as own:
            return await download_audio(play_info,content_id,output_dir,duration_seconds,own)
    target=folder/'audio.m4a';temporary=folder/('.audio-'+secrets.token_hex(8))
    if target.exists() or target.is_symlink():raise ValueError('audio_asset_already_exists')
    try:
        async with client.stream('GET',stream['url'],headers={'Referer':'https://www.bilibili.com/'}) as response:
            if response.status_code!=200:raise ValueError('audio_http_status')
            size=0;head=b'';digest=hashlib.sha256();token=AUDIO_RESPONSE_ACTIVE.set(True)
            try:
                with os.fdopen(os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600),'wb') as file:
                    async for chunk in response.aiter_bytes(65536):
                        size+=len(chunk)
                        if size>MAX_AUDIO_BYTES:raise ValueError('audio_single_file_size_limit')
                        head=(head+chunk)[:16];digest.update(chunk);file.write(chunk)
            finally:AUDIO_RESPONSE_ACTIVE.reset(token)
            if size<12 or head[4:8]!=b'ftyp':raise ValueError('audio_container_not_mp4')
        os.replace(temporary,target)
        return {'status':'downloaded','kind':'audio','content_id':content_id,'path':str(target),'bytes':size,'sha256':digest.hexdigest(),
                'duration_seconds_reported':stream['duration_seconds_reported'],'bandwidth_reported':stream['bandwidth_reported'],
                'single_file_limit_bytes':MAX_AUDIO_BYTES,'credentials_used':False,'source':'same_native_bilibili_dash_response'}
    except ValueError as error:
        reason=str(error) if str(error) in ('audio_http_status','audio_single_file_size_limit','audio_container_not_mp4') else 'audio_download_failed'
        return {'status':'limited' if 'size_limit' in reason else 'failed','reason':reason,'kind':'audio','content_id':content_id}
    except Exception:return {'status':'failed','reason':'audio_download_failed','kind':'audio','content_id':content_id}
    finally:temporary.unlink(missing_ok=True)
