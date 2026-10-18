import io,json,unittest,urllib.error
from cloud_sync import CloudClient,CloudError

class TransportTests(unittest.TestCase):
    def client(self,blob):
        class Opener:
            def open(self,*args,**kwargs):return io.BytesIO(blob)
        client=object.__new__(CloudClient);client.role='owner';client.endpoint='https://example.supabase.co/functions/v1/crowd-machine';client.headers={};client.opener=Opener()
        return client
    def test_feed_accepts_whole_group_above_old_response_limit(self):
        value={'data':'x'*2500000};blob=json.dumps({'ok':True,'result':value}).encode()
        self.assertEqual(self.client(blob).call('participant_pro_receipts'),value)
        with self.assertRaisesRegex(CloudError,'cloud_response_size_limit'):self.client(blob).call('task_list')
    def test_over_limit_is_not_truncated_and_no_retry(self):
        blob=json.dumps({'ok':True,'result':{'data':'x'*(8*1024*1024+129)}}).encode()
        with self.assertRaisesRegex(CloudError,'cloud_response_size_limit'):self.client(blob).call('participant_pro_receipts')
    def test_feed_network_error_is_read_unavailable(self):
        class Opener:
            def open(self,*args,**kwargs):raise urllib.error.URLError('offline')
        client=self.client(b'');client.opener=Opener()
        with self.assertRaisesRegex(CloudError,'cloud_read_unavailable'):client.call('participant_pro_receipts')

if __name__=='__main__':unittest.main()
