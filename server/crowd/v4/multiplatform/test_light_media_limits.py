import asyncio,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
import mc_runner
from native_media_scope import install_hook
from light_transcripts import LightTranscripts
class Limit(SystemExit):pass
class Tests(unittest.TestCase):
 def test_sdk_short_dirs_cleanup_only_new_parts_both_platforms(self):
  for platform,alias in [('dy','douyin'),('ks','kuaishou')]:
   with tempfile.TemporaryDirectory() as directory:
    root=Path(directory).resolve();output=root/'output';output.mkdir()
    folders=[output/name/'media' for name in (platform,alias)]
    for folder in folders:folder.mkdir(parents=True);(folder/'old.part').write_bytes(b'old')
    class Crawler:
     async def download_media(self):
      for folder in folders:(folder/'new.part').write_bytes(b'new')
      raise Limit(76)
    install_hook(Crawler,platform,output,Limit,mc_runner.read,mc_runner.write)
    asyncio.run(Crawler().download_media())
    for folder in folders:
     self.assertEqual((folder/'old.part').read_bytes(),b'old');self.assertFalse((folder/'new.part').exists())
    self.assertEqual(mc_runner.read(root/'phase.json')['media_reason'],'single_response_byte_limit')
 def test_limit_reason_not_completed_and_old_queue_not_rewritten(self):
  import test_media_native
  f=test_media_native.Tests();f.setUp()
  try:
   mc_runner.write(f.folder/'manifest.json',{'run_id':f.run,'request':{'platform':'dy','media':True,'platform_options':{'transcript_only':True}}})
   f.normalized['media']=[];f.save()
   mc_runner.write(f.folder/'phase.json',{'media_reason':'single_response_byte_limit','subtitle_status':'unavailable'})
   jobs=SimpleNamespace(root=f.root/'media-processing');queue=LightTranscripts(f.root,jobs,lambda run:f.folder)
   state=queue.enqueue(f.run);self.assertEqual(state['state'],'needs_attention');queue.tick()
   self.assertEqual(queue.status(f.run)['reason'],'native_video_over_collection_limit')
   old={**state,'state':'audio_unavailable'};old.pop('reason',None)
   mc_runner.write(queue._path(f.run),old);before=queue._path(f.run).read_bytes()
   self.assertEqual(queue.status(f.run)['state'],'needs_attention')
   self.assertEqual(queue._path(f.run).read_bytes(),before)
  finally:f.tearDown()
if __name__=='__main__':unittest.main()
