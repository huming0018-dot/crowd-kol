"""One-slot local sampled-video-text jobs, separate from ASR and source captures."""
import fcntl,gzip,hashlib,io,json,math,os,re,subprocess,threading,time,uuid
from pathlib import Path
from analysis_artifact import _read,_safe_ancestors
from complete_video import read_bytes
from light_audio_fallback import reference
from mc_runner import uid,write

ROOT=Path(__file__).resolve().parent.parent/'postprocess'
FILES=('video_ocr.py','video_vision.swift')
PROFILE='apple_vision_video_hard_text_2fps_v1'
HEX=re.compile(r'[a-f0-9]{64}')

def sha(path):
    h=hashlib.sha256()
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()

def source(jobs,parent_id,run_folder):
    parent_id=uid(parent_id);folder=jobs.root/parent_id;run_folder=Path(run_folder)
    parent,_=_read(folder/'state.json',200000);progress,_=_read(folder/'video-progress.json',10000)
    if parent.get('job_id')!=parent_id or parent.get('kind') not in ('complete_audio','complete_video') or parent.get('state') not in ('completed','failed') or parent.get('platform')!='douyin' or run_folder.name!=parent.get('run_id'):raise ValueError('video_ocr_parent_invalid')
    fresh,body_hash=reference(run_folder,parent['run_id'],parent['content_id'])
    manifest,_=_read(run_folder/'manifest.json',200000);status,_=_read(run_folder/'status.json',200000)
    if manifest.get('run_id')!=parent['run_id'] or status.get('run_id')!=parent['run_id'] or status.get('state')!='completed' or parent.get('source_reference_sha256')!=fresh['reference_sha256']:raise ValueError('video_ocr_source_binding_changed')
    expected_sha=progress.get('source_sha256');expected_bytes=progress.get('downloaded_bytes')
    if parent.get('state')=='completed':
        result,result_sha=_read(folder/'result.json',200000)
        if result_sha!=parent.get('result_sha256') or len(result)!=1:raise ValueError('video_ocr_parent_changed')
        evidence=result[0]['evidence'];expected_sha=evidence.get('source_asset_sha256');expected_bytes=evidence.get('source_bytes')
    path=folder/'source.mp4';_safe_ancestors(path)
    if not isinstance(expected_sha,str) or not HEX.fullmatch(expected_sha) or type(expected_bytes) is not int or not 0<expected_bytes<=256*1024*1024 or path.is_symlink() or not path.is_file() or path.stat().st_nlink!=1 or path.stat().st_size!=expected_bytes or sha(path)!=expected_sha:raise ValueError('video_ocr_source_changed')
    return path,{'video_source_job_id':parent_id,'run_id':parent['run_id'],'platform':'douyin','content_id':parent['content_id'],
                 'entity_ref':'douyin:content:'+parent['content_id'],'asset_sha256':expected_sha,'source_bytes':expected_bytes,
                 'source_record_sha256':body_hash,'source_reference_sha256':fresh['reference_sha256']}

def native_configuration():
    native=os.environ.get('CROWD_VIDEO_OCR_NATIVE')
    if not native:raise ValueError('video_ocr_native_not_configured')
    path=Path(native);_safe_ancestors(path)
    if path.is_symlink() or not path.is_file() or not os.access(path,os.X_OK):raise ValueError('video_ocr_native_not_configured')
    expected_source=read_bytes(path.parent/'native.source.sha256',100).decode().strip()
    expected_binary=read_bytes(path.parent/'native.binary.sha256',100).decode().strip()
    if expected_source!=sha(ROOT/'video_vision.swift') or expected_binary!=sha(path):raise ValueError('video_ocr_native_changed')
    return path,expected_binary

def start(jobs,source_job_id,run_folder,crop_top=.67,crop_bottom=.82):
    path,binding=source(jobs,source_job_id,run_folder);native,binary_sha=native_configuration()
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in (crop_top,crop_bottom)) or not 0<=crop_top<crop_bottom<=1 or crop_bottom-crop_top<.05:raise ValueError('invalid_video_ocr_crop')
    ffmpeg=os.environ.get('CROWD_FFMPEG')
    if not ffmpeg or not Path(ffmpeg).is_file():raise ValueError('video_ocr_ffmpeg_unavailable')
    probe=subprocess.run([ffmpeg,'-hide_banner','-protocol_whitelist','file,pipe','-f','mov','-i',str(path)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=30)
    text=probe.stderr.decode('utf8',errors='replace');matched=re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)',text)
    if len(probe.stderr)>1024*1024 or not matched or 'Video:' not in text:raise ValueError('video_ocr_duration_unverified')
    duration=int(matched[1])*3600+int(matched[2])*60+float(matched[3])
    if not 0<duration<=7200:raise ValueError('invalid_video_ocr_duration')
    files={name:sha(ROOT/name) for name in FILES}
    identity={**binding,'duration_seconds':duration,'processing_profile':PROFILE,'processor_files':files,'compiled_binary_sha256':binary_sha,'crop_top':crop_top,'crop_bottom':crop_bottom}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    with jobs.lock:
        if jobs.closed:raise ValueError('media_processor_closed')
        for folder in jobs.root.iterdir():
            if folder.is_dir() and not folder.is_symlink() and (folder/'state.json').is_file():
                saved=jobs.status(folder.name)
                if saved.get('input_hash')==key:return {**saved,'reused_existing_job':True,'cached':saved['state']=='completed'}
                if saved['state']=='interrupted_unknown':raise ValueError('media_processor_reconciliation_required')
        if any(t.is_alive() for t in jobs.threads.values()):raise ValueError('media_processor_busy')
        lock=os.fdopen(os.open(jobs.root/'processor.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600),'a+')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:lock.close();raise ValueError('media_processor_busy') from None
        if os.fstat(lock.fileno()).st_nlink!=1:lock.close();raise ValueError('unsafe_video_ocr_work')
        try:
            job_id=str(uuid.uuid4());folder=jobs.root/job_id;folder.mkdir(mode=0o700)
            state={**identity,'job_id':job_id,'kind':'video_ocr','state':'queued','input_hash':key,'created_at':time.time(),'source_kind':'sampled_video_text','uploaded':False,'network_attempts':0,'model_calls':0,'run_folder':str(Path(run_folder).resolve())}
            write(folder/'state.json',state)
            thread=threading.Thread(target=execute,args=(jobs,state,path,native,lock),daemon=True);jobs.threads[job_id]=thread;thread.start()
            return state
        except BaseException:lock.close();raise

def execute(jobs,state,path,native,lock):
    folder=jobs.root/state['job_id'];job_id=state['job_id'];proc=None
    try:
        configured,binary_sha=native_configuration()
        if configured!=native or binary_sha!=state['compiled_binary_sha256'] or any(sha(ROOT/name)!=value for name,value in state['processor_files'].items()):raise ValueError('video_ocr_native_changed')
        with jobs.lock:
            if jobs.closed or job_id in jobs.cancelled:state.update(state='cancelled');return
            command=[jobs.python,str(ROOT/'video_ocr.py'),'--input',str(path),'--work-dir',str(folder/'video-ocr'),'--platform',state['platform'],'--content-id',state['content_id'],'--source-sha256',state['asset_sha256'],'--duration',str(state['duration_seconds']),'--native',str(native),'--crop-top',str(state['crop_top']),'--crop-bottom',str(state['crop_bottom'])]
            proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,pass_fds=(lock.fileno(),))
            jobs.processes[job_id]=proc;state.update(state='running',processor_pid=proc.pid);write(folder/'state.json',state)
        proc.wait(timeout=1830)
        if job_id in jobs.cancelled:state.update(state='cancelled')
        elif proc.returncode:state.update(state='failed',reason='video_ocr_local_processing_failed')
        else:
            result,_=_read(folder/'video-ocr/result.json',200000);write(folder/'result.json',result)
            candidate={**state,'state':'completed','result_sha256':sha(folder/'result.json')}
            _validate(jobs,job_id,candidate)
            state.update(candidate)
    except subprocess.TimeoutExpired:jobs._kill(proc);state.update(state='failed',reason='video_ocr_timeout')
    except (OSError,ValueError,TypeError,KeyError,IndexError):jobs._kill(proc);state.update(state='failed',reason='video_ocr_result_or_source_changed')
    finally:
        with jobs.lock:
            jobs.processes.pop(job_id,None)
            if job_id in jobs.cancelled:state.update(state='cancelled')
            write(folder/'state.json',{**state,'finished_at':time.time()})
        lock.close()

def load_video_ocr(jobs,job_id):
    job_id=uid(job_id);folder=jobs.root/job_id;state,_=_read(folder/'state.json',200000)
    return _validate(jobs,job_id,state)

def _validate(jobs,job_id,state):
    folder=jobs.root/job_id
    if state.get('job_id')!=job_id or state.get('kind')!='video_ocr' or state.get('state')!='completed':raise ValueError('video_ocr_not_completed')
    _,binding=source(jobs,state['video_source_job_id'],Path(state['run_folder']))
    if any(state.get(k)!=v for k,v in binding.items()):raise ValueError('video_ocr_source_binding_changed')
    files=state.get('processor_files');_,binary_sha=native_configuration()
    if not isinstance(files,dict) or set(files)!=set(FILES) or any(sha(ROOT/name)!=value for name,value in files.items()) or binary_sha!=state.get('compiled_binary_sha256') or state.get('processing_profile')!=PROFILE:raise ValueError('video_ocr_processor_changed')
    identity={**binding,**{key:state.get(key) for key in ('duration_seconds','processing_profile','processor_files','compiled_binary_sha256','crop_top','crop_bottom')}}
    if hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()!=state.get('input_hash'):raise ValueError('video_ocr_input_hash_changed')
    result,result_sha=_read(folder/'result.json',200000)
    if result_sha!=state.get('result_sha256') or not isinstance(result,list) or len(result)!=1 or result[0].get('kind')!='video_text' or any(result[0].get(k)!=state[k] for k in ('platform','content_id')):raise ValueError('video_ocr_result_changed')
    e=result[0]['evidence'];duration=state['duration_seconds']
    if e.get('frame_evidence_file')!='frames.json.gz':raise ValueError('video_ocr_frames_invalid')
    if e.get('processor')!='apple_vision_sampled_video_text' or e.get('source_kind')!='sampled_video_text' or e.get('spoken_transcript') is not False or e.get('cer') is not None or e.get('truncated') is not False or e.get('asset_sha256')!=state['asset_sha256'] or e.get('sample_start')!=0 or e.get('sample_end')!=duration or e.get('duration_seconds')!=duration or e.get('sample_fps')!=2 or e.get('timestamp_uncertainty_seconds')!=.5 or e.get('crop_top_origin')!=[state['crop_top'],state['crop_bottom']] or e.get('compiled_binary_sha256')!=state['compiled_binary_sha256'] or e.get('provider_source_sha256')!=state['processor_files']['video_vision.swift']:raise ValueError('video_ocr_coverage_incomplete')
    data=read_bytes(folder/'video-ocr/frames.json.gz',2*1024*1024)
    if hashlib.sha256(data).hexdigest()!=e.get('frame_evidence_sha256'):raise ValueError('video_ocr_frames_changed')
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as archive:raw=archive.read(4*1024*1024+1)
    except (OSError,EOFError):raise ValueError('video_ocr_frames_invalid') from None
    if len(raw)>4*1024*1024:raise ValueError('video_ocr_frames_limit')
    frames=json.loads(raw);count=math.ceil(duration*2)
    if not isinstance(frames,list) or len(frames)!=count or e.get('sampled_frames')!=count or e.get('expected_frames')!=count:raise ValueError('video_ocr_coverage_incomplete')
    for index,frame in enumerate(frames):
        if set(frame)!={'index','time','sha256','blocks','native_seconds'} or type(frame['index']) is not int or frame['index']!=index or frame['time']!=index*.5 or not isinstance(frame['sha256'],str) or not HEX.fullmatch(frame['sha256']) or not isinstance(frame['blocks'],list) or len(frame['blocks'])>50:raise ValueError('video_ocr_frames_invalid')
        if type(frame['time']) not in (int,float) or not math.isfinite(frame['time']):raise ValueError('video_ocr_frames_invalid')
        if type(frame['native_seconds']) not in (int,float) or not math.isfinite(frame['native_seconds']) or not 0<=frame['native_seconds']<=60:raise ValueError('video_ocr_frames_invalid')
        for b in frame['blocks']:
            if set(b)!={'text','confidence','bbox','selected'} or not isinstance(b['text'],str) or not 0<len(b['text'])<=500 or type(b['selected']) is not bool or type(b['confidence']) not in (int,float) or not math.isfinite(b['confidence']) or not 0<=b['confidence']<=1 or not isinstance(b['bbox'],list) or len(b['bbox'])!=4 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in b['bbox']):raise ValueError('video_ocr_frames_invalid')
            if b['bbox'][0]+b['bbox'][2]>1+1e-6 or b['bbox'][1]+b['bbox'][3]>1+1e-6:raise ValueError('video_ocr_frames_invalid')
            center=b['bbox'][1]+b['bbox'][3]/2
            if b['selected']!=(state['crop_top']+.02<=center<=state['crop_bottom']-.02):raise ValueError('video_ocr_frames_invalid')
    import importlib.util
    spec=importlib.util.spec_from_file_location('crowd_video_ocr',ROOT/'video_ocr.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    merged=module.merge_frames(frames,duration);ranges=[[s.pop('first_frame'),s.pop('last_frame')] for s in merged]
    if e.get('segments')!=merged or e.get('segment_frame_ranges')!=ranges:raise ValueError('video_ocr_segments_changed')
    return {'state':state,'evidence':e,'result':result,'result_sha256':result_sha}
