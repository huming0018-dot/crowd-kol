import asyncio,hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import bili_audio as m
DATA=b'\x00\x00\x00\x18ftypM4A '+b'audio bytes'
URL='https://audio.bilivideo.com/stream.m4a?deadline=123'
def info(rate=64000,duration=100):return {'dash':{'duration':duration,'audio':[{'bandwidth':rate,'baseUrl':URL}]}}
class Response:
 status_code=200
 async def __aenter__(self):return self
 async def __aexit__(self,*a):return False
 async def aiter_bytes(self,*a):
  assert m.AUDIO_RESPONSE_ACTIVE.get()
  yield DATA
class Client:
 def __init__(self,response=None):self.response=response or Response();self.calls=[]
 def stream(self,*a,**kw):self.calls.append((a,kw));return self.response
class AudioTest(unittest.TestCase):
 def test_select_and_boundaries(self):
  p=info();p['dash']['audio'].append({'bandwidth':128000,'baseUrl':URL})
  self.assertEqual(m.select_audio(p)['bandwidth_reported'],64000)
  for url in ['http://audio.bilivideo.com/a','https://bilivideo.com.evil/a','https://user:secret@audio.bilivideo.com/a','https://audio.bilivideo.com:443/a']:
   self.assertIsNone(m.public_audio_url(url))
  for duration in [True,float('nan'),7201,0]:
   with self.assertRaises(ValueError):m.select_audio(info(duration=duration))
  with self.assertRaisesRegex(ValueError,'estimated'):m.select_audio(info(rate=128000,duration=7200))
 def test_download_hash_scope(self):
  with tempfile.TemporaryDirectory() as td:
   client=Client();r=asyncio.run(m.download_audio(info(),'BV123',Path(td).resolve(),client=client))
   self.assertEqual(r['status'],'downloaded');self.assertEqual(r['sha256'],hashlib.sha256(DATA).hexdigest())
   self.assertEqual(Path(r['path']).read_bytes(),DATA);self.assertEqual(len(client.calls),1)
   self.assertEqual(client.calls[0][1]['headers'],{'Referer':'https://www.bilibili.com/'})
   self.assertNotIn(URL,json.dumps(r));self.assertFalse(m.AUDIO_RESPONSE_ACTIVE.get())
 def test_durl_no_request(self):
  with tempfile.TemporaryDirectory() as td:
   client=Client();r=asyncio.run(m.download_audio({'durl':[{'url':URL}]},'BV123',Path(td).resolve(),client=client))
   self.assertEqual(r['reason'],'dash_audio_unavailable');self.assertEqual(client.calls,[])
 def test_budget_exit_preserved(self):
  class Limited(Response):
   async def aiter_bytes(self,*a):
    yield DATA
    raise SystemExit(73)
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(SystemExit) as ctx:asyncio.run(m.download_audio(info(),'BV123',Path(td).resolve(),client=Client(Limited())))
   self.assertEqual(ctx.exception.code,73);self.assertFalse(m.AUDIO_RESPONSE_ACTIVE.get())
   self.assertEqual(list(Path(td).resolve().rglob('.audio-*')),[])
 def test_hardlink_and_actual_byte_cap(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td).resolve();outside=base/'original';outside.write_bytes(b'original')
   folder=base/'out/bili/media/BV123';folder.mkdir(parents=True)
   os.link(outside,folder/'audio.m4a')
   with self.assertRaises(ValueError):asyncio.run(m.download_audio(info(),'BV123',base/'out',client=Client()))
   self.assertEqual(outside.read_bytes(),b'original')
   with patch.object(m,'MAX_AUDIO_BYTES',16):
    r=asyncio.run(m.download_audio(info(rate=1,duration=1),'BV456',base/'out',client=Client()))
   self.assertEqual(r['status'],'limited');self.assertFalse((base/'out/bili/media/BV456/audio.m4a').exists())
 def test_symlink_and_safe_error(self):
  class Broken(Client):
   def stream(self,*a,**kw):raise ValueError('private_secret')
  with tempfile.TemporaryDirectory() as td:
   base=Path(td).resolve();outside=base/'outside';outside.mkdir();(base/'out').symlink_to(outside,target_is_directory=True)
   with self.assertRaises(ValueError):asyncio.run(m.download_audio(info(),'BV123',base/'out',client=Client()))
   self.assertEqual(list(outside.iterdir()),[])
   r=asyncio.run(m.download_audio(info(),'BV456',base/'safe',client=Broken()))
   self.assertEqual(r['reason'],'audio_download_failed');self.assertNotIn('private',json.dumps(r))
if __name__=='__main__':unittest.main()
