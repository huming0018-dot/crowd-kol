"""Loopback-only XHS/DY wrapper around separately licensed pure local signers."""
import argparse,asyncio,hashlib,importlib.metadata,ipaddress,json,logging,os,re,signal,socket,sys,threading,time
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
HOST,PORT='127.0.0.1',8990
SOURCE_COMMIT='26c53d8f3221d95e0d4961b0593debd179d3cf10'
ERROR_REASONS={'signer_failed_no_retry','sign_budget_exhausted','invalid_local_sign_request',
               'request_origin_rejected','unsupported_sign_endpoint','native_signer_failed','sign_internal_error'}
sys.dont_write_bytecode=True

def verify_source(root):
    root=Path(root).resolve()
    manifest=json.loads((Path(__file__).parent/'SIGN-SOURCE-SHA.json').read_text())
    for name,digest in manifest.items():
        p=root/name
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            raise ValueError('sign_source_changed')
    return root

def allowed(request):
    return request.remote_ip in ('127.0.0.1','::1') and request.headers.get('Host') in (f'{HOST}:{PORT}',f'localhost:{PORT}') and request.headers.get('Origin') is None

class SignGate:
    def __init__(self):
        self.lock=asyncio.Lock();self.signs=0;self.failed=False
        self.first_error_reason=None;self.native_failure_reason=None;self.rejected_calls=0;self.on_error=None
    def record_error(self,reason):
        if not isinstance(reason,str) or reason not in ERROR_REASONS:reason='sign_internal_error'
        if self.first_error_reason is None:
            self.first_error_reason=reason
            if self.on_error is not None:
                try:self.on_error()
                except BaseException:pass  # Diagnostics cannot replace native/budget errors.
    def note_rejection(self,reason):
        self.rejected_calls+=1
        self.record_error(reason)
    def reject(self,reason):
        self.note_rejection(reason)
        raise ValueError(reason)
    async def sign(self,platform,native,signer,request):
        async with self.lock:
            if self.failed:self.reject('signer_failed_no_retry')
            if self.signs>=100:self.reject('sign_budget_exhausted')
            prefix=r'/api/sns/web/v[12]/' if platform=='xhs' else r'/aweme/v[12]/web/'
            if platform not in ('xhs','dy') or not isinstance(request.uri,str) or not re.match(prefix,request.uri) or len(request.uri)>16000 or not isinstance(request.cookies,str) or not request.cookies:
                self.reject('invalid_local_sign_request')
            # Cookie order/non-auth fields change; only the collector's official self
            # check and bound client can authorize account identity, never a signer.
            self.signs+=1
            try:return await native(signer,request,force_init=False)
            except BaseException:
                self.failed=True
                self.native_failure_reason='native_signer_failed'
                self.record_error(self.native_failure_reason)
                raise

def loopback(host):
    if host=='localhost':return True
    try:return ipaddress.ip_address(host).is_loopback
    except (ValueError,TypeError):return False

def deny_external_socket():
    # Python TCP/UDP/DNS guards; not an OS sandbox for native code or Node.
    original_connect=socket.socket.connect;original_ex=socket.socket.connect_ex
    original_sendto=socket.socket.sendto;original_getaddrinfo=socket.getaddrinfo
    original_send=socket.socket.send;original_sendall=socket.socket.sendall
    original_sendmsg=getattr(socket.socket,'sendmsg',None)
    def check(address):
        if not isinstance(address,tuple) or not loopback(address[0]):raise OSError('sign_external_request_denied')
    def peer(sock):
        if sock.family!=socket.AF_UNIX:check(sock.getpeername())
    def connect(sock,address):check(address);return original_connect(sock,address)
    def connect_ex(sock,address):check(address);return original_ex(sock,address)
    def sendto(sock,data,*args):
        if not args:raise OSError('sign_external_request_denied')
        check(args[-1]);return original_sendto(sock,data,*args)
    def send(sock,*args):peer(sock);return original_send(sock,*args)
    def sendall(sock,*args):peer(sock);return original_sendall(sock,*args)
    def sendmsg(sock,buffers,ancdata=(),flags=0,address=None):
        if address is not None:check(address)
        else:peer(sock)
        return original_sendmsg(sock,buffers,ancdata,flags,address) if address is not None else original_sendmsg(sock,buffers,ancdata,flags)
    def getaddrinfo(host,port,family=0,type=0,proto=0,flags=0):
        if not loopback(host):raise OSError('sign_external_request_denied')
        host='127.0.0.1' if host=='localhost' else host
        return original_getaddrinfo(host,port,family,type,proto,flags|socket.AI_NUMERICHOST)
    def gethostbyname(host):
        if not loopback(host):raise OSError('sign_external_request_denied')
        return '127.0.0.1' if host=='localhost' else str(host)
    def gethostbyname_ex(host):return (host,[],[gethostbyname(host)])
    def gethostbyaddr(host):return (gethostbyname(host),[],[gethostbyname(host)])
    original_getnameinfo=socket.getnameinfo
    def getnameinfo(address,flags):
        check(address);return original_getnameinfo(address,flags|socket.NI_NUMERICHOST|socket.NI_NUMERICSERV)
    socket.socket.connect=connect;socket.socket.connect_ex=connect_ex
    socket.socket.sendto=sendto;socket.socket.send=send;socket.socket.sendall=sendall
    if original_sendmsg:socket.socket.sendmsg=sendmsg
    socket.getaddrinfo=getaddrinfo;socket.gethostbyname=gethostbyname
    socket.gethostbyname_ex=gethostbyname_ex;socket.gethostbyaddr=gethostbyaddr;socket.getnameinfo=getnameinfo

def clean_node_environment():
    for key in list(os.environ):
        if key.startswith(('NODE_','DYLD_')) or key in ('LD_PRELOAD','LD_LIBRARY_PATH','BASH_ENV','ENV'):
            os.environ.pop(key,None)
    os.environ['EXECJS_RUNTIME']='Node'

async def build_application(root):
    if sys.version_info[:2]!=(3,12):raise ValueError('sign_requires_python312')
    for name,version in json.loads((Path(__file__).parent/'DEPENDENCIES.json').read_text()).items():
        if importlib.metadata.version(name)!=version:raise ValueError('sign_dependency_mismatch')
    for item in json.loads((Path(__file__).parent/'DEPENDENCY-SHA.json').read_text()):
        distribution=importlib.metadata.distribution(item['distribution'])
        path=Path(distribution.locate_file(item['file']))
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('sign_dependency_changed')
    clean_node_environment()
    node=json.loads((Path(__file__).parent/'NODE-SHA.json').read_text())
    node_path=Path(node['path'])
    if not node_path.is_file() or hashlib.sha256(node_path.read_bytes()).hexdigest()!=node['sha256']:raise ValueError('sign_node_changed')
    os.environ['PATH']=str(node_path.parent)+os.pathsep+os.environ.get('PATH','')
    root=verify_source(root)
    for name in ('config','apis.xiaohongshu','apis.douyin'):
        module=sys.modules.get(name)
        if module and not Path(module.__file__).resolve().is_relative_to(root):raise ValueError('sign_module_collision')
    deny_external_socket();sys.path.insert(0,str(root));os.chdir(root);logging.disable(logging.CRITICAL)
    import config
    config.IS_DEBUG=False;config.sign_type='javascript'
    os.environ['EXECJS_RUNTIME']='Node'
    import tornado.web
    from apis.base_handler import PongHandler
    import apis.xiaohongshu as xhs
    import apis.douyin as dy
    from logic.xhs.xhs_logic import XhsJavascriptSign
    from logic.douyin.douyin_logic import DouyinJavascriptSign
    gate=SignGate();xsign=XhsJavascriptSign();dsign=DouyinJavascriptSign()
    async def xs(req):return await gate.sign('xhs',XhsJavascriptSign.sign.__wrapped__,xsign,req)
    async def ds(req):return await gate.sign('dy',DouyinJavascriptSign.sign.__wrapped__,dsign,req)
    xhs.xhs_sign_logic.sign=xs;dy.dy_sign_logic.sign=ds
    class Local:
        def prepare(self):
            if not allowed(self.request):
                gate.note_rejection('request_origin_rejected')
                raise tornado.web.HTTPError(403)
            return super().prepare()
        def set_default_headers(self):
            self.set_header('Cache-Control','no-store');self.set_header('X-Content-Type-Options','nosniff')
        def options(self):raise tornado.web.HTTPError(403)
        def write_error(self,status_code,**kwargs):self.finish({'error':'sign_request_failed','status':status_code})
        def log_exception(self,*args):pass
        def return_error(self,errorcode,extra=None):return super().return_error(errorcode,extra={})
        def return_error_info(self,errorcode,errmsg,extra=None):return super().return_error_info(errorcode,'sign_failed',extra={})
        def return_error_with_extra_msg(self,errorcode,errmsg,extra=None):return super().return_error_with_extra_msg(errorcode,'sign_failed',extra={})
    class Missing(tornado.web.RequestHandler):
        def prepare(self):
            gate.note_rejection('unsupported_sign_endpoint')
            raise tornado.web.HTTPError(404 if allowed(self.request) else 403)
    app=tornado.web.Application([(r'/signsrv/pong',type('LocalPong',(Local,PongHandler),{})),(r'/signsrv/v1/xhs/sign',type('LocalXhs',(Local,xhs.XhsSignHandler),{})),(r'/signsrv/v1/douyin/sign',type('LocalDy',(Local,dy.DouyinSignHandler),{}))],debug=False,autoreload=False,default_handler_class=type('LocalMissing',(Local,Missing),{}),log_function=lambda _:None)
    app.sign_gate=gate
    return app

def lifecycle_file(path):
    p=Path(path).expanduser()
    if not p.is_absolute() or any(x.is_symlink() for x in (p,*p.parents)):raise ValueError('unsafe_lifecycle')
    return os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)

def event(fd,name,app=None):
    row={'schema':'crowd-signsrv-local-v1','event':name,'pid':os.getpid(),'host':HOST,'port':PORT,'platforms':['xhs','dy'],'source_commit':SOURCE_COMMIT,'source_requests':0,'browser_started':False,'sign_count':app.sign_gate.signs if app else 0,'failed':app.sign_gate.failed if app else True}
    if app:
        row.update(first_error_reason=app.sign_gate.first_error_reason,
                   native_failure_reason=app.sign_gate.native_failure_reason,rejected_calls=app.sign_gate.rejected_calls)
    os.write(fd,(json.dumps(row,sort_keys=True)+'\n').encode());os.fsync(fd)

async def serve(app,fd):
    import tornado.httpserver
    listener=tornado.httpserver.HTTPServer(app,xheaders=False,max_body_size=128*1024,max_buffer_size=256*1024)
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    app.sign_gate.on_error=lambda:event(fd,'sign_error',app)
    for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,stop.set)
    try:
        listener.listen(PORT,address=HOST);event(fd,'started',app)
        await stop.wait()
    finally:
        listener.stop();await listener.close_all_connections()
        for sig in (signal.SIGTERM,signal.SIGINT):loop.remove_signal_handler(sig)
        event(fd,'stopped',app)

def main():
    parent=os.environ.get('CROWD_SIGNER_PARENT_PID')
    if parent is not None:
        if not parent.isdecimal() or int(parent)!=os.getppid():raise ValueError('sign_parent_changed')
        lifetime=float(os.environ.get('CROWD_SIGNER_MAX_SECONDS','0'))
        if not 0<lifetime<=7210:raise ValueError('invalid_sign_lifetime')
        deadline=time.monotonic()+lifetime
        def watch_parent():
            while os.getppid()==int(parent) and time.monotonic()<deadline:time.sleep(.25)
            os.kill(os.getpid(),signal.SIGTERM)
        threading.Thread(target=watch_parent,daemon=True).start()
    p=argparse.ArgumentParser();p.add_argument('--source-root',required=True);p.add_argument('--serve',action='store_true');p.add_argument('--lifecycle');a=p.parse_args();fd=None;app=None
    try:
        if a.serve:
            if not a.lifecycle:raise ValueError('lifecycle_required')
            fd=lifecycle_file(a.lifecycle)
        with open(os.devnull,'w') as sink,redirect_stdout(sink),redirect_stderr(sink):
            async def run():
                nonlocal app
                app=await build_application(a.source_root)
                if a.serve:await serve(app,fd)
            asyncio.run(run())
        if not a.serve:print(json.dumps({'ok':True,'validate_only':True,'listening':False,'source_requests':0,'browser_started':False,'platforms':['xhs','dy']}))
        return 0
    except Exception:
        if fd is not None:event(fd,'runtime_failed',app)
        print(json.dumps({'ok':False,'error':'sign_runtime_unavailable'}));return 2
    finally:
        if fd is not None:os.close(fd)
if __name__=='__main__':raise SystemExit(main())
