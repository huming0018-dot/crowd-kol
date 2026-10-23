"""Offline ACK selection only; no scheduler, capture, HTTP, or state mutation."""
from pathlib import Path
import importlib.util,hashlib,sqlite3,stat,sys,uuid
MAX_ROWS=2000
MAX_SNAPSHOT_BYTES=8*1024*1024
class SnapshotError(ValueError):pass
def uid(x):
    try:
        if type(x)is not str or str(uuid.UUID(x))!=x:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise SnapshotError('ack_scope_invalid')from None
    return x
def _bridge(path,expected):
    p=Path(path)
    if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise SnapshotError('ack_bridge_changed')
    spec=importlib.util.spec_from_file_location('approved_material_bridge',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def extract_rows(rows,*,scope,local_run_id,outcome,api_attempts,runtime_root,wire_sha256,bridge_path,bridge_sha256):
    """Caller supplies verified post-finish context, never untrusted browser input.

    rows contains task/child rows plus every row claiming this local origin;
    extra scope on the local origin is rejected, never silently joined.
    """
    if type(scope)is not dict or set(scope)!={'task_id','child_id','cloud_run_id','lease_epoch','platform'}:raise SnapshotError('ack_scope_invalid')
    for k in ('task_id','child_id','cloud_run_id'):uid(scope[k])
    uid(local_run_id)
    if type(scope['lease_epoch'])is not int or not 1<=scope['lease_epoch']<=2147483647 or type(scope['platform'])is not str:raise SnapshotError('ack_scope_invalid')
    if outcome not in ('completed','failed','stopped') or type(api_attempts)is not int or api_attempts<0:raise SnapshotError('ack_source_outcome_unknown')
    if type(rows)is not list or not 1<=len(rows)<=MAX_ROWS:raise SnapshotError('ack_count_invalid')
    if any(type(r)not in (list,tuple) or len(r)!=7 for r in rows):raise SnapshotError('ack_row_invalid')
    if sum(len(r[2].encode())+len((r[5]or'').encode()) for r in rows if type(r[2])is str and (r[5]is None or type(r[5])is str))>MAX_SNAPSHOT_BYTES:raise SnapshotError('ack_size_invalid')
    bridge=_bridge(bridge_path,bridge_sha256)
    runtime=Path(runtime_root)
    if hashlib.sha256((runtime/'cloud_sync.py').read_bytes()).hexdigest()!=wire_sha256:raise SnapshotError('ack_wire_changed')
    sys.path.insert(0,str(runtime))
    import cloud_sync
    if Path(cloud_sync.__file__).resolve()!=(runtime/'cloud_sync.py').resolve():raise SnapshotError('ack_wire_changed')
    from cloud_sync import SCHEMA,canonical,_hash
    captures=[];seen=set();local_scopes=set();excluded=[];pending=0;history=0
    for row in rows:
        if len(row)!=7:raise SnapshotError('ack_row_invalid')
        cid,rid,raw,digest,state,receipt,error=row
        if type(raw)is not str or len(raw.encode())>3_000_000:raise SnapshotError('ack_size_invalid')
        try:e=bridge.parse_json(raw.encode())
        except Exception:raise SnapshotError('ack_original_invalid')from None
        if type(e)is not dict or e.get('schema')!=SCHEMA or canonical(e)!=raw or _hash(SCHEMA,e)!=digest or e.get('run_id')!=rid or e.get('capture_id')!=cid:raise SnapshotError('ack_original_invalid')
        rec=e.get('record');origin=rec.get('origin') if type(rec)is dict else None
        if type(origin)is not dict:raise SnapshotError('ack_local_origin_unknown')
        origin_id=uid(origin.get('run_id'))
        for k in ('task_id','child_id','run_id','capture_id'):uid(e.get(k))
        if type(e.get('lease_epoch'))is not int or e['lease_epoch']<1:raise SnapshotError('ack_scope_invalid')
        if e['lease_epoch']>scope['lease_epoch']:raise SnapshotError('ack_future_scope_unfinished')
        wire_scope=(e['task_id'],e['child_id'],e['run_id'],e['lease_epoch'],e.get('platform'))
        if origin_id==local_run_id:local_scopes.add(wire_scope)
        same_scope=(e['task_id']==scope['task_id'] and e['child_id']==scope['child_id'] and e.get('platform')==scope['platform'])
        if not same_scope:raise SnapshotError('ack_multiple_scopes')
        if state!='acknowledged':
            pending+=1;continue
        if error is not None or type(receipt)is not str or len(receipt.encode())>100000:raise SnapshotError('ack_receipt_missing')
        try:r=bridge.parse_json(receipt.encode())
        except Exception:raise SnapshotError('ack_receipt_invalid')from None
        if type(r)is not dict:raise SnapshotError('ack_receipt_invalid')
        for k in ('task_id','child_id','run_id','lease_epoch','capture_id'):
            if type(r.get(k))is not type(e.get(k)) or r.get(k)!=e.get(k):raise SnapshotError('ack_receipt_binding')
        if r.get('status')!='received' or r.get('envelope_hash')!=digest or r.get('reward_eligible')is not False or rec.get('reward_eligible')is not False:raise SnapshotError('ack_receipt_invalid')
        if cid!=str(uuid.uuid5(uuid.UUID(rid),canonical(rec))) or cid in seen:raise SnapshotError('ack_identity_invalid')
        seen.add(cid)
        if rec.get('platform')!=scope['platform']:raise SnapshotError('ack_multiple_scopes')
        if rec.get('kind')not in ('content','comment'):
            excluded.append({'capture_id':cid,'kind':rec.get('kind'),'envelope_hash':digest});continue
        if rid!=scope['cloud_run_id']:history+=1
        captures.append({'capture_id':cid,'envelope_hash':digest,'envelope_canonical':raw,'receipt_canonical':receipt,'envelope':e,'receipt':r})
    expected=(scope['task_id'],scope['child_id'],scope['cloud_run_id'],scope['lease_epoch'],scope['platform'])
    if local_scopes!={expected}:raise SnapshotError('ack_local_cloud_mapping_unknown')
    if not captures:raise SnapshotError('ack_material_empty')
    snapshot={'schema':'ctfs-confirmed-capture-snapshot-v1','source_kind':'durable_public_capture_snapshot_not_original_http',
      'task_id':scope['task_id'],'child_id':scope['child_id'],'latest_local_run_id':local_run_id,
      'captures':sorted(captures,key=lambda x:x['capture_id']),'coverage':'partial' if outcome!='completed' or pending or excluded else 'unknown',
      'source_status':{'state':outcome,'api_attempts':api_attempts},'reward_eligible':False,
      'delivery_selection':{'acknowledged_material_rows':len(captures),'historical_material_rows':history,'nonacknowledged_rows_excluded':pending,'acknowledged_other_kinds_deferred':excluded}}
    # Existing approved bridge is the final record/canonical/hash/text contract.
    try:bridge.snapshot_bundle(snapshot,runtime_root)
    except (ValueError,TypeError,KeyError,AssertionError):raise SnapshotError('ack_material_contract_rejected')from None
    return snapshot

def read_scope_rows(outbox,scope,local_run_id):
    p=Path(outbox).absolute()
    if any(x.is_symlink()for x in (p,*p.parents))or not stat.S_ISREG(p.stat().st_mode):raise SnapshotError('ack_outbox_invalid')
    with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=0.02)as db:
        db.execute('PRAGMA query_only=ON')
        # OR detects one local origin appearing under multiple cloud scopes.
        db.execute('BEGIN')
        where = """(json_extract(envelope,'$.task_id')=? AND json_extract(envelope,'$.child_id')=?)
               OR json_extract(envelope,'$.record.origin.run_id')=?"""
        args=(scope['task_id'],scope['child_id'],local_run_id)
        count,total,big=db.execute("""SELECT count(*),coalesce(sum(length(CAST(envelope AS BLOB))+coalesce(length(CAST(receipt AS BLOB)),0)),0),
            coalesce(max(length(CAST(envelope AS BLOB))>3000000 OR length(CAST(receipt AS BLOB))>100000),0)
            FROM captures WHERE """+where,args).fetchone()
        if count>MAX_ROWS or total>MAX_SNAPSHOT_BYTES or big:raise SnapshotError('ack_size_invalid')
        rows=db.execute("""SELECT id,run_id,envelope,digest,state,receipt,error FROM captures WHERE """+where+
            " ORDER BY id LIMIT ?",(*args,MAX_ROWS+1)).fetchall()
    if len(rows)>MAX_ROWS:raise SnapshotError('ack_count_invalid')
    return rows
