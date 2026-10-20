from pathlib import Path
import ast,hashlib,http.client,importlib.util,json,sys,threading,unittest
HERE=Path(__file__).resolve().parent;import os
RUNTIME=Path(os.environ.get('CROWD_MP_ROOT',str(HERE)));TARGET=Path(os.environ.get('CROWD_HTTP_CANDIDATE',str(HERE)))
sys.path.insert(0,str(RUNTIME));spec=importlib.util.spec_from_file_location('candidate_dashboard',TARGET/'dashboard.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Close:
 def close(self):pass
class App:
 token='fixture';root=HERE/'never-opened';health_events=watchlists=Close();analysis_jobs=owner_tasks=cloud_worker=media_jobs=None
 def __init__(self):self.calls=0
 def material_delivery(self,*a,**k):self.calls+=1;return b'exact saved bytes'
 def health(self):self.calls+=1;return {'ok':True}
class Tests(unittest.TestCase):
 def setUp(self):
  self.app=App();self.s=m.make_server(self.app,0);self.t=threading.Thread(target=self.s.serve_forever,daemon=True);self.t.start();self.addCleanup(self.close)
 def close(self):self.s.shutdown();self.t.join(2);self.s.server_close();self.assertFalse(self.t.is_alive())
 def request(self,method,path,headers=None,body=None):
  c=http.client.HTTPConnection('127.0.0.1',self.s.server_port,timeout=4)
  try:c.request(method,path,body,headers or{});r=c.getresponse();return r.status,r.read()
  finally:c.close()
 def test_standard_accept_queue_capacity_is_bounded(self):
  self.assertEqual(self.s.request_queue_size,64)
 def test_exact_export_response_unchanged(self):
  code,body=self.request('GET','/materials/report.json');self.assertEqual(code,200);self.assertEqual(body,b'exact saved bytes');self.assertEqual(self.app.calls,1)
 def test_foreign_host_rejected_before_any_app_call(self):
  code,body=self.request('GET','/materials/report.json',{'Host':'foreign.invalid'});self.assertEqual(code,403);self.assertEqual(json.loads(body)['error'],'host_rejected');self.assertEqual(self.app.calls,0)
 def test_foreign_origin_rejected_before_any_app_call(self):
  code,body=self.request('POST','/api/health',{'Origin':'https://foreign.invalid','X-Crowd-CSRF':'fixture','Content-Type':'application/json'},b'{"action":"status","payload":{}}');self.assertEqual(code,403);self.assertEqual(json.loads(body)['error'],'local_origin_required');self.assertEqual(self.app.calls,0)
 def test_missing_csrf_rejected_before_any_app_call(self):
  code,body=self.request('POST','/api/health',{'Origin':'http://127.0.0.1:'+str(self.s.server_port),'Content-Type':'application/json'},b'{"action":"status","payload":{}}');self.assertEqual(code,403);self.assertEqual(json.loads(body)['error'],'workbench_page_updated');self.assertEqual(self.app.calls,0)
 def test_normal_ui_status_post_retains_contract(self):
  code,body=self.request('POST','/api/health',{'Origin':'http://127.0.0.1:'+str(self.s.server_port),'X-Crowd-CSRF':'fixture','Content-Type':'application/json'},b'{"action":"status","payload":{}}');self.assertEqual(code,200);self.assertEqual(json.loads(body),{'ok':True});self.assertEqual(self.app.calls,1)
if __name__=='__main__':unittest.main()
