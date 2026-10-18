import csv,io,json,os,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from dashboard import Application,make_server

CONFIG=os.environ.get('CROWD_TEST_MATERIAL_CONFIG')
@unittest.skipUnless(CONFIG, 'explicit real-material fixture required; no credentials or captures bundled')
class MaterialWorkbenchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();mc=self.root/'mc';mc.mkdir()
  for n in ['main.py','LICENSE']:(mc/n).write_text('fixture')
  self.app=Application(self.root/'workbench',mc);self.app.owner_tasks.close();self.app.watchlists.close()
  self.path=self.app.root/'data-products/material-runtime.json';self.path.parent.mkdir()
  self.config=json.loads(Path(CONFIG).read_text());self.write(self.config)
  self.server=make_server(self.app,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_port)
 def write(self,value):
  self.path.write_text(json.dumps(value));self.path.chmod(0o600)
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
 def get(self,path):return urllib.request.urlopen(self.url+path,timeout=30)
 def test_real_cli_four_formats_through_existing_http(self):
  with self.get('/materials') as r:
   html=r.read();self.assertEqual(r.status,200);self.assertIn('text/html',r.headers['Content-Type']);self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy'])
  self.assertTrue('已确认公开素材'.encode() in html, 'material HTML title absent')
  with self.get('/materials/report.json') as r:
   self.assertIn('attachment',r.headers['Content-Disposition']);data=json.load(r)
  with self.get('/materials/materials.jsonl') as r:lines=[json.loads(line)for line in r.read().decode().splitlines()]
  with self.get('/materials/materials.csv') as r:
   self.assertIn('attachment',r.headers['Content-Disposition']);rows=list(csv.DictReader(io.StringIO(r.read().decode())))
  self.assertEqual(len(data['items']),31);self.assertEqual(lines,data['items']);self.assertEqual([json.loads(x['record'])for x in rows],data['items'])
  self.assertTrue(all(x['metadata']['coverage']=='partial'for x in data['items']))
 def test_invalid_config_or_permissions_returns_bounded_409(self):
  for value,mode in [(None,0o600),({**self.config,'script_sha256':'0'*64},0o600),(self.config,0o644)]:
   self.write(value);self.path.chmod(mode)
   with self.assertRaises(urllib.error.HTTPError) as caught:self.get('/materials')
   self.assertEqual(caught.exception.code,409);body=json.load(caught.exception);self.assertEqual(body['error'],'material_delivery_unavailable');self.assertNotIn(str(self.root),json.dumps(body))
 def test_deep_config_json_returns_409(self):
  self.path.write_text('['*1100+'0'+']'*1100);self.path.chmod(0o600)
  with self.assertRaises(urllib.error.HTTPError)as caught:self.get('/materials')
  self.assertEqual(caught.exception.code,409);self.assertEqual(json.load(caught.exception)['error'],'material_delivery_unavailable')
 def test_host_guard_and_no_arbitrary_file_route(self):
  req=urllib.request.Request(self.url+'/materials',headers={'Host':'example.org'})
  with self.assertRaises(urllib.error.HTTPError)as caught:urllib.request.urlopen(req)
  self.assertEqual(caught.exception.code,403)
  with self.assertRaises(urllib.error.HTTPError)as caught:self.get('/materials/../../../etc/passwd')
  self.assertEqual(caught.exception.code,404)

if __name__=='__main__':unittest.main()
