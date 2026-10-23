"""Offline original KS Client/Extractor/handler/SQLite fixture entry (not real auth).

  CROWD_KS_SDK=<licensed-SDK-root> <existing-Pro-Python> -B probe_pro_ks_sdk.py
  G61_SCENARIO=missing_cursor|stop|identity|self_pending <same command>
The fixture defaults to own fixtures/pro-ks-saved-fixture.json. Optional
CROWD_KS_SAVED_FIXTURE is an explicit test-only input. Optional
CROWD_KS_ARTIFACT_DIR must be a new temporary output directory. No private SDK,
credentials or user path is bundled; socket/getaddrinfo denied. This explicit
probe is outside unittest auto-discovery. Missing SDK/input fails, never skips.
The synthetic principal/state in this temporary test is not production login.
"""
import asyncio,copy,hashlib,io,json,os,sqlite3,sys,tempfile,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
HERE=Path(__file__).resolve().parent;SDK=Path(os.environ['CROWD_KS_SDK']);MP=HERE;sys.path[:0]=[str(HERE),str(SDK)]
sys.addaudithook(lambda event,args:(_ for _ in ()).throw(RuntimeError('NETWORK_FORBIDDEN'))if event in('socket.connect','socket.getaddrinfo')else None)
import config,httpx,acquisition_protocol
from async_db import AsyncSQLiteDB
from var import media_crawler_db_var
from media_platform.kuaishou.client import KuaiShouApiClient
from media_platform.kuaishou.graphql import KuaiShouGraphQL
from media_platform.kuaishou.extractor import KuaishouExtractor
from media_platform.kuaishou.handlers.detail_handler import DetailHandler
from media_platform.kuaishou.processors.video_processor import VideoProcessor
from media_platform.kuaishou.processors.comment_processor import CommentProcessor
from constant.kuaishou import KUAISHOU_COMMENT_LIST_V2,KUAISHOU_SUB_COMMENT_LIST_V2
from repo.checkpoint.checkpoint_store import CheckpointRepoManager,CheckpointJsonFileRepo
import pro_executor as executor,pro_ks_entry as entry,mc_runner
from mc_source_steps import NativeSteps
from shared_request_budget import RunRequestBudget,request_fingerprint
from results_store import ResultsStore
RAW=json.loads(Path(os.environ.get('CROWD_KS_SAVED_FIXTURE',HERE/'fixtures/pro-ks-saved-fixture.json')).read_text());VID=RAW['video_id'];SCENARIO=os.environ.get('G61_SCENARIO','normal')
class Client(KuaiShouApiClient):
 def __init__(self):
  self.timeout=10;self._extractor=KuaishouExtractor();self._graphql=KuaiShouGraphQL.__new__(KuaiShouGraphQL);self._graphql.graphql_dir=str(SDK/'media_platform/kuaishou/graphql')+'/';self._graphql.load_graphql_queries();self.account_info=SimpleNamespace(ip_info=None,account=SimpleNamespace(cookies='synthetic-fixture-no-real-credentials'));self.account_with_ip_pool=None
class Sink:
 def __init__(self,run,manifest):self.run=run;self.manifest=manifest;self.attempts=0;self.updates=[]
 def update(self,**fields):self.updates.append(fields)
async def main():
 with tempfile.TemporaryDirectory(prefix='g61-ks-entry-')as temp:
  root=Path(temp).resolve();runid=str(uuid.uuid4());sid=str(uuid.uuid4());run=root/'runs'/runid;run.mkdir(parents=True);os.chdir(run);os.environ['VOX_ACQUISITION_ID']=runid
  request={'source_executor':'pro','platform':'ks','mode':'detail','targets':[VID],'max_items':1,'max_comments':0,'comments':True,'replies':True,'media':False,'wordcloud':False,'platform_options':{},'session_id':sid,'max_api_requests':5,'timeout_seconds':60,'start_page':1,'interval_seconds':0};manifest={'run_id':runid,'request':request};mc_runner.write(run/'manifest.json',manifest)
  session=root/'sessions'/sid;session.mkdir(parents=True);mc_runner.write(session/'identity.json',{'platform':'ks'});state=root/'accounts'/sid/'state.json';state.parent.mkdir(parents=True);baseline={'session_id':sid,'platform':'ks','generation':1,'account_ref':'a'*64,'state':'authenticated','authorized_for_run':runid,'identity_status':'synthetic_fixture_only'};mc_runner.write(state,baseline)
  assert executor.explicit_unsupported(request)is None and 'ks'not in executor.SUPPORTED
  selected=executor.selection(request,{},installation={'root':str(SDK),'python':sys.executable});assert selected['backend']=='pro'
  config.SAVE_DATA_OPTION='db';config.DB_TYPE='sqlite';config.CRAWLER_TIME_SLEEP=0;config.ENABLE_CHECKPOINT=True;config.SPECIFIED_CHECKPOINT_ID=runid;config.ENABLE_GET_COMMENTS=True;config.ENABLE_GET_SUB_COMMENTS=True;config.KS_SPECIFIED_ID_LIST=[VID]
  dbpath=run/executor.DB_NAME
  with sqlite3.connect(dbpath)as db:db.executescript((SDK/'schema/sqlite_tables.sql').read_text())
  db=AsyncSQLiteDB(str(dbpath));await db.connect();media_crawler_db_var.set(db);entry.register_observations(acquisition_protocol);await acquisition_protocol.initialize(db)
  calls=[]
  async def response(req):
   data=json.loads(req.content);assert req.url.scheme=='https' and req.url.host=='www.kuaishou.com'
   if req.url.path=='/graphql':
    assert data['operationName']=='visionVideoDetail'and data['variables']['photoId']==VID;raw={'data':copy.deepcopy(RAW['detail'])};kind='detail'
   else:
    assert data['photoId']==VID;kind='reply'if 'rootCommentId'in data else'root';assert req.url.path==(KUAISHOU_SUB_COMMENT_LIST_V2 if kind=='reply'else KUAISHOU_COMMENT_LIST_V2)
    page=next(p for p in RAW['pages']if p['kind']==kind and p['cursor']==data['pcursor']);raw={'result':1,**copy.deepcopy(page['raw'])}
    if SCENARIO=='missing_cursor'and kind=='root':raw.pop('pcursorV2')
   calls.append(kind)
   if SCENARIO=='stop'and kind=='detail':(run/'stop').touch()
   if SCENARIO=='identity'and kind=='detail':mc_runner.write(state,{**baseline,'generation':2})
   return httpx.Response(200,json=raw,request=req)
  original_init=httpx.AsyncClient.__init__
  def local_init(self,*args,**kwargs):kwargs['transport']=httpx.MockTransport(response);original_init(self,*args,**kwargs)
  original_methods=(httpx.AsyncClient.send,httpx.Client.send,httpx.Response.aiter_bytes)
  sink=Sink(run,manifest);steps=NativeSteps(run,runid,'ks');hook=None
  try:
   with patch.object(httpx.AsyncClient,'__init__',local_init):
    executor.install_transport_limits(httpx,request,sink,native_steps=steps)
    client=Client();manager=CheckpointRepoManager(CheckpointJsonFileRepo(str(run/'data/checkpoints')));handler=DetailHandler(client,manager,VideoProcessor(client,manager,asyncio.Semaphore(1)),CommentProcessor(client,manager,asyncio.Semaphore(1)))
    if SCENARIO=='self_pending':
     from pro_account_sessions import install_pro_account_hooks
     identity=install_pro_account_hooks(root,sid,'ks',runid,lambda *args:None,httpx,Client)
     try:
      try:await client.pong()
      except SystemExit as error:assert error.code==77
      else:raise AssertionError('unsupported self unexpectedly authorized')
      assert calls==[]and not(run/'ks-evidence.json').exists();print(json.dumps({'status':'PASS_KS_SELF_PENDING_FAILCLOSED','platform_HTTP':0,'real_identity_proved':False}));return
     finally:identity.restore()
    hook=entry.install_detail(run,manifest,executor,DetailHandler,Client)
    try:
     with patch('random.uniform',return_value=0),patch('media_platform.kuaishou.processors.comment_processor.PER_NOTE_MAX_COMMENTS_COUNT',0):await handler.handle()
    except (entry.KuaishouStop,ValueError)as error:
     assert SCENARIO in('stop','identity','missing_cursor'),str(error)
     assert not(run/'ks-task-scope.json').exists()and entry.summary(run,manifest,executor)['coverage']=='unknown'
     if SCENARIO in('stop','identity'):assert calls==['detail']
     print(json.dumps({'status':'PASS_PARTIAL_REFUSED','scenario':SCENARIO,'fixed_error':str(error),'fixture_http_calls':len(calls),'cloud_ack':False}));return
    assert SCENARIO=='normal'
    scope,projection=entry.read_scope(run,manifest,executor);records,media,evidence=executor.import_records(run,manifest);completion=executor.completion(run,manifest,None)
    assert len(records)==5 and records==projection['records']and media==[]and evidence['executor']=='mediacrawler_pro'and evidence['local_committed']is True and evidence['cloud_ack']is False
    assert completion['content_count']==1 and completion['comment_count']==4 and completion['cloud_ack']is False and completion['coverage']=='exhausted'
    assert executor.pagination_summary(run,manifest)['coverage']=='exhausted'
    assert len(calls)==5 and sink.attempts==5 and RunRequestBudget(run/'request-budget.json',runid,request_fingerprint(request),5).snapshot()['used']==5
    # Same existing budget rejects a sixth attempt before fixture HTTP; no new request.
    try:
     async with httpx.AsyncClient()as c:await c.post('https://www.kuaishou.com/graphql',json={})
    except SystemExit as error:assert error.code==73
    else:raise AssertionError('budget overflow accepted')
    assert len(calls)==5
    store=ResultsStore(root/'exports');store.ingest({'run_id':runid,'records':records,'media':media,'source':evidence});packages={f:store.export(f)for f in('json','jsonl','csv','xlsx')};assert all(v['row_count']==5 for v in packages.values())
    content=next(x for x in json.loads(packages['json']['data'])['items']if x['kind']=='content');assert content['raw_caption']['text']==RAW['detail']['visionVideoDetail']['photo']['caption']and len(content['media_references'])==2
    if os.environ.get('CROWD_KS_ARTIFACT_DIR'):
     destination=Path(os.environ['CROWD_KS_ARTIFACT_DIR']);destination.mkdir(mode=0o700,exist_ok=False)
     for name,value in [('normalized',{'records':records,'media':media,'source':evidence}),('scope',scope)]:
      path=destination/(name+'.json');path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True));path.chmod(0o600)
     for fmt,value in packages.items():
      path=destination/('results.'+fmt);path.write_bytes(value['data']);path.chmod(0o600)
    before=len(calls)
    try:await handler.handle()
    except entry.KuaishouStop as error:assert error.reason=='ks_existing_capture_requires_reconciliation'
    else:raise AssertionError('existing capture source repeated')
    assert len(calls)==before
    print(json.dumps({'status':'PASS_REAL_SDK_PRO_ENTRY_BUDGET_ACCOUNT_PROTOCOL_SCOPE_IMPORT_RESULTS','rows':len(records),'fixture_http_calls':len(calls),'shared_budget_used':sink.attempts,'pro_observation_rows':len(executor.observations(run,manifest)),'original_global_checkpoint_unchanged':executor.checkpoint(run,manifest)['acquisition_committed']is False,'formats':{f:{'rows':v['row_count'],'sha256':v['sha256']}for f,v in packages.items()},'actual_platform_requests':0,'cloud_ack':False,'identity_fixture_not_real_authentication':True}))
  finally:
   if hook:hook.restore()
   httpx.AsyncClient.send,httpx.Client.send,httpx.Response.aiter_bytes=original_methods;await db.close()
asyncio.run(main())
