"""Seven offline formal regressions. Required private evidence is never bundled; no source/network."""
from pathlib import Path
import os,sys,tempfile,subprocess,json,hashlib
D=Path(__file__).resolve().parent;MP=D.parents[1]/'multiplatform'
for name in ('CROWD_G08_EVIDENCE_DIR','CROWD_G08_REAL_WIRE','CROWD_G08_MIGRATION','CROWD_TEST_TOOLS','CROWD_PRO_PYTHON','CROWD_MATERIAL_CONFIG'):
    if not os.environ.get(name):raise SystemExit(name+' is required; NOT verified, no skip/pass')
wire=Path(os.environ['CROWD_G08_REAL_WIRE']).resolve()
if not wire.is_file():raise SystemExit('CROWD_G08_REAL_WIRE missing; saved-input vertical is NOT verified')
if hashlib.sha256(wire.read_bytes()).hexdigest()!='e88d469d1a1d1345547fad50573ea22760f53a9776071e8cee1b844a31206cfa':raise SystemExit('saved input drift')
out=Path(tempfile.mkdtemp(prefix='g08-formal-offline-'));PY=os.environ['CROWD_PRO_PYTHON'];env={**os.environ,'PYTHONPATH':str(MP),'CROWD_G08_CLAIM_OUTPUT':str(out/'CLAIM.PRIVATE.json'),'CROWD_G08_FEED_OUTPUT':str(out/'FEED.PRIVATE.json'),'CROWD_G08_FEED':str(out/'FEED.PRIVATE.json')}
commands=[['node',str(D/'test_owner_authorization.mjs')],['node',str(D/'test_edge.mjs')],['node',str(MP/'test_unified_owner_ui.mjs')],['node',str(MP/'test_owner_participant_cancel_ui.mjs')],[PY,'-B',str(MP/'test_owner_participant_cancel.py')],[PY,'-B',str(D/'native_claim_contract.py'),'--wire',str(out/'CLAIM.PRIVATE.json')],[PY,'-B',str(D/'test_materials.py')]]
results=[]
for i,cmd in enumerate(commands):
    p=subprocess.run(cmd,env=env,capture_output=True,text=True);log=out/f'{i+1:02d}.log';log.write_text(p.stdout+p.stderr);results.append({'name':Path(cmd[1]if cmd[0]=='node'else cmd[2]).name,'exit':p.returncode,'log':str(log),'sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    if p.returncode:print(json.dumps({'status':'FAIL','results':results,'scratch':str(out)}));raise SystemExit(p.returncode)
r={'schema':'g08-portable-regression-v1','status':'PASS','results':results,'scratch':str(out),'source':0,'production_writes':0,'saved_input':'isolated PG ACK fixtures over saved1/35/13/9; not new real ACKs'};(out/'RESULT.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
