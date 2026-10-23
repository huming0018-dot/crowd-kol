import io,json,logging,socket,ssl,sys,unittest,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from cloud_sync import CloudClient,CloudError
from publication_client import PublicationClient
SECRET='PRIVATE_key_header_body_url_UID_never_log'
class Response(io.BytesIO):
 def __init__(self,data=None,error=None):super().__init__(json.dumps({'ok':True,'result':{}}).encode() if data is None else data);self.error=error
 def read(self,n):
  if self.error:raise self.error
  return super().read(n)
class Opener:
 def __init__(self,error=None,response=None):self.error=error;self.response=response;self.calls=0
 def open(self,*a,**kw):
  self.calls+=1
  if self.error:raise self.error
  return self.response or Response()
class Tests(unittest.TestCase):
 def client(self,opener,role='owner'):
  c=CloudClient.__new__(CloudClient);c.role=role;c.endpoint='https://synthetic.supabase.co/functions/v1/crowd-machine';c.headers={'X-Crowd-Owner-Key':SECRET};c.opener=opener;return c
 def test_transport_fixed_classes_and_external_read_contract(self):
  cases=[(urllib.error.URLError(socket.gaierror(-2,SECRET)),'dns_resolution_failed'),(urllib.error.URLError(ssl.SSLCertVerificationError(1,SECRET)),'tls_certificate_verification_failed'),(ssl.SSLError(1,SECRET),'tls_failed'),(TimeoutError(SECRET),'timeout'),(ConnectionRefusedError(SECRET),'connection_refused'),(ConnectionResetError(SECRET),'connection_reset'),(OSError(SECRET),'transport_other')]
  for error,label in cases:
   with self.subTest(label=label):
    op=Opener(error=error)
    with self.assertLogs('cloud_sync',level='WARNING')as logs:
     with self.assertRaisesRegex(CloudError,'^cloud_read_unavailable$'):PublicationClient(self.client(op)).read('a'*64,'json','a'*64)
    self.assertEqual(op.calls,1);text=' '.join(logs.output);self.assertIn('classification='+label,text);self.assertIn('stage=connection',text);self.assertNotIn(SECRET,text);self.assertEqual(len(logs.output),1)
 def test_http_status_only_then_existing_safe_error(self):
  error=urllib.error.HTTPError('https://'+SECRET,403,SECRET,{},io.BytesIO(b'{"ok":false,"error":"principal_denied"}'));op=Opener(error=error)
  with self.assertLogs('cloud_sync',level='WARNING')as logs:
   with self.assertRaisesRegex(CloudError,'^principal_denied$'):self.client(op).call('publication_get',{})
  self.assertIn('http_status=403',logs.output[0]);self.assertIn('stage=http_response',logs.output[0]);self.assertNotIn(SECRET,str(logs.output));self.assertEqual(op.calls,1)
 def test_body_timeout_and_generic_body_read(self):
  for error,label in [(TimeoutError(SECRET),'timeout'),(OSError(SECRET),'transport_other')]:
   with self.assertLogs('cloud_sync',level='WARNING')as logs:
    with self.assertRaisesRegex(CloudError,'^cloud_read_unavailable$'):PublicationClient(self.client(Opener(response=Response(error=error)))).read('a'*64,'json','a'*64)
   self.assertIn('stage=body_read',logs.output[0]);self.assertIn('classification='+label,logs.output[0]);self.assertNotIn(SECRET,str(logs.output))
 def test_write_worker_and_other_actions_not_logged_or_retried(self):
  for role,action,expected in [('owner','publication_put','cloud_outcome_unknown'),('worker','publication_get','cloud_outcome_unknown'),('owner','task_list','cloud_read_unavailable')]:
   op=Opener(error=OSError(SECRET))
   with self.assertNoLogs('cloud_sync',level='WARNING'):
    with self.assertRaisesRegex(CloudError,'^'+expected+'$'):self.client(op,role).call(action,{})
   self.assertEqual(op.calls,1)
 def test_success_unchanged_no_log(self):
  with self.assertNoLogs('cloud_sync',level='WARNING'):self.assertEqual(self.client(Opener()).call('publication_get',{}),{})
if __name__=='__main__':unittest.main()
