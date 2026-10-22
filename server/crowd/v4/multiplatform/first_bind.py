"""First XHS binding for an installed worker, using the original Pro self check.
No cloud RPC, scheduler, source collection, account copy or relay is performed.
"""
import argparse,fcntl,hashlib,json,os,re,socket,subprocess,sys,uuid
from pathlib import Path
from install_machine_node import installed,private,write_once,encode,need,sha
ENROLL_SHA='7c39217c54063e5621edc585ad94412649d1742e1b5e749a949d87892603cbd8'

def context(root):
 root=Path(root).absolute();record=installed(root)
 need(len(record['collector_roots'])==1,'first_bind_requires_one_registered_collector')
 sys.path.insert(0,record['runtime'])
 return root,record,Path(record['collector_roots'][0])
def existing(collector,client_id):
 from account_sessions import AccountSessions
 store=AccountSessions(collector);matches=[]
 for session in sorted((collector/'sessions').iterdir()):
  need(not session.is_symlink(),'unsafe_session_path')
  if not session.is_dir():continue
  identity=json.loads(private(session/'identity.json'))
  if identity.get('platform')!='xhs':continue
  bound=json.loads(private(session/'pro-binding.json'))
  need(bound.get('client_id')==client_id,'existing_xhs_binding_conflict')
  value=store.status(session.name,'xhs');matches.append(value)
 need(len(matches)<=1,'existing_xhs_binding_ambiguous')
 return matches[0]if matches else None
def usable(value):
 return bool(value and value.get('state')in('authenticated','resumed')and value.get('identity_status')=='authenticated_self_id'and value.get('login_verified')is True and value.get('recovering')is False and value.get('login_in_progress')is False and type(value.get('generation'))is int and value['generation']>=1 and type(value.get('account_ref'))is str and re.fullmatch('[a-f0-9]{64}',value['account_ref']))
def result(value):
 return {'state':'bound','session_id':value['session_id'],'generation':value['generation'],'identity_basis':'cached_original_pro_official_self','reused':True,'source_collection_started':False}
def bind(root,client_id,*,status=False,invoke=subprocess.run,connect=socket.create_connection):
 need(type(client_id)is str and re.fullmatch('[A-Za-z0-9_-]{1,128}',client_id)is not None,'invalid_local_client_id')
 root,record,collector=context(root);value=existing(collector,client_id)
 if usable(value):return result(value)
 if status:return {'state':'unbound_or_unverified','source_collection_started':False}
 need(value is None,'existing_session_unverified_do_not_rebind')
 # Before creating any plan/intent, give the operator a finite actionable error.
 try:
  with connect(('127.0.0.1',8274),timeout=2):pass
 except OSError:raise ValueError('cookiebridge_not_running_start_original_local_server')from None
 from pro_executor import task_installation,probe
 from mc_runner import BridgeError
 try:selected=task_installation(collector,{'source_executor':'pro'});probe(selected['root'],selected['python'])
 except (BridgeError,ValueError,OSError):raise ValueError('pro_dependencies_unavailable_run_install')from None
 enroll=Path(__file__).with_name('pro_bridge_enroll.py');need(sha(enroll.read_bytes())==ENROLL_SHA,'enrollment_source_changed')
 fd=os.open(root/'first-bind.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);value=existing(collector,client_id)
  if usable(value):return result(value)
  need(value is None,'existing_session_unverified_do_not_rebind')
  plans=root/'binding-plans';plans.mkdir(mode=0o700,exist_ok=True);plan_path=plans/(hashlib.sha256(client_id.encode()).hexdigest()+'.json')
  if plan_path.exists():
   plan=json.loads(private(plan_path));need(plan.get('collector_root')==str(collector)and plan.get('binding',{}).get('client_id')==client_id,'first_bind_plan_changed')
  else:
   plan={'schema':'crowd-pro-bridge-enrollment-v1','collector_root':str(collector),'session_id':str(uuid.uuid4()),'binding':{'platform':'xhs','client_id':client_id,'cookiebridge_url':'http://127.0.0.1:8274','sign_url':'http://127.0.0.1:8990'}};write_once(plan_path,encode(plan))
  need(set(plan)=={'schema','collector_root','session_id','binding'}and plan['schema']=='crowd-pro-bridge-enrollment-v1'and str(uuid.UUID(plan['session_id']))==plan['session_id']and plan['binding']=={'platform':'xhs','client_id':client_id,'cookiebridge_url':'http://127.0.0.1:8274','sign_url':'http://127.0.0.1:8990'},'first_bind_plan_changed')
  need(not(collector/'enrollments'/(plan['session_id']+'.json')).exists(),'first_bind_pending_or_unknown_do_not_retry')
  env={k:v for k,v in os.environ.items()if not k.startswith(('VOX_','PYTHON','LD_','DYLD_'))and k not in('BASH_ENV','ENV','NODE_OPTIONS','NODE_PATH')};env.update(PYTHONPATH=record['runtime'],PYTHONDONTWRITEBYTECODE='1')
  done=invoke([selected['python'],'-B',str(enroll),'--plan',str(plan_path),'--plan-sha256',sha(private(plan_path))],env=env,capture_output=True)
  # Do not expose child stdout/stderr or turn an unknown into a new SID/retry.
  need(done.returncode==0,'first_bind_failed_or_unknown_inspect_local_enrollment');value=existing(collector,client_id);need(usable(value),'first_bind_official_self_unverified')
  return {**result(value),'reused':False}
 finally:os.close(fd)
def reason(error):
 value=str(error)
 allowed={'invalid_local_client_id','first_bind_requires_one_registered_collector','existing_xhs_binding_conflict','existing_xhs_binding_ambiguous','existing_session_unverified_do_not_rebind','cookiebridge_not_running_start_original_local_server','pro_dependencies_unavailable_run_install','enrollment_source_changed','first_bind_plan_changed','first_bind_pending_or_unknown_do_not_retry','first_bind_failed_or_unknown_inspect_local_enrollment','first_bind_official_self_unverified','unsafe_session_path'}
 return value if value in allowed else 'local_binding_unavailable'
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);parser.add_argument('--client-id',required=True,help='Client ID shown by your original local CookieBridge extension; never a Cookie');parser.add_argument('--status',action='store_true',help='Read cached local status only; no connection, auth or write');a=parser.parse_args()
 try:value=bind(a.root,a.client_id,status=a.status)
 except (ValueError,OSError):print(json.dumps({'state':'not_ready','reason_code':reason(sys.exc_info()[1]),'source_collection_started':False}));return 2
 print(json.dumps(value));return 0 if value['state']=='bound'else 2
if __name__=='__main__':raise SystemExit(main())
