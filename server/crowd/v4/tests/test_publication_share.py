import sys,tempfile,unittest,json,hashlib,datetime,uuid,os
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'multiplatform'))
import publication_share as share
class Test(unittest.TestCase):
 def test_explicit_owner_and_valid_response(self):
  with tempfile.TemporaryDirectory() as t:
   app=fixture(Path(t).resolve());v=share.generate(app,{'request_id':str(uuid.uuid4())});self.assertTrue(v['page_url'].startswith('https://app-lyart-eta-22.vercel.app/materials#publication='));self.assertEqual(app.cloud_client.actions,['publication_links']);self.assertEqual(len(list((Path(t)/'publication-share-intents').iterdir())),1)
 def test_worker_invalid_payload_and_scope_never_call(self):
  with tempfile.TemporaryDirectory() as t:
   app=fixture(Path(t).resolve());app.cloud_client.role='worker'
   with self.assertRaisesRegex(ValueError,'owner_authorization_required'):share.generate(app,{'request_id':str(uuid.uuid4())})
   self.assertEqual(app.cloud_client.actions,[])
   app.cloud_client.role='owner'
   for payload in [{},{'request_id':'bad'},{'request_id':str(uuid.uuid4()),'report_hash':'x'}]:
    with self.assertRaisesRegex(ValueError,'publication_share_invalid'):share.generate(app,payload)
   app.bodies['json']=b'{"project_id":"wrong","items":[]}'
   with self.assertRaisesRegex(ValueError,'publication_share_scope_unavailable'):share.generate(app,{'request_id':str(uuid.uuid4())})
   self.assertEqual(app.cloud_client.actions,[])
 def test_unknown_and_expired_not_reminted_and_no_url_log(self):
  for mode in ['unknown','expired']:
   with self.subTest(mode=mode),tempfile.TemporaryDirectory()as t:
    root=Path(t).resolve();app=fixture(root);app.cloud_client.mode=mode;payload={'request_id':str(uuid.uuid4())}
    with self.assertRaisesRegex(ValueError,'publication_share_outcome_unknown_no_retry'):share.generate(app,payload)
    with self.assertRaisesRegex(ValueError,'publication_share_already_attempted'):share.generate(app,payload)
    self.assertEqual(app.cloud_client.actions,['publication_links']);raw=next((root/'publication-share-intents').iterdir()).read_text();self.assertNotIn('token',raw);self.assertNotIn('page_url',raw);self.assertNotIn('SENSITIVE',raw)
 def test_success_same_request_no_second_sign_and_exact_original(self):
  with tempfile.TemporaryDirectory()as t:
   root=Path(t).resolve();app=fixture(root);payload={'request_id':str(uuid.uuid4())};value=share.generate(app,payload)
   import base64
   encoded=value['page_url'].split('#publication=')[1];data=json.loads(base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4)))
   for fmt,raw in app.bodies.items():self.assertEqual(data['formats'][fmt]['sha256'],hashlib.sha256(raw).hexdigest())
   self.assertEqual(data['expires_in'],900)
   with self.assertRaisesRegex(ValueError,'publication_share_already_attempted'):share.generate(app,payload)
   self.assertEqual(app.cloud_client.actions,['publication_links'])
 def test_concurrent_same_id_one_sign(self):
  import concurrent.futures
  with tempfile.TemporaryDirectory()as t:
   app=fixture(Path(t).resolve());payload={'request_id':str(uuid.uuid4())}
   with concurrent.futures.ThreadPoolExecutor(2)as pool:
    futures=[pool.submit(share.generate,app,payload)for _ in range(2)];results=[]
    for f in futures:
     try:results.append(f.result())
     except ValueError as e:results.append(str(e))
   self.assertEqual(app.cloud_client.actions,['publication_links']);self.assertEqual(sum(type(x)is dict for x in results),1)
 def test_actual_application_cloud_new_action_and_old_status_unchanged(self):
  from dashboard import Application
  with tempfile.TemporaryDirectory()as t:
   app=fixture(Path(t).resolve());v=Application.cloud(app,'publication_share',{'request_id':str(uuid.uuid4())});self.assertTrue(v['ok']);self.assertEqual(app.cloud_client.actions,['publication_links'])
 @unittest.skipUnless(os.environ.get('CROWD_PUBLICATION_TEST_SNAPSHOT'),'provide original four-format snapshot for integration test')
 def test_original_four_bytes_with_actual_client_validation(self):
  with tempfile.TemporaryDirectory()as t:
   app=fixture(Path(t).resolve());source=Path(os.environ['CROWD_PUBLICATION_TEST_SNAPSHOT']).resolve();app.bodies={f:(source/('report.'+f)).read_bytes()for f in share.MIMES};app.cloud_client=Cloud(app.bodies);v=share.generate(app,{'request_id':str(uuid.uuid4())});self.assertEqual(v['report_hash'],'cec2019d3f3c7724d2ff6712d31cbf44a1a4731ee1b255f94cd4fe4cbfb6b5a8');self.assertEqual(sum(len(x)for x in app.bodies.values()),211899)
class Cloud:
 role='owner';endpoint='https://bdwrhshgdeghgyzwpxnl.supabase.co/functions/v1/crowd-machine'
 def __init__(self,bodies):self.actions=[];self.bodies=bodies;self.mode='valid'
 def call(self,action,payload):
  self.actions.append(action)
  if self.mode=='unknown':raise RuntimeError('SENSITIVE_SYNTHETIC')
  now=datetime.datetime.now(datetime.timezone.utc);report=hashlib.sha256(self.bodies['json']).hexdigest();value={'schema':'crowd-publication-links-v1','owner_scope':'crowd-owner-main','report_hash':report,'project_id':'shanghai-existing-six-domain','issued_at':now.isoformat(timespec='milliseconds').replace('+00:00','Z'),'expires_at':(now+datetime.timedelta(seconds=900 if self.mode!='expired' else -1)).isoformat(timespec='milliseconds').replace('+00:00','Z'),'expires_in':900,'media_bytes_included':False,'formats':{}}
  for f,b in self.bodies.items():value['formats'][f]={'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'mime':share.MIMES[f],'signed_url':self.endpoint.split('/functions/')[0]+'/storage/v1/object/sign/crowd-publication-snapshots/publications/crowd-owner-main/'+report+'/report.'+f+'?token=synthetic.not-real&download='}
  return value
class App:
 def material_delivery(self,fmt,domain):assert domain is True;return self.bodies[fmt]
def fixture(root):
 app=App();app.root=root;app.bodies={f:(b'{"project_id":"shanghai-existing-six-domain","items":[]}'if f=='json'else('synthetic '+f).encode())for f in share.MIMES};app.cloud_client=Cloud(app.bodies);return app
if __name__=='__main__':unittest.main()
