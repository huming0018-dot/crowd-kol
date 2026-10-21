"""Temporary-only imports; real scanner and ResultsStore. No process/source/API."""
import base64,hashlib,importlib.util,json,os,socket,sys,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
MP=Path(__file__).resolve().parent;sys.path.insert(0,str(MP))
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('mc_zero_review',HERE/'mc_runner.py');M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
from results_store import ResultsStore
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1cAAAAASUVORK5CYII=')
class ZeroMedia(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'collector';self.rid=str(uuid.uuid4());self.run=self.root/'runs'/self.rid;self.folder=self.run/'output/xhs/media/note1';self.folder.mkdir(parents=True)
  M.write(self.run/'manifest.json',{'run_id':self.rid,'request':{'platform':'xhs'},'source':{}});M.write(self.run/'status.json',{'state':'completed'})
 def do_import(self):
  with patch.object(socket.socket,'connect',side_effect=AssertionError('network_forbidden')):
   return M.import_output(self.root,{'run_id':self.rid})
 def test_actual_empty_png_not_admitted_good_file_and_records_preserved(self):
  empty=self.folder/'failed.png';empty.write_bytes(b'');good=self.folder/'valid.png';good.write_bytes(PNG)
  j=self.run/'output/xhs/jsonl';j.mkdir();(j/'detail_contents_saved.jsonl').write_text(json.dumps({'note_id':'note1','title':'原标题','desc':'正文全文🙂'})+'\n');(j/'detail_comments_saved.jsonl').write_text(json.dumps({'note_id':'note1','comment_id':'c1','content':'原评论'})+'\n')
  result=self.do_import();self.assertEqual([x['path'] for x in result['media']],[str(good.relative_to(self.run))]);self.assertEqual(result['summary']['rejected_media_files'],1);self.assertEqual(result['rejected_media_files'],1);self.assertEqual((empty.stat().st_size,empty.read_bytes()),(0,b''));self.assertEqual(good.read_bytes(),PNG)
  self.assertEqual([(x['kind'],x.get('title'),x.get('body'),x.get('text')) for x in result['records']],[('comment',None,None,'原评论'),('content','原标题','正文全文🙂',None)])
  before=[x['record_hash']for x in result['records']];store=ResultsStore(Path(self.tmp.name)/'results');saved=store.ingest(result);self.assertEqual(saved['added_versions'],3);self.assertNotIn(hashlib.sha256(b'').hexdigest(),json.dumps(store.list_results({})))
  replay=self.do_import();self.assertEqual(replay,result);self.assertEqual([x['record_hash']for x in replay['records']],before);self.assertTrue(store.ingest(replay)['duplicate_import'])
 def test_only_empty_files_keep_originals_without_valid_media(self):
  files=[]
  for ext in ('.jpg','.jpeg','.png','.webp','.gif','.mp4','.m4a','.mp3','.aac','.wav','.webm','.flv','.mov'):
   p=self.folder/('empty'+ext);p.write_bytes(b'');files.append(p)
  result=self.do_import();self.assertEqual(result['media'],[]);self.assertEqual(result['summary']['media_files'],0);self.assertEqual(result['summary']['rejected_media_files'],len(files));self.assertEqual(result['records'],[]);self.assertTrue(all(p.is_file()and p.stat().st_size==0 for p in files))
 def test_nonempty_file_metadata_and_bounds_unchanged(self):
  p=self.folder/'valid.png';p.write_bytes(PNG);r=self.do_import();self.assertEqual(r['summary']['rejected_media_files'],0);self.assertEqual(r['media'][0]['bytes'],len(PNG));self.assertEqual(r['media'][0]['sha256'],hashlib.sha256(PNG).hexdigest());self.assertEqual(r['media'][0]['status'],'downloaded_by_external_executor');self.assertFalse(r['media'][0]['reward_eligible'])
  with open(self.folder/'oversize.mp4','wb')as f:f.truncate(26214401)
  with self.assertRaisesRegex(M.BridgeError,'media_import_byte_limit'):self.do_import()
if __name__=='__main__':unittest.main()
