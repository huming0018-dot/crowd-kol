import asyncio,json,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import pro_executor as p
from mc_source_steps import NativeSteps,read_steps
from shared_request_budget import RunRequestBudget,request_fingerprint,BudgetError

class TransportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.run=Path(self.tmp.name);self.rid=str(uuid.uuid4());self.req={'source_executor':'pro','platform':'bili','max_api_requests':2};self.sink=p.ProgressSink(self.run,{'run_id':self.rid,'request':self.req});self.steps=NativeSteps(self.run,self.rid,'bili');self.original=(httpx.AsyncClient.send,httpx.Client.send,httpx.Response.aiter_bytes);self.addCleanup(self.restore)
 def restore(self):httpx.AsyncClient.send,httpx.Client.send,httpx.Response.aiter_bytes=self.original
 def install(self,callback=None):p.install_transport_limits(httpx,self.req,self.sink,debit_callback=callback,native_steps=self.steps)
 def rows(self):return read_steps(self.run,self.rid)
 def test_sync_async_actual_transport_and_no_sensitive_values(self):
  async def go():
   async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'cookie':'NEVER_RECORD'},request=r))) as c:await c.get('https://example.test/?token=NEVER_RECORD',headers={'Cookie':'NEVER_RECORD'})
  self.install();asyncio.run(go())
  with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(201,request=r))) as c:c.get('https://example.test')
  self.assertEqual([(x['source_stage'],x['api_attempts'],x['http_status']) for x in self.rows()],[('request_started',1,0),('response_received',1,200),('request_started',2,0),('response_received',2,201)])
  self.assertNotIn('NEVER_RECORD',(self.run/'mc-source-steps.sqlite3').read_bytes().decode('latin1'))
 def test_network_failure_retains_budget_no_fake_response(self):
  def fail(r):raise httpx.ConnectError('SECRET',request=r)
  self.install()
  with httpx.Client(transport=httpx.MockTransport(fail)) as c:
   with self.assertRaises(httpx.ConnectError):c.get('https://example.test')
  self.assertEqual([r['source_stage'] for r in self.rows()],['request_started','request_failed']);self.assertEqual(self.sink.attempts,1)
 def test_http_logout_records_real_response_before_exit(self):
  self.install()
  with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(401,request=r))) as c:
   with self.assertRaises(SystemExit) as e:c.get('https://example.test')
  self.assertEqual(e.exception.code,77);self.assertEqual(self.rows()[-1]['http_status'],401)
 def test_budget_denial_never_starts_request(self):
  self.install();budget=RunRequestBudget(self.run/'request-budget.json',self.rid,request_fingerprint(self.req),2);budget.debit('pro');budget.debit('pro')
  with httpx.Client(transport=httpx.MockTransport(lambda r:self.fail('must not reach transport'))) as c:
   with self.assertRaises(SystemExit) as e:c.get('https://example.test')
  self.assertEqual(e.exception.code,73);self.assertEqual(self.rows(),[])
 def test_async_cancel_records_failure_and_rethrows(self):
  async def fail(r):raise asyncio.CancelledError()
  async def go():
   async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as c:await c.get('https://example.test')
  self.install()
  with self.assertRaises(asyncio.CancelledError):asyncio.run(go())
  self.assertEqual(self.rows()[-1]['source_stage'],'request_failed')
 def test_monitor_failure_does_not_repeat_or_fail_source(self):
  self.steps.emit=lambda *a,**k:(_ for _ in ()).throw(ValueError('private error'))
  self.install();calls=[]
  with httpx.Client(transport=httpx.MockTransport(lambda r:(calls.append(1) or httpx.Response(200,request=r)))) as c:self.assertEqual(c.get('https://example.test').status_code,200)
  self.assertEqual(calls,[1]);self.assertEqual(self.steps.error,'pro_transport_monitor_failed');self.assertEqual(json.loads((self.run/'phase.json').read_text())['source_monitor_error'],'pro_steps_observation_failed')
 def test_aio_original_contract_shared_debit_and_redirect(self):
  calls=[]
  class Session:
   _retry_connection=True
   async def _request(self,*a,**kw):calls.append(kw);return SimpleNamespace(status=302)
  fake=SimpleNamespace(ClientSession=Session);budget=RunRequestBudget(self.run/'request-budget.json',self.rid,request_fingerprint(self.req),2,create=True)
  p.install_aio_transport(fake,self.req,lambda:budget.debit('pro'),self.steps)
  with self.assertRaises(BudgetError):asyncio.run(Session()._request('GET','http://unused'))
  self.assertEqual(calls,[{'allow_redirects':False}]);self.assertEqual(self.rows()[-1]['http_status'],302);self.assertEqual(budget.snapshot()['used'],1)
 def test_aio_failure_no_response_or_retry(self):
  class Session:
   async def _request(self,*a,**kw):raise RuntimeError('SECRET')
  fake=SimpleNamespace(ClientSession=Session);p.install_aio_transport(fake,self.req,lambda:1,self.steps)
  with self.assertRaises(RuntimeError):asyncio.run(Session()._request('GET','http://unused'))
  self.assertEqual([r['source_stage'] for r in self.rows()],['request_started','request_failed'])
if __name__=='__main__':unittest.main()
