"""Isolated self-authenticated Zhihu detail control; licensed SDK stays external.
This is not registered by the production executor or a stand-alone collector.
HTTP transport/ledger and AccountSessions authorization must be installed by caller.
"""
import hashlib
import json
import re
from urllib.parse import urlsplit


class ZhihuStop(BaseException):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def register_observations(protocol):
    mapping={'zhihu_content':('zhihu','topic','content_id'),
             'zhihu_comment':('zhihu','comment','comment_id')}
    for table, spec in mapping.items():
        if table in protocol.TABLES and protocol.TABLES[table] != spec:
            raise ValueError('zhihu_protocol_mapping_conflict')
    protocol.TABLES.update(mapping)
    return mapping


def self_proof(response):
    """Only official self response; never target creator, Cookie or raw diagnostic."""
    try:
        u=urlsplit(str(response.url))
        if (u.scheme!='https' or u.hostname!='www.zhihu.com' or u.port not in (None,443)
                or u.path!='/api/v4/me' or u.username or u.password or u.fragment):
            return None
        # Native SDK adds include=email,is_active,is_bind_phone; do not persist fields.
        from urllib.parse import parse_qs
        query=parse_qs(u.query,keep_blank_values=True)
        if query not in ({},{'include':['email,is_active,is_bind_phone']}):
            return ('check_failed',None)
        if response.status_code==401:return ('logged_out',None)
        if response.status_code!=200:return ('check_failed',None)
        data=response.json()
        uid=data.get('uid') if isinstance(data,dict) else None
        if not isinstance(uid,(str,int)) or isinstance(uid,bool) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',str(uid)):
            return ('check_failed',None)
        return ('authenticated',str(uid))
    except Exception:return ('check_failed',None)


def detail_target(value):
    if not isinstance(value,str):raise ValueError('zhihu_detail_target_invalid')
    u=urlsplit(value)
    if u.scheme!='https' or u.hostname not in ('www.zhihu.com','zhihu.com','zhuanlan.zhihu.com') or u.port or u.username or u.password or u.fragment:
        raise ValueError('zhihu_detail_target_invalid')
    article=re.fullmatch(r'/p/([1-9][0-9]*)/?',u.path)
    if article:return None,article.group(1)
    if u.hostname=='zhuanlan.zhihu.com':raise ValueError('zhihu_detail_target_invalid')
    match=re.fullmatch(r'/question/([1-9][0-9]*)/answer/([1-9][0-9]*)/?',u.path)
    if not match:raise ValueError('zhihu_detail_target_invalid')
    return match.groups()


def _identity(value):
    if not isinstance(value,(str,int)) or isinstance(value,bool) or not re.fullmatch(r'[1-9][0-9]{0,29}',str(value)):
        raise ZhihuStop('zhihu_comment_identity_invalid')
    return str(value)


class ZhihuDetail:
    """Reuse original client, extractor, model, store and durable checkpoint manager.

    adapter provides existing observations/checkpoint/bridge helpers. No retries or
    alternate network channel are created. Do not call before official same-ref auth.
    """
    def __init__(self,run,manifest,adapter,client,extractor,store,manager):
        self.run,self.manifest,self.adapter=run,manifest,adapter
        self.client,self.extractor,self.store,self.manager=client,extractor,store,manager
        request=manifest['request']
        if (request.get('platform')!='zhihu' or request.get('mode')!='detail'
                or type(request.get('max_items')) is not int or request['max_items']!=1
                or request.get('media') is not False or request.get('platform_options')!={}
                or request.get('wordcloud',False) is not False
                or type(request.get('max_comments')) is not int or not 1<=request['max_comments']<=200
                or len(request.get('targets',[]))!=1):raise ValueError('zhihu_candidate_scope_unsupported')
        self.question,self.content_id=detail_target(request['targets'][0])
        self.pages=[];self.coverage='partial';self.reason='not_started';self.saved_count=0
    def persist(self):
        body={'schema_version':1,'operation_id':self.manifest['run_id'],'platform':'zhihu',
              'pages':self.pages,'coverage':self.coverage,'reason':self.reason,'invalid':False}
        text=self.adapter.bridge().canonical(body)
        if len(self.pages)>1000 or len(text.encode())>2_900_000:raise ZhihuStop('zhihu_page_evidence_limit')
        self.adapter.bridge().write(self.run/'pro-pagination.json',
          {**body,'sha256':hashlib.sha256(text.encode()).hexdigest()})
    def durable(self,kind,models):
        rows={entity:row for k,entity,row in self.adapter.observations(self.run,self.manifest) if k==kind}
        for model in models:
            entity=str(model.content_id if kind=='topic' else model.comment_id)
            if entity not in rows:raise ZhihuStop('zhihu_save_not_durable')
            expected=model.model_dump()
            # Native SQLite schema intentionally stores these timestamps as TEXT.
            for key in ('content_id','question_id','created_time','updated_time','publish_time'):
                if key in expected and expected[key] is not None:expected[key]=str(expected[key])
            if any(key not in rows[entity] or type(rows[entity][key]) is not type(value) or rows[entity][key]!=value
                   for key,value in expected.items()):raise ZhihuStop('zhihu_saved_model_mismatch')
            if str(rows[entity].get('content_id'))!=self.content_id:raise ZhihuStop('zhihu_saved_content_mismatch')
        return rows
    async def page(self,content,scope,incoming,parent=None):
        if len(self.pages)>=1000:raise ZhihuStop('zhihu_page_evidence_limit')
        raw=(await self.client.get_root_comments(self.content_id,content.content_type,incoming,10)
             if scope=='root' else await self.client.get_child_comments(parent,incoming,10))
        if not isinstance(raw,dict) or not isinstance(raw.get('paging'),dict) or not isinstance(raw.get('data'),list) or len(raw['data'])>10000:
            raise ZhihuStop('zhihu_page_shape_invalid')
        paging=raw['paging'];is_end=paging.get('is_end')
        if type(is_end) is not bool:raise ZhihuStop('zhihu_page_end_invalid')
        outgoing=self.extractor.extract_offset(paging)
        if not isinstance(outgoing,str) or len(outgoing)>512:raise ZhihuStop('zhihu_page_cursor_invalid')
        models=self.extractor.extract_comments(content,raw['data'])
        ids=[_identity(m.comment_id) for m in models]
        if len(models)!=len(raw['data']) or [str(x.get('id')) for x in raw['data'] if isinstance(x,dict)]!=ids:
            raise ZhihuStop('zhihu_extractor_dropped_rows')
        if scope=='root' and any(m.parent_comment_id not in ('','0',0,None) for m in models):
            raise ZhihuStop('zhihu_root_parent_invalid')
        if scope=='reply':
            prior_reply_ids={i for p in self.pages if p['scope']=='reply' and p['parent_id']==parent and p['saved'] for i in p['ids']}
            parents={str(m.comment_id):str(m.parent_comment_id or '') for m in models}
            for entity in ids:
                visited=set();current=entity
                while current not in prior_reply_ids and current!=parent:
                    if current in visited or current not in parents:raise ZhihuStop('zhihu_reply_parent_mismatch')
                    visited.add(current);current=parents[current]
        if len(ids)!=len(set(ids)):raise ZhihuStop('zhihu_duplicate_page_ids')
        prior={i for p in self.pages for i in p['ids']}
        if self.saved_count+len(ids)>10000:raise ZhihuStop('zhihu_observation_limit')
        if prior.intersection(ids):raise ZhihuStop('zhihu_comment_replayed')
        if not is_end and (not models or outgoing==incoming or any(p['scope']==scope and p['parent_id']==parent and p['cursor_in']==outgoing for p in self.pages)):
            raise ZhihuStop('zhihu_pagination_cursor_stalled')
        page={'scope':scope,'content_id':self.content_id,'parent_id':parent,'ids':ids,
              'cursor_in':incoming,'cursor_out':outgoing,'has_more':not is_end,'saved':False,
              'checkpoint_committed':False,'embedded':False,'reply_roots':{str(m.comment_id):m.sub_comment_count for m in models} if scope=='root' else {}}
        self.pages.append(page);self.persist()
        if models:
            await self.store.batch_update_zhihu_note_comments(models)
            self.durable('comment',models)
        page['saved']=True;self.saved_count+=len(models);self.persist()
        return models,page
    async def collect(self):
        try:
            article=self.question is None
            content=(await self.client.get_article_info(self.content_id) if article
                     else await self.client.get_answer_info(self.question,self.content_id))
            if (content is None or str(content.content_id)!=self.content_id
              or content.content_type!=('article' if article else 'answer')
              or not article and str(content.question_id)!=self.question):
                raise ZhihuStop('zhihu_detail_identity_invalid')
            await self.store.update_zhihu_content(content);self.durable('topic',[content])
            if not self.manifest['request']['comments']:
                self.reason='comments_disabled';self.persist();return content
            offset=''
            while True:
                roots,page=await self.page(content,'root',offset)
                if self.manifest['request']['replies']:
                    for root in roots:
                        if type(root.sub_comment_count) is not int or root.sub_comment_count<0:raise ZhihuStop('zhihu_reply_count_invalid')
                        if root.sub_comment_count:
                            child_offset='';before_count=self.saved_count
                            while True:
                                _,reply=await self.page(content,'reply',child_offset,str(root.comment_id))
                                if not reply['has_more']:break
                                child_offset=reply['cursor_out']
                            if self.saved_count-before_count!=root.sub_comment_count:raise ZhihuStop('zhihu_replies_not_fully_saved')
                # Never commit roots ahead of their saved reply chain.
                done=not page['has_more'];limited=self.saved_count>=self.manifest['request']['max_comments']
                result=await self.manager.update_note_comment_cursor(
                    checkpoint_id=self.manifest['run_id'],note_id=self.content_id,
                    comment_cursor=page['cursor_out'],is_success_crawled_comments=done or limited,saved_comment_count=self.saved_count)
                cp=self.adapter.checkpoint(self.run,self.manifest)
                notes=[n for n in (cp or {}).get('crawled_note_list',[]) if str(n.get('note_id'))==self.content_id]
                if result is not True or not notes or notes[0].get('current_note_comment_cursor')!=page['cursor_out'] or notes[0].get('is_success_crawled_comments') is not (done or limited):
                    raise ZhihuStop('zhihu_checkpoint_unconfirmed')
                page['checkpoint_committed']=True;self.persist()
                if done or limited:
                    self.coverage='exhausted' if done else 'limit_reached';self.reason='accessible_page_chain_ended' if done else 'limit_reached';self.persist();return content
                offset=page['cursor_out']
        except BaseException:
            self.coverage='partial';self.reason='interrupted_or_failed'
            try:self.persist()
            except BaseException:pass
            raise


def install_detail(run,manifest,adapter,handler_type):
    """Wrap original handler after native account setup and DB initialization."""
    original=handler_type.handle
    from media_platform.zhihu.client import ZhiHuClient
    original_request=ZhiHuClient.request
    if not hasattr(original_request,'__wrapped__'):raise ValueError('zhihu_native_retry_contract_changed')
    import inspect
    native_request=inspect.unwrap(original_request)
    if native_request.__module__!='media_platform.zhihu.client' or native_request.__name__!='request':raise ValueError('zhihu_native_retry_contract_changed')
    ZhiHuClient.request=native_request
    async def handle(handler):
        from model.m_checkpoint import Checkpoint
        from repo.platform_save_data import zhihu as store
        from media_platform.zhihu.help import ZhihuExtractor
        # Unknown old attempt must never be silently resumed/re-fetched.
        if (run/'pro-pagination.json').exists():raise ZhihuStop('zhihu_unknown_resume_forbidden')
        question,content_id=detail_target(manifest['request']['targets'][0])
        manager=handler.checkpoint_manager
        await manager.save_checkpoint(Checkpoint(platform='zhihu',mode='detail',id=manifest['run_id']))
        await manager.add_note_to_checkpoint(manifest['run_id'],content_id,
            {'content_type':'article' if question is None else 'answer','question_id':question})
        collector=ZhihuDetail(run,manifest,adapter,handler.zhihu_client,ZhihuExtractor(),store,manager)
        await collector.collect()
        before=adapter.checkpoint(run,manifest)
        previous=before.get('crawled_note_list') if isinstance(before,dict) else None
        if not isinstance(previous,list) or len(previous)!=1 or str(previous[0].get('note_id'))!=content_id:
            raise ZhihuStop('zhihu_body_checkpoint_unconfirmed')
        # Native manager defaults this parameter to None and would erase the last
        # committed root cursor when merely setting the note success flag.
        await manager.update_note_to_checkpoint(checkpoint_id=manifest['run_id'],note_id=content_id,
            is_success_crawled=True,is_success_crawled_comments=True,
            current_note_comment_cursor=previous[0].get('current_note_comment_cursor'))
        cp=adapter.checkpoint(run,manifest)
        notes=cp.get('crawled_note_list',[]) if isinstance(cp,dict) else []
        if len(notes)!=1 or notes[0].get('is_success_crawled') is not True:
            raise ZhihuStop('zhihu_body_checkpoint_unconfirmed')
    handler_type.handle=handle
    class Hook:
        def restore(self):
            handler_type.handle=original
            ZhiHuClient.request=original_request
    return Hook()


def pagination_summary(run,manifest,adapter):
    if not manifest['request']['comments']:return {'coverage':'not_requested','reason':'comments_disabled'}
    from pro_source_steps import safe_json
    d=safe_json(run/'pro-pagination.json')
    if not isinstance(d,dict):return {'coverage':'unknown','reason':'zhihu_page_evidence_missing'}
    body={k:v for k,v in d.items() if k!='sha256'}
    if (type(d.get('schema_version')) is not int or d['schema_version']!=1
      or d.get('operation_id')!=manifest['run_id'] or d.get('platform')!='zhihu'
      or d.get('sha256')!=hashlib.sha256(adapter.bridge().canonical(body).encode()).hexdigest()
      or d.get('invalid') is not False or not isinstance(d.get('pages'),list) or len(d['pages'])>1000):
        return {'coverage':'unknown','reason':'zhihu_page_evidence_invalid'}
    rows={e:v for k,e,v in adapter.observations(run,manifest) if k=='comment'}
    target=detail_target(manifest['request']['targets'][0])[1]
    for page in d['pages']:
        if (not isinstance(page,dict) or page.get('scope') not in ('root','reply')
          or page.get('content_id')!=target or not isinstance(page.get('ids'),list)
          or any(not isinstance(i,str) or not re.fullmatch(r'[1-9][0-9]{0,29}',i) for i in page['ids']) or len(page['ids'])!=len(set(page['ids']))
          or type(page.get('saved')) is not bool or type(page.get('checkpoint_committed')) is not bool
          or type(page.get('has_more')) is not bool or page.get('embedded') is not False
          or not isinstance(page.get('reply_roots'),dict)
          or any(not isinstance(k,str) or not re.fullmatch(r'[1-9][0-9]{0,29}',k) or type(v) is not int or v<0 for k,v in page.get('reply_roots',{}).items())
          or not isinstance(page.get('cursor_in'),str) or not isinstance(page.get('cursor_out'),str)
          or page['scope']=='root' and page.get('parent_id') is not None
          or page['scope']=='reply' and (not isinstance(page.get('parent_id'),str) or not re.fullmatch(r'[1-9][0-9]{0,29}',page['parent_id']) or page['checkpoint_committed'] is not False)):
            return {'coverage':'unknown','reason':'zhihu_page_shape_invalid'}
        for entity in page['ids']:
            if entity not in rows or str(rows[entity].get('content_id'))!=target:
                return {'coverage':'unknown','reason':'zhihu_durable_identity_mismatch'}
            if page['scope']=='root' and rows[entity].get('parent_comment_id') not in ('','0',0,None):
                return {'coverage':'unknown','reason':'zhihu_root_parent_invalid'}
            if page['scope']=='reply':
                visited=set();current=entity
                while current!=page['parent_id']:
                    if current in visited or current not in rows:return {'coverage':'unknown','reason':'zhihu_reply_parent_mismatch'}
                    visited.add(current);current=str(rows[current].get('parent_comment_id') or '')
                if current not in rows or rows[current].get('parent_comment_id') not in ('','0',0,None):
                    return {'coverage':'unknown','reason':'zhihu_reply_root_missing'}
    roots=[x for x in d['pages'] if isinstance(x,dict) and x.get('scope')=='root']
    all_ids=[i for page in d['pages'] for i in page['ids']]
    if len(all_ids)!=len(set(all_ids)):return {'coverage':'unknown','reason':'zhihu_repeated_page_comment_ids'}
    declared_roots={i for page in roots for i in page['ids']}
    if any(page['scope']=='reply' and page['parent_id'] not in declared_roots for page in d['pages']):return {'coverage':'unknown','reason':'zhihu_reply_scope_root_missing'}
    if not roots:return {'coverage':'partial','reason':'zhihu_root_missing'}
    previous='';seen=set();ended=False
    for page in roots:
        ids=page.get('ids')
        if (ended or page.get('cursor_in')!=previous or not isinstance(ids,list) or seen.intersection(ids)
          or page.get('saved') is not True or page.get('checkpoint_committed') is not True
          or type(page.get('has_more')) is not bool or any(i not in rows for i in ids)):
            return {'coverage':'unknown','reason':'zhihu_root_chain_invalid'}
        seen.update(ids);previous=page.get('cursor_out');ended=not page['has_more']
        declared=page.get('reply_roots',{})
        if set(declared)!=set(ids) or any(type(rows[i].get('sub_comment_count')) is not int or declared[i]!=rows[i]['sub_comment_count'] for i in ids):
            return {'coverage':'unknown','reason':'zhihu_root_reply_declaration_unbound'}
        if manifest['request']['replies']:
            for root,count in declared.items():
                if type(count) is not int or count<0:return {'coverage':'unknown','reason':'zhihu_reply_count_invalid'}
                chain=[x for x in d['pages'] if isinstance(x,dict) and x.get('scope')=='reply' and x.get('parent_id')==root]
                cursor='';reply_ids=set();reply_ended=False
                for reply in chain:
                    if (reply_ended or reply.get('cursor_in')!=cursor or reply.get('saved') is not True or not isinstance(reply.get('ids'),list)
                       or reply_ids.intersection(reply['ids']) or any(i not in rows for i in reply['ids'])):
                        return {'coverage':'unknown','reason':'zhihu_reply_chain_invalid'}
                    reply_ids.update(reply['ids']);cursor=reply.get('cursor_out');reply_ended=not reply['has_more']
                if count and (not chain or chain[-1].get('has_more') is not False or len(reply_ids)!=count):
                    return {'coverage':'partial','reason':'zhihu_replies_not_fully_saved'}
    if set(rows)!={i for p in d['pages'] for i in p['ids']}:return {'coverage':'partial','reason':'zhihu_orphan_saved_comments'}
    cp=adapter.checkpoint(run,manifest)
    notes=cp.get('crawled_note_list') if isinstance(cp,dict) else None
    if (not isinstance(notes,list) or len(notes)!=1 or not isinstance(notes[0],dict)
      or str(notes[0].get('note_id'))!=target or notes[0].get('current_note_comment_cursor')!=roots[-1]['cursor_out']
      or notes[0].get('is_success_crawled') is not True or notes[0].get('is_success_crawled_comments') is not True
      or type(notes[0].get('saved_comment_count')) is not int or notes[0]['saved_comment_count']!=len(rows)):
        return {'coverage':'partial','reason':'zhihu_checkpoint_unconfirmed'}
    if roots[-1]['has_more'] is False:return {'coverage':'exhausted','reason':'accessible_page_chain_ended'}
    if d.get('coverage')=='limit_reached' and len(rows)>=manifest['request']['max_comments']:
        return {'coverage':'limit_reached','reason':'page_level_soft_limit'}
    return {'coverage':'partial','reason':'zhihu_chain_not_ended'}
