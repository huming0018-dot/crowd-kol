import json,hashlib,tempfile,unittest,uuid,sqlite3,os
from pathlib import Path
from pro_source_steps import project,canonical,digest
from mc_source_steps import NativeSteps,read_steps
from pro_executor import DB_NAME
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.run=Path(self.t.name).resolve()/str(uuid.uuid4());self.run.mkdir();self.rid=self.run.name;self.m={'run_id':self.rid,'executor':{'backend':'pro'},'request':{'platform':'bili'}}
  (self.run/'manifest.json').write_text(json.dumps(self.m));self.db=self.run/DB_NAME
  with sqlite3.connect(self.db) as d:d.execute('CREATE TABLE vox_crawl_observation(operation_id TEXT,platform TEXT,kind TEXT,entity_id TEXT,payload TEXT)')
  self.put('topic','1',{'video_id':'1','bvid':'BV1popx6zEe1'})
 def tearDown(self):self.t.cleanup()
 def put(self,kind,id,row):
  with sqlite3.connect(self.db) as d:d.execute('INSERT INTO vox_crawl_observation VALUES(?,?,?,?,?)',(self.rid,'bili',kind,id,json.dumps(row)))
 def pages(self,ids=['10','11'],scope='root',parent=None,saved=True):
  page={'scope':scope,'content_id':'1','parent_id':parent,'ids':ids,'cursor_in':0,'cursor_out':1,'saved':saved,'checkpoint_committed':False,'invalid':False}
  doc={'schema_version':1,'operation_id':self.rid,'pages':[page],'invalid':False};doc['sha256']=digest(doc);(self.run/'pro-pagination.json').write_text(json.dumps(doc));return doc
 def test_actual_sqlite_partial_then_full_stable_pair_and_replay(self):
  self.pages();self.put('comment','10',{'comment_id':'10','video_id':'1','parent_comment_id':'0'});before=self.db.read_bytes()
  NativeSteps(self.run,self.rid,'bili').transport('request_started',3)
  self.assertEqual(project(self.run)['facts_added'],3);steps=read_steps(self.run,self.rid);self.assertEqual([v['source_stage'] for v in steps],['request_started','content_saved','page_received','page_partially_saved']);pagehash=steps[-1]['page_sha256'];self.assertEqual(steps[-1]['saved_rows'],1);self.assertEqual(steps[-1]['api_attempts'],3);self.assertEqual(before,self.db.read_bytes());self.assertEqual(project(self.run)['facts_added'],0)
  self.put('comment','11',{'comment_id':'11','video_id':'1','parent_comment_id':'0'});self.assertEqual(project(self.run)['facts_added'],1);new=read_steps(self.run,self.rid);self.assertEqual(new[-1]['source_stage'],'page_saved');self.assertEqual(new[-1]['page_sha256'],pagehash);self.assertFalse(new[-1]['checkpoint_committed'])
 def test_page_flag_is_not_storage_proof(self):
  self.pages();project(self.run);self.assertEqual([s['source_stage'] for s in read_steps(self.run,self.rid)],['content_saved','page_received'])
 def test_wrong_parent_never_reported_as_saved(self):
  self.pages(['20'],'reply','10');self.put('comment','20',{'comment_id':'20','video_id':'1','parent_comment_id':'999'});project(self.run);self.assertNotIn('page_saved',[x['source_stage'] for x in read_steps(self.run,self.rid)])
 def test_empty_page_is_received_not_fake_saved(self):
  self.pages([]);project(self.run);self.assertNotIn('page_saved',[x['source_stage'] for x in read_steps(self.run,self.rid)])
 def test_mutable_checkpoint_does_not_change_source_page_identity(self):
  doc=self.pages();project(self.run);doc['pages'][0]['checkpoint_committed']=True;doc['pages'][0]['saved']=False;doc.pop('sha256');doc['sha256']=digest(doc);(self.run/'pro-pagination.json').write_text(json.dumps(doc));self.assertEqual(project(self.run)['facts_added'],0)
 def test_broken_hash_wrong_run_and_boolean_schema_fixed_error(self):
  for which in ('hash','operation','boolean'):
   doc=self.pages()
   if which=='hash':doc['sha256']='a'*64
   if which=='operation':doc['operation_id']=str(uuid.uuid4())
   if which=='boolean':doc['schema_version']=True
   if which!='hash':doc.pop('sha256');doc['sha256']=digest(doc)
   (self.run/'pro-pagination.json').write_text(json.dumps(doc))
   with self.assertRaises(ValueError):project(self.run)
 def test_symlink_ancestor_page_and_fifo_rejected_no_hang(self):
  target=self.run/'real';target.write_text('{}');p=self.run/'pro-pagination.json';p.symlink_to(target)
  with self.assertRaises(ValueError):project(self.run)
  p.unlink();os.mkfifo(p)
  with self.assertRaises(ValueError):project(self.run)
 def test_status_actual_caller_keeps_terminal_and_exposes_monitor_failure(self):
  import mc_runner,time
  root=self.run.parent;folder=root/'runs';folder.mkdir();self.run.rename(folder/self.rid);self.run=folder/self.rid;self.db=self.run/DB_NAME
  (self.run/'status.json').write_text(json.dumps({'run_id':self.rid,'state':'failed','executor':'mediacrawler_pro','updated_at':time.time(),'reason':'original_failure'}))
  (self.run/'phase.json').write_text(json.dumps({'source_monitor_error':'pro_steps_observation_failed'}))
  result=mc_runner.status(root,{'run_id':self.rid});self.assertEqual(result['state'],'failed');self.assertEqual(result['reason'],'original_failure');self.assertEqual(result['source_monitor_error'],'pro_steps_observation_failed');self.assertEqual(result['source_steps'][0]['source_stage'],'content_saved')
 def test_default_mc_no_journal_no_changed_behavior(self):
  self.m['executor']={'backend':'mc'};self.assertEqual(project(self.run,self.m)['facts_added'],0);self.assertFalse((self.run/'mc-source-steps.sqlite3').exists())
 def test_failed_progress_counts_are_current_storage_not_success_or_file_mutation(self):
  import mc_runner,time
  self.put('comment','10',{'comment_id':'10','video_id':'1','parent_comment_id':'0'})
  folder=self.run.parent/'runs';folder.mkdir();self.run.rename(folder/self.rid);self.run=folder/self.rid;self.db=self.run/DB_NAME
  raw={'run_id':self.rid,'state':'failed','executor':'mediacrawler_pro','updated_at':time.time(),'reason':'original_failure','item_count':0,'comment_count':0}
  status=self.run/'status.json';status.write_text(json.dumps(raw));before=status.read_bytes()
  result=mc_runner.status(folder.parent,{'run_id':self.rid})
  self.assertEqual((result['item_count'],result['comment_count']),(1,1));self.assertEqual(result['source_reported_counts'],{'item_count':0,'comment_count':0})
  self.assertEqual(result['count_basis'],'current_durable_pro_observations');self.assertEqual(result['state'],'failed');self.assertEqual(result['reason'],'original_failure');self.assertEqual(status.read_bytes(),before)
 def test_empty_valid_storage_is_known_zero_not_missing_storage(self):
  with sqlite3.connect(self.db) as db:db.execute('DELETE FROM vox_crawl_observation')
  self.assertEqual(project(self.run)['saved_counts'],{'contents':0,'comments':0})
  self.db.unlink();self.assertNotIn('saved_counts',project(self.run))
 def test_counts_do_not_bypass_broken_page_proof(self):
  doc=self.pages();doc['sha256']='0'*64;(self.run/'pro-pagination.json').write_text(json.dumps(doc))
  with self.assertRaises(ValueError):project(self.run)
 def test_invalid_counts_keep_status_failure_visible_without_crashing(self):
  import mc_runner,time
  from unittest.mock import patch
  folder=self.run.parent/'runs';folder.mkdir();self.run.rename(folder/self.rid);self.run=folder/self.rid;self.db=self.run/DB_NAME
  raw={'run_id':self.rid,'state':'failed','executor':'mediacrawler_pro','updated_at':time.time(),'reason':'original_failure','item_count':0,'comment_count':0}
  status=self.run/'status.json';status.write_text(json.dumps(raw));before=status.read_bytes();project(self.run)
  bad_values=[[],{},True,{'contents':True,'comments':1},{'contents':1,'comments':False},{'contents':-1,'comments':1},{'contents':1,'comments':100001},{'contents':1.0,'comments':1},{'contents':1,'comments':1,'extra':1}]
  for bad in bad_values:
   with self.subTest(bad=bad),patch('pro_source_steps.project',return_value={'saved_counts':bad}):result=mc_runner.status(folder.parent,{'run_id':self.rid})
   self.assertEqual(result['source_monitor_error'],'pro_steps_observation_failed');self.assertEqual(result['state'],'failed');self.assertEqual((result['item_count'],result['comment_count']),(0,0));self.assertEqual(status.read_bytes(),before)
if __name__=='__main__':unittest.main()
