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
    if c.get('schema')=='crowd-material-recompute-v1':return 'reprocess-'+sha(canonical(c))
    return 'pro-'+sha(canonical(c)) if c.get('schema')=='crowd-participant-pro-material-context-v1' else c['local_run_id']
def validate_context(c):
    if type(c)is dict and c.get('schema')=='crowd-material-recompute-v1':
        if set(c)!={'schema','original','pro_key','expected_job','target_release','config'}:raise ValueError('material_recompute_invalid')
        original=validate_context(c['original'])
        if original['schema']!='crowd-participant-pro-material-context-v1'or material_context_key(original)!=c['pro_key']:raise ValueError('material_recompute_invalid')
        import re
        release=c['target_release'];cfg=c['config']
        if type(release)is not dict or set(release)!={'pack_id','version','hash'}or not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',release['pack_id'])or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',release['version'])or not re.fullmatch('[a-f0-9]{64}',release['hash'])or not re.fullmatch('[a-f0-9]{64}',c['expected_job']):raise ValueError('material_recompute_invalid')
        if type(cfg)is not dict or set(cfg)not in (KEYS|{'pro_snapshot_sha256'},KEYS|{'pro_snapshot_sha256','pro_comments_sha256'}):raise ValueError('material_recompute_invalid')
        return c
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
                config=c['config']if c.get('schema')=='crowd-material-recompute-v1'else private_json(self.root/'data-products/material-auto-runtime.json')
                if type(config)is not dict or set(config)not in (KEYS,KEYS|{'pro_snapshot_sha256'},KEYS|{'pro_snapshot_sha256','pro_comments_sha256'}):raise ValueError('material_auto_config_invalid')
                if _digest(config['worker_script'])!=config['worker_sha256']:raise ValueError('material_auto_worker_changed')
                r={'process':None,'thread':None};self.running[local]=r
                thread=threading.Thread(target=self._work,args=(local,path,config,r),daemon=True)
                r['thread']=thread;thread.start()
        # Retain the existing durable postprocessing_runs item until ready.
        return {'material_pending': True, 'state': 'processing'}
    def prepare_recompute(self,key,expected_job,resolved):
        """Internal server resolver only; no browser filesystem paths or approval writes."""
        import base64,yaml
        from participant_material_delivery import publication
        from workbench_material_call import command
        with self.lock:
            current=publication(self.root,key)
            if current.get('state')!='ready'or current.get('job_id')!=expected_job:raise ValueError('material_recompute_current_changed')
            pointer=current['publication_pointer'];command(pointer,'read','json')
            request=private_json(pointer['request'])
            if sha(canonical(request))!=pointer['request_sha256']:raise ValueError('material_recompute_original_changed')
            original_pack=yaml.safe_load(Path(request['pack_path'],'pack.yaml').read_bytes())['pack']['pack_id']
            if type(resolved)is not dict or set(resolved)!={'release','files'}or resolved['release']['pack_id']!=original_pack:raise ValueError('material_recompute_pack_scope')
            release=resolved['release'];files=resolved['files'];names={'pack.yaml','fields.yaml','pointers.json','validation.yaml','rubric.yaml','expectations.yaml'}
            if type(files)is not dict or set(files)!=names:raise ValueError('material_recompute_pack_invalid')
            raw={name:base64.b64decode(files[name],validate=True)for name in names}
            if sum(map(len,raw.values()))>4*1024*1024:raise ValueError('material_recompute_pack_invalid')
            parsed={name.split('.')[0]:json.loads(raw[name])if name=='pointers.json'else yaml.safe_load(raw[name])for name in names}
            if sha(canonical(parsed))!=release['hash']:raise ValueError('material_recompute_pack_changed')
            meta=yaml.safe_load(raw['pack.yaml'])['pack']
            if meta['pack_id']!=release['pack_id']or meta['version']!=release['version']:raise ValueError('material_recompute_pack_invalid')
            cfg=private_json(self.root/'data-products/material-auto-runtime.json')
            # The original ready job supplies the exact source/tool pins. Only pack changes.
            for k in ('toolbox_root','toolbox_pins'):
                if cfg[k]!=request[k]:raise ValueError('material_recompute_runtime_changed')
            pins={name:sha(blob)for name,blob in raw.items()}
            artifact=sha(canonical({'pro_key':key,'release':release,'pins':pins,'source_request':pointer['request_sha256']}))
            project=self.directory/artifact;pack=project/'target-pack'
            if any(p.is_symlink()for p in (pack,*pack.parents)):raise ValueError('material_auto_path_invalid')
            project.mkdir(mode=0o700,exist_ok=True);pack.mkdir(mode=0o700,exist_ok=True)
            if any(p.is_symlink()for p in (pack,*pack.parents)):raise ValueError('material_auto_path_invalid')
            for name,blob in raw.items():
                target=pack/name
                if target.is_symlink():raise ValueError('material_auto_path_invalid')
                if target.exists():
                    if target.read_bytes()!=blob:raise ValueError('material_recompute_pack_changed')
                else:
                    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                    with os.fdopen(fd,'wb')as stream:stream.write(blob);stream.flush();os.fsync(stream.fileno())
            cfg={**cfg,'pack_path':str(pack),'pack_sha256':pins}
            result={'schema':'crowd-material-recompute-v1','original':current['context'],'pro_key':key,'expected_job':expected_job,'target_release':release,'config':cfg}
            validate_context(result)
            # Persist old readable descriptor before any work is scheduled. Never modify old state here.
            old=Path(pointer['request']).parent/'ready.json'
            if old.exists():
                if {**private_json(old),'context':current['context']}!=current:raise ValueError('material_recompute_original_changed')
            else:write(old,current)
            return result

    def select_version(self,key,expected_job,job_id):
        from participant_material_delivery import publication
        with self.lock:
            current=publication(self.root,key);chosen=publication(self.root,key,job_id=job_id)
            if current.get('state')!='ready'or current.get('job_id')!=expected_job:raise ValueError('material_recompute_current_changed')
            if chosen.get('state')!='ready':raise ValueError('material_recompute_not_ready')
            write(self.directory/(key+'.json'),{**chosen,'context':current['context']})
            return {'state':'selected','pro_key':key,'job_id':job_id,'source_calls':0,'knowledge_pin_changed':False,'cloud_pointer_changed':False}

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
