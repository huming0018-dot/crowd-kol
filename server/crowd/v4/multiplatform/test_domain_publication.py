"""Explicit real-domain fixtures; no source requests or credentials bundled."""
from pathlib import Path
import csv,io,json,os,subprocess,tempfile,threading,unittest,urllib.request,urllib.error,hashlib
from dashboard import Application,make_server
from workbench_material_call import command
DOMAIN=os.environ.get('CROWD_TEST_DOMAIN_CONFIG');MATERIAL=os.environ.get('CROWD_TEST_MATERIAL_CONFIG')
@unittest.skipUnless(DOMAIN and MATERIAL,'explicit real-domain and material fixture configs required')
class DomainTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name).resolve();mc=root/'mc';mc.mkdir()
  for name in ['main.py','LICENSE']:(mc/name).write_text('fixture')
  self.app=Application(root/'workbench',mc);self.app.owner_tasks.close();self.app.watchlists.close();self.folder=self.app.root/'data-products';self.folder.mkdir()
  for name,source in [('domain-runtime.json',DOMAIN),('material-runtime.json',MATERIAL)]:
   p=self.folder/name;p.write_bytes(Path(source).read_bytes());p.chmod(0o600)
  self.server=make_server(self.app,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_port)
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
 def get(self,path):return urllib.request.urlopen(self.url+path,timeout=30)
 def test_actual_domain_four_formats_and_existing_material_kept(self):
  with self.get('/data-product')as r:self.assertEqual(r.status,200);self.assertTrue('发现'.encode()in r.read())
  with self.get('/data-product/report.json')as r:self.assertIn('attachment',r.headers['Content-Disposition']);data=json.load(r)
  with self.get('/data-product/items.jsonl')as r:jsonl=[json.loads(x)for x in r.read().decode().splitlines()]
  with self.get('/data-product/items.csv')as r:csvrows=[json.loads(x['record'])for x in csv.DictReader(io.StringIO(r.read().decode()))]
  self.assertEqual(len(data['items']),6);self.assertEqual(jsonl,data['items']);self.assertEqual(csvrows,data['items']);self.assertTrue(all(x['unknowns']['taste']=='unknown'for x in data['items']))
  with self.get('/materials/report.json')as r:self.assertEqual(len(json.load(r)['items']),31)
 def test_missing_domain_config_fails_without_impacting_material(self):
  (self.folder/'domain-runtime.json').unlink()
  with self.assertRaises(urllib.error.HTTPError)as e:self.get('/data-product')
  self.assertEqual(e.exception.code,409)
  with self.get('/materials/report.json')as r:self.assertEqual(len(json.load(r)['items']),31)
 def test_shared_source_pin_reader_keeps_existing_material_contract(self):
  config=json.loads(Path(MATERIAL).read_text());script=Path(__file__).parent/'material_bridge.py';config.update(script=str(script),script_sha256=hashlib.sha256(script.read_bytes()).hexdigest())
  r=subprocess.run(command(config,'read','json'),capture_output=True,timeout=30);self.assertEqual(r.returncode,0);self.assertEqual(len(json.loads(r.stdout)['items']),31)
 def test_wrong_report_project_manifest_pack_and_source_pins_rejected(self):
  config=json.loads(Path(DOMAIN).read_text());request=json.loads(Path(config['request']).read_text())
  with tempfile.TemporaryDirectory()as tmp:
   path=Path(tmp).resolve()/'request.json'
   for key,value in [('report_hash','0'*64),('project_id','wrong-project'),('manifest_sha256','0'*64),('toolbox_pins_sha256','0'*64),('pack_sha256',{k:'0'*64 for k in request['pack_sha256']})]:
    path.write_text(json.dumps({**request,key:value}));cfg={**config,'request':str(path),'request_sha256':hashlib.sha256(path.read_bytes()).hexdigest()};r=subprocess.run(command(cfg,'read','json'),capture_output=True,timeout=30);self.assertEqual(r.returncode,2);self.assertEqual(r.stdout,b'');self.assertEqual(r.stderr,b'publication_rejected\n')

if __name__=='__main__':unittest.main()
