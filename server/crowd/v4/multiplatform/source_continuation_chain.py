"""One known shape-failure continuation, separating latest failure from old seed.
No browser/Cookie/network action and no local state mutation. Central CAS is separate.
"""
import contextlib,copy,hashlib,json,sqlite3
from pathlib import Path
from public_source_seed import (SeedError,read_object,safe,digest,canonical,build_seed,
                                validate_seed,matching_reuse,TOPIC,COMMENT)
from shared_request_budget import request_fingerprint
CHAIN_KEYS={'previous_continuation_id','seed_source_local_run_id','prior_api_attempts'}
KNOWN='wb_reply_page_shape_invalid'

def uuid(value):
 from source_continuation import identifier
 return identifier(value)

def seed_source(context):
 proof=context.get('proof',{});chain=proof.get('chain')
 if chain is None:return context.get('source_local_run_id')
 if type(chain)is not dict or set(chain)!=CHAIN_KEYS:raise SeedError('continuation_chain_invalid')
 uuid(chain.get('previous_continuation_id'));uuid(chain.get('seed_source_local_run_id'))
 if type(chain.get('prior_api_attempts'))is not int or not 0<chain['prior_api_attempts']<=500:raise SeedError('continuation_chain_invalid')
 if proof.get('failure_reason')!=KNOWN or proof.get('identity_binding')!='same_verified_subject':raise SeedError('continuation_chain_invalid')
 return chain['seed_source_local_run_id']

def public_rows(run,rid):
 path=safe(run/'pro-observations.sqlite3');rows=[]
 with contextlib.closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
  db.execute('pragma query_only=ON')
  for platform,kind,entity,raw in db.execute('select platform,kind,entity_id,payload from vox_crawl_observation where operation_id=? order by kind,entity_id',(rid,)):
   if platform!='wb' or kind not in ('topic','comment') or not isinstance(raw,str) or len(raw)>1_000_000 or len(rows)>=2000:raise SeedError('continuation_chain_observation_invalid')
   try:value=json.loads(raw)
   except (ValueError,RecursionError):raise SeedError('continuation_chain_observation_invalid') from None
   if type(value)is not dict or set(value)!=(TOPIC if kind=='topic' else COMMENT):raise SeedError('continuation_chain_observation_invalid')
   rows.append((kind,entity,value))
 return rows

def build_chain_seed(latest_run,account,expected):
 """Validate exactly a known no-fresh-write failed attempt; never promote unknown."""
 run=safe(latest_run);rid=uuid(run.name)
 needed={'manifest_sha256','status_sha256','pagination_sha256','normalized_sha256','budget_sha256'}
 if type(expected)is not dict or set(expected)!=needed:raise SeedError('continuation_chain_pins_invalid')
 names={'manifest_sha256':'manifest.json','status_sha256':'status.json','pagination_sha256':'pro-pagination.json','normalized_sha256':'normalized.json','budget_sha256':'request-budget.json'}
 values={}
 for key,name in names.items():
  value,sha=read_object(run/name)
  if sha!=expected[key]:raise SeedError('continuation_chain_source_changed')
  values[name]=value
 m,s,n,b,p=(values[x] for x in ['manifest.json','status.json','normalized.json','request-budget.json','pro-pagination.json']);q=m.get('request');previous=m.get('source_continuation');lease=m.get('source_continuation_lease')
 if type(q)is not dict or q.get('platform')!='wb' or q.get('source_executor')!='pro' or q.get('mode')!='detail' or q.get('comments')is not True or q.get('replies')is not True or type(previous)is not dict or previous.get('kind')!='wb-replies-v1' or previous.get('new_content_quota')is not False or previous.get('reward_eligible')is not False:raise SeedError('continuation_chain_request_invalid')
 if m.get('run_id')!=rid or s.get('run_id')!=rid or s.get('state')!='failed' or type(s.get('exit_code'))is not int or s['exit_code']!=74 or s.get('failure_reason')!=KNOWN:raise SeedError('continuation_chain_not_known_failed')
 prior_proof=previous.get('proof');subject=previous.get('account_context')
 # This smallest version permits one further attempt after the original grant.
 # Another chained/unknown failure is explicitly not implicitly recoverable.
 if type(prior_proof)is not dict or 'chain' in prior_proof or prior_proof.get('failure_reason')!='wb_embedded_replies_incomplete' or prior_proof.get('exit_code')!=74:raise SeedError('continuation_chain_parent_invalid')
 if type(account)is not dict or set(account)!={'session_id','generation','account_ref'} or account!=subject or q.get('session_id')!=account['session_id']:raise SeedError('continuation_chain_account_changed')
 for key in ['continuation_id','source_run_id','source_local_run_id','source_worker_id']:uuid(previous.get(key))
 if type(lease)is not dict or type(previous.get('source_lease_epoch'))is not int or type(lease.get('lease_epoch'))is not int or lease['lease_epoch']!=previous['source_lease_epoch']+1 or lease.get('worker_id')!=previous['source_worker_id']:raise SeedError('continuation_chain_lease_invalid')
 for key in ['task_id','child_id','run_id','worker_id']:uuid(lease.get(key))
 used=s.get('api_attempts');limit=q.get('max_api_requests');prior=prior_proof.get('api_attempts')
 if any(type(x)is not int for x in [used,limit,prior]) or not 0<used<limit or not 0<prior<=500 or b.get('schema')!='crowd-shared-request-budget-v1' or b.get('run_id')!=rid or b.get('request_hash')!=request_fingerprint(q) or type(b.get('used'))is not int or type(b.get('limit'))is not int or b['used']!=used or b['limit']!=limit or type(b.get('stages'))is not list or len(b['stages'])!=used or any(x!='pro' for x in b['stages']):raise SeedError('continuation_chain_budget_invalid')
 seed,_=read_object(run/'public-source-seed.json');validate_seed(seed);anchor=uuid(seed.get('source_run_id'))
 if anchor!=previous['source_local_run_id'] or seed['seed_sha256']!=previous.get('seed_sha256') or seed['seed_sha256']!=prior_proof.get('seed_sha256') or seed.get('account_context')!=account:raise SeedError('continuation_chain_seed_changed')
 rebuilt=build_seed(run.parent/anchor,account,seed['source_pins'])
 if canonical(seed)!=canonical(rebuilt):raise SeedError('continuation_chain_seed_changed')
 original=read_object(run.parent/anchor/'manifest.json')[0]['request'];old_status=read_object(run.parent/anchor/'status.json')[0]
 if type(original.get('max_api_requests'))is not int or original['max_api_requests']!=prior+limit or old_status.get('api_attempts')!=prior:raise SeedError('continuation_chain_prior_budget_invalid')
 want=copy.deepcopy(original);want['max_api_requests']=limit
 if canonical(q)!=canonical(want):raise SeedError('continuation_chain_scope_changed')
 if p.get('sha256')!=digest({k:v for k,v in p.items() if k!='sha256'}) or p.get('operation_id')!=rid or p.get('platform')!='wb' or p.get('invalid')is not False or any(x.get('scope')=='reply' for x in p.get('pages',[])):raise SeedError('continuation_chain_partial_page_unknown')
 # No new source record can be smuggled into the anchor by this recovery mode.
 if n.get('run_id')!=rid or n.get('capture_records')!=[] or type(n.get('rejected_records'))is not int or n['rejected_records']!=0:raise SeedError('continuation_chain_fresh_or_rejected_rows')
 rows=public_rows(run,rid);path=safe(run/'source-reuse.sqlite3')
 with contextlib.closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
  db.execute('pragma query_only=ON')
  if db.execute('select count(*) from pending_store').fetchone()[0]!=0:raise SeedError('continuation_chain_store_unknown')
  if db.execute('select * from binding').fetchall()!=[(rid,seed['seed_sha256'],anchor)]:raise SeedError('continuation_chain_journal_changed')
  marks={(kind,entity):(raw,meta) for kind,entity,raw,meta in db.execute('select kind,entity_id,readback_sha256,metadata from reused')}
 if not rows or len(marks)!=len(rows):raise SeedError('continuation_chain_fresh_rows')
 expected_norm={}
 for kind,entity,row in rows:
  wanted=matching_reuse(seed,kind,entity,row);mark=marks.get((kind,entity))
  if mark is None or mark[0]!=digest(row) or json.loads(mark[1])!=wanted:raise SeedError('continuation_chain_reuse_changed')
  source=next(x for x in [seed['topic']]+seed['raw_root_rows']+seed['embedded_rows'] if x['kind']==kind and x['entity_id']==entity)
  expected_norm[(kind,entity)]=source['normalized_record']
 normalized=n.get('records')
 if type(normalized)is not list or len(normalized)!=len(expected_norm):raise SeedError('continuation_chain_normalized_changed')
 for x in normalized:
  key=('topic',str(x.get('content_id'))) if x.get('kind')=='content' else ('comment',str(x.get('comment_id')))
  if key not in expected_norm or canonical(x)!=canonical(expected_norm.pop(key)):raise SeedError('continuation_chain_normalized_changed')
 if expected_norm:raise SeedError('continuation_chain_normalized_changed')
 return {'seed':seed,'chain':{'previous_continuation_id':previous['continuation_id'],'seed_source_local_run_id':anchor,'prior_api_attempts':prior},'latest_failure':{'run_id':rid,'failure_reason':KNOWN,'api_attempts':used,'request_limit':limit,'requests_remaining':limit-used,'aggregate_spent':prior+used,'original_total':original['max_api_requests'],'cloud_lease':lease},'pins':expected}

def fresh_account(root,subject,latest,caller):
 """Capture the current identity proof under the existing account state lock."""
 import fcntl,os,stat,re,math
 folder=Path(root)/'accounts'/subject['session_id'];fd=os.open(safe(folder/'state.lock'),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  if not stat.S_ISREG(os.fstat(fd).st_mode):raise SeedError('continuation_account_changed')
  try:fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
  except BlockingIOError:raise SeedError('continuation_account_changed') from None
  state,state_hash=read_object(folder/'state.json')
  keys=('session_id','generation','account_ref','pending_run_id','authorized_for_run','state','identity_status','verified_at')
  if type(state.get('verified_at')) not in (int,float) or not math.isfinite(state['verified_at']) or state['verified_at']<=0 or state.get('account_changed')is True:raise SeedError('continuation_account_changed')
  if type(state.get('generation'))is not int or state['generation']<1 or type(state.get('account_ref'))is not str or not re.fullmatch('[a-f0-9]{64}',state['account_ref']) or {k:state.get(k) for k in subject}!=subject or state.get('pending_run_id')!=latest or state.get('authorized_for_run')!=latest or state.get('state') not in ('authenticated','resumed','ready') or state.get('identity_status')!='authenticated_self_id' or type(caller)is not dict or any(canonical(state.get(k))!=canonical(caller.get(k)) for k in keys):raise SeedError('continuation_account_changed')
  return state_hash
 finally:os.close(fd)

def prepare_chain(root,payload,account):
 """Called only by the existing authenticated lease path, never by an arbitrary run."""
 root=Path(root).resolve();q=payload['request'];lease=payload['lease'];context=lease['source_continuation'];proof=context['proof'];subject=context['account_context'];old=root/'runs'/uuid(context['source_local_run_id'])
 pins={key:read_object(old/name)[1] for key,name in [('manifest_sha256','manifest.json'),('status_sha256','status.json'),('pagination_sha256','pro-pagination.json'),('normalized_sha256','normalized.json'),('budget_sha256','request-budget.json')]}
 if pins['manifest_sha256']!=proof.get('manifest_sha256') or pins['status_sha256']!=proof.get('status_sha256'):raise SeedError('continuation_source_changed')
 if fresh_account(root,subject,old.name,account)!=proof.get('account_state_sha256'):raise SeedError('continuation_account_changed')
 built=build_chain_seed(old,subject,pins);latest=built['latest_failure'];previous_lease=latest['cloud_lease']
 if proof.get('chain')!=built['chain'] or proof.get('api_attempts')!=latest['api_attempts'] or proof.get('seed_sha256')!=built['seed']['seed_sha256'] or context['source_run_id']!=previous_lease['run_id'] or context['source_lease_epoch']!=previous_lease['lease_epoch'] or context['source_worker_id']!=previous_lease['worker_id'] or lease['task_id']!=previous_lease['task_id'] or lease['child_id']!=previous_lease['child_id']:raise SeedError('continuation_chain_grant_changed')
 expected=copy.deepcopy(read_object(old/'manifest.json')[0]['request']);expected['max_api_requests']=latest['requests_remaining']
 if canonical(q)!=canonical(expected):raise SeedError('continuation_budget_invalid')
 if fresh_account(root,subject,old.name,account)!=proof.get('account_state_sha256'):raise SeedError('continuation_account_changed')
 return {'seed':built['seed'],'context':copy.deepcopy(context),'request':copy.deepcopy(q)}

def owner_chain_payload(root,preview,account,runtime_sha256,idempotency_key):
 import fcntl,os
 root=Path(root).resolve();subject={k:account.get(k) for k in ('session_id','generation','account_ref')};old=root/'runs'/uuid(preview['local_run_id'])
 session=root/'sessions'/uuid(subject['session_id']);fd=os.open(safe(session/'active.lock'),os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise SeedError('continuation_executor_active') from None
  pins={key:read_object(old/name)[1] for key,name in [('manifest_sha256','manifest.json'),('status_sha256','status.json'),('pagination_sha256','pro-pagination.json'),('normalized_sha256','normalized.json'),('budget_sha256','request-budget.json')]}
  built=build_chain_seed(old,subject,pins);latest=built['latest_failure'];lease=latest['cloud_lease'];seed=built['seed'];original=read_object(root/'runs'/seed['source_run_id']/'manifest.json')[0]['request']
  if type(preview.get('capture_count'))is not int or preview['capture_count']!=0 or preview.get('capture_digest')!=hashlib.sha256(b'crowd-machine-capture-audit-v1\n').hexdigest():raise SeedError('continuation_chain_capture_changed')
  if any(preview.get(k)!=lease[k] for k in ['task_id','child_id','worker_id','run_id','lease_epoch']) or preview.get('account_context')!=subject or type(preview.get('api_attempts'))is not int or preview['api_attempts']!=latest['api_attempts'] or type(preview.get('requests_remaining'))is not int or preview['requests_remaining']!=latest['requests_remaining'] or canonical(preview['request'])!=canonical(original):raise SeedError('continuation_chain_preview_changed')
  state_hash=fresh_account(root,subject,old.name,account)
 finally:os.close(fd)
 proof={'continuation_kind':'wb-replies-v1','failure_reason':KNOWN,'executor_inactive':True,'local_state':'failed','exit_code':74,'api_attempts':latest['api_attempts'],'status_sha256':pins['status_sha256'],'manifest_sha256':pins['manifest_sha256'],'account_state_sha256':state_hash,'seed_sha256':seed['seed_sha256'],'runtime_sha256':runtime_sha256,'identity_binding':'same_verified_subject','chain':built['chain']}
 return {**{k:preview[k] for k in ['task_id','child_id','worker_id','claim_id','run_id','lease_epoch','local_run_id','expected_revision','expected_finish_hash','capture_count','capture_digest']},'idempotency_key':idempotency_key,'account_context':subject,'proof':proof}
