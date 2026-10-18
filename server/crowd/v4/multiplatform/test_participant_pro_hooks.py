import asyncio
import unittest
import uuid
from participant_pro import ParticipantError
from participant_pro_hooks import ParticipantNativeHooks

class Tests(unittest.IsolatedAsyncioTestCase):
    def context(self):return {'schema':'crowd-participant-pro-local-v1','binding':{'subject':str(uuid.uuid4())},'installation_id':str(uuid.uuid4()),'task_id':19,'lease':str(uuid.uuid4()),'known_ids':['a'*24],'limit':2}
    async def test_original_discovery_filter_before_native_slice_and_two_details(self):
        c=self.context();calls=[]
        def rpc(action,p):
            calls.append((action,p));return {'matched':True,'subject':c['binding']['subject'],'installation_id':c['installation_id']} if action=='verify_platform_principal' else {'allowed':True,'reason':None}
        class Client:
            async def get_note_by_keyword(self,*a,**kw):return {'items':[{'id':v*24,'model_type':'note'} for v in 'abc'],'has_more':True,'untouched':7}
            async def get_note_by_id(self,note,*a,**kw):return {'native':note}
        search,detail=Client.get_note_by_keyword,Client.get_note_by_id
        h=ParticipantNativeHooks(c,rpc).install(Client)
        try:
            with self.assertRaises(SystemExit):await Client().get_note_by_keyword('fixture')
            await h.identity('xhs','f'*24)
            result=await Client().get_note_by_keyword('fixture');self.assertEqual([r['id'] for r in result['items']],['b'*24,'c'*24]);self.assertEqual(result['untouched'],7)
            for row in result['items'][:2]:self.assertEqual((await Client().get_note_by_id(row['id']))['native'],row['id'])
            self.assertEqual(await Client().get_note_by_keyword('fixture'),{'items':[],'has_more':False})
            with self.assertRaises(ParticipantError):await Client().get_note_by_id('d'*24)
            self.assertEqual([p['p_action'] for a,p in calls if a=='pro_guard'],['search','detail','detail'])
        finally:h.restore()
        self.assertIs(Client.get_note_by_keyword,search);self.assertIs(Client.get_note_by_id,detail)
    async def test_unknown_guard_aborts_native_exception_handlers(self):
        c=self.context()
        def rpc(*a):raise RuntimeError('unknown')
        h=ParticipantNativeHooks(c,rpc);h.authenticated=True
        with self.assertRaises(SystemExit) as caught:await h.guard('search')
        self.assertEqual(caught.exception.code,86)
    async def test_wrong_principal_denies_every_source(self):
        c=self.context();h=ParticipantNativeHooks(c,lambda *a:{'matched':False})
        with self.assertRaises(ParticipantError):await h.identity('xhs','f'*24)
        with self.assertRaises(SystemExit):await h.guard('search')
    async def test_success_then_mismatch_revokes_and_terminally_blocks_source(self):
        c=self.context();calls=[];matched=True
        def rpc(action,p):
            calls.append(action)
            return {'matched':matched,'subject':c['binding']['subject'],'installation_id':c['installation_id']}
        h=ParticipantNativeHooks(c,rpc)
        await h.identity('xhs','f'*24);self.assertTrue(h.authenticated)
        matched=False
        with self.assertRaises(ParticipantError):await h.identity('xhs','e'*24)
        self.assertFalse(h.authenticated)
        with self.assertRaises(SystemExit):await h.guard('detail','b'*24)
        self.assertEqual(calls,['verify_platform_principal','verify_platform_principal'])
    async def test_success_then_transport_unknown_revokes_and_blocks_source(self):
        c=self.context();calls=[];unknown=False
        def rpc(action,p):
            calls.append(action)
            if unknown:raise RuntimeError('outcome unknown')
            return {'matched':True,'subject':c['binding']['subject'],'installation_id':c['installation_id']}
        h=ParticipantNativeHooks(c,rpc)
        await h.identity('xhs','f'*24);unknown=True
        with self.assertRaises(RuntimeError):await h.identity('xhs','f'*24)
        self.assertFalse(h.authenticated)
        with self.assertRaises(SystemExit):await h.guard('search')
        self.assertEqual(calls,['verify_platform_principal','verify_platform_principal'])
    async def test_denied_guard_no_detail(self):
        c=self.context();calls=[]
        class Client:
            async def get_note_by_keyword(self,*a,**kw):raise AssertionError('source')
            async def get_note_by_id(self,*a,**kw):calls.append(1)
        h=ParticipantNativeHooks(c,lambda *a:{'allowed':False,'reason':'captcha'}).install(Client);h.authenticated=True
        try:
            with self.assertRaises(SystemExit):await Client().get_note_by_id('b'*24)
            self.assertEqual(calls,[]);self.assertEqual(h.details,set())
        finally:h.restore()

if __name__=='__main__':unittest.main()
