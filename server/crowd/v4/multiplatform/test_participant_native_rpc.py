import io,json,socket,struct,threading,unittest,uuid
from participant_native_rpc import FrameIO,NativeMux,NativeTransport,ProtocolError,frame
U=lambda:str(uuid.uuid4())
class Tests(unittest.TestCase):
 def test_utf8_full_frame_limit_and_exact_schema(self):
  s=U();v=frame('rpc_request',s,7,method='pro_submit',params={'p_payload':{'body':'中'*1500}})
  b=io.BytesIO();FrameIO(io.BytesIO(),b).send(v);self.assertGreater(len(b.getvalue()),4096)
  self.assertEqual(FrameIO(io.BytesIO(b.getvalue()),io.BytesIO()).read(),v)
  with self.assertRaises(ProtocolError):FrameIO(io.BytesIO(),io.BytesIO()).send(frame('rpc_request',s,7,method='pro_submit',params={'body':'中'*90000}))
  bad={**v,'token':'bad'}
  with self.assertRaises(ProtocolError):FrameIO(io.BytesIO(),io.BytesIO()).send(bad)
 def test_whole_envelope_exact_limit_including_canonical_and_multibyte(self):
  v=frame('rpc_request',U(),7,method='pro_submit',params={'record':'中文'*10000,'canonical_record':'中文'*10000,'pad':''})
  def encoded(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
  v['params']['pad']='x'*(262144-len(encoded(v)));self.assertEqual(len(encoded(v)),262144)
  b=io.BytesIO();FrameIO(io.BytesIO(),b).send(v);self.assertEqual(len(b.getvalue()),262148)
  v['params']['pad']+='中'
  with self.assertRaises(ProtocolError):FrameIO(io.BytesIO(),io.BytesIO()).send(v)
 def test_foreign_session_and_repeated_result_close_channel(self):
  for kind in ('session','duplicate'):
   a,b=socket.socketpair();sid=U();mux=NativeMux(FrameIO(a.makefile('rb',buffering=0),a.makefile('wb',buffering=0)),sid,7,timeout=.2);remote=FrameIO(b.makefile('rb',buffering=0),b.makefile('wb',buffering=0));mux.start()
   if kind=='session':remote.send(frame('pro_status',U(),7,run_id=None))
   else:remote.send(frame('rpc_result',sid,7,id=U(),ok=True,result={}))
   self.assertTrue(mux.disconnected.wait(.5));a.close();b.close()
 def test_newer_stop_epoch_revokes_original_port_without_rpc(self):
  a,b=socket.socketpair();sid=U();mux=NativeMux(FrameIO(a.makefile('rb',buffering=0),a.makefile('wb',buffering=0)),sid,7);remote=FrameIO(b.makefile('rb',buffering=0),b.makefile('wb',buffering=0));mux.start()
  remote.send(frame('pro_stop',sid,8,run_id=None));self.assertEqual(mux.commands.get(timeout=.5)['epoch'],8);self.assertTrue(mux.stopped.is_set())
  with self.assertRaises(ProtocolError):mux.call('pro_guard',{})
  mux.close();a.close();b.close()
 def test_short_pipe_writes_keep_whole_frame(self):
  class Short(io.BytesIO):
   def write(self,b):return super().write(b[:7])
  out=Short();v=frame('rpc_request',U(),7,method='pro_submit',params={'body':'中'*2000})
  FrameIO(io.BytesIO(),out).send(v);self.assertEqual(FrameIO(io.BytesIO(out.getvalue()),io.BytesIO()).read(),v)
 def test_truncated_duplicate_foreign_frames(self):
  for raw in (b'\x01',struct.pack('<I',10)+b'{}',struct.pack('<I',262145)):
   with self.assertRaises(ProtocolError):FrameIO(io.BytesIO(raw),io.BytesIO()).read()
  raw=b'{"schema":"a","schema":"b"}'
  with self.assertRaises(ProtocolError):FrameIO(io.BytesIO(struct.pack('<I',len(raw))+raw),io.BytesIO()).read()
 def test_mux_parallel_child_and_parent_results_do_not_cross(self):
  a,b=socket.socketpair();session=U();port=FrameIO(a.makefile('rb',buffering=0),a.makefile('wb',buffering=0));remote=FrameIO(b.makefile('rb',buffering=0),b.makefile('wb',buffering=0));mux=NativeMux(port,session,7);mux.start()
  answers={}
  ts=[threading.Thread(target=lambda n=n:answers.__setitem__(n,mux.call('pro_status',{'n':n}))) for n in range(2)]
  for t in ts:t.start()
  r=[remote.read(),remote.read()]
  for x in reversed(r):remote.send(frame('rpc_result',session,7,id=x['id'],ok=True,result={'n':x['params']['n']}))
  for t in ts:t.join(1)
  self.assertEqual(answers,{0:{'n':0},1:{'n':1}});mux.close();a.close();b.close()
 def test_stop_disconnect_blocks_new_rpc(self):
  a,b=socket.socketpair();session=U();mux=NativeMux(FrameIO(a.makefile('rb',buffering=0),a.makefile('wb',buffering=0)),session,7);mux.start();mux.stop()
  with self.assertRaises(ProtocolError):mux.call('pro_guard',{})
  mux.close();a.close();b.close()
if __name__=='__main__':unittest.main()
