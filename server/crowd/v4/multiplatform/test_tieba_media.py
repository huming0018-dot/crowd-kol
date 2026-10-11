import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import tieba_media as media

class Response:
 status_code=200
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def aiter_bytes(self,size):yield b'\xff\xd8\xff'+b'x'*20

class Client:
 def __init__(self):self.requests=[]
 def stream(self,method,url,headers):
  self.requests.append((method,url,headers));return Response()

class Tests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.output=Path(self.temp.name).resolve()/'output'
  self.data={'first_floor':{'id':'42','content':[{'type':3,'origin_src':'http://tiebapic.baidu.com/forum/pic.jpg'}]},
             'user_list':[{'avatar':'https://tiebapic.baidu.com/avatar.jpg'}]}
 def test_extract_primary_and_reply_media_not_user_avatar(self):
  self.data['post_list']=[{'id':'43','content':[{'src':'https://imgsrc.baidu.com/reply.png'}]}]
  result=media.extract_assets(self.data)
  self.assertEqual([x['source_post_id'] for x in result],['42','43'])
  self.assertTrue(result[0]['url'].startswith('https://'))
  self.assertFalse(any('avatar' in x['url'] for x in result))
 def test_credential_arbitrary_host_and_asset_bound(self):
  for value in ('https://127.0.0.1/a.jpg','https://tiebapic.baidu.com.evil.test/a','https://user:pass@tiebapic.baidu.com/a','https://tiebapic.baidu.com/a?token=private'):
   self.assertIsNone(media.asset_url(value))
  self.data['first_floor']['content']=[{'src':'https://tiebapic.baidu.com/%s.jpg'%i} for i in range(20)]
  self.assertEqual(len(media.extract_assets(self.data)),3)
 def test_html_asset_scope(self):
  p=media.PostImages();p.feed('<img src="https://tiebapic.baidu.com/avatar.jpg"><div class="d_post_content"><img src="https://tiebapic.baidu.com/actual.jpg"></div>')
  self.assertEqual(p.urls,['https://tiebapic.baidu.com/actual.jpg'])
 async def test_actual_download_bytes_hash_and_no_cookie(self):
  client=Client();result=await media.download_assets(self.data,'123',self.output,client)
  row=result['downloaded'][0];data=Path(row['path']).read_bytes()
  self.assertEqual(row['sha256'],hashlib.sha256(data).hexdigest())
  self.assertEqual(row['bytes'],23);self.assertFalse(result['credentials_used'])
  self.assertEqual(set(client.requests[0][2]),{'Referer'})
  self.assertEqual(json.loads((Path(row['path']).parent/'assets.json').read_text())['downloaded'],result['downloaded'])
 async def test_bounds_failure_cleanup_and_original_symlink(self):
  with patch.object(media,'MAX_FILE',10):
   result=await media.download_assets(self.data,'123',self.output,Client())
  self.assertEqual(result['errors'],['tieba_media_size_limit']);self.assertEqual(result['downloaded'],[])
  self.assertFalse(list(self.output.glob('**/.part-*')))
  victim=Path(self.temp.name)/'victim';victim.mkdir();(self.output/'tieba/media/456').symlink_to(victim,target_is_directory=True)
  with self.assertRaisesRegex(ValueError,'symlink'):
   await media.download_assets(self.data,'456',self.output,Client())
  self.assertFalse(list(victim.iterdir()))
 async def test_hook_reuses_response_without_repeating_first_page(self):
  data=self.data
  class Native:
   async def _get_pc_page_data(self,note_id,page=1):return data
  calls=[]
  async def download(value,note_id,output):calls.append((value,note_id,output))
  with patch.object(media,'download_assets',download):
   media.install_hook(Native,self.output)
   self.assertIs(await Native()._get_pc_page_data('123'),data)
   await Native()._get_pc_page_data('123');await Native()._get_pc_page_data('123',2)
  self.assertEqual(len(calls),1)

 async def test_manifest_hardlink_does_not_modify_original_and_budget_exit_propagates(self):
  directory=self.output/'tieba/media/123';directory.mkdir(parents=True)
  victim=Path(self.temp.name)/'original';victim.write_text('original unchanged')
  os.link(victim,directory/'assets.json')
  result=await media.download_assets(self.data,'123',self.output,Client())
  self.assertEqual(victim.read_text(),'original unchanged')
  self.assertEqual(json.loads((directory/'assets.json').read_text())['downloaded'],result['downloaded'])
  class BudgetExit:
   def stream(self,*args,**kwargs):raise SystemExit(73)
  with self.assertRaises(SystemExit) as failure:
   await media.download_assets(self.data,'456',self.output,BudgetExit())
  self.assertEqual(failure.exception.code,73)
  self.assertFalse(list(self.output.glob('**/.part-*')))

if __name__=='__main__':unittest.main()
