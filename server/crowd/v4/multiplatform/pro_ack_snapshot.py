"""Pure typed extraction of existing Owner Pro receipts; never cloud/source/decisions."""
import hashlib,json,re,uuid
from datetime import datetime,timedelta
from pathlib import Path
SCHEMA='crowd-participant-pro-material-snapshot-v1'
CONTEXT='crowd-participant-pro-material-context-v1'
SCOPE={'task_id','subject','installation_id','dispatch_id'}
CURSOR=SCOPE|{'created_at','request'}
GROUP=SCOPE|{'task_status','target','received','group_cursor','receipts'}
MAX_BYTES=8*1024*1024
class ProSnapshotError(ValueError):pass
def need(ok):
 if not ok:raise ProSnapshotError('participant_material_contract_invalid')
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def uid(v):
 try:need(type(v)is str and str(uuid.UUID(v))==v)
 except (ValueError,TypeError,AttributeError):raise ProSnapshotError('participant_material_contract_invalid')from None
 return v
def timestamp(v):
 try:
  need(type(v)is str);t=datetime.fromisoformat(v.replace('Z','+00:00'));need(t.utcoffset()==timedelta(0));return t
 except (ValueError,TypeError,AttributeError):raise ProSnapshotError('participant_material_contract_invalid')from None
def scope(v):
 need(type(v)is dict and set(v)==SCOPE);need(type(v['task_id'])is int and v['task_id']>0)
 for k in SCOPE-{'task_id'}:uid(v[k])
 return v
def cursor(v,s):
 need(type(v)is dict and set(v)==CURSOR);need({k:v[k]for k in SCOPE}==s);timestamp(v['created_at']);uid(v['request']);return v
def validate_context(c):
 need(type(c)is dict and set(c)==SCOPE|{'schema','group_cursor','group_path','group_sha256'}and c['schema']==CONTEXT)
 s=scope({k:c[k]for k in SCOPE});cursor(c['group_cursor'],s)
 need(type(c['group_sha256'])is str and re.fullmatch('[a-f0-9]{64}',c['group_sha256']) is not None)
 need(type(c['group_path'])is str and Path(c['group_path']).is_absolute());return c
def extract(group):
 need(type(group)is dict and set(group)==GROUP);need(len(canonical(group).encode())<=MAX_BYTES)
 s=scope({k:group[k]for k in SCOPE});cursor(group['group_cursor'],s)
 need(group['task_status']in ('open','leased','complete','paused','cancelled'))
 need(type(group['target'])is int and type(group['received'])is int and 0<=group['received']<=group['target']<=100000)
 rows=group['receipts'];need(type(rows)is list and 1<=len(rows)<=2000)
 seen=set();proofs=set();notes=set();counts=set()
 for row in rows:
  need(type(row)is dict and set(row)=={'request','proof_id','created_at','pro_payload','receipt','proof_status'})
  request=uid(row['request']);timestamp(row['created_at']);pid=row['proof_id'];need(type(pid)is int and pid>0 and pid not in proofs and request not in seen and row['proof_status']in ('received','verified'))
  p=row['pro_payload'];need(type(p)is dict and set(p)=={'schema','source_kind','reward_eligible','record','canonical_record','provenance'})
  need(p['schema']=='crowd-participant-pro-v1'and p['source_kind']=='mediacrawler_pro'and p['reward_eligible']is False)
  rec=p['record'];need(type(rec)is dict and rec.get('platform')=='xiaohongshu'and rec.get('kind')=='content'and rec.get('source_kind')=='mediacrawler_api'and rec.get('reward_eligible')is False and rec.get('text_status')=='reported'and rec.get('text_truncated')is False)
  note=rec.get('content_id');body=rec.get('body');need(type(note)is str and re.fullmatch('[a-f0-9]{24}',note)is not None and note not in notes and type(body)is str and 1<=len(body)<=500000)
  record={k:v for k,v in rec.items()if k!='record_hash'};sha=digest(record);need(p['canonical_record']==canonical(record) and rec.get('record_hash')==sha)
  prov=p['provenance'];need(type(prov)is dict and set(prov)=={'local_run_id','upstream_commit','observation_sha256','request_sha256','captured_at'})
  run=uid(prov['local_run_id']);timestamp(prov['captured_at'])
  need(type(prov['upstream_commit'])is str and re.fullmatch('[a-f0-9]{40}',prov['upstream_commit'])is not None and type(prov['request_sha256'])is str and re.fullmatch('[a-f0-9]{64}',prov['request_sha256'])is not None and prov['observation_sha256']==sha)
  need(request==str(uuid.uuid5(uuid.UUID(run),str(s['task_id'])+':'+note)))
  receipt=row['receipt'];need(type(receipt)is dict and set(receipt)=={'request','gate','inserted','duplicate','task_received','proof_id','source_kind','reward_eligible','record_hash'})
  n=receipt['task_received'];need(receipt['request']==request and type(receipt['proof_id'])is int and receipt['proof_id']==pid and receipt['gate']=='received'and receipt['inserted']is True and receipt['duplicate']is False and receipt['source_kind']=='mediacrawler_pro'and receipt['reward_eligible']is False and receipt['record_hash']==sha and type(n)is int and 1<=n<=group['received']and n not in counts)
  seen.add(request);proofs.add(pid);notes.add(note);counts.add(n)
 ordered=sorted(rows,key=lambda x:(timestamp(x['created_at']),x['request']))
 last=ordered[-1];need(group['group_cursor']['created_at']==last['created_at']and group['group_cursor']['request']==last['request'])
 return {'schema':SCHEMA,'scope':s,'task_status':group['task_status'],'target':group['target'],'received':group['received'],'group_cursor':group['group_cursor'],'receipts':ordered,'coverage':'unknown'if group['task_status']=='complete'else'partial','source_kind':'durable_participant_pro_receipt_not_original_http','reward_eligible':False}
def original_group(snapshot):
 need(type(snapshot)is dict and set(snapshot)=={'schema','scope','task_status','target','received','group_cursor','receipts','coverage','source_kind','reward_eligible'}and snapshot['schema']==SCHEMA)
 s=snapshot['scope'];scope(s);group={**s,**{k:snapshot[k]for k in ['task_status','target','received','group_cursor','receipts']}}
 need(extract(group)==snapshot);return group
def project_id(snapshot):
 original_group(snapshot);return 'confirmed-pro-'+digest(snapshot['scope'])[:24]
def records(snapshot):
 original_group(snapshot);return {row['request']:row for row in snapshot['receipts']}
def bundle(snapshot):
 original_group(snapshot);sources=[];candidates=[]
 for row in snapshot['receipts']:
  rec=row['pro_payload']['record'];text=rec['body'];rid=row['request'];title=text[:80]
  sources.append({'version_id':rid,'source_id':rec['platform']+'-ugc','source_kind':'ugc','canonical_body':text,'canonical_body_sha256':hashlib.sha256(text.encode()).hexdigest(),'retrieved_at':row['created_at']})
  evidence=[{'source_version_id':rid,'start':0,'end':len(title),'quote':title,'field':'title'}]+[{'source_version_id':rid,'start':start,'end':min(start+5000,len(text)),'quote':text[start:start+5000],'field':'text'}for start in range(0,len(text),5000)]
  candidates.append({'id':rid,'revision':1,'draft':{'title':title,'text':text,'entity_type':rec['kind']},'evidence':evidence,'capture':row,'coverage':snapshot['coverage'],'unscoreable_reason':'No verified restaurant identity or independent dining evidence. Material traceability is not taste, quality or reward.'})
 return {'source_versions':sources,'candidates':candidates,'capture_snapshot':snapshot}

def validate_group(group):
 """Return verified typed snapshot; original group is not modified."""
 return extract(group)
def validate_cursor(value):
 need(type(value)is dict and set(value)==CURSOR);return cursor(value,scope({k:value[k]for k in SCOPE}))
