"""Existing Consumer publications, indexed by participant ACK scope."""
from pathlib import Path
import html,re,json,hashlib
from automatic_materials import private_json,validate_context,material_context_key

KEY=re.compile(r'pro-[a-f0-9]{64}')

def publication(root,key,job_id=None):
    if type(key) is not str or KEY.fullmatch(key) is None:raise ValueError('material_delivery_unavailable')
    state=private_json(Path(root)/'data-products/material-auto'/(key+'.json'))
    context=validate_context(state['context'])
    if context['schema']!='crowd-participant-pro-material-context-v1' or material_context_key(context)!=key:
        raise ValueError('material_delivery_unavailable')
    if job_id is not None:
        if type(job_id)is not str or re.fullmatch('[a-f0-9]{64}',job_id)is None:raise ValueError('material_delivery_unavailable')
        try:value=private_json(Path(root)/'data-products/material-auto'/job_id/'ready.json')
        except OSError:raise ValueError('material_delivery_unavailable')from None
        ctx=validate_context(value['context']);original=ctx['original']if ctx.get('schema')=='crowd-material-recompute-v1'else ctx
        if original!=context or value.get('job_id')!=job_id or value.get('state')!='ready':raise ValueError('material_delivery_unavailable')
        state=value
    if state.get('state') not in ('waiting','processing','ready','blocked'):raise ValueError('material_delivery_unavailable')
    return state

def summaries(root):
    directory=Path(root)/'data-products/material-auto'
    if any(p.is_symlink() for p in (directory,*directory.parents)):raise ValueError('material_delivery_unavailable')
    latest={}
    paths=list(directory.glob('pro-*.json'))
    if len(paths)>2000:raise ValueError('material_publication_index_limit')
    for path in paths:
        if KEY.fullmatch(path.stem) is None:continue
        state=publication(root,path.stem);c=state['context']
        scope=tuple(c[k] for k in ('task_id','subject','installation_id','dispatch_id'))
        from pro_ack_snapshot import timestamp,validate_group
        from material_bridge import read_bytes
        expected=Path(root).absolute()/'data-products/participant-pro-ack-inputs'/(c['group_sha256']+'.json')
        if Path(c['group_path'])!=expected:raise ValueError('material_delivery_unavailable')
        raw=read_bytes(expected,8*1024*1024)
        if hashlib.sha256(raw).hexdigest()!=c['group_sha256']:raise ValueError('material_delivery_unavailable')
        group=json.loads(raw);verified=validate_group(group)
        if group['group_cursor']!=c['group_cursor']:raise ValueError('material_delivery_unavailable')
        # A late commit can grow the ACK set without changing its max timestamp.
        order=(len(verified['receipts']),timestamp(c['group_cursor']['created_at']),c['group_cursor']['request'],expected.stat().st_mtime_ns)
        if scope not in latest or order>latest[scope][0]:latest[scope]=(order,path.stem,state)
    values=[]
    for order,key,state in sorted(latest.values(),reverse=True):
        ready=state.get('state')=='ready'
        values.append({'task_id':state['context']['task_id'],'state':state.get('state'),
            'items':state.get('items') if ready else None,'coverage':state.get('coverage') if ready else None,
            'url':'/materials/pro/'+key if ready else None})
    return values

def index_html(root):
    rows=summaries(root)
    parts=['<!doctype html><meta charset="utf-8"><title>参与者素材</title><h1>参与者素材</h1>',
           '<p>云端已确认的数据自动进入清洗、可追溯性评分和审计。该评分不代表内容质量、口味或参与者奖励。</p>',
           '<p><a href="/">返回工作台</a> · <a href="/materials">原已审素材</a> · <a href="/data-product">领域发现</a></p>']
    if not rows:parts.append('<p>暂无参与者素材处理结果；原数据与回执保留。</p>')
    names={'waiting':'等待处理','processing':'处理中','blocked':'处理异常，原数据保留','ready':'已处理'}
    for row in rows:
        parts.append('<article><h2>任务 '+str(row['task_id'])+'</h2><p>'+names.get(row['state'],'状态未确认')+'</p>')
        if row['url']:
            url=html.escape(row['url'],quote=True)
            parts.append('<p>'+str(row['items'])+' 条 · 来源覆盖：'+html.escape(str(row['coverage']))+'</p><p><a href="'+url+'">查看素材</a>')
            for label,suffix in [('JSON','report.json'),('JSONL','materials.jsonl'),('CSV','materials.csv')]:parts.append(' · <a href="'+url+'/'+suffix+'">'+label+'</a>')
            parts.append('</p>')
        parts.append('</article>')
    return ''.join(parts).encode()
