"""Bounded native frames and one stdio reader; no listener, credentials or platform HTTP."""
import json
import os
import queue
import socket
import stat
import struct
import threading
import uuid
from participant_pro_transport import ParticipantTransportError

SCHEMA='crowd-participant-native-v1'
LIMIT=262144
METHODS=frozenset({'scope','verify_platform_principal','pro_claim','pro_guard','pro_submit','pro_status','pro_receipt','pro_finish','pro_comment_submit','pro_comment_commit','pro_comment_receipt'})
BASE={'schema','type','id','session','epoch'}
EXTRA={'pro_hello':{'version'},'pro_start':{'subject','installation_id','task_id','intent'},
       'pro_status':{'run_id'},'pro_stop':{'run_id'},'rpc_request':{'method','params'},
       'pro_state':{'run_id','state','phase','received','target','pending','error'}}
SAFE_ERRORS=frozenset({'participant_scope_changed','participant_writer_busy','participant_stopped',
                      'participant_rpc_outcome_unknown','participant_protocol_invalid'})
class ProtocolError(ParticipantTransportError):pass

def require(ok):
    if not ok:raise ProtocolError('participant_protocol_invalid')
def valid_uuid(value):
    try:return type(value) is str and str(uuid.UUID(value))==value
    except (ValueError,TypeError,AttributeError):return False

def capability(value):
    require(type(value)is dict and set(value)=={'schema','runtime_sha256','entry_sha256','worker_sha256','upstream_commit','comment_options_v1','max_api_requests'})
    require(value['schema']=='crowd-participant-pro-capability-v1' and value['comment_options_v1'] is True)
    import re
    require(all(type(value[k])is str and re.fullmatch('[a-f0-9]{64}',value[k]) for k in ('runtime_sha256','entry_sha256','worker_sha256')))
    require(type(value['upstream_commit'])is str and re.fullmatch('[a-f0-9]{40}',value['upstream_commit']) and type(value['max_api_requests'])is int and 1<=value['max_api_requests']<=100)
    return value

def validate(value):
    require(type(value) is dict and value.get('schema')==SCHEMA and valid_uuid(value.get('id')) and valid_uuid(value.get('session')))
    require(type(value.get('epoch')) is int and 0<=value['epoch']<=9007199254740991)
    kind=value.get('type');require(type(kind) is str)
    if kind=='rpc_result':
        require(type(value.get('ok')) is bool)
        require(set(value)==BASE|{'ok','result','error'})
        require(value['error'] is None if value['ok'] else value['result'] is None)
        if not value['ok']:require(type(value['error']) is str and value['error'] in SAFE_ERRORS)
    else:
        require(kind in EXTRA and set(value)==BASE|EXTRA[kind]|({'capabilities'} if kind=='pro_state' and 'capabilities'in value else {'capability_request'} if kind=='pro_hello' and 'capability_request'in value else set()))
        if kind=='pro_state' and 'capabilities'in value:capability(value['capabilities'])
    if kind=='rpc_request':require(type(value['method']) is str and value['method'] in METHODS and type(value['params']) is dict)
    if kind=='pro_start':
        require(valid_uuid(value['subject']) and valid_uuid(value['installation_id']) and valid_uuid(value['intent']) and type(value['task_id']) is int and 0<value['task_id']<=9007199254740991)
    if kind in ('pro_stop','pro_status'):require(value['run_id'] is None or valid_uuid(value['run_id']))
    if kind=='pro_hello':
        require(type(value['version']) is int and value['version']==1)
        if 'capability_request'in value:require(value['capability_request']=='pro_comment_options_v1')
    return value

def frame(kind,session,epoch,**extra):
    if kind=='rpc_result':
        extra.setdefault('error',None);extra.setdefault('result',None)
    return validate({'schema':SCHEMA,'type':kind,'id':extra.pop('id',str(uuid.uuid4())),'session':session,'epoch':epoch,**extra})
def _pairs(pairs):
    result={}
    for k,v in pairs:
        require(k not in result);result[k]=v
    return result
class FrameIO:
    def __init__(self,reader,writer):self.reader,self.writer=reader,writer;self.lock=threading.Lock()
    def _read(self,n):
        out=bytearray()
        while len(out)<n:
            chunk=self.reader.read(n-len(out))
            if not chunk:raise ProtocolError('participant_rpc_outcome_unknown')
            out.extend(chunk)
        return bytes(out)
    def read(self):
        n=struct.unpack('<I',self._read(4))[0];require(0<n<=LIMIT)
        try:value=json.loads(self._read(n).decode('utf8'),object_pairs_hook=_pairs,parse_constant=lambda x:require(False))
        except (ValueError,UnicodeError,RecursionError):raise ProtocolError('participant_protocol_invalid') from None
        return validate(value)
    def send(self,value):
        validate(value)
        try:raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8')
        except (ValueError,TypeError,RecursionError):raise ProtocolError('participant_protocol_invalid') from None
        require(0<len(raw)<=LIMIT)
        with self.lock:
            data=memoryview(struct.pack('<I',len(raw))+raw)
            while data:
                count=self.writer.write(data)
                if not count:raise ProtocolError('participant_rpc_outcome_unknown')
                data=data[count:]
            self.writer.flush()

class NativeMux:
    """The parent is the only reader of host stdin; child sockets never consume it."""
    def __init__(self,port,session,epoch,timeout=35):
        require(valid_uuid(session) and type(epoch) is int and 0<=epoch<=9007199254740991)
        self.port,self.session,self.epoch,self.timeout=port,session,epoch,timeout
        self.pending={};self.lock=threading.Lock();self.commands=queue.Queue(16)
        self.stopped=threading.Event();self.disconnected=threading.Event();self.seen=set()
    def start(self):threading.Thread(target=self._reader,daemon=True).start()
    def _reader(self):
        try:
            while not self.disconnected.is_set():
                v=self.port.read();require(v['session']==self.session and (v['epoch']==self.epoch or v['type']=='pro_stop' and v['epoch']>=self.epoch))
                if v['type']=='rpc_result':
                    with self.lock:q=self.pending.get(v['id'])
                    require(q is not None);q.put_nowait(v)
                else:
                    require(v['type'] in ('pro_start','pro_status','pro_stop','pro_hello') and v['id'] not in self.seen and len(self.seen)<2048)
                    self.seen.add(v['id'])
                    if v['type']=='pro_stop':self.stop()
                    self.commands.put_nowait(v)
        except Exception:self.close()
    def call(self,method,params):
        if self.stopped.is_set() or self.disconnected.is_set():raise ProtocolError('participant_stopped')
        v=frame('rpc_request',self.session,self.epoch,method=method,params=params);q=queue.Queue(1)
        with self.lock:
            require(len(self.pending)<32);self.pending[v['id']]=q
        try:
            self.port.send(v)
            try:result=q.get(timeout=self.timeout)
            except queue.Empty:raise ProtocolError('participant_rpc_outcome_unknown') from None
            if result is None or self.stopped.is_set():raise ProtocolError('participant_rpc_outcome_unknown')
            if not result['ok']:raise ProtocolError(result['error'])
            return result['result']
        finally:
            with self.lock:self.pending.pop(v['id'],None)
    def stop(self):
        self.stopped.set()
        with self.lock:
            for q in self.pending.values():
                try:q.put_nowait(None)
                except queue.Full:pass
    def close(self):
        self.stop();self.disconnected.set()
        with self.lock:
            for q in self.pending.values():
                try:q.put_nowait(None)
                except queue.Full:pass

class NativeTransport:
    def __init__(self,mux,subject,installation_id,task_id):
        require(valid_uuid(subject) and valid_uuid(installation_id) and type(task_id) is int and task_id>0)
        self.mux=mux;self.task_id=task_id;self.node=None
        self.binding={'profile':'native-messaging','subject':subject,'installation_id':installation_id,
                      'generation':mux.epoch,'transport':'native','native_session':mux.session}
    def __call__(self,method,params):
        require(method in METHODS and type(params) is dict)
        if method not in ('scope','verify_platform_principal'):
            require(params.get('p_task')==self.task_id)
            require('p_installation_id' not in params or params['p_installation_id']==self.binding['installation_id'])
            params={**params,'p_installation_id':self.binding['installation_id']}
        return self.mux.call(method,params)
    def scope(self):
        value=self('scope',{})
        if type(value) is not dict or value.get('subject')!=self.binding['subject'] or value.get('installation_id')!=self.binding['installation_id'] or type(value.get('generation')) is not int or value['generation']!=self.binding['generation']:
            raise ProtocolError('participant_scope_changed')
        return {k:value[k] for k in ('subject','installation_id')}
    def verify_platform_principal(self,uid):return self('verify_platform_principal',{'uid':uid})

class ChildTransport(NativeTransport):
    def __init__(self,context,fd):
        require(type(fd) is int and fd>2 and stat.S_ISSOCK(os.fstat(fd).st_mode))
        self.socket=socket.socket(fileno=os.dup(fd));self.socket.settimeout(35);self.port=FrameIO(self.socket.makefile('rb',buffering=0),self.socket.makefile('wb',buffering=0));self.lock=threading.Lock()
        self.binding=dict(context['binding']);self.task_id=context['task_id'];self.node=None
    def __call__(self,method,params):
        require(method in METHODS and type(params) is dict)
        v=frame('rpc_request',self.binding['native_session'],self.binding['generation'],method=method,params=params)
        with self.lock:
            self.port.send(v);r=self.port.read()
            require(r['type']=='rpc_result' and r['id']==v['id'] and r['session']==v['session'] and r['epoch']==v['epoch'])
        if not r['ok']:raise ProtocolError(r['error'])
        return r['result']

def from_context(context):
    if context.get('binding',{}).get('transport')=='native':
        try:fd=int(os.environ['CROWD_PARTICIPANT_RPC_FD'])
        except (KeyError,ValueError):raise ProtocolError('participant_protocol_invalid') from None
        return ChildTransport(context,fd)
    from participant_pro_transport import ParticipantProTransport
    return ParticipantProTransport(**context['binding'],node=context['node'])

def relay_child(sock,mux,task_id=None,installation_id=None):
    """Dedicated per-source endpoint; one request at a time, responses keep child UUID."""
    port=FrameIO(sock.makefile('rb',buffering=0),sock.makefile('wb',buffering=0))
    try:
        while not mux.disconnected.is_set():
            v=port.read();require(v['type']=='rpc_request' and v['session']==mux.session and v['epoch']==mux.epoch)
            if task_id is not None and v['method'] not in ('scope','verify_platform_principal'):
                require(v['params'].get('p_task')==task_id and v['params'].get('p_installation_id')==installation_id)
            try:
                result=mux.call(v['method'],v['params']);r=frame('rpc_result',mux.session,mux.epoch,id=v['id'],ok=True,result=result)
            except ParticipantTransportError as e:
                code=str(e);r=frame('rpc_result',mux.session,mux.epoch,id=v['id'],ok=False,error=code if code in SAFE_ERRORS else 'participant_rpc_outcome_unknown')
            port.send(r)
    except Exception:pass  # A lost capability is UNKNOWN; never reconnect or retry a source call.
    finally:sock.close()
