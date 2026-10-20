"""Read-only rerunner: temp fixtures only; no production API/config/runtime actions."""
import json,os,subprocess,sys
from pathlib import Path
base=Path(__file__).resolve().parent
cfg=json.loads(Path(sys.argv[1] if len(sys.argv)>1 else base/'local-test-environment.json').read_text())
env=os.environ.copy();env.update({k:v for k,v in cfg.items() if k not in ('python','legacy_python')});env['PYTHONPATH']=cfg['CROWD_XHS_MP']
commands=[[cfg['python'],'-B',str(base/'test_media.py')],[cfg['CROWD_PRO_NODE'],'--experimental-vm-modules',str(base/'test_download.mjs')],[cfg['legacy_python'],'-B','-m','unittest','test_saved_media_attachments','test_pro_executor','test_pro_media_integration','test_shared_request_budget']]
for command in commands:
 result=subprocess.run(command,cwd=cfg['CROWD_XHS_MP'],env=env,timeout=60)
 if result.returncode:raise SystemExit(result.returncode)
