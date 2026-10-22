"""Linux/WSL2 worker install entry; licensed Pro SDK stays separately local.
Prerequisites: Python3.12, uv and git; a normal separately paired worker config.
No browser/profile/identity copy, Owner key, SDK download or service startup.
"""
from pathlib import Path
import argparse,json,os,sys
from install_machine_node import install,runtime,need,private,write_once,encode
from prepare_machine_node import prepare

def same_or_once(path,value):
    raw=encode(value)
    if path.exists():need(private(path)==raw,'existing_node_configuration_conflict')
    else:write_once(path,raw)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('runtime','root','cloud-config','sdk-root','signer-root','uv'):parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--runtime-sha256',required=True)
    parser.add_argument('--collector-root',type=Path)
    args=parser.parse_args();need(sys.platform.startswith('linux')and sys.version_info[:2]==(3,12),'linux_python312_required')
    runtime(args.runtime,args.runtime_sha256)
    sys.path.insert(0,str(args.runtime.absolute()))
    # These are the original source and Signer hash checks; do not install code
    # from an arbitrary path just because the operator can name it.
    from pro_executor import PINNED_COMMIT
    from mc_runner import source_info
    from pro_signer_server import verify_source
    info=source_info(args.sdk_root);need(info['commit']==PINNED_COMMIT and not info['dirty'],'pro_source_changed');verify_source(args.signer_root)
    from portable_node import prepare as node_prepare
    helper=Path.home()/'.local/share/CrowdV4Updater';helper.mkdir(mode=0o700,parents=True,exist_ok=True);node_prepare(helper)
    prepared=prepare(args.root,{'pro':args.sdk_root,'signer':args.signer_root},Path(sys.executable),args.uv)
    collector=args.collector_root or args.root/'collector';collector.mkdir(mode=0o700,parents=True,exist_ok=True)
    for name in ('runs','sessions'):(collector/name).mkdir(mode=0o700,exist_ok=True)
    same_or_once(collector/'pro-executor.json',{'root':str(args.sdk_root.absolute()),'python':prepared['python']})
    same_or_once(collector/'pro-signer.json',{'source_root':str(args.signer_root.absolute()),'python':prepared['signer_python']})
    result=install(args.runtime,args.runtime_sha256,args.root,args.cloud_config,Path(sys.executable),args.sdk_root,[collector])
    print('Next: start the separately installed original CookieBridge on 127.0.0.1:8274, then use bind-linux.sh with your local Client ID. See README.md.',file=sys.stderr)
    print(json.dumps({**result,'authenticated':False,'local_account_binding_required':True,'scheduler_started':False}));return 0
if __name__=='__main__':raise SystemExit(main())
