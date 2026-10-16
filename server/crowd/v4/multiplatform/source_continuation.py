"""Known-failed WB continuation: rebuild public seed, never accept supplied rows."""
import copy,hashlib,json,os,uuid
from pathlib import Path
from public_source_seed import SeedError,build_seed,read_object,canonical,digest,ReuseJournal

def identifier(value):
 try:result=str(uuid.UUID(value))
 except (ValueError,TypeError,AttributeError):raise SeedError('continuation_identity_invalid') from None
 if result!=value:raise SeedError('continuation_identity_invalid')
 return result

def prepare(root,payload,account):
 """Only an authenticated worker lease may supply grant metadata, never source data."""
 if not isinstance(payload,dict) or set(payload)!={'request','lease'}:raise SeedError('continuation_payload_invalid')
 request=payload['request'];lease=payload['lease'];context=lease.get('source_continuation') if isinstance(lease,dict) else None
 if not isinstance(request,dict) or not isinstance(context,dict) or context.get('kind')!='wb-replies-v1' or context.get('new_content_quota') is not False or context.get('reward_eligible') is not False:raise SeedError('continuation_grant_invalid')
 for field in ('continuation_id','source_run_id','source_local_run_id','source_worker_id'):identifier(context.get(field))
 for field in ('run_id','task_id','child_id','worker_id'):identifier(lease.get(field))
 if lease['worker_id']!=context['source_worker_id'] or type(context.get('source_lease_epoch')) is not int or type(lease.get('lease_epoch')) is not int or lease['lease_epoch']!=context['source_lease_epoch']+1 or lease.get('delivery_basis')!='live_capture' or lease.get('may_dispatch') is not True:raise SeedError('continuation_lease_invalid')
 proof=context.get('proof');subject=context.get('account_context')
 if not isinstance(proof,dict) or not isinstance(subject,dict) or proof.get('continuation_kind')!='wb-replies-v1' or proof.get('failure_reason') not in ('wb_embedded_replies_incomplete','wb_reply_page_shape_invalid','wb_reply_terminal_incomplete') or proof.get('exit_code')!=74 or proof.get('executor_inactive') is not True:raise SeedError('continuation_grant_invalid')
 if not isinstance(account,dict) or account.get('login_in_progress') is not False or account.get('account_changed') is True or account.get('identity_status')!='authenticated_self_id' or account.get('state') not in ('authenticated','resumed','ready') or {k:account.get(k) for k in ('session_id','generation','account_ref')}!=subject:raise SeedError('continuation_account_changed')
 if 'progress'in proof:
  from public_source_progress import prepare_progress
  return prepare_progress(root,payload,account)
 if 'chain' in proof:
  from source_continuation_chain import seed_source,prepare_chain
  seed_source(context)
  return prepare_chain(root,payload,account)
 if proof.get('failure_reason')!='wb_embedded_replies_incomplete':raise SeedError('continuation_grant_invalid')
 root=Path(root).resolve();old=root/'runs'/context['source_local_run_id'];oldrequest=read_object(old/'manifest.json')[0]['request']
 account_path=root/'accounts'/subject['session_id']/'state.json'
 if read_object(account_path)[1]!=proof.get('account_state_sha256'):raise SeedError('continuation_account_changed')
 pins={key:read_object(old/name)[1] for key,name in [('manifest_sha256','manifest.json'),('status_sha256','status.json'),('pagination_sha256','pro-pagination.json'),('normalized_sha256','normalized.json')]}
 if any(pins[k]!=proof.get(k) for k in ('manifest_sha256','status_sha256')):raise SeedError('continuation_source_changed')
 seed=build_seed(old,subject,pins)
 if seed['seed_sha256']!=proof.get('seed_sha256'):raise SeedError('continuation_seed_changed')
 spent=proof.get('api_attempts');total=oldrequest.get('max_api_requests');remaining=request.get('max_api_requests')
 if type(spent) is not int or type(total) is not int or type(remaining) is not int or not 0<remaining==total-spent:raise SeedError('continuation_budget_invalid')
 expected=copy.deepcopy(oldrequest);expected['max_api_requests']=remaining
 if canonical(request)!=canonical(expected) or request.get('session_id')!=subject['session_id']:raise SeedError('continuation_request_changed')
 return {'seed':seed,'context':copy.deepcopy(context),'request':copy.deepcopy(request)}

def initialize_run(run,prepared):
 """Called under original session lock before worker spawn; no credential material."""
 run=Path(run);identifier(run.name)
 for name,value in [('public-source-seed.json',prepared['seed'])]:
  fd=os.open(run/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  try:
   raw=(canonical(value)+'\n').encode();view=memoryview(raw)
   while view:view=view[os.write(fd,view):]
   os.fsync(fd)
  finally:os.close(fd)
 return {**prepared['context'],'seed_sha256':prepared['seed']['seed_sha256']}

def split_import(run,manifest,records):
 context=manifest.get('source_continuation')
 if context is None:return None
 seed=read_object(Path(run)/'public-source-seed.json')[0]
 if seed.get('seed_sha256')!=context.get('seed_sha256') or seed.get('seed_sha256')!=context.get('proof',{}).get('seed_sha256') or seed.get('account_context')!=context.get('account_context') or seed.get('source_run_id')!=__import__('source_continuation_chain').seed_source(context):raise SeedError('continuation_seed_changed')
 return ReuseJournal(Path(run),seed,existing_only=True).split_records(records)
