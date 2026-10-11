import json,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import dashboard

class ZhihuIdentityTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve()
  self.app=dashboard.Application(self.base/'runtime');self.start=Mock(return_value={'state':'queued'})
  self.app.media_jobs=SimpleNamespace(start=self.start)
  self.file={'platform':'zhihu','content_id':'123','source_content_type':'answer','path':'output/zhihu/media/123/answer/001.jpg'}
  self.body={'kind':'content','platform':'zhihu','content_id':'123','content_type':'answer','body':'answer text'}
  self.payload={'run_id':'00000000-0000-4000-8000-000000000001','path':self.file['path'],'content_id':'123','kind':'ocr'}
 def tearDown(self):
  self.app.watchlists.close()
  self.app.owner_tasks.close()
  self.temp.cleanup()
 def process(self,records=None,file=None,payload=None):
  result={'records':records if records is not None else [self.body],'media':[file or self.file]}
  with patch.object(self.app,'media_file',return_value=self.base/'image.jpg'),patch.object(self.app,'run',return_value={'ok':True,'result':result}):
   return self.app.process_media('start',payload or self.payload)
 def test_unique_typed_source_matches(self):
  self.assertEqual(self.process(),{'state':'queued'});self.start.assert_called_once()
 def test_numeric_collision_rejected_without_job(self):
  article={**self.body,'content_type':'article','body':'article text'}
  with self.assertRaisesRegex(ValueError,'media_content_identity_ambiguous'):self.process([self.body,article])
  self.start.assert_not_called()
 def test_missing_mismatched_and_duplicate_types_rejected(self):
  for rows,file in [([self.body],{**self.file,'source_content_type':None}),([{**self.body,'content_type':None}],self.file),([{**self.body,'content_type':'article'}],self.file),([self.body,{**self.body,'body':'another version'}],self.file)]:
   with self.assertRaisesRegex(ValueError,'media_content_identity_ambiguous'):self.process(rows,file)
  self.start.assert_not_called()
 def test_content_id_not_guessed_or_user_assigned(self):
  with self.assertRaisesRegex(ValueError,'media_content_not_in_task'):self.process(payload={**self.payload,'content_id':'456'})
  self.start.assert_not_called()
 def test_other_platform_association_unchanged(self):
  file={**self.file,'platform':'xiaohongshu','path':'output/xhs/media/a.jpg'}
  row={**self.body,'platform':'xiaohongshu','content_type':None}
  self.process([row],file,{**self.payload,'path':file['path']});self.start.assert_called_once()
 def test_ambiguous_media_remains_downloadable(self):
  path=self.app.runner_root/'runs'/self.payload['run_id']/self.file['path'];path.parent.mkdir(parents=True);path.write_bytes(b'original image')
  result={'media':[self.file],'records':[self.body,{**self.body,'content_type':'article'}]}
  with patch.object(self.app,'run',return_value={'ok':True,'result':result}):
   saved=self.app.media_file({'run_id':self.payload['run_id'],'path':self.file['path']})
  self.assertEqual(saved.read_bytes(),b'original image');self.start.assert_not_called()
 def test_ui_filters_ambiguous_identity(self):
  source=(Path(__file__).parent/'media-ui.js').read_text();helper=source.split('  function contentRows(file){',1)[1].split('\n',1)[0]
  script="const assert=require('node:assert/strict');let resultData;function contentRows(file){"+helper+"\nconst file="+json.dumps(self.file)+";const body="+json.dumps(self.body)+";resultData={records:[body]};assert.equal(contentRows(file).length,1);resultData={records:[body,{...body,content_type:'article'}]};assert.equal(contentRows(file).length,0);resultData={records:[{...body,content_type:null}]};assert.equal(contentRows(file).length,0);resultData={records:[body]};assert.equal(contentRows({...file,source_content_type:null}).length,0);assert.equal(contentRows({platform:'xiaohongshu',path:'output/xhs/a.jpg'}).length,1);"
  completed=subprocess.run(['node','-e',script],capture_output=True,text=True)
  self.assertEqual(completed.returncode,0,completed.stderr)
  self.assertIn('知乎素材缺少唯一类型身份',source)
if __name__=='__main__':unittest.main()
