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
from participant_pro_transport import ParticipantTransportError

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

def task_comment_options(claim,task,capacity):
    """Only an authenticated claim can override native defaults for this run."""
    if 'pro_comment_options' not in claim:return None
    value=claim['pro_comment_options']
    require(type(value)is dict and set(value)=={'schema','task_id','dispatch_id','request_hash','comments','replies','max_comments','max_api_requests'},'participant_task_options_invalid')
    require(value['schema']=='crowd-participant-pro-comment-options-v1' and type(value['task_id'])is int and value['task_id']==task['id'],'participant_task_options_invalid')
    uuid_value(value['dispatch_id'])
    require(type(value['request_hash'])is str and re.fullmatch('[a-f0-9]{64}',value['request_hash']) and type(value['max_api_requests'])is int and 1<=value['max_api_requests']<=capacity,'participant_task_options_invalid')
    from participant_pro_comments import options
    resolved=options({k:value[k]for k in ('comments','replies','max_comments')})
    require(resolved['comments']is True and task.get('comments_capture')is True,'participant_task_options_invalid')
    return dict(value)

def source_failure_error(status):
    # A fixed platform diagnosis, never an arbitrary upstream error/body.
    return 'login_required' if isinstance(status,dict) and status.get('state')=='login_required' and status.get('reason')=='login_required' else None

class ParticipantOutbox(CloudOutbox):
    REJECTIONS=frozenset({'invalid_envelope','request_reused','invalid_pro_payload','invalid_pro_record',
        'record_hash_mismatch','invalid_timestamp','unrelated_note','pro_not_selected','task_full',
        'detail_not_admitted','safety_pause','test_completed','comment_parent_denied','invalid_pro_comment','comment_request_mismatch','comments_not_enabled','comment_capture_sealed','invalid_comment_capture','comment_capture_objects_mismatch','invalid_comment_pages','comment_capture_pages_mismatch','comment_capture_parent_mismatch','comment_capture_incomplete','comment_capture_options_mismatch','lease_lost','approval_required','pro_scope_denied'})
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
    def stage_comment(self,record,lease,provenance,parent_request):
        from participant_pro_comments import payload
        return self.stage_comment_payload(payload(record,provenance),lease,parent_request)
    def stage_comment_payload(self,payload,lease,parent_request):
        from participant_pro_comments import validate_payload,request_id,COMMENT,canonical
        record=validate_payload(payload,lease['task_id'],parent_request)
        request=request_id(payload['provenance']['local_run_id'],lease['task_id'],record['content_id'],record['comment_id'] if payload['schema']==COMMENT else None)
        params={'p_task':lease['task_id'],'p_lease':lease['lease'],'p_request':request,'p_parent_request':parent_request,'p_payload':payload,'p_installation_id':lease['installation_id']}
        uuid_value(lease['lease']);uuid_value(lease['installation_id'])
        # Existing durable table, separate typed key; never collide with old content_id/UUID.
        key=('comment:' if payload['schema']==COMMENT else 'comment-capture:')+record['content_id']+(':'+record['comment_id'] if payload['schema']==COMMENT else '')
        encoded=canonical(params)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT request,params FROM participant_delivery WHERE task=? AND content_id=?',(lease['task_id'],key)).fetchone()
            if old:require(old==(request,encoded),'participant_payload_conflict');return request
            db.execute('INSERT INTO participant_delivery VALUES(?,?,?,?,?,NULL)',(request,lease['task_id'],key,encoded,'pending'))
        return request
    def flush(self,task_id=None):
        import json
        with self._db() as db:rows=db.execute("SELECT request,params FROM participant_delivery WHERE state='pending' AND (? IS NULL OR task=?) ORDER BY rowid",(task_id,task_id)).fetchall()
        for request,encoded in rows:
            params=json.loads(encoded)
            child=params['p_payload'].get('schema') in ('crowd-participant-pro-comment-v1','crowd-participant-pro-comment-capture-v1')
            try:
                lookup=self.client('pro_comment_receipt' if child else 'pro_receipt',{'p_task':params['p_task'],'p_installation_id':params['p_installation_id'],'p_request':request})
                require(isinstance(lookup,dict) and type(lookup.get('found')) is bool and lookup.get('request')==request,'participant_receipt_invalid')
                receipt=lookup.get('receipt') if lookup['found'] else self.client(('pro_comment_submit' if params['p_payload']['schema']=='crowd-participant-pro-comment-v1' else 'pro_comment_commit') if child else 'pro_submit',params)
                if isinstance(receipt,dict) and set(receipt)=={'error'} and receipt.get('error') in self.REJECTIONS:
                    with self._db() as db:db.execute('UPDATE participant_delivery SET state=?,receipt=? WHERE request=? AND params=?',('rejected',mc_runner.canonical(receipt),request,encoded))
                    if receipt['error'] not in ('unrelated_note','task_full'):return 'rejected'
                    continue
                if child:
                    from participant_pro_comments import validate_receipt
                    validate_receipt(receipt,request,params['p_payload'],params['p_parent_request'])
                else:
                    require(isinstance(receipt,dict) and receipt.get('request')==request and receipt.get('gate')=='received' and receipt.get('source_kind')=='mediacrawler_pro' and receipt.get('reward_eligible') is False and receipt.get('record_hash')==params['p_payload']['record']['record_hash'],'participant_receipt_invalid')
                    require(type(receipt.get('inserted')) is bool and type(receipt.get('duplicate')) is bool and receipt['inserted']!=receipt['duplicate'] and type(receipt.get('task_received')) is int and ((receipt['inserted'] and type(receipt.get('proof_id')) is int and receipt['proof_id']>0) or (receipt['duplicate'] and (receipt.get('proof_id') is None or type(receipt.get('proof_id')) is int and receipt['proof_id']>0))),'participant_receipt_invalid')
            except Exception:return 'unknown'  # Preserve exact durable UUID/payload; never re-source.
            with self._db() as db:db.execute('UPDATE participant_delivery SET state=?,receipt=? WHERE request=? AND params=?',('delivered',mc_runner.canonical(receipt),request,encoded))
        with self._db() as db:rejected=db.execute("SELECT count(*) FROM participant_delivery WHERE state='rejected' AND (? IS NULL OR task=?)",(task_id,task_id)).fetchone()[0]
        return 'rejected' if rejected else 'delivered'
    def receipts(self,task_id=None):
        import json
        with self._db() as db:return [v for r in db.execute("SELECT receipt FROM participant_delivery WHERE state='delivered' AND (? IS NULL OR task=?) ORDER BY rowid",(task_id,task_id)) if (v:=json.loads(r[0])).get('gate')=='received']

class ParticipantProWorker:
    """One original-task acquisition run; resume never launches a second source run.

    runner(action,payload) is the existing mc_runner start/status/import contract.
    Native source hooks receive only the safe participant context, never credentials.
    """
    def __init__(self,root,transport,runner,*,task_id,installation_id,subject,session_id,known_ids,request_options=None):
        for v in (installation_id,subject,session_id):uuid_value(v)
        require(type(task_id) is int and task_id>0,'participant_task_invalid')
        require(isinstance(known_ids,list) and len(known_ids)==len(set(known_ids)) and all(isinstance(v,str) and re.fullmatch('[a-f0-9]{24}',v) for v in known_ids),'participant_known_ids_invalid')
        self.transport,self.runner=transport,runner;self.task_id,self.installation,self.subject,self.session=task_id,installation_id,subject,session_id
        self.known_ids=known_ids;self.request_options=request_options;self.outbox=ParticipantOutbox(root,transport)
    def tick(self,request):
        import json
        self.phase='local_status'
        status=None
        with self.outbox._db() as db:old=db.execute('SELECT state,run_id,context FROM participant_runs WHERE task=?',(self.task_id,)).fetchone()
        if old:
            state,run_id,encoded_context=old;context=json.loads(encoded_context)
            previous=context['binding'];binding=getattr(self.transport,'binding',None)
            require(isinstance(binding,dict) and all(binding.get(k)==previous.get(k) for k in ('profile','subject','installation_id')),'participant_scope_changed')
            require(type(previous.get('generation')) is int and previous['generation']>=0 and binding.get('generation') in (None,previous['generation']),'participant_scope_changed')
            binding['generation']=previous['generation']  # BEFORE scope/RPC; Stop cannot mint new authority.
        if old and state=='running':
            status=self.runner('status',{'run_id':run_id})
            if status.get('state') not in mc_runner.FINAL:
                return {'state':'running','run_id':run_id,'source_started':True}
        self.phase='scope'
        require(self.transport.scope()=={'subject':self.subject,'installation_id':self.installation},'participant_scope_changed')
        if old and state in ('partial','complete','finish_unknown','source_failed','source_unknown'):
            return {'state':state,'run_id':run_id,'source_started':False,**({'error':context['source_error']} if context.get('source_error')=='login_required' else {})}
        self.phase='delivery'
        delivery=self.outbox.flush(self.task_id)
        if delivery=='unknown':return {'state':'delivery_unknown','source_started':False}
        if delivery=='rejected':
            if old:
                with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=? WHERE task=?',('partial',self.task_id))
            return {'state':'partial','reason':'known_delivery_rejected','source_started':False}
        recovering=bool(old and state in ('recover_ready','native_ready'))
        if old and not recovering:
            if state=='launching':return {'state':'source_launch_unknown','source_started':False}
        else:
            claim=self.transport('pro_claim',{'p_task':self.task_id,'p_installation_id':self.installation})
            task,grant=claim_scope(claim,self.task_id,self.installation)
            authority=task_comment_options(claim,task,(self.request_options or request or {}).get('max_api_requests',0))
            if grant['remaining']==0:return {'state':'stopped','source_started':False}
            if request is None:
                options=self.request_options
                require(isinstance(options,dict) and set(options)=={'purpose','max_api_requests'},'participant_request_invalid')
                resolved=None
                if task.get('comments_capture') is True:
                    from participant_pro_comments import options as native_options
                    resolved=native_options({k:authority[k]for k in ('comments','replies','max_comments')} if authority is not None else self.runner('comment_options',{}));require(resolved['comments'] is True,'participant_native_comments_disabled')
                query=task['anchor_terms'][0] if isinstance(task.get('anchor_terms'),list) and len(task['anchor_terms'])==1 else task.get('query')
                request={'platform':'xhs','mode':'search','source_executor':'pro','session_id':self.session,'targets':[query],
                         'comments':bool(resolved),'replies':resolved['replies'] if resolved else False,'media':False,**options,**({'max_comments':resolved['max_comments']} if resolved else {}),**({'max_api_requests':authority['max_api_requests']} if authority is not None else {})}
            require(request.get('platform')=='xhs' and request.get('source_executor')=='pro' and request.get('session_id')==self.session and request.get('mode') in ('search','detail'),'participant_request_invalid')
            if task.get('comments_capture') is not True:
                require(request.get('comments') is False and request.get('replies') is False,'participant_comments_not_authorized')
            require(task.get('query') in request.get('targets',[]) or (isinstance(task.get('anchor_terms'),list) and len(task['anchor_terms'])==1 and request.get('targets')==task['anchor_terms']),'participant_query_scope_invalid')
            require(len(request.get('targets',[]))==1,'participant_query_scope_invalid')
            p={**request,'max_items':grant['remaining']}
            recovery=context.get('recovery') if recovering else None
            if recovery is not None:
                require(task['received']==recovery['expected_received'],'participant_recovery_count_changed')
                p['max_api_requests']=recovery['total_limit']-recovery['used_requests']
                control=self.transport('pro_guard',{'p_task':self.task_id,'p_lease':task['lease_token'],'p_action':'control','p_note':None,'p_installation_id':self.installation})
                require(isinstance(control,dict) and control.get('allowed') is True and control.get('reason') is None and type(control.get('counts',{}).get('detail')) is int and control['counts']['detail']==recovery['expected_detail_count'],'participant_recovery_count_changed')
            resolved=None
            if task.get('comments_capture') is True:
                from participant_pro_comments import options as native_options
                resolved=native_options({k:authority[k]for k in ('comments','replies','max_comments')} if authority is not None else self.runner('comment_options',{}));require(resolved['comments'] is True and all(p.get(k)==resolved[k] for k in ('comments','replies','max_comments')),'participant_native_comments_changed')
                if authority is not None:require(p.get('max_api_requests')==authority['max_api_requests'],'participant_task_options_invalid')
            p=mc_runner.validate(p,native_comments=resolved)
            own_known=claim.get('known_note_ids');nested_known=task.get('known_note_ids')
            for values in (own_known,nested_known):
                require(isinstance(values,list) and len(values)<=500 and all(isinstance(v,str) and re.fullmatch('[a-f0-9]{24}',v) for v in values) and len(values)==len(set(values)),'participant_known_ids_invalid')
            require(set(self.known_ids)<=set(own_known),'participant_known_ids_invalid')
            # Reuse original node_claim's same-query exclusion contract, not a global lookup.
            server_known=sorted(set(own_known)|set(nested_known))
            if recovery is not None and recovery.get('scope_recovery') is True:
                require(set(recovery['required_exclusions'])<=set(server_known),'participant_known_scope_not_fixed')
            require(p['start_page']==1,'participant_start_page_invalid')
            binding=getattr(self.transport,'binding',None);require(isinstance(binding,dict),'participant_transport_binding_required')
            context={'schema':'crowd-participant-pro-local-v1','binding':dict(binding),'node':self.transport.node,'task_id':self.task_id,'lease':task['lease_token'],'installation_id':self.installation,'known_ids':server_known,'search_sort':'time_descending','limit':grant['remaining'],'target':grant['target'],'request_sha256':digest(p)}
            if resolved is not None:context['comment_options']=resolved
            if authority is not None:context['task_comment_options']=authority
            if recovery is not None:context['recovery']=recovery
            if recovering and 'native_start' in json.loads(encoded_context):context['native_start']=json.loads(encoded_context)['native_start']
            with self.outbox._db() as db:
                if recovering:
                    changed=db.execute('UPDATE participant_runs SET state=?,run_id=NULL,context=? WHERE task=? AND state=?',('launching',mc_runner.canonical(context),self.task_id,state)).rowcount
                    require(changed==1,'participant_recovery_changed')
                else:db.execute('INSERT INTO participant_runs VALUES(?,?,NULL,?)',(self.task_id,'launching',mc_runner.canonical(context)))
            # A crash/unknown launch leaves launching durable; it is never automatically retried.
            started=self.runner('start',{'request':p,'participant_context':context});run_id=uuid_value(started.get('run_id'))
            with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=?,run_id=? WHERE task=?',('running',run_id,self.task_id))
        self.phase='local_status'
        if status is None:status=self.runner('status',{'run_id':run_id})
        if status.get('state') not in mc_runner.FINAL:return {'state':'running','run_id':run_id,'source_started':True}
        self.phase='import'
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
        self.phase='stage'
        comment_plans=[]
        if context.get('comment_options') is not None:
            from participant_pro_comments import capture_payload,payload,validate_payload,body_request
            meta=imported.get('participant_comment_capture');require(isinstance(meta,dict),'participant_comment_evidence_missing')
            comments=[r for r in records if r.get('kind')=='comment']
            require(all(r.get('content_id') in {n['content_id'] for n in content} for r in comments),'participant_comment_parent_missing')
            prov={'local_run_id':run_id,'upstream_commit':PINNED_COMMIT,'request_sha256':context['request_sha256'],'captured_at':context['captured_at']}
            for note in content:
                children=[r for r in comments if r['content_id']==note['content_id']];parent=body_request(run_id,self.task_id,note['content_id'])
                pages=[r for r in meta['pages'] if r.get('content_id')==note['content_id']]
                cap=capture_payload(note['content_id'],children,pages,meta['sha256'],meta['coverage'],prov,self.task_id,context['comment_options'])
                for child in children:validate_payload(payload(child,prov),self.task_id,parent)
                comment_plans.append((parent,children,cap,prov))
        for r in content:
            require(r.get('content_id') not in context['known_ids'],'participant_known_content_returned')
            self.outbox.stage(r,{'task_id':self.task_id,'lease':context['lease'],'installation_id':self.installation},{'local_run_id':run_id,'upstream_commit':PINNED_COMMIT,'request_sha256':context['request_sha256'],'captured_at':context['captured_at']})
        for parent,children,cap,prov in comment_plans:
            lease={'task_id':self.task_id,'lease':context['lease'],'installation_id':self.installation}
            for child in children:self.outbox.stage_comment(child,lease,prov,parent)
            self.outbox.stage_comment_payload(cap,lease,parent)
        self.phase='delivery'
        delivered=self.outbox.flush(self.task_id)
        if delivered!='delivered':
            if delivered=='rejected':
                with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=? WHERE task=?',('partial',self.task_id))
            return {'state':'partial' if delivered=='rejected' else 'delivery_unknown','run_id':run_id,'source_started':False}
        if status.get('state')!='completed':
            final='source_unknown' if status.get('state')=='interrupted_unknown' else 'source_failed'
            error=source_failure_error(status)
            if error:context['source_error']=error
            with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=?,context=? WHERE task=?',(final,mc_runner.canonical(context),self.task_id))
            return {'state':final,'run_id':run_id,'source_started':False,**({'error':error} if error else {})}
        if not any(r.get('inserted') is True for r in self.outbox.receipts(self.task_id)):
            with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=? WHERE task=?',('partial',self.task_id))
            return {'state':'partial','reason':'no_new_received','run_id':run_id,'source_started':False}
        if any(cap['record']['coverage']['coverage'] != 'exhausted' for _,_,cap,_ in comment_plans):
            with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=? WHERE task=?',('partial',self.task_id))
            return {'state':'partial','reason':'comments_incomplete','run_id':run_id,'source_started':False}
        # Not enough relevant native records is partial; never open another source run implicitly.
        with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=? WHERE task=?',('finish_unknown',self.task_id))
        self.phase='finish'
        receipt=self.transport('pro_finish',{'p_task':self.task_id,'p_lease':context['lease'],'p_installation_id':self.installation})
        if isinstance(receipt,dict) and receipt.get('error')=='comments_incomplete':
            with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=? WHERE task=?',('partial',self.task_id))
            return {'state':'partial','reason':'comments_incomplete','run_id':run_id,'source_started':False}
        fresh=self.transport('pro_status',{'p_task':self.task_id,'p_installation_id':self.installation})
        task=fresh.get('task') if isinstance(fresh,dict) else None
        complete=isinstance(task,dict) and task.get('id')==self.task_id and task.get('source_executor')=='mediacrawler_pro' and type(task.get('received')) is int and task.get('target')==context['target'] and task['received']==task['target'] and task.get('status')=='complete'
        final='complete' if complete else 'partial'
        with self.outbox._db() as db:db.execute('UPDATE participant_runs SET state=? WHERE task=?',(final,self.task_id))
        return {'state':final,'run_id':run_id,'receipt_count':len(self.outbox.receipts(self.task_id)),'finish':receipt,'coverage':imported.get('summary',{}).get('coverage','unverified'),'comments_and_media':'preserved_in_original_run_exports','source_started':False}

    def restart_known_stopped_native_once(self,previous_run_id,*,native_start):
        """Explicit authorized third attempt, not replay or automatic checkpoint resume."""
        import json
        require(self.task_id==29 and self.subject=='2fc8765e-700a-41c1-b325-a21c5faa22ce' and self.installation=='3cde2858-39a5-42e1-b7ab-dd62053d2dac' and self.session=='903d6888-6397-426c-a5e4-8080597c7101' and previous_run_id=='729d6565-1cc6-4222-a6bd-670a502f1d05','participant_reexecution_refused')
        with self.outbox._db() as db:
            old=db.execute('SELECT state,run_id,context FROM participant_runs WHERE task=?',(self.task_id,)).fetchone()
            deliveries=db.execute('SELECT count(*) FROM participant_delivery WHERE task=?',(self.task_id,)).fetchone()[0]
        require(old is not None and old[0]=='running' and old[1]==previous_run_id and deliveries==0,'participant_reexecution_refused')
        context=json.loads(old[2]);prior=context.get('recovery',{});binding=self.transport.binding;previous=context.get('binding',{});old_start=context.get('native_start',{})
        require(prior.get('old_run_id')=='356dbc9f-3692-47d7-8c3c-74f5ed101c9b' and prior.get('used_requests')==4 and prior.get('total_limit')==14 and not prior.get('explicit_reexecution') and context.get('target')==2 and context.get('limit')==2,'participant_reexecution_refused')
        require(type(native_start) is dict and set(native_start)=={'subject','installation_id','task_id','intent'} and native_start['subject']==self.subject and native_start['installation_id']==self.installation and native_start['task_id']==self.task_id,'participant_scope_changed')
        uuid_value(native_start['intent']);uuid_value(binding.get('native_session'))
        require(all(binding.get(k)==previous.get(k) for k in ('profile','subject','installation_id')) and binding.get('profile')=='native-messaging' and type(binding.get('generation')) is int and type(previous.get('generation')) is int and binding['generation']>previous['generation'] and binding['native_session']!=previous.get('native_session') and native_start['intent']!=old_start.get('intent') and self.request_options=={'purpose':'noncommercial_research','max_api_requests':14},'participant_scope_changed')
        require(self.transport.scope()=={'subject':self.subject,'installation_id':self.installation},'participant_scope_changed')
        inspected=self.runner('inspect',{'run_id':previous_run_id});first=self.runner('inspect',{'run_id':prior['old_run_id']})
        require(first.get('task_id')==self.task_id and first.get('installation_id')==self.installation and first.get('session_id')==self.session and first.get('state')=='login_required' and first.get('exit_code')==77 and first.get('used_requests')==4 and first.get('total_limit')==14 and first.get('observation_count')==0 and first.get('detail_admissions')==0 and first.get('participant_binding')==prior.get('old_context',{}).get('binding'),'participant_reexecution_refused')
        require(inspected.get('participant_context_sha256')==digest(context) and inspected.get('state')=='stopped' and inspected.get('exit_code')==-15 and inspected.get('session_idle') is True and inspected.get('budget_binding_valid') is True and inspected.get('used_requests')==4 and inspected.get('total_limit')==10 and inspected.get('observation_count')==0 and inspected.get('detail_admissions')==0 and inspected.get('participant_binding')==previous and inspected.get('session_id')==self.session and inspected.get('task_id')==self.task_id and inspected.get('installation_id')==self.installation and inspected.get('guard_failure')=={'action':'search','outcome':'rpc_unknown','reason':None} and inspected.get('checkpoint_seed') is True,'participant_reexecution_refused')
        fresh=self.transport('pro_status',{'p_task':self.task_id,'p_installation_id':self.installation});task=fresh.get('task',{});g=fresh.get('acceptance_supplement',{})
        require(task.get('id')==self.task_id and task.get('source_executor')=='mediacrawler_pro' and task.get('received')==0 and task.get('target')==2 and set(g)=={'schema','id','task_id','installation_id','baseline_received','extra_limit','remaining','target'} and g.get('id')=='13761788-0860-40b8-a8ac-69a20ae1a5a1' and g.get('baseline_received')==0 and g.get('extra_limit')==2 and g.get('schema')=='crowd-acceptance-batch-v1' and g.get('installation_id')==self.installation and g.get('task_id')==self.task_id and g.get('target')==2 and g.get('remaining')==2,'participant_reexecution_refused')
        lease=context.get('lease');uuid_value(lease)
        control=self.transport('pro_guard',{'p_task':self.task_id,'p_lease':lease,'p_action':'control','p_note':None,'p_installation_id':self.installation})
        count=control.get('counts',{}).get('detail') if isinstance(control,dict) else None
        require(isinstance(control,dict) and control.get('allowed') is True and control.get('reason') is None and type(count) is int and count==prior.get('expected_detail_count'),'participant_reexecution_refused')
        require(self.runner('inspect',{'run_id':previous_run_id})==inspected and self.transport.scope()=={'subject':self.subject,'installation_id':self.installation},'participant_reexecution_changed')
        archive={'explicit_reexecution':True,'authorization':'original_task29_two_items_total22','old_run_id':previous_run_id,'old_context':context,'old_context_sha256':digest(context),'inspection':inspected,'first_inspection':first,'used_requests':8,'total_limit':22,'expected_detail_count':count,'expected_received':0}
        new={**context,'binding':dict(binding),'native_start':dict(native_start),'recovery':archive}
        with self.outbox._db() as db:
            changed=db.execute('UPDATE participant_runs SET state=?,context=? WHERE task=? AND state=? AND run_id=? AND context=?',('recover_ready',mc_runner.canonical(new),self.task_id,old[0],previous_run_id,old[2])).rowcount
            require(changed==1,'participant_reexecution_changed')
        return {'state':'recover_ready','previous_run_id':previous_run_id,'remaining_source_requests':14,'used_source_requests':8,'total_source_limit':22,'source_started':False}

    def recover_known_failed_once(self,previous_run_id,*,expected_used_requests,expected_detail_count,expected_received,native_start=None):
        """Explicit operator recovery of known failed-before-detail, never UNKNOWN replay.

        Checks are local reads + authenticated status only. The next normal tick claims
        the original task, verifies unchanged central detail count, then launches once.
        """
        import json
        uuid_value(previous_run_id)
        with self.outbox._db() as db:
            old=db.execute('SELECT state,run_id,context FROM participant_runs WHERE task=?',(self.task_id,)).fetchone()
            deliveries=db.execute('SELECT count(*) FROM participant_delivery WHERE task=?',(self.task_id,)).fetchone()[0]
        require(old is not None and old[0] in ('partial','source_failed') and old[1]==previous_run_id and deliveries==0,'participant_recovery_refused')
        context=json.loads(old[2]);require('recovery' not in context,'participant_recovery_already_used')
        binding=self.transport.binding;previous=context['binding']
        require(all(binding.get(k)==previous.get(k) for k in ('profile','subject','installation_id')) and type(previous.get('generation')) is int,'participant_scope_changed')
        if native_start is not None:
            prior=context.get('native_start',{})
            require(type(native_start) is dict and set(native_start)=={'subject','installation_id','task_id','intent'} and native_start.get('subject')==self.subject and native_start.get('installation_id')==self.installation and native_start.get('task_id')==self.task_id,'participant_scope_changed')
            uuid_value(native_start.get('intent'));uuid_value(binding.get('native_session'))
            require(old[0]=='source_failed' and previous.get('profile')=='native-messaging' and prior.get('subject')==self.subject and prior.get('installation_id')==self.installation and prior.get('task_id')==self.task_id and native_start['intent']!=prior.get('intent') and binding.get('native_session')!=previous.get('native_session') and type(binding.get('generation')) is int and binding['generation']>=previous['generation'],'participant_recovery_refused')
        else:
            require(binding.get('generation') in (None,previous['generation']),'participant_scope_changed')
            binding['generation']=previous['generation']
        require(self.transport.scope()=={'subject':self.subject,'installation_id':self.installation},'participant_scope_changed')
        inspected=self.runner('inspect',{'run_id':previous_run_id})
        if native_start is not None:
            require(inspected.get('state')=='login_required' and inspected.get('exit_code')==77 and inspected.get('session_id')==self.session and inspected.get('checkpoint_created') is False and inspected.get('checkpoint_present') is False and inspected.get('detail_admissions')==0 and inspected.get('participant_binding')==previous and inspected.get('task_id')==self.task_id and inspected.get('installation_id')==self.installation and expected_used_requests==4 and inspected.get('total_limit')==14 and self.request_options.get('max_api_requests')==14,'participant_recovery_refused')
        else:
            require(inspected.get('state')=='failed','participant_recovery_refused')
        require(inspected.get('observation_count')==0 and inspected.get('used_requests')==expected_used_requests and type(expected_used_requests) is int and expected_used_requests>=0 and type(inspected.get('total_limit')) is int and 1<=inspected['total_limit']-expected_used_requests<=500,'participant_recovery_refused')
        require(type(expected_received) is int and expected_received>=0,'participant_recovery_refused')
        fresh=self.transport('pro_status',{'p_task':self.task_id,'p_installation_id':self.installation})
        task=fresh.get('task',{});g=fresh.get('acceptance_supplement',{})
        require(task.get('id')==self.task_id and task.get('source_executor')=='mediacrawler_pro' and task.get('received')==expected_received and task.get('target')==context['target'] and g.get('installation_id')==self.installation and g.get('task_id')==self.task_id and g.get('remaining')==context['target']-expected_received and g.get('remaining')>0,'participant_recovery_refused')
        if native_start is not None:
            lease=context.get('lease');uuid_value(lease)
            control=self.transport('pro_guard',{'p_task':self.task_id,'p_lease':lease,'p_action':'control','p_note':None,'p_installation_id':self.installation})
            require(isinstance(control,dict) and control.get('allowed') is True and control.get('reason') is None and type(control.get('counts',{}).get('detail')) is int,'participant_recovery_refused')
            expected_detail_count=control['counts']['detail']
        require(type(expected_detail_count) is int and expected_detail_count>=0,'participant_recovery_refused')
        archive={'old_run_id':previous_run_id,'old_context':context,'old_context_sha256':digest(context),'inspection':inspected,'used_requests':expected_used_requests,'total_limit':inspected['total_limit'],'expected_detail_count':expected_detail_count,'expected_received':expected_received}
        new={**context,'recovery':archive}
        if native_start is not None:
            new.update(binding=dict(binding),native_start=dict(native_start))
            require(self.transport.scope()=={'subject':self.subject,'installation_id':self.installation},'participant_scope_changed')
        with self.outbox._db() as db:
            changed=db.execute('UPDATE participant_runs SET state=?,context=? WHERE task=? AND state=? AND run_id=? AND context=?',('recover_ready',mc_runner.canonical(new),self.task_id,old[0],previous_run_id,old[2])).rowcount
            require(changed==1,'participant_recovery_changed')
        return {'state':'recover_ready','previous_run_id':previous_run_id,'remaining_source_requests':inspected['total_limit']-expected_used_requests,'source_started':False}


    def recover_known_note_scope_once(self,previous_run_id,*,expected_used_requests,expected_detail_count,expected_received,total_request_limit=20):
        """Explicit one-off repair for the proven same-query exclusion-scope mismatch."""
        import json
        uuid_value(previous_run_id)
        with self.outbox._db() as db:
            old=db.execute('SELECT state,run_id,context FROM participant_runs WHERE task=?',(self.task_id,)).fetchone()
            deliveries=db.execute('SELECT count(*) FROM participant_delivery WHERE task=?',(self.task_id,)).fetchone()[0]
        require(old is not None and old[0]=='source_failed' and old[1]==previous_run_id and deliveries==0,'participant_scope_recovery_refused')
        context=json.loads(old[2]);prior=context.get('recovery',{})
        require(prior.get('scope_recovery') is not True and isinstance(prior.get('old_run_id'),str) and type(prior.get('used_requests')) is int and type(prior.get('total_limit')) is int,'participant_scope_recovery_refused')
        binding=self.transport.binding;previous=context['binding']
        require(all(binding.get(k)==previous.get(k) for k in ('profile','subject','installation_id')) and type(previous.get('generation')) is int and binding.get('generation') in (None,previous['generation']),'participant_scope_changed')
        binding['generation']=previous['generation']
        require(self.transport.scope()=={'subject':self.subject,'installation_id':self.installation},'participant_scope_changed')
        inspected=self.runner('inspect',{'run_id':previous_run_id});failure=inspected.get('guard_failure',{})
        require(inspected.get('state')=='failed' and inspected.get('observation_count')==0 and type(expected_used_requests) is int and inspected.get('used_requests')==expected_used_requests and expected_used_requests>0 and inspected.get('total_limit')==prior['total_limit']-prior['used_requests'] and failure=={'action':'detail','outcome':'denied','reason':'known_note'} and inspected.get('detail_admissions')==0,'participant_scope_recovery_refused')
        selected=inspected.get('selected_note_ids')
        require(isinstance(selected,list) and 1<=len(selected)<=context['limit'] and all(isinstance(v,str) and re.fullmatch('[a-f0-9]{24}',v) for v in selected) and not(set(selected)&set(context['known_ids'])),'participant_scope_recovery_refused')
        require(type(expected_received) is int and expected_received>=0,'participant_scope_recovery_refused')
        used=prior['used_requests']+expected_used_requests
        require(type(total_request_limit) is int and total_request_limit in (prior['total_limit'],26) and (total_request_limit==prior['total_limit'] or prior['total_limit']==20 and used==12),'participant_request_limit_refused')
        # Existing XHS path: credentials/pong/me4 + first search2 + 2 HTTP/sign calls per detail.
        require(total_request_limit-used>=6+2*(context['target']-expected_received),'participant_remaining_request_budget_insufficient')
        require(used<total_request_limit and type(expected_detail_count) is int and expected_detail_count==prior['expected_detail_count'] and type(expected_received) is int and expected_received==prior['expected_received'],'participant_scope_recovery_refused')
        fresh=self.transport('pro_status',{'p_task':self.task_id,'p_installation_id':self.installation});task=fresh.get('task',{});g=fresh.get('acceptance_supplement',{})
        require(task.get('id')==self.task_id and task.get('source_executor')=='mediacrawler_pro' and task.get('received')==expected_received and task.get('target')==context['target'] and g.get('installation_id')==self.installation and g.get('task_id')==self.task_id and g.get('remaining')==context['target']-expected_received and g.get('remaining')>0,'participant_scope_recovery_refused')
        recovery={'scope_recovery':True,'required_exclusions':selected,'old_run_id':previous_run_id,'old_context':context,'old_context_sha256':digest(context),'inspection':inspected,'used_requests':used,'total_limit':total_request_limit,'previous_total_limit':prior['total_limit'],'limit_change_reason':'explicit_known_note_scope_repair' if total_request_limit!=prior['total_limit'] else 'unchanged','expected_detail_count':expected_detail_count,'expected_received':expected_received}
        new={**context,'recovery':recovery}
        with self.outbox._db() as db:
            changed=db.execute('UPDATE participant_runs SET state=?,context=? WHERE task=? AND state=? AND run_id=? AND context=?',('recover_ready',mc_runner.canonical(new),self.task_id,old[0],previous_run_id,old[2])).rowcount
            require(changed==1,'participant_recovery_changed')
        return {'state':'recover_ready','previous_run_id':previous_run_id,'remaining_source_requests':total_request_limit-used,'source_started':False}


def local_runner(root,mc,*,participant_channel=None):
    """Reuse established subprocess runner/import/export; never copy Pro source."""
    def call(action,payload):
        if action=='start':
            if participant_channel is not None:
                with participant_channel() as fd:
                    return mc_runner.start(root,mc,payload['request'],participant_context=payload['participant_context'],participant_rpc_fd=fd)
            return mc_runner.start(root,mc,payload['request'],participant_context=payload['participant_context'])
        if action=='status':return mc_runner.status(root,payload)
        if action=='comment_options':
            from pro_executor import resolved_comment_options
            return resolved_comment_options(root)
        if action=='inspect':
            from pro_executor import observations
            run=mc_runner.run_dir(root,payload['run_id']);manifest=mc_runner.read(run/'manifest.json');status=mc_runner.read(run/'status.json');budget=mc_runner.read(run/'request-budget.json')
            require(manifest.get('source',{}).get('commit')==__import__('pro_executor').PINNED_COMMIT and manifest.get('participant_pro') is not None and budget.get('run_id')==payload['run_id'],'participant_recovery_refused')
            cp=__import__('pro_executor').checkpoint(run,manifest)
            journal=mc_runner.read(run/'participant-pro-guard.json') if (run/'participant-pro-guard.json').exists() else {}
            last=journal.get('events',[])[-1] if journal.get('events') else {}
            failure={k:last.get(k) for k in ('action','outcome','reason')}
            import os,fcntl,stat
            session_idle=False
            try:
                fd=os.open(Path(root)/'sessions'/manifest['request']['session_id']/'active.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                try:
                    info=os.fstat(fd)
                    if stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid():
                        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);session_idle=True
                finally:os.close(fd)
            except OSError:pass
            from shared_request_budget import request_fingerprint
            budget_binding_valid=budget.get('request_hash')==request_fingerprint(manifest['request'])
            checkpoint_seed=isinstance(cp,dict) and cp.get('acquisition_committed') is False and cp.get('is_completed') is False and cp.get('current_search_page')==1 and cp.get('current_search_id') is None and cp.get('crawled_note_list')==[] and cp.get('failed_search_pages')==[]
            saved_names=['manifest.json','status.json','request-budget.json']
            for name in ['participant-pro-guard.json','data/checkpoints/'+payload['run_id']+'.json','data/checkpoints/vox/'+payload['run_id']+'.json']:
                if (run/name).is_file():saved_names.append(name)
            return {'participant_context_sha256':digest(manifest.get('participant_pro')),'session_idle':session_idle,'budget_binding_valid':budget_binding_valid,'checkpoint_seed':checkpoint_seed,'state':status.get('state'),'exit_code':status.get('exit_code'),'checkpoint_created':status.get('checkpoint_created'),'checkpoint_present':cp is not None,'participant_binding':manifest.get('participant_pro',{}).get('binding'),'task_id':manifest.get('participant_pro',{}).get('task_id'),'installation_id':manifest.get('participant_pro',{}).get('installation_id'),'session_id':manifest.get('request',{}).get('session_id'),'observation_count':len(observations(run,manifest)),'used_requests':budget.get('used'),'total_limit':budget.get('limit'),'guard_failure':failure,'detail_admissions':sum(e.get('action')=='detail' and e.get('outcome')=='admitted' for e in journal.get('events',[])),'selected_note_ids':[n['note_id'] for n in (cp or {}).get('crawled_note_list',[])],'saved_files_sha256':{name:hashlib.sha256((run/name).read_bytes()).hexdigest() for name in saved_names}}
        if action=='import':
            result=mc_runner.import_output(root,payload)
            run=mc_runner.run_dir(root,payload['run_id']);result['manifest']=mc_runner.read(run/'manifest.json')
            if result['manifest'].get('participant_pro',{}).get('comment_options') is not None:
                path=run/'pro-pagination.json';blob=path.read_bytes() if path.is_file() else None
                value=__import__('json').loads(blob) if blob is not None else {'pages':[]}
                result['participant_comment_capture']={'pages':value['pages'],'sha256':hashlib.sha256(blob).hexdigest() if blob is not None else None,'coverage':result.get('pro_acquisition',{}).get('pagination',{'coverage':'unknown','reason':'pagination_evidence_missing'})}
            return result
        raise ParticipantError('participant_runner_action_invalid')
    return call


def transport_diagnostic(error,phase):
    # Only fixed transport codes/phase names; never exception body, stack, URLs or credentials.
    known={'participant_writer_busy','participant_scope_changed','participant_profile_changed',
           'participant_worker_missing','participant_worker_invalid','participant_listener_invalid',
           'participant_port_invalid','participant_profile_invalid','invalid_participant_scope',
           'invalid_participant_action','invalid_participant_params','invalid_platform_principal',
           'invalid_participant_transport','participant_node_runtime_missing'}
    code=str(error)
    return {'state':'blocked' if code in known else 'unknown',
            'reason':code if code in known else 'participant_rpc_outcome_unknown',
            'phase':phase if phase in {'local_status','scope','delivery','import','stage','finish'} else 'initial'}

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
    ap.add_argument('--recover-known-failed-once')
    ap.add_argument('--recover-known-note-scope-once')
    ap.add_argument('--expected-used-requests',type=int)
    ap.add_argument('--expected-detail-count',type=int)
    ap.add_argument('--expected-received',type=int)
    ap.add_argument('--total-request-limit',type=int,default=20)
    args=ap.parse_args()
    require(1<=args.poll_seconds<=60,'participant_poll_invalid')
    rpc=ParticipantProTransport(args.profile,args.subject,args.installation_id,node=args.node)
    worker=ParticipantProWorker(Path(args.root),rpc,local_runner(args.root,args.mc_root),task_id=args.task_id,
        installation_id=args.installation_id,subject=args.subject,session_id=args.session_id,
        known_ids=mc_runner.read(args.known_ids_file))
    request=mc_runner.read(args.request_file)
    require(not (args.recover_known_failed_once and args.recover_known_note_scope_once),'participant_recovery_refused')
    if args.recover_known_note_scope_once:
        result=worker.recover_known_note_scope_once(args.recover_known_note_scope_once,expected_used_requests=args.expected_used_requests,expected_detail_count=args.expected_detail_count,expected_received=args.expected_received,total_request_limit=args.total_request_limit)
        print(mc_runner.canonical(result),flush=True)
        return
    if args.recover_known_failed_once:
        result=worker.recover_known_failed_once(args.recover_known_failed_once,expected_used_requests=args.expected_used_requests,expected_detail_count=args.expected_detail_count,expected_received=args.expected_received)
        print(mc_runner.canonical(result),flush=True)
        return  # Explicit preparation only; separate normal invocation launches once.
    while True:
        try:result=worker.tick(request)
        except ParticipantTransportError as error:
            diagnostic=transport_diagnostic(error,getattr(worker,'phase','initial'))
            print(mc_runner.canonical(diagnostic),flush=True)
            raise SystemExit(2 if diagnostic['state']=='unknown' else 1) from None
        # Safe summary only: never record, target URL, principal, config or RPC error text.
        print(mc_runner.canonical({k:v for k,v in result.items() if k in ('state','run_id','receipt_count','coverage','source_started')}),flush=True)
        if args.once or result['state']!='running':
            if result['state']=='source_failed':raise SystemExit(1)
            if result['state']=='source_unknown':raise SystemExit(2)
            break
        time.sleep(args.poll_seconds)

if __name__=='__main__':
    try:main()
    except (ParticipantError,mc_runner.BridgeError):
        print('{"state":"blocked","reason":"participant_contract_refused"}')
        raise SystemExit(1)
    except Exception:
        print('{"state":"unknown","reason":"participant_outcome_unknown"}')
        raise SystemExit(2)
