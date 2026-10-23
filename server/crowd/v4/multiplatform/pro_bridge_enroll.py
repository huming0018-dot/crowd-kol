"""First local Bridge session verification through the original Pro pong/hooks.
Only an explicit fresh SID is registered. No existing identity is copied or
principal seeded; only a real official self response may authenticate it.
The one-shot operator is not a collector, login bypass or cross-device service.
"""
from pathlib import Path
from urllib.parse import urlsplit,urlencode
import argparse,asyncio,contextlib,fcntl,io,json,os,re,sys,uuid
from install_machine_node import need,private,write_once,encode

class SelfOnlyGate:
    def __init__(self,bound):self.bound=bound;self.counts={k:0 for k in ('bridge','health','signer','official_self')}
    def authorize(self,method,url,body):
        u=urlsplit(str(url));need(not u.username and not u.password and not u.fragment,'enrollment_endpoint_forbidden')
        expected=self.bound['cookiebridge_url']+'/api/cookies/xhs?'+urlencode({'client_id':self.bound['client_id']})
        kind='bridge'if method=='GET'and str(url)==expected else 'health'if method=='GET'and str(url)==self.bound['sign_url']+'/signsrv/pong' else 'signer'if method=='POST'and str(url)==self.bound['sign_url']+'/signsrv/v1/xhs/sign'else 'official_self'if method=='GET'and str(url)=='https://edith.xiaohongshu.com/api/sns/web/v2/user/me'else None
        need(kind is not None and self.counts[kind]==0,'enrollment_endpoint_forbidden')
        if kind=='health':need(self.counts['bridge']==1,'enrollment_sequence_changed')
        if kind=='signer':
            need(self.counts['bridge']==1 and self.counts['health']==1 and len(body)<=65536,'enrollment_sequence_changed');value=json.loads(body);need(type(value)is dict and value.get('uri')=='/api/sns/web/v2/user/me'and value.get('data')is None,'enrollment_endpoint_forbidden')
        if kind=='official_self':need(self.counts['signer']==1,'enrollment_sequence_changed')
        self.counts[kind]+=1;return kind
    def complete(self):return all(count==1 for count in self.counts.values())

def register(root,sid,bound):
    root=Path(root);need(str(uuid.UUID(sid))==sid and set(bound)=={'platform','client_id','cookiebridge_url','sign_url'}and bound['platform']=='xhs'and bound['cookiebridge_url']=='http://127.0.0.1:8274'and bound['sign_url']=='http://127.0.0.1:8990','enrollment_binding_invalid')
    need(type(bound['client_id'])is str and re.fullmatch('[A-Za-z0-9_-]{1,128}',bound['client_id'])is not None,'enrollment_binding_invalid');session=root/'sessions'/sid
    need(not session.exists()and not session.is_symlink()and not(root/'accounts'/sid).exists(),'fresh_session_required')
    session.mkdir(mode=0o700);write_once(session/'identity.json',encode({'platform':'xhs'}));write_once(session/'pro-binding.json',encode(bound))
    return session

class Quiet(io.TextIOBase):
    def write(self,value):return len(value)
    def flush(self):pass

async def verify(root,sid,bound,installed,operation):
    from account_sessions import AccountSessions
    from pro_account_sessions import install_pro_account_hooks
    store=AccountSessions(root);before=store.status(sid,'xhs');need(before.get('generation')==0 and before.get('account_ref')is None,'fresh_session_required')
    sys.path.insert(0,installed['root']);os.environ['ENABLE_LOG_FILE']='false'
    with contextlib.redirect_stdout(Quiet()),contextlib.redirect_stderr(Quiet()):
        import config,httpx
        from pkg.tools import utils
        config.ENABLE_LOG_FILE=False;config.SIGN_SRV_HOST='127.0.0.1';config.SIGN_SRV_PORT='8990';utils.logger.remove()
        from pkg.account_pool.pool import AccountPoolManager,AccountWithIpPoolManager
        from pkg.rpc.sign_srv_client import SignServerClient
        from media_platform.xhs.client import XiaoHongShuClient
        from pro_executor import install_bound_account
        old_init,old_send=httpx.AsyncClient.__init__,httpx.AsyncClient.send;old_loader=AccountPoolManager.load_accounts_from_cookie_bridge;old_rpc=SignServerClient.request;gate=SelfOnlyGate(bound)
        def init(client,*args,**kwargs):
            need(kwargs.get('proxy')is None and kwargs.get('proxies')is None,'enrollment_endpoint_forbidden');kwargs.update(trust_env=False,follow_redirects=False,timeout=10,transport=httpx.AsyncHTTPTransport(retries=0,trust_env=False));return old_init(client,*args,**kwargs)
        async def send(client,request,*args,**kwargs):
            gate.authorize(request.method,str(request.url),request.content);kwargs.update(follow_redirects=False,stream=True);response=await old_send(client,request,*args,**kwargs)
            try:
                need(not 300<=response.status_code<400,'enrollment_redirect_forbidden');body=bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk);need(len(body)<=262144,'enrollment_response_too_large')
                response._content=bytes(body)
            finally:await response.aclose()
            return response
        async def rpc(client,method,uri,**kwargs):
            need((method=='GET'and uri=='/signsrv/pong'and not kwargs)or(method=='POST'and uri=='/signsrv/v1/xhs/sign'and set(kwargs)=={'json'}),'enrollment_endpoint_forbidden')
            async with httpx.AsyncClient()as session:
                response=await session.request(method,bound['sign_url']+uri,**kwargs);need(response.status_code==200,'enrollment_signer_unavailable');return response.json()
        httpx.AsyncClient.__init__,httpx.AsyncClient.send=init,send;SignServerClient.request=rpc;hook=None
        try:
            install_bound_account(AccountPoolManager,bound,'xhs',httpx)
            hook=install_pro_account_hooks(root,sid,'xhs',operation,lambda *_:None,httpx,XiaoHongShuClient)
            pool=AccountWithIpPoolManager('xhs','cookie_bridge',proxy_ip_pool=None);await pool.load_accounts_from_cookie_bridge();client=XiaoHongShuClient(account_with_ip_pool=pool);client.account_info=await pool.get_account_with_ip_info();result=await client.pong();need(result is True and gate.complete(),'enrollment_official_self_unverified')
        finally:
            if hook is not None:hook.restore()
            httpx.AsyncClient.__init__,httpx.AsyncClient.send=old_init,old_send;SignServerClient.request=old_rpc;AccountPoolManager.load_accounts_from_cookie_bridge=old_loader
    after=store.status(sid,'xhs');need(after.get('identity_status')=='authenticated_self_id'and after.get('state')=='authenticated'and after.get('generation')==1 and after.get('login_verified')is True and after.get('account_ref')is not None,'enrollment_official_self_unverified')
    return {'state':'authenticated','identity_basis':'original_pro_official_self','generation':1,'requests':gate.counts,'source_collection_started':False,'browser_started':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--plan-sha256',required=True);args=parser.parse_args()
    from install_machine_node import sha
    raw=private(args.plan);need(sha(raw)==args.plan_sha256,'enrollment_plan_changed');plan=json.loads(raw);need(set(plan)=={'schema','collector_root','session_id','binding'}and plan['schema']=='crowd-pro-bridge-enrollment-v1','enrollment_plan_invalid')
    root=Path(plan['collector_root']);sid=plan['session_id'];bound=plan['binding'];base=root/'enrollments';base.mkdir(mode=0o700,exist_ok=True);intent=base/(sid+'.json');write_once(intent,encode({'state':'attempted_no_retry','schema':plan['schema'],'session_id':sid,'plan_sha256':args.plan_sha256}))
    register(root,sid,bound)
    from pro_executor import task_installation,probe
    installed=task_installation(root,{'source_executor':'pro'});probe(installed['root'],installed['python'])
    operation=str(uuid.uuid4());run=root/'runs'/operation;run.mkdir(mode=0o700);write_once(run/'COMPONENT.json',encode({'kind':'account_enrollment','source_collection_started':False,'not_a_task':True}))
    from managed_pro_signer import owned_signer
    fd=os.open(root/'sessions'/sid/'active.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with owned_signer(run,{'platform':'xhs','timeout_seconds':45},bound):result=asyncio.run(asyncio.wait_for(verify(root,sid,bound,installed,operation),timeout=40))
        write_once(base/(sid+'.RESULT.json'),encode(result));print(json.dumps(result));return 0
    except BaseException:
        # The permanent intent prevents unknown replays; no error text or response.
        print(json.dumps({'state':'verification_failed_or_unknown','source_collection_started':False}));return 2
    finally:os.close(fd)
if __name__=='__main__':raise SystemExit(main())
