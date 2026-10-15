"""Own glue: Pro content identity -> existing MC media engine, without content recrawl.
Not wired into production. Caller installs original run transport budgets first.
"""
import asyncio,re
from urllib.parse import urlsplit

class MediaContractError(ValueError):pass

def _url(value,domains):
 if not isinstance(value,str) or len(value)>4096 or any(ord(c)<=32 for c in value):raise MediaContractError('hybrid_media_url_invalid')
 try:u=urlsplit(value);port=u.port
 except ValueError:raise MediaContractError('hybrid_media_url_invalid') from None
 if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.fragment or port not in (None,80 if u.scheme=='http' else 443) or not any(u.hostname==d or u.hostname.endswith('.'+d) for d in domains):raise MediaContractError('hybrid_media_url_invalid')
 return value

def weibo_mblog(note):
 """Use persisted original Pro fields; do not invent detail or refetch content."""
 if not isinstance(note,dict) or not isinstance(note.get('note_id'),str) or not re.fullmatch('[0-9]{1,20}',note['note_id']):raise MediaContractError('hybrid_media_identity_invalid')
 images=note.get('image_list','');videos=note.get('video_url','')
 if not isinstance(images,str) or not isinstance(videos,str):raise MediaContractError('hybrid_media_shape_invalid')
 # The mature MC extractor chooses only video when present. Mixed posts need a
 # separate explicit policy; refuse rather than silently discard source images.
 if videos:raise MediaContractError('hybrid_weibo_video_not_integrated')
 urls=[_url(x.strip(),('sinaimg.cn',)) for x in images.split(',') if x.strip()]
 if not urls or len(urls)>100 or len(set(urls))!=len(urls):raise MediaContractError('hybrid_media_image_list_invalid')
 return {'id':note['note_id'],'pics':[{'url':u} for u in urls]}

async def download_weibo_images(note,media_module,downloader):
 """Run actual installed MC extractor/downloader; original image URLs stay separate.
 Downloader must be newly constructed for this run, without inherited old files.
 Return does not assert download success: caller validates original manifest/files.
 """
 mblog=weibo_mblog(note);items=media_module.build_media_items(mblog)
 if len(items)!=len(mblog['pics']) or any(str(getattr(i.media_type,'value',i.media_type))!='image' or i.content_id!=note['note_id'] for i in items):raise MediaContractError('hybrid_media_sdk_contract_changed')
 await downloader.download_all(items)
 return {'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_downloader',
         'content_id':note['note_id'],'requested_images':len(items),
         'original_urls':[p['url'] for p in mblog['pics']],
         'transport_urls':[i.url for i in items],
         'bytes_verified':False,'cloud_ack':False,'cached_asset_reuse':False}

def bili_view(note,official_response):
 """Requires SAME fresh Pro detail response View, whose cid model drops today."""
 if not isinstance(note,dict) or not isinstance(official_response,dict):raise MediaContractError('hybrid_bili_view_missing')
 view=official_response.get('View')
 if not isinstance(view,dict):raise MediaContractError('hybrid_bili_view_missing')
 def number(x):return str(x) if type(x) is int and 0<x<2**53 else x if isinstance(x,str) and re.fullmatch('[1-9][0-9]{0,15}',x) and int(x)<2**53 else None
 aid,cid=number(view.get('aid')),number(view.get('cid'));bvid=view.get('bvid')
 if not aid or not cid or not isinstance(bvid,str) or not re.fullmatch('BV[A-Za-z0-9]{10}',bvid) or aid!=note.get('video_id') or bvid!=note.get('bvid'):raise MediaContractError('hybrid_media_identity_invalid')
 if view.get('pic'):_url(view['pic'],('hdslb.com',))
 if 'duration' in view and (type(view['duration']) not in (int,float) or not 0<view['duration']<=7200):raise MediaContractError('hybrid_media_duration_invalid')
 return {'View':{k:view[k] for k in ('aid','cid','bvid','pic','duration') if k in view}}

async def download_bili(note,official_response,media_only_callback):
 """Invoke bound original MC media-only wrapper, preserving subtitle/quality policy.
 Caller supplies configured guarded crawler.download_media, never crawler.start.
 """
 view=bili_view(note,official_response)
 await media_only_callback(view,asyncio.Semaphore(1))
 return {'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only',
         'content_id':note['video_id'],'bvid':note['bvid'],'bytes_verified':False,
         'cloud_ack':False,'cached_asset_reuse':False}

def supports_request(request):
 """Candidate Bili implementation capability; caller still requires adoption gate.
 Non-long-audio transcript-only has no mature wrapper here and is rejected.
 """
 if not isinstance(request,dict) or request.get('platform')!='bili' or request.get('media') is not True:return False
 options=request.get('platform_options',{})
 if not isinstance(options,dict) or set(options)-{'quality','long_audio','transcript_only'}:return False
 if 'quality' in options and (type(options['quality']) is not int or options['quality'] not in (16,32,64,80,112,116,120,125,126,127)):return False
 if any(k in options and type(options[k]) is not bool for k in ('long_audio','transcript_only')):return False
 if options.get('transcript_only') and options.get('long_audio') is not True:return False
 return True

def capabilities():
 return {'production_ready':False,'bili_media_only':'candidate_implemented_requires_independent_review_and_adoption',
         'wb_images':'offline_glue_only','bili_quality16':'original_native_wrapper',
         'bili_long_audio':'original_native_wrapper','bili_transcript_only':'subtitle_first_when_long_audio_true',
         'reason':'not_adopted_or_formally_routed'}
