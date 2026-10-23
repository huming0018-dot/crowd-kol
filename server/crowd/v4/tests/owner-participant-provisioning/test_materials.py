"""Offline PGlite feed -> original pinned Jobs/Consumer exports; no network/source."""
from pathlib import Path
import json,os,sys,tempfile,hashlib,subprocess,csv,io,copy,unittest
HERE=Path(__file__).resolve().parent
MP=HERE.parents[1]/'multiplatform'
SRC=MP
sys.path[:0]=[str(SRC),str(MP)]
from automatic_materials import write,material_context_key
from pro_ack_snapshot import canonical,extract
from material_auto_worker import process
from workbench_material_call import command
csv.field_size_limit(8*1024*1024)
GROUP=json.loads(Path(os.environ['CROWD_G08_FEED']).read_text())['groups'][0]
CONFIG=json.loads(Path(os.environ['CROWD_MATERIAL_CONFIG']).read_text())
class Tests(unittest.TestCase):
 def test_actual_pg_feed_35objects_13pages_four_formats(self):
  # These are isolated PG ACKs over original saved Pro input, NOT new production ACKs.
  self.assertEqual(len(GROUP['comment_receipts']),35);self.assertEqual(len(GROUP['comment_captures'][0]['pro_payload']['record']['pages']),13)
  with tempfile.TemporaryDirectory(prefix='g06-original-jobs-')as tmp:
   root=Path(tmp).resolve();inputs=root/'data-products/participant-pro-ack-inputs';inputs.mkdir(parents=True)
   raw=canonical(GROUP).encode();sha=hashlib.sha256(raw).hexdigest();gp=inputs/(sha+'.json');gp.write_bytes(raw);gp.chmod(0o600)
   ctx={k:GROUP[k]for k in ['task_id','subject','installation_id','dispatch_id','group_cursor']};ctx.update(schema='crowd-participant-pro-material-context-v1',group_path=str(gp),group_sha256=sha)
   key=material_context_key(ctx);state=root/'data-products/material-auto'/(key+'.json');state.parent.mkdir();write(state,{'state':'waiting','context':ctx})
   # Existing early body publication is a different immutable ACK-set context.
   early=copy.deepcopy(GROUP);early['comment_receipts']=[];early['comment_captures']=[];row=early['receipts'][-1];early['group_cursor'].update(created_at=row['created_at'],request=row['request'])
   earlyraw=canonical(early).encode();earlysha=hashlib.sha256(earlyraw).hexdigest();earlyctx={**ctx,'group_cursor':early['group_cursor'],'group_path':str(inputs/(earlysha+'.json')),'group_sha256':earlysha}
   oldkey=material_context_key(earlyctx);self.assertNotEqual(key,oldkey);oldstate=state.parent/(oldkey+'.json');write(oldstate,{'state':'ready','context':earlyctx,'publication_pointer':{'old':'preserved'}});oldbytes=oldstate.read_bytes()
   cfg={**CONFIG,'worker_script':str(SRC/'material_auto_worker.py'),'worker_sha256':hashlib.sha256((SRC/'material_auto_worker.py').read_bytes()).hexdigest(),'bridge_path':str(SRC/'material_bridge.py'),'bridge_sha256':hashlib.sha256((SRC/'material_bridge.py').read_bytes()).hexdigest(),'runtime_root':str(SRC),'runtime_cloud_sha256':hashlib.sha256((MP/'cloud_sync.py').read_bytes()).hexdigest(),'pro_snapshot_sha256':hashlib.sha256((SRC/'pro_ack_snapshot.py').read_bytes()).hexdigest(),'pro_comments_sha256':hashlib.sha256((SRC/'participant_pro_comments.py').read_bytes()).hexdigest()}
   try:process(root,state,cfg)
   except Exception:
    import shutil
    debug=Path(tempfile.mkdtemp(prefix='g08-material-debug-'))/'preserved';shutil.copytree(root,debug)
    raise
   ready=json.loads(state.read_text());self.assertEqual(ready['state'],'ready');self.assertEqual(ready['items'],1);self.assertEqual(ready['source_requests'],0)
   pointer=ready['publication_pointer'];out={fmt:subprocess.check_output(command(pointer,'read',fmt),env={**os.environ,'PYTHONPATH':str(MP)})for fmt in ('html','json','jsonl','csv')}
   report=json.loads(out['json']);capture=report['items'][0]['metadata']['capture'];self.assertEqual(capture['comment_receipts'],GROUP['comment_receipts'] if GROUP['comment_receipts']==sorted(GROUP['comment_receipts'],key=lambda x:x['request']) else sorted(GROUP['comment_receipts'],key=lambda x:x['request']));self.assertEqual(capture['comment_capture'],GROUP['comment_captures'][0]);self.assertEqual(len(capture['comment_capture']['pro_payload']['record']['objects']),35)
   rows=json.loads(out['jsonl'].decode().splitlines()[0]);self.assertEqual(rows,report['items'][0]);self.assertEqual(json.loads(next(csv.DictReader(io.StringIO(out['csv'].decode())))['record']),rows)
   self.assertIn(GROUP['comment_receipts'][0]['request'].encode(),out['html']);self.assertEqual(oldstate.read_bytes(),oldbytes)
   self.assertEqual(capture['pro_payload']['record']['media'],GROUP['receipts'][0]['pro_payload']['record']['media']);self.assertEqual(len(capture['pro_payload']['record']['media']),9)
   # Read path rechecks new validator pin; tampering is not made valid by a valid old snapshot pin.
   reqpath=Path(pointer['request']);req=json.loads(reqpath.read_text());req['pro_comments_sha256']='0'*64;reqpath.write_text(canonical(req));bad={**pointer,'request_sha256':hashlib.sha256(reqpath.read_bytes()).hexdigest()};p=subprocess.run(command(bad,'read','json'),capture_output=True,env={**os.environ,'PYTHONPATH':str(MP)});self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,b'')
if __name__=='__main__':unittest.main()
