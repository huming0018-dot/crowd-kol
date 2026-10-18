"""Thin hooks around pinned Pro methods; no platform request/parser implementation."""
import inspect
import re
from participant_pro import ParticipantError, require

class ParticipantNativeHooks:
    def __init__(self,context,rpc):
        require(context.get('schema')=='crowd-participant-pro-local-v1','participant_context_invalid')
        self.context,self.rpc=context,rpc;self.authenticated=False;self.details=set();self.originals=[]
        self.known=set(context['known_ids']);self.limit=context['limit']
        require(type(self.limit) is int and 1<=self.limit<=100,'participant_context_invalid')
    async def identity(self,platform,uid):
        self.authenticated=False  # A failed re-check must revoke this run's prior proof.
        require(platform=='xhs' and isinstance(uid,str) and re.fullmatch('[a-f0-9]{24}',uid),'participant_principal_invalid')
        result=self.rpc('verify_platform_principal',{'uid':uid})
        if inspect.isawaitable(result):result=await result
        require(isinstance(result,dict) and result.get('matched') is True and result.get('installation_id')==self.context['installation_id'] and result.get('subject')==self.context['binding']['subject'],'participant_principal_mismatch')
        self.authenticated=True
    async def guard(self,action,note=None):
        if not self.authenticated:raise SystemExit(78)  # Native Exception handlers cannot retry without identity.
        c=self.context
        try:
            result=self.rpc('pro_guard',{'p_task':c['task_id'],'p_lease':c['lease'],'p_action':action,'p_note':note,'p_installation_id':c['installation_id']})
            if inspect.isawaitable(result):result=await result
        except Exception:
            raise SystemExit(86) from None  # Native handlers catch Exception; unknown must stop.
        if not isinstance(result,dict) or result.get('allowed') is not True or result.get('reason') is not None:
            raise SystemExit(74)  # No automatic source retry/fallback after a denied action.
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

def from_context(context,client_class):
    from participant_pro_transport import ParticipantProTransport
    rpc=ParticipantProTransport(**context['binding'],node=context['node'])
    return ParticipantNativeHooks(context,rpc).install(client_class)
