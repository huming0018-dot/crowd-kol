"""Local sampled video text, never speech transcription or semantic truth."""
import argparse,gzip,hashlib,json,math,os,re,resource,select,shutil,subprocess,tempfile,time,platform as system_platform,sys,traceback
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parent
_spec=importlib.util.spec_from_file_location('crowd_video_ocr_geometry',ROOT/'video_ocr_geometry.py')
_geometry=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_geometry)
project_geometry=_geometry.project
LIMIT=200000
FPS=2
STAGE={'name':'preflight','frame_index':None,'returncode':None}
ERROR_CODES={'invalid_video_ocr_identity','invalid_video_ocr_crop','video_ocr_source_changed','invalid_video_ocr_duration','invalid_video_ocr_range','unsafe_video_ocr_work','video_ocr_existing_work','video_ocr_ffmpeg_unavailable','video_ocr_cancelled','video_ocr_timeout','video_ocr_frame_decode_failed','video_ocr_sample_incomplete','video_ocr_native_timeout','invalid_video_ocr_native','video_ocr_native_failed','video_ocr_frame_evidence_limit','video_ocr_report_limit'}

def failure_diagnostic(error):
    # Never persist exception messages or OCR text; only fixed codes and stack locations.
    return {'reason':str(error) if type(error) is ValueError and str(error) in ERROR_CODES else 'video_ocr_internal_error',
            'exception_type':type(error).__name__,'python_version':system_platform.python_version(),
            'stage':dict(STAGE),
            'stack':[{'file':frame.filename,'line':frame.lineno,'function':frame.name} for frame in traceback.extract_tb(error.__traceback__)[-6:]]}

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()

def merge_frames(frames,end):
    rows=[]
    for f in frames:
        text='\n'.join(b['text'] for b in f['blocks'] if b.get('selected',True)).strip()
        if not text:continue
        if rows and rows[-1]['text']==text and f['index']==rows[-1]['last_frame']+1:
            rows[-1].update(end=min(end,f['time']+.5),last_frame=f['index'])
        else:rows.append({'start':f['time'],'end':min(end,f['time']+.5),'text':text,'first_frame':f['index'],'last_frame':f['index']})
    return rows

def prepare(source,work,platform,content_id,source_sha256,duration,start=0,seconds=None,native=None,crop_top=.67,crop_bottom=.82):
    STAGE.update(name='preflight',frame_index=None,returncode=None)
    if platform not in ('xiaohongshu','douyin','bilibili','kuaishou','weibo','zhihu','tieba') or not isinstance(content_id,str) or not re.fullmatch(r'[A-Za-z0-9_:-]{1,100}',content_id):raise ValueError('invalid_video_ocr_identity')
    source=Path(source);work=Path(work)
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in (crop_top,crop_bottom)) or not 0<=crop_top<crop_bottom<=1 or crop_bottom-crop_top<.05:raise ValueError('invalid_video_ocr_crop')
    crop_height=crop_bottom-crop_top;subtitle_band=(crop_top+.02,crop_bottom-.02)
    if source.is_symlink() or not source.is_file() or source.stat().st_size>256*1024*1024 or digest(source)!=source_sha256:raise ValueError('video_ocr_source_changed')
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<duration<=7200:raise ValueError('invalid_video_ocr_duration')
    seconds=duration-start if seconds is None else seconds
    if not 0<=start<duration or not 0<seconds<=duration-start:raise ValueError('invalid_video_ocr_range')
    if any(p.is_symlink() for p in (work,*work.parents)):raise ValueError('unsafe_video_ocr_work')
    work.mkdir(parents=True,exist_ok=True)
    if any(work.iterdir()):raise ValueError('video_ocr_existing_work')
    ffmpeg=os.environ.get('CROWD_FFMPEG') or shutil.which('ffmpeg')
    if not ffmpeg or not Path(ffmpeg).is_file():raise ValueError('video_ocr_ffmpeg_unavailable')
    executable=Path(native) if native else ROOT/'crowd-video-vision'
    command=[str(executable)] if executable.is_file() else ['swift','-module-cache-path',str(work/'swift-cache'),str(ROOT/'video_vision.swift')]
    begin=time.monotonic();cpu=resource.getrusage(resource.RUSAGE_CHILDREN);frames=[];decode_seconds=0
    original=source.stat();proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
    def check():
        if (work/'cancel.requested').exists():raise ValueError('video_ocr_cancelled')
        if time.monotonic()-begin>1800:raise ValueError('video_ocr_timeout')
    try:
        for offset in range(0,math.ceil(seconds),20):
            check();span=min(20,seconds-offset)
            with tempfile.TemporaryDirectory(prefix='frames-',dir=work) as tmp:
                pattern=str(Path(tmp)/'%06d.jpg')
                decode_started=time.monotonic()
                STAGE.update(name='decode',frame_index=len(frames),returncode=None)
                task=subprocess.Popen([ffmpeg,'-v','error','-xerror','-nostdin','-protocol_whitelist','file,pipe','-ss',str(start+offset),'-t',str(span),'-i',str(source),'-vf','tpad=stop_mode=clone:stop_duration=0.5,fps=fps=2:start_time=0:round=near,crop=iw:ih*%s:0:ih*%s'%(crop_height,crop_top),'-frames:v',str(math.ceil(span*FPS)),'-q:v','3',pattern],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                while task.poll() is None:
                    try:check()
                    except BaseException:task.kill();task.wait();raise
                    time.sleep(.1)
                STAGE['returncode']=task.returncode
                if task.returncode:raise ValueError('video_ocr_frame_decode_failed')
                decode_seconds+=time.monotonic()-decode_started
                images=sorted(Path(tmp).glob('*.jpg'))
                if len(images)!=math.ceil(span*FPS) or sum(p.stat().st_size for p in images)>512*1024*1024:raise ValueError('video_ocr_sample_incomplete')
                for image in images:
                    check();index=len(frames)
                    STAGE.update(name='native',frame_index=index,returncode=None)
                    proc.stdin.write(json.dumps({'path':str(image),'index':index})+'\n');proc.stdin.flush()
                    if not select.select([proc.stdout],[],[],60)[0]:raise ValueError('video_ocr_native_timeout')
                    raw=proc.stdout.readline()
                    check()
                    if not raw:
                        STAGE['returncode']=proc.poll()
                        raise ValueError('video_ocr_native_failed')
                    if len(raw)>100000:raise ValueError('invalid_video_ocr_native')
                    value=json.loads(raw)
                    if value.get('index')!=index or value.get('truncated') is not False or not isinstance(value.get('blocks'),list) or len(value['blocks'])>50:raise ValueError('invalid_video_ocr_native')
                    blocks=[]
                    for b in value['blocks']:
                        box=b['bbox'];confidence=b['confidence'];text=b['text']
                        if not isinstance(text,str) or not 0<len(text)<=500 or type(confidence) not in (int,float) or not math.isfinite(confidence) or not 0<=confidence<=1:raise ValueError('invalid_video_ocr_native')
                        geometry=project_geometry(box,crop_top,crop_bottom);fullbox=geometry['bbox']
                        blocks.append({'text':text,'confidence':confidence,**geometry,
                                       'selected':subtitle_band[0]<=fullbox[1]+fullbox[3]/2<=subtitle_band[1]})
                    # Vision observations are not guaranteed reading-order sorted.
                    blocks.sort(key=lambda b:(round(b['bbox'][1],2),b['bbox'][0]))
                    latency=value.get('native_seconds')
                    if type(latency) not in (int,float) or not math.isfinite(latency) or not 0<=latency<=60:raise ValueError('invalid_video_ocr_native')
                    frames.append({'index':index,'time':round(start+offset+(int(image.stem)-1)/FPS,3),'sha256':digest(image),'blocks':blocks,'native_seconds':latency})
            (work/'state.json').write_text(json.dumps({'state':'processing','processed_frames':len(frames),'expected_frames':math.ceil(seconds*FPS)}))
        proc.stdin.close();proc.wait(timeout=30)
        STAGE['returncode']=proc.returncode
        if proc.returncode:raise ValueError('video_ocr_native_failed')
        STAGE.update(name='proof',frame_index=len(frames),returncode=proc.returncode)
        current=source.stat()
        if any(getattr(original,k)!=getattr(current,k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')) or digest(source)!=source_sha256:raise ValueError('video_ocr_source_changed')
        encoded=json.dumps(frames,ensure_ascii=False,separators=(',',':')).encode();proof=gzip.compress(encoded,mtime=0)
        if len(encoded)>4*1024*1024 or len(proof)>2*1024*1024:raise ValueError('video_ocr_frame_evidence_limit')
        (work/'frames.json.gz').write_bytes(proof)
        rows=merge_frames(frames,start+seconds);usage=resource.getrusage(resource.RUSAGE_CHILDREN)
        evidence={'processor':'apple_vision_sampled_video_text','source_kind':'sampled_video_text','asset_sha256':source_sha256,'duration_seconds':duration,'segments':rows,'timeline':'absolute_seconds','sample_fps':FPS,'crop_top_origin':[crop_top,crop_bottom],'timestamp_kind':'resampled_frame_time','timestamp_uncertainty_seconds':.5,'sample_start':start,'sample_end':start+seconds,'sampled_frames':len(frames),'expected_frames':math.ceil(seconds*FPS),'frame_evidence_sha256':hashlib.sha256(proof).hexdigest(),'frame_evidence_file':'frames.json.gz','semantic_status':'not_reviewed','cer':None,'spoken_transcript':False,'coverage':'every_2fps_sample_in_selected_crop; short_or_outside_subtitles_may_be_missing','truncated':False,'wall_seconds':time.monotonic()-begin,'child_cpu_seconds':usage.ru_utime+usage.ru_stime-cpu.ru_utime-cpu.ru_stime,'peak_child_rss_bytes':usage.ru_maxrss,'network_requests':0,'asr_model_calls':0}
        result=[{'kind':'video_text','platform':platform,'content_id':content_id,'evidence':evidence}]
        evidence.update(frame_decode_seconds=decode_seconds,native_ocr_seconds=sum(f['native_seconds'] for f in frames),
                        first_native_seconds=frames[0]['native_seconds'] if frames else None,
                        crop_top_origin=[crop_top,crop_bottom],subtitle_band_top_origin=list(subtitle_band),eof_partial_frame_policy='nearest_last_decoded_frame',
                        timestamp_uncertainty_seconds=.5,provider_source_sha256=digest(ROOT/'video_vision.swift'),
                        compiled_binary_sha256=digest(executable) if executable.is_file() else None,
                        provider_execution_mode='compiled_binary' if executable.is_file() else 'swift_source_interpreter',macos_version=system_platform.mac_ver()[0])
        evidence['segment_frame_ranges']=[[r.pop('first_frame'),r.pop('last_frame')] for r in rows]
        output=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()
        if len(output)>LIMIT:raise ValueError('video_ocr_report_limit')
        (work/'result.json').write_bytes(output);(work/'state.json').write_text(json.dumps({'state':'completed','processed_frames':len(frames),'expected_frames':math.ceil(seconds*FPS)}))
        return result
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
        if not proc.stdin.closed:proc.stdin.close()
        proc.stdout.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--work-dir',required=True);p.add_argument('--platform',required=True);p.add_argument('--content-id',required=True);p.add_argument('--source-sha256',required=True);p.add_argument('--duration',type=float,required=True);p.add_argument('--start',type=float,default=0);p.add_argument('--seconds',type=float);p.add_argument('--native');p.add_argument('--crop-top',type=float,default=.67);p.add_argument('--crop-bottom',type=float,default=.82);a=p.parse_args()
    try:prepare(a.input,a.work_dir,a.platform,a.content_id,a.source_sha256,a.duration,a.start,a.seconds,a.native,a.crop_top,a.crop_bottom)
    except Exception as error:
        diagnostic=failure_diagnostic(error)
        sys.stderr.write(json.dumps(diagnostic,ensure_ascii=False)+'\n')
        parent=Path(a.work_dir).parent
        try:
            if parent.is_dir() and not any(p.is_symlink() for p in (parent,*parent.parents)):
                with os.fdopen(os.open(parent/'video-ocr-error.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as stream:json.dump(diagnostic,stream,ensure_ascii=False)
        except OSError:pass
        raise SystemExit(1)
