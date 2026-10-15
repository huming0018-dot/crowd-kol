import unittest,tempfile,sys,uuid,json,os,multiprocessing,asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from shared_request_budget import RunRequestBudget,request_fingerprint,BudgetError,install_hybrid_transport_limits
import pro_executor as p

def race(path,rid,digest,q):
 b=RunRequestBudget(path,rid,digest,12);n=0
 while True:
  try:b.debit('media');n+=1
  except SystemExit as e:assert e.code==73;break
 q.put(n)
class Budget(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.path=self.root/'request-budget.json';self.rid=str(uuid.uuid4());self.request={'source_executor':'pro','platform':'bili','max_api_requests':12};self.hash=request_fingerprint(self.request);self.b=RunRequestBudget(self.path,self.rid,self.hash,12,create=True)
 def tearDown(self):self.t.cleanup()
 def test_pro_and_child_share_without_reset_or_refund(self):
  for _ in range(8):self.b.debit('pro')
  child=RunRequestBudget(self.path,self.rid,self.hash,12)
  for _ in range(4):child.debit('media')
  with self.assertRaises(SystemExit) as e:child.debit('media')
  self.assertEqual(e.exception.code,73);self.assertEqual(RunRequestBudget(self.path,self.rid,self.hash,12,create=True).snapshot()['used'],12);self.assertEqual(self.b.snapshot()['stages'],['pro']*8+['media']*4)
 def test_eight_processes_exact12_admissions(self):
  ctx=multiprocessing.get_context('fork');q=ctx.Queue();procs=[ctx.Process(target=race,args=(self.path,self.rid,self.hash,q)) for _ in range(8)]
  for x in procs:x.start()
  for x in procs:x.join(10);self.assertEqual(x.exitcode,0)
  self.assertEqual(sum(q.get(timeout=2) for _ in procs),12);self.assertEqual(self.b.snapshot()['used'],12)
 def test_wrong_binding_and_malformed_state_fail_closed(self):
  for rid,hash_,limit in [(str(uuid.uuid4()),self.hash,12),(self.rid,'a'*64,12),(self.rid,self.hash,13)]:
   with self.assertRaises(BudgetError):RunRequestBudget(self.path,rid,hash_,limit)
  value=self.b.snapshot();value['used']=True;self.path.write_text(json.dumps(value))
  with self.assertRaises(BudgetError):self.b.snapshot()
 def test_symlink_fifo_and_permissions_rejected(self):
  self.path.unlink();self.path.symlink_to('/nonexistent/private')
  with self.assertRaises(BudgetError):self.b.snapshot()
  self.path.unlink();os.mkfifo(self.path)
  with self.assertRaises(BudgetError):self.b.snapshot()
  self.path.unlink();RunRequestBudget(self.path,self.rid,self.hash,12,create=True);self.path.chmod(0o644)
  with self.assertRaises(BudgetError):self.b.snapshot()
 def test_interrupted_write_never_refunds_or_auto_recreates(self):
  with patch('shared_request_budget.os.write',side_effect=OSError('private')):
   with self.assertRaises(BudgetError):self.b.debit('pro')
  self.assertEqual(self.b.snapshot()['used'],0) # failure happened before persistence AND before any source
  self.path.write_bytes(b'{"partial')
  with self.assertRaises(BudgetError):RunRequestBudget(self.path,self.rid,self.hash,12,create=True)
 def test_real_pro_httpx_guard_and_media_three_transports_share(self):
  import httpx,requests
  calls=[]
  async def send(client,request,*a,**kw):calls.append('httpx');return httpx.Response(200,json={'code':0,'data':{}},request=request)
  def req(client,*a,**kw):calls.append('requests');return SimpleNamespace(status_code=200)
  class Aio:
   async def _request(self,*a,**kw):calls.append('aio');return SimpleNamespace(status=200)
  original_bytes=httpx.Response.aiter_bytes;original_sync=httpx.Client.send
  manifest={'run_id':self.rid,'request':self.request};sink=p.ProgressSink(self.root,manifest)
  try:
   with patch.object(httpx.AsyncClient,'send',send),patch.object(requests.sessions.Session,'request',req):
    p.install_transport_limits(httpx,self.request,sink)
    async def source():
     async with httpx.AsyncClient(trust_env=False) as client:await client.get('https://isolated.invalid/source')
    asyncio.run(source());self.assertEqual(self.b.snapshot()['used'],1)
  finally:httpx.Response.aiter_bytes=original_bytes;httpx.Client.send=original_sync
  # Separate process semantics: original HTTPX/requests/AIO in the media child.
  try:
   with patch.object(httpx.AsyncClient,'send',send),patch.object(requests.sessions.Session,'request',req):
    install_hybrid_transport_limits(httpx,requests,SimpleNamespace(ClientSession=Aio),self.request,sink,self.b)
    async def media():
     async with httpx.AsyncClient(trust_env=False) as client:
      response=await client.get('https://isolated.invalid/media');await response.aread()
     await Aio()._request('GET','https://isolated.invalid/aio')
    asyncio.run(media());requests.Session().get('https://isolated.invalid/request')
   self.assertEqual(self.b.snapshot()['used'],4);self.assertEqual(self.b.snapshot()['stages'],['pro','media','media','media']);self.assertEqual(calls,['httpx','httpx','aio','requests'])
  finally:httpx.Response.aiter_bytes=original_bytes;httpx.Client.send=original_sync
 def test_exhausted_real_guard_never_reaches_transport(self):
  import httpx,requests
  calls=[]
  async def send(*args,**kwargs):calls.append(True);raise AssertionError('source must not run')
  for _ in range(12):self.b.debit('pro')
  sink=p.ProgressSink(self.root,{'run_id':self.rid,'request':self.request});original_bytes=httpx.Response.aiter_bytes;original_sync=httpx.Client.send;original_requests=requests.sessions.Session.request
  try:
   with patch.object(httpx.AsyncClient,'send',send):
    install_hybrid_transport_limits(httpx,requests,None,self.request,sink,self.b)
    async def attempted():
     async with httpx.AsyncClient(trust_env=False) as client:await client.get('https://isolated.invalid/blocked')
    with self.assertRaises(SystemExit) as error:asyncio.run(attempted())
    self.assertEqual(error.exception.code,73);self.assertEqual(calls,[]);self.assertEqual(self.b.snapshot()['used'],12)
  finally:httpx.Response.aiter_bytes=original_bytes;httpx.Client.send=original_sync;requests.sessions.Session.request=original_requests
 def test_failed_real_transport_still_consumes_reservation(self):
  import httpx
  calls=[]
  async def send(*args,**kwargs):calls.append(True);raise httpx.ConnectError('synthetic private failure')
  sink=p.ProgressSink(self.root,{'run_id':self.rid,'request':self.request});original_bytes=httpx.Response.aiter_bytes;original_sync=httpx.Client.send
  try:
   with patch.object(httpx.AsyncClient,'send',send):
    p.install_transport_limits(httpx,self.request,sink)
    async def attempted():
     async with httpx.AsyncClient(trust_env=False) as client:await client.get('https://isolated.invalid/failed')
    with self.assertRaises(httpx.ConnectError):asyncio.run(attempted())
   self.assertEqual(calls,[True]);self.assertEqual(self.b.snapshot()['used'],1)
  finally:httpx.Response.aiter_bytes=original_bytes;httpx.Client.send=original_sync
 def test_actual_pro_aio_wrapper_same_debit_and_no_follow(self):
  import ast
  node=next(n for n in ast.walk(ast.parse(Path(p.__file__).read_text())) if isinstance(n,ast.AsyncFunctionDef) and n.name=='bounded_aio');calls=[];headers=[]
  def debit():calls.append('debit');return self.b.debit('pro')
  async def old(client,*a,**kw):headers.append(kw);return SimpleNamespace(status=302)
  scope={'request':self.request,'debit':debit,'old_aio':old};exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'actual_pro_aio','exec'),scope)
  with self.assertRaises(BudgetError):asyncio.run(scope['bounded_aio'](SimpleNamespace(_retry_connection=True),'GET','https://isolated.invalid',allow_redirects=True))
  self.assertEqual(calls,['debit']);self.assertEqual(headers,[{'allow_redirects':False}]);self.assertEqual(self.b.snapshot()['used'],1)
if __name__=='__main__':unittest.main()
