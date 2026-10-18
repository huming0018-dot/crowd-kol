"""Thin hooks around pinned Pro methods; no platform request/parser implementation."""
import inspect
import asyncio
import time
import re
from participant_pro import ParticipantError, require

class ParticipantNativeHooks:
    def __init__(self,context,rpc,*,clock=None,sleeper=None,journal=None,timeout_seconds=600):
        require(context.get('schema')=='crowd-participant-pro-local-v1','participant_context_invalid')
        self.context,self.rpc=context,rpc;self.authenticated=False;self.details=set();self.originals=[]
        self.known=set(context['known_ids']);self.limit=context['limit']
        require(type(self.limit) is int and 1<=self.limit<=100,'participant_context_invalid')
        require(type(timeout_seconds) is int and 30<=timeout_seconds<=1800,'participant_context_invalid')
        self.clock=clock or time.monotonic;self.sleep=sleeper or asyncio.sleep
        self.deadline=self.clock()+timeout_seconds;self.journal=journal;self.events=[]
    def record(self,action,outcome,result=None):
        # Fixed metadata only: no note ID, principal, lease, URL, token or raw exception.
        event={'action':action,'outcome':outcome}
        reasons={'action_gap','action_budget','session_rest','daily_quota','test_completed','safety_pause',
                 'captcha','rate_limit','lease_expired','lease_lost','task_full','paused','approval_required',
                 'known_note','note_busy','global_pause','executor_changed'}
        if isinstance(result,dict):
            reason=result.get('reason')
            event['reason']=reason if isinstance(reason,str) and reason in reasons else 'other' if reason is not None else None
            for key in ('wait_ms','action_wait_ms','gap_ms'):
                value=result.get(key)
                if type(value) in (int,float) and 0<=value<=300000 and value==value:event[key]=value
        self.events=(self.events+[event])[-100:]
        if self.journal is not None:
            try:self.journal({'schema':'crowd-participant-pro-guard-v1','events':self.events})
            except Exception:pass  # A diagnostic failure cannot change source authorization.

    async def identity(self,platform,uid):
        self.authenticated=False  # A failed re-check must revoke this run's prior proof.
        require(platform=='xhs' and isinstance(uid,str) and re.fullmatch('[a-f0-9]{24}',uid),'participant_principal_invalid')
        result=self.rpc('verify_platform_principal',{'uid':uid})
        if inspect.isawaitable(result):result=await result
        require(isinstance(result,dict) and result.get('matched') is True and result.get('installation_id')==self.context['installation_id'] and result.get('subject')==self.context['binding']['subject'],'participant_principal_mismatch')
        self.authenticated=True
    async def guard(self,action,note=None):
        if not self.authenticated:
            self.record(action,'principal_unverified');raise SystemExit(78)
        c=self.context
        while True:
            if self.clock()>=self.deadline:
                self.record(action,'deadline');raise SystemExit(75)
            try:
                # The bound transport checks original owner/node/generation before AND after
                # this RPC. Reapplying after a known non-admission never repeats a source call.
                result=self.rpc('pro_guard',{'p_task':c['task_id'],'p_lease':c['lease'],'p_action':action,'p_note':note,'p_installation_id':c['installation_id']})
                if inspect.isawaitable(result):result=await result
            except Exception:
                self.record(action,'rpc_unknown');raise SystemExit(86) from None
            if self.clock()>=self.deadline:
                self.record(action,'deadline');raise SystemExit(75)
            if isinstance(result,dict) and result.get('allowed') is True and result.get('reason') is None:
                self.record(action,'admitted',result);return
            if isinstance(result,dict) and result.get('allowed') is False and result.get('reason')=='action_gap':
                wait=result.get('wait_ms')
                if type(wait) in (int,float) and wait==wait and 0<wait<=300000 and self.clock()+wait/1000<self.deadline:
                    self.record(action,'known_gap_wait',result)
                    await self.sleep(wait/1000)
                    continue
            self.record(action,'denied',result);raise SystemExit(74)
    def install(self,client_class):
        hook=self
        original_search=client_class.get_note_by_keyword;original_detail=client_class.get_note_by_id
        async def search(client,*args,**kwargs):
            if len(hook.details)>=hook.limit:return {'items':[],'has_more':False}
            await hook.guard('search')
            result=await original_search(client,*args,**kwargs)
            require(isinstance(result,dict) and isinstance(result.get('items'),list),'participant_discovery_invalid')
            # Filter original IDs before the native handler applies its max_notes slice.
            # Keep every other native field and let original handler/parser own interpretation.
            result=dict(result);result['items']=[r for r in result['items'] if not isinstance(r,dict) or r.get('id') not in hook.known|hook.details]
            return result
        async def detail(client,note_id,*args,**kwargs):
            require(isinstance(note_id,str) and re.fullmatch('[a-f0-9]{24}',note_id),'participant_note_invalid')
            require(note_id not in hook.known and note_id not in hook.details and len(hook.details)<hook.limit,'participant_detail_limit')
            await hook.guard('detail',note_id)
            hook.details.add(note_id)  # A charged attempt is never retried through this wrapper.
            return await original_detail(client,note_id,*args,**kwargs)
        self.originals=[(client_class,'get_note_by_keyword',original_search),(client_class,'get_note_by_id',original_detail)]
        client_class.get_note_by_keyword,client_class.get_note_by_id=search,detail
        return self
    def restore(self):
        for cls,name,original in reversed(self.originals):setattr(cls,name,original)
        self.originals=[]

def from_context(context,client_class,*,run=None,timeout_seconds=600):
    from participant_native_rpc import from_context as transport_from_context
    rpc=transport_from_context(context)
    journal=None
    if run is not None:
        from pathlib import Path
        from mc_runner import write
        journal=lambda value:write(Path(run)/'participant-pro-guard.json',value)
    return ParticipantNativeHooks(context,rpc,journal=journal,timeout_seconds=timeout_seconds).install(client_class)
