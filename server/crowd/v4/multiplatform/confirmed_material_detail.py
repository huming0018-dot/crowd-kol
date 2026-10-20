"""Read-only source detail for the current verified generic publication.

No new publication, source, registration or import. The caller supplies a report
from Application.material_delivery('json'), never a browser-supplied report/path.
Attachment lookup only calls the existing resolver for an exact registered match.
"""
import hashlib
import re
import uuid
from pathlib import Path
from material_bridge import snapshot_bundle
from saved_media_attachments import SCHEMA,read_json_object,read,sha,WB_LIMIT

HEX=re.compile(r'[a-f0-9]{64}')
VIRTUAL=re.compile(r'attachments/[a-f0-9]{64}/[a-f0-9]{64}\.(jpg|png|webp)')


def _registered(root):
    directory=Path(root).absolute()/'media-attachments'
    if not directory.exists():return []
    if directory.is_symlink()or directory.resolve()!=directory:raise ValueError('material_source_attachment_unsafe')
    files=list(directory.glob('*/*/attachment.json'))
    if len(files)>2000:raise ValueError('material_source_attachment_limit')
    return [(p,read_json_object(p,1024*1024))for p in files]


def _media(record,registered,resolve):
    refs=record.get('media',[])
    if type(refs)is not list or len(refs)>100:raise ValueError('material_source_media_invalid')
    result=[]
    for ref in refs:
        if type(ref)is not dict or type(ref.get('media_id'))is not str or not HEX.fullmatch(ref['media_id']):raise ValueError('material_source_media_invalid')
        key=(record.get('platform'),record.get('content_id'),record.get('comment_id')or None,record.get('record_hash'),ref['media_id'],sha(ref.get('url')))
        matches=[(p,s)for p,s in registered if (s.get('platform'),s.get('content_id'),s.get('comment_id')or None,s.get('source_record_hash'),s.get('media_id'),s.get('source_url_sha256'))==key]
        if len(matches)>1:raise ValueError('material_source_attachment_ambiguous')
        item={'media_id':ref['media_id'],'kind':ref.get('kind'),'state':'reference_only'}
        if matches:
            p,s=matches[0];run=s.get('run_id');virtual=s.get('path')
            if s.get('schema')!=SCHEMA or type(run)is not str or str(uuid.UUID(run))!=run or p.parent.parent.name!=run or type(virtual)is not str or not VIRTUAL.fullmatch(virtual)or p.parent.name!=virtual.split('/')[1]or s.get('media_kind')!='image':raise ValueError('material_source_attachment_invalid')
            # This is deliberately the registered attachments branch of media_file;
            # it can never fall back to run('import') or create a registration.
            asset=resolve({'run_id':run,'path':virtual})
            blob=read(asset,WB_LIMIT)
            if type(s.get('bytes'))is not int or len(blob)!=s['bytes']or hashlib.sha256(blob).hexdigest()!=s.get('asset_sha256'):raise ValueError('material_source_attachment_changed')
            item.update(state='registered_verified',run_id=run,path=virtual,bytes=len(blob),sha256=s['asset_sha256'],media_origin={'run_id':run,'source_record_hash':s['source_record_hash'],'source_observation_sha256':s['source_observation_sha256']})
        result.append(item)
    return result


def project(report,root,resolve):
    """Project original capture fields, not flattened Consumer draft titles."""
    if type(report)is not dict or type(report.get('items'))is not list or not 1<=len(report['items'])<=2000:raise ValueError('material_source_report_invalid')
    captures=[];byid={}
    for row in report['items']:
        if type(row)is not dict or type(row.get('metadata'))is not dict:raise ValueError('material_source_capture_invalid')
        c=row['metadata'].get('capture')
        if type(c)is not dict or row.get('identity',{}).get('source_record_id')!=c.get('capture_id'):raise ValueError('material_source_capture_invalid')
        captures.append(c)
    first=captures[0].get('envelope',{})
    task,child=first.get('task_id'),first.get('child_id')
    if report.get('project_id')!='confirmed-'+str(task):raise ValueError('material_source_scope_invalid')
    # Reuse the existing exact canonical envelope/receipt/hash/UUID/scope checks.
    snapshot_bundle({'schema':'ctfs-confirmed-capture-snapshot-v1','task_id':task,'child_id':child,'captures':captures},Path(__file__).parent)
    registered=_registered(root);contents=[];comments=[];contentkeys=set();commentkeys={}
    for c in captures:
        e=c['envelope'];r=e['record'];kind=r['kind'];cid=c['capture_id']
        if cid in byid:raise ValueError('material_source_duplicate')
        if r.get('record_hash')!=sha({k:v for k,v in r.items()if k!='record_hash'}):raise ValueError('material_source_record_changed')
        item={'capture_id':cid,'envelope_hash':c['envelope_hash'],'record_hash':r.get('record_hash'),'platform':r['platform'],'content_id':r.get('content_id'),'capture_origin':r.get('origin',{}),'capture_run_id':e['run_id'],'coverage':r.get('coverage','unknown'),'text':r['text']if kind=='comment'else r['body'],'media':_media(r,registered,resolve)}
        key=(r['platform'],r.get('content_id'))
        if not all(type(x)is str and x for x in key)or type(item['record_hash'])is not str or not HEX.fullmatch(item['record_hash']):raise ValueError('material_source_identity_invalid')
        if kind=='content':
            if key in contentkeys:raise ValueError('material_source_content_ambiguous')
            if r.get('title')is not None and type(r['title'])is not str:raise ValueError('material_source_title_invalid')
            contentkeys.add(key);item['title']=r.get('title');contents.append(item)
        else:
            comment=r.get('comment_id');parent=r.get('parent_comment_id');status=r.get('parent_status')
            if type(comment)is not str or not comment or (*key,comment)in commentkeys:raise ValueError('material_source_comment_invalid')
            item.update(comment_id=comment,parent_comment_id=parent,parent_status=status,parent_capture_id=None,relationship='unassigned');comments.append(item);commentkeys[(*key,comment)]=item
        byid[cid]=item
    roots=replies=unassigned=0
    for item in comments:
        key=(item['platform'],item['content_id']);parent=item['parent_comment_id']
        if key not in contentkeys:raise ValueError('material_source_content_missing')
        if item['parent_status']=='reported_root':
            if parent not in (item['comment_id'],None,'','0'):raise ValueError('material_source_root_invalid')
            item['relationship']='root';roots+=1
        elif item['parent_status']=='reported':
            original=commentkeys.get((*key,parent))
            if original is None or original is item:raise ValueError('material_source_parent_outside_scope')
            item['relationship']='reply';item['parent_capture_id']=original['capture_id'];replies+=1
        else:unassigned+=1
    for item in comments:
        seen=set();current=item
        while current['parent_capture_id']is not None:
            if current['capture_id']in seen:raise ValueError('material_source_parent_cycle')
            seen.add(current['capture_id']);current=byid[current['parent_capture_id']]
        if item['relationship']=='reply'and current['relationship']!='root':raise ValueError('material_source_parent_unverified')
    return {'schema':'crowd-confirmed-material-source-detail-v1','project_id':report['project_id'],'task_id':task,'child_id':child,'coverage':'partial_or_unknown','source_calls':0,'publication_changed':False,'contents':contents,'comments':comments,'counts':{'contents':len(contents),'roots':roots,'replies':replies,'unassigned':unassigned}}
