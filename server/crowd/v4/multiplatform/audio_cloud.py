"""Honest Pro-collected M4A cloud schema; reuses existing journal/RPC lifecycle."""
import hashlib,json,re,uuid
from cloud_sync import canonical
from mc_runner import canonical as source_canonical
from media_cloud import _job_id,_job_lock,_publish_prepared,download_media_video,media_video_cloud_status

HEX=re.compile('[a-f0-9]{64}')
AUDIO_FIELDS={'idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','platform','content_id','capture_id','envelope_hash','asset_sha256','asset_bytes','duration_ms','source_duration_ms','source_asset_sha256','source_observation_sha256','source_reference_sha256','result_file_sha256','manifest_version','representation','completeness','content_kind','content_type','entity_ref','container','video_track_present','source_record_hash','audio_track_present','content_mime','source_record_canonical'}
def sha(value):return hashlib.sha256((value if isinstance(value,bytes) else canonical(value).encode())).hexdigest()

def validate_audio_manifest(value):
 if not isinstance(value,dict) or set(value)!=AUDIO_FIELDS:raise ValueError('invalid_audio_manifest')
 for k in ('task_id','child_id','run_id','local_run_id','local_job_id','capture_id'):
  if not isinstance(value[k],str) or _job_id(value[k])!=value[k]:raise ValueError('invalid_audio_manifest')
 if type(value['manifest_version']) is not int or value['manifest_version']!=3 or value['idempotency_key']!='audio:'+value['local_job_id'] or value['platform']!='bilibili' or value['content_kind']!='content' or value['content_type'] is not None or value['entity_ref']!='bilibili:content:'+str(value['content_id']) or value['representation']!='pro_collected_audio' or value['completeness']!='saved_asset_not_full_length_verified' or value['container']!='m4a' or value['content_mime']!='audio/mp4' or value['audio_track_present'] is not True or value['video_track_present'] is not False:raise ValueError('invalid_audio_manifest')
 if not isinstance(value['content_id'],str) or not re.fullmatch('[1-9][0-9]{0,19}',value['content_id']):raise ValueError('invalid_audio_manifest')
 for k in ('envelope_hash','asset_sha256','source_asset_sha256','source_observation_sha256','source_reference_sha256','result_file_sha256','source_record_hash'):
  if not isinstance(value[k],str) or not HEX.fullmatch(value[k]):raise ValueError('invalid_audio_manifest')
 if any(type(value[k]) is not int for k in ('lease_epoch','asset_bytes','duration_ms','source_duration_ms')) or not 1<=value['lease_epoch']<=2147483647 or not 1<=value['asset_bytes']<=50*1024*1024 or not 1<=value['duration_ms']<=7200000 or value['duration_ms']!=value['source_duration_ms'] or value['source_asset_sha256']!=value['asset_sha256']:raise ValueError('invalid_audio_manifest')
 text=value['source_record_canonical']
 try:
  if not isinstance(text,str) or len(text.encode())>128*1024:raise ValueError()
  source=json.loads(text)
  if not isinstance(source,dict) or 'record_hash' in source or source_canonical(source)!=text or hashlib.sha256(text.encode()).hexdigest()!=value['source_record_hash'] or source.get('platform')!='bilibili' or source.get('kind')!='content' or source.get('content_id')!=value['content_id']:raise ValueError()
  origin=source.get('origin',{})
  if not isinstance(origin,dict) or origin.get('run_id')!=value['local_run_id'] or origin.get('operation_id')!=value['local_run_id'] or origin.get('executor')!='mediacrawler_pro' or origin.get('observation_sha256')!=value['source_observation_sha256']:raise ValueError()
 except (ValueError,TypeError,RecursionError):raise ValueError('invalid_audio_manifest') from None
 return {'manifest_hash':hashlib.sha256(('crowd-media-audio-v3\n'+canonical(value)).encode()).hexdigest()}

def _same_record(body,record,source_hash):
 if not isinstance(record,dict):return False
 strip=lambda row:{k:v for k,v in row.items() if k not in ('record_hash','author_id')}
 if canonical(strip(body))!=canonical(strip(record)) or ('record_hash' in record and record['record_hash']!=source_hash):return False
 if 'author_id' in body:
  return 'author_id' in record and canonical(body['author_id'])==canonical(record['author_id'])
 if 'author_id' in record:
  author=body.get('author')
  return isinstance(author,dict) and 'author_id' in author and canonical(author['author_id'])==canonical(record['author_id'])
 return True

def prepare_native_audio(jobs,client,run_folder,content_id,asset_sha256,entity_ref=None,binding=None):
 from media_native import _identity,_duration
 if client is None or getattr(client,'role',None) not in ('owner','worker'):raise ValueError('principal_denied')
 _,identity,body,item,normalized_sha,data=_identity(run_folder,content_id,asset_sha256,entity_ref,native_audio=True)
 origin=body.get('origin',{});observation=origin.get('observation_sha256')
 if origin.get('executor')!='mediacrawler_pro' or not isinstance(observation,str) or not HEX.fullmatch(observation):raise ValueError('audio_pro_observation_required')
 duration=_duration(data,audio_only=True);local=identity['local_run_id'];source={k:v for k,v in body.items() if k!='record_hash'};source_hash=hashlib.sha256(source_canonical(source).encode()).hexdigest()
 if body.get('record_hash')!=source_hash:raise ValueError('audio_pro_source_hash_invalid')
 if client.role=='worker':
  fields={'task_id','child_id','run_id','lease_epoch','local_run_id','capture_id','envelope_hash'}
  if not isinstance(binding,dict) or set(binding)!=fields or binding.get('local_run_id')!=local:raise ValueError('media_cloud_identity_mismatch')
  receipt=binding;task,child,run,epoch=(binding[k] for k in ('task_id','child_id','run_id','lease_epoch'))
 else:
  matches={(t['task_id'],c['child_id'],a['run_id'],a['lease_epoch']) for t in client.call('task_list').get('tasks',[]) for c in t.get('children',[]) for a in c.get('attempts',[]) if a.get('local_run_id')==local}
  if len(matches)!=1:raise ValueError('media_cloud_source_ambiguous')
  task,child,run,epoch=matches.pop();sources=[]
  for candidate in client.call('results',{'task_id':task}).get('items',[]):
   row=candidate.get('record',{});r=candidate.get('receipt',{})
   if row.get('platform')!='bilibili' or row.get('kind')!='content' or row.get('content_id')!=content_id or row.get('origin',{}).get('run_id')!=local:continue
   expected={'task_id':task,'child_id':child,'run_id':run,'lease_epoch':epoch,'status':'received','reward_eligible':False}
   if not _same_record(body,row,source_hash) or any(canonical(r.get(k))!=canonical(v) for k,v in expected.items()):raise ValueError('media_cloud_identity_mismatch')
   sources.append(r)
  if len(sources)!=1:raise ValueError('media_cloud_source_ambiguous')
  receipt=sources[0]
 job=str(uuid.uuid5(uuid.NAMESPACE_URL,'crowd-native-audio-v3:'+canonical(identity)))
 payload={'idempotency_key':'audio:'+job,'task_id':task,'child_id':child,'run_id':run,'lease_epoch':epoch,'local_run_id':local,'local_job_id':job,'platform':'bilibili','content_id':content_id,'capture_id':receipt['capture_id'],'envelope_hash':receipt['envelope_hash'],'asset_sha256':asset_sha256,'asset_bytes':len(data),'duration_ms':duration,'source_duration_ms':duration,'source_asset_sha256':asset_sha256,'source_observation_sha256':observation,'source_reference_sha256':sha({**identity,'media_path':item['path'],'source_observation_sha256':observation}),'result_file_sha256':normalized_sha,'manifest_version':3,'representation':'pro_collected_audio','completeness':'saved_asset_not_full_length_verified','content_kind':'content','content_type':None,'entity_ref':identity['entity_ref'],'container':'m4a','video_track_present':False,'audio_track_present':True,'content_mime':'audio/mp4','source_record_hash':source_hash,'source_record_canonical':source_canonical(source)}
 validate_audio_manifest(payload);return payload,data

def publish_native_audio(jobs,client,run_folder,content_id,asset_sha256,entity_ref=None,opener=None,binding=None):
 payload,data=prepare_native_audio(jobs,client,run_folder,content_id,asset_sha256,entity_ref,binding)
 with _job_lock(jobs,payload['local_job_id']):return _publish_prepared(jobs,client,payload,data,opener)

def native_audio_cloud_status(jobs,client,run_folder,content_id,asset_sha256,entity_ref=None):
 from media_native import _identity
 identity=_identity(run_folder,content_id,asset_sha256,entity_ref,native_audio=True)[1]
 job=str(uuid.uuid5(uuid.NAMESPACE_URL,'crowd-native-audio-v3:'+canonical(identity)))
 return {'reference_id':job,**media_video_cloud_status(jobs,client,job)}

def download_native_audio(jobs,client,run_folder,content_id,asset_sha256,entity_ref=None,opener=None):
 result=native_audio_cloud_status(jobs,client,run_folder,content_id,asset_sha256,entity_ref)
 data=download_media_video(jobs,client,result['reference_id'],opener)
 if data.get('mime')!='audio/mp4':raise ValueError('audio_cloud_receipt_mismatch')
 return data
