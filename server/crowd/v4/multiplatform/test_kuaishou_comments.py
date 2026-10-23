import asyncio
import ast
import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Callable,Dict,List,Optional
import unittest
import sys
from unittest.mock import patch

from kuaishou_comments import RELATIONS,ROOT,REPLY,install_hook,relations
from mc_runner import normalize,configure_platform_hooks


class KuaishouRelationTests(unittest.TestCase):
    def test_runner_installs_only_for_explicit_ks_comments(self):
        import kuaishou_comments
        client=type('Native',(),{});factory=type('Factory',(),{})
        modules={'media_platform.kuaishou.client':SimpleNamespace(KuaiShouClient=client),
                 'store.kuaishou':SimpleNamespace(KuaishouStoreFactory=factory)}
        with patch.dict(sys.modules,modules),patch.object(kuaishou_comments,'install_hook') as hook:
            configure_platform_hooks(None,{'platform':'ks','mode':'detail','comments':True,'media':False})
            hook.assert_called_once_with(client,factory)
            configure_platform_hooks(None,{'platform':'ks','mode':'detail','comments':False,'media':False})
            self.assertEqual(hook.call_count,1)
    def test_strict_success_real_ids_and_scope(self):
        payload={'result':1,'rootCommentsV2':[{'comment_id':123},{'commentId':'456'}]}
        before=copy.deepcopy(payload)
        self.assertEqual(relations(payload,'photo1'),{('photo1','123'):{'parent_comment_id':'0','parent_relation_basis':ROOT},('photo1','456'):{'parent_comment_id':'0','parent_relation_basis':ROOT}})
        self.assertEqual(payload,before)
        self.assertEqual(relations({'result':1,'subCommentsV2':[{'comment_id':456}]},'photo1',123),{('photo1','456'):{'parent_comment_id':'123','parent_relation_basis':REPLY}})
        for value in (True,1.0,None,0):self.assertEqual(relations({**payload,'result':value},'photo1'),{})
        for value in (True,1.0,'0','bad'):
            self.assertEqual(relations({'result':1,'subCommentsV2':[{'comment_id':456}]},'photo1',value),{})
        self.assertEqual(relations({'result':1,'rootCommentsV2':[{'comment_id':True},{'comment_id':1.0},{'comment_id':123,'commentId':456}]},'photo1'),{})
        self.assertEqual(relations({'result':1,'subCommentsV2':[{'comment_id':123}]},'photo1',123),{})
        self.assertEqual(relations({'result':1,'rootCommentsV2':[{}]*2001},'photo1'),{})

    def test_store_same_photo_only_preserves_explicit_unknown_and_original_text(self):
        saved=[];calls=[]
        class Sink:
            async def store_comment(self,comment_item):saved.append(comment_item)
            async def store_content(self,content_item):return content_item
        class Factory:
            create_store=staticmethod(Sink)
        class Client:
            async def get_video_comments(self,photo_id):
                calls.append('root');return {'result':1,'rootCommentsV2':[{'comment_id':123}]}
            async def get_video_sub_comments(self,photo_id,parent):
                calls.append('reply');return {'result':1,'subCommentsV2':[{'comment_id':456}]}
            async def get_video_all_comments(self,photo_id):
                await self.get_video_comments(photo_id)
                for row in ({'video_id':photo_id,'comment_id':'123','content':'exact 文字🙂'},
                            {'video_id':'OTHER','comment_id':'123','content':'foreign'},
                            {'video_id':photo_id,'comment_id':'123','parent_comment_id':None}):
                    original=copy.deepcopy(row);await Factory.create_store().store_comment(row);assert row==original
                await self.get_video_sub_comments(photo_id,123)
                await Factory.create_store().store_comment({'video_id':photo_id,'comment_id':'456','content':'reply'})
        install_hook(Client,Factory);asyncio.run(Client().get_video_all_comments('photo1'))
        self.assertEqual(calls,['root','reply']);self.assertIsNone(RELATIONS.get())
        self.assertEqual(saved[0]['parent_comment_id'],'0');self.assertEqual(saved[0]['content'],'exact 文字🙂')
        self.assertNotIn('parent_comment_id',saved[1]);self.assertIsNone(saved[2]['parent_comment_id'])
        self.assertEqual(saved[3]['parent_comment_id'],'123');self.assertEqual(saved[3]['parent_relation_basis'],REPLY)
        self.assertEqual(asyncio.run(Factory.create_store().store_content({'plain':True})),{'plain':True})

    def test_concurrent_tasks_and_failed_outer_call_clear_context(self):
        saved=[]
        class Sink:
            async def store_comment(self,comment_item):saved.append(comment_item)
        class Factory:create_store=staticmethod(Sink)
        class Client:
            async def get_video_comments(self,photo_id):
                await asyncio.sleep(0);return {'result':1,'rootCommentsV2':[{'comment_id':123}]}
            async def get_video_sub_comments(self,*args):return {'result':1,'subCommentsV2':[]}
            async def get_video_all_comments(self,photo_id):
                await self.get_video_comments(photo_id);await asyncio.sleep(0)
                await Factory.create_store().store_comment({'video_id':photo_id,'comment_id':'123'})
                if photo_id=='FAIL':raise ValueError('fixture_failure')
        install_hook(Client,Factory)
        async def exercise():
            await asyncio.gather(Client().get_video_all_comments('ONE'),Client().get_video_all_comments('TWO'))
            self.assertIsNone(RELATIONS.get())
            with self.assertRaises(ValueError):await Client().get_video_all_comments('FAIL')
            self.assertIsNone(RELATIONS.get())
        asyncio.run(exercise());self.assertEqual({r['video_id'] for r in saved},{'ONE','TWO','FAIL'})
        self.assertTrue(all(r['parent_comment_id']=='0' for r in saved))

    def test_invalid_reply_root_does_not_parse_root_endpoint_shape(self):
        saved=[]
        class Sink:
            async def store_comment(self,comment_item):saved.append(comment_item)
        class Factory:create_store=staticmethod(Sink)
        class Client:
            async def get_video_comments(self,*args):return {'result':1,'rootCommentsV2':[{'comment_id':123}]}
            async def get_video_sub_comments(self,*args):return {'result':1,'rootCommentsV2':[{'comment_id':123}]}
            async def get_video_all_comments(self,photo_id):
                for invalid in (None,True,1.0,'invalid'):
                    await self.get_video_comments(photo_id)
                    await self.get_video_sub_comments(photo_id,invalid)
                    self_assert(RELATIONS.get()=={})
                    await Factory.create_store().store_comment({'video_id':photo_id,'comment_id':'123'})
        self_assert=self.assertTrue
        install_hook(Client,Factory);asyncio.run(Client().get_video_all_comments('photo1'))
        self.assertTrue(all('parent_comment_id' not in row for row in saved));self.assertIsNone(RELATIONS.get())

    def test_actual_installed_sdk_callback_store_and_normalize(self):
        sdk=Path('/Users/hubowen/WorkBuddy/2026-10-08-22-53-19/MediaCrawler')
        client_path=sdk/'media_platform/kuaishou/client.py';store_path=sdk/'store/kuaishou/__init__.py'
        if not client_path.exists() or not store_path.exists():self.skipTest('installed SDK absent; no source requested')
        klass=next(x for x in ast.parse(client_path.read_text()).body if isinstance(x,ast.ClassDef) and x.name=='KuaiShouClient')
        names={'get_video_comments','get_video_sub_comments','get_video_all_comments','get_comments_all_sub_comments'}
        methods=[x for x in klass.body if isinstance(x,ast.AsyncFunctionDef) and x.name in names]
        saved=[];requests=[];payloads={
            '/rest/v/photo/comment/list':{'result':1,'pcursorV2':'no_more','rootCommentsV2':[{'comment_id':123,'content':'root text','hasSubComments':True}]},
            '/rest/v/photo/comment/sublist':{'result':1,'pcursorV2':'no_more','subCommentsV2':[{'comment_id':456,'content':'reply text'}]}}
        class Sink:
            async def store_comment(self,comment_item):saved.append(comment_item)
        class Factory:create_store=staticmethod(Sink)
        scope={'Dict':Dict,'List':List,'Optional':Optional,'Callable':Callable,'asyncio':asyncio,
               'config':SimpleNamespace(ENABLE_GET_SUB_COMMENTS=True),'random':SimpleNamespace(uniform=lambda *_:0),
               'utils':SimpleNamespace(logger=SimpleNamespace(info=lambda *_:None),get_current_timestamp=lambda:123),
               'KuaishouStoreFactory':Factory,'anonymize_user_id':lambda _:None,'mask_nickname':lambda _:None}
        exec(compile(ast.Module(body=methods,type_ignores=[]),str(client_path),'exec'),scope)
        functions=[x for x in ast.parse(store_path.read_text()).body if isinstance(x,ast.AsyncFunctionDef) and x.name in ('batch_update_ks_video_comments','update_ks_video_comment')]
        exec(compile(ast.Module(body=functions,type_ignores=[]),str(store_path),'exec'),scope)
        Client=type('Client',(),{n:scope[n] for n in names})
        async def request(self,path,payload):requests.append((path,payload));return copy.deepcopy(payloads[path])
        Client.request_rest_v2=request
        async def no_wait(*_):pass
        with patch('asyncio.sleep',side_effect=no_wait):
            asyncio.run(Client().get_video_all_comments('photo1',callback=scope['batch_update_ks_video_comments'],max_count=1))
            self.assertEqual(len(saved),2);self.assertTrue(all('parent_comment_id' not in r for r in saved))
            saved.clear();requests.clear();install_hook(Client,Factory)
            asyncio.run(Client().get_video_all_comments('photo1',callback=scope['batch_update_ks_video_comments'],max_count=1))
        self.assertEqual(len(requests),2);self.assertEqual(saved[0]['parent_comment_id'],'0');self.assertEqual(saved[1]['parent_comment_id'],'123')
        self.assertEqual([r['content'] for r in saved],['root text','reply text']);self.assertIsNone(RELATIONS.get())
        records=[normalize('ks','comment',r,{'path':'offline_fixture','row':i}) for i,r in enumerate(saved)]
        self.assertEqual(records[0]['parent_status'],'reported_root');self.assertEqual(records[1]['parent_relation_basis'],REPLY)
        self.assertEqual(records[1]['parent_comment_id'],'123')
        legacy=normalize('ks','comment',{'video_id':'photo1','comment_id':'123','content':'old'}, {'path':'offline_fixture','row':1})
        self.assertEqual(legacy['parent_status'],'missing_upstream');self.assertNotIn('parent_relation_basis',legacy)


if __name__=='__main__':unittest.main()
