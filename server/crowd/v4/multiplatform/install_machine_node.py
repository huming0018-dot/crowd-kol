"""Install/start only an owned worker runtime; no SDK, account, pair or OTA mutation.

Operator supplies the exact reviewed NODE-RUNTIME.json hash, a normal separately
paired worker config, licensed SDK path and existing local collector roots.
"""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,stat,sys,tempfile

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

def install(source,pin,root,cloud_config,python,sdk,collectors):
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
    if current.exists():
        need(private(current)==encode(record),'existing_node_configuration_conflict');installed(root)
        return {'state':'current','runtime_sha256':pin,'execution_ready':False}
    base=root/'node-revisions';base.mkdir(mode=0o700,exist_ok=True);directory(base)
    if not target.exists():
        stage=Path(tempfile.mkdtemp(prefix='.stage-',dir=base))
        try:
            for name in value['files']:write_once(stage/name,(Path(source)/name).read_bytes())
            write_once(stage/'NODE-RUNTIME.json',raw);runtime(stage,pin);os.rename(stage,target)
        finally:
            if stage.exists():shutil.rmtree(stage)
    runtime(target,pin)
    if not config.exists():write_once(config,cloud)
    need(private(config)==cloud,'existing_node_configuration_conflict');write_once(current,encode(record))
    fd=os.open(root,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return {'state':'installed','runtime_sha256':pin,'execution_ready':False}

def installed(root):
    root=directory(Path(root).absolute());value=json.loads(private(root/'node-install.json'))
    need(value.get('schema')=='crowd-machine-node-install-v1');runtime(Path(value['runtime']),value['runtime_sha256'])
    need(value['entry']==str(Path(value['runtime'])/'machine_node.py')and sha(Path(value['python']).read_bytes())==value['python_sha256'],'node_runtime_changed')
    need(sha(private(root/'cloud-config.json'))==value['cloud_config_sha256'],'existing_node_configuration_conflict');return value

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    new=sub.add_parser('install');new.add_argument('--runtime',type=Path,required=True);new.add_argument('--runtime-sha256',required=True);new.add_argument('--cloud-config',type=Path,required=True);new.add_argument('--python',type=Path,required=True);new.add_argument('--mc-root',type=Path,required=True);new.add_argument('--collector-root',action='append',type=Path,required=True);new.add_argument('--root',type=Path,required=True)
    start=sub.add_parser('start');start.add_argument('--root',type=Path,required=True);start.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.action=='install':print(json.dumps(install(args.runtime,args.runtime_sha256,args.root,args.cloud_config,args.python,args.mc_root,args.collector_root)));return 0
    v=installed(args.root);argv=[v['python'],'-B',v['entry'],'--root',str(args.root.absolute()),'--mc-root',v['mc_root']]
    for collector in v['collector_roots']:argv+=['--collector-root',collector]
    if args.check:argv+=['--check']
    env={k:v for k,v in os.environ.items()if not k.startswith(('VOX_','DYLD_','LD_','PYTHON'))and k not in ('BASH_ENV','ENV','NODE_OPTIONS','NODE_PATH')};env['PYTHONDONTWRITEBYTECODE']='1'
    os.execve(v['python'],argv,env)
if __name__=='__main__':raise SystemExit(main())
