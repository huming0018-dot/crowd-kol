import tempfile,unittest,os,subprocess,gzip,json
from pathlib import Path
from unittest.mock import patch
import video_ocr

class VideoOCRTests(unittest.TestCase):
    def test_merge_only_adjacent_exact_text_and_blank_breaks_repeat(self):
        def f(i,text):return {'index':i,'time':i*.5,'blocks':[{'text':text}] if text else []}
        rows=video_ocr.merge_frames([f(0,'你好'),f(1,'你好'),f(2,''),f(3,'你好'),f(4,'你 好'),f(5,'你好')],3.)
        self.assertEqual([(r['text'],r['start'],r['end']) for r in rows],[('你好',0.,1.),('你好',1.5,2.),('你 好',2.,2.5),('你好',2.5,3.)])

    def test_source_identity_and_range_rejected_before_native(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source.mp4';source.write_bytes(b'ownedfixture');sha=video_ocr.digest(source)
            with patch.object(video_ocr.subprocess,'Popen',side_effect=AssertionError('must not start native')):
                with self.assertRaisesRegex(ValueError,'source_changed'):video_ocr.prepare(source,root/'work','douyin','123','0'*64,60)
                with self.assertRaisesRegex(ValueError,'invalid_video_ocr_duration'):video_ocr.prepare(source,root/'work','douyin','123',sha,7201)
                with self.assertRaisesRegex(ValueError,'invalid_video_ocr_range'):video_ocr.prepare(source,root/'work','douyin','123',sha,60,59,2)
                with self.assertRaisesRegex(ValueError,'invalid_video_ocr_crop'):video_ocr.prepare(source,root/'work','douyin','123',sha,60,crop_top=.8,crop_bottom=.7)
                source.unlink();source.symlink_to(root/'missing')
                with self.assertRaisesRegex(ValueError,'source_changed'):video_ocr.prepare(source,root/'work','douyin','123',sha,60)

    def test_real_fractional_video_sampling_with_offline_native_fixture(self):
        ffmpeg=os.environ.get('CROWD_FFMPEG')
        if not ffmpeg or not Path(ffmpeg).is_file():self.skipTest('existing ffmpeg required')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();source=root/'source.mp4'
            subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=black:size=320x240:rate=30','-t','2.1','-c:v','libx264',str(source)],check=True)
            native=root/'offline-python';native.write_text('''#!/Users/hubowen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
import sys,json
for line in sys.stdin:
 value=json.loads(line)
 print(json.dumps({'index':value['index'],'truncated':False,'native_seconds':0.01,'blocks':[{'text':'fixture画面字','confidence':0.5,'bbox':[.2,.5,.5,.3]}]}),flush=True)
''');native.chmod(0o700)
            out=video_ocr.prepare(source,root/'work','douyin','123',video_ocr.digest(source),2.1,native=native)
            e=out[0]['evidence'];self.assertEqual(e['sampled_frames'],5)
            self.assertFalse(e['spoken_transcript']);self.assertIsNone(e['cer'])
            self.assertEqual(len(e['segments']),1);self.assertEqual(e['segments'][0]['end'],2.1)
            frames=json.loads(gzip.decompress((root/'work/frames.json.gz').read_bytes()))
            self.assertEqual([f['time'] for f in frames],[0.,.5,1.,1.5,2.])
            self.assertEqual(list((root/'work').glob('frames-*')),[])
            native.write_text(native.read_text().replace("'truncated':False","'truncated':True"))
            with self.assertRaisesRegex(ValueError,'invalid_video_ocr_native'):
                video_ocr.prepare(source,root/'reject','douyin','123',video_ocr.digest(source),2.1,native=native)
            self.assertFalse((root/'reject/result.json').exists())

if __name__=='__main__':unittest.main()
