import asyncio
import importlib.util
import inspect
import os
from pathlib import Path
import unittest
import uuid
from participant_pro import ParticipantError

if os.environ.get('PARTICIPANT_HOOK_SOURCE'):
    spec=importlib.util.spec_from_file_location('old_hooks',os.environ['PARTICIPANT_HOOK_SOURCE']);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);Hooks=module.ParticipantNativeHooks
else:
    from participant_pro_hooks import ParticipantNativeHooks as Hooks

class Tests(unittest.IsolatedAsyncioTestCase):
    def context(self):return {'schema':'crowd-participant-pro-local-v1','binding':{'subject':str(uuid.uuid4())},'installation_id':str(uuid.uuid4()),'task_id':19,'lease':str(uuid.uuid4()),'known_ids':[],'limit':2}
    async def test_known_gap_waits_and_readmits_before_one_original_detail(self):
        c=self.context();events=[];clock=[0.0];source=[];rpc_calls=[]
        async def sleep(n):events.append(('sleep',n));clock[0]+=n
        def rpc(a,p):
            rpc_calls.append(p['p_action'])
            if len(rpc_calls)==1:return {'allowed':False,'reason':'action_gap','wait_ms':994,'action_wait_ms':994,'gap_ms':1000}
            return {'allowed':True,'reason':None}
        options={'clock':lambda:clock[0],'sleeper':sleep,'journal':lambda e:events.append(('journal',e))}
        h=Hooks(c,rpc,**{k:v for k,v in options.items() if k in inspect.signature(Hooks).parameters})
        h.authenticated=True
        class Client:
            async def get_note_by_keyword(self,*a,**k):raise AssertionError('no search replay')
            async def get_note_by_id(self,note,*a,**k):source.append(note);return {'original':True}
        h.install(Client)
        try:self.assertEqual(await Client().get_note_by_id('a'*24),{'original':True})
        finally:h.restore()
        self.assertEqual(rpc_calls,['detail','detail']);self.assertEqual(source,['a'*24]);self.assertEqual(clock[0],.994)
        self.assertEqual([e['outcome'] for e in h.events],['known_gap_wait','admitted'])
    async def test_stop_during_wait_blocks_before_source(self):
        stopped=[False];calls=[]
        async def sleep(n):stopped[0]=True
        def rpc(a,p):
            calls.append(a)
            if stopped[0]:raise ParticipantError('participant_scope_changed')
            return {'allowed':False,'reason':'action_gap','wait_ms':1}
        h=Hooks(self.context(),rpc,sleeper=sleep);h.authenticated=True
        with self.assertRaises(SystemExit) as caught:await h.guard('detail','a'*24)
        self.assertEqual(caught.exception.code,86);self.assertEqual(len(calls),2)
    async def test_budget_pause_unknown_and_malformed_wait_do_not_retry(self):
        responses=[{'allowed':False,'reason':r,'wait_ms':1} for r in ('captcha','session_rest','action_budget','daily_quota','safety_pause')]
        responses += [{'allowed':False,'reason':'action_gap','wait_ms':w} for w in (None,True,0,-1,300001,float('nan'),'1')]
        for response in responses:
            calls=[]
            def rpc(*a):calls.append(1);return response
            async def sleep(n):self.fail('must not wait')
            h=Hooks(self.context(),rpc,sleeper=sleep);h.authenticated=True
            with self.assertRaises(SystemExit):await h.guard('detail','a'*24)
            self.assertEqual(calls,[1])
    async def test_wait_exceeding_deadline_and_rpc_crossing_deadline_stop(self):
        for response in ({'allowed':False,'reason':'action_gap','wait_ms':31000},{'allowed':True,'reason':None}):
            clock=[0.0]
            def rpc(*a):
                if response['allowed']:clock[0]=31
                return response
            async def sleep(n):self.fail('deadline')
            h=Hooks(self.context(),rpc,clock=lambda:clock[0],sleeper=sleep,timeout_seconds=30);h.authenticated=True
            with self.assertRaises(SystemExit):await h.guard('search')
    async def test_existing_fixed_reasons_preserved_without_free_text(self):
        h=Hooks(self.context(),lambda *a:None)
        for reason in ('known_note','note_busy','global_pause','executor_changed'):
            h.record('detail','denied',{'reason':reason})
            self.assertEqual(h.events[-1]['reason'],reason)
        h.record('detail','denied',{'reason':'arbitrary private fixture'})
        self.assertEqual(h.events[-1]['reason'],'other')
    async def test_journal_failure_cannot_block_authorized_action(self):
        def broken(v):raise OSError('fixture')
        h=Hooks(self.context(),lambda *a:{'allowed':True,'reason':None},journal=broken);h.authenticated=True
        await h.guard('search');self.assertEqual(h.events[-1]['outcome'],'admitted')

if __name__=='__main__':unittest.main()
