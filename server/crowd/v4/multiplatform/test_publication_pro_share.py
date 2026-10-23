import unittest,tempfile,uuid,hashlib,json,datetime,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'candidate'))
sys.path.append(os.environ['CROWD_MP_ROOT'])
import publication_share as share
KEY='pro-'+'a'*64
def scope_fixture(root):
 from pro_ack_snapshot import canonical,digest,validate_group,project_id
 from automatic_materials import material_context_key
 run=str(uuid.uuid4());note='a'*24;request=str(uuid.uuid5(uuid.UUID(run),'29:'+note));u='00000000-0000-4000-8000-000000000001';i='00000000-0000-4000-8000-000000000002';d='00000000-0000-4000-8000-000000000003';at='2026-10-19T00:00:00Z'
 record={'kind':'content','platform':'xiaohongshu','content_id':note,'source_kind':'mediacrawler_api','reward_eligible':False,'body':'fixture','text_status':'reported','text_truncated':False};h=digest(record);p={'schema':'crowd-participant-pro-v1','source_kind':'mediacrawler_pro','reward_eligible':False,'record':{**record,'record_hash':h},'canonical_record':canonical(record),'provenance':{'local_run_id':run,'upstream_commit':'a'*40,'observation_sha256':h,'request_sha256':'b'*64,'captured_at':at}}
 scope={'task_id':29,'subject':u,'installation_id':i,'dispatch_id':d};cursor={**scope,'created_at':at,'request':request};row={'request':request,'proof_id':56,'created_at':at,'pro_payload':p,'receipt':{'request':request,'gate':'received','inserted':True,'duplicate':False,'task_received':1,'proof_id':56,'source_kind':'mediacrawler_pro','reward_eligible':False,'record_hash':h},'proof_status':'received'};group={**scope,'task_status':'complete','target':1,'received':1,'group_cursor':cursor,'receipts':[row]};snapshot=validate_group(group);path=root/'group.json';path.write_text(canonical(group));path.chmod(0o600);c={'schema':'crowd-participant-pro-material-context-v1',**scope,'group_cursor':cursor,'group_path':str(path),'group_sha256':hashlib.sha256(path.read_bytes()).hexdigest()};state={'state':'ready','context':c,'source_scope':scope,'items':1};report={'project_id':project_id(snapshot),'as_of':at,'tool_version':'0.5.1','items':[{'identity':{'source_record_id':request},'metadata':{'capture':row},'draft':{'body':'fixture'}}]};return state,report,material_context_key(c)
class Cloud:
 role='owner';endpoint='https://bdwrhshgdeghgyzwpxnl.supabase.co/functions/v1/crowd-machine'
 def __init__(self):self.actions=[];self.payload=None;self.fail=None;self.corrupt=False
 def call(self,action,p):
  self.actions.append(action)
  if self.fail==action:raise RuntimeError('PRIVATE_ERROR')
  if action=='publication_put':self.payload=p;return {'schema':'stored','report_hash':p['manifest']['report_hash']}
  m=self.payload['manifest']
  if action=='publication_get':
   f=p['format'];body=self.payload['files'][f];return {'schema':'crowd-publication-read-v1','report_hash':m['report_hash'],'format':f,'body_utf8':body+('bad'if self.corrupt else ''),'bytes':len(body.encode()),'sha256':m['formats'][f]['sha256'],'media_bytes_included':False}
  assert action=='publication_links'
  now=datetime.datetime.now(datetime.timezone.utc);v={'schema':'crowd-publication-links-v1','owner_scope':'crowd-owner-main','report_hash':m['report_hash'],'project_id':m['project_id'],'issued_at':now.isoformat(timespec='milliseconds').replace('+00:00','Z'),'expires_at':(now+datetime.timedelta(seconds=900)).isoformat(timespec='milliseconds').replace('+00:00','Z'),'expires_in':900,'formats':{},'media_bytes_included':False}
  for f,e in m['formats'].items():v['formats'][f]={**e,'signed_url':self.endpoint.split('/functions/')[0]+'/storage/v1/object/sign/crowd-publication-snapshots/publications/crowd-owner-main/'+m['report_hash']+'/report.'+f+'?token=synthetic&download='}
  return v
class App:
 def __init__(self,root):self.root=root;self.cloud_client=Cloud();self.state='ready';self.reads=[];self.bodies={f:('x'+f).encode()for f in share.MIMES};self.scope_state,report,self.key=scope_fixture(root);self.bodies['json']=json.dumps(report,separators=(',',':')).encode()
 def material_delivery(self,fmt,*,domain=False,pro_key=None):assert not domain and pro_key==KEY;self.reads.append(fmt);return self.bodies[fmt]
def payload(op,key=None):
 if key is None:key=KEY
 return {'request_id':str(uuid.uuid4()),'pro_key':key,'operation':op}
class Tests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.app=App(Path(self.t.name).resolve());global KEY;KEY=self.app.key;import participant_material_delivery;self.old=participant_material_delivery.publication;participant_material_delivery.publication=lambda root,key:({**self.app.scope_state,'state':self.app.state}if key==KEY else (_ for _ in()).throw(ValueError('material_delivery_unavailable')))
 def tearDown(self):import participant_material_delivery;participant_material_delivery.publication=self.old;self.t.cleanup()
 def test_publish_verify_links(self):
  v=share.generate(self.app,payload('publish'));self.assertTrue(v['verified']);self.assertNotIn('page_url',v);self.assertEqual(self.app.cloud_client.actions,['publication_put']+['publication_get']*4)
  link=share.generate(self.app,payload('links'));self.assertIn('#publication=',link['page_url']);self.assertEqual(self.app.cloud_client.actions[-1],'publication_links')
 def test_not_ready(self):
  self.app.state='waiting'
  with self.assertRaises(ValueError):share.generate(self.app,payload('publish'))
  self.assertEqual(self.app.cloud_client.actions,[])
 def test_unknown_publish_not_repeated_and_explicit_verify(self):
  self.app.cloud_client.fail='publication_put';p=payload('publish')
  with self.assertRaisesRegex(ValueError,'publish_unknown'):share.generate(self.app,p)
  for q in [p,payload('publish')]:
   with self.assertRaises(ValueError):share.generate(self.app,q)
  self.assertEqual(self.app.cloud_client.actions,['publication_put'])
  self.app.cloud_client.fail=None
  # Simulate committed put whose response was lost, then read-only reconcile.
  from publication_client import bundle
  dirs=list((self.app.root/'publication-pro-bundles').iterdir());self.app.cloud_client.payload=bundle(dirs[0],dirs[0].name)
  self.assertTrue(share.generate(self.app,payload('verify'))['verified']);self.assertEqual(self.app.cloud_client.actions.count('publication_put'),1)
 def test_refresh_unknown_preserved(self):
  self.app.cloud_client.fail='publication_put'
  with self.assertRaises(ValueError):share.generate(self.app,payload('publish'))
  restarted=object.__new__(App);restarted.root=self.app.root;restarted.cloud_client=Cloud();restarted.reads=[];restarted.bodies=self.app.bodies
  with self.assertRaisesRegex(ValueError,'publish_unknown_verify_required'):share.generate(restarted,payload('publish'))
  self.assertEqual(restarted.cloud_client.actions,[])
 def test_link_requires_verified(self):
  with self.assertRaises(ValueError):share.generate(self.app,payload('links'))
  self.assertEqual(self.app.cloud_client.actions,[])
 def test_link_unknown_no_remint(self):
  share.generate(self.app,payload('publish'));self.app.cloud_client.fail='publication_links';p=payload('links')
  with self.assertRaisesRegex(ValueError,'links_unknown'):share.generate(self.app,p)
  with self.assertRaises(ValueError):share.generate(self.app,p)
  self.assertEqual(self.app.cloud_client.actions.count('publication_links'),1)
  for f in self.app.root.rglob('*.json'):self.assertNotIn('synthetic',f.read_text())
 def test_remote_corrupt_no_link(self):
  self.app.cloud_client.corrupt=True
  with self.assertRaisesRegex(ValueError,'publish_unknown'):share.generate(self.app,payload('publish'))
  with self.assertRaises(ValueError):share.generate(self.app,payload('links'))
  self.assertNotIn('publication_links',self.app.cloud_client.actions)
 def test_limits_and_scope(self):
  for p in [payload('publish','../../bad'),{**payload('publish'),'directory':'/tmp'},payload('bad')]:
   with self.assertRaises(ValueError):share.generate(self.app,p)
  self.app.bodies['html']=b'x'*250000
  with self.assertRaises(ValueError):share.generate(self.app,payload('publish'))
  self.assertEqual(self.app.cloud_client.actions,[])
 def test_wrong_scope_before_cloud(self):
  report=json.loads(self.app.bodies['json']);report['project_id']='confirmed-pro-'+'b'*24;self.app.bodies['json']=json.dumps(report).encode()
  with self.assertRaisesRegex(ValueError,'scope_mismatch'):share.generate(self.app,payload('publish'))
  self.assertEqual(self.app.cloud_client.actions,[])
 def test_same_project_wrong_receipt_before_cloud(self):
  report=json.loads(self.app.bodies['json']);report['items'][0]['metadata']['capture']['proof_id']=55;self.app.bodies['json']=json.dumps(report).encode()
  with self.assertRaisesRegex(ValueError,'scope_mismatch'):share.generate(self.app,payload('publish'))
  self.assertEqual(self.app.cloud_client.actions,[])
 def test_worker_denied(self):
  self.app.cloud_client.role='worker'
  with self.assertRaises(ValueError):share.generate(self.app,payload('publish'))
  self.assertEqual(self.app.cloud_client.actions,[])
 def test_immutable_changed(self):
  share.generate(self.app,payload('publish'));self.app.bodies['html']+=b'changed'
  with self.assertRaises(ValueError):share.generate(self.app,payload('links'))
  self.assertNotIn('publication_links',self.app.cloud_client.actions)
if __name__=='__main__':unittest.main()
