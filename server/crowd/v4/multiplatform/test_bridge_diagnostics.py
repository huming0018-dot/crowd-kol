import asyncio,json,sys,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
H=Path(__file__).resolve().parent;F=Path('/Users/hubowen/Desktop/桌面 - 胡博文的MacBook Pro/pushpull/crowd-kol/server/crowd/v4/multiplatform');UP=Path('/Users/hubowen/Desktop/爬虫/references/mediacrawler-pro-2026-10-14/MediaCrawlerPro-Python');sys.path[:0]=[str(H),str(F),str(UP)]
import pro_executor as p,httpx
class Tests(unittest.TestCase):
 def run_case(self,payload=None,status=200,transport=None,sink_error=None):
  bound={'cookiebridge_url':'http://127.0.0.1:8274','sign_url':'http://127.0.0.1:8989','client_id':'synthetic-bound'};events=[];sent=[];accounts=[]
  class Pool:
   _platform_name='bili'
   def add_account(self,a):accounts.append(a)
  class Sink:
   attempts=0
   def update(self,**kw):
    events.append(kw)
    if sink_error is not None and 'bridge_stage' in kw:raise sink_error
  sink=Sink();observer=[]
  async def send(client,request,**kw):
   sent.append(request.url.host)
   if transport is not None:raise transport
   return httpx.Response(status,json=payload,request=request)
  orig_bytes=httpx.Response.aiter_bytes;code=0
  with patch.object(httpx.AsyncClient,'send',send),patch.object(httpx.Client,'send',lambda *a,**k:None),patch.object(httpx.Response,'aiter_bytes',orig_bytes):
   p.install_transport_limits(httpx,{'platform':'bili','max_api_requests':12},sink,lambda r:observer.append(r.status_code))
   p.install_bound_account(Pool,bound,'bili',httpx,sink=sink)
   try:asyncio.run(Pool().load_accounts_from_cookie_bridge())
   except SystemExit as e:code=e.code
  self.assertIsNone(p._BRIDGE_FETCH.get());return code,events,sent,accounts,observer
 def test_bridge_business_errors_not_platform_logout(self):
  for code,reason in [(100,'extension_disconnected'),(101,'cookies_missing'),(102,'bridge_request_timeout'),(103,'bound_account_missing'),(2,'business_error')]:
   result,events,sent,accounts,observer=self.run_case({'isok':False,'biz_code':code,'msg':'SECRET_COOKIE=sensitive UID=123 http://private'})
   self.assertEqual(result,86);self.assertEqual(sent,['127.0.0.1']);self.assertFalse(accounts);self.assertFalse(observer)
   d=events[-1];self.assertEqual(d['bridge_reason'],reason);self.assertEqual(d['bridge_business_code'],code);self.assertNotIn('SECRET',json.dumps(events));self.assertNotIn('private',json.dumps(events))
 def test_bridge_http_auth_and_rate_errors_are_unavailable(self):
  for status in [301,401,403,429,500]:
   code,events,*_=self.run_case({'raw':'CANARY'},status);self.assertEqual(code,86);self.assertEqual(events[-1]['bridge_http_status'],status)
 def test_empty_invalid_or_malformed_credentials_not_platform_logout(self):
  cases=[[],None,{'isok':True,'data':{}},{'isok':True,'data':{'client_id':True,'platform':'bili','cookies':'SYNTHETIC'}},{'isok':True,'data':[]},{'isok':True,'data':{'client_id':'synthetic-bound','platform':'bili','cookies':''}},{'isok':True,'data':{'client_id':'synthetic-bound','platform':'bili','cookies':'SYNTHETIC','valid':False}}]
  for payload in cases:self.assertEqual(self.run_case(payload)[0],86)
 def test_other_bound_client_or_platform_remains_changed78(self):
  for delta in [{'client_id':'other'},{'platform':'xhs'}]:
   self.assertEqual(self.run_case({'isok':True,'data':{'client_id':'synthetic-bound','platform':'bili','cookies':'SYNTHETIC',**delta}})[0],78)
 def test_bridge_transport_fixed_without_exception_text(self):
  code,events,*_=self.run_case(transport=httpx.ConnectError('CANARY_cookie_secret'))
  self.assertEqual(code,86);self.assertEqual(events[-1]['bridge_reason'],'transport_error');self.assertNotIn('CANARY',json.dumps(events))
 def test_ready_cookie_does_not_emit_authenticated(self):
  code,events,sent,accounts,observer=self.run_case({'isok':True,'data':{'client_id':'synthetic-bound','platform':'bili','cookies':'SYNTHETIC'}})
  self.assertEqual(code,0);self.assertEqual(len(accounts),1);self.assertFalse(any('account_state' in x for x in events));self.assertEqual(sent,['127.0.0.1'])
 def test_diagnostic_write_failure_does_not_replace86(self):
  for error in [OSError('sensitive'),RuntimeError('sensitive')]:self.assertEqual(self.run_case({'isok':False,'biz_code':100},sink_error=error)[0],86)
 def test_budget_cancel_and_official403_remain_original(self):
  for error in [SystemExit(73),SystemExit(80),asyncio.CancelledError()]:
   if isinstance(error,asyncio.CancelledError):
    with self.assertRaises(asyncio.CancelledError):self.run_case(transport=error)
   else:self.assertEqual(self.run_case(transport=error)[0],error.code)
  sink=SimpleNamespace(attempts=0,update=lambda **kw:None)
  async def send(client,request,**kw):return httpx.Response(403,request=request)
  with patch.object(httpx.AsyncClient,'send',send),patch.object(httpx.Client,'send'),patch.object(httpx.Response,'aiter_bytes',httpx.Response.aiter_bytes):
   p.install_transport_limits(httpx,{'platform':'bili','max_api_requests':12},sink)
   async def call():
    async with httpx.AsyncClient() as c:await c.get('https://api.bilibili.com/x/web-interface/nav')
   with self.assertRaises(SystemExit) as e:asyncio.run(call())
   self.assertEqual(e.exception.code,77)
if __name__=='__main__':unittest.main()
