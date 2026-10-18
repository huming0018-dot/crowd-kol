import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from tieba_body import first_floor,install_hook
from mc_runner import normalize

class TiebaBodyTests(unittest.TestCase):
    def data(self,**extra):return {'thread':{'id':'123'},**extra}
    def test_explicit_first_floor_text_html_and_fragments(self):
        body=first_floor(self.data(first_floor={'content':[{'type':0,'text':'Hello '},{'text':'world 正文'},{'type':3,'text':'image alt','src':'https://public.invalid/img.jpg'}]}),'123')
        self.assertEqual(body['text'],'Hello world 正文');self.assertEqual(body['status'],'body_text');self.assertEqual(body['media_count'],1)
    def test_plain_text_blocks_keep_literal_markup_and_angle_tail(self):
        for text in ('I <3 this','比较 a < b','文本末尾 <','<script>literal public text</script>'):
            self.assertEqual(first_floor(self.data(first_floor={'content':[{'type':0,'text':text}]}),'123')['text'],text)
        self.assertEqual(first_floor(self.data(first_floor={'content':'正文<br>后文<script>skip</script> <'}),'123')['text'],'正文 后文 <')
        self.assertEqual(first_floor(self.data(first_floor={'content':[{'text':'','c':'fallback text'}]}),'123')['text'],'fallback text')
    def test_only_explicit_post_floor_one_not_reply_or_position(self):
        body=first_floor(self.data(post_list=[{'floor':2,'content':'reply'},{'post_no':'1','tid':'123','content':'正文'}]),'123')
        self.assertEqual(body['text'],'正文');self.assertEqual(body['source'],'post_list_explicit_floor_1')
        for row in ({'content':'first position is reply'},{'floor':True,'content':'bool'},{'floor':1,'post_no':2,'content':'conflict'}):
            self.assertEqual(first_floor(self.data(post_list=[row]),'123')['text'],'')
    def test_summary_is_not_full_body_or_pure_media(self):
        body=first_floor({'thread':{'id':'123','origin_thread_info':{'abstract':'摘要','content':'fallback cannot establish first floor'}}},'123')
        self.assertEqual(body['status'],'summary_only');self.assertEqual(body['text'],'');self.assertEqual(body['summary_chars'],2)
        self.assertEqual(first_floor(self.data(first_floor={'id':'1'}),'123')['status'],'missing_body_field')
    def test_media_only_empty_and_missing_are_distinct(self):
        for value in ([{'type':3,'text':'image alt'}],'<img src="https://public.invalid/img.jpg" alt="not body">'):
            body=first_floor(self.data(first_floor={'content':value}),'123');self.assertEqual(body['status'],'media_only');self.assertEqual(body['text'],'')
        self.assertEqual(first_floor(self.data(first_floor={'content':[]}),'123')['status'],'empty_first_floor')
        self.assertEqual(first_floor(self.data(),'123')['status'],'missing_first_floor')
    def test_ambiguous_foreign_identity_and_oversize_fail_closed(self):
        cases=[({'thread':{'id':'999'},'first_floor':{'content':'foreign'}},'identity_mismatch'),(self.data(first_floor={'tid':'999','content':'foreign'}),'identity_mismatch'),(self.data(first_floor={'floor':2,'content':'reply'}),'first_floor_conflict'),(self.data(post_list=[{'floor':1,'content':'one'},{'post_no':1,'content':'other'}]),'first_floor_ambiguous'),(self.data(first_floor={'content':[{'text':'x'*1_000_001}]}),'input_limit'),(self.data(first_floor={'content':[{'type':99,'text':'unknown not body'}]}),'content_unavailable')]
        for value,code in cases:
            with self.subTest(code=code),self.assertRaisesRegex(ValueError,'tieba_body_'+code):first_floor(value,'123')
        for thread in ({'id':'123','tid':'999'},{'id':123.0},{'id':True},{'id':'123','tid':None}):
            with self.subTest(thread=thread),self.assertRaisesRegex(ValueError,'tieba_body_identity_mismatch'):first_floor({'thread':thread,'first_floor':{'content':'unconfirmed'}},'123')
        self.assertEqual(first_floor({'thread':{'id':123,'tid':'123'},'first_floor':{'content':'confirmed'}},'123')['text'],'confirmed')
    def test_native_same_response_hook_no_requests_or_mutation(self):
        calls=[]
        class Extractor:
            def extract_note_detail_from_api(self,data):return SimpleNamespace(note_id=data['thread']['id'],desc='native summary')
        class Client:
            def __init__(self):self._page_extractor=Extractor()
            async def get_note_by_id(self,note_id):
                calls.append(note_id);await asyncio.sleep(0)
                return self._page_extractor.extract_note_detail_from_api({'thread':{'id':note_id},'post_list':[{'floor':1,'content':'body '+note_id}]})
        with tempfile.TemporaryDirectory() as folder:
            install_hook(Client,Extractor,folder)
            async def exercise():return await asyncio.gather(Client().get_note_by_id('123'),Client().get_note_by_id('456'))
            rows=asyncio.run(exercise());self.assertEqual([r.desc for r in rows],['body 123','body 456']);self.assertEqual(calls,['123','456'])
            phase=json.loads((Path(folder)/'phase.json').read_text());self.assertNotIn('text',phase['tieba_body'])
            self.assertEqual(phase['tieba_body']['source'],'post_list_explicit_floor_1');self.assertEqual(phase['tieba_body']['text_chars'],8)
            self.assertNotIn('123',json.dumps(phase));self.assertNotIn('http',json.dumps(phase))
    def test_actual_installed_native_get_method_keeps_context_through_extract(self):
        import ast
        import os
        sdk=Path(os.environ.get('MC_EXTERNAL_ROOT','/Users/hubowen/WorkBuddy/2026-10-08-22-53-19/MediaCrawler'))/'media_platform/tieba/client.py'
        if not sdk.exists():self.skipTest('installed SDK absent; no download or source request')
        tree=ast.parse(sdk.read_text());klass=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BaiduTieBaClient')
        method=next(n for n in klass.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='get_note_by_id')
        scope={'TiebaNote':SimpleNamespace,'utils':SimpleNamespace(logger=SimpleNamespace(info=lambda *a:None,error=lambda *a:None))}
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(sdk),'exec'),scope)
        calls=[]
        class Extractor:
            def extract_note_detail_from_api(self,data):
                from tieba_body import TARGET
                calls.append(('extract',TARGET.get()));return SimpleNamespace(note_id=data['thread']['id'],desc='native summary')
        class Client:
            get_note_by_id=scope['get_note_by_id']
            playwright_page=True
            def __init__(self):self._page_extractor=Extractor()
            async def _get_pc_page_data(self,note_id,page):
                calls.append(('existing_request',note_id,page));return {'thread':{'id':note_id},'post_list':[{'post_no':1,'content':'verified first floor'}]}
        with tempfile.TemporaryDirectory() as folder:
            install_hook(Client,Extractor,folder);note=asyncio.run(Client().get_note_by_id('123'))
            self.assertEqual(note.desc,'verified first floor');self.assertEqual(calls,[('existing_request','123',1),('extract','123')])
            from tieba_body import TARGET
            self.assertIsNone(TARGET.get())
    def test_actual_sdk_extractor_reproduces_missing_floor_fallback_and_summary(self):
        import ast,html,re
        from typing import Any,Dict,List,Tuple
        from urllib.parse import parse_qs,quote,unquote,urljoin
        sdk=Path('/Users/hubowen/WorkBuddy/2026-10-08-22-53-19/MediaCrawler/media_platform/tieba/help.py')
        if not sdk.exists():self.skipTest('installed SDK absent; no download or source request')
        tree=ast.parse(sdk.read_text());klass=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TieBaExtractor')
        scope={'html':html,'json':json,'re':re,'Any':Any,'Dict':Dict,'List':List,'Tuple':Tuple,'Selector':SimpleNamespace,'TiebaNote':SimpleNamespace,'TiebaComment':SimpleNamespace,'TiebaCreator':SimpleNamespace,'const':SimpleNamespace(TIEBA_URL='https://tieba.baidu.com'),'utils':SimpleNamespace(get_time_str_from_unix_time=lambda _:''),'anonymize_user_id':lambda _:'anonymous','mask_nickname':lambda _:'' ,'parse_qs':parse_qs,'quote':quote,'unquote':unquote,'urljoin':urljoin}
        exec(compile(ast.Module(body=[klass],type_ignores=[]),str(sdk),'exec'),scope)
        extractor=scope['TieBaExtractor']()
        data=self.data(post_list=[{'post_no':1,'content':[{'type':0,'text':'full first floor'}]}])
        self.assertEqual(extractor.extract_note_detail_from_api(data).desc,'')
        self.assertEqual(first_floor(data,'123')['text'],'full first floor')
        data={'thread':{'id':'123','origin_thread_info':{'abstract':'summary only'}}}
        self.assertEqual(extractor.extract_note_detail_from_api(data).desc,'summary only')
        self.assertEqual(first_floor(data,'123')['text'],'')
    def test_saved_real_680_character_content_and_normalize_unchanged(self):
        root=Path(__file__).resolve().parents[5]
        path=root/'.crowd-launch/seven-platform-live/tieba/runs/f52a56a5-738d-46ce-93d4-c52fb1de7d6b/output/tieba/jsonl/detail_contents_2026-10-11.jsonl'
        if not path.exists():self.skipTest('real historical fixture absent; no source requested')
        original=path.read_bytes();row=json.loads(original.splitlines()[0]);self.assertEqual(len(row['desc']),680)
        body=first_floor({'thread':{'id':row['note_id']},'first_floor':{'content':row['desc']}},row['note_id'])
        self.assertEqual(body['text'],row['desc']);self.assertEqual(body['status'],'body_text')
        before=normalize('tieba','content',row,{'path':'public_fixture','row':1});after=normalize('tieba','content',{**row,'desc':body['text']},{'path':'public_fixture','row':1})
        self.assertEqual(before,after);self.assertEqual(path.read_bytes(),original)

if __name__=='__main__':unittest.main()
