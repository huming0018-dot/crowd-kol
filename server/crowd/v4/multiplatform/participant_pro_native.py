"""Fixed native-host entry for the existing participant Worker; stdout is frames only."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import queue
import socket
import stat
import sys
import threading
import time
from participant_native_rpc import FrameIO,NativeMux,NativeTransport,ProtocolError,frame,valid_uuid,relay_child
from participant_pro import ParticipantProWorker,ParticipantOutbox,ParticipantError,local_runner,transport_diagnostic
import mc_runner

CONFIG_KEYS={'schema','python','entry','entry_sha256','root','mc_root','session_id','max_api_requests','purpose'}
STATES={'ready','not_ready','running','complete','partial','finish_unknown','source_failed','source_unknown',
        'delivery_unknown','source_launch_unknown','stopped','blocked','unknown','native_ready','launching'}
PHASES={'initial','local_status','scope','delivery','import','stage','finish','source','stopping'}
ERRORS={'participant_scope_changed','participant_writer_busy','participant_stopped','participant_rpc_outcome_unknown',
        'participant_protocol_invalid','participant_contract_refused','participant_installation_invalid','participant_existing_run'}

def load_config(path):
    path=Path(path)
    if not path.is_absolute():raise ProtocolError('participant_installation_invalid')
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077 or not 0<st.st_size<=16384:raise ValueError()
            raw=os.read(fd,16385);after=os.fstat(fd)
            if len(raw)!=st.st_size or (st.st_size,st.st_mtime_ns,st.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError()
            cfg=json.loads(raw)
        finally:os.close(fd)
        if type(cfg) is not dict or set(cfg)!=CONFIG_KEYS or cfg['schema']!='crowd-participant-pro-install-v1':raise ValueError()
        for k in ('python','entry','root','mc_root'):
            if type(cfg[k]) is not str or not Path(cfg[k]).is_absolute() or k!='python' and Path(cfg[k]).is_symlink():raise ValueError()
        if not Path(cfg['python']).is_file() or not os.access(cfg['python'],os.X_OK) or not Path(cfg['root']).is_dir() or not Path(cfg['mc_root']).is_dir():raise ValueError()
        if Path(cfg['entry']).resolve()!=Path(__file__).resolve() or hashlib.sha256(Path(cfg['entry']).read_bytes()).hexdigest()!=cfg['entry_sha256']:raise ValueError()
        if not valid_uuid(cfg['session_id']) or type(cfg['max_api_requests']) is not int or not 1<=cfg['max_api_requests']<=100 or cfg['purpose']!='noncommercial_research':raise ValueError()
        return cfg
    except (OSError,ValueError,TypeError,KeyError,RecursionError):raise ProtocolError('participant_installation_invalid') from None

def installation_ready(config):
    # Original capability exit is local-only and does not load an account or make HTTP.
    from pro_executor import task_installation,probe,binding_for
    installation=task_installation(config['root'],{'source_executor':'pro'})
    probe(installation['root'],installation['python'])
    binding_for(config['root'],{'session_id':config['session_id'],'platform':'xhs'})

class NativeService:
    def __init__(self,config,mux,runner_factory=local_runner,worker_class=ParticipantProWorker):
        self.config,self.mux,self.runner_factory,self.worker_class=config,mux,runner_factory,worker_class
        self.worker=None;self.thread=None;self.start_message=None;self.last={'state':'ready','source_started':False};self.reconnected=False;self.lock=threading.Lock()
    @contextlib.contextmanager
    def child_channel(self):
        if self.mux.stopped.is_set():raise ProtocolError('participant_stopped')
        parent,child=socket.socketpair()
        threading.Thread(target=relay_child,args=(parent,self.mux,self.worker.task_id,self.worker.installation),daemon=True).start()
        try:yield child.fileno()
        finally:child.close()
    def runner(self):
        base=self.runner_factory(self.config['root'],self.config['mc_root'],participant_channel=self.child_channel)
        def call(action,payload):
            if action=='start' and self.mux.stopped.is_set():raise ProtocolError('participant_stopped')
            result=base(action,payload)
            if action=='start' and self.mux.stopped.is_set():
                # Stop that races an already-started owned child, not a second launch.
                mc_runner.stop(self.config['root'],{'run_id':result['run_id'],'origin':'user','reason':'user_stop'})
            return result
        return call
    def snapshot(self):
        value={'run_id':None,'state':self.last.get('state','unknown'),'phase':getattr(self.worker,'phase','initial'),
               'received':None,'target':None,'pending':0,'error':self.last.get('error')}
        if self.worker is not None:
            with self.worker.outbox._db() as db:
                row=db.execute('SELECT state,run_id,context FROM participant_runs WHERE task=?',(self.worker.task_id,)).fetchone()
                pending=db.execute("SELECT count(*) FROM participant_delivery WHERE task=? AND state='pending'",(self.worker.task_id,)).fetchone()[0]
                receipts=db.execute("SELECT receipt FROM participant_delivery WHERE task=? AND state='delivered'",(self.worker.task_id,)).fetchall()
            value['pending']=pending
            if row:
                state,run,encoded=row;context=json.loads(encoded)
                value['run_id']=run;value['target']=context.get('target')
                value['received']=context.get('target',0)-context.get('limit',0) if type(context.get('target')) is int and type(context.get('limit')) is int else None
                for r in receipts:
                    n=json.loads(r[0]).get('task_received')
                    if type(n) is int:value['received']=max(value['received'] or 0,n)
                if state=='complete':value['received']=value['target']
                if value['state']=='ready':value['state']=state
        if value['pending'] and value['state']=='running':value['state']='delivery_unknown'
        value['state']=value['state'] if value['state'] in STATES else 'unknown'
        value['phase']=value['phase'] if value['phase'] in PHASES else 'initial'
        value['error']=value['error'] if value['error'] in ERRORS else None
        return value
    def emit(self,message):self.mux.port.send(frame('pro_state',self.mux.session,self.mux.epoch,**self.snapshot()))
    def start(self,message):
        if self.mux.stopped.is_set():raise ProtocolError('participant_stopped')
        if self.reconnected:raise ProtocolError('participant_existing_run')
        if self.start_message is not None:
            if any(message[k]!=self.start_message[k] for k in ('subject','installation_id','task_id','intent')):raise ProtocolError('participant_existing_run')
            self.emit(message);return
        rpc=NativeTransport(self.mux,message['subject'],message['installation_id'],message['task_id'])
        worker=self.worker_class(Path(self.config['root']),rpc,self.runner(),
            task_id=message['task_id'],installation_id=message['installation_id'],subject=message['subject'],session_id=self.config['session_id'],known_ids=[],
            request_options={k:self.config[k] for k in ('purpose','max_api_requests')})
        native_start={k:message[k] for k in ('subject','installation_id','task_id','intent')}
        with worker.outbox._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state,context FROM participant_runs WHERE task=?',(message['task_id'],)).fetchone()
            if row:
                context=json.loads(row[1]);old=context.get('native_start')
                if row[0]!='complete' and (old!=native_start or context.get('binding',{}).get('generation')!=message['epoch']):raise ProtocolError('participant_existing_run')
            else:
                db.execute('INSERT INTO participant_runs VALUES(?,?,NULL,?)',(message['task_id'],'native_ready',mc_runner.canonical({'binding':dict(rpc.binding),'native_start':native_start})))
        self.worker=worker;self.start_message=message
        self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()
    def _run(self):
        try:
            while not self.mux.stopped.is_set():
                result=self.worker.tick(None)
                with self.lock:self.last=result
                self.emit(self.start_message)
                if result.get('state')!='running':return
                self.mux.stopped.wait(1)
        except Exception as e:
            diagnostic=transport_diagnostic(e,getattr(self.worker,'phase','initial')) if isinstance(e,ProtocolError) else {'state':'blocked' if isinstance(e,ParticipantError) else 'unknown','reason':'participant_contract_refused' if isinstance(e,ParticipantError) else 'participant_rpc_outcome_unknown'}
            self.last={'state':diagnostic['state'],'error':diagnostic['reason']}
            try:self.emit(self.start_message)
            except Exception:pass
    def restore_status(self,run_id):
        # Reconnection is read/stop only; an old source operation is never launched again.
        box=ParticipantOutbox(self.config['root'],lambda *a:None)
        with box._db() as db:rows=db.execute('SELECT task,state,run_id,context FROM participant_runs').fetchall()
        found=[]
        for task,state,run,raw in rows:
            c=json.loads(raw);b=c.get('binding',{})
            if b.get('transport')=='native' and b.get('native_session')==self.mux.session and b.get('generation')==self.mux.epoch and run==run_id:found.append((task,state,run,c))
        if len(found)!=1:raise ProtocolError('participant_existing_run')
        task,state,run,c=found[0];b=c['binding'];rpc=NativeTransport(self.mux,b['subject'],b['installation_id'],task)
        self.worker=self.worker_class(Path(self.config['root']),rpc,self.runner(),
            task_id=task,installation_id=b['installation_id'],subject=b['subject'],session_id=self.config['session_id'],known_ids=[],request_options={k:self.config[k] for k in ('purpose','max_api_requests')})
        if state=='running' and run is not None:
            local=self.worker.runner('status',{'run_id':run}).get('state')
            if local in mc_runner.FINAL:state='partial' if local=='completed' else 'source_unknown' if local=='interrupted_unknown' else 'source_failed'
        self.reconnected=True;self.last={'state':state if state in STATES else 'unknown'}
    def stop_owned(self):
        self.mux.stop();unresolved=False
        if self.worker is not None:
            with self.worker.outbox._db() as db:row=db.execute('SELECT run_id FROM participant_runs WHERE task=?',(self.worker.task_id,)).fetchone()
            if row and row[0]:
                state=mc_runner.stop(self.config['root'],{'run_id':row[0],'origin':'user','reason':'user_stop'})
                unresolved=state.get('state') not in mc_runner.FINAL or state.get('state')=='interrupted_unknown'
            with self.worker.outbox._db() as db:unresolved=unresolved or bool(db.execute("SELECT count(*) FROM participant_delivery WHERE task=? AND state='pending'",(self.worker.task_id,)).fetchone()[0])
        with self.mux.lock:unresolved=unresolved or bool(self.mux.pending)
        self.last={'state':'unknown' if unresolved or self.thread and self.thread.is_alive() else 'stopped','error':None}
    def handle(self,message):
        kind=message['type']
        if kind=='pro_start':self.start(message)
        elif kind=='pro_hello':self.emit(message)
        elif kind=='pro_status':
            if self.worker is None:self.restore_status(message['run_id'])
            if message['run_id'] is not None and message['run_id']!=self.snapshot()['run_id']:raise ProtocolError('participant_scope_changed')
            self.emit(message)
        elif kind=='pro_stop':
            if self.worker is None and message['run_id'] is not None:self.restore_status(message['run_id'])
            if message['run_id'] is not None and message['run_id']!=self.snapshot()['run_id']:raise ProtocolError('participant_scope_changed')
            self.stop_owned();self.emit(message)
        else:raise ProtocolError('participant_protocol_invalid')
    def serve(self,first):
        self.handle(first)
        while not self.mux.disconnected.is_set():
            try:message=self.mux.commands.get(timeout=.1)
            except queue.Empty:continue
            try:self.handle(message)
            except Exception as e:
                code=str(e);self.last={'state':'blocked','error':code if code in ERRORS else 'participant_contract_refused'}
                self.emit(message)
        # EOF closes child authority immediately and requests the existing owned-run stop.
        self.stop_owned()
        if self.thread:self.thread.join(3)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    protocol_out=sys.stdout.buffer
    # Library output can never contaminate native framing or leak source data to stderr.
    devnull=open(os.devnull,'w');sys.stdout=devnull;sys.stderr=devnull
    port=FrameIO(sys.stdin.buffer,protocol_out)
    try:
        first=port.read()
        if first['type'] not in ('pro_hello','pro_start'):raise ProtocolError('participant_protocol_invalid')
        try:
            cfg=load_config(args.config);installation_ready(cfg)
        except Exception:
            port.send(frame('pro_state',first['session'],first['epoch'],run_id=None,state='not_ready',phase='initial',received=None,target=None,pending=0,error='participant_installation_invalid'))
            return
        mux=NativeMux(port,first['session'],first['epoch']);mux.seen.add(first['id']);mux.start()
        NativeService(cfg,mux).serve(first)
    except Exception:
        # No raw traceback/URL/credentials. The host keeps disconnect UNKNOWN/busy.
        raise SystemExit(2) from None
if __name__=='__main__':main()
