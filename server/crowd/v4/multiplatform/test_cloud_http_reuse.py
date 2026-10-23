"""Real loopback HTTP/1.1 transport; no cloud/platform requests or engine execution."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,socket,tempfile,threading,unittest
from cloud_sync import CloudClient,CloudError,CloudOutbox,CloudWorker,DeliveryLeaseError
from test_cloud_sync import lease,row

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self):
        super().__init__(('127.0.0.1',0),Handler);self.accepted=0;self.seen=[];self.receipts={};self.lease=lease();self.mode=None;self.revoke_after_capture=False;self.revoke_after_lookup=False
    def get_request(self):
        conn,address=super().get_request();self.accepted+=1;conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);return conn,address
class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def do_POST(self):
        v=json.loads(self.rfile.read(int(self.headers['Content-Length'])));action=v['action'];p=v['payload'];self.server.seen.append((action,p,self.client_address[1]))
        status=200;value={'ok':True,'result':{'lease':self.server.lease}}
        if self.server.mode=='revoked':status=403;value={'ok':False,'error':'worker_revoked'}
        elif self.server.mode=='redirect':
            self.send_response(302);self.send_header('Location','/must-not-follow');self.send_header('Content-Length','0');self.end_headers();return
        elif action=='capture':
            e=p['envelope'];receipt={k:e[k]for k in ('capture_id','run_id','lease_epoch','task_id','child_id')};receipt.update(envelope_hash=p['envelope_hash'],status='received',source_kind='machine_api',reward_eligible=False)
            self.server.receipts[e['capture_id']]=receipt;value={'ok':True,'result':{'receipt':receipt}}
            if self.server.mode=='drop_capture_once':
                self.server.mode=None;self.close_connection=True;self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if self.server.revoke_after_capture:self.server.mode='revoked'
        elif action=='receipt':
            value={'ok':True,'result':{'receipt':self.server.receipts.get(p['capture_id'])}}
            if self.server.revoke_after_lookup:self.server.mode='revoked'
        raw=json.dumps(value).encode()
        if self.server.mode=='oversize_once':raw=b'x'*2000001;self.server.mode=None
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        if self.server.mode=='server_close':self.send_header('Connection','close');self.close_connection=True
        self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass

class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.server=Server();self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        f=self.root/'cloud.json';f.write_text(json.dumps({'endpoint':f'http://127.0.0.1:{self.server.server_port}/functions/v1/crowd-machine','worker_key':'b'*64,'project_key':'sb_publishable_synthetic'}));f.chmod(0o600);self.client=CloudClient(f,role='worker',allow_test_loopback=True)
    def tearDown(self):
        transport=getattr(self.client,'_transport',None)
        if transport is not None:transport.discard()
        self.server.shutdown();self.server.server_close();self.thread.join(2);self.temp.cleanup()
    def test_repeated_guard_requests_reuse_one_connection(self):
        for sequence in range(1,7):self.client.call('heartbeat',{'run_id':self.server.lease['run_id'],'lease_epoch':1,'sequence':sequence})
        self.assertEqual(len(self.server.seen),6);self.assertEqual(self.server.accepted,1,'six successful sequential requests must not establish six transports')
    def test_96_outbox_rows_keep_every_guard_and_ack_with_one_transport(self):
        box=CloudOutbox(self.root,self.client);box.stage_imported([dict(row(),content_id=str(i))for i in range(96)],self.server.lease)
        with box._db()as db:before=db.execute('select id,envelope,digest from captures order by rowid').fetchall()
        count=0
        def guard():
            nonlocal count;count+=1;self.client.call('heartbeat',{'run_id':self.server.lease['run_id'],'lease_epoch':1,'sequence':count})
        result=box.flush(before_send=guard);self.assertEqual((result['acknowledged'],result['pending']),(96,0));self.assertEqual(count,96);self.assertEqual([a for a,_,_ in self.server.seen],['heartbeat','capture']*96);self.assertEqual(self.server.accepted,1)
        with box._db()as db:self.assertEqual(before,db.execute('select id,envelope,digest from captures order by rowid').fetchall())
    def test_lost_ack_destroys_connection_no_resend_then_same_receipt_lookup(self):
        box=CloudOutbox(self.root,self.client);ids=box.stage_imported([row()],self.server.lease);self.server.mode='drop_capture_once'
        first=box.flush();self.assertEqual(first['pending'],1);self.assertEqual(first['errors'],['cloud_outcome_unknown']);self.assertEqual([a for a,_,_ in self.server.seen],['capture'])
        second=box.flush();self.assertEqual((second['pending'],second['acknowledged']),(0,1));self.assertEqual([a for a,_,_ in self.server.seen],['capture','receipt']);self.assertEqual(list(self.server.receipts),ids);self.assertEqual(self.server.accepted,2)
    def test_server_close_is_honored_without_request_retry(self):
        self.server.mode='server_close';self.client.call('heartbeat',{});self.client.call('heartbeat',{});self.assertEqual(len(self.server.seen),2);self.assertEqual(self.server.accepted,2)
    def test_redirect_is_not_followed_and_connection_is_discarded(self):
        self.server.mode='redirect'
        with self.assertRaisesRegex(CloudError,'cloud_redirect_denied'):self.client.call('heartbeat',{})
        self.server.mode=None;self.client.call('heartbeat',{});self.assertEqual(len(self.server.seen),2);self.assertEqual(self.server.accepted,2)
    def test_oversized_response_cannot_poison_next_message(self):
        self.server.mode='oversize_once'
        with self.assertRaisesRegex(CloudError,'cloud_response_size_limit'):self.client.call('heartbeat',{})
        self.client.call('heartbeat',{});self.assertEqual(self.server.accepted,2)
    def test_threads_do_not_share_connection_or_mix_responses(self):
        failures=[];gate=threading.Barrier(2)
        def work():
            try:
                gate.wait(2)
                for _ in range(2):self.client.call('heartbeat',{})
            except BaseException as e:failures.append(e)
            finally:
                transport=getattr(self.client,'_transport',None)
                if transport is not None:transport.discard()
        threads=[threading.Thread(target=work)for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(3);self.assertFalse(t.is_alive())
        self.assertEqual(failures,[]);self.assertEqual(len(self.server.seen),4);self.assertEqual(self.server.accepted,2)
    def test_revocation_guard_stops_next_capture(self):
        worker=CloudWorker(self.root,self.client,lambda *args:(_ for _ in()).throw(AssertionError('no source')));worker.outbox.stage_imported([dict(row(),content_id=str(i))for i in range(3)],self.server.lease);self.server.revoke_after_capture=True;state={'phase':'delivering','lease':self.server.lease,'outcome':'completed'}
        with self.assertRaises(DeliveryLeaseError):worker.outbox.flush(before_send=lambda:worker._renew_delivery(state))
        self.assertEqual([a for a,_,_ in self.server.seen],['heartbeat','capture','heartbeat']);self.assertEqual(worker.outbox.stats()['acknowledged'],1);self.assertEqual(worker.outbox.stats()['pending'],2)
    def test_legacy_unconfirmed_row_rechecks_guard_after_receipt_before_capture(self):
        worker=CloudWorker(self.root,self.client,lambda *a:(_ for _ in()).throw(AssertionError('no source')));worker.outbox.stage_imported([row()],self.server.lease)
        with worker.outbox._db()as db:
            db.execute('delete from capture_first_delivery');before=db.execute('select id,envelope,digest from captures').fetchall()
        self.server.revoke_after_lookup=True;state={'phase':'delivering','lease':self.server.lease,'outcome':'completed'}
        with self.assertRaises(DeliveryLeaseError):worker.outbox.flush(before_send=lambda:worker._renew_delivery(state))
        self.assertEqual([a for a,_,_ in self.server.seen],['heartbeat','receipt','heartbeat']);self.assertEqual(worker.outbox.stats()['pending'],1);self.assertEqual(self.server.receipts,{})
        with worker.outbox._db()as db:
            self.assertEqual(before,db.execute('select id,envelope,digest from captures').fetchall());self.assertEqual(db.execute('select attempts,quarantined from capture_delivery').fetchone(),(0,0))
if __name__=='__main__':unittest.main()
