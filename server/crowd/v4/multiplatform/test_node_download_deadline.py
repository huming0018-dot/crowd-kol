"""Bounded real subprocess/TCP fault cases; never downloads platform data."""
import contextlib,io,json,os,signal,subprocess,sys,tempfile,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock,patch
import portable_node as P
URL='https://nodejs.org/download/release/'+P.VERSION+'/node-'+P.VERSION+'-linux-arm64.tar.gz'
RUN=subprocess.run
POP=subprocess.Popen
@contextlib.contextmanager
def drip_server():
 counts=[]
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def do_GET(self):
   counts.append(1);self.send_response(200);self.send_header('Content-Length','40');self.end_headers()
   try:
    for _ in range(40):self.wfile.write(b'x');self.wfile.flush();time.sleep(.03)
   except (BrokenPipeError,ConnectionResetError):pass
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 try:yield server.server_port,counts
 finally:server.shutdown();server.server_close();thread.join()
def injected_worker(args,pid,port=None,delay=0):
 # Only test transport is replaced. Real product worker and stdlib subprocess
 # timeout/kill/wait execute; original official request URL stays unchanged.
 code='import os,sys,time,urllib.request,runpy;from pathlib import Path;Path('+repr(str(pid))+').write_text(str(os.getpid()));time.sleep('+str(delay)+');'
 if port is not None:
  code+='''
real=urllib.request.build_opener(urllib.request.ProxyHandler({}))
class BoundOpener:
 def open(self,request,timeout):
  response=real.open('http://127.0.0.1:PORT/',timeout=timeout);response.url=request.full_url;return response
urllib.request.build_opener=lambda *a:BoundOpener()
'''.replace('PORT',str(port))
 code+='sys.argv='+repr(args[2:])+';runpy.run_path('+repr(args[2])+',run_name="__main__")'
 return [sys.executable,'-I','-c',code]
def dead(pid):
 try:os.kill(pid,0)
 except ProcessLookupError:return True
 return False
class Tests(unittest.TestCase):
 def test_actual_tcp_drip_deadline_kills_and_reaps_one_child(self):
  with tempfile.TemporaryDirectory()as d,drip_server()as(port,counts):
   pid=Path(d)/'pid';calls=[]
   def run(args,**kw):calls.append(args);return POP(injected_worker(args,pid,port),**kw)
   start=time.monotonic()
   with patch.object(P,'DOWNLOAD_DEADLINE',.25),patch.object(P.subprocess,'Popen',side_effect=run),self.assertRaisesRegex(ValueError,'node_download_deadline'):P.fetch(URL)
   self.assertLess(time.monotonic()-start,.7);self.assertEqual(counts,[1]);self.assertEqual(len(calls),1)
   self.assertEqual(calls[0][:2],[sys.executable,'-I']);self.assertEqual(calls[0][3:],['--fetch-worker',URL]);self.assertTrue(dead(int(pid.read_text())))
 def test_preconnect_block_is_inside_total_deadline(self):
  with tempfile.TemporaryDirectory()as d:
   pid=Path(d)/'pid'
   with patch.object(P,'DOWNLOAD_DEADLINE',.15),patch.object(P.subprocess,'Popen',side_effect=lambda args,**kw:POP(injected_worker(args,pid,delay=5),**kw)),self.assertRaisesRegex(ValueError,'node_download_deadline'):P.fetch(URL)
   self.assertTrue(dead(int(pid.read_text())))
 def test_parent_keyboard_interrupt_reaps_owned_child(self):
  with tempfile.TemporaryDirectory()as d:
   pid=Path(d)/'pid';finished=threading.Event()
   def interrupt():
    for _ in range(200):
     if pid.exists():os.kill(os.getpid(),signal.SIGINT);return
     if finished.wait(.01):return
   thread=threading.Thread(target=interrupt);thread.start()
   try:
    with patch.object(P.subprocess,'Popen',side_effect=lambda args,**kw:POP(injected_worker(args,pid,delay=5),**kw)),self.assertRaises(KeyboardInterrupt):P.fetch(URL)
   finally:finished.set();thread.join()
   self.assertTrue(dead(int(pid.read_text())))
 def test_worker_has_independent_deadline_if_parent_stops_waiting(self):
  code='import sys,time;sys.path.insert(0,'+repr(str(Path(P.__file__).parent))+');import portable_node as P;P.DOWNLOAD_DEADLINE=.15;P._download=lambda url:time.sleep(5);raise SystemExit(P._fetch_worker('+repr(URL)+'))'
  start=time.monotonic();r=RUN([sys.executable,'-I','-c',code],capture_output=True,timeout=2)
  self.assertEqual(r.returncode,-signal.SIGALRM);self.assertLess(time.monotonic()-start,.7);self.assertEqual(r.stdout,b'')
 def test_fixed_urls_and_finite_errors_no_raw_stderr_or_retry(self):
  with patch.object(P.subprocess,'Popen')as run:
   for value in('http://nodejs.org/file','https://elsewhere.invalid/file',URL+'?secret=x',None):
    with self.assertRaisesRegex(ValueError,'node_download_url_invalid'):P.fetch(value)
   run.assert_not_called()
  def completed(status,raw):
   child=Mock();child.returncode=status;child.communicate.return_value=(raw,None);child.__enter__=Mock(return_value=child);child.__exit__=Mock(return_value=False);return child
  for status,reason in[(3,'node_download_redirected'),(4,'node_archive_too_large'),(2,'node_download_failed')]:
   with patch.object(P.subprocess,'Popen',return_value=completed(status,b'raw-sensitive'))as run,self.assertRaisesRegex(ValueError,reason):P.fetch(URL)
   self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.kwargs['stdin'],subprocess.DEVNULL);self.assertEqual(run.call_args.kwargs['stderr'],subprocess.DEVNULL)
  with patch.object(P.subprocess,'Popen',return_value=completed(0,b'12345')),patch.object(P,'MAX_ARCHIVE',4),self.assertRaisesRegex(ValueError,'node_archive_too_large'):P.fetch(URL)
 def test_process_setup_consumes_same_deadline_budget(self):
  child=Mock();child.returncode=0;child.communicate.return_value=(b'bytes',None);child.__enter__=Mock(return_value=child);child.__exit__=Mock(return_value=False)
  with patch.object(P,'DOWNLOAD_DEADLINE',1),patch.object(P.time,'monotonic',side_effect=[10,10.4]),patch.object(P.subprocess,'Popen',return_value=child):self.assertEqual(P.fetch(URL),b'bytes')
  self.assertAlmostEqual(child.communicate.call_args.kwargs['timeout'],.6)
 def test_original_tls_opener_redirect_and_byte_bound_preserved(self):
  response=Mock();response.url=URL;response.read.return_value=b'original';response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False);opener=Mock();opener.open.return_value=response
  with patch.object(P.urllib.request,'build_opener',return_value=opener)as build:
   self.assertEqual(P._download(URL),b'original');self.assertIsInstance(build.call_args.args[0],P.NoRedirect);self.assertEqual(opener.open.call_args.args[0].full_url,URL);self.assertEqual(opener.open.call_args.kwargs['timeout'],120);self.assertEqual(response.read.call_args.args,(P.MAX_ARCHIVE+1,))
   response.url=URL+'?changed'
   with self.assertRaisesRegex(ValueError,'node_download_redirected'):P._download(URL)
  with self.assertRaisesRegex(ValueError,'node_download_redirected'):P.NoRedirect().redirect_request(None,None,None,None,None,None)
 def test_deadline_keeps_unknown_intent_and_cannot_retry_or_commit_late(self):
  with tempfile.TemporaryDirectory()as d:
   helper=Path(d).resolve();helper.chmod(0o700);pid=helper/'child-pid'
   with patch.object(P,'DOWNLOAD_DEADLINE',.15),patch.object(P.subprocess,'Popen',side_effect=lambda args,**kw:POP(injected_worker(args,pid,delay=5),**kw)),self.assertRaisesRegex(ValueError,'node_download_deadline'):P.prepare(helper,arch='arm64',system='linux',fetch=P.fetch)
   intent=next(helper.rglob('INTENT.json'));before=intent.read_bytes();self.assertFalse(list(helper.rglob('RESULT.json')));self.assertTrue(dead(int(pid.read_text())))
   with self.assertRaisesRegex(ValueError,'node_attempt_unknown'):P.prepare(helper,arch='arm64',system='linux',fetch=lambda _:self.fail('unknown retried'))
   self.assertEqual(intent.read_bytes(),before);self.assertFalse(list(helper.rglob('archive.tar.gz')))
if __name__=='__main__':unittest.main()
