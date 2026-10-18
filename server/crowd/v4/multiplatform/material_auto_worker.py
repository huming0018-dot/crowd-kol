"""Owned deterministic post-finish worker; original Jobs is in pinned bridge."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,signal,subprocess,sys,threading,time
from automatic_materials import private_json,write,validate_context,canonical,sha,KEYS
from workbench_material_call import _digest
from ack_snapshot import read_scope_rows,extract_rows

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--context',required=True);ap.add_argument('--config',required=True);ap.add_argument('--root',required=True);ap.add_argument('--parent-pid',type=int,required=True);args=ap.parse_args()
    if os.getpgrp()!=os.getpid() or os.getppid()!=args.parent_pid:raise ValueError('material_auto_parent_invalid')
    done=threading.Event()
    def watch_parent():
        while not done.wait(.5):
            if os.getppid()!=args.parent_pid:
                os.killpg(os.getpgrp(),signal.SIGKILL);os._exit(74)
    threading.Thread(target=watch_parent,daemon=True).start()
    try:process(Path(args.root),Path(args.context),private_json(args.config))
    finally:done.set()
def process(root,path,cfg):
    if type(cfg)is not dict or set(cfg)not in (KEYS,KEYS|{'pro_snapshot_sha256'}):raise ValueError('material_auto_config_invalid')
    state=private_json(path);c=validate_context(state['context'])
    if _digest(cfg['bridge_path'])!=cfg['bridge_sha256']:raise ValueError('material_auto_bridge_changed')
    if _digest(Path(cfg['runtime_root'])/'cloud_sync.py')!=cfg['runtime_cloud_sha256']:raise ValueError('material_auto_wire_changed')
    pro=c.get('schema')=='crowd-participant-pro-material-context-v1'
    if pro:
        if _digest(Path(cfg['runtime_root'])/'pro_ack_snapshot.py')!=cfg.get('pro_snapshot_sha256'):raise ValueError('material_auto_pro_snapshot_changed')
        from pro_ack_snapshot import extract
        # The root writes this hash-addressed input before its queue/cursor save.
        expected=root.absolute()/'data-products/participant-pro-ack-inputs'/(c['group_sha256']+'.json')
        if Path(c['group_path'])!=expected:raise ValueError('material_auto_pro_input_scope')
        from material_bridge import read_bytes,parse_json
        blob=read_bytes(expected,8*1024*1024)
        if sha(blob)!=c['group_sha256']:raise ValueError('material_auto_pro_input_changed')
        group=parse_json(blob)
        if canonical(group)!=blob:raise ValueError('material_auto_pro_input_changed')
        snapshot=extract(group)
        if snapshot['scope']!={k:c[k]for k in ['task_id','subject','installation_id','dispatch_id']}or snapshot['group_cursor']!=c['group_cursor']:raise ValueError('material_auto_pro_input_scope')
        fresh=len(snapshot['receipts'])
    else:
        scope={k:c[k]for k in ['task_id','child_id','cloud_run_id','lease_epoch','platform']}
        rows=read_scope_rows(root/'cloud-outbox/outbox.sqlite3',scope,c['local_run_id'])
        snapshot=extract_rows(rows,scope=scope,local_run_id=c['local_run_id'],outcome=c['outcome'],api_attempts=c['api_attempts'],
            runtime_root=cfg['runtime_root'],wire_sha256=cfg['runtime_cloud_sha256'],bridge_path=cfg['bridge_path'],bridge_sha256=cfg['bridge_sha256'])
        fresh=len(snapshot['captures'])-snapshot['delivery_selection']['historical_material_rows']
        if fresh<=0:
            write(path,{**state,'state':'no_new_ack','fresh_acknowledged':0,'deferred_captures':snapshot['delivery_selection']['acknowledged_other_kinds_deferred']});return
    spec=importlib.util.spec_from_file_location('pinned_material_bridge',cfg['bridge_path'])
    bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
    sourcepins=sha(bridge.read_bytes(cfg['toolbox_pins'],1024*1024))
    # Same ACKs and pins give the same time basis and deterministic job ID.
    from datetime import datetime
    if pro:
        asof=max((x['created_at']for x in snapshot['receipts']),key=lambda x:datetime.fromisoformat(x.replace('Z','+00:00')))
        key={'scope':snapshot['scope'],'snapshot_sha256':sha(canonical(snapshot)),'ack_set':[{'request':x['request'],'proof_id':x['proof_id'],'record_hash':x['receipt']['record_hash'],'receipt_sha256':sha(canonical(x['receipt']))}for x in snapshot['receipts']],
             'as_of':asof,'toolbox_source_pins_sha256':sourcepins,'pack_sha256':cfg['pack_sha256'],'bridge_sha256':cfg['bridge_sha256'],'runtime_cloud_sha256':cfg['runtime_cloud_sha256'],'pro_snapshot_sha256':cfg['pro_snapshot_sha256']}
    else:
        asof=max((x['receipt']['received_at']for x in snapshot['captures']),key=lambda x:datetime.fromisoformat(x.replace('Z','+00:00')))
        key={'scope':{k:c[k]for k in ['task_id','child_id','platform']},
             'ack_set':[{'id':x['capture_id'],'hash':x['envelope_hash'],'receipt_sha256':sha(x['receipt_canonical'].encode())}for x in snapshot['captures']],
             'as_of':asof,'toolbox_source_pins_sha256':sourcepins,'pack_sha256':cfg['pack_sha256'],
             'bridge_sha256':cfg['bridge_sha256'],'runtime_cloud_sha256':cfg['runtime_cloud_sha256']}
    job_id=sha(canonical(key));project=root/'data-products/material-auto'/job_id
    if any(x.is_symlink()for x in (project,*project.parents)):raise ValueError('material_auto_path_invalid')
    project.mkdir(mode=0o700,exist_ok=True)
    request_path=project/'request.json';snap_path=project/'capture-snapshot.json';output=project/'publication'
    snapraw=canonical(snapshot)
    request={'snapshot_path':str(snap_path),'snapshot_sha256':sha(snapraw),'toolbox_root':cfg['toolbox_root'],'toolbox_pins':cfg['toolbox_pins'],
             'pack_path':cfg['pack_path'],'pack_sha256':cfg['pack_sha256'],'output':str(output),'as_of':asof,'runtime_root':cfg['runtime_root'],'runtime_cloud_sha256':cfg['runtime_cloud_sha256']}
    if pro:request['pro_snapshot_sha256']=cfg['pro_snapshot_sha256']
    if request_path.exists():
        prior=private_json(request_path)
        # Same deterministic job never gets its original input overwritten.
        if prior!=request or bridge.read_bytes(snap_path,8*1024*1024)!=snapraw:raise ValueError('material_auto_job_changed')
    else:
        fd=os.open(snap_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb')as f:f.write(snapraw);f.flush();os.fsync(f.fileno())
        write(request_path,request)
    write(path,{**state,'state':'processing','job_id':job_id,'fresh_acknowledged':fresh})
    # Root-owned reviewed bridge drives existing Jobs/snapshot-file only.
    cmd=[cfg['python'],'-B',cfg['bridge_path'],'--request',str(request_path),'--action','build-jobs','--job-id',job_id]
    with open(project/'jobs.log','ab')as log:
        result=subprocess.run(cmd,stdout=log,stderr=log,timeout=150,check=False)
    if result.returncode:raise ValueError('material_auto_jobs_failed')
    # Gate all publication bytes through the existing Consumer read CLI.
    read_cmd=[cfg['python'],'-B',cfg['bridge_path'],'--request',str(request_path),'--action','read','--format','json']
    checked=subprocess.run(read_cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15,check=False)
    if checked.returncode or len(checked.stdout)>16*1024*1024:raise ValueError('material_auto_read_failed')
    delivered=json.loads(checked.stdout)
    if len(delivered.get('items',[]))!=(len(snapshot['receipts'])if pro else len(snapshot['captures'])):raise ValueError('material_auto_read_failed')
    pointer={'python':cfg['python'],'script':cfg['bridge_path'],'script_sha256':cfg['bridge_sha256'],
             'request':str(request_path),'request_sha256':sha(canonical(request))}
    # Only materials pointer changes, after ready; domain-runtime stays intact.
    if not pro:write(root/'data-products/material-runtime.json',pointer)
    write(path,{**state,'state':'ready','job_id':job_id,'items':len(delivered['items']),'coverage':snapshot['coverage'],
                'fresh_acknowledged':fresh,'snapshot_sha256':sha(snapraw),'source_requests':0,'model_calls':0,**({'source_scope':snapshot['scope'],'publication_pointer':pointer}if pro else {})})
if __name__=='__main__':
    try:main()
    except Exception:
        sys.stderr.write('material_auto_processing_failed\n');raise SystemExit(74)
