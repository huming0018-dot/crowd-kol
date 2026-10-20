"""Portable synthetic receipts only: no real ACK/private capture/live API.

Original actual31 and registered-image acceptance remain private G57 evidence.
The fake resolver below tests projection boundaries, not image decoding or a
production registration; those are covered by the private original-resolver test.
"""
import copy,hashlib,json,tempfile,unittest,uuid
from pathlib import Path
from cloud_sync import canonical,_hash,SCHEMA

def capture(record,task,child,run):
 cid=str(uuid.uuid5(uuid.UUID(run),canonical(record)))
 e={'schema':SCHEMA,'task_id':task,'child_id':child,'run_id':run,'lease_epoch':1,'capture_id':cid,'record':record}
 h=_hash(SCHEMA,e);receipt={k:e[k] for k in ['task_id','child_id','run_id','lease_epoch','capture_id']};receipt.update(status='received',reward_eligible=False,envelope_hash=h,received_at='2026-10-20T00:00:00Z')
 return {'capture_id':cid,'envelope':e,'envelope_hash':h,'envelope_canonical':canonical(e),'receipt':receipt,'receipt_canonical':canonical(receipt)}
def other_report():
 task,child,run=[str(uuid.uuid4())for _ in range(3)]
 records=[{'kind':'content','platform':'weibo','content_id':'other','title':'原题 < & '+('长'*120),'body':'完整正文😀\n第二行','reward_eligible':False,'media':[{'media_id':'e'*64,'url':'https://example.invalid/synthetic.png','kind':'image'}],'origin':{'run_id':run}}, {'kind':'comment','platform':'weibo','content_id':'other','comment_id':'r','parent_comment_id':'r','parent_status':'reported_root','text':'根评论','reward_eligible':False,'media':[],'origin':{'run_id':run}}, {'kind':'comment','platform':'weibo','content_id':'other','comment_id':'s','parent_comment_id':'r','parent_status':'reported','text':'子回复','reward_eligible':False,'media':[],'origin':{'run_id':run}}]
 for r in records:r['record_hash']=hashlib.sha256(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 return {'project_id':'confirmed-'+task,'items':[{'identity':{'source_record_id':(c:=capture(r,task,child,run))['capture_id']},'metadata':{'capture':c,'coverage':'partial'}}for r in records]}

class Detail(unittest.TestCase):
 def setUp(self):
  from confirmed_material_detail import project
  self.project=project
  self.report=other_report()
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
 def tearDown(self):self.temp.cleanup()
 def run_project(self,report=None,resolve=None):return self.project(report or self.report,self.root,resolve or (lambda body:(_ for _ in ()).throw(AssertionError('unexpected resolver'))))
 def test_synthetic_exact_text_and_relationship(self):
  d=self.run_project();self.assertEqual((d['counts']['contents'],d['counts']['roots'],d['counts']['replies']),(1,1,1));self.assertEqual(d['coverage'],'partial_or_unknown')
  items={x['capture_id']:x for x in d['contents']+d['comments']}
  for item in self.report['items']:
   c=item['metadata']['capture'];r=c['envelope']['record'];out=items[c['capture_id']]
   self.assertEqual(out['text'],r.get('body')if r['kind']=='content'else r['text']);self.assertEqual(out['record_hash'],r['record_hash']);self.assertEqual(out['capture_origin'],r['origin']);self.assertEqual(out['envelope_hash'],c['envelope_hash'])
   if r['kind']=='content':self.assertEqual(out['title'],r['title'])
 def test_second_non31_fixture(self):
  d=self.run_project(other_report());self.assertEqual(d['counts'],{'contents':1,'roots':1,'replies':1,'unassigned':0});self.assertEqual(d['contents'][0]['text'],'完整正文😀\n第二行');self.assertTrue(len(d['contents'][0]['title'])>80)
 def test_null_original_title_is_preserved_not_body_prefix(self):
  d=other_report();c=d['items'][0]['metadata']['capture'];e=c['envelope'];r=e['record'];r['title']=None;r['record_hash']=hashlib.sha256(json.dumps({k:v for k,v in r.items()if k!='record_hash'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest();c=capture(r,e['task_id'],e['child_id'],e['run_id']);d['items'][0]['metadata']['capture']=c;d['items'][0]['identity']['source_record_id']=c['capture_id']
  out=self.run_project(d);self.assertIsNone(out['contents'][0]['title']);self.assertEqual(out['contents'][0]['text'],'完整正文😀\n第二行')
 def test_second_independent_scope_has_no_first_scope_ids(self):
  first,second=other_report(),other_report();a,b=self.run_project(first),self.run_project(second)
  self.assertNotEqual(a['project_id'],b['project_id']);self.assertNotEqual(a['task_id'],b['task_id']);self.assertTrue({x['capture_id']for x in a['contents']+a['comments']}.isdisjoint({x['capture_id']for x in b['contents']+b['comments']}));self.assertEqual(a['counts'],b['counts']);self.assertEqual(a['counts'],{'contents':1,'roots':1,'replies':1,'unassigned':0})
 def test_invalid_original_receipt_and_wrong_project(self):
  for mutate in [lambda d:d.update(project_id='foreign'),lambda d:d['items'][0]['metadata']['capture']['receipt'].update(status='accepted'),lambda d:d['items'][0]['identity'].update(source_record_id=str(uuid.uuid4()))]:
   d=copy.deepcopy(self.report);mutate(d)
   with self.assertRaises(ValueError):self.run_project(d)
 def test_fresh_envelope_cannot_reuse_stale_source_record_hash(self):
  d=other_report();c=d['items'][0]['metadata']['capture'];r=c['envelope'];rec=r['record'];rec['body']='changed body with stale hash';new=capture(rec,r['task_id'],r['child_id'],r['run_id']);d['items'][0]['metadata']['capture']=new;d['items'][0]['identity']['source_record_id']=new['capture_id']
  with self.assertRaises(ValueError):self.run_project(d)
 def test_duplicate_or_foreign_parent(self):
  d=other_report();d['items'].append(copy.deepcopy(d['items'][1]));
  with self.assertRaises(ValueError):self.run_project(d)
  d=other_report();c=d['items'][2]['metadata']['capture'];rec=c['envelope']['record'];rec['parent_comment_id']='not-here';rec['record_hash']=hashlib.sha256(json.dumps({k:v for k,v in rec.items()if k!='record_hash'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest();r=c['envelope'];new=capture(rec,r['task_id'],r['child_id'],r['run_id']);d['items'][2]['metadata']['capture']=new;d['items'][2]['identity']['source_record_id']=new['capture_id']
  with self.assertRaises(ValueError):self.run_project(d)
 def test_unknown_parent_is_explicit_not_grouped(self):
  d=other_report();c=d['items'][2]['metadata']['capture'];r=c['envelope'];rec=r['record'];rec['parent_status']='unknown';rec['record_hash']=hashlib.sha256(json.dumps({k:v for k,v in rec.items()if k!='record_hash'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest();new=capture(rec,r['task_id'],r['child_id'],r['run_id']);d['items'][2]['metadata']['capture']=new;d['items'][2]['identity']['source_record_id']=new['capture_id'];out=self.run_project(d)
  self.assertEqual(out['counts']['unassigned'],1);self.assertIsNone(out['comments'][1]['parent_capture_id'])
 def attachment(self):
  body=next(i['metadata']['capture']['envelope']['record']for i in self.report['items']if i['metadata']['capture']['envelope']['record']['kind']=='content');ref=body['media'][0]
  from saved_media_attachments import sha
  run=str(uuid.uuid4());folder=self.root/'media-attachments'/run/('a'*64);folder.mkdir(parents=True)
  blob=b'fixture registered image bytes';asset=folder/('b'*64+'.jpg');asset.write_bytes(blob)
  side={'schema':'crowd-saved-media-attachment-v1','media_id':ref['media_id'],'platform':body['platform'],'content_id':body['content_id'],'comment_id':None,'source_record_hash':body['record_hash'],'source_url_sha256':sha(ref['url']),'run_id':run,'path':'attachments/'+'a'*64+'/'+'b'*64+'.jpg','bytes':len(blob),'asset_sha256':hashlib.sha256(blob).hexdigest(),'source_observation_sha256':'c'*64,'media_kind':'image'}
  (folder/'attachment.json').write_text(json.dumps(side));return side,folder,asset
 def test_registered_attachment_reuses_resolver_origin_separate(self):
  side,folder,asset=self.attachment();calls=[]
  def resolve(b):calls.append(b);return asset
  out=self.run_project(resolve=resolve);media=out['contents'][0]['media'][0]
  self.assertEqual(calls,[{'run_id':side['run_id'],'path':side['path']}]);self.assertEqual(media['state'],'registered_verified');self.assertNotEqual(out['contents'][0]['capture_origin']['run_id'],media['media_origin']['run_id']);self.assertEqual(media['sha256'],side['asset_sha256'])
 def test_hash_drift_duplicate_and_foreign_attachment_reject_or_omit(self):
  side,folder,asset=self.attachment();asset.write_bytes(b'changed')
  with self.assertRaises(ValueError):self.run_project(resolve=lambda b:asset)
  asset.write_bytes(b'fixture registered image bytes');other=folder.parent/('d'*64);other.mkdir();(other/'attachment.json').write_bytes((folder/'attachment.json').read_bytes())
  with self.assertRaises(ValueError):self.run_project(resolve=lambda b:asset)
  (other/'attachment.json').unlink();side['content_id']='foreign';(folder/'attachment.json').write_text(json.dumps(side));out=self.run_project();self.assertEqual(out['contents'][0]['media'][0]['state'],'reference_only')
 def test_resolver_failure_and_symlink_rejected(self):
  side,folder,asset=self.attachment()
  with self.assertRaises(ValueError):self.run_project(resolve=lambda b:(_ for _ in ()).throw(ValueError('denied')))
  raw=(folder/'attachment.json').read_bytes();(folder/'attachment.json').unlink();q=self.root/'outside';q.write_bytes(raw);(folder/'attachment.json').symlink_to(q)
  with self.assertRaises(ValueError):self.run_project()

if __name__=='__main__':unittest.main()
