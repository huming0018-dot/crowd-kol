"""Prepare and start the separately licensed original loopback CookieBridge.
No browser, relay, copied login or network-facing listener is provided.
"""
import fcntl,json,os,socket,subprocess,sys,time,urllib.request
from pathlib import Path
from install_machine_node import encode,need,private,sha,write_once
from prepare_machine_node import environment,execute
BRIDGE_COMMIT='fcddd00887014a1a57acdd847d337f655f31e46c'
def source(root):
 values=[]
 for args in(('rev-parse','HEAD'),('status','--porcelain')):
  value=subprocess.run(['git','-C',str(root),*args],capture_output=True,env=environment(),timeout=10);need(value.returncode==0,'original_cookiebridge_source_changed');values.append(value.stdout.strip())
 need(values==[BRIDGE_COMMIT.encode(),b''],'original_cookiebridge_source_changed')
 need((Path(root)/'server/app.py').is_file(),'original_cookiebridge_missing')
def prepare(root,collector,bridge,python,uv):
 bridge=Path(bridge).resolve();source(bridge);lock=Path(__file__).with_name('BRIDGE-DEPENDENCIES.lock');raw=lock.read_bytes()
 inputs={'source_root':str(bridge),'commit':BRIDGE_COMMIT,'lock_sha256':sha(raw),'python_sha256':sha(Path(python).read_bytes()),'uv_sha256':sha(Path(uv).read_bytes()),'link_mode':'copy'}
 base=Path(root)/'node-dependencies'/('bridge-'+sha(encode(inputs)));record=Path(collector)/'pro-cookiebridge.json'
 if record.exists():
  value=json.loads(private(record));need(value['source_root']==str(bridge),'existing_cookiebridge_configuration_conflict');validate(value);return value
 need(not base.exists(),'cookiebridge_dependency_attempt_unknown');base.mkdir(parents=True,mode=0o700)
 write_once(base/'INTENT.json',encode(inputs));requirements=base/'requirements.lock';write_once(requirements,raw)
 env=environment();execute([str(uv),'venv','--python',str(python),str(base/'venv')],env=env,cwd=bridge)
 selected=base/'venv/bin/python'
 build=base/'build.lock';write_once(build,raw.splitlines(keepends=True)[0])
 execute([str(uv),'pip','install','--python',str(selected),'--require-hashes','--no-deps','-r',str(build)],env=env,cwd=bridge)
 execute([str(uv),'pip','install','--python',str(selected),'--require-hashes','--no-deps','--no-build-isolation','-r',str(requirements)],env=env,cwd=bridge)
 value={'schema':'crowd-local-cookiebridge-v1','source_root':str(bridge),'python':str(selected),'python_sha256':sha(selected.read_bytes()),'lock_sha256':sha(raw)}
 validate(value);write_once(base/'RESULT.json',encode(value));write_once(record,encode(value));return value
def validate(value):
 need(set(value)=={'schema','source_root','python','python_sha256','lock_sha256'}and value['schema']=='crowd-local-cookiebridge-v1','cookiebridge_configuration_invalid')
 source(Path(value['source_root']));need(sha(Path(value['python']).read_bytes())==value['python_sha256'],'cookiebridge_python_changed')
 need(sha(Path(__file__).with_name('BRIDGE-DEPENDENCIES.lock').read_bytes())==value['lock_sha256'],'cookiebridge_dependency_lock_changed')
 execute([value['python'],'-I','-c','import pydantic,tornado.web;assert pydantic.__version__=="2.10.4"'],env=environment(),cwd=Path(value['source_root']),timeout=10)
def listening():
 try:
  with socket.create_connection(('127.0.0.1',8274),timeout=1):return True
 except OSError:return False
def original_accounts():
 class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,*a,**kw):return None
 with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open('http://127.0.0.1:8274/api/accounts',timeout=2)as response:
  need(response.status==200,'cookiebridge_existing_service_unverified');raw=response.read(262145)
 need(len(raw)<=262144,'cookiebridge_existing_service_unverified');value=json.loads(raw)
 need(type(value)is dict and value.get('biz_code')==0 and value.get('isok')is True and type(value.get('data'))is dict and type(value['data'].get('accounts'))is list,'cookiebridge_existing_service_unverified')
def ensure(collector):
 # Existing original service is reused, never killed or rebound.
 if listening():original_accounts();return {'state':'reused'}
 record=Path(collector)/'pro-cookiebridge.json';need(record.exists(),'cookiebridge_not_running_run_install_with_local_bridge')
 value=json.loads(private(record));validate(value)
 fd=os.open(Path(collector)/'cookiebridge-start.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if listening():original_accounts();return {'state':'reused'}
  log=os.open(Path(collector)/'cookiebridge.log',os.O_CREAT|os.O_APPEND|os.O_WRONLY|os.O_NOFOLLOW,0o600)
  env=environment();env.update(APP_HOST='127.0.0.1',APP_PORT='8274',IS_DEBUG='')
  with os.fdopen(log,'ab')as output:
   child=subprocess.Popen([value['python'],'-B','app.py'],cwd=Path(value['source_root'])/'server',env=env,stdin=subprocess.DEVNULL,stdout=output,stderr=output,start_new_session=True)
  for _ in range(30):
   need(child.poll()is None,'cookiebridge_start_failed_inspect_private_log')
   if listening():original_accounts();return {'state':'started_original_server','pid':child.pid}
   time.sleep(.1)
  child.terminate()
  try:child.wait(timeout=5)
  except subprocess.TimeoutExpired:raise ValueError('cookiebridge_owned_start_pending_inspect_private_log')from None
  raise ValueError('cookiebridge_start_timeout_inspect_private_log')
 finally:os.close(fd)
