"""Prepare venvs from licensed local upstream locks, never copy/download the SDK.
Only a complete validated RESULT permits reuse. An interrupted install is not
silently repeated. Source/account/readiness actions are not performed here.
"""
from pathlib import Path
import hashlib,json,os,subprocess,sys
from install_machine_node import encode,need,directory,private,sha,write_once

def execute(args,*,env,cwd,timeout=600):
    result=subprocess.run(args,env=env,cwd=cwd,capture_output=True,timeout=timeout)
    need(result.returncode==0 and len(result.stdout)<=65536,'dependency_command_failed')
    return result.stdout

def environment():
    value={'HOME':str(Path.home()),'PATH':os.defpath,'PYTHONDONTWRITEBYTECODE':'1','UV_PYTHON_DOWNLOADS':'never','UV_KEYRING_PROVIDER':'disabled','UV_LINK_MODE':'copy','UV_NO_PROGRESS':'1','GIT_OPTIONAL_LOCKS':'0'}
    return value

def validate(paths,sources,run=execute):
    from pro_executor import probe,PINNED_COMMIT
    info=probe(str(sources['pro']),str(paths['pro']))
    need(info.get('commit')==PINNED_COMMIT and not info.get('dirty'),'pro_source_changed')
    script="import socket;socket.socket.connect=lambda *a,**k:(_ for _ in()).throw(OSError('network denied'));from media_platform.xhs.client import XiaoHongShuClient;from media_platform.xhs.handlers.detail_handler import DetailHandler;from repo.platform_save_data.xhs.xhs_store_impl import XhsDbStoreImplement"
    env=environment();env['PYTHONPATH']=str(sources['pro'])
    run([str(paths['pro']),'-B','-c',script],env=env,cwd=sources['pro'],timeout=20)
    from managed_pro_signer import SERVER
    env=environment();env['PYTHONPATH']=str(Path(__file__).parent)
    value=json.loads(run([str(paths['signer']),'-B',str(SERVER),'--source-root',str(sources['signer'])],env=env,cwd=sources['signer'],timeout=20))
    need(value.get('ok')is True and value.get('validate_only')is True and value.get('listening')is False,'signer_dependency_unavailable')

def prepare(root,sources,python,uv,*,run=execute,validate=None):
    root=Path(root).absolute();python=Path(python).absolute();uv=Path(uv).absolute();need(set(sources)=={'pro','signer'})
    need(root.resolve()==root and python.is_file()and uv.is_file()and os.access(uv,os.X_OK))
    inputs={'link_mode':'copy','python':str(python),'python_sha256':sha(python.read_bytes()),'uv':str(uv),'uv_sha256':sha(uv.read_bytes()),'projects':{}}
    sources={role:Path(path).absolute()for role,path in sources.items()}
    for role,path in sources.items():
        need(path.resolve()==path and path.is_dir());inputs['projects'][role]={'root':str(path),'files':{name:sha((path/name).read_bytes())for name in ('pyproject.toml','uv.lock')}}
    key=sha(encode(inputs));base=root/'node-dependencies';target=base/key
    root.mkdir(mode=0o700,parents=True,exist_ok=True);directory(root);base.mkdir(mode=0o700,exist_ok=True);directory(base)
    if target.exists():
        directory(target);need((target/'RESULT.json').is_file(),'dependency_attempt_unknown');result=json.loads(private(target/'RESULT.json'))
        need(result.get('key')==key and result.get('input')==inputs,'dependency_input_changed')
        for role,pin in result['python_sha256'].items():need(sha(Path(result['environments'][role]).read_bytes())==pin,'dependency_interpreter_changed')
        return {'state':'prepared','key':key,'python':result['environments']['pro'],'signer_python':result['environments']['signer'],'authenticated':False}
    target.mkdir(mode=0o700);write_once(target/'INTENT.json',encode({'key':key,'input':inputs}))
    paths={role:target/role/'bin/python'for role in sources}
    for role,path in sources.items():
        env=environment();env['UV_PROJECT_ENVIRONMENT']=str(target/role);env['UV_CACHE_DIR']=str(root/'dependency-cache')
        run([str(uv),'venv',str(target/role),'--python',str(python)],env=env,cwd=path)
        run([str(uv),'sync','--frozen','--no-dev','--no-install-project','--project',str(path),'--python',str(python)],env=env,cwd=path)
    (validate if validate is not None else lambda value:globals()['validate'](value,sources,run))(paths)
    write_once(target/'RESULT.json',encode({'key':key,'input':inputs,'environments':{role:str(path)for role,path in paths.items()},'python_sha256':{role:sha(path.read_bytes())for role,path in paths.items()}}))
    return {'state':'prepared','key':key,'python':str(paths['pro']),'signer_python':str(paths['signer']),'authenticated':False}
