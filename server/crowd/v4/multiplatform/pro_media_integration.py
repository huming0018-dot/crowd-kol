"""Own Pro-content/native-MC-media glue. Credentials remain in process memory."""
import hashlib,time
from pathlib import Path
from pro_media_parent import BiliDetailObserver,run_media_child

class MediaStage:
 def __init__(self,request):
  self.enabled=request.get('source_executor')=='pro' and request.get('media') is True
  self.view=BiliDetailObserver();self.headers={};self.bili_wbi=None;self.dy_sources={}
 def observe(self,response):
  if not self.enabled:return
  from urllib.parse import urlsplit
  u=urlsplit(str(response.request.url))
  if u.hostname=='www.douyin.com' and u.path=='/aweme/v1/web/aweme/detail/' and response.status_code==200:
   data=response.json()
   if type(data) is dict and type(data.get('status_code')) is int and data['status_code']==0 and type(data.get('aweme_detail')) is dict:
    raw=data['aweme_detail'];key=raw.get('aweme_id');source={k:raw.get(k) for k in ('aweme_id','images','video')}
    if type(key) is str:
     if key in self.dy_sources and self.dy_sources[key]!=source:raise ValueError('hybrid_douyin_source_changed')
     self.dy_sources[key]=source
  if u.hostname=='www.douyin.com' and u.path=='/aweme/v1/web/module/feed/' and response.status_code==200:
   data=response.json()
   if type(data) is dict and type(data.get('StatusCode')) is int and data['StatusCode']==0:
    import json
    for card in data.get('cards',[]):
     if type(card) is dict and card.get('type')==1 and type(card.get('aweme')) is str:
      raw=json.loads(card['aweme']);key=raw.get('aweme_id')
      if type(key) is str:self.dy_sources[key]={k:raw.get(k) for k in ('aweme_id','images','video')};break
  self.view.observe(response)
  # Only retain headers from the exact accepted, already-issued official View.
  try:
   data=response.json()
   if response.status_code!=200 or not isinstance(data,dict) or type(data.get('code')) is not int or data['code']!=0:return
   raw=data['data'];row=raw.get('View',raw)
   bvid=row.get('bvid')
   if self.view.views.get(bvid) is None:return
   from urllib.parse import urlsplit
   u=urlsplit(str(response.request.url))
   if u.scheme!='https' or u.hostname!='api.bilibili.com' or u.path not in ('/x/web-interface/view','/x/web-interface/view/detail') or u.username or u.password or u.port not in (None,443) or u.fragment:return
   h=response.request.headers
   safe={k:h[k] for k in ('Cookie','User-Agent','Referer') if k in h}
   if any(not isinstance(v,str) or '\r' in v or '\n' in v or len(v)>65536 for v in safe.values()):raise ValueError('hybrid_media_headers_invalid')
   self.headers[bvid]=safe
  except (KeyError,TypeError,AttributeError,ValueError):return
 def run(self,run,manifest,rows,*,mc_root,remaining):
  if not self.enabled:return None
  from pro_hybrid_media import supports_request
  tieba=(manifest['request'].get('platform')=='tieba' and manifest['request'].get('mode')=='detail' and manifest['request'].get('max_items')==1 and manifest['request'].get('platform_options',{})=={})
  from pro_douyin_entry import supports as supports_dy
  if not (supports_request(manifest['request']) or tieba or supports_dy(manifest['request'])) or mc_root is None:raise ValueError('hybrid_media_runtime_unavailable')
  topics=[row for kind,entity,row in rows if kind=='topic']
  # The present child owns one fresh output/dispatch intent, so no implicit fanout.
  if len(topics)!=1 or manifest['request']['max_items']!=1:raise ValueError('hybrid_media_single_content_required')
  note=topics[0]
  if manifest['request'].get('platform')=='dy':
   from shared_request_budget import canonical
   from mc_runner import write
   source=self.dy_sources.get(note.get('aweme_id'))
   if source is None:raise ValueError('hybrid_douyin_source_missing')
   view={'run_id':manifest['run_id'],'observation_sha256':hashlib.sha256(canonical(note).encode()).hexdigest(),'source':source};headers={}
   write(Path(run)/'dy-media-source.json',view)
  elif manifest['request'].get('platform')=='tieba':
   from pro_tieba_entry import read_json
   from pro_tieba_adapter import digest
   source=read_json(Path(run)/'tieba-media-source.json');note={'note_id':note['note_id']};view={'tieba_source_sha256':digest(source)};headers={}
  elif manifest['request'].get('platform')=='wb':
   from pro_hybrid_media import weibo_mblog
   from shared_request_budget import canonical
   weibo_mblog(note)
   view={'weibo_observation_sha256':hashlib.sha256(canonical(note).encode()).hexdigest()};headers={}
  else:
   view=self.view.response_for(note);headers=self.headers.get(note.get('bvid'))
   if headers is None:raise ValueError('hybrid_media_headers_unavailable')
  if remaining<=0:raise SystemExit(80)
  mc_root=Path(mc_root);python=mc_root/'.venv/bin/python'
  if not mc_root.is_absolute() or not mc_root.is_dir() or not python.is_file():raise ValueError('hybrid_media_runtime_unavailable')
  import shared_request_budget
  context=self.bili_wbi.media_context() if self.bili_wbi is not None else None
  result=run_media_child(run,note,view,headers,python=python,mc_root=mc_root,wbi_context=context,
   runtime_root=Path(__file__).parent,budget_module_root=Path(shared_request_budget.__file__).parent,timeout=remaining)
  if result.get('state')!='completed':raise ValueError('hybrid_media_partial')
  return result

def summary(run,manifest):
 from analysis_artifact import _read
 from shared_request_budget import request_fingerprint
 path=Path(run)/'hybrid-media-result.json'
 if not path.exists():return None
 value=_read(path,1048576)[0]
 if not isinstance(value,dict) or type(value.get('schema_version')) is not int or value.get('schema_version')!=1 or type(value.get('api_attempts')) is not int or not 0<=value['api_attempts']<=manifest['request']['max_api_requests'] or value.get('run_id')!=manifest['run_id'] or value.get('request_hash')!=request_fingerprint(manifest['request']) or value.get('state') not in ('completed','partial') or value.get('cloud_ack') is not False or value.get('content_engine')!='mediacrawler_pro' or value.get('media_engine')!='native_mc_media_only' or not isinstance(value.get('assets'),list):raise ValueError('hybrid_media_result_binding_invalid')
 if manifest['request'].get('platform')=='wb':
  from pro_executor import observations
  from wb_media_child import verify_assets
  from shared_request_budget import canonical
  topics=[row for kind,entity,row in observations(Path(run),manifest) if kind=='topic']
  if len(topics)!=1:raise ValueError('hybrid_media_single_content_required')
  checked=verify_assets(Path(run),topics[0])
  from pro_hybrid_media import weibo_image_plan
  from shared_request_budget import RunRequestBudget
  complete=len(checked)==len(weibo_image_plan(topics[0]))
  ledger=RunRequestBudget(Path(run)/'request-budget.json',manifest['run_id'],request_fingerprint(manifest['request']),manifest['request']['max_api_requests'])
  if (canonical(checked)!=canonical(value['assets']) or value['state']!=('completed' if complete else 'partial')
      or value.get('subtitle_available') is not False or value['api_attempts']!=ledger.snapshot()['used']):raise ValueError('hybrid_weibo_asset_mismatch')
 return value

def annotate_import(run,manifest,media):
 """Bind actual scanner readback to same-run child result, without source mutations."""
 result=summary(run,manifest)
 if result is None:return
 expected=result['assets'];paths=set()
 from cloud_sync import canonical
 fields=(('path','bytes','sha256','platform','content_id') if manifest['request'].get('platform') in ('wb','tieba','dy') else ('path','bytes','sha256','platform','content_id','source_media_id','bilibili_view_cid','bilibili_media_identity_sha256'))
 for asset in expected:
  if not isinstance(asset,dict) or asset.get('path') in paths:raise ValueError('hybrid_media_result_binding_invalid')
  paths.add(asset.get('path'))
  matches=[m for m in media if m.get('path')==asset.get('path')]
  if len(matches)!=1:raise ValueError('hybrid_media_asset_missing')
  item=matches[0]
  if any(canonical(item.get(k))!=canonical(asset.get(k)) for k in fields) or item.get('source_kind')!='mediacrawler_api' or item.get('reward_eligible') is not False or asset.get('source_kind')!='mediacrawler_api' or asset.get('reward_eligible') is not False or asset.get('content_engine')!='mediacrawler_pro' or asset.get('media_engine')!='native_mc_media_only':raise ValueError('hybrid_media_asset_mismatch')
  suffix=Path(asset['path']).suffix
  kind='audio' if suffix=='.m4a' else 'video' if suffix=='.mp4' else 'image'
  if asset.get('kind')!=kind:raise ValueError('hybrid_media_asset_mismatch')
  item.update(kind=kind,status='downloaded_by_hybrid_media_executor',content_engine='mediacrawler_pro',media_engine='native_mc_media_only')
  if manifest['request'].get('platform')=='wb':
   item.update({key:asset[key] for key in ('source_media_id','original_url','transport_url','image_index','weibo_observation_sha256','width','height','rgba_sha256')})
 # No unchecked file may get silently attributed to this hybrid child.
 if any(m.get('path') not in paths for m in media if m.get('path')):raise ValueError('hybrid_media_unregistered_asset')
