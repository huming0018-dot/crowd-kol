"""Real saved second-domain Consumer via normal HTTP; no production writes."""
from pathlib import Path
import csv,hashlib,io,json,os,tempfile,threading,unittest,urllib.request,urllib.error
from dashboard import Application,make_server

PROJECT='participant-software-deployments-20261019'

class Projects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config=os.environ.get('CROWD_PROJECT_TEST_CONFIG');legacy=os.environ.get('CROWD_PROJECT_TEST_LEGACY_ROOT')
        if not config or not legacy:raise RuntimeError('explicit real project reader and original legacy fixture paths required')
        cls.config_source=Path(config);cls.original=Path(legacy)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.folder=self.root/'data-products';self.folder.mkdir()
        self.config=json.loads(self.config_source.read_text())
        for n in ['material-runtime.json','domain-runtime.json']:(self.folder/n).write_bytes((self.original/n).read_bytes());(self.folder/n).chmod(0o600)
        self.app=object.__new__(Application);self.app.root=self.root;self.app.token='test-only-nonce'
        self.app.analysis_jobs=self.app.owner_tasks=self.app.cloud_worker=self.app.automatic_materials=self.app.media_jobs=None
        class Noop:
            def close(self):pass
        self.app.health_events=Noop();self.app.watchlists=Noop()
        self.server=make_server(self.app,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def get(self,path):
        with urllib.request.urlopen(self.url+path,timeout=30)as r:return r.status,r.read(),r.headers
    def register(self,projects=None):
        p=self.folder/'project-publications.json'
        p.write_text(json.dumps({'schema':'crowd-project-publications-v1','projects':projects if projects is not None else [{'project_id':PROJECT,'name':'软件更新观察','config':self.config}]}));p.chmod(0o600)
    def test_no_registry_is_clear_empty_index(self):
        status,text,_=self.get('/data-products');self.assertEqual(status,200);self.assertIn('暂无已登记项目'.encode(),text)
    def test_actual_second_domain_four_formats(self):
        self.register();status,index,_=self.get('/data-products');self.assertEqual(status,200);self.assertIn('软件更新观察'.encode(),index)
        base='/data-products/projects/'+PROJECT
        self.assertIn('软件部署'.encode(),self.get(base)[1])
        data=json.loads(self.get(base+'/report.json')[1]);lines=[json.loads(x)for x in self.get(base+'/items.jsonl')[1].splitlines()]
        rows=[json.loads(x['record'])for x in csv.DictReader(io.StringIO(self.get(base+'/items.csv')[1].decode()))]
        self.assertEqual(data['project_id'],PROJECT);self.assertEqual(len(data['items']),1);self.assertEqual(lines,data['items']);self.assertEqual(rows,data['items'])
        self.assertIn('attachment',self.get(base+'/report.json')[2]['Content-Disposition'])
    def test_original_routes_remain_original_projects(self):
        self.register();materials=json.loads(self.get('/materials/report.json')[1]);domain=json.loads(self.get('/data-product/report.json')[1])
        self.assertEqual(len(materials['items']),31);self.assertEqual(len(domain['items']),6)
    def test_unknown_project_does_not_fallback(self):
        self.register()
        with self.assertRaises(urllib.error.HTTPError)as error:self.get('/data-products/projects/unknown-project/report.json')
        self.assertEqual(error.exception.code,409)
    def test_wrong_request_project_rejected(self):
        req=json.loads(Path(self.config['request']).read_text());req['project_id']='wrong-project';p=self.root/'bad-request.json';p.write_text(json.dumps(req))
        cfg={**self.config,'request':str(p),'request_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        self.register([{'project_id':PROJECT,'name':'wrong','config':cfg}])
        with self.assertRaises(urllib.error.HTTPError)as error:self.get('/data-products/projects/'+PROJECT+'/report.json')
        self.assertEqual(error.exception.code,409)
    def test_bad_hash_and_duplicate_registry_fail_closed(self):
        for entries in [[{'project_id':PROJECT,'name':'bad','config':{**self.config,'request_sha256':'0'*64}}],
            [{'project_id':PROJECT,'name':'a','config':self.config},{'project_id':PROJECT,'name':'b','config':self.config}]]:
            self.register(entries)
            with self.assertRaises(urllib.error.HTTPError)as error:self.get('/data-products')
            self.assertEqual(error.exception.code,409)
    def test_registry_symlink_and_route_traversal_rejected(self):
        self.register();p=self.folder/'project-publications.json';other=self.root/'original-registry.json';p.rename(other);p.symlink_to(other)
        with self.assertRaises(urllib.error.HTTPError)as error:self.get('/data-products')
        self.assertEqual(error.exception.code,409)
        with self.assertRaises(urllib.error.HTTPError)as error:self.get('/data-products/projects/%2e%2e%2fetc/report.json')
        self.assertEqual(error.exception.code,404)

    def test_name_escaped_and_foreign_script_rejected(self):
        self.register([{'project_id':PROJECT,'name':'<img src=x onerror=alert(1)>','config':self.config}])
        text=self.get('/data-products')[1];self.assertIn(b'&lt;img',text);self.assertNotIn(b'<img',text)
        script=self.root/'other.py';script.write_text('raise RuntimeError("not the original Consumer reader")')
        cfg={**self.config,'script':str(script),'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest()}
        self.register([{'project_id':PROJECT,'name':'wrong reader','config':cfg}])
        with self.assertRaises(urllib.error.HTTPError)as error:self.get('/data-products')
        self.assertEqual(error.exception.code,409)

    def test_foreign_report_and_pack_rejected_by_existing_consumer(self):
        original=json.loads(Path(self.config['request']).read_text())
        for key,value in [('report_hash','0'*64),('manifest_sha256','0'*64),('pack_sha256',{n:'0'*64 for n in original['pack_sha256']})]:
            request={**original,key:value};p=self.root/('wrong-'+key+'.json');p.write_text(json.dumps(request))
            cfg={**self.config,'request':str(p),'request_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            self.register([{'project_id':PROJECT,'name':'mismatch','config':cfg}])
            with self.assertRaises(urllib.error.HTTPError)as error:self.get('/data-products/projects/'+PROJECT+'/report.json')
            self.assertEqual(error.exception.code,409)

if __name__=='__main__':unittest.main()
