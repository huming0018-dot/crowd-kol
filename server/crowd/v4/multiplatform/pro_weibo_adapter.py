"""Runtime-only bridge for the licensed Pro Weibo SDK; no upstream code bundled.
Not registered in the production executor. Source methods/extractors/stores stay native.
"""
import asyncio
import contextvars
import hashlib
import json
import re
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit, urlencode
import importlib
import inspect

class WeiboAdapterStop(BaseException):
    def __init__(self,reason):self.reason=reason;super().__init__(reason)

def capabilities():
    return {'platform':'wb','modes':['search','detail','creator'],'hot_search':'upstream_present_not_integrated',
            'reply_scope':'embedded_or_verified_child_cursor; unconfirmed replies remain partial',
            'media':'references_only; byte download not implemented','production_registered':False}

def register_observations(protocol):
    """Original SQLite writer consults TABLES inside its existing transaction."""
    expected={'weibo_note':('wb','topic','note_id'),'weibo_note_comment':('wb','comment','comment_id')}
    for table,value in expected.items():
        if table in protocol.TABLES and protocol.TABLES[table]!=value:raise ValueError('wb_protocol_mapping_conflict')
    protocol.TABLES.update(expected)
    return expected

def prepare(config,protocol,request):
    if request.get('platform')!='wb' or request.get('mode') not in capabilities()['modes']:raise ValueError('wb_operation_unsupported')
    # WB NoteProcessor reads base_config directly; aggregate config alone is ignored.
    from config import base_config
    for target in (config,base_config):
        target.ENABLE_WEIBO_FULL_TEXT=True
        target.PER_NOTE_MAX_COMMENTS_COUNT=request['max_comments']
    return register_observations(protocol)

def self_proof(response):
    try:
        u=urlsplit(str(response.request.url))
        if (u.scheme!='https' or u.hostname!='m.weibo.cn' or u.port not in (None,443) or u.path!='/api/config'
                or u.query or u.fragment or u.username or u.password):return None
        if response.status_code!=200:return ('check_failed',None)
        data=response.json();body=data.get('data')
        if not isinstance(body,dict):return ('check_failed',None)
        if body.get('login') is False:return ('logged_out',None)
        if body.get('login') is not True or ('ok' in data and (type(data['ok']) is not int or data['ok']!=1)):return ('check_failed',None)
        values=[v for v in (body.get('uid'),data.get('uid')) if v is not None]
        if not values or any(isinstance(v,bool) or not re.fullmatch(r'[1-9][0-9]{0,29}',str(v)) for v in values):return ('check_failed',None)
        if len({str(v) for v in values})!=1:return ('check_failed',None)
        return ('authenticated',str(values[0]))
    except Exception:return ('check_failed',None)

class WeiboIdentity:
    def __init__(self,collector_root,session_id,run_id,event=lambda *a:None):
        from account_sessions import AccountSessions
        self.store=AccountSessions(collector_root);self.session=session_id;self.run=run_id;self.event=event
        self.capture=contextvars.ContextVar('wb_official_self',default=None);self.originals=None
    def emit(self,value):self.event(value['state'],value)
    def observe_response(self,response):
        slot=self.capture.get();proof=self_proof(response)
        if slot is not None and proof is not None:slot['proof']=proof
    def install(self,client_type,httpx_module):
        original_pong=client_type.pong;original_send=httpx_module.AsyncClient.send;owner=self
        async def send(client,*a,**kw):
            response=await original_send(client,*a,**kw);owner.observe_response(response);return response
        async def pong(client,*a,**kw):
            previous=owner.store.status(owner.session,'wb')
            if previous.get('pending_run_id') and not previous.get('account_ref'):
                if previous['pending_run_id']!=owner.run:raise SystemExit(85)
                owner.store._update(owner.session,'wb',lambda v:v.update(recovering=True,identity_status='baseline_unverified'))
            owner.emit(owner.store.observe(owner.session,'wb','checking',owner.run))
            slot={'proof':('check_failed',None)};token=owner.capture.set(slot)
            try:result=await original_pong(client,*a,**kw)
            except BaseException:
                try:owner.emit(owner.store.observe(owner.session,'wb','logged_out' if slot['proof'][0]=='logged_out' else 'check_failed',owner.run))
                except BaseException:pass
                raise
            finally:owner.capture.reset(token)
            proof,uid=slot['proof']
            if result is not True or proof!='authenticated':
                owner.emit(owner.store.observe(owner.session,'wb','logged_out' if proof=='logged_out' else 'check_failed',owner.run))
                raise SystemExit(77 if proof=='logged_out' else 86)
            value=owner.store.observe(owner.session,'wb','authenticated',owner.run,uid);owner.emit(value)
            if value['state']=='account_changed':raise SystemExit(78)
            if value.get('authorized_for_run')!=owner.run:raise SystemExit(77)
            return True
        client_type.pong=pong;httpx_module.AsyncClient.send=send
        self.originals=(client_type,httpx_module,original_pong,original_send);return self
    def restore(self):
        if self.originals:
            cls,httpx,pong,send=self.originals;cls.pong=pong;httpx.AsyncClient.send=send;self.originals=None

class WeiboPagination:
    def __init__(self,run,manifest,bridge,event=lambda *a:None,page_budget=100):
        if type(page_budget) is not int or not 1<=page_budget<=1000:raise ValueError('wb_page_budget_invalid')
        bridge.uid(manifest['run_id'])
        if manifest['request']['platform']!='wb' or manifest['request']['mode'] not in capabilities()['modes']:raise ValueError('wb_operation_unsupported')
        self.run=Path(run);self.manifest=manifest;self.bridge=bridge;self.event=event;self.page_budget=page_budget
        self.pages=[];self.coverage='partial';self.reason='not_started';self.original=None
        path=self.run/'pro-pagination.json'
        if path.is_symlink():raise ValueError('wb_page_file_invalid')
        if path.exists():
            fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|getattr(os,'O_NOFOLLOW',0))
            try:
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size>3_000_000:raise ValueError('wb_page_file_invalid')
                with os.fdopen(fd,'rb',closefd=False) as stream:payload=stream.read(3_000_001)
                if len(payload)>3_000_000:raise ValueError('wb_page_file_invalid')
                d=json.loads(payload)
                if not isinstance(d,dict):raise ValueError('wb_page_file_invalid')
            finally:os.close(fd)
            sha=d.pop('sha256',None)
            if (type(d.get('schema_version')) is not int or d.get('schema_version')!=1 or d.get('invalid') is not False or d.get('platform')!='wb' or d.get('operation_id')!=manifest['run_id'] or hashlib.sha256(bridge.canonical(d).encode()).hexdigest()!=sha):raise ValueError('wb_page_file_binding')
            self.pages=d['pages'];self.coverage=d.get('coverage','partial');self.reason=d.get('reason','resume')
            if not isinstance(self.pages,list) or len(self.pages)>1000:raise ValueError('wb_page_file_invalid')
    def persist(self):
        d={'schema_version':1,'operation_id':self.manifest['run_id'],'platform':'wb','pages':self.pages,
           'coverage':self.coverage,'reason':self.reason,'invalid':False}
        raw=self.bridge.canonical(d)
        if len(self.pages)>1000 or len(raw.encode())>2_900_000:raise WeiboAdapterStop('wb_page_evidence_limit')
        self.bridge.write(self.run/'pro-pagination.json',{**d,'sha256':hashlib.sha256(raw.encode()).hexdigest()})
    def notify(self,page):
        # Only the existing central step reader's safe descriptor; no content/UID/cookies.
        try:self.event('page_saved' if page['saved'] else 'page_partially_saved',{'page_sha256':hashlib.sha256(self.bridge.canonical(page).encode()).hexdigest(),
                'page_index':self.pages.index(page)+1,'scope':page['scope'],'saved_rows':len(page.get('selected_ids',page['ids'])),
                'checkpoint_committed':page['checkpoint_committed']})
        except Exception:pass
    def page(self,note,scope,models,incoming,outgoing,more,parent=None):
        ids=[str(m.comment_id) for m in models]
        seen={identity for previous in self.pages for identity in previous['ids']}
        if seen.intersection(ids):raise WeiboAdapterStop('wb_comment_replayed')
        if len(set(ids))!=len(ids) or any(not re.fullmatch(r'[1-9][0-9]{0,29}',v) for v in ids):raise WeiboAdapterStop('wb_comment_identity_invalid')
        p={'scope':scope,'content_id':str(note),'parent_id':parent,'ids':ids,'cursor_in':incoming,'cursor_out':outgoing,
           'has_more':more,'saved':False,'checkpoint_committed':False,'embedded':scope=='reply'}
        self.pages.append(p);self.persist();return p
    async def save(self,page,models,callback):
        try:
            if models:await callback(page['content_id'],models)
            from pro_executor import observations
            rows={entity:row for kind,entity,row in observations(self.run,self.manifest) if kind=='comment'}
            for identity in page.get('selected_ids',page['ids']):
                row=rows.get(identity,{})
                if str(row.get('note_id'))!=page['content_id']:raise ValueError('wb_save_not_durable')
                parent=str(row.get('parent_comment_id') or '')
                if (page['scope']=='reply' and parent!=page['parent_id']) or (page['scope']=='root' and parent not in ('','0',identity)):
                    raise ValueError('wb_comment_parent_invalid')
            page['saved']=len(page.get('selected_ids',page['ids']))==len(page['ids']);page['selected_saved']=True;self.persist();self.notify(page)
        except BaseException:
            self.reason='wb_save_failed'
            try:self.persist()
            except Exception:pass
            raise
    async def collect_replies(self,processor,note_id,model,callback):
        """Use the installed client's guarded transport/extractor; never retry a page."""
        root=str(model.comment_id);declared=str(model.sub_comment_count or '0')
        if not declared.isdigit():raise WeiboAdapterStop('wb_reply_count_invalid')
        embedded=model.sub_comments or []
        complete=(len(embedded)==int(declared) and all(not c.sub_comments and str(c.sub_comment_count or '0')=='0' for c in embedded))
        if complete:
            page=self.page(note_id,'reply',embedded,None,None,False,root)
            await self.save(page,embedded,callback)
            return embedded
        # Embedded previews overlap child pagination. They are not separately saved,
        # so each child identity is saved exactly once in the authoritative chain.
        cursor=0;result=[];known=set();expected=int(declared)
        for _ in range(self.page_budget):
            client=processor.wb_client
            # Exact installed SDK raw-response contract, without its retry/IP rotation.
            request=inspect.unwrap(client.request)
            sdk=importlib.import_module(type(client).__module__)
            if (not callable(request) or getattr(request,'__module__',None)!=type(client).__module__
                    or Path(inspect.getfile(request)).resolve()!=Path(sdk.__file__).resolve()
                    or getattr(sdk,'WEIBO_API_URL',None)!='https://m.weibo.cn'):
                raise WeiboAdapterStop('wb_reply_transport_contract_invalid')
            response=await request(client,method='GET',url=sdk.WEIBO_API_URL+'/comments/hotFlowChild?'+urlencode({'cid':root,'max_id':cursor,'max_id_type':0}),return_response=True)
            if type(getattr(response,'status_code',None)) is not int or response.status_code!=200:
                raise WeiboAdapterStop('wb_reply_http_invalid')
            try:raw=response.json()
            except (ValueError,UnicodeError,RecursionError):raise WeiboAdapterStop('wb_reply_page_shape_invalid') from None
            if not isinstance(raw,dict) or type(raw.get('ok')) is not int or raw['ok'] not in (0,1):
                raise WeiboAdapterStop('wb_reply_business_code_invalid')
            if not isinstance(raw.get('data'),list) or (raw['ok']==0 and raw['data']):raise WeiboAdapterStop('wb_reply_page_shape_invalid')
            outgoing=raw.get('max_id')
            if type(outgoing) is not int or outgoing<0:raise WeiboAdapterStop('wb_reply_cursor_invalid')
            rows=raw['data'];targets={};models=[]
            for row in rows:
                if not isinstance(row,dict):raise WeiboAdapterStop('wb_reply_page_shape_invalid')
                identity=str(row.get('id',''));parent=str(row.get('rootid',''))
                if not re.fullmatch(r'[1-9][0-9]{0,29}',identity) or parent!=root or identity==root:raise WeiboAdapterStop('wb_reply_parent_invalid')
                if row.get('comments'):raise WeiboAdapterStop('wb_reply_nested_shape_unverified')
                target=row.get('reply_id')
                if target is not None:
                    target=str(target)
                    if not re.fullmatch(r'[1-9][0-9]{0,29}',target):raise WeiboAdapterStop('wb_reply_target_invalid')
                    targets[identity]=target
                child=processor.wb_client._extractor.extract_comment_from_dict(str(note_id),row)
                if child is None or str(child.parent_comment_id)!=root:raise WeiboAdapterStop('wb_reply_parent_invalid')
                models.append(child)
            ids=[str(c.comment_id) for c in models]
            if known.intersection(ids):raise WeiboAdapterStop('wb_comment_replayed')
            known.update(ids)
            page=self.page(note_id,'reply',models,[cursor,0],[outgoing,0],outgoing!=0,root)
            page['embedded']=False;page['targets']=targets;page['declared_count']=expected
            await self.save(page,models,callback);result.extend(models)
            if outgoing==0:
                if len(known)<expected or not {str(c.comment_id) for c in embedded}.issubset(known):raise WeiboAdapterStop('wb_reply_terminal_incomplete')
                if any(t!=root and t not in known for p in self.pages if p.get('parent_id')==root for t in p.get('targets',{}).values()):raise WeiboAdapterStop('wb_reply_target_unbound')
                return result
            if not rows or outgoing==cursor:raise WeiboAdapterStop('wb_reply_cursor_stalled')
            cursor=outgoing
            import config
            await asyncio.sleep(config.CRAWLER_TIME_SLEEP)
        raise WeiboAdapterStop('wb_reply_page_budget')

    async def collect(self,processor,note_id,callback=None,checkpoint_id=''):
        if checkpoint_id!=self.manifest['run_id']:raise ValueError('wb_checkpoint_binding')
        if callback is None:
            from repo.platform_save_data.weibo import batch_update_weibo_note_comments
            callback=batch_update_weibo_note_comments
        manager=processor.checkpoint_manager;note=await manager.get_note_info_from_checkpont(checkpoint_id,note_id)
        if getattr(note,'is_success_crawled_comments',False):return []
        incoming=-1;cursor_type=0;result=[];previous_count=int(getattr(note,'saved_comment_count',0) or 0)
        saved_cursor=await manager.get_note_comment_cursor(checkpoint_id,note_id)
        if any(p['scope']=='root' and p['content_id']==str(note_id) and not p['checkpoint_committed'] for p in self.pages):raise WeiboAdapterStop('wb_partial_page_requires_resolution')
        if saved_cursor:
            matched=[p for p in self.pages if p['scope']=='root' and p['content_id']==str(note_id) and p['checkpoint_committed'] and str(p['cursor_out'][0])==saved_cursor]
            if not matched:raise WeiboAdapterStop('wb_resume_cursor_type_unverified')
            incoming,cursor_type=matched[-1]['cursor_out']
        for _ in range(self.page_budget):
            models,meta=await processor.wb_client.get_note_comments(note_id,incoming,cursor_type)
            outgoing=meta.get('max_id');next_type=meta.get('max_id_type',0)
            if type(outgoing) is not int or outgoing<0 or type(next_type) is not int or not 0<=next_type<=9:raise WeiboAdapterStop('wb_page_cursor_invalid')
            received=models
            limit=self.manifest['request']['max_comments']
            remaining=max(0,limit-previous_count-len(result)) if limit else len(received)
            models=received[:remaining]
            if received and not models:raise WeiboAdapterStop('wb_comment_limit_state_invalid')
            root=self.page(note_id,'root',received,[incoming,cursor_type],[outgoing,next_type],outgoing!=0)
            truncated=len(models)!=len(received)
            if truncated:root['selected_ids']=[str(v.comment_id) for v in models];root['selection_limit']=limit;root['selection_completed']=False
            await self.save(root,models,callback);result.extend(models)
            complete=True
            if self.manifest['request']['replies']:
                for model in models:
                    result.extend(await self.collect_replies(processor,note_id,model,callback))
            self.reason='wb_embedded_replies_incomplete' if not complete else 'wb_cursor_stalled' if outgoing and (not models or [incoming,cursor_type]==[outgoing,next_type]) else None
            if self.reason:
                self.coverage='partial';self.persist();raise WeiboAdapterStop(self.reason)
            limit=self.manifest['request']['max_comments'];limited=bool(limit and previous_count+len(result)>=limit)
            terminal=outgoing==0 or limited
            # A selected prefix cannot advance beyond unprocessed roots in this page.
            committed_cursor=incoming if truncated else outgoing
            ok=await manager.update_note_comment_cursor(checkpoint_id=checkpoint_id,note_id=note_id,comment_cursor=str(committed_cursor),
                saved_comment_count=previous_count+len(result),is_success_crawled_comments=terminal)
            actual=await manager.get_note_info_from_checkpont(checkpoint_id,note_id)
            if ok is not True or await manager.get_note_comment_cursor(checkpoint_id,note_id)!=str(committed_cursor) or actual.saved_comment_count!=previous_count+len(result):
                raise WeiboAdapterStop('wb_checkpoint_unconfirmed')
            root['checkpoint_committed']=not truncated
            if truncated:root['selection_completed']=True
            self.coverage='limit_reached' if truncated else 'exhausted' if outgoing==0 else 'limit_reached' if limited else 'partial'
            self.reason='selected_root_prefix_limit' if truncated else 'accessible_chain_ended' if outgoing==0 else 'comment_limit' if limited else 'more_pages'
            self.persist();self.notify(root)
            if terminal:return result
            incoming,cursor_type=outgoing,next_type
            import config
            await asyncio.sleep(config.CRAWLER_TIME_SLEEP)
        self.coverage='partial';self.reason='wb_page_budget';self.persist();raise WeiboAdapterStop(self.reason)
    def install(self,processor_class):
        self.original=(processor_class,processor_class.get_note_all_comments);owner=self
        async def collected(processor,note_id,callback=None,checkpoint_id=''):
            return await owner.collect(processor,note_id,callback,checkpoint_id)
        processor_class.get_note_all_comments=collected;return self
    def restore(self):
        if self.original:
            cls,method=self.original;cls.get_note_all_comments=method;self.original=None

def pagination_summary(run,manifest,executor):
    """Recheck actual saved identities and cursor chains; do not trust coverage labels."""
    if not manifest['request']['comments']:return {'coverage':'not_requested','reason':'comments_not_requested'}
    try:
        evidence=WeiboPagination(run,manifest,executor.bridge())
        if not evidence.pages:return {'coverage':'unknown','reason':'wb_page_evidence_missing'}
        rows=executor.observations(run,manifest)
        topics={identity for kind,identity,_ in rows if kind=='topic'}
        saved={identity:row for kind,identity,row in rows if kind=='comment'}
        checkpoint=executor.checkpoint(run,manifest)
        notes={str(n['note_id']):n for n in (checkpoint or {}).get('crawled_note_list',[])}
        seen=set();all_exhausted=True
        for note in topics:
            roots=[p for p in evidence.pages if p['scope']=='root' and p['content_id']==note]
            if not roots or roots[0]['cursor_in']!=[-1,0]:raise ValueError('origin')
            root_ids=set();count=0
            for index,page in enumerate(roots):
                for key in ('cursor_in','cursor_out'):
                    pair=page[key]
                    if (not isinstance(pair,list) or len(pair)!=2 or any(type(v) is not int for v in pair) or
                        pair[0]<(-1 if key=='cursor_in' else 0) or not 0<=pair[1]<=9):raise ValueError('cursor')
                if type(page['has_more']) is not bool:raise ValueError('terminal')
                if index and (roots[index-1]['has_more'] is not True or page['cursor_in']!=roots[index-1]['cursor_out']):raise ValueError('chain')
                selected=page.get('selected_ids')
                if selected is not None:
                    consumed=sum(len(v.get('selected_ids',v['ids'])) for v in evidence.pages[:evidence.pages.index(page)] if v['content_id']==note)
                    if len(selected)!=min(len(page['ids']),max(0,manifest['request']['max_comments']-consumed)):raise ValueError('selection_count')
                    if (index!=len(roots)-1 or not isinstance(selected,list) or not selected or selected!=page['ids'][:len(selected)] or len(selected)>=len(page['ids']) or
                        page['saved'] is not False or page['checkpoint_committed'] is not False or page.get('selected_saved') is not True or page.get('selection_completed') is not True or
                        type(page.get('selection_limit')) is not int or page['selection_limit']!=manifest['request']['max_comments'] or len(selected)>page['selection_limit']):raise ValueError('selection')
                elif page['saved'] is not True or page['checkpoint_committed'] is not True:return {'coverage':'partial','reason':'wb_parent_checkpoint_unconfirmed'}
                root_ids.update(selected if selected is not None else page['ids'])
            selected=[p for p in evidence.pages if p['content_id']==note]
            for page in selected:
                if page['scope'] not in ('root','reply') or (page['saved'] is not True and page.get('selection_completed') is not True):return {'coverage':'partial','reason':'wb_page_not_saved'}
                if page['scope']=='reply':
                    if page['parent_id'] not in root_ids or page['checkpoint_committed'] is not False:return {'coverage':'partial','reason':'wb_reply_binding_invalid'}
                    chain=[p for p in selected if p['scope']=='reply' and p['parent_id']==page['parent_id']]
                    if page.get('embedded') is True:
                        if len(chain)!=1 or page['has_more'] is not False:raise ValueError('embedded_chain')
                    else:
                        for i,part in enumerate(chain):
                            for key in ('cursor_in','cursor_out'):
                                pair=part[key]
                                if not isinstance(pair,list) or len(pair)!=2 or any(type(v) is not int for v in pair) or pair[0]<0 or pair[1]!=0:raise ValueError('reply_cursor')
                            if type(part['has_more']) is not bool or part['has_more']!=(part['cursor_out'][0]!=0):raise ValueError('reply_terminal')
                            if part['cursor_in']!=([0,0] if i==0 else chain[i-1]['cursor_out']):raise ValueError('reply_chain')
                            if i and chain[i-1]['has_more'] is not True:raise ValueError('reply_after_terminal')
                        if chain[-1]['has_more'] is not False:raise ValueError('reply_incomplete')
                        identities={v for part in chain for v in part['ids']}
                        for part in chain:
                            if type(part.get('declared_count')) is not int or part['declared_count']<0 or len(identities)<part['declared_count']:raise ValueError('reply_count')
                            targets=part.get('targets')
                            if not isinstance(targets,dict) or not set(targets).issubset(part['ids']) or any(t!=page['parent_id'] and t not in identities for t in targets.values()):raise ValueError('reply_target')
                if len(page['ids'])!=len(set(page['ids'])):raise ValueError('duplicates')
                for identity in page.get('selected_ids',page['ids']):
                    if identity in seen:raise ValueError('replayed')
                    seen.add(identity);count+=1;row=saved.get(identity,{})
                    if str(row.get('note_id'))!=note:raise ValueError('durable')
                    parent=str(row.get('parent_comment_id') or '')
                    if page['scope']=='root' and parent not in ('','0',identity):raise ValueError('root_parent')
                    if page['scope']=='reply' and parent!=page['parent_id']:raise ValueError('reply_parent')
            cp=notes.get(note,{})
            if (cp.get('is_success_crawled_comments') is not True or type(cp.get('saved_comment_count')) is not int or cp.get('saved_comment_count')!=count or
                str(cp.get('current_note_comment_cursor'))!=str(roots[-1]['cursor_in'][0] if roots[-1].get('selection_completed') else roots[-1]['cursor_out'][0])):return {'coverage':'partial','reason':'wb_checkpoint_count_or_cursor_mismatch'}
            last=roots[-1]
            if last.get('selection_completed') is True:
                if not manifest['request']['max_comments'] or count<manifest['request']['max_comments']:raise ValueError('selection_limit')
                all_exhausted=False
            elif last['has_more'] is False:
                if last['cursor_out'][0]!=0:raise ValueError('terminal')
            elif last['has_more'] is True:
                if not manifest['request']['max_comments'] or count<manifest['request']['max_comments']:return {'coverage':'partial','reason':'wb_limit_unconfirmed'}
                all_exhausted=False
            else:raise ValueError('terminal')
        if set(saved)!=seen or any(p['content_id'] not in topics for p in evidence.pages):raise ValueError('unbound')
        return {'coverage':'exhausted' if all_exhausted else 'limit_reached','reason':'accessible_chain_ended' if all_exhausted else 'selected_root_prefix_limit' if any(p.get('selection_completed') is True for p in evidence.pages) else 'comment_limit','reply_scope':'embedded_or_verified_child_cursor'}
    except (OSError,ValueError,KeyError,TypeError,AttributeError,RecursionError,executor.bridge().BridgeError):
        return {'coverage':'unknown','reason':'wb_pagination_evidence_invalid'}
