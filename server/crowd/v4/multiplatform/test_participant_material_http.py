import csv,hashlib,io,json,os,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from dashboard import Application,make_server
from automatic_materials import write,canonical,material_context_key
from material_auto_worker import process

FIXTURE=os.environ.get('CROWD_PRO_ACK_FIXTURE')
CONFIG=os.environ.get('CROWD_TEST_MATERIAL_AUTO_CONFIG')
@unittest.skipUnless(FIXTURE and CONFIG,'explicit real ACK and pinned toolbox config required')
class HttpTests(unittest.TestCase):
    def test_actual_jobs_publication_four_formats_and_index(self):
        group=json.loads(Path(FIXTURE).read_text());cfg=json.loads(Path(CONFIG).read_text())
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();directory=root/'data-products';inputs=directory/'participant-pro-ack-inputs';inputs.mkdir(parents=True);(directory/'material-auto').mkdir()
            blob=canonical(group);digest=hashlib.sha256(blob).hexdigest();source=inputs/(digest+'.json');source.write_bytes(blob);source.chmod(0o600)
            context={'schema':'crowd-participant-pro-material-context-v1',**{k:group[k] for k in ('task_id','subject','installation_id','dispatch_id','group_cursor')},'group_path':str(source),'group_sha256':digest}
            key=material_context_key(context);state=directory/'material-auto'/(key+'.json');write(state,{'state':'waiting','context':context})
            process(root,state,cfg)
            app=object.__new__(Application);app.root=root;app.token='test-only-nonce';app.analysis_jobs=app.owner_tasks=app.cloud_worker=app.automatic_materials=app.media_jobs=None
            class Noop:
                def close(self):pass
            app.health_events=Noop();app.watchlists=Noop()
            server=make_server(app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
            try:
                def get(path):
                    with urllib.request.urlopen(base+path,timeout=30) as r:return r.read()
                index=json.loads(get('/materials/participants.json'));self.assertTrue(index['ok']);self.assertEqual(index['publications'][0]['items'],2)
                self.assertIn('参与者素材'.encode(),get('/materials/participants'))
                url='/materials/pro/'+key;self.assertTrue(get(url).startswith(b'<!'))
                data=json.loads(get(url+'/report.json'));lines=[json.loads(v) for v in get(url+'/materials.jsonl').splitlines()];rows=list(csv.DictReader(io.StringIO(get(url+'/materials.csv').decode())))
                self.assertEqual(len(data['items']),2);self.assertEqual(lines,data['items']);self.assertEqual([json.loads(v['record']) for v in rows],lines)
                self.assertEqual({v['metadata']['capture']['proof_id'] for v in lines},{56,57})
                with self.assertRaises(urllib.error.HTTPError) as bad:get('/materials/pro/../../etc/passwd')
                self.assertEqual(bad.exception.code,404)
            finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
