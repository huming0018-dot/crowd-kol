"""Owner-configured project publications; existing Consumer remains the read gate."""
from pathlib import Path
import hashlib,html,json,os,re,stat
from material_bridge import read_bytes,read_json
from workbench_material_call import command

PROJECT=re.compile(r'[a-z0-9][a-z0-9-]{0,63}')


def entries(root):
    path=Path(root)/'data-products/project-publications.json'
    if path.is_symlink()or any(p.is_symlink()for p in path.parents):raise ValueError('project_publications_invalid')
    try:meta=path.stat()
    except FileNotFoundError:return []
    if not stat.S_ISREG(meta.st_mode)or meta.st_uid!=os.getuid()or meta.st_mode&0o077 or meta.st_nlink!=1:
        raise ValueError('project_publications_invalid')
    doc=read_json(path,65536)
    if type(doc)is not dict or set(doc)!={'schema','projects'}or doc['schema']!='crowd-project-publications-v1' or type(doc['projects'])is not list or len(doc['projects'])>32:
        raise ValueError('project_publications_invalid')
    seen=set()
    for item in doc['projects']:
        if type(item)is not dict or set(item)!={'project_id','name','config'}:
            raise ValueError('project_publications_invalid')
        pid=item['project_id'];name=item['name'];config=item['config']
        if type(pid)is not str or PROJECT.fullmatch(pid)is None or pid in seen or type(name)is not str or not 1<=len(name)<=200:
            raise ValueError('project_publications_invalid')
        seen.add(pid)
        command(config,'read','json')
        expected=hashlib.sha256(read_bytes(Path(__file__).with_name('publication_reader.py'),1024*1024)).hexdigest()
        if config['script_sha256']!=expected:raise ValueError('project_publications_invalid')
        request=read_json(config['request'],65536)
        if request.get('project_id')!=pid:raise ValueError('project_publication_scope_changed')
    return doc['projects']


def reader(root,project_id):
    if type(project_id)is not str or PROJECT.fullmatch(project_id)is None:raise ValueError('project_publication_unavailable')
    selected=[item for item in entries(root)if item['project_id']==project_id]
    if len(selected)!=1:raise ValueError('project_publication_unavailable')
    return selected[0]['config']


def index_html(root):
    rows=entries(root)
    parts=['<!doctype html><meta charset="utf-8"><title>项目交付</title><h1>项目交付</h1>',
        '<p>选择项目查看已保存的结果。打开时核对快照、规则版本和原始证据；不会启动采集。</p>',
        '<p><a href="/">工作台</a> · <a href="/materials/participants">参与者素材</a> · <a href="/data-product">领域发现</a></p>']
    if not rows:parts.append('<p>暂无已登记项目；原素材和任务保留。</p>')
    for row in rows:
        url='/data-products/projects/'+row['project_id']
        parts.append('<article><h2>'+html.escape(row['name'])+'</h2><p><a href="'+url+'">查看与核验</a>')
        for label,path in [('JSON','report.json'),('JSONL','items.jsonl'),('CSV','items.csv')]:
            parts.append(' · <a href="'+url+'/'+path+'">'+label+'</a>')
        parts.append('</p></article>')
    return ''.join(parts).encode()
