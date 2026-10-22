"""Install/start only an owned worker runtime; no SDK, account, pair or OTA mutation.

Operator supplies the exact reviewed NODE-RUNTIME.json hash, a normal separately
paired worker config, licensed SDK path and existing local collector roots.
"""
from pathlib import Path
import argparse,contextlib,fcntl,hashlib,json,os,re,shutil,sqlite3,stat,sys,tempfile

def sha(raw):return hashlib.sha256(raw).hexdigest()
def need(ok,reason='node_installation_invalid'):
    if not ok:raise ValueError(reason)
def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def private(path):
    path=Path(path);s=path.lstat();need(not path.is_symlink()and stat.S_ISREG(s.st_mode)and s.st_uid==os.getuid()and not s.st_mode&0o077)
    return path.read_bytes()
def directory(path):
    path=Path(path);need(path.is_absolute()and path.resolve()==path and path.is_dir())
    s=path.stat();need(s.st_uid==os.getuid()and not s.st_mode&0o077);return path
def write_once(path,raw):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
def runtime(source,pin):
    source=Path(source);need(source.is_absolute()and source.resolve()==source)
    raw=(source/'NODE-RUNTIME.json').read_bytes();need(sha(raw)==pin,'node_runtime_changed');value=json.loads(raw)
    need(set(value)=={'schema','files'}and value['schema']=='crowd-machine-node-runtime-v1'and type(value['files'])is dict and 5<=len(value['files'])<=512)
    need({'machine_node.py','cloud_sync.py','mc_runner.py','pro_executor.py','portable_node.py'}<=value['files'].keys())
    for name,digest in value['files'].items():
        need(type(name)is str and re.fullmatch('[A-Za-z0-9_.-]+',name)and not name.startswith('test_')and(name.endswith('.py')or name in {'SIGN-SOURCE-SHA.json','DEPENDENCIES.json','DEPENDENCY-SHA.json','NODE-SHA.json','pro_xhs_download.mjs'}))
        path=source/name;need(not path.is_symlink()and path.is_file()and re.fullmatch('[a-f0-9]{64}',digest)and sha(path.read_bytes())==digest,'node_runtime_changed')
    return value,raw

def install(source,pin,root,cloud_config,python,sdk,collectors,*,upgrade=False):
    need(os.name=='posix','linux_or_macos_required');value,raw=runtime(source,pin)
    cloud=private(cloud_config);data=json.loads(cloud);need('owner_key'not in data,'worker_only_config_required')
    from cloud_sync import CloudClient
    CloudClient(cloud_config,'worker')  # Validation only; no HTTP call.
    python=Path(python).absolute();need(python.is_file()and os.access(python,os.X_OK))
    sdk=Path(sdk).absolute();need(sdk.is_dir());collectors=[Path(p).absolute()for p in collectors]
    need(collectors and all((p/'runs').is_dir()and(p/'sessions').is_dir()for p in collectors),'collector_root_required')
    root=Path(root).absolute();need(root.resolve()==root)
    fingerprint=sha(raw);target=root/'node-revisions'/fingerprint
    record={'schema':'crowd-machine-node-install-v1','runtime':str(target),'runtime_sha256':pin,'entry':str(target/'machine_node.py'),'python':str(python),'python_sha256':sha(python.read_bytes()),'mc_root':str(sdk),'collector_roots':[str(p)for p in collectors],'cloud_config_sha256':sha(cloud)}
    if root.exists():directory(root)
    else:root.mkdir(mode=0o700,parents=True)
    config=root/'cloud-config.json';current=root/'node-install.json'
    if config.exists():need(private(config)==cloud,'existing_node_configuration_conflict')
    previous=installed(root)if current.exists()else None
    if previous is not None:
        if private(current)==encode(record):return {'state':'current','runtime_sha256':pin,'execution_ready':False}
        need(upgrade,'existing_node_configuration_conflict')
        mutable={'runtime','runtime_sha256','entry'}
        need({k:v for k,v in previous.items()if k not in mutable}=={k:v for k,v in record.items()if k not in mutable},'upgrade_identity_or_configuration_changed')
    base=root/'node-revisions';base.mkdir(mode=0o700,exist_ok=True);directory(base)
    if not target.exists():
        stage=Path(tempfile.mkdtemp(prefix='.stage-',dir=base))
        try:
            for name in value['files']:write_once(stage/name,(Path(source)/name).read_bytes())
            write_once(stage/'NODE-RUNTIME.json',raw);runtime(stage,pin);os.rename(stage,target)
        finally:
            if stage.exists():shutil.rmtree(stage)
    runtime(target,pin)
    if previous is not None:return upgrade_record(root,previous,record)
    if not config.exists():write_once(config,cloud)
    need(private(config)==cloud,'existing_node_configuration_conflict');write_once(current,encode(record))
    fd=os.open(root,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return {'state':'installed','runtime_sha256':pin,'execution_ready':False}

def worker_running(record,root):
    need(sys.platform.startswith('linux')and Path('/proc').is_dir(),'upgrade_requires_linux_process_guard')
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if p.stat().st_uid!=os.getuid():continue
            args=(p/'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:continue
        except PermissionError:raise ValueError('upgrade_process_unverified')from None
        same_entry=os.fsencode(record['entry'])in args or any(args[i:i+2]==[b'-m',b'machine_node']for i in range(len(args)-1))
        same_root=any(args[i:i+2]==[b'--root',os.fsencode(root)]for i in range(len(args)-1))or b'--root='+os.fsencode(root)in args
        if same_entry and same_root:return True
    return False

def upgrade_record(root,before,after):
    current=root/'node-install.json';raw=private(current);need(json.loads(raw)==before,'upgrade_installation_changed')
    need(not worker_running(before,root),'upgrade_worker_must_be_stopped')
    with contextlib.ExitStack()as stack:
        worker=root/'cloud-worker';worker.mkdir(mode=0o700,exist_ok=True);directory(worker)
        locks=[root/'node-upgrade.lock',worker/'worker.lock']
        for collector in before['collector_roots']:
            for session in sorted((Path(collector)/'sessions').iterdir()):
                need(not session.is_symlink(),'upgrade_session_unsafe')
                if session.is_dir():locks.append(session/'active.lock')
        for path in locks:
            fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600);stack.callback(os.close,fd)
            metadata=os.fstat(fd);need(stat.S_ISREG(metadata.st_mode)and metadata.st_uid==os.getuid()and not metadata.st_mode&0o022,'upgrade_lock_unsafe')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('upgrade_worker_or_session_busy')from None
        need(private(current)==raw and not worker_running(before,root),'upgrade_installation_changed')
        state_path=worker/'state.json';state= json.loads(private(state_path))if state_path.exists()else {'phase':'idle'}
        need(state.get('phase')=='idle'and state.get('lease')is None and state.get('local_run_id')is None and all(type(state.get(k,[]))is list and not state.get(k,[])for k in('pending_deliveries','waiting_logins','postprocessing_runs'))and type(state.get('postprocessing_contexts',{}))is dict and not state.get('postprocessing_contexts',{}),'upgrade_worker_not_idle')
        db=root/'cloud-outbox/outbox.sqlite3'
        if db.exists():
            need(not db.is_symlink(),'upgrade_outbox_unsafe')
            with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)as conn:need(conn.execute("SELECT count(*)FROM captures WHERE state!='acknowledged'").fetchone()[0]==0,'upgrade_outbox_pending')
        intent=root/('node-upgrade-'+after['runtime_sha256']+'.INTENT.json')
        write_once(intent,encode({'state':'attempted_no_retry','before':before,'after':after,'before_sha256':sha(raw)}))
        sync_directory(root)  # Durable INTENT must precede any live pointer replacement.
        temporary=root/('.node-install-'+after['runtime_sha256']+'.tmp');write_once(temporary,encode(after))
        need(private(current)==raw,'upgrade_installation_changed');os.replace(temporary,current)
        fd=os.open(root,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        need(installed(root)==after,'upgrade_after_changed')
        write_once(root/('node-upgrade-'+after['runtime_sha256']+'.RESULT.json'),encode({'state':'upgraded','runtime_sha256':after['runtime_sha256'],'identity_or_cloud_config_changed':False,'scheduler_started':False}))
        sync_directory(root)
    return {'state':'upgraded','runtime_sha256':after['runtime_sha256'],'execution_ready':False,'scheduler_started':False}

def sync_directory(path):
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

def installed(root):
    root=directory(Path(root).absolute());value=json.loads(private(root/'node-install.json'))
    need(value.get('schema')=='crowd-machine-node-install-v1');runtime(Path(value['runtime']),value['runtime_sha256'])
    need(value['entry']==str(Path(value['runtime'])/'machine_node.py')and sha(Path(value['python']).read_bytes())==value['python_sha256'],'node_runtime_changed')
    need(sha(private(root/'cloud-config.json'))==value['cloud_config_sha256'],'existing_node_configuration_conflict');return value

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    new=sub.add_parser('install');new.add_argument('--runtime',type=Path,required=True);new.add_argument('--runtime-sha256',required=True);new.add_argument('--cloud-config',type=Path,required=True);new.add_argument('--python',type=Path,required=True);new.add_argument('--mc-root',type=Path,required=True);new.add_argument('--collector-root',action='append',type=Path,required=True);new.add_argument('--root',type=Path,required=True);new.add_argument('--upgrade',action='store_true')
    start=sub.add_parser('start');start.add_argument('--root',type=Path,required=True);start.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.action=='install':print(json.dumps(install(args.runtime,args.runtime_sha256,args.root,args.cloud_config,args.python,args.mc_root,args.collector_root,upgrade=args.upgrade)));return 0
    v=installed(args.root);argv=[v['python'],'-B',v['entry'],'--root',str(args.root.absolute()),'--mc-root',v['mc_root']]
    for collector in v['collector_roots']:argv+=['--collector-root',collector]
    if args.check:argv+=['--check']
    env={k:v for k,v in os.environ.items()if not k.startswith(('VOX_','DYLD_','LD_','PYTHON'))and k not in ('BASH_ENV','ENV','NODE_OPTIONS','NODE_PATH')};env['PYTHONDONTWRITEBYTECODE']='1'
    os.execve(v['python'],argv,env)
if __name__=='__main__':raise SystemExit(main())
