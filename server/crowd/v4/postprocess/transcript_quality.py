"""Read ASR review candidates and save explicit text revisions without inference."""
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import time
import uuid

MAX_SEGMENTS=8000
MAX_EDITS=50
MAX_CHARACTERS=240000
HASH=re.compile(r'[a-f0-9]{64}')
FLAGS=frozenset(('low_logprob','high_compression','possible_no_speech','repeated_adjacent_text'))


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def text_hash(value):return hashlib.sha256(value.encode()).hexdigest()
def job_id(value):
    try:
        parsed=str(uuid.UUID(value))
        if parsed!=value:raise ValueError()
        return parsed
    except (ValueError,TypeError,AttributeError):raise ValueError('invalid_transcript_job_id') from None
def ancestors(path):
    aliases={'/tmp':'/private/tmp','/var':'/private/var'}
    for part in (Path(path).absolute(),*Path(path).absolute().parents):
        if part.is_symlink() and not (str(part) in aliases and str(part.resolve())==aliases[str(part)]):raise ValueError('unsafe_transcript_quality_path')
def read_json(path,limit=8*1024*1024):
    ancestors(path);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=os.getuid() or before.st_size>limit:raise ValueError('unsafe_transcript_quality_file')
        raw=os.read(fd,limit+1);after=os.fstat(fd)
        if len(raw)>limit or (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('transcript_quality_file_changed')
        return json.loads(raw),hashlib.sha256(raw).hexdigest()
    finally:os.close(fd)
def audio_hash(path):
    ancestors(path);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=os.getuid() or before.st_size>64*1024*1024:raise ValueError('unsafe_transcript_quality_audio')
        digest=hashlib.sha256()
        while True:
            raw=os.read(fd,1024*1024)
            if not raw:break
            digest.update(raw)
        after=os.fstat(fd)
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('transcript_quality_file_changed')
        return digest.hexdigest()
    finally:os.close(fd)
def write_json(path,value):
    with path.open('x',encoding='utf8') as stream:
        os.chmod(path,0o600);stream.write(canonical(value));stream.flush();os.fsync(stream.fileno())
def finite(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except OverflowError:return False

def optimizer():
    spec=importlib.util.spec_from_file_location('crowd_transcript_optimize',Path(__file__).with_name('transcript_optimize.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class TranscriptQuality:
    def __init__(self,root):
        ancestors(Path(root));self.root=Path(root).resolve()/'media-processing'
    def _chunks(self,saved):
        path=self.root/saved['audio_source_job_id']/'long-asr/chunks.json'
        return read_json(path,65536)[0]['chunks'] if path.is_file() else []
    def _removal(self,saved,index,retained):
        return optimizer().overlap_removal(saved['evidence']['segments'],self._chunks(saved),index,retained)
    def _load(self,identity,chain=()):
        identity=job_id(identity)
        if identity in chain or len(chain)>=8:raise ValueError('transcript_revision_cycle')
        folder=self.root/identity;state,_=read_json(folder/'state.json',65536);result,digest=read_json(folder/'result.json')
        if state.get('job_id')!=identity or state.get('state')!='completed' or state.get('kind')!='asr':raise ValueError('transcript_quality_not_completed')
        if state.get('result_sha256') is not None and state['result_sha256']!=digest:raise ValueError('transcript_quality_result_changed')
        if not isinstance(result,list) or len(result)!=1 or not isinstance(result[0],dict):raise ValueError('invalid_transcript_quality_result')
        record=result[0];evidence=record.get('evidence',{})
        if (record.get('kind')!='transcript' or record.get('platform')!=state.get('platform')
                or record.get('content_id')!=state.get('content_id') or evidence.get('source_kind')!='authorized_local_file'
                or not isinstance(state.get('asset_sha256'),str) or not HASH.fullmatch(state['asset_sha256'])
                or evidence.get('asset_sha256')!=state['asset_sha256']):raise ValueError('transcript_quality_identity_mismatch')
        rows=evidence.get('segments');duration=evidence.get('duration_seconds')
        if not isinstance(rows,list) or not 1<=len(rows)<=MAX_SEGMENTS or not finite(duration) or not 0<duration<=7200:raise ValueError('invalid_transcript_quality_segments')
        characters=0
        for row in rows:
            if (not isinstance(row,dict) or not {'start','end','text'}<=set(row)<= {'start','end','text','chunk_index'}
                    or 'chunk_index' in row and (type(row['chunk_index']) is not int or not 0<=row['chunk_index']<512)
                    or not isinstance(row['text'],str) or not row['text'].strip()
                    or len(row['text'])>24000 or any(not finite(row[key]) for key in ('start','end')) or not 0<=row['start']<=row['end']<=duration):raise ValueError('invalid_transcript_quality_segments')
            characters+=len(row['text'])
        if characters>MAX_CHARACTERS:raise ValueError('transcript_quality_text_limit')
        revision=state.get('text_revision')
        if revision is not None:
            if (not isinstance(revision,dict) or revision.get('reviewer_kind') not in ('human_manual','machine_suggestion')
                    or revision.get('semantic_status')!='not_reviewed' or revision.get('human_groundtruth') is not False
                    or not isinstance(revision.get('edits'),list) or type(revision.get('edited_segments')) is not int
                    or not 1<=revision['edited_segments']==len(revision['edits'])<=MAX_EDITS):raise ValueError('transcript_revision_parent_changed')
            parent=self._load(revision.get('source_job_id'),chain+(identity,))
            if (parent['result_sha256']!=revision.get('source_result_sha256')
                    or any(canonical(state.get(key))!=canonical(parent['state'].get(key)) for key in ('platform','content_id','run_id','asset_sha256','entity_ref'))
                    or canonical(evidence.get('text_revision'))!=canonical(revision)
                    or canonical(evidence.get('quality_diagnostics'))!=canonical(parent['evidence'].get('quality_diagnostics'))
                    ):raise ValueError('transcript_revision_parent_changed')
            mutable_evidence={'segments','raw_text','truncated','text_revision'}
            mutable_state={'job_id','created_at','finished_at','input_hash','result_sha256','text_revision','source_job_id','processor_pid','review_status'}
            if (canonical({k:v for k,v in evidence.items() if k not in mutable_evidence})!=canonical({k:v for k,v in parent['evidence'].items() if k not in mutable_evidence})
                    or canonical({k:v for k,v in state.items() if k not in mutable_state})!=canonical({k:v for k,v in parent['state'].items() if k not in mutable_state})
                    or canonical({k:v for k,v in record.items() if k!='evidence'})!=canonical({k:v for k,v in parent['result'][0].items() if k!='evidence'})):
                raise ValueError('transcript_revision_parent_changed')
            expected=copy.deepcopy(parent['evidence']['segments']);seen=set();removed=set();retained_targets=set()
            for edit in revision['edits']:
                index=edit.get('segment_index')
                deletion='removed_overlap_with' in edit
                fields={'segment_index','original_text','original_text_sha256','revised_text_sha256','start','end'}
                if (set(edit)!=fields|({'removed_overlap_with','overlap_proof'} if deletion else set())
                        or type(index) is not int or not 0<=index<len(expected) or index in seen):raise ValueError('transcript_revision_parent_changed')
                seen.add(index);prior=expected[index]
                if deletion:
                    target=edit['removed_overlap_with'];proof=self._removal(parent,index,target)
                    if (proof is None or canonical(proof)!=canonical(edit['overlap_proof'])
                            or edit['revised_text_sha256'] is not None):raise ValueError('transcript_revision_parent_changed')
                    removed.add(index);retained_targets.add(target)
                    revised=prior['text']
                else:
                    # Edited positions are parent indexes, even after earlier removals.
                    final_index=index-sum(value<index for value in removed)
                    if not 0<=final_index<len(rows) or len(rows[final_index]['text'])>2000:raise ValueError('transcript_revision_parent_changed')
                    revised=rows[final_index]['text']
                if (edit.get('original_text')!=prior['text'] or edit.get('original_text_sha256')!=text_hash(prior['text'])
                        or not deletion and edit.get('revised_text_sha256')!=text_hash(revised)
                        or (edit.get('start'),edit.get('end'))!=(prior['start'],prior['end'])):raise ValueError('transcript_revision_parent_changed')
                prior['text']=revised
            expected=[row for index,row in enumerate(expected) if index not in removed]
            if removed&retained_targets:raise ValueError('transcript_revision_parent_changed')
            if (canonical(rows)!=canonical(expected) or revision.get('audio_source_job_id')!=parent['audio_source_job_id']
                    or state.get('source_job_id')!=parent['audio_source_job_id']):raise ValueError('transcript_revision_parent_changed')
            text='\n'.join('[%.2f–%.2f] %s'%(row['start'],row['end'],row['text']) for row in rows)
            if (evidence.get('raw_text')!=text[:24000] or evidence.get('truncated') is not (len(text)>24000)
                    or state.get('input_hash')!=text_hash(canonical({'source':parent['result_sha256'],'revision':revision}))
                    or state.get('review_status')!='not_reviewed'):
                raise ValueError('transcript_revision_parent_changed')
            source=parent['audio_source_job_id']
            depth=parent['revision_depth']+1
        else:
            inputs=list(folder.glob('input.*'))
            if len(inputs)!=1 or audio_hash(inputs[0])!=state['asset_sha256']:raise ValueError('transcript_quality_audio_unverified')
            source=identity
            depth=0
        if evidence.get('processor') in ('faster_whisper_local_segmented','mlx_whisper_local_segmented'):
            checkpoint,_=read_json(folder/'long-asr/state.json',65536)
            # Fresh parent state need not mirror counters; revisions keep the original audio manifest.
            manifest,_=read_json(self.root/source/'long-asr/chunks.json',65536)
            total=checkpoint.get('total_chunks');chunks=manifest.get('chunks')
            if (checkpoint.get('state')!='completed' or type(total) is not int or not 0<total<=512
                    or type(checkpoint.get('completed_chunks')) is not int or checkpoint['completed_chunks']!=total
                    or 'total_chunks' in state and (type(state['total_chunks']) is not int or state['total_chunks']!=total)
                    or type(evidence.get('audio_windows_processed')) is not int or evidence['audio_windows_processed']!=total
                    or type(manifest.get('schema')) is not int or manifest['schema']!=1 or manifest.get('asset_sha256')!=state['asset_sha256']
                    or not finite(manifest.get('duration_seconds')) or manifest['duration_seconds']!=duration
                    or not isinstance(chunks,list) or len(chunks)!=total
                    or any(not isinstance(row,dict) or type(row.get('index')) is not int or row['index']!=index for index,row in enumerate(chunks))):raise ValueError('transcript_quality_checkpoint_incomplete')
        return {'job_id':identity,'folder':folder,'state':state,'result':result,'result_sha256':digest,'evidence':evidence,'audio_source_job_id':source,'revision_depth':depth}
    def validate(self,identity):
        try:return self._load(identity)
        except (KeyError,TypeError,IndexError,OSError,AttributeError):raise ValueError('invalid_transcript_quality_files') from None
    def lookup(self,identity):
        saved=self.validate(identity);evidence=saved['evidence'];diagnostic=evidence.get('quality_diagnostics',{})
        native=diagnostic.get('segments',[]) if isinstance(diagnostic,dict) else []
        if not isinstance(native,list) or len(native)>16000:raise ValueError('invalid_transcript_quality_diagnostics')
        candidates=[];counts={flag:0 for flag in FLAGS};recorded=0
        for index,row in enumerate(native):
            if not isinstance(row,dict):raise ValueError('invalid_transcript_quality_diagnostics')
            metrics={key:row.get(key) if finite(row.get(key)) else None for key in ('avg_logprob','compression_ratio','no_speech_prob')}
            if metrics['no_speech_prob'] is not None and not 0<=metrics['no_speech_prob']<=1:metrics['no_speech_prob']=None
            if metrics['compression_ratio'] is not None and metrics['compression_ratio']<0:metrics['compression_ratio']=None
            recorded+=sum(value is not None for value in metrics.values())
            if not isinstance(row.get('flags',[]),list):raise ValueError('invalid_transcript_quality_diagnostics')
            flags=list(dict.fromkeys(flag for flag in row.get('flags',[]) if isinstance(flag,str) and flag in FLAGS))
            for flag in flags:counts[flag]+=1
            if flags and (not isinstance(row.get('text'),str) or any(not finite(row.get(key)) for key in ('start','end'))
                    or not 0<=row['start']<=row['end']<=evidence['duration_seconds']):raise ValueError('invalid_transcript_quality_diagnostics')
            if flags:candidates.append({'diagnostic_index':index,'chunk_index':row.get('chunk_index'),'segment_index':row.get('segment_index'),
                                       'start':row.get('start'),'end':row.get('end'),'text':row.get('text'),**metrics,'flags':flags,
                                       'basis':'original_window_not_corrected_or_merged_text'})
        cursor=0.;gaps=[]
        for row in sorted(evidence['segments'],key=lambda value:(value['start'],value['end'])):
            if row['start']-cursor>=5:gaps.append({'start':cursor,'end':row['start'],'basis':'no_transcript_text_not_proven_silence_or_missing_speech'})
            cursor=max(cursor,row['end'])
        if evidence['duration_seconds']-cursor>=5:gaps.append({'start':cursor,'end':evidence['duration_seconds'],'basis':'no_transcript_text_not_proven_silence_or_missing_speech'})
        return {'ok':True,'job_id':saved['job_id'],'source_job_id':saved['audio_source_job_id'],
                'result_sha256':saved['result_sha256'],'asset_sha256':saved['state']['asset_sha256'],
                'platform':saved['state']['platform'],'content_id':saved['state']['content_id'],
                'segments':[{'segment_index':i,**row,'text_sha256':text_hash(row['text'])} for i,row in enumerate(evidence['segments'])],
                'quality':{'review_status':'not_reviewed','cer':None,'human_reference':None,
                           'native_metric_status':'available' if native and recorded==len(native)*3 else 'partial' if recorded else 'unknown',
                           'original_diagnostic_segments':len(native),'flag_counts':counts,'candidates':candidates,
                           'overlap_decisions':evidence.get('overlap_decisions',[]),'no_text_windows':evidence.get('no_text_windows'),
                           'untranscribed_intervals':sorted(gaps,key=lambda row:row['end']-row['start'],reverse=True)[:100],
                           'untranscribed_intervals_total':len(gaps),'untranscribed_seconds':sum(row['end']-row['start'] for row in gaps),
                           'automatic_text_replacement':False,'confidence_is_accuracy':False},
                'text_revision':saved['state'].get('text_revision'),'source_requests':0,'model_calls':0}
    def optimization_preview(self,identity,source_context=None,references=None):
        saved=self.validate(identity)
        plan=optimizer().plan(saved['evidence'],self._chunks(saved),source_context,references)
        return {'ok':True,'job_id':saved['job_id'],'result_sha256':saved['result_sha256'],**plan}
    def create_optimized_revision(self,identity,expected_result_sha256,expected_plan_sha256,source_context=None,references=None):
        plan=self.optimization_preview(identity,source_context,references)
        if plan['result_sha256']!=expected_result_sha256 or plan['plan_sha256']!=expected_plan_sha256:
            raise ValueError('transcript_optimization_stale_plan')
        edits=[{key:value for key,value in edit.items() if key!='basis'} for edit in plan['edits']]
        return self.create_revision(identity,expected_result_sha256,edits,'machine_suggestion',True,optimization_plan=plan)
    def create_revision(self,identity,expected_result_sha256,edits,reviewer_kind,acknowledge_new_version,optimization_plan=None):
        if (acknowledge_new_version is not True or reviewer_kind not in ('human_manual','machine_suggestion')
                or not isinstance(expected_result_sha256,str) or not HASH.fullmatch(expected_result_sha256)
                or not isinstance(edits,list) or not 1<=len(edits)<=MAX_EDITS):raise ValueError('invalid_transcript_revision_request')
        saved=self.validate(identity)
        if saved['revision_depth']>=7:raise ValueError('transcript_revision_chain_limit')
        if saved['result_sha256']!=expected_result_sha256:raise ValueError('transcript_revision_stale_result')
        result=copy.deepcopy(saved['result']);rows=result[0]['evidence']['segments'];seen=set();proof=[];removed=set();retained_targets=set()
        edits=sorted(edits,key=lambda edit:edit.get('segment_index',-1) if isinstance(edit,dict) and type(edit.get('segment_index')) is int else -1)
        for edit in edits:
            deletion=isinstance(edit,dict) and 'remove_overlap_with' in edit
            if (not isinstance(edit,dict) or set(edit)!={'segment_index','expected_text_sha256'}|({'remove_overlap_with'} if deletion else {'text'})
                    or type(edit['segment_index']) is not int or not 0<=edit['segment_index']<len(rows) or edit['segment_index'] in seen
                    or not deletion and (not isinstance(edit['text'],str) or not edit['text'].strip() or len(edit['text'])>2000
                    or re.search(r'(?:cookie|authorization|password|access_token|refresh_token|private_key|api_key|secret)\s*[=:]',edit['text'],re.I))):
                raise ValueError('invalid_transcript_revision_edit')
            index=edit['segment_index'];seen.add(index);original=rows[index]
            if text_hash(original['text'])!=edit['expected_text_sha256']:raise ValueError('transcript_revision_stale_segment')
            item={'segment_index':index,'original_text':original['text'],'original_text_sha256':edit['expected_text_sha256'],
                  'revised_text_sha256':None if deletion else text_hash(edit['text']),'start':original['start'],'end':original['end']}
            if deletion:
                retained=edit['remove_overlap_with'];overlap=self._removal(saved,index,retained)
                if overlap is None:raise ValueError('invalid_transcript_overlap_removal')
                item.update(removed_overlap_with=retained,overlap_proof=overlap);removed.add(index);retained_targets.add(retained)
            else:rows[index]['text']=edit['text']
            proof.append(item)
        if removed&retained_targets or len(removed)==len(rows):raise ValueError('invalid_transcript_overlap_removal')
        rows=[row for index,row in enumerate(rows) if index not in removed]
        result[0]['evidence']['segments']=rows
        if sum(len(row['text']) for row in rows)>MAX_CHARACTERS:raise ValueError('transcript_quality_text_limit')
        now=time.time();new_id=str(uuid.uuid4());revision={'source_job_id':saved['job_id'],'audio_source_job_id':saved['audio_source_job_id'],
            'source_result_sha256':saved['result_sha256'],'reviewer_kind':reviewer_kind,'edited_segments':len(proof),'edits':proof,
            'created_at':now,'semantic_status':'not_reviewed','human_groundtruth':False,'model_calls':0,'source_requests':0}
        if optimization_plan is not None:
            revision['optimization']={key:copy.deepcopy(optimization_plan[key]) for key in
                ('schema_version','policy','plan_sha256','input_sha256','reference_binding','lexical_candidates','review_concerns','edits')}
        evidence=result[0]['evidence'];evidence['text_revision']=revision
        raw='\n'.join('[%.2f–%.2f] %s'%(row['start'],row['end'],row['text']) for row in rows)
        evidence.update(raw_text=raw[:24000],truncated=len(raw)>24000)
        state=copy.deepcopy(saved['state']);state.update(job_id=new_id,text_revision=revision,state='completed',created_at=now,finished_at=now,
              source_job_id=saved['audio_source_job_id'],
              processor_pid=None,review_status='not_reviewed',input_hash=text_hash(canonical({'source':saved['result_sha256'],'revision':revision})),
              result_sha256=text_hash(canonical(result)))
        ancestors(self.root);folder=self.root/new_id;folder.mkdir(mode=0o700)
        try:
            write_json(folder/'result.json',result)
            if evidence.get('processor') in ('faster_whisper_local_segmented','mlx_whisper_local_segmented'):
                (folder/'long-asr').mkdir(mode=0o700);checkpoint,_=read_json(saved['folder']/'long-asr/state.json',65536)
                write_json(folder/'long-asr/state.json',checkpoint)
            write_json(folder/'state.json',state)
        except BaseException:
            shutil.rmtree(folder);raise
        return {'ok':True,'job_id':new_id,'source_job_id':saved['audio_source_job_id'],'state':'completed','result_sha256':state['result_sha256'],
                'result':result,'text_revision':revision,'platform':state['platform'],'content_id':state['content_id'],
                'asset_sha256':state['asset_sha256'],'source_requests':0,'model_calls':0}
