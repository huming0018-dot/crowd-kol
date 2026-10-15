"""Native MC source observations: local durable safe descriptors, never source content.
Storage readback is distinct from native checkpoint/coverage and from cloud ACK.
"""
import contextlib,contextvars,hashlib,inspect,json,os,re,sqlite3,stat,threading,uuid
from pathlib import Path
STAGES=frozenset(('request_started','response_received','request_failed','page_received','page_saved','page_partially_saved','content_saved','store_failed','monitor_failed'))
SCOPES=frozenset(('request','content','root','reply'))
LIMIT=4000

def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'))
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def identity(value):
    if isinstance(value,bool) or not isinstance(value,(str,int)):return None
    value=str(value)
    return digest(value) if re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',value) else None

class NativeSteps:
    def __init__(self,run,run_id,platform):
        self.run=Path(run).resolve();self.run_id=str(uuid.UUID(run_id));self.platform=platform;self.path=self.run/'mc-source-steps.sqlite3';self.error=None;self.originals=[];self.pending=[];self.saved={};self.generation=0;self.last_attempt=0;self.store_failed=False;self.lock=threading.RLock();self.callback_context=contextvars.ContextVar('native_comment_callback',default=None)
        try:
            if self.path.is_symlink():raise ValueError('unsafe_monitor_store')
            with contextlib.closing(self.connect()) as db, db:
                db.executescript('CREATE TABLE IF NOT EXISTS binding(run TEXT NOT NULL,platform TEXT NOT NULL);CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY,event TEXT NOT NULL);')
                rows=db.execute('SELECT run,platform FROM binding').fetchall()
                if not rows:db.execute('INSERT INTO binding VALUES(?,?)',(self.run_id,platform))
                elif rows!=[(self.run_id,platform)]:raise ValueError('monitor_binding')
            self.path.chmod(0o600)
        except (OSError,ValueError,sqlite3.Error):self.error='native_steps_store_failed'
    def connect(self):
        if self.path.is_symlink():raise ValueError('unsafe_monitor_store')
        return sqlite3.connect(self.path,timeout=.02)
    def emit(self,stage,scope='request',api_attempts=None,http_status=0,page_sha256=None,saved_rows=0):
        if stage not in STAGES or scope not in SCOPES:return
        if stage=='page_partially_saved' and (scope not in ('root','reply') or type(saved_rows) is not int or saved_rows<1):return
        if api_attempts is None:api_attempts=self.last_attempt
        if any(type(v) is not int or not 0<=v<=10**9 for v in (api_attempts,saved_rows)) or type(http_status) is not int or not 0<=http_status<=599:return
        event={'source_stage':stage,'scope':scope,'api_attempts':api_attempts,'http_status':http_status,'saved_rows':saved_rows,'checkpoint_committed':False}
        if page_sha256 is not None:
            if not isinstance(page_sha256,str) or not re.fullmatch('[a-f0-9]{64}',page_sha256):return
            event['page_sha256']=page_sha256
        try:
            with self.lock,contextlib.closing(self.connect()) as db, db:
                if db.execute('SELECT count(*) FROM events').fetchone()[0]>=LIMIT:raise ValueError('monitor_limit')
                db.execute('INSERT INTO events(event) VALUES(?)',(canonical(event),))
        except (ValueError,OSError,sqlite3.Error):self.error='native_steps_store_failed'
    def transport(self,stage,attempts,response=None):
        if type(attempts) is int:self.last_attempt=max(self.last_attempt,attempts)
        status=getattr(response,'status_code',0)
        self.emit(stage,api_attempts=attempts,http_status=status if type(status) is int else 0)
    def page(self,scope,result,key,id_key,bound):
        try:
            values=result.get(key) if isinstance(result,dict) else None
            if self.platform=='bili' and scope=='root' and isinstance(values,list):
                from media_platform.bilibili.client import _extract_pinned_comments
                pinned=_extract_pinned_comments((result.get('top'),result.get('top_replies')))
                merged=[];seen=set()
                for row in [*pinned,*values]:
                    value=identity(row.get(id_key)) if isinstance(row,dict) else None
                    if value not in seen:merged.append(row);seen.add(value)
                values=merged
            if not isinstance(values,list) or len(values)>1000:return
            ids=[identity(row.get(id_key)) for row in values if isinstance(row,dict)]
            if len(ids)!=len(values) or None in ids or len(ids)!=len(set(ids)):return
            safe={k:identity(v) for k,v in bound.items() if k in ('note_id','video_id','mid_id','aweme_id','photo_id','content_id','root_comment_id','comment_id','level_one_comment_id','cursor','max_id','max_id_type','offset','next','pn','ps','pcursor')}
            page={'ids':ids,'scope':scope,'digest':digest([self.platform,scope,safe,ids]),'done':False,'generation':self.generation}
            self.pending.append(page)
            context=self.callback_context.get()
            if context is not None and context['scope']==scope:context['page']=page
            self.emit('page_received',scope,page_sha256=page['digest'])
            self.check_pages()
        except Exception:self.error='native_steps_page_failed'
    def select_callback_page(self,page,values,id_key):
        if page is None or not isinstance(values,list) or len(values)>1000:return
        ids=[identity(row.get(id_key)) for row in values if isinstance(row,dict)]
        if len(ids)!=len(values) or None in ids or len(ids)!=len(set(ids)) or not set(ids)<=set(page['ids']):
            self.error='native_steps_callback_mismatch';return
        page['selected_ids']=ids
        page['partial']=set(ids)!=set(page['ids'])
        self.check_pages()
    def check_pages(self):
        for page in self.pending:
            required=page.get('selected_ids',page['ids'])
            if page['done'] or not required or not all(i in self.saved and self.saved[i][2]>page['generation'] for i in required):continue
            try:
                by_path={self.saved[i][0] for i in required}
                verified={}
                for path in by_path:
                    if path.is_symlink() or not path.resolve().is_relative_to(self.run/'output') or any(x.is_symlink() for x in path.parents if x!=self.run and self.run in x.parents):raise ValueError('unsafe_output')
                    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|getattr(os,'O_NOFOLLOW',0))
                    try:
                        info=os.fstat(fd)
                        if not stat.S_ISREG(info.st_mode) or info.st_size>50_000_000:raise ValueError('unsafe_output')
                        with os.fdopen(fd,'rb',closefd=False) as f:raw=f.read(50_000_001)
                        if len(raw)>50_000_000:raise ValueError('unsafe_output')
                        rows=[json.loads(line) for line in raw.splitlines() if line.strip()] if path.suffix=='.jsonl' else json.loads(raw)
                        if not isinstance(rows,list):raise ValueError('output_shape')
                        for row in rows:
                            if isinstance(row,dict):
                                key=identity(row.get('comment_id'))
                                if key:verified[key]=digest(row)
                    finally:os.close(fd)
                if not all(verified.get(i)==self.saved[i][1] for i in required):continue
                page['done']=True;self.emit('page_partially_saved' if page.get('partial') else 'page_saved',page['scope'],page_sha256=page['digest'],saved_rows=len(required))
            except (OSError,ValueError,RecursionError):self.error='native_steps_readback_failed'
    def install(self):
        # Original seven-platform JSON writer is the common durable boundary.
        from tools.async_file_writer import AsyncFileWriter
        owner=self
        def make_store(original,file_format):
            async def store(writer,item,item_type):
                try:value=await original(writer,item,item_type)
                except Exception:
                    owner.store_failed=True
                    owner.emit('store_failed','root' if item_type=='comments' else 'content');raise
                try:
                    if item_type=='contents' and isinstance(item,dict):
                        path=Path(writer._get_file_path(file_format,item_type))
                        if path.is_symlink() or not path.resolve().is_relative_to(owner.run/'output') or not path.is_file() or path.stat().st_size>50_000_000:raise ValueError('unsafe_output')
                        fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|getattr(os,'O_NOFOLLOW',0))
                        try:
                            info=os.fstat(fd)
                            if not stat.S_ISREG(info.st_mode) or info.st_size>50_000_000:raise ValueError('unsafe_output')
                            with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(50_000_001)
                            if len(raw)>50_000_000:raise ValueError('unsafe_output')
                            rows=[json.loads(line) for line in raw.splitlines() if line.strip()] if path.suffix=='.jsonl' else json.loads(raw)
                        finally:os.close(fd)
                        if not isinstance(rows,list) or not any(digest(row)==digest(item) for row in rows if isinstance(row,dict)):raise ValueError('content_not_saved')
                        owner.emit('content_saved','content',page_sha256=digest(item),saved_rows=1)
                    if item_type=='comments' and isinstance(item,dict):
                        key=identity(item.get('comment_id'))
                        if key:
                            owner.generation+=1
                            owner.saved[key]=(Path(writer._get_file_path(file_format,item_type)),digest(item),owner.generation)
                            owner.check_pages()
                except Exception:owner.error='native_steps_readback_failed'
                return value
            return store
        for method,file_format in (('write_single_item_to_json','json'),('write_to_jsonl','jsonl')):
            original=getattr(AsyncFileWriter,method)
            setattr(AsyncFileWriter,method,make_store(original,file_format))
            self.originals.append((AsyncFileWriter,method,original))
        import importlib
        modules={'wb':('weibo','WeiboClient',[('get_note_comments','root','data','id')]),'bili':('bilibili','BilibiliClient',[('get_video_comments','root','replies','rpid'),('get_video_level_two_comments','reply','replies','rpid')]),'xhs':('xhs','XiaoHongShuClient',[('get_note_comments','root','comments','id'),('get_note_sub_comments','reply','comments','id')]),'dy':('douyin','DouYinClient',[('get_aweme_comments','root','comments','cid'),('get_sub_comments','reply','comments','cid')]),'ks':('kuaishou','KuaiShouClient',[('get_video_comments','root','rootCommentsV2','commentId'),('get_video_sub_comments','reply','subCommentsV2','commentId')]),'zhihu':('zhihu','ZhiHuClient',[('get_root_comments','root','data','id'),('get_child_comments','reply','data','id')])}
        if self.platform in modules:
            module,name,methods=modules[self.platform];cls=getattr(importlib.import_module('media_platform.'+module+'.client'),name)
            for method,scope,key,id_key in methods:
                fn=getattr(cls,method);signature=inspect.signature(fn)
                def make(fn,signature,scope,key,id_key):
                    async def request(client,*a,**kw):
                        result=await fn(client,*a,**kw)
                        try:owner.page(scope,result,key,id_key,signature.bind(client,*a,**kw).arguments)
                        except Exception:owner.error='native_steps_page_failed'
                        return result
                    return request
                setattr(cls,method,make(fn,signature,scope,key,id_key));self.originals.append((cls,method,fn))
        if self.platform=='bili':
            # Original root paginator slices max_count before callback and invokes
            # reply callbacks recursively first. Scope contexts keep those batches
            # attached to their actual returned page; selected roots are not full raw pages.
            for method,scope in (('get_video_all_comments','root'),('get_video_all_level_two_comments','reply')):
                original=getattr(cls,method);signature=inspect.signature(original)
                def wrap_paginator(original,signature,scope):
                    async def paginator(client,*args,**kwargs):
                        bound=signature.bind(client,*args,**kwargs);callback=bound.arguments.get('callback')
                        context={'scope':scope,'page':None}
                        if callback is not None:
                            async def selected(*a,**kw):
                                if owner.callback_context.get() is context and len(a)>=2:
                                    owner.select_callback_page(context['page'],a[1],'rpid')
                                result=await callback(*a,**kw)
                                if owner.callback_context.get() is context:
                                    page=context['page'];owner.check_pages()
                                    if page is not None and page.get('selected_ids') and not page['done']:
                                        owner.error='native_steps_readback_failed';owner.emit('monitor_failed',page['scope'],page_sha256=page['digest'])
                                return result
                            bound.arguments['callback']=selected
                        token=owner.callback_context.set(context)
                        try:return await original(*bound.args,**bound.kwargs)
                        finally:owner.callback_context.reset(token)
                    return paginator
                setattr(cls,method,wrap_paginator(original,signature,scope));self.originals.append((cls,method,original))
        return self
    def restore(self):
        for cls,name,original in reversed(self.originals):setattr(cls,name,original)
        self.originals=[]

def read_steps(run,run_id):
    path=Path(run)/'mc-source-steps.sqlite3'
    if not path.exists():return []
    if path.is_symlink() or not path.is_file() or path.stat().st_size>10_000_000:raise ValueError('native_steps_store_invalid')
    try:
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.02) as db:
            rows=db.execute('SELECT run FROM binding').fetchall()
            if rows!=[(str(uuid.UUID(run_id)),)]:raise ValueError('native_steps_binding_invalid')
            result=[]
            for sequence,raw in db.execute('SELECT sequence,event FROM events ORDER BY sequence LIMIT ?',(LIMIT,)):
                if len(raw)>2048:raise ValueError('native_steps_event_invalid')
                value=json.loads(raw)
                if not isinstance(value,dict) or set(value)-{'source_stage','scope','api_attempts','http_status','saved_rows','checkpoint_committed','page_sha256'}:raise ValueError('native_steps_event_invalid')
                if value.get('source_stage') not in STAGES or value.get('scope') not in SCOPES or value.get('checkpoint_committed') is not False:raise ValueError('native_steps_event_invalid')
                for key,maximum in (('api_attempts',500),('http_status',599),('saved_rows',10**9)):
                    if type(value.get(key)) is not int or not 0<=value[key]<=maximum:raise ValueError('native_steps_event_invalid')
                if 'page_sha256' in value and (not isinstance(value['page_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['page_sha256'])):raise ValueError('native_steps_event_invalid')
                if value['source_stage']=='page_partially_saved' and value['scope'] not in ('root','reply'):raise ValueError('native_steps_event_invalid')
                if value['source_stage'] in ('page_saved','page_partially_saved','content_saved') and ('page_sha256' not in value or value['saved_rows']<1):raise ValueError('native_steps_event_invalid')
                result.append({'source_sequence':sequence,**value})
            return result
    except (OSError,ValueError,TypeError,AttributeError,RecursionError,sqlite3.Error):raise ValueError('native_steps_observation_failed')
