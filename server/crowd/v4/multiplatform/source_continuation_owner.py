from source_continuation import *

def owner_payload(root,preview,account,runtime_sha256,idempotency_key):
 """Combine authoritative read-only CAS preview with local public proof, no cloud write."""
 import fcntl,re
 root=Path(root).resolve()
 required={'task_id','child_id','worker_id','claim_id','run_id','lease_epoch','local_run_id','expected_revision','expected_finish_hash','capture_count','capture_digest','account_context','api_attempts','requests_remaining','request'}
 if not isinstance(preview,dict) or set(preview)!=required or not isinstance(runtime_sha256,str) or not re.fullmatch('[a-f0-9]{64}',runtime_sha256) or not isinstance(idempotency_key,str) or not re.fullmatch('[A-Za-z0-9:_-]{1,120}',idempotency_key):raise SeedError('continuation_preview_invalid')
 for field in ('task_id','child_id','worker_id','claim_id','run_id','local_run_id'):identifier(preview.get(field))
 subject={k:account.get(k) for k in ('session_id','generation','account_ref')}
 if account.get('identity_status')!='authenticated_self_id' or account.get('login_in_progress') is not False or account.get('state') not in ('authenticated','resumed','ready') or preview['account_context'] not in ({},subject):raise SeedError('continuation_account_changed')
 old=root/'runs'/preview['local_run_id'];request=read_object(old/'manifest.json')[0]['request']
 if canonical(request)!=canonical(preview['request']):raise SeedError('continuation_request_changed')
 session=root/'sessions'/subject['session_id'];fd=os.open(session/'active.lock',os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise SeedError('continuation_executor_active') from None
  pins={key:read_object(old/name)[1] for key,name in [('manifest_sha256','manifest.json'),('status_sha256','status.json'),('pagination_sha256','pro-pagination.json'),('normalized_sha256','normalized.json')]}
  seed=build_seed(old,subject,pins)
  status=read_object(old/'status.json')[0]
  if status.get('api_requests',status.get('api_attempts'))!=preview['api_attempts'] or preview['requests_remaining']!=request['max_api_requests']-preview['api_attempts']:raise SeedError('continuation_budget_invalid')
  state_hash=read_object(root/'accounts'/subject['session_id']/'state.json')[1]
 finally:os.close(fd)
 proof={'continuation_kind':'wb-replies-v1','failure_reason':'wb_embedded_replies_incomplete','executor_inactive':True,'local_state':'failed','exit_code':74,'api_attempts':preview['api_attempts'],'status_sha256':pins['status_sha256'],'manifest_sha256':pins['manifest_sha256'],'account_state_sha256':state_hash,'seed_sha256':seed['seed_sha256'],'runtime_sha256':runtime_sha256,'identity_binding':'first_verified_subject' if preview['account_context']=={} else 'same_verified_subject'}
 return {**{k:preview[k] for k in ['task_id','child_id','worker_id','claim_id','run_id','lease_epoch','local_run_id','expected_revision','expected_finish_hash','capture_count','capture_digest']},'idempotency_key':idempotency_key,'account_context':subject,'proof':proof}
