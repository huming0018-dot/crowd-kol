"""Bounded public checkpoint reconstruction; existing receipts remain authority.
No credentials/profile or whole upstream DB copied. No platform/cloud I/O.
"""
import copy,hashlib,json,sqlite3,contextlib,uuid
from pathlib import Path
from public_source_seed import SeedError,read_object,safe,canonical,digest,build_seed,validate_seed
from source_continuation_chain import public_rows
from shared_request_budget import request_fingerprint
KNOWN={'wb_embedded_replies_incomplete','wb_reply_page_shape_invalid','wb_reply_terminal_incomplete'}
def identity(value):
 try:r=str(uuid.UUID(value))
 except (ValueError,TypeError,AttributeError):raise SeedError('progress_id_invalid') from None
 if r!=value:raise SeedError('progress_id_invalid')
 return r

def receipt_rows(path,local_id,expected_records,binding):
 """Read existing outbox only; bind every fresh record to exact durable ACK."""
 from cloud_sync import canonical as cloud_canonical,_hash,SCHEMA
 result=[];expected={cloud_canonical(v):v for v in expected_records}
 if len(expected)!=len(expected_records):raise SeedError('progress_record_duplicate')
 if isinstance(path,list):
  captures=[row for row in path if row[1]==binding['run_id']]
 else:
  path=safe(path)
  with contextlib.closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True))as db:
   db.execute('pragma query_only=ON');captures=db.execute('select id,run_id,envelope,digest,state,receipt,error from captures where run_id=? order by id',(binding['run_id'],)).fetchall()
 if len(captures)>2000:raise SeedError('progress_capture_limit')
 for cid,rid,raw,dh,state,receipt,error in captures:
  if not isinstance(raw,str) or len(raw)>3_000_000 or not isinstance(receipt,str) or len(receipt)>100_000:raise SeedError('progress_ack_missing')
  try:e=json.loads(raw);rc=json.loads(receipt)
  except (ValueError,TypeError,RecursionError):raise SeedError('progress_ack_invalid') from None
  if not isinstance(e,dict)or not isinstance(rc,dict)or cloud_canonical(e)!=raw or e.get('schema')!=SCHEMA or _hash(SCHEMA,e)!=dh or e.get('capture_id')!=cid or rid!=binding['run_id'] or state!='acknowledged' or error is not None:raise SeedError('progress_ack_invalid')
  for k in ('task_id','child_id','run_id','lease_epoch'):
   if type(e.get(k))!=type(binding[k]) or e.get(k)!=binding[k] or type(rc.get(k))!=type(binding[k]) or rc.get(k)!=binding[k]:raise SeedError('progress_ack_binding')
  record=e.get('record');record_key=cloud_canonical(record)
  if record_key not in expected or record.get('origin',{}).get('run_id')!=local_id or rc.get('capture_id')!=cid or rc.get('envelope_hash')!=dh or rc.get('status')!='received' or rc.get('reward_eligible') is not False:raise SeedError('progress_ack_binding')
  if cid!=str(uuid.uuid5(uuid.UUID(binding['run_id']),record_key)):raise SeedError('progress_ack_identity')
  result.append({'capture_id':cid,'envelope_hash':dh,'receipt_sha256':digest(rc),'source_local_run_id':local_id,'record':record,'envelope':e,'receipt':rc})
 if len(result)!=len(expected):raise SeedError('progress_ack_missing')
 return result

def reconstruct(root,latest_local,outbox,subject):
 """Known segments must positively consume one original task budget; no fixed depth."""
 root=safe(root);latest_local=identity(latest_local);segments=[];seen=set();cursor=latest_local;anchor_seed=None;task_scope=None
 while True:
  if cursor in seen:raise SeedError('progress_cycle')
  seen.add(cursor);run=root/'runs'/cursor;m,mh=read_object(run/'manifest.json');s,sh=read_object(run/'status.json');n,nh=read_object(run/'normalized.json');p,ph=read_object(run/'pro-pagination.json')
  if m.get('run_id')!=cursor or n.get('run_id')!=cursor or s.get('state')!='failed' or type(s.get('exit_code'))is not int or s['exit_code']!=74 or s.get('failure_reason')not in KNOWN:raise SeedError('progress_outcome_unknown')
  q=m.get('request');used=s.get('api_attempts')
  if not isinstance(q,dict)or q.get('platform')!='wb' or q.get('source_executor')!='pro' or q.get('comments')is not True or q.get('replies')is not True or type(used)is not int or used<=0 or type(q.get('max_api_requests'))is not int or used>q['max_api_requests']:raise SeedError('progress_budget_invalid')
  if p.get('sha256')!=digest({k:v for k,v in p.items()if k!='sha256'})or p.get('operation_id')!=cursor or p.get('invalid')is not False:raise SeedError('progress_page_invalid')
  checkpoints=[]
  for checkpointpath in (run/'data/checkpoints/vox'/(cursor+'.json'),run/'data/checkpoints'/(cursor+'.json')):
   if checkpointpath.exists():
    checkpoint,checkpointsha=read_object(checkpointpath)
    if checkpoint.get('id')!=cursor or checkpoint.get('platform')!='wb'or checkpoint.get('mode')!=q.get('mode')or type(checkpoint.get('is_completed'))is not bool or not isinstance(checkpoint.get('crawled_note_list'),list):raise SeedError('progress_checkpoint_invalid')
    checkpoints.append(checkpoint)
  if not checkpoints or any(canonical(x)!=canonical(checkpoints[0])for x in checkpoints):raise SeedError('progress_checkpoint_missing_or_conflict')
  checkpoint=checkpoints[0]
  if checkpoint['is_completed']is not False or any(x.get('is_success_crawled_comments')is not False for x in checkpoint['crawled_note_list']):raise SeedError('progress_checkpoint_outcome_conflict')
  context=m.get('source_continuation');rows=public_rows(run,cursor)
  if context is None:
   if anchor_seed is None:raise SeedError('progress_anchor_missing')
   if cursor!=anchor_seed['source_run_id']:raise SeedError('progress_anchor_changed')
   seed=build_seed(run,subject,anchor_seed['source_pins'])
   if canonical(seed)!=canonical(anchor_seed):raise SeedError('progress_anchor_changed')
   next_manifest=segments[-1]['manifest'];prev=next_manifest['source_continuation'];cl=next_manifest['source_continuation_lease'];binding={k:cl[k]for k in ('task_id','child_id')};binding.update(run_id=prev['source_run_id'],lease_epoch=prev['source_lease_epoch'],worker_id=prev['source_worker_id'])
  else:
   if not isinstance(context,dict)or context.get('kind')!='wb-replies-v1' or context.get('new_content_quota')is not False or context.get('reward_eligible')is not False or canonical(context.get('account_context'))!=canonical(subject):raise SeedError('progress_context_invalid')
   seed,_=read_object(run/'public-source-seed.json');validate_seed(seed)
   if anchor_seed is None:anchor_seed=base_seed(seed)
   if canonical(base_seed(seed))!=canonical(anchor_seed)or context.get('seed_sha256')!=seed['seed_sha256']:raise SeedError('progress_seed_changed')
   binding=m.get('source_continuation_lease')
   if not isinstance(binding,dict):raise SeedError('progress_lease_missing')
   # ReuseJournal constructor performs chmod/DDL even in existing_only mode.
   # Existing evidence is read with the same schema contract, strictly read-only.
   journalpath=safe(run/'source-reuse.sqlite3')
   with contextlib.closing(sqlite3.connect(journalpath.as_uri()+'?mode=ro',uri=True))as journal:
    journal.execute('pragma query_only=ON')
    if journal.execute('select * from binding').fetchall()!=[(cursor,seed['seed_sha256'],seed['source_run_id'])] or journal.execute('select 1 from pending_store limit 1').fetchone():raise SeedError('progress_pending_or_binding_unknown')
   budget,_=read_object(run/'request-budget.json')
   if budget.get('run_id')!=cursor or budget.get('request_hash')!=request_fingerprint(q)or type(budget.get('used'))is not int or budget['used']!=used or type(budget.get('limit'))is not int or budget.get('limit')!=q['max_api_requests']or not isinstance(budget.get('stages'),list)or len(budget['stages'])!=used or any(stage not in ('pro','media')for stage in budget['stages']):raise SeedError('progress_budget_changed')
  if task_scope is None:task_scope={k:binding[k]for k in ('task_id','child_id','worker_id')}
  if {k:binding.get(k)for k in task_scope}!=task_scope or type(binding.get('lease_epoch'))is not int:raise SeedError('progress_scope_changed')
  fresh=n.get('capture_records',n.get('records')if context is None else None)
  if not isinstance(fresh,list)or type(n.get('rejected_records'))is not int or n['rejected_records']!=0:raise SeedError('progress_records_invalid')
  ack=receipt_rows(outbox,cursor,fresh,binding)
  rawmap={(k,str(i)):v for k,i,v in rows}
  for page in p.get('pages',[]):
   if page.get('scope')not in ('root','reply')or page.get('saved')is not True and page.get('selected_saved')is not True:raise SeedError('progress_page_not_durable')
   ids=page.get('selected_ids',page.get('ids'))
   if not isinstance(ids,list)or len(ids)!=len(set(ids)):raise SeedError('progress_page_identity_invalid')
   for value in ids:
    raw=rawmap.get(('comment',value))
    if raw is None or str(raw.get('note_id'))!=str(page.get('content_id'))or page['scope']=='reply'and str(raw.get('parent_comment_id'))!=page.get('parent_id'):raise SeedError('progress_page_not_durable')
  for receipt in ack:
   rec=receipt['record'];key=('topic',str(rec.get('content_id')))if rec.get('kind')=='content'else('comment',str(rec.get('comment_id')));raw=rawmap.get(key)
   if raw is None or rec.get('origin',{}).get('observation_sha256')!=digest(raw):raise SeedError('progress_observation_changed')
   receipt.update(kind=key[0],entity_id=key[1],payload=raw,source_observation_sha256=digest(raw),normalized_record=rec)
  segments.append({'run_id':cursor,'manifest':m,'status':s,'pagination':p,'normalized_records':n.get('records'),'binding':binding,'used':used,'limit':q['max_api_requests'],'pins':{'manifest_sha256':mh,'status_sha256':sh,'normalized_sha256':nh,'pagination_sha256':ph,'checkpoint_sha256':digest(checkpoint),'budget_sha256':read_object(run/'request-budget.json')[1]},'acknowledged_rows':ack})
  if context is None:break
  cursor=identity(context.get('source_local_run_id'))
 segments.reverse();total=segments[0]['limit'];spent=0
 for i,seg in enumerate(segments):
  if seg['limit']!=total-spent:raise SeedError('progress_budget_chain_changed')
  if i:
   prev=segments[i-1];ctx=seg['manifest']['source_continuation']
   if type(ctx.get('proof',{}).get('api_attempts'))is not int or ctx['proof']['api_attempts']!=prev['used']or ctx['source_local_run_id']!=prev['run_id']or ctx['source_run_id']!=prev['binding']['run_id']or ctx['source_lease_epoch']!=prev['binding']['lease_epoch']or seg['binding']['lease_epoch']!=prev['binding']['lease_epoch']+1:raise SeedError('progress_predecessor_changed')
   marker=ctx.get('proof',{}).get('progress',ctx.get('proof',{}).get('chain'))
   if marker is not None:
    if type(marker.get('prior_api_attempts'))is not int or marker['prior_api_attempts']!=sum(x['used']for x in segments[:i-1])or i<2 or marker.get('previous_continuation_id')!=prev['manifest'].get('source_continuation',{}).get('continuation_id')or marker.get('seed_source_local_run_id')!=anchor_seed['source_run_id']:raise SeedError('progress_predecessor_changed')
   if canonical({k:v for k,v in seg['manifest']['request'].items()if k!='max_api_requests'})!=canonical({k:v for k,v in segments[0]['manifest']['request'].items()if k!='max_api_requests'}):raise SeedError('progress_input_changed')
  spent+=seg['used']
 if spent>=total:raise SeedError('progress_budget_exhausted')
 grantids=[seg['manifest']['source_continuation']['continuation_id']for seg in segments if seg['manifest'].get('source_continuation')]
 if len(grantids)!=len(set(grantids)):raise SeedError('progress_grant_cycle')
 unique={}
 for seg in segments:
  for row in seg['acknowledged_rows']:
   key=(row['kind'],row['entity_id'])
   if key in unique:raise SeedError('progress_conflicting_source')
   unique[key]=row
 trusted={(row['kind'],row['entity_id']):row['normalized_record']for row in unique.values()}
 for seg in segments:
  if not isinstance(seg['normalized_records'],list):raise SeedError('progress_normalized_invalid')
  for record in seg['normalized_records']:
   key=('topic',str(record.get('content_id')))if record.get('kind')=='content'else('comment',str(record.get('comment_id')))
   if key not in trusted or canonical(record)!=canonical(trusted[key]):raise SeedError('progress_reused_record_changed')
 progress={'schema':'crowd-wb-public-progress-v1','anchor_seed_sha256':anchor_seed['seed_sha256'],'anchor_local_run_id':anchor_seed['source_run_id'],'latest_local_run_id':latest_local,'account_context':subject,'scope':task_scope,'total_limit':total,'spent':spent,'remaining':total-spent,'segments':[{k:v for k,v in x.items()if k not in ('manifest','status','pagination','normalized_records','acknowledged_rows')}for x in segments],'rows':list(unique.values()),'new_capture_eligible':False}
 if len(canonical(progress).encode())>2_800_000:raise SeedError('progress_size_limit')
 return {**progress,'progress_sha256':digest(progress)},segments,anchor_seed

def validate_progress(progress):
 if type(progress)is not dict or progress.get('schema')!='crowd-wb-public-progress-v1' or progress.get('new_capture_eligible')is not False or progress.get('progress_sha256')!=digest({k:v for k,v in progress.items()if k!='progress_sha256'}):raise SeedError('progress_changed')
 if type(progress.get('spent'))is not int or type(progress.get('total_limit'))is not int or type(progress.get('remaining'))is not int or progress['spent']<=0 or progress['remaining']<=0 or progress['spent']+progress['remaining']!=progress['total_limit']:raise SeedError('progress_budget_invalid')
 return progress

def seed_with_progress(seed,progress,segments):
 validate_seed(seed);validate_progress(progress)
 if progress['anchor_seed_sha256']!=seed['seed_sha256'] or progress['anchor_local_run_id']!=seed['source_run_id'] or canonical(progress['account_context'])!=canonical(seed['account_context']):raise SeedError('progress_seed_changed')
 pages={};root_counts={r['entity_id']:int(r['payload']['sub_comment_count'])for r in seed['raw_root_rows']if r['entity_id']in seed['selected_root_ids']}
 known={r['entity_id']:r for r in progress['rows']if r['kind']=='comment'}
 for segment in segments[1:]:
  grouped={}
  for page in segment['pagination']['pages']:
   if page.get('scope')=='reply':grouped.setdefault(page.get('parent_id'),[]).append(page)
  for parent,chain in grouped.items():
   if parent not in root_counts or not chain or chain[0].get('cursor_in')!=[0,0]:raise SeedError('progress_reply_scope_invalid')
   ids=[]
   for index,page in enumerate(chain):
    if page.get('saved')is not True or page.get('checkpoint_committed')is not False or page.get('embedded')is not False or type(page.get('has_more'))is not bool or type(page.get('declared_count'))is not int or page['declared_count']!=root_counts[parent] or not isinstance(page.get('ids'),list):raise SeedError('progress_reply_page_invalid')
    for pair in (page.get('cursor_in'),page.get('cursor_out')):
     if not isinstance(pair,list)or len(pair)!=2 or any(type(x)is not int for x in pair)or pair[0]<0 or pair[1]!=0:raise SeedError('progress_reply_cursor_invalid')
    if page['has_more']!=(page['cursor_out'][0]!=0)or index and (chain[index-1]['has_more']is not True or chain[index-1]['cursor_out']!=page['cursor_in']):raise SeedError('progress_reply_cursor_invalid')
    for identity in page['ids']:
     row=known.get(identity)
     if identity in ids or row is None or str(row['payload']['parent_comment_id'])!=parent or str(row['payload']['note_id'])!=seed['content_id']:raise SeedError('progress_reply_binding_invalid')
     ids.append(identity)
   # Unknown or partial response may not be skipped; only a durable terminal page.
   if chain[-1]['has_more']is not False:raise SeedError('progress_reply_not_terminal')
   terminal={'parent_id':parent,'ids':ids,'declared_count':root_counts[parent],'cursor_in':[0,0],'cursor_out':[0,0],'has_more':False,'targets':{k:v for page in chain for k,v in page.get('targets',{}).items()},'reply_coverage':'missing_unknown'if len(ids)<root_counts[parent]else'accessibly_complete','observed_count':len(ids),'missing_count':max(0,root_counts[parent]-len(ids))}
   if any(target!=parent and target not in ids for target in terminal['targets'].values()):raise SeedError('progress_reply_target_invalid')
   if parent in pages and canonical(pages[parent])!=canonical(terminal):raise SeedError('progress_reply_conflict')
   pages[parent]=terminal
 value=copy.deepcopy(seed);value.pop('seed_sha256');value['base_seed_sha256']=seed['seed_sha256'];value['public_progress']=copy.deepcopy(progress);value['progress_reply_pages']=pages
 if len(canonical(value).encode())>2_900_000:raise SeedError('progress_size_limit')
 value['seed_sha256']=digest(value);return value

def base_seed(seed):
 if 'public_progress'not in seed:return seed
 validate_seed(seed);progress=validate_progress(seed['public_progress']);value={k:v for k,v in seed.items()if k not in ('seed_sha256','public_progress','progress_reply_pages','base_seed_sha256')};value['seed_sha256']=digest(value)
 if value['seed_sha256']!=seed.get('base_seed_sha256')or value['seed_sha256']!=progress['anchor_seed_sha256']:raise SeedError('progress_seed_changed')
 return value

def candidates(seed):
 original=base_seed(seed);rows=[original['topic']]+[r for r in original['raw_root_rows']if r['entity_id']in original['selected_root_ids']]+original['embedded_rows'];keys={(x['kind'],x['entity_id'])for x in rows}
 if 'public_progress'in seed:
  for row in seed['public_progress']['rows']:
   key=(row.get('kind'),row.get('entity_id'))
   if row.get('source_local_run_id')==original['source_run_id']:continue
   if key in keys or row.get('kind')!='comment'or str(row.get('payload',{}).get('parent_comment_id'))not in original['selected_root_ids']:raise SeedError('progress_row_scope_invalid')
   if row.get('source_observation_sha256')!=digest(row.get('payload'))or row.get('normalized_record',{}).get('origin',{}).get('run_id')!=row.get('source_local_run_id'):raise SeedError('progress_origin_invalid')
   rows.append(row);keys.add(key)
 return rows

PROGRESS_KEYS={'previous_continuation_id','seed_source_local_run_id','anchor_seed_sha256','progress_sha256','prior_api_attempts'}
def proof_progress(seed,segments):
 progress=seed['public_progress'];validate_progress(progress)
 return {'previous_continuation_id':segments[-1]['manifest']['source_continuation']['continuation_id'],'seed_source_local_run_id':seed['source_run_id'],'anchor_seed_sha256':seed['base_seed_sha256'],'progress_sha256':progress['progress_sha256'],'prior_api_attempts':progress['spent']-segments[-1]['used']}

def snapshot_path(root,sha):
 import re
 if not isinstance(sha,str)or not re.fullmatch('[a-f0-9]{64}',sha):raise SeedError('progress_hash_invalid')
 return safe(Path(root)/'continuation-public-progress'/(sha+'.json'))

def receipt_source(progress):
 from cloud_sync import canonical as cloud_canonical
 return [[r['capture_id'],r['envelope']['run_id'],cloud_canonical(r['envelope']),r['envelope_hash'],'acknowledged',cloud_canonical(r['receipt']),None]for r in progress['rows']]

def persist_snapshot(root,progress):
 import os
 validate_progress(progress);path=snapshot_path(root,progress['progress_sha256']);path.parent.mkdir(mode=0o700,exist_ok=True)
 if path.exists():
  if canonical(read_object(path)[0])!=canonical(progress):raise SeedError('progress_snapshot_conflict')
  return
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:
  raw=(canonical(progress)+'\n').encode();view=memoryview(raw)
  while view:view=view[os.write(fd,view):]
  os.fsync(fd)
 finally:os.close(fd)

def prepare_progress(root,payload,account):
 from source_continuation_chain import fresh_account
 root=safe(Path(root));request=payload['request'];lease=payload['lease'];ctx=lease['source_continuation'];proof=ctx['proof'];marker=proof.get('progress');subject=ctx['account_context'];latest=ctx['source_local_run_id']
 if not isinstance(marker,dict)or set(marker)!=PROGRESS_KEYS or 'chain'in proof:raise SeedError('progress_grant_invalid')
 snapshot,_=read_object(snapshot_path(root,marker.get('progress_sha256')));validate_progress(snapshot)
 if snapshot['progress_sha256']!=marker['progress_sha256']:raise SeedError('progress_snapshot_changed')
 if proof.get('failure_reason')!='wb_reply_terminal_incomplete':raise SeedError('progress_outcome_unsupported')
 if fresh_account(root,subject,latest,account)!=proof.get('account_state_sha256'):raise SeedError('progress_account_changed')
 p,segments,base=reconstruct(root,latest,receipt_source(snapshot),subject)
 if canonical(snapshot)!=canonical(p):raise SeedError('progress_snapshot_changed')
 seed=seed_with_progress(base,p,segments)
 if marker!=proof_progress(seed,segments)or proof.get('seed_sha256')!=seed['seed_sha256']or proof.get('api_attempts')!=segments[-1]['used']or proof.get('failure_reason')!=segments[-1]['status']['failure_reason']:raise SeedError('progress_proof_changed')
 source=segments[-1];binding=source['binding']
 if proof.get('manifest_sha256')!=source['pins']['manifest_sha256']or proof.get('status_sha256')!=source['pins']['status_sha256']or ctx['source_run_id']!=binding['run_id']or ctx['source_lease_epoch']!=binding['lease_epoch']or lease['worker_id']!=binding['worker_id']or lease['task_id']!=binding['task_id']or lease['child_id']!=binding['child_id']:raise SeedError('progress_lease_changed')
 expected=copy.deepcopy(source['manifest']['request']);expected['max_api_requests']=p['remaining']
 if canonical(request)!=canonical(expected):raise SeedError('progress_input_changed')
 if fresh_account(root,subject,latest,account)!=proof.get('account_state_sha256'):raise SeedError('progress_account_changed')
 return {'seed':seed,'context':copy.deepcopy(ctx),'request':copy.deepcopy(request)}

def owner_progress_payload(root,preview,account,runtime_sha256,idempotency_key,outbox):
 import os,fcntl,stat
 from source_continuation_chain import fresh_account
 if outbox is None:raise SeedError('progress_receipt_store_required')
 root=safe(Path(root));subject={k:account.get(k)for k in ('session_id','generation','account_ref')};latest=preview['local_run_id'];identity(latest)
 fd=os.open(safe(root/'sessions'/subject['session_id']/'active.lock'),os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  if not stat.S_ISREG(os.fstat(fd).st_mode):raise SeedError('progress_lock_invalid')
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise SeedError('continuation_executor_active')from None
  statehash=fresh_account(root,subject,latest,account)
  progress,segments,base=reconstruct(root,latest,outbox,subject)
  if segments[-1]['status']['failure_reason']!='wb_reply_terminal_incomplete':raise SeedError('progress_outcome_unsupported')
  seed=seed_with_progress(base,progress,segments);last=segments[-1];binding=last['binding']
  for k in ('task_id','child_id','worker_id','run_id','lease_epoch'):
   if type(preview[k])!=type(binding[k])or preview[k]!=binding[k]:raise SeedError('progress_preview_changed')
  audit=hashlib.sha256(('crowd-machine-capture-audit-v1\n'+'\n'.join(sorted(r['capture_id']+':'+r['envelope_hash']for r in last['acknowledged_rows']))).encode()).hexdigest()
  if type(preview['capture_count'])is not int or preview['capture_count']!=len(last['acknowledged_rows'])or preview['capture_digest']!=audit or type(preview['api_attempts'])is not int or preview['api_attempts']!=last['used']or type(preview['requests_remaining'])is not int or preview['requests_remaining']!=progress['remaining']or canonical(preview['account_context'])!=canonical(subject)or canonical(preview['request'])!=canonical(segments[0]['manifest']['request']):raise SeedError('progress_preview_changed')
  if fresh_account(root,subject,latest,account)!=statehash:raise SeedError('progress_account_changed')
  persist_snapshot(root,progress)
 finally:os.close(fd)
 proof={'continuation_kind':'wb-replies-v1','failure_reason':last['status']['failure_reason'],'executor_inactive':True,'local_state':'failed','exit_code':74,'api_attempts':last['used'],'status_sha256':last['pins']['status_sha256'],'manifest_sha256':last['pins']['manifest_sha256'],'account_state_sha256':statehash,'seed_sha256':seed['seed_sha256'],'runtime_sha256':runtime_sha256,'identity_binding':'same_verified_subject','progress':proof_progress(seed,segments)}
 return {**{k:preview[k]for k in ('task_id','child_id','worker_id','claim_id','run_id','lease_epoch','local_run_id','expected_revision','expected_finish_hash','capture_count','capture_digest')},'idempotency_key':idempotency_key,'account_context':subject,'proof':proof}

def known_partial_media(run,manifest,status,normalized):
 """Only a known finished accessible-reply gap with complete verified media."""
 run=safe(Path(run));request=manifest.get('request',{});context=manifest.get('source_continuation')
 if (request.get('platform')!='wb'or request.get('source_executor')!='pro'or request.get('mode')!='detail'or request.get('comments')is not True or request.get('replies')is not True or request.get('media')is not True or not isinstance(context,dict)or context.get('kind')!='wb-replies-v1'or context.get('new_content_quota')is not False or status.get('state')!='failed'or normalized.get('run_state')!='failed'or type(status.get('exit_code'))is not int or status['exit_code']!=74 or status.get('failure_reason')!='wb_reply_terminal_incomplete'):raise SeedError('progress_partial_media_denied')
 phase,_=read_object(run/'phase.json')
 if (phase.get('phase')!='failed'or phase.get('failure_reason')!='wb_reply_terminal_incomplete'or phase.get('media_stage')!='completed'or phase.get('api_attempts_unverified')is not False or status.get('api_attempts_unverified')is not False or phase.get('account_identity_status')!='authenticated_self_id'or type(phase.get('account_generation'))is not int or type(status.get('account_generation'))is not int or type(context.get('account_context',{}).get('generation'))is not int or phase.get('account_generation')<1 or phase.get('account_generation')!=context.get('account_context',{}).get('generation')or status.get('account_generation')!=phase.get('account_generation')or status.get('account_identity_status')!='authenticated_self_id'):raise SeedError('progress_partial_media_denied')
 from shared_request_budget import RunRequestBudget
 budget=RunRequestBudget(run/'request-budget.json',manifest['run_id'],request_fingerprint(request),request['max_api_requests']).snapshot()
 if type(status.get('api_attempts'))is not int or type(phase.get('api_attempts'))is not int or status['api_attempts']!=budget['used']or phase['api_attempts']!=budget['used']:raise SeedError('progress_partial_media_budget_unknown')
 import pro_executor
 coverage=pro_executor.pagination_summary(run,manifest)
 if coverage.get('coverage')!='partial'or coverage.get('reason')!='wb_reply_terminal_incomplete'or coverage.get('independent_selected_roots_visited')is not True:raise SeedError('progress_partial_media_scope_unknown')
 from pro_media_integration import summary
 media=summary(run,manifest)
 if not isinstance(media,dict)or media.get('state')!='completed'or not isinstance(media.get('assets'),list)or not media['assets']or media.get('api_attempts')!=budget['used']:raise SeedError('progress_partial_media_incomplete')
 return True
