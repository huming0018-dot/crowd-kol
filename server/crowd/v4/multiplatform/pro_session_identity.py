"""Candidate-only fixed original-session scope; never an official user-ID proof.
Caller must explicitly choose this mode for a new bounded task. No production route
currently installs it. Existing UID verification and recovery guards stay intact.
"""
from urllib.parse import urlsplit
import json,re

class SessionScopeError(BaseException):
    reason='pro_original_session_scope_changed'

def _binding(value,platform):
    if type(value) is not dict or set(value)!={'platform','client_id','cookiebridge_url','sign_url'}:raise SessionScopeError()
    if value['platform']!=platform or type(value['client_id']) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,128}',value['client_id']):raise SessionScopeError()
    for key,port in [('cookiebridge_url',8274),('sign_url',8990)]:
        if type(value[key]) is not str:raise SessionScopeError()
        try:u=urlsplit(value[key]);observed_port=u.port
        except ValueError:raise SessionScopeError() from None
        if u.scheme!='http' or u.hostname!='127.0.0.1' or observed_port!=port or u.path not in ('','/') or u.query or u.fragment or u.username or u.password:raise SessionScopeError()
    return dict(value)

class OriginalSessionScope:
    """Read-only guard around existing stored login + explicitly pinned client.
    Does not authenticate, refresh verified_at, grant a run or prove same UID.
    """
    def __init__(self,store,session_id,platform,run_id,binding,read_binding,*,previous_pending_run_id):
        if platform not in ('dy','ks') or not callable(read_binding):raise SessionScopeError()
        self.store,self.sid,self.platform,self.run=store,session_id,platform,run_id
        self.bound=_binding(binding,platform);self.read_binding=read_binding;self.pending=previous_pending_run_id
        current=store.status(session_id,platform)
        self.context={k:current.get(k) for k in ('session_id','platform','generation','account_ref','pending_run_id','identity_status','state','login_verified','authorized_for_run','verified_at')}
        if (type(current.get('generation')) is not int or current['generation']<0 or current.get('state') not in ('authenticated','resumed')
                or current.get('identity_status') not in ('session_only_unverified','manually_confirmed_same_account')
                or current.get('login_verified') is not True or current.get('account_ref') is not None
                or current.get('pending_run_id')!=previous_pending_run_id):raise SessionScopeError()
        self.originals=None;self.validate()
    def validate(self):
        current=self.store.status(self.sid,self.platform)
        try:match=json.dumps({k:current.get(k) for k in self.context},sort_keys=True,allow_nan=False)==json.dumps(self.context,sort_keys=True,allow_nan=False)
        except (TypeError,ValueError):match=False
        if not match or _binding(self.read_binding(),self.platform)!=self.bound:raise SessionScopeError()
        return {'identity_basis':'fixed_original_session','official_uid_verified':False,'platform_login_currently_verified':False,
                'session_id':self.sid,'generation':self.context['generation'],'account_ref':None,'run_id':self.run}
    def observe_response(self,response):self.validate()
    def install(self,client_class,httpx_module):
        if self.originals is not None:raise SessionScopeError()
        pong,send=client_class.pong,httpx_module.AsyncClient.send;owner=self
        async def scoped_pong(client,*args,**kwargs):
            owner.validate()
            return True  # SDK initialization only; no private history or follower-list probe.
        async def scoped_send(client,*args,**kwargs):
            owner.validate()
            response=await send(client,*args,**kwargs)
            owner.validate()
            return response  # Check response-time context, including exact Bridge replies.
        client_class.pong=scoped_pong;httpx_module.AsyncClient.send=scoped_send
        self.originals=(client_class,httpx_module,pong,send);return self
    def restore(self):
        if self.originals:
            cls,httpx,pong,send=self.originals;cls.pong=pong;httpx.AsyncClient.send=send;self.originals=None
