"""Linux/WSL2 worker install entry; licensed Pro SDK stays separately local.
Prerequisites: Python3.12, uv and git; a normal separately paired worker config.
No browser/profile/identity copy, Owner key, SDK download or service startup.
"""
from pathlib import Path
import argparse,json,os,sys
from install_machine_node import install,installed,runtime,need,private,write_once,encode
from prepare_machine_node import prepare

def same_or_once(path,value):
    raw=encode(value)
    if path.exists():need(private(path)==raw,'existing_node_configuration_conflict')
    else:write_once(path,raw)
def local_project(explicit,name,homes):
    if explicit is not None:return explicit.absolute()
    marker='server/app.py' if name=='MediaCrawlerPro-CookieBridge' else 'pyproject.toml'
    matches={str((home/name).resolve())for home in homes if(home/name/marker).is_file()}
    need(len(matches)==1,'licensed_'+name+'_missing_or_ambiguous_supply_local_path')
    return Path(matches.pop())

def prepare_node(helper,cache):
    from portable_node import prepare,architecture,VERSION,MAX_ARCHIVE
    if cache is None:return prepare(helper)
    name='node-'+VERSION+'-linux-'+architecture()+'.tar.gz'
    archive=cache/name
    def cached(url):
        need(url=='https://nodejs.org/download/release/'+VERSION+'/'+name,'node_archive_cache_url_changed')
        need(archive.exists(),'node_archive_cache_missing')
        need(not archive.is_symlink()and archive.is_file(),'node_archive_cache_unsafe')
        need(archive.stat().st_size<=MAX_ARCHIVE,'node_archive_too_large')
        with archive.open('rb')as stream:raw=stream.read(MAX_ARCHIVE+1)
        need(len(raw)<=MAX_ARCHIVE,'node_archive_too_large')
        return raw  # Original prepare/resource still verifies pinned archive, files and licenses.
    return prepare(helper,fetch=cached)

def existing_dependencies(root,sdk,signer,collector):
    record=installed(root)
    need(record['mc_root']==str(sdk)and record['collector_roots']==[str(collector)],'existing_node_configuration_conflict')
    pro=json.loads(private(collector/'pro-executor.json'));sign=json.loads(private(collector/'pro-signer.json'))
    need(set(pro)=={'root','python'}and pro['root']==str(sdk)and set(sign)=={'source_root','python'}and sign['source_root']==str(signer),'existing_node_configuration_conflict')
    from pro_executor import probe
    from pro_signer_server import verify_source
    verify_source(signer);probe(str(sdk),pro['python'])
    need(Path(sign['python']).is_file(),'selected_signer_python_missing')
    return record

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('runtime','root','cloud-config','sdk-root','signer-root','uv','pro-home','bootstrap-cache','bridge-root'):parser.add_argument('--'+flag,type=Path)
    parser.add_argument('--check',action='store_true');parser.add_argument('--upgrade',action='store_true')
    parser.add_argument('--runtime-sha256')
    parser.add_argument('--collector-root',type=Path)
    args=parser.parse_args();need(sys.platform.startswith('linux')and sys.version_info[:2]==(3,12),'linux_python312_required')
    args.root=(args.root or Path.home()/'.local/share/CrowdWorker').absolute()
    old=installed(args.root)if(args.root/'node-install.json').exists()else None
    args.runtime=(args.runtime or Path(__file__).parent/'server/crowd/v4/multiplatform').absolute()
    if args.runtime_sha256 is None:
        package=json.loads((Path(__file__).parent/'PACKAGE-MANIFEST.json').read_bytes());args.runtime_sha256=package['runtime_manifest_sha256']
    runtime(args.runtime,args.runtime_sha256)
    args.cloud_config=args.cloud_config or args.root/'cloud-config.json'
    collector=(args.collector_root or(Path(old['collector_roots'][0])if old else args.root/'collector')).absolute()
    homes=[p for p in(args.pro_home,Path.home()/'MediaCrawlerPro',Path.home()/'mediacrawler-pro',Path.home())if p is not None]
    if old and args.sdk_root is None:args.sdk_root=Path(old['mc_root'])
    if old and args.signer_root is None:args.signer_root=Path(json.loads(private(collector/'pro-signer.json'))['source_root'])
    args.sdk_root=local_project(args.sdk_root,'MediaCrawlerPro-Python',homes)
    args.signer_root=local_project(args.signer_root,'MediaCrawlerPro-SignSrv',homes)
    sys.path.insert(0,str(args.runtime.absolute()))
    # These are the original source and Signer hash checks; do not install code
    # from an arbitrary path just because the operator can name it.
    from pro_executor import PINNED_COMMIT
    from mc_runner import source_info
    from pro_signer_server import verify_source
    info=source_info(args.sdk_root);need(info['commit']==PINNED_COMMIT and not info['dirty'],'pro_source_changed');verify_source(args.signer_root)
    if old:
        record=existing_dependencies(args.root,args.sdk_root,args.signer_root,collector)
        if args.check:
            print(json.dumps({'state':'installed_dependencies_checked','authenticated':'not_rechecked','scheduler_started':False}));return 0
        if args.bridge_root is not None:
            need(args.uv is not None,'uv_required')
            from local_cookiebridge import prepare as bridge_prepare
            bridge_prepare(args.root,collector,args.bridge_root,Path(record['python']),args.uv)
        result=install(args.runtime,args.runtime_sha256,args.root,args.cloud_config,Path(record['python']),args.sdk_root,[collector],upgrade=args.upgrade)
        print(json.dumps({**result,'existing_identity_preserved':True,'scheduler_started':False}));return 0
    need(not args.check,'node_not_installed_run_install')
    need(args.uv is not None,'uv_required')
    helper=Path.home()/'.local/share/CrowdV4Updater';helper.mkdir(mode=0o700,parents=True,exist_ok=True);prepare_node(helper,args.bootstrap_cache)
    prepared=prepare(args.root,{'pro':args.sdk_root,'signer':args.signer_root},Path(sys.executable),args.uv)
    collector.mkdir(mode=0o700,parents=True,exist_ok=True)
    for name in ('runs','sessions'):(collector/name).mkdir(mode=0o700,exist_ok=True)
    same_or_once(collector/'pro-executor.json',{'root':str(args.sdk_root.absolute()),'python':prepared['python']})
    same_or_once(collector/'pro-signer.json',{'source_root':str(args.signer_root.absolute()),'python':prepared['signer_python']})
    from local_cookiebridge import prepare as bridge_prepare
    args.bridge_root=local_project(args.bridge_root,'MediaCrawlerPro-CookieBridge',homes)
    bridge_prepare(args.root,collector,args.bridge_root,Path(sys.executable),args.uv)
    result=install(args.runtime,args.runtime_sha256,args.root,args.cloud_config,Path(sys.executable),args.sdk_root,[collector])
    print('Next: bind-linux.sh reuses your existing binding or starts the original local Bridge and selects its unique connected XHS client. Complete login in the original browser extension if needed.',file=sys.stderr)
    print(json.dumps({**result,'authenticated':False,'local_account_binding_required':True,'scheduler_started':False}));return 0
if __name__=='__main__':raise SystemExit(main())
