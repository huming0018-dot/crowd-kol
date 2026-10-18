import unittest,tempfile,json,sys,uuid,ast,asyncio,copy
from pathlib import Path
from types import SimpleNamespace
H=Path(__file__).resolve().parent;sys.path.insert(0,str(H));import account_sessions as m
class BridgeLaunch(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.sid=str(uuid.uuid4());self.session=self.root/'sessions'/self.sid;self.profile=self.session/'browser_data/xhs_bridge_profile';self.profile.mkdir(parents=True);self.binding=self.session/'pro-binding.json';self.good={'platform':'xhs','client_id':'original-client','cookiebridge_url':'http://127.0.0.1:8274','sign_url':'http://127.0.0.1:8990'};self.binding.write_text(json.dumps(self.good));self.before=self.binding.read_bytes()
 def tearDown(self):self.tmp.cleanup()
 def run_options(self,**changes):
  args=dict(root=self.root,session_id=self.sid,platform='xhs',browser_name='chromium',user_data_dir=self.profile,options={'headless':False,'args':['--fixed-existing-option'],'ignore_default_args':['--mute-audio']});args.update(changes);original=copy.deepcopy(args['options']);result=m._preserve_bound_xhs_bridge(**args);self.assertEqual(args['options'],original);return result
 def test_exact_existing_binding_only_removes_disable_flag(self):
  result=self.run_options();self.assertEqual(result,{'headless':False,'args':['--fixed-existing-option'],'ignore_default_args':['--mute-audio','--disable-extensions']});self.assertEqual(self.binding.read_bytes(),self.before);self.assertEqual(list(self.profile.iterdir()),[])
 def test_no_binding_no_change(self):
  self.binding.unlink();self.assertEqual(self.run_options()['ignore_default_args'],['--mute-audio'])
 def test_other_platform_profile_type_no_change(self):
  for changes in [{'platform':'bili'},{'browser_name':'firefox'},{'user_data_dir':self.profile.parent},{'user_data_dir':None},{'session_id':'not-uuid'}]:self.assertEqual(self.run_options(**changes)['ignore_default_args'],['--mute-audio'])
 def test_invalid_binding_never_enables(self):
  for value in [[],None,{},dict(self.good,client_id='bad secret'),dict(self.good,platform='bili'),dict(self.good,cookiebridge_url='http://remote.invalid:8274'),dict(self.good,sign_url='http://user:pass@127.0.0.1:8990'),dict(self.good,sign_url='http://127.0.0.1:8990/?x=1')]:
   self.binding.write_text(json.dumps(value));self.assertEqual(self.run_options()['ignore_default_args'],['--mute-audio'])
 def test_non_string_service_urls_keep_original_options(self):
  for field in ('cookiebridge_url','sign_url'):
   for invalid in ({}, {'host':'private'}, [], ['private'], 0, 123, False, True, None):
    with self.subTest(field=field,value_type=type(invalid).__name__):
     value=dict(self.good);value[field]=invalid;self.binding.write_text(json.dumps(value));self.assertEqual(self.run_options()['ignore_default_args'],['--mute-audio'])
 def test_binding_and_profile_symlinks_rejected(self):
  real=self.binding.with_suffix('.real');self.binding.rename(real);self.binding.symlink_to(real);self.assertEqual(self.run_options()['ignore_default_args'],['--mute-audio']);self.binding.unlink();real.rename(self.binding);other=self.profile.with_name('different');self.profile.rename(other);self.profile.symlink_to(other,target_is_directory=True);self.assertEqual(self.run_options()['ignore_default_args'],['--mute-audio'])
 def test_parent_profile_symlink_never_enables(self):
  parent=self.profile.parent;actual=parent.with_name('other-browser-data');parent.rename(actual);parent.symlink_to(actual,target_is_directory=True);self.assertEqual(self.run_options()['ignore_default_args'],['--mute-audio'])
 def test_true_or_invalid_ignore_args_not_weakened(self):
  for value in [True,False,None,{},['--existing',1]]:
   options={'ignore_default_args':value};self.assertEqual(self.run_options(options=options),options)
 def test_dedup_only_default_filter_no_new_load_flag(self):
  result=self.run_options(options={'ignore_default_args':['--disable-extensions','--mute-audio']});self.assertEqual(result['ignore_default_args'],['--disable-extensions','--mute-audio']);self.assertNotIn('args',result)
 def test_real_worker_wrapper_uses_gate_for_positional_and_keyword(self):
  node=next(x for x in ast.walk(ast.parse((H/'account_sessions.py').read_text())) if isinstance(x,ast.AsyncFunctionDef) and x.name=='persistent');calls=[]
  async def original(browser,*a,**kw):calls.append((a,kw));return 'original-result'
  scope={'original':original,'Path':Path,'args':SimpleNamespace(root=self.root,session_id=self.sid,platform='xhs'),'_preserve_bound_xhs_bridge':m._preserve_bound_xhs_bridge};exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'actual_worker_persistent','exec'),scope);browser=SimpleNamespace(name='chromium',executable_path='/usr/bin/true')
  self.assertEqual(asyncio.run(scope['persistent'](browser,str(self.profile),headless=False)),'original-result');self.assertEqual(asyncio.run(scope['persistent'](browser,user_data_dir=str(self.profile),headless=False)),'original-result');self.assertEqual(len(calls),2);self.assertTrue(all(x[1]['ignore_default_args']==['--disable-extensions'] for x in calls));self.assertTrue(all('args' not in x[1] for x in calls))
if __name__=='__main__':unittest.main()
