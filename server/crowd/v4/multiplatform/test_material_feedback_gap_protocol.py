"""Real 065 creation then selected SDK migration in a disposable workspace only."""
from pathlib import Path
from types import SimpleNamespace
import copy,json,os,sqlite3,subprocess,sys,tempfile,unittest,uuid
HERE=Path(__file__).resolve().parent
MP=Path(os.environ.get('CROWD_MP_ROOT',str(HERE)))
TARGET=Path(os.environ.get('CROWD_FEEDBACK_CANDIDATE',str(HERE)))
sys.path[:0]=[str(TARGET),str(MP)]
import material_feedback as product
from toolbox.knowledge import KnowledgeStore,AuthContext,KnowledgeError

SEED=r'''
from pathlib import Path
import json,shutil,sys
target=Path(sys.argv[1]);sys.path[:0]=[sys.argv[2],sys.argv[3]];sys.argv=[sys.argv[0]]
from importlib.metadata import version
assert version('ctfs-toolbox')=='0.6.5','legacy SDK must be the real pinned065'
from test_material_feedback_gap import Gap
case=Gap();case.setUp()
try:
 result=case.submit();row=case.service._gap_path(case.fid)
 st=case.service.store(True)
 try:assert st.get_payload(result['gap_intent'])['payload_bytes']==b'{}'
 finally:st.close()
 shutil.copytree(case.root,target)
 meta={'binding':case.binding.config,'feedback':case.feedback,'source':case.s,
       'fid':case.fid,'gap_intent':result['gap_intent'],'actor':case.service.actor}
 (target/'seed.json').write_text(json.dumps(meta));(target/'seed.json').chmod(0o600)
finally:case.doCleanups()
'''

class Protocol(unittest.TestCase):
 def test_real_legacy_empty_history_and_new_semantic_payload_without_rewrite(self):
  legacy=os.environ.get('CROWD_KNOWLEDGE_LEGACY_PYTHON')
  self.assertTrue(legacy,'CROWD_KNOWLEDGE_LEGACY_PYTHON must name the pinned065 Python; missing evidence is not a skip')
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp).resolve()/'copied065'
   result=subprocess.run([legacy,'-B','-c',SEED,str(root),str(TARGET),str(MP)],capture_output=True,text=True,timeout=30)
   self.assertEqual(result.returncode,0,result.stdout+result.stderr)
   meta=json.loads((root/'seed.json').read_text());scope=dict(zip(('tenant','project','space'),meta['binding']['scope']))
   db=root/'knowledge'/scope['tenant']/scope['project']/scope['space']/'knowledge.sqlite3'
   with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)as old:
    names=[r[0]for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_migrations'")]
    rows={n:old.execute('SELECT * FROM "'+n+'" ORDER BY rowid').fetchall()for n in names}
   auth=AuthContext(**scope,role='consumer',actor_ref=meta['actor'])
   store=KnowledgeStore(root/'knowledge',auth);store.close()
   with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)as current:
    for n,expected in rows.items():self.assertEqual(current.execute('SELECT * FROM "'+n+'" ORDER BY rowid').fetchall(),expected,n)
   binding=SimpleNamespace(config=meta['binding'],config_sha256='a'*64,authenticate=lambda _:None)
   service=product.MaterialFeedback(root,binding,None,resolver=lambda *_:copy.deepcopy(meta['source']))
   service.store=lambda readonly=False:KnowledgeStore(root/'knowledge',auth,read_only=readonly)
   self.assertEqual(service.actor,meta['actor'])
   self.assertEqual(service.gap_status({'feedback_intent':meta['fid']})['state'],'pending_gap')
   store=service.store(True)
   try:self.assertEqual(store.get_payload(meta['gap_intent'])['payload_bytes'],b'{}')
   finally:store.close()
   fid=str(uuid.uuid4());self.assertEqual(service.submit({**meta['feedback'],'intent_id':fid})['state'],'pending_feedback')
   preview=service.gap_preview({'feedback_intent':fid})
   result=service.gap_submit({'feedback_intent':fid,'expected_feedback_sha256':preview['feedback_sha256'],'gap_type':'regression-miss','title':'New gap after migration','description':'Same authorized source; SDK owns payload canonicalization','consent_private':True})
   self.assertEqual(result['state'],'pending_gap');row=product.read(service._gap_path(fid));store=service.store(True)
   try:
    payload=store.get_payload(result['gap_intent']);decoded=json.loads(payload['payload_bytes'])
    if hasattr(product.knowledge_sdk,'_canonical_gap'):
     self.assertEqual(decoded['description'],row['event']['description']);self.assertEqual(decoded['gap_id'],result['gap_intent']);self.assertNotEqual(payload['payload_hash'],product.digest(b'{}'))
    else:self.assertEqual(decoded,{})
    self.assertEqual(store.get_payload(meta['gap_intent'])['payload_bytes'],b'{}')
   finally:store.close()
   with sqlite3.connect(db)as current:current.execute('UPDATE submissions SET payload_bytes=? WHERE submission_id=?',(b'tampered',result['gap_intent']));current.commit()
   with self.assertRaises(KnowledgeError):service.gap_status({'feedback_intent':fid})

if __name__=='__main__':unittest.main()
