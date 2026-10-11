"""Download public post media from the same native Tieba response, without cookies."""
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit, urlunsplit, parse_qsl

MAX_FILE=25*1024*1024
MAX_TOTAL=50*1024*1024
MAX_ASSETS=3
HOSTS={'tiebapic.baidu.com','imgsrc.baidu.com','imgsa.baidu.com','tb-video.bdstatic.com'}

def asset_url(value):
    if not isinstance(value,str) or len(value)>2000:return None
    if value.startswith('//'):value='https:'+value
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in ('http','https') or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port or parsed.fragment:return None
        if any(re.search(r'(?i)(token|cookie|authorization|credential|session|password|secret|x-amz)',k) for k,v in parse_qsl(parsed.query)):return None
        return urlunsplit(('https',parsed.netloc,parsed.path,parsed.query,''))
    except ValueError:return None

class PostImages(HTMLParser):
    def __init__(self):super().__init__();self.stack=[];self.urls=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);inside=any(self.stack) or any(x in attrs.get('class','').split() for x in ('d_post_content','j_d_post_content'))
        if tag not in ('img','br','hr','meta','input','source','link'):self.stack.append(inside)
        if inside and tag in ('img','source','video'):
            value=next((asset_url(attrs[k]) for k in ('data-original','data-src','src') if k in attrs and asset_url(attrs[k])),None)
            if value and value not in self.urls:self.urls.append(value)
    def handle_endtag(self,tag):
        if self.stack:self.stack.pop()

def extract_assets(data):
    if not isinstance(data,dict):return []
    posts=[data.get('first_floor') or {}]+(data.get('post_list') or [])
    assets=[];seen=set()
    for post in posts[:50]:
        if not isinstance(post,dict):continue
        content=post.get('content') or []
        if isinstance(content,str):
            parser=PostImages();parser.feed('<div class="d_post_content">'+content[:2_000_000]+'</div>')
            rows=[{'src':url} for url in parser.urls]
        elif isinstance(content,list):rows=content[:500]
        else:continue
        for item in rows:
            if not isinstance(item,dict):continue
            url=next((asset_url(item[k]) for k in ('origin_src','big_cdn_src','big_src','cdn_src','src','video_url') if k in item and asset_url(item[k])),None)
            if not url or url in seen:continue
            seen.add(url);assets.append({'url':url,'source_post_id':str(post.get('id') or post.get('pid') or '')[:100]})
            if len(assets)==MAX_ASSETS:return assets
    return assets

def media_type(head):
    if head[:3]==b'\xff\xd8\xff':return 'jpg'
    if head[:8]==b'\x89PNG\r\n\x1a\n':return 'png'
    if head[:6] in (b'GIF87a',b'GIF89a'):return 'gif'
    if head[:4]==b'RIFF' and head[8:12]==b'WEBP':return 'webp'
    if head[4:8]==b'ftyp':return 'mp4'
    raise ValueError('tieba_asset_not_media')

def safe_directory(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in [path,*path.parents]):raise ValueError('tieba_media_symlink')
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    return path

async def download_assets(data,note_id,output_dir,client=None,*,platform='tieba',extractor=None,content_type=None):
    if platform not in ('tieba','zhihu'):raise ValueError('public_media_platform_invalid')
    if platform=='zhihu' and not callable(extractor):raise ValueError('zhihu_media_extractor_required')
    if platform=='zhihu' and content_type not in ('answer','article','zvideo'):raise ValueError('zhihu_content_type_invalid')
    if not isinstance(note_id,str) or not re.fullmatch('[0-9]{1,24}' if platform=='tieba' else '[0-9]{1,30}',note_id):raise ValueError('invalid_'+platform+'_note_id')
    folder=safe_directory(Path(output_dir)/platform/'media'/note_id)
    if platform=='zhihu':folder=safe_directory(folder/content_type)
    downloaded=[];errors=[];total=0
    try:
        assets=(extractor or extract_assets)(data)
        if not isinstance(assets,list):raise ValueError(platform+'_asset_extraction_failed')
        assets=assets[:MAX_ASSETS]
    except ValueError as error:
        code=str(error);errors.append(code if re.fullmatch('[a-z0-9_]{1,100}',code) else platform+'_asset_extraction_failed');assets=[]
    except Exception:errors.append(platform+'_asset_extraction_failed');assets=[]
    if client is None:
        import httpx
        async with httpx.AsyncClient(timeout=12,follow_redirects=False,trust_env=False) as own:
            return await download_assets(data,note_id,output_dir,own,platform=platform,extractor=extractor,content_type=content_type)
    validator=asset_url
    if platform=='zhihu':
        from zhihu_media import asset_url as validator
    for index,asset in enumerate(assets,1):
        temporary=folder/('.part-'+secrets.token_hex(8))
        try:
            url=validator(asset.get('url')) if isinstance(asset,dict) else None
            if not url:raise ValueError(platform+'_asset_url_rejected')
            if platform=='zhihu' and asset.get('source_content_type')!=content_type:raise ValueError('zhihu_asset_type_mismatch')
            referer='https://tieba.baidu.com/p/'+note_id if platform=='tieba' else 'https://www.zhihu.com/'
            async with client.stream('GET',url,headers={'Referer':referer}) as response:
                if response.status_code!=200:raise ValueError(platform+'_asset_http_status')
                size=0;head=b'';digest=hashlib.sha256()
                with os.fdopen(os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600),'wb') as stream:
                    async for chunk in response.aiter_bytes(65536):
                        size+=len(chunk);total+=len(chunk)
                        if size>MAX_FILE or total>MAX_TOTAL:raise ValueError(platform+'_media_size_limit')
                        head=(head+chunk)[:16];digest.update(chunk);stream.write(chunk)
                try:extension=media_type(head)
                except ValueError:raise ValueError(platform+'_asset_not_media') from None
                target=folder/('%03d.%s'%(index,extension))
                if target.exists() or target.is_symlink():raise ValueError(platform+'_asset_already_exists')
                os.replace(temporary,target)
                downloaded.append({'content_id':note_id,'path':str(target),'sha256':digest.hexdigest(),'bytes':size,
                                   'type':extension,'source_post_id':asset['source_post_id'],'status':'downloaded_public_post_asset',
                                   **({'source_content_type':asset.get('source_content_type')} if platform=='zhihu' else {})})
        except ValueError as error:errors.append(str(error))
        except Exception:errors.append(platform+'_asset_download_failed')
        finally:
            if temporary.exists():temporary.unlink()
    evidence={'content_id':note_id,'assets_found':len(assets),'downloaded':downloaded,'errors':errors,
              'source':'same_native_tieba_page_response' if platform=='tieba' else 'same_native_zhihu_response',
              **({'source_content_type':content_type} if platform=='zhihu' else {}),
              'credentials_used':False,'coverage':'observed_post_assets_only' if platform=='tieba' else 'observed_body_assets_only'}
    manifest=folder/'assets.json'
    if manifest.is_symlink():raise ValueError('tieba_media_symlink')
    temporary=folder/('.manifest-'+secrets.token_hex(8))
    try:
        with os.fdopen(os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600),'w',encoding='utf8') as stream:
            stream.write(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
        os.replace(temporary,manifest)
    finally:
        if temporary.exists():temporary.unlink()
    return evidence

def install_hook(client_class,output_dir):
    original=client_class._get_pc_page_data
    seen=set()
    async def wrapped(self,note_id,page=1):
        data=await original(self,note_id,page)
        if page==1 and note_id not in seen:
            seen.add(note_id)
            await download_assets(data,str(note_id),output_dir)
        return data
    client_class._get_pc_page_data=wrapped
