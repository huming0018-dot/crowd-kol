import unittest,tempfile,json,sys,uuid,copy,ast,asyncio
from pathlib import Path
from types import SimpleNamespace
H=Path(__file__).resolve().parent;sys.path.insert(0,str(H));import account_sessions as m
class BoundBiliTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.sid=str(uuid.uuid4());self.session=self.root/'sessions'/self.sid;self.profile=self.session/'browser_data/bili_bridge_profile';self.profile.mkdir(parents=True);self.binding=self.session/'pro-binding.json';self.good={'platform':'bili','client_id':'original-bili-client','cookiebridge_url':'http://127.0.0.1:8274','sign_url':'http://127.0.0.1:8990'};self.binding.write_text(json.dumps(self.good));self.original_binding=self.binding.read_bytes()
 def tearDown(self):self.tmp.cleanup()
 def options(self,**delta):
  args={'root':self.root,'session_id':self.sid,'platform':'bili','browser_name':'chromium','user_data_dir':self.profile,'options':{'headless':False,'args':['--old-flag'],'ignore_default_args':['--mute-audio']}};args.update(delta);old=copy.deepcopy(args['options']);result=m._preserve_bound_xhs_bridge(**args);self.assertEqual(args['options'],old);return result
 def unchanged(self,**delta):self.assertEqual(self.options(**delta)['ignore_default_args'],['--mute-audio'])
 def test_exact_original_bili_enables_only_existing_extensions(self):
  self.assertEqual(self.options(),{'headless':False,'args':['--old-flag'],'ignore_default_args':['--mute-audio','--disable-extensions']});self.assertEqual(self.binding.read_bytes(),self.original_binding);self.assertEqual(list(self.profile.iterdir()),[])
 def test_missing_binding_keeps_default(self):self.binding.unlink();self.unchanged()
 def test_wrong_platform_browser_or_profile_keeps_default(self):
  for delta in [{'platform':'xhs'},{'platform':'wb'},{'browser_name':'firefox'},{'user_data_dir':self.profile.parent},{'user_data_dir':self.profile.with_name('xhs_bridge_profile')},{'session_id':'bad'}]:self.unchanged(**delta)
 def test_mismatched_binding_and_extra_fields_keeps_default(self):
  for value in [[],None,{},dict(self.good,platform='xhs'),dict(self.good,client_id='bad secret'),dict(self.good,extra=True)]:self.binding.write_text(json.dumps(value));self.unchanged()
 def test_service_url_types_and_nonloopback_rejected(self):
  for key in ('cookiebridge_url','sign_url'):
   for bad in [None,True,False,[],{},7,'https://127.0.0.1:8274','http://evil.test:8274','http://user:pass@127.0.0.1:8274','http://127.0.0.1:8274/path','http://127.0.0.1:8274/?query=1']:
    self.binding.write_text(json.dumps({**self.good,key:bad}));self.unchanged()
 def test_binding_symlink_rejected(self):
  real=self.binding.with_suffix('.real');self.binding.rename(real);self.binding.symlink_to(real);self.unchanged()
 def test_profile_symlink_rejected(self):
  real=self.profile.with_name('old');self.profile.rename(real);self.profile.symlink_to(real,target_is_directory=True);self.unchanged()
 def test_profile_parent_symlink_rejected(self):
  parent=self.profile.parent;real=parent.with_name('other');parent.rename(real);parent.symlink_to(real,target_is_directory=True);self.unchanged()
 def test_oversized_binding_and_invalid_ignore_args_keeps_default(self):
  self.binding.write_text(' '*16385);self.unchanged();self.binding.write_text(json.dumps(self.good))
  for invalid in [True,False,None,{},['--existing',1]]:
   options={'ignore_default_args':invalid};self.assertEqual(self.options(options=options),options)
 def test_exact_worker_wrapper_positional_and_keyword_without_launch(self):
  node=next(x for x in ast.walk(ast.parse((H/'account_sessions.py').read_text())) if isinstance(x,ast.AsyncFunctionDef) and x.name=='persistent');calls=[]
  async def original(browser,*a,**kw):calls.append((a,kw));return 'fake-context-no-browser'
  scope={'original':original,'Path':Path,'args':SimpleNamespace(root=self.root,session_id=self.sid,platform='bili'),'_preserve_bound_xhs_bridge':m._preserve_bound_xhs_bridge};exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'actual_worker_persistent','exec'),scope);browser=SimpleNamespace(name='chromium',executable_path='/usr/bin/true')
  for kwargs,args in [({},[str(self.profile)]),({'user_data_dir':str(self.profile)},[])]:self.assertEqual(asyncio.run(scope['persistent'](browser,*args,**kwargs)),'fake-context-no-browser')
  self.assertEqual(len(calls),2);self.assertTrue(all(row[1]['ignore_default_args']==['--disable-extensions'] for row in calls));self.assertTrue(all('args' not in row[1] for row in calls));self.assertEqual(self.binding.read_bytes(),self.original_binding)
if __name__=='__main__':unittest.main()
