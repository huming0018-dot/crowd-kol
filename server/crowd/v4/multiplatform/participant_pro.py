"""Participant task adapter. Original Pro owns acquisition; original RPC owns acceptance.

No participant JWT, Cookie, browser proof or reward is synthesized here. Delivery uses
CloudOutbox's existing private SQLite/transaction primitive, in a separate table so
machine captures and their immutable unknown outcomes remain untouched.
"""
import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
import mc_runner
from cloud_sync import CloudOutbox

class ParticipantError(ValueError):pass

def digest(value):return hashlib.sha256(mc_runner.canonical(value).encode()).hexdigest()
def require(ok,code):
    if not ok:raise ParticipantError(code)
def uuid_value(v):
    try:require(str(uuid.UUID(v))==v,'invalid_participant_uuid')
    except (ValueError,AttributeError,TypeError):raise ParticipantError('invalid_participant_uuid') from None
    return v

def claim_scope(value,task_id,installation):
    require(isinstance(value,dict) and value.get('source_executor')=='mediacrawler_pro' and value.get('reward_eligible') is False,'participant_claim_invalid')
    task=value.get('task');grant=value.get('acceptance_supplement')
    require(isinstance(task,dict) and type(task.get('id')) is int and task['id']==task_id,'participant_claim_invalid')
    require(isinstance(grant,dict) and set(grant)=={'schema','id','task_id','installation_id','baseline_received','extra_limit','remaining','target'},'participant_batch_invalid')
    require(grant['schema']=='crowd-acceptance-batch-v1' and grant['task_id']==task_id and grant['installation_id']==installation,'participant_batch_invalid')
    uuid_value(grant['id']);uuid_value(task.get('lease_token'))
    for k in ('baseline_received','extra_limit','remaining','target'):require(type(grant[k]) is int,'participant_batch_invalid')
    require(grant['baseline_received']>=0 and 1<=grant['extra_limit']<=100 and grant['target']==grant['baseline_received']+grant['extra_limit'] and 0<=grant['remaining']<=grant['extra_limit'],'participant_batch_invalid')
    require(type(task.get('received')) is int and task.get('target')==grant['target'] and task['received']==grant['target']-grant['remaining'],'participant_batch_invalid')
    return task,grant

class ParticipantOutbox(CloudOutbox):
    REJECTIONS=frozenset({'invalid_envelope','request_reused','invalid_pro_payload','invalid_pro_record',
        'record_hash_mismatch','invalid_timestamp','unrelated_note','pro_not_selected','task_full',
        'detail_not_admitted','safety_pause','test_completed'})
    def __init__(self,root,rpc):
        super().__init__(root,rpc)
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS participant_delivery(request TEXT PRIMARY KEY, task INTEGER NOT NULL, content_id TEXT NOT NULL, params TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT, UNIQUE(task,content_id))')
            db.execute('CREATE TABLE IF NOT EXISTS participant_runs(task INTEGER PRIMARY KEY, state TEXT NOT NULL, run_id TEXT, context TEXT NOT NULL)')
    def stage(self,record,lease,provenance):
        require(isinstance(record,dict) and record.get('kind')=='content' and record.get('platform')=='xiaohongshu' and record.get('source_kind')=='mediacrawler_api' and record.get('reward_eligible') is False,'participant_record_invalid')
        require(re.fullmatch('[a-f0-9]{24}',str(record.get('content_id',''))) is not None,'participant_record_invalid')
        canonical=mc_runner.canonical({k:v for k,v in record.items() if k!='record_hash'})
        sha=hashlib.sha256(canonical.encode()).hexdigest();require(record.get('record_hash')==sha,'participant_record_hash_invalid')
        require(set(provenance)=={'local_run_id','upstream_commit','request_sha256','captured_at'},'participant_provenance_invalid')
        uuid_value(provenance['local_run_id']);uuid_value(lease['lease']);uuid_value(lease['installation_id'])
        require(type(lease['task_id']) is int and lease['task_id']>0 and re.fullmatch('[a-f0-9]{40}',provenance['upstream_commit']) and re.fullmatch('[a-f0-9]{64}',provenance['request_sha256']),'participant_provenance_invalid')
        try:require(datetime.fromisoformat(provenance['captured_at'].replace('Z','+00:00')).utcoffset() is not None,'participant_provenance_invalid')
        except (ValueError,TypeError,AttributeError):raise ParticipantError('participant_provenance_invalid') from None
        request=str(uuid.uuid5(uuid.UUID(provenance['local_run_id']),str(lease['task_id'])+':'+record['content_id']))
        params={'p_task':lease['task_id'],'p_lease':lease['lease'],'p_request':request,'p_installation_id':lease['installation_id'],'p_payload':{'schema':'crowd-participant-pro-v1','source_kind':'mediacrawler_pro','reward_eligible':False,'record':record,'canonical_record':canonical,'provenance':{**provenance,'observation_sha256':sha}}}
        encoded=mc_runner.canonical(params);require(len(encoded.encode())<=260000,'participant_record_size')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT request,params FROM participant_delivery WHERE task=? AND content_id=?',(lease['task_id'],record['content_id'])).fetchone()
            if old:
                require(old==(request,encoded),'participant_payload_conflict');return request
            db.execute('INSERT INTO participant_delivery VALUES(?,?,?,?,?,NULL)',(request,lease['task_id'],record['content_id'],encoded,'pending'))
        return request
    def flush(self):
        import json
        with self._db() as db:rows=db.execute("SELECT request,params FROM participant_delivery WHERE state='pending' ORDER BY rowid").fetchall()
        for request,encoded in rows:
            params=json.loads(encoded)
            try:
                lookup=self.client('pro_receipt',{'p_task':params['p_task'],'p_installation_id':params['p_installation_id'],'p_request':request})
                require(isinstance(lookup,dict) and type(lookup.get('found')) is bool and lookup.get('request')==request,'participant_receipt_invalid')
                receipt=lookup.get('receipt') if lookup['found'] else self.client('pro_submit',params)
                if isinstance(receipt,dict) and set(receipt)=={'error'} and receipt.get('error') in self.REJECTIONS:
                    with self._db() as db:db.execute('UPDATE participant_delivery SET state=?,receipt=? WHERE request=? AND params=?',('rejected',mc_runner.canonical(receipt),request,encoded))
                    if receipt['error'] not in ('unrelated_note','task_full'):return 'rejected'
                    continue
                require(isinstance(receipt,dict) and receipt.get('request')==request and receipt.get('gate')=='received' and receipt.get('source_kind')=='mediacrawler_pro' and receipt.get('reward_eligible') is False and receipt.get('record_hash')==params['p_payload']['record']['record_hash'],'participant_receipt_invalid')
                require(type(receipt.get('inserted')) is bool and type(receipt.get('duplicate')) is bool and receipt['inserted']!=receipt['duplicate'] and type(receipt.get('task_received')) is int and ((receipt['inserted'] and type(receipt.get('proof_id')) is int and receipt['proof_id']>0) or (receipt['duplicate'] and (receipt.get('proof_id') is None or type(receipt.get('proof_id')) is int and receipt['proof_id']>0))),'participant_receipt_invalid')
            except Exception:return 'unknown'  # Preserve exact durable UUID/payload; never re-source.
            with self._db() as db:db.execute('UPDATE participant_delivery SET state=?,receipt=? WHERE request=? AND params=?',('delivered',mc_runner.canonical(receipt),request,encoded))
        with self._db() as db:rejected=db.execute("SELECT count(*) FROM participant_delivery WHERE state='rejected'").fetchone()[0]
        return 'rejected' if rejected else 'delivered'
    def receipts(self):
        import json
        with self._db() as db:return [json.loads(r[0]) for r in db.execute("SELECT receipt FROM participant_delivery WHERE state='delivered' ORDER BY rowid")]

class ParticipantProWorker:
    """One original-task acquisition run; resume never launches a second source run.

    runner(action,payload) is the existing mc_runner start/status/import contract.
    Native source hooks receive only the safe participant context, never credentials.
    """
    def __init__(self,root,transport,runner,*,task_id,installation_id,subject,session_id,known_ids):
        for v in (installation_id,subject,session_id):uuid_value(v)
        require(type(task_id) is int and task_id>0,'participant_task_invalid')
        require(isinstance(known_ids,list) and len(known_ids)==len(set(known_ids)) and all(isinstance(v,str) and re.fullmatch('[a-f0-9]{24}',v) for v in known_ids),'participant_known_ids_invalid')
        self.transport,self.runner=transport,runner;self.task_id,self.installation,self.subject,self.session=task_id,installation_id,subject,session_id
        self.known_ids=known_ids;self.outbox=ParticipantOutbox(root,transport)
    def tick(self,request):
        import json
        with self.outbox._db() as db:old=db.execute('SELECT state,run_id,context FROM participant_runs WHERE task=?',(self.task_id,)).fetchone()
        if old:
            state,run_id,encoded_context=old;context=json.loads(encoded_context)
            previous=context['binding'];binding=getattr(self.transport,'binding',None)
            require(isinstance(binding,dict) and all(binding.get(k)==previous.get(k) for k in ('profile','subject','installation_id')),'participant_scope_changed')
            require(type(previous.get('generation')) is int and previous['generation']>=0 and binding.get('generation') in (None,previous['generation']),'participant_scope_changed')
            binding['generation']=previous['generation']  # BEFORE scope/RPC; Stop cannot mint new authority.
        require(self.transport.scope()=={'subject':self.subject,'installation_id':self.installation},'participant_scope_changed')
        if old and state in ('partial','complete','finish_unknown'):
            return {'state':state,'run_id':run_id,'source_started':False}
        delivery=self.outbox.flush()
        if delivery=='unknown':return {'state':'delivery_unknown','source_started':False}
        if delivery=='rejected':
            if old:
                with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=? WHERE task=?',('partial',self.task_id))
            return {'state':'partial','reason':'known_delivery_rejected','source_started':False}
        if old:
            if state=='launching':return {'state':'source_launch_unknown','source_started':False}
        else:
            claim=self.transport('pro_claim',{'p_task':self.task_id,'p_installation_id':self.installation})
            task,grant=claim_scope(claim,self.task_id,self.installation)
            if grant['remaining']==0:return {'state':'stopped','source_started':False}
            require(request.get('platform')=='xhs' and request.get('source_executor')=='pro' and request.get('session_id')==self.session and request.get('mode') in ('search','detail'),'participant_request_invalid')
            if task.get('comments_capture') is not True:
                require(request.get('comments') is False and request.get('replies') is False,'participant_comments_not_authorized')
            require(task.get('query') in request.get('targets',[]) or (isinstance(task.get('anchor_terms'),list) and len(task['anchor_terms'])==1 and request.get('targets')==task['anchor_terms']),'participant_query_scope_invalid')
            require(len(request.get('targets',[]))==1,'participant_query_scope_invalid')
            p={**request,'max_items':grant['remaining']};p=mc_runner.validate(p)
            server_known=claim.get('known_note_ids')
            require(isinstance(server_known,list) and len(server_known)==len(set(server_known)) and all(isinstance(v,str) and re.fullmatch('[a-f0-9]{24}',v) for v in server_known) and set(self.known_ids)<=set(server_known),'participant_known_ids_invalid')
            require(p['start_page']==1,'participant_start_page_invalid')
            binding=getattr(self.transport,'binding',None);require(isinstance(binding,dict),'participant_transport_binding_required')
            context={'schema':'crowd-participant-pro-local-v1','binding':dict(binding),'node':self.transport.node,'task_id':self.task_id,'lease':task['lease_token'],'installation_id':self.installation,'known_ids':server_known,'search_sort':'time_descending','limit':grant['remaining'],'target':grant['target'],'request_sha256':digest(p)}
            with self.outbox._db() as db:db.execute('INSERT INTO participant_runs VALUES(?,?,NULL,?)',(self.task_id,'launching',mc_runner.canonical(context)))
            # A crash/unknown launch leaves launching durable; it is never automatically retried.
            started=self.runner('start',{'request':p,'participant_context':context});run_id=uuid_value(started.get('run_id'))
            with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=?,run_id=? WHERE task=?',('running',run_id,self.task_id))
        status=self.runner('status',{'run_id':run_id})
        if status.get('state') not in mc_runner.FINAL:return {'state':'running','run_id':run_id,'source_started':True}
        imported=self.runner('import',{'run_id':run_id});records=imported.get('records',[])
        manifest=imported.get('manifest',{})
        commit=manifest.get('source',{}).get('commit')
        # The actual pinned SDK is independently rechecked by pro_executor.probe.
        from pro_executor import PINNED_COMMIT
        require(commit==PINNED_COMMIT,'participant_upstream_changed')
        if 'captured_at' not in context:
            # Time of durable normalized observation/import, not a claimed raw HTTP time.
            context['captured_at']=datetime.now(timezone.utc).isoformat()
            with self.outbox._db() as db:db.execute('UPDATE participant_runs SET context=? WHERE task=?',(mc_runner.canonical(context),self.task_id))
        content=[r for r in records if r.get('kind')=='content'];require(len(content)<=context['limit'],'participant_source_limit_exceeded')
        for r in content:
            require(r.get('content_id') not in context['known_ids'],'participant_known_content_returned')
            self.outbox.stage(r,{'task_id':self.task_id,'lease':context['lease'],'installation_id':self.installation},{'local_run_id':run_id,'upstream_commit':PINNED_COMMIT,'request_sha256':context['request_sha256'],'captured_at':context['captured_at']})
        delivered=self.outbox.flush()
        if delivered!='delivered':
            if delivered=='rejected':
                with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=? WHERE task=?',('partial',self.task_id))
            return {'state':'partial' if delivered=='rejected' else 'delivery_unknown','run_id':run_id,'source_started':False}
        # Not enough relevant native records is partial; never open another source run implicitly.
        with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=? WHERE task=?',('finish_unknown',self.task_id))
        receipt=self.transport('pro_finish',{'p_task':self.task_id,'p_lease':context['lease'],'p_installation_id':self.installation})
        fresh=self.transport('pro_status',{'p_task':self.task_id,'p_installation_id':self.installation})
        task=fresh.get('task') if isinstance(fresh,dict) else None
        complete=isinstance(task,dict) and task.get('id')==self.task_id and task.get('source_executor')=='mediacrawler_pro' and type(task.get('received')) is int and task.get('target')==context['target'] and task['received']==task['target'] and task.get('status')=='complete'
        final='complete' if complete else 'partial'
        with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=? WHERE task=?',(final,self.task_id))
        return {'state':final,'run_id':run_id,'receipt_count':len(self.outbox.receipts()),'finish':receipt,'coverage':imported.get('summary',{}).get('coverage','unverified'),'comments_and_media':'preserved_in_original_run_exports','source_started':False}


def local_runner(root,mc):
    """Reuse established subprocess runner/import/export; never copy Pro source."""
    def call(action,payload):
        if action=='start':return mc_runner.start(root,mc,payload['request'],participant_context=payload['participant_context'])
        if action=='status':return mc_runner.status(root,payload)
        if action=='import':
            result=mc_runner.import_output(root,payload)
            result['manifest']=mc_runner.read(mc_runner.run_dir(root,payload['run_id'])/'manifest.json')
            return result
        raise ParticipantError('participant_runner_action_invalid')
    return call


def main():
    import argparse
    import json
    import time
    from participant_pro_transport import ParticipantProTransport
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('root','mc-root','profile','subject','installation-id','session-id','known-ids-file','request-file','node'):
        ap.add_argument('--'+name,required=True)
    ap.add_argument('--task-id',type=int,required=True)
    ap.add_argument('--poll-seconds',type=int,default=2)
    ap.add_argument('--once',action='store_true')
    args=ap.parse_args()
    require(1<=args.poll_seconds<=60,'participant_poll_invalid')
    rpc=ParticipantProTransport(args.profile,args.subject,args.installation_id,node=args.node)
    worker=ParticipantProWorker(Path(args.root),rpc,local_runner(args.root,args.mc_root),task_id=args.task_id,
        installation_id=args.installation_id,subject=args.subject,session_id=args.session_id,
        known_ids=mc_runner.read(args.known_ids_file))
    request=mc_runner.read(args.request_file)
    while True:
        result=worker.tick(request)
        # Safe summary only: never record, target URL, principal, config or RPC error text.
        print(mc_runner.canonical({k:v for k,v in result.items() if k in ('state','run_id','receipt_count','coverage','source_started')}),flush=True)
        if args.once or result['state']!='running':break
        time.sleep(args.poll_seconds)

if __name__=='__main__':
    try:main()
    except (ParticipantError,mc_runner.BridgeError):
        print('{"state":"blocked","reason":"participant_contract_refused"}')
        raise SystemExit(1)
    except Exception:
        print('{"state":"unknown","reason":"participant_outcome_unknown"}')
        raise SystemExit(2)
