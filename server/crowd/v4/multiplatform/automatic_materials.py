"""Existing postprocessing_runs owns retry; one owned deterministic child."""
from pathlib import Path
import hashlib,json,os,signal,stat,subprocess,tempfile,threading,time,uuid
from workbench_material_call import _digest
KEYS={'python','worker_script','worker_sha256','toolbox_root','toolbox_pins','pack_path','pack_sha256','bridge_path','bridge_sha256','runtime_root','runtime_cloud_sha256'}
class MaterialPending(ValueError):pass
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def private_json(path):
    p=Path(path)
    if any(x.is_symlink()for x in (p,*p.parents)):raise ValueError('material_auto_config_invalid')
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb')as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077 or st.st_size>1024*1024:raise ValueError('material_auto_config_invalid')
        blob=f.read(1024*1024+1)
    return json.loads(blob)
def write(path,value):
    path=Path(path)
    if any(x.is_symlink()for x in (path,*path.parents)):raise ValueError('material_auto_path_invalid')
    fd,tmp=tempfile.mkstemp(prefix='.material-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb')as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def material_context_key(c):
    validate_context(c)
    return 'pro-'+sha(canonical(c)) if c.get('schema')=='crowd-participant-pro-material-context-v1' else c['local_run_id']
def validate_context(c):
    if type(c)is dict and c.get('schema')=='crowd-participant-pro-material-context-v1':
        from pro_ack_snapshot import validate_context as validate_pro_context
        return validate_pro_context(c)
    keys={'schema','local_run_id','task_id','child_id','cloud_run_id','lease_epoch','platform','outcome','api_attempts','finish_hash','finish_verified'}
    if type(c)is not dict or set(c)!=keys:raise ValueError('material_auto_context_invalid')
    for k in ['local_run_id','task_id','child_id','cloud_run_id']:
        if type(c[k])is not str or str(uuid.UUID(c[k]))!=c[k]:raise ValueError('material_auto_context_invalid')
    if c['schema']!='crowd-material-postprocessing-v1' or c['finish_verified'] is not True or c['outcome']not in ('completed','failed','stopped') or type(c['lease_epoch'])is not int or c['lease_epoch']<1 or type(c['api_attempts'])is not int or c['api_attempts']<0:raise ValueError('material_auto_context_invalid')
    if type(c['platform'])is not str or type(c['finish_hash'])is not str or len(c['finish_hash'])!=64 or any(x not in '0123456789abcdef'for x in c['finish_hash']):raise ValueError('material_auto_context_invalid')
    return c
class AutomaticMaterials:
    def __init__(self,root):
        self.root=Path(root).absolute();self.directory=self.root/'data-products/material-auto'
        if any(x.is_symlink()for x in (self.directory,*self.directory.parents)):raise ValueError('material_auto_path_invalid')
        self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.lock=threading.Lock();self.running={};self.closed=False
    def enqueue(self,context):
        c=validate_context(context);local=material_context_key(c);path=self.directory/(local+'.json')
        with self.lock:
            if self.closed:raise MaterialPending('material_auto_closed')
            if path.exists():
                old=private_json(path)
                if old.get('context')!=c:raise ValueError('material_auto_context_changed')
                if old.get('state')in ('ready','no_new_ack'):return old
                if old.get('state')=='blocked':raise MaterialPending('material_auto_blocked')
            else:write(path,{'state':'waiting','context':c})
            if local not in self.running and not self.running:
                config=private_json(self.root/'data-products/material-auto-runtime.json')
                if type(config)is not dict or set(config)not in (KEYS,KEYS|{'pro_snapshot_sha256'},KEYS|{'pro_snapshot_sha256','pro_comments_sha256'}):raise ValueError('material_auto_config_invalid')
                if _digest(config['worker_script'])!=config['worker_sha256']:raise ValueError('material_auto_worker_changed')
                r={'process':None,'thread':None};self.running[local]=r
                thread=threading.Thread(target=self._work,args=(local,path,config,r),daemon=True)
                r['thread']=thread;thread.start()
        # Retain the existing durable postprocessing_runs item until ready.
        return {'material_pending': True, 'state': 'processing'}
    def _work(self,local,path,config,r):
        try:
            cfg=self.directory/(local+'.config.json');write(cfg,config)
            cmd=[config['python'],'-B',config['worker_script'],'--context',str(path),'--config',str(cfg),'--root',str(self.root),'--parent-pid',str(os.getpid())]
            with tempfile.TemporaryFile()as log:
                with self.lock:
                    if self.closed:return
                    p=subprocess.Popen(cmd,stdout=log,stderr=log,start_new_session=True,close_fds=True)
                    r['process']=p
                try:code=p.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid,signal.SIGTERM)
                    try:p.wait(timeout=2)
                    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
                    code=74
            state=private_json(path)
            if code or state.get('state')not in ('ready','no_new_ack'):
                write(path,{**state,'state':'waiting' if self.closed else 'blocked','error':'material_auto_interrupted' if self.closed else 'material_auto_processing_failed'})
        except Exception:
            try:
                value=private_json(path);write(path,{**value,'state':'blocked','error':'material_auto_processing_failed'})
            except Exception:pass
        finally:
            with self.lock:self.running.pop(local,None)
    def close(self):
        # Reuse the existing owned-group TERM/KILL/reap contract, including its
        # guard against signaling an already reaped/reused leader PID.
        from managed_pro_signer import stop_owned
        with self.lock:
            self.closed=True;running=list(self.running.values())
        failure=None
        for r in running:
            p=r.get('process')
            if p is not None:
                try:stop_owned(p)
                except Exception as error:failure=error
        for r in running:
            t=r.get('thread')
            if t:
                t.join(timeout=3)
                if t.is_alive():failure=MaterialPending('material_auto_stop_unknown')
        if failure is not None:raise MaterialPending('material_auto_stop_unknown')from failure
