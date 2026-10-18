"""Compare one already-saved Pro SQLite run to its normalized/export projection.

No fetching, account acquisition or cloud submission. Original APIs are not called.
References are checked as references; byte downloads are never inferred.
"""
import hashlib
import os
from pathlib import Path
import mc_runner
import pro_executor
from participant_pro import require

def compare_saved_run(root,run_id,output):
    run=mc_runner.run_dir(root,run_id);manifest=mc_runner.read(run/'manifest.json')
    require(manifest.get('source',{}).get('commit')==pro_executor.PINNED_COMMIT,'participant_upstream_changed')
    require(manifest['request']['platform']=='xhs','participant_compare_platform')
    # Original established native parser/import, not a second source request.
    records,media,evidence=pro_executor.import_records(run,manifest)
    raw=pro_executor.observations(run,manifest)
    rows={(kind,identity):row for kind,identity,row in raw}
    checks=[]
    for r in records:
        key=('topic',r['content_id']) if r['kind']=='content' else ('comment',r['comment_id'])
        row=rows[key];raw_text=row.get('desc') if r['kind']=='content' else row.get('content')
        projected=r.get('body') if r['kind']=='content' else r.get('text')
        check={'kind':r['kind'],'record_hash':r['record_hash'],'native_row_sha256':hashlib.sha256(mc_runner.canonical(row).encode()).hexdigest(),'text_length':len(raw_text or ''),'text_exact':isinstance(raw_text,str) and projected==raw_text,'text_truncated':r.get('text_truncated'),'title_exact':r.get('title')==row.get('title') if r['kind']=='content' else None,'parent_exact':r.get('parent_comment_id')==row.get('parent_comment_id') if r['kind']=='comment' else None,'references':len(r.get('media',[]))}
        require(check['native_row_sha256']==r['origin']['observation_sha256'],'participant_native_row_changed')
        checks.append(check)
    # Reuse the current exporter in an isolated, create-only audit directory.
    output=Path(output);output.mkdir(mode=0o700,parents=False,exist_ok=False)
    from results_store import ResultsStore
    store=ResultsStore(output);store.ingest({'run_id':run_id,'records':records,'media':media,'source':{'executor':'mediacrawler_pro'}})
    exports={}
    for fmt in ('json','jsonl','csv','xlsx'):
        exported=store.export(fmt);data=exported['data'];export_manifest=exported['manifest']
        target=output/('results.'+fmt)
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        exports[fmt]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'row_count':export_manifest['row_count']}
    report={'schema':'crowd-pro-same-run-compare-v1','run_id':run_id,'source_repeated':False,'checks':checks,'all_text_exact':all(c['text_exact'] and c['text_truncated'] is False for c in checks),'comments':'not_requested' if manifest['request'].get('comments') is False else evidence.get('pagination',{}),'media':'references_only_no_byte_equivalence','exports':exports,'coverage':'unverified' if not manifest['request'].get('comments') else evidence.get('pagination',{}).get('coverage','unknown')}
    mc_runner.write(output/'COMPARISON.json',report)
    return report

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    for field in ('root','run-id','output'):ap.add_argument('--'+field,required=True)
    args=ap.parse_args();report=compare_saved_run(args.root,args.run_id,args.output)
    print(mc_runner.canonical({k:report[k] for k in ('schema','run_id','source_repeated','all_text_exact','coverage')}))
