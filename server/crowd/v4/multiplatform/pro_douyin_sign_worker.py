"""Private stdin, installed licensed JS through the audited signer loader; no listener."""
import asyncio,json,os,signal,sys,threading,time
from pathlib import Path

def main():
 if len(sys.argv)!=3 or sys.argv[1]!="_credential_child":raise ValueError()
 fd=int(sys.argv[2])
 parent=os.getppid();group=os.getpgrp();done=threading.Event()
 def guardian():
  end=time.monotonic()+10
  while not done.wait(.1):
   if os.getppid()!=parent or time.monotonic()>end:
    os.killpg(group,signal.SIGKILL);return
 threading.Thread(target=guardian,daemon=True).start()
 try:
  raw=sys.stdin.buffer.read(16385)
  if len(raw)>16384:raise ValueError()
  payload=json.loads(raw)
  if type(payload) is not dict or set(payload)!={'source_root','uri','query_params','user_agent'}:raise ValueError()
  sys.path.insert(0,str(Path(__file__).parent))
  from pro_signer_server import build_application
  async def execute():
   app=await build_application(Path(payload['source_root']))
   from params.douyin_sign import DouyinSignRequest
   from apis.douyin import dy_sign_logic
   # Licensed pure JS uses query + UA only. No Cookie enters this worker.
   req=DouyinSignRequest(uri=payload['uri'],query_params=payload['query_params'],user_agent=payload['user_agent'],cookies='pure-js-no-credential-input')
   result=await dy_sign_logic.sign(req)
   if app.sign_gate.signs!=1 or app.sign_gate.failed:raise ValueError()
   return {'a_bogus':result.a_bogus}
  value=asyncio.run(execute())
  data=json.dumps(value).encode()
  if len(data)>4096:raise ValueError()
  with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush()
 finally:done.set()
if __name__=='__main__':
 try:main()
 except BaseException:sys.stderr.write('pro_signer_unavailable\n');raise SystemExit(86)
