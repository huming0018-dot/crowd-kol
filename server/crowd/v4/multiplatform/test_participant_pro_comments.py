"""Synthetic typed comment receipts; offline, no licensed SDK/source/credentials."""
import copy,io,json,tempfile,unittest,uuid
from pathlib import Path
import participant_pro_comments as c
from participant_pro import ParticipantOutbox
from participant_native_rpc import frame,FrameIO,ProtocolError
RUN='11111111-1111-4111-8111-111111111111';TASK=7;NOTE='a'*24;COMMENT='b'*24
PROV={'local_run_id':RUN,'upstream_commit':'d'*40,'request_sha256':'e'*64,'captured_at':'2026-10-19T00:00:00Z'}
def record():
 r={'kind':'comment','platform':'xiaohongshu','content_id':NOTE,'comment_id':COMMENT,'parent_comment_id':'','origin':{'run_id':RUN},'source_kind':'mediacrawler_api','reward_eligible':False,'text':'本地合成评论😀','text_status':'reported','text_truncated':False};r['record_hash']=c.sha(r);return r
def page():return {'scope':'root','content_id':NOTE,'parent_id':None,'ids':[COMMENT],'cursor_in':'','cursor_out':'end','has_more':False,'saved':True,'checkpoint_committed':True,'embedded':False,'invalid':False,'reply_roots':{COMMENT:0},'reply_cursor_start':{COMMENT:''}}
def cap(coverage='exhausted'):return c.capture_payload(NOTE,[record()],[page()],'f'*64,{'coverage':coverage,'reason':'accessible_page_chain_ended'},PROV,TASK,{'comments':True,'replies':False,'max_comments':0})
class Tests(unittest.TestCase):
 def test_native_unlimited_not_a_local_200_object_limit(self):
  self.assertEqual(cap()['record']['resolved_native_options']['max_comments'],0);self.assertEqual(c.options({'comments':True,'replies':True,'max_comments':350})['max_comments'],350)
 def test_body_comment_seal_ids_are_distinct(self):
  ids={c.body_request(RUN,TASK,NOTE),c.request_id(RUN,TASK,NOTE,COMMENT),c.request_id(RUN,TASK,NOTE)};self.assertEqual(len(ids),3)
 def test_partial_or_unsaved_is_not_exhausted(self):
  self.assertEqual(cap('partial')['record']['coverage']['coverage'],'partial');p=page();p['saved']=False;p['checkpoint_committed']=False
  with self.assertRaises(c.CommentError):c.capture_payload(NOTE,[record()],[p],'f'*64,{'coverage':'exhausted','reason':'accessible_page_chain_ended'},PROV,TASK,{'comments':True,'replies':False,'max_comments':0})
 def test_parent_hash_and_multibyte_payload_bound(self):
  r=record();p=c.payload(r,PROV)
  with self.assertRaises(c.CommentError):c.validate_payload(p,TASK,str(uuid.uuid4()))
  p['record']['text']='tampered'
  with self.assertRaises(c.CommentError):c.validate_payload(p,TASK,c.body_request(RUN,TASK,NOTE))
  r=record();r['text']='中'*50000;r['record_hash']=c.sha({k:v for k,v in r.items()if k!='record_hash'})
  with self.assertRaises(c.CommentError):c.validate_payload(c.payload(r,PROV),TASK,c.body_request(RUN,TASK,NOTE))
 def test_unknown_child_uses_exact_receipt_lookup_no_new_source(self):
  saved={};calls=[]
  def rpc(action,p):
   calls.append(action)
   if action=='pro_comment_receipt':return {'found':p['p_request']in saved,'request':p['p_request'],'receipt':saved.get(p['p_request'])}
   r=p['p_payload']['record'];saved[p['p_request']]={'request':p['p_request'],'gate':'comment_received','inserted':True,'duplicate':False,'parent_request':p['p_parent_request'],'note_id':NOTE,'comment_id':COMMENT,'record_hash':r['record_hash'],'source_kind':'mediacrawler_pro','reward_eligible':False,'created_at':'2026-10-19T00:00:01Z'};raise TimeoutError('controlled')
  with tempfile.TemporaryDirectory()as t:
   box=ParticipantOutbox(Path(t),rpc);lease={'task_id':TASK,'lease':str(uuid.uuid4()),'installation_id':str(uuid.uuid4())};req=box.stage_comment(record(),lease,PROV,c.body_request(RUN,TASK,NOTE));self.assertEqual(box.flush(TASK),'unknown');self.assertEqual(box.flush(TASK),'delivered');self.assertEqual(calls.count('pro_comment_submit'),1);self.assertIn(req,saved);self.assertEqual(box.receipts(TASK),[])
 def test_native_frame_methods_and_whole_utf8_limit(self):
  for method in ('pro_comment_submit','pro_comment_commit','pro_comment_receipt'):
   v=frame('rpc_request',RUN,1,method=method,params={});buf=io.BytesIO();FrameIO(io.BytesIO(),buf).send(v);self.assertEqual(FrameIO(io.BytesIO(buf.getvalue()),io.BytesIO()).read(),v)
  v=frame('rpc_request',RUN,1,method='pro_comment_submit',params={'text':'😀'*66000})
  with self.assertRaises(ProtocolError):FrameIO(io.BytesIO(),io.BytesIO()).send(v)
if __name__=='__main__':unittest.main()
