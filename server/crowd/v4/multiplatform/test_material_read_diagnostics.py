"""Fixed read diagnostics only: real local HTTP handler and controlled subprocess boundary."""
from pathlib import Path
import importlib.util,json,logging,os,sys,tempfile,threading,unittest,urllib.request,urllib.error,sqlite3
from types import SimpleNamespace
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
if not (HERE/'material_bridge.py').is_file():
 support=os.environ.get('CROWD_MULTIPLATFORM_DIR')
 if not support or not (Path(support)/'material_bridge.py').is_file():raise RuntimeError('CROWD_MULTIPLATFORM_DIR required; no skip')
 sys.path.insert(0,support)
sys.path.insert(0,str(HERE))
import dashboard as host
import knowledge_review_call as boundary
class Capture(logging.Handler):
 def __init__(self):super().__init__();self.rows=[]
 def emit(self,record):self.rows.append(record.getMessage())
class Tests(unittest.TestCase):
 def setUp(self):
  self.sink=Capture();self.log=logging.getLogger('crowd.workbench.material_read');self.old=self.log.level;self.log.setLevel(logging.WARNING);self.log.addHandler(self.sink)
  self.child=Capture();self.clog=logging.getLogger('crowd.workbench.knowledge_read');self.cold=self.clog.level;self.clog.setLevel(logging.WARNING);self.clog.addHandler(self.child)
 def tearDown(self):
  self.log.removeHandler(self.sink);self.log.setLevel(self.old);self.clog.removeHandler(self.child);self.clog.setLevel(self.cold)
 def events(self,sink):return [json.loads(x)for x in sink.rows]
 def http(self,action,error=None,status403=False):
  def cloud(a,p):
   if error is not None:raise error
   return {'ok':True,'kept':True}
  app=SimpleNamespace(token='t'*48,cloud=cloud,health_events=SimpleNamespace(close=lambda:None),analysis_jobs=None,watchlists=SimpleNamespace(close=lambda:None),owner_tasks=None,cloud_worker=None,media_jobs=None)
  server=host.make_server(app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();origin='http://127.0.0.1:'+str(server.server_port)
  try:
   body={'action':action,'payload':{'never_log':'RAW_SECRET_COOKIE_URL','pro_key':'private_scope'}}
   req=urllib.request.Request(origin+'/api/cloud',json.dumps(body).encode(),{'Content-Type':'application/json','Origin':origin,'X-Crowd-CSRF':'bad'if status403 else app.token})
   try:
    with urllib.request.urlopen(req,timeout=5)as r:return r.status,json.load(r)
   except urllib.error.HTTPError as e:return e.code,json.load(e)
  finally:server.shutdown();server.server_close();thread.join(2)
 def call(self,action,run):
  with tempfile.TemporaryDirectory()as temp:
   p=Path(temp).resolve()/'runtime.json';p.write_text(json.dumps({'python':'/fixed/python','script':'/fixed/service.py','script_sha256':'a'*64,'request':'/fixed/request.json','request_sha256':'b'*64}));p.chmod(0o600)
   with patch.object(boundary,'material_command',return_value=['/fixed/python','-B','/fixed/service.py']),patch.object(boundary.subprocess,'run',side_effect=run)as proc:
    try:return boundary.call(p,p.parent/'cloud.json',{'action':action,'payload':{}})
    finally:self.assertEqual(proc.call_count,1);self.assertEqual(proc.call_args.kwargs['timeout'],25)
 def runner(self,value,code=0):
  def run(*a,**kw):kw['stdout'].write(json.dumps(value).encode());return SimpleNamespace(returncode=code)
  return run
 def test_route_known_read_error_preserves_400_and_records_safe_code(self):
  status,value=self.http('material_versions',ValueError('knowledge_read_unavailable'));self.assertEqual((status,value),(400,{'ok':False,'error':'knowledge_read_unavailable'}))
  rows=self.events(self.sink);self.assertEqual(len(rows),1);r=rows[0];self.assertEqual(r['action'],'material_versions');self.assertEqual(r['error_code'],'knowledge_read_unavailable');self.assertEqual(r['phase'],'route');self.assertIs(type(r['elapsed_ms']),int)
 def test_feedback_unknown_error_never_serializes_payload_or_raw_error(self):
  status,value=self.http('material_feedback_preview',ValueError('https://RAW_SECRET/error?cookie=SECRET'));self.assertEqual(status,400);self.assertEqual(value['error'],'invalid_request');rows=self.events(self.sink);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['error_code'],'request_failed');self.assertNotIn('SECRET',json.dumps(rows));self.assertNotIn('private_scope',json.dumps(rows))
 def test_sqlite_503_classification_preserves_http_contract(self):
  self.assertEqual(self.http('material_versions',sqlite3.OperationalError('RAW_SECRET')),(503,{'ok':False,'error':'local_storage_unavailable'}));self.assertEqual(self.events(self.sink)[0]['error_code'],'local_storage_unavailable')
 def test_success_write_and_403_do_not_create_material_read_events(self):
  self.assertEqual(self.http('material_versions')[0],200);self.assertEqual(self.sink.rows,[])
  self.http('material_feedback_submit',ValueError('knowledge_outcome_unknown'));self.assertEqual(self.sink.rows,[])
  self.assertEqual(self.http('material_feedback_preview',status403=True),(403,{'ok':False,'error':'workbench_page_updated'}));self.assertEqual(self.sink.rows,[])
 def test_child_fixed_reason_survives_in_diagnostic_only(self):
  with self.assertRaisesRegex(ValueError,'knowledge_request_unavailable'):self.call('material_feedback_preview',self.runner({'error':'cloud_read_unavailable'},2))
  rows=self.events(self.child);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['phase'],'child_exit');self.assertEqual(rows[0]['error_code'],'cloud_read_unavailable')
 def test_child_raw_or_malformed_error_is_fixed_class_only(self):
  for error in ['https://RAW_SECRET_COOKIE',{'private':'RAW_SECRET'},None]:
   self.child.rows.clear()
   with self.assertRaisesRegex(ValueError,'knowledge_request_unavailable'):self.call('material_releases',self.runner({'error':error},2))
   rows=self.events(self.child);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['error_code'],'child_exit_unclassified');self.assertNotIn('SECRET',json.dumps(rows))
 def test_timeout_unchanged_read_failure_and_no_write_diagnostic(self):
  def timeout(*a,**kw):raise boundary.subprocess.TimeoutExpired('RAW_SECRET',25)
  with self.assertRaisesRegex(ValueError,'knowledge_read_unavailable'):self.call('material_feedback_preview',timeout)
  r=self.events(self.child);self.assertEqual(r[0]['phase'],'timeout');self.assertEqual(r[0]['error_code'],'knowledge_read_unavailable');self.child.rows.clear()
  with self.assertRaisesRegex(ValueError,'knowledge_outcome_unknown'):self.call('material_feedback_submit',timeout)
  self.assertEqual(self.child.rows,[])
 def test_invalid_output_and_launch_error_are_not_raw(self):
  def invalid(*a,**kw):kw['stdout'].write(b'RAW_SECRET');return SimpleNamespace(returncode=0)
  with self.assertRaises(ValueError):self.call('material_releases',invalid)
  self.assertEqual(self.events(self.child)[0]['phase'],'output_parse');self.assertNotIn('SECRET',''.join(self.child.rows));self.child.rows.clear()
  def missing(*a,**kw):raise FileNotFoundError('RAW_SECRET')
  with self.assertRaises(FileNotFoundError):self.call('material_releases',missing)
  self.assertEqual(self.events(self.child)[0]['phase'],'launch');self.assertNotIn('SECRET',''.join(self.child.rows))
 def test_logging_failure_cannot_replace_original_result(self):
  with patch.object(logging.getLogger('crowd.workbench.knowledge_read'),'warning',side_effect=RuntimeError('logfail')):
   with self.assertRaisesRegex(ValueError,'knowledge_request_unavailable'):self.call('material_releases',self.runner({'error':'cloud_read_unavailable'},2))
  with patch.object(logging.getLogger('crowd.workbench.material_read'),'warning',side_effect=RuntimeError('logfail')):
   self.assertEqual(self.http('material_versions',ValueError('knowledge_read_unavailable')),(400,{'ok':False,'error':'knowledge_read_unavailable'}))
 def test_success_no_child_diagnostic(self):
  self.assertEqual(self.call('material_feedback_preview',self.runner({'state':'feedback_preview'})),{'state':'feedback_preview'});self.assertEqual(self.child.rows,[])
 def test_output_limit_diagnostic_preserves_original_error(self):
  def large(*a,**kw):kw['stdout'].write(b'x'*(1024*1024+1));return SimpleNamespace(returncode=0)
  with self.assertRaisesRegex(ValueError,'knowledge_request_unavailable'):self.call('material_releases',large)
  row=self.events(self.child)[0];self.assertEqual(row['phase'],'output_limit');self.assertEqual(row['error_code'],'output_limit')
 def test_result_shape_diagnostic_preserves_original_error(self):
  with self.assertRaisesRegex(ValueError,'knowledge_result_invalid'):self.call('material_releases',self.runner([]))
  row=self.events(self.child)[0];self.assertEqual(row['phase'],'result_shape');self.assertEqual(row['error_code'],'knowledge_result_invalid')
if __name__=='__main__':unittest.main()
