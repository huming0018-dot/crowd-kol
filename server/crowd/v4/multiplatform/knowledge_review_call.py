"""Fixed 065 subprocess boundary for the existing local Owner workbench."""
from pathlib import Path
import json,os,stat,subprocess,tempfile
from material_bridge import parse_json
from workbench_material_call import command as material_command


def call(config_path, cloud_config, body):
    if type(body)is not dict or set(body)!={'action','payload'} or body['action'] not in ('preview','decide','status','publication_preview','publication_release','publication_pin','publication_rollback','publication_status','publication_read') or type(body['payload'])is not dict:
        raise ValueError('knowledge_request_invalid')
    raw=json.dumps(body,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>32768:raise ValueError('knowledge_request_too_large')
    path=Path(config_path)
    if any(p.is_symlink()for p in (path,*path.parents)):raise ValueError('knowledge_runtime_unsafe')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb')as f:
        info=os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>65536:
            raise ValueError('knowledge_runtime_requires_0600')
        cfg=parse_json(f.read(65537))
    # Reuse the already audited Python/script/request validation contract.
    verified=material_command(cfg,'read','json')
    argv=verified[:3]+['--service-config',cfg['request'],'--service-sha256',cfg['request_sha256'],'--cloud-config',str(cloud_config),'--body-fd','0']
    env={'PATH':os.environ.get('PATH',''),'PYTHONPATH':str(Path(cfg['script']).parent),'PYTHONDONTWRITEBYTECODE':'1'}
    with tempfile.TemporaryFile()as output:
        try:
            process=subprocess.run(argv,input=raw,stdout=output,stderr=subprocess.DEVNULL,env=env,timeout=25,close_fds=True)
        except subprocess.TimeoutExpired:
            raise ValueError('knowledge_outcome_unknown'if body['action']in ('decide','publication_release','publication_pin','publication_rollback')else 'knowledge_read_unavailable')from None
        if os.fstat(output.fileno()).st_size>1024*1024:
            raise ValueError('knowledge_request_unavailable')
        output.seek(0);value=parse_json(output.read(1024*1024+1))
        prewrite={'knowledge_preview_expired','knowledge_decision_invalid','knowledge_decision_request_invalid','knowledge_preview_required'}
        if (body['action']=='decide' and process.returncode==2 and type(value)is dict
                and set(value)=={'error'} and type(value['error'])is str and value['error']in prewrite):
            return {'state':'not_submitted','error_code':value['error'],'message':'本次决定未提交：预览已过期或输入未通过校验。请刷新提案，原理由可保留。'}
        if process.returncode:raise ValueError('knowledge_request_unavailable')
    if type(value)is not dict or 'error'in value:
        raise ValueError('knowledge_result_invalid')
    return value
