"""Observe XHS/DY native pagination and durable operation rows without replacing loops."""
import hashlib
import inspect
import sqlite3
from pathlib import Path


class CursorStalled(BaseException):
    # Upstream catches per-note Exception; a stalled page must not issue another request.
    pass


def cursor(value, platform):
    if platform=='xhs':return value if isinstance(value,str) and len(value)<=512 else None
    return value if type(value) is int and value>=0 else None


def more(value):
    if type(value) is bool:return value
    if type(value) is int and value in (0,1):return bool(value)
    return None


class CursorPagination:
    def __init__(self, run, manifest, adapter):
        self.run,self.manifest,self.adapter=Path(run),manifest,adapter
        self.platform=manifest['request']['platform']
        self.pages=[];self.invalid=False
    def persist(self):
        doc={'schema_version':1,'operation_id':self.manifest['run_id'],'platform':self.platform,'pages':self.pages,'invalid':self.invalid}
        text=self.adapter.bridge().canonical(doc)
        if len(self.pages)>1000 or len(text.encode())>2_900_000:raise SystemExit(76)
        self.adapter.bridge().write(self.run/'pro-pagination.json',{**doc,'sha256':hashlib.sha256(text.encode()).hexdigest()})
    def record(self,scope,content,models,data,incoming,parent=None,embedded=False):
        ids=[self.adapter.bridge().opaque(c.comment_id) for c in models]
        page={'scope':scope,'content_id':str(content),'parent_id':str(parent) if parent is not None else None,'ids':ids,
              'cursor_in':cursor(incoming,self.platform) if not embedded else None,
              'cursor_out':cursor(data.get('cursor'),self.platform),'has_more':more(data.get('has_more')),
              'saved':not ids,'checkpoint_committed':False,'embedded':embedded,'pinned_gap':False,
              'reply_roots':{str(c.comment_id):self.adapter.page_number(c.sub_comment_count) for c in models} if scope=='root' else {},
              'invalid':None in ids or len(ids)!=len(set(ids))}
        page['invalid']|=page['cursor_out'] is None or page['has_more'] is None or (not embedded and page['cursor_in'] is None) or None in page['reply_roots'].values()
        self.pages.append(page);self.persist()
        if page['has_more'] and (not models or page['cursor_out']==page['cursor_in']):
            page['stalled']=True;self.persist();raise CursorStalled()
        return page
    def install(self,client,store,manager):
        p=self.platform
        root_name,reply_name,save_name=(('get_note_comments','get_note_sub_comments','batch_update_xhs_note_comments') if p=='xhs' else ('get_aweme_comments','get_sub_comments','batch_update_dy_aweme_comments'))
        root,reply,save,commit=getattr(client,root_name),getattr(client,reply_name),getattr(store,save_name),manager.update_note_comment_cursor
        async def observe(fn,scope,args,kwargs):
            bound=inspect.signature(fn).bind(*args,**kwargs);bound.apply_defaults();a=bound.arguments
            value=await fn(*args,**kwargs);models,data=value
            content=a['note_id' if p=='xhs' else 'aweme_id'];parent=a.get('root_comment_id' if p=='xhs' else 'comment_id')
            root_page=self.record(scope,content,models,data,a['cursor'],parent)
            if p=='xhs' and scope=='root' and self.manifest['request']['replies']:
                raw=data.get('comments',[])
                root_page['reply_cursor_start']={str(item.get('id')):cursor(item.get('sub_comment_cursor',''),'xhs') for item in raw if isinstance(item,dict)}
                if len(raw)!=len(models):self.invalid=True;self.persist();return value
                instance=args[0]
                for root_model,item in zip(models,raw):
                    if str(item.get('id'))!=str(root_model.comment_id):self.invalid=True;continue
                    embedded=item.get('sub_comments') or []
                    if embedded:
                        parsed=instance._extractor.extract_comments_from_dict(content,embedded,'',root_model.comment_id)
                        self.record('reply',content,parsed,{'cursor':item.get('sub_comment_cursor',''),'has_more':item.get('sub_comment_has_more',False)},None,root_model.comment_id,True)
                self.persist()
            return value
        async def roots(*a,**kw):return await observe(root,'root',a,kw)
        async def replies(*a,**kw):return await observe(reply,'reply',a,kw)
        async def saved(*args,**kwargs):
            bound=inspect.signature(save).bind(*args,**kwargs);models=bound.arguments['comments']
            result=await save(*args,**kwargs)
            ids=[str(model.comment_id) for model in models]
            candidates=[page for page in self.pages if not page['saved'] and page['ids']==ids]
            rows={entity:row for kind,entity,row in self.adapter.observations(self.run,self.manifest) if kind=='comment'}
            for page in candidates:
                content_key='note_id' if p=='xhs' else 'aweme_id'
                page['saved']=all(entity in rows and str(rows[entity].get(content_key))==page['content_id'] and
                    (str(rows[entity].get('parent_comment_id') or '') in ('','0') if page['scope']=='root' else str(rows[entity].get('parent_comment_id'))==page['parent_id']) for entity in ids)
            if models and not candidates:self.invalid=True
            self.persist();return result
        async def committed(*args,**kwargs):
            a=inspect.signature(commit).bind(*args,**kwargs);a.apply_defaults();a=a.arguments
            result=await commit(*args,**kwargs)
            cp=self.adapter.checkpoint(self.run,self.manifest)
            notes=[n for n in (cp or {}).get('crawled_note_list',[]) if str(n.get('note_id'))==str(a['note_id'])]
            if result is True and a['checkpoint_id']==self.manifest['run_id'] and notes and str(notes[0].get('current_note_comment_cursor'))==str(a['comment_cursor']) and notes[0].get('is_success_crawled_comments') is a['is_success_crawled_comments']:
                matches=[page for page in self.pages if page['scope']=='root' and page['content_id']==str(a['note_id']) and str(page['cursor_out'])==str(a['comment_cursor'])]
                if matches:
                    page=matches[-1];durable=page['saved']
                    if self.manifest['request']['replies']:
                        for parent,count in page['reply_roots'].items():
                            children=[child for child in self.pages if child['scope']=='reply' and child['content_id']==page['content_id'] and child['parent_id']==parent]
                            durable &= all(child['saved'] for child in children) and (not count or bool(children) and not children[-1]['has_more'] and len({entity for child in children for entity in child['ids']})==count)
                    page['checkpoint_committed']=bool(durable)
            self.persist();return result
        setattr(client,root_name,roots);setattr(client,reply_name,replies);setattr(store,save_name,saved);manager.update_note_comment_cursor=committed


def summary(run,manifest,adapter):
    try:
        path=Path(run)/'pro-pagination.json'
        if path.is_symlink() or path.stat().st_size>3_000_000:raise ValueError()
        doc=adapter.bridge().read(path);digest=doc.pop('sha256')
        if digest!=hashlib.sha256(adapter.bridge().canonical(doc).encode()).hexdigest() or doc['operation_id']!=manifest['run_id'] or doc.get('platform')!=manifest['request']['platform']:raise ValueError()
        pages=doc['pages'];platform=doc['platform']
        if not pages or doc['invalid'] or any(page['invalid'] for page in pages):return {'coverage':'unknown','reason':'pagination_fields_invalid'}
        if any(page.get('stalled') or not page['saved'] for page in pages):return {'coverage':'partial','reason':'page_stalled_or_not_saved'}
        observations=adapter.observations(run,manifest)
        saved={entity:row for kind,entity,row in observations if kind=='comment'}
        topics={entity for kind,entity,row in observations if kind=='topic'}
        roots_all=[page for page in pages if page['scope']=='root']
        if {page['content_id'] for page in roots_all}!=topics or set(saved)!={entity for page in pages for entity in page['ids']}:return {'coverage':'unknown','reason':'page_observation_set_mismatch'}
        root_ids={entity for page in roots_all for entity in page['ids']}
        if any(page['parent_id'] not in root_ids for page in pages if page['scope']=='reply'):return {'coverage':'unknown','reason':'reply_root_not_observed'}
        key='note_id' if platform=='xhs' else 'aweme_id'
        for page in pages:
            if any(entity not in saved or str(saved[entity].get(key))!=page['content_id'] or (str(saved[entity].get('parent_comment_id') or '') not in ('','0') if page['scope']=='root' else str(saved[entity].get('parent_comment_id'))!=page['parent_id']) for entity in page['ids']):raise ValueError()
        exhausted=True
        for content in {page['content_id'] for page in pages if page['scope']=='root'}:
            roots=[page for page in pages if page['scope']=='root' and page['content_id']==content]
            if roots[0]['cursor_in']!=('' if platform=='xhs' else 0):return {'coverage':'unknown','reason':'root_chain_origin_unknown'}
            seen=set();seen_ids=set()
            for index,page in enumerate(roots):
                if page['cursor_in'] in seen or index and (not roots[index-1]['has_more'] or roots[index-1]['cursor_out']!=page['cursor_in']):return {'coverage':'unknown','reason':'root_chain_invalid'}
                seen.add(page['cursor_in'])
                if seen_ids.intersection(page['ids']):return {'coverage':'unknown','reason':'repeated_root_ids'}
                seen_ids.update(page['ids'])
                if manifest['request']['replies']:
                    for parent,count in page['reply_roots'].items():
                        replies=[r for r in pages if r['scope']=='reply' and r['content_id']==content and r['parent_id']==parent]
                        ids=[i for r in replies for i in r['ids']]
                        if not count and replies:return {'coverage':'unknown','reason':'unexpected_replies_for_zero_count'}
                        if count and (not replies or replies[-1]['has_more'] or len(set(ids))!=count or len(ids)!=len(set(ids))):return {'coverage':'partial','reason':'reply_chain_incomplete'}
                        if replies and not replies[0]['embedded'] and replies[0]['cursor_in']!=(page.get('reply_cursor_start',{}).get(parent) if platform=='xhs' else 0):return {'coverage':'unknown','reason':'reply_chain_origin_unknown'}
                        for j,r in enumerate(replies):
                            if j and (not replies[j-1]['has_more'] or replies[j-1]['cursor_out']!=r['cursor_in']):return {'coverage':'unknown','reason':'reply_cursor_chain_invalid'}
            cp=adapter.checkpoint(run,manifest);notes=[n for n in (cp or {}).get('crawled_note_list',[]) if str(n.get('note_id'))==content]
            if not roots[-1]['checkpoint_committed'] or not notes or str(notes[0].get('current_note_comment_cursor'))!=str(roots[-1]['cursor_out']):return {'coverage':'partial','reason':'parent_checkpoint_unconfirmed'}
            exhausted &= not roots[-1]['has_more']
        if exhausted:return {'coverage':'exhausted','reason':'accessible_page_chain_ended'}
        cp=adapter.checkpoint(run,manifest);limit=manifest['request']['max_comments']
        if cp and cp.get('acquisition_committed') is True and limit and all(n.get('is_success_crawled_comments') is True and n.get('saved_comment_count',0)>=limit for n in cp.get('crawled_note_list',[])):
            return {'coverage':'limit_reached','reason':'upstream_batch_limit'}
        return {'coverage':'partial','reason':'root_chain_incomplete'}
    except (OSError,ValueError,KeyError,TypeError,AttributeError,sqlite3.Error):return {'coverage':'unknown','reason':'pagination_evidence_invalid'}
