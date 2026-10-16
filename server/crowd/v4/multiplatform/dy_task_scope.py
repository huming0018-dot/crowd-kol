"""Finite Owner admission for the independently replayed Pro hot-search slice."""
CAPABILITY='pro_dy_trending_v1'
def supports(r):
 return (type(r) is dict and r.get('platform')=='dy' and r.get('source_executor')=='pro'
  and r.get('mode')=='trending' and r.get('targets',[])==[]
  and type(r.get('max_items')) is int and r['max_items']==1
  and type(r.get('max_comments')) is int and r['max_comments']==3
  and all(r.get(k) is True for k in ('comments','replies','media'))
  and r.get('wordcloud',False) is False and r.get('platform_options',{})=={}
  and type(r.get('max_api_requests')) is int and 1<=r['max_api_requests']<=12
  and type(r.get('timeout_seconds')) is int and 30<=r['timeout_seconds']<=120
  and r.get('start_page',1)==1 and type(r.get('start_page',1)) is int
  and type(r.get('interval_seconds',0)) is int and r.get('interval_seconds',0)==0)
def owner_scope(p):
 return (type(p) is dict and type(p.get('platform_options_by_platform',{})) is dict
  and type(p.get('session_by_platform',{})) is dict and p.get('platforms')==['dy'] and supports({
  **p,'platform':'dy','targets':p.get('targets',[]),'max_items':p.get('desired_items'),
  'platform_options':p.get('platform_options_by_platform',{}).get('dy',{})})
  and not p.get('targets_by_platform') and not p.get('targets'))
def ready(app,p):
 if not owner_scope(p):raise ValueError('pro_dy_scope_unsupported')
 from account_sessions import AccountSessions
 from pro_executor import task_installation,binding_for
 from managed_pro_signer import private_object,SignerError
 from mc_runner import BridgeError
 sid=app._cloud_session({'platform':'dy'})
 if p.get('session_by_platform',{}).get('dy',sid)!=sid:raise ValueError('pro_session_identity_unverified')
 roots=[root for root in app._roots() if (root/'sessions'/sid).is_dir()]
 if len(roots)!=1:raise ValueError('collector_session_ambiguous')
 root=roots[0];request={'platform':'dy','source_executor':'pro','session_id':sid}
 try:
  task_installation(root,request);binding_for(root,request)
  descriptor=private_object(root/'pro-signer.json')
 except (BridgeError,SignerError) as error:raise ValueError(str(error)) from None
 from pathlib import Path
 if (set(descriptor)!={'python','source_root'} or any(type(v) is not str for v in descriptor.values())
     or not Path(descriptor['python']).is_absolute() or not Path(descriptor['python']).is_file()
     or not Path(descriptor['source_root']).is_absolute() or not Path(descriptor['source_root']).is_dir()):
  raise ValueError('pro_signer_installation_invalid')
 # Identity is still checked atomically by OriginalSessionScope at execution.
 state=AccountSessions(root).status(sid,'dy')
 if state.get('identity_status')!='manually_confirmed_same_account':raise ValueError('pro_session_identity_unverified')
 return [CAPABILITY]
