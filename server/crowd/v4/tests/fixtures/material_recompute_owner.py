from pathlib import Path
import sys,json,importlib.util,uuid
from types import SimpleNamespace
from unittest.mock import patch
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'runtime'))
assert importlib.util.find_spec('yaml')is None,'test must use actual yaml-free Owner Python'
from dashboard import Application
from automatic_materials import AutomaticMaterials,private_json
from cloud_sync import CloudWorker
args=private_json(root/'owner-boundary.json');auto=AutomaticMaterials(root)
try:
 app=Application.__new__(Application);app.root=root;app.cloud_client=SimpleNamespace(role='owner');app.automatic_materials=auto;worker=CloudWorker(root/'cloud-outbox',object(),lambda*a:None);worker._save({'phase':'idle'});app.cloud_worker=worker
 def knowledge(a,b,body):return {'releases':[args['resolved']['release']]}if body['action']=='material_releases'else args['resolved']
 with patch('knowledge_review_call.call',side_effect=knowledge):
  if sys.argv[2]=='catalog':
   value=app.cloud('material_versions',{'pro_key':args['key']});assert value['releases']==[args['resolved']['release']]
  elif sys.argv[2]=='direct':
   value=auto.prepare_recompute(args['key'],args['old'],args['resolved']);assert value['schema']=='crowd-material-recompute-v1'
  else:
   value=app.cloud('material_recompute',{'request_id':str(uuid.uuid4()),'pro_key':args['key'],'expected_job':args['old'],'release':args['resolved']['release']});assert value['state']=='queued';assert len(private_json(worker.path)['postprocessing_runs'])==1
 assert 'yaml'not in sys.modules,'Owner must not import toolbox dependencies'
 print(json.dumps({'state':'PASS','yaml_in_owner':False,'source':0,'mode':sys.argv[2]}))
finally:auto.close()
