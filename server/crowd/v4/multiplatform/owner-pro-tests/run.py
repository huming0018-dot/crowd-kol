import os,sys,subprocess,tempfile,json,shutil
from pathlib import Path
here=Path(__file__).resolve().parent
repo=Path(os.environ.get('G14_REPO',str(here.parents[4])));support=repo/'server/crowd/v4/multiplatform';source=Path(os.environ.get('G14_SOURCE',str(here.parent)))
node=os.environ.get('NODE',shutil.which('node')or'node');python=sys.executable
out=Path(sys.argv[1]);out.mkdir(mode=0o700,parents=True,exist_ok=False)
env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(source)+os.pathsep+str(support),'G14_SOURCE':str(source),'G14_EDGE_DIR':str(repo/'server/crowd/v4/supabase/functions/crowd-machine'),'G14_CAPABILITIES':str(out/'capabilities.json'),'G14_REQUESTS_OUTPUT':str(out/'requests.json'),'G14_REQUESTS':str(out/'requests.json')}
commands=[('capabilities-json',[python,'-c',"import json,pro_executor;print(json.dumps(pro_executor.owner_task_capabilities()))"]),('ui',[node,str(here/'tests/test_routing_ui.mjs')]),('contract',[node,str(here/'tests/test_contract.mjs')]),('selection-durable',[python,str(here/'tests/test_dispatch_selection.py')]),('capability-tests',[python,str(here/'tests/test_capabilities.py')]),('old-ui',[node,str(here/'tests/legacy_owner_ui.mjs')]),('old-owner',[python,'-m','unittest','test_owner_tasks','test_owner_cancel_delivery'])]
results=[]
for name,command in commands:
 r=subprocess.run(command,env=env,cwd=out,capture_output=True,text=True)
 with (out/(name+'.log')).open('x')as f:f.write(r.stdout+r.stderr)
 results.append({'name':name,'returncode':r.returncode})
 if name=='capabilities-json' and r.returncode==0:(out/'capabilities.json').open('x').write(r.stdout)
 if r.returncode:print(json.dumps(results));sys.exit(r.returncode)
(out/'RESULT.json').open('x').write(json.dumps({'source_actions':0,'results':results},indent=2)+'\n');print(json.dumps(results))
