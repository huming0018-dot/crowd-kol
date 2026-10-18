"""Actual exception handler/supervisor/projection contracts; no native/source requests."""
import ast
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import Mock, patch

import discovery
import mc_runner
from dashboard import Application


class UnavailableTests(unittest.TestCase):
    def test_executor_handler_classifies_only_fixed_type_without_message(self):
        tree=ast.parse(Path(mc_runner.__file__).read_text())
        execute=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='execute')
        handler=next(n for n in ast.walk(execute) if isinstance(n,ast.ExceptHandler)
                     and isinstance(n.type,ast.Name) and n.type.id=='BaseException')
        function=ast.FunctionDef(name='handle',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg='exc')],kwonlyargs=[],kw_defaults=[],defaults=[]),body=handler.body,decorator_list=[])
        module=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
        class Imitation(discovery.DiscoveryUnavailable):pass
        for error in (discovery.DiscoveryUnavailable(),ValueError('discovery_empty_or_unavailable'),
                      ValueError('Cookie=PRIVATE_SECRET https://private.invalid/?token=PRIVATE_SECRET'),Imitation()):
            captured=[];namespace={'run':Path('/offline'),'attempts':0,
                                  'write':lambda path,value:captured.append(value)}
            exec(compile(module,'actual_execute_handler','exec'),namespace)
            with self.assertRaises(SystemExit) as raised:namespace['handle'](error)
            self.assertEqual(raised.exception.code,74);self.assertEqual(len(captured),1)
            self.assertNotIn('PRIVATE_SECRET',json.dumps(captured))
            if type(error) is discovery.DiscoveryUnavailable:
                self.assertEqual(captured[0],{'phase':'failed','api_attempts':0,**discovery.failure_metadata(error)})
            else:self.assertNotIn('failure_reason',captured[0])

    def supervisor(self,folder,fields,mode='homefeed',code=74,stop=False,legacy=False):
        root=Path(folder);rid=str(uuid.uuid4());run=root/'runs'/rid;(run/'output').mkdir(parents=True)
        request={'timeout_seconds':180,'session_id':str(uuid.uuid4()),'mode':mode}
        if legacy:request.pop('session_id')
        mc_runner.write(run/'manifest.json',{'request':request})
        mc_runner.write(run/'status.json',{'state':'running','updated_at':time.time()})
        mc_runner.write(run/'phase.json',{'phase':'failed','api_attempts':0,**fields})
        if stop:mc_runner.stop(root,{'run_id':rid})
        child=Mock();child.poll.return_value=None if legacy else code;child.wait.return_value=code
        with patch('browser_session.existing_browser_session',return_value=None) as inspect,patch('browser_session.terminate_executor') as terminate,patch.object(mc_runner.subprocess,'Popen',return_value=child),patch.object(mc_runner.os,'close'):
            mc_runner.worker(root,root/'fake-mc',rid,99)
            if legacy:
                inspect.assert_not_called();terminate.assert_called_once_with(child.pid,False)
        return mc_runner.read(run/'status.json')

    def test_real_supervisor_reason_keeps_login_stop_and_unknown_separate(self):
        fields=discovery.failure_metadata(discovery.DiscoveryUnavailable())
        with tempfile.TemporaryDirectory() as folder:
            good=self.supervisor(folder,fields)
            self.assertTrue(discovery.unavailable_failure(good));self.assertEqual(good['state'],'failed')
            for delta in ({'failure_type':'ValueError'},{'failure_stage':'other'},{'failure_reason':'private_secret'}, {'failure_reason':None}):
                state=self.supervisor(folder,{**fields,**delta});self.assertEqual(state['reason'],'executor_error')
            self.assertEqual(self.supervisor(folder,fields,mode='search')['reason'],'executor_error')
            for code,reason in ((77,'login_required'),(78,'account_changed'),(73,'api_request_limit')):
                self.assertEqual(self.supervisor(folder,fields,code=code)['reason'],reason)
            legacy=self.supervisor(folder,{},stop=True,legacy=True)
            self.assertEqual((legacy['state'],legacy['reason']),('stopped','user_stop'))
            stopped=self.supervisor(folder,fields,stop=True)
            self.assertEqual((stopped['state'],stopped['reason']),('stopped','user_stop'))

    def test_matching_failed_owner_projection_readonly_legacy_and_other_child_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Application(folder);rid=str(uuid.uuid4());run=app.runner_root/'runs'/rid;run.mkdir(parents=True)
            state={'state':'failed','exit_code':74,'reason':'discovery_empty_or_unavailable',
                   'updated_at':time.time(),**discovery.failure_metadata(discovery.DiscoveryUnavailable())}
            mc_runner.write(run/'status.json',state);original=(run/'status.json').read_bytes()
            value={'task':{'children':[{'state':'failed','local_run_id':rid,'reason_code':'no_content_observed'},
                     {'state':'completed','local_run_id':rid},{'state':'waiting','local_run_id':rid},
                     {'state':'failed','local_run_id':str(uuid.uuid4())}]}}
            before=json.dumps(value,sort_keys=True);projected=app._task_stop_projection(value)
            self.assertEqual(projected['task']['children'][0]['local_failure_reason'],'discovery_empty_or_unavailable')
            for child in projected['task']['children'][1:]:self.assertNotIn('local_failure_reason',child)
            self.assertEqual(json.dumps(value,sort_keys=True),before);self.assertEqual((run/'status.json').read_bytes(),original)
            legacy={**state,'reason':'executor_error','failure_type':'ValueError'}
            legacy.pop('failure_stage');legacy.pop('failure_reason');mc_runner.write(run/'status.json',legacy)
            old=(run/'status.json').read_bytes()
            self.assertNotIn('local_failure_reason',app._task_stop_projection(value)['task']['children'][0])
            self.assertEqual((run/'status.json').read_bytes(),old)


if __name__=='__main__':unittest.main()
