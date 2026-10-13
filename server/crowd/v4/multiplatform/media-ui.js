'use strict';
const mediaView = (() => {
  const call=(action,payload={})=>api('/api/media-processing',{action,payload});
  const dialog=node('dialog');dialog.id='media_process_dialog';dialog.setAttribute('aria-labelledby','media_process_title');
  dialog.innerHTML=`<div class="dialog-head"><h2 id="media_process_title">本地媒体处理</h2><button type="button" id="media_process_close">关闭</button></div><div class="dialog-body"><p class="hint">仅处理本轮已经下载的文件。不会重新下载或上传素材；关联内容由你选择。</p><label>这份文件属于哪条内容？<select id="media_content"></select></label><label>处理方式<select id="media_kind"><option value="ocr">图片文字 OCR</option><option value="video_ocr">视频画面文字（轻量）</option><option value="asr">音视频本地转写</option><option value="transcript">导入已有字幕</option></select></label><label id="media_asr_engine_label" hidden>转写引擎<select id="media_asr_engine"><option value="cpu">原 CPU 转写</option><option value="mlx" disabled>Mac 加速（词时间，仍需校对）</option></select></label><label id="media_speech_check_label" hidden><input type="checkbox" id="media_speech_check">先检查完整音轨；未检测到讲话时暂停转写，可继续听写</label><label id="media_video_region_label" hidden>画面文字位置<select id="media_video_region"><option value="bottom">下方字幕区</option><option value="top">上方文案区</option><option value="full">全画面（可能含招牌、水印）</option></select></label><p id="media_process_hint" class="hint"></p><p id="media_process_state" role="status"></p><div class="actions"><button id="media_process_start" class="primary">处理已下载文件</button><button id="media_process_cancel" disabled>取消处理</button><button id="media_process_resume" hidden>从断点继续</button><button id="media_speech_bypass" hidden>继续听写（跳过语音检测）</button><button id="video_ocr_retry" hidden>重新提取画面文字</button></div><details><summary>本轮已保存的处理任务与断点</summary><div id="media_process_jobs"></div></details><pre id="media_process_result" hidden></pre></div>`;
  document.body.append(dialog);let selection=null,job=null,generation=0,timer=null,jobGeneration=0,nativeSelectionFile=null,inputPlan=null,previewGeneration=0;
  const qualityOutput=node('pre');qualityOutput.id='media_process_quality';qualityOutput.hidden=true;dialog.append(qualityOutput);
  const exportPanel=node('div');exportPanel.id='media_process_exports';exportPanel.hidden=true;dialog.append(exportPanel);
  const playbackPanel=node('details'),player=node('video'),playbackMessage=node('p');player.controls=true;player.preload='metadata';
  playbackPanel.append(node('summary','按时间试听原素材 · 不代表已校对'),player,playbackMessage);playbackPanel.hidden=true;dialog.append(playbackPanel);
  let playbackUrl=null,playbackGeneration=0;
  function clearPlayback(){exportPanel.hidden=true;exportPanel.replaceChildren();playbackGeneration++;player.pause?.();player.removeAttribute?.('src');player.load?.();if(playbackUrl)URL.revokeObjectURL(playbackUrl);playbackUrl=null;player.onloadedmetadata=null;player.ontimeupdate=null;playbackPanel.hidden=true;playbackMessage.textContent='';while(playbackPanel.children.length>3)playbackPanel.lastChild.remove();}
  function transcriptSrt(rows){
    const stamp=value=>{if(typeof value!=='number'||!Number.isFinite(value)||value<0||value>7200)throw Error('invalid_transcript_time');const ms=Math.round(value*1000),pad=(n,width=2)=>String(n).padStart(width,'0');return pad(Math.floor(ms/3600000))+':'+pad(Math.floor(ms/60000)%60)+':'+pad(Math.floor(ms/1000)%60)+','+pad(ms%1000,3);};
    return rows.map((row,index)=>{if(row.end<row.start||typeof row.text!=='string')throw Error('invalid_transcript_time');return (index+1)+'\n'+stamp(row.start)+' --> '+stamp(row.end)+'\n'+row.text.replace(/\r\n?/g,'\n').replace(/\n{2,}/g,'\n')+'\n';}).join('\n');
  }
  function visualLineInventory(rows){const lines=new Map();for(const row of rows){for(const text of new Set(row.text.split('\n').filter(line=>line.trim()))){const previous=lines.get(text);if(previous){previous.segment_count++;previous.last_end=row.end;}else lines.set(text,{text,segment_count:1,first_start:row.start,last_end:row.end});}}return [...lines.values()];}
  function renderExports(state){
    if(state.state!=='completed'||!['asr','subtitle','video_ocr'].includes(state.kind)||!Array.isArray(state.result)||state.result.length!==1)return;
    const item=state.result[0],evidence=item?.evidence,hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
    if(!evidence||evidence.asset_sha256!==state.asset_sha256||!hash(state.asset_sha256)||!hash(state.input_hash)||item.platform!==state.platform||item.content_id!==state.content_id||!Array.isArray(evidence.segments)||!evidence.segments.length)return;
    const visual=state.kind==='video_ocr',subtitle=state.kind==='subtitle',viewTicket=generation,jobTicket=jobGeneration;
    const identity=Object.fromEntries(['job_id','source_job_id','text_revision','run_id','platform','content_id','entity_ref','asset_sha256','input_hash','result_sha256','model_manifest_sha256','processor_files','processing_profile','native_video_context_sha256','video_source_job_id','source_reference_sha256','source_record_sha256','created_at','asr_engine'].filter(key=>state[key]!==undefined).map(key=>[key,state[key]]));
    const payload={schema_version:1,job:identity,semantic_review:'not_reviewed',full_segments:true,result:state.result};
    const valid=()=>dialog.open&&viewTicket===generation&&jobTicket===jobGeneration&&job===state;
    exportPanel.hidden=false;
    exportPanel.append(node('p',visual?'画面文字：每秒2帧、指定字幕区域采样，时间误差约0.5秒。可能漏掉短字幕或区域外文字，也可能读到招牌、贴字，不能代替全文听写。':'导出全部时间段；不受正文预览截断限制。包含原任务身份与诊断，仍待听音校对。'),
      button(visual?'导出画面文字 JSON':subtitle?'导出字幕 JSON':'导出完整转写 JSON',()=>{if(valid())download('crowd-transcript-'+state.job_id+'.json',payload);}),
      button('导出纯文字稿 TXT',()=>{
        if(!valid())return;
        const rows=typeof resultData==='object'&&resultData?(resultData.records||resultData.items||[]):[],title=rows.find(row=>row.platform===state.platform&&row.content_id===state.content_id&&['content','dynamic'].includes(row.kind))?.title||'完整文字稿';
        const text=[title,visual?'采样画面文字 · 非语音转写 · 尚未人工校对':subtitle?'平台字幕轨 · 语义完整性未知 · 尚未人工校对':'转写文字 · 尚未整体人工校对','',...evidence.segments.map(row=>row.text),'','完整时间轴、来源与诊断保留在 JSON。'].join('\n');
        const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'})),a=node('a');a.href=url;a.download='crowd-transcript-text-'+state.job_id+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }),
      button(visual?'导出画面文字 TXT':subtitle?'导出字幕 TXT':'导出完整转写 TXT',()=>{
        if(!valid())return;
        const lines=[visual?'采样画面文字 · 非语音转写 · 未人工校对':subtitle?'平台字幕轨 · 语义完整性未知 · 未人工校对':'完整转写 · 未人工校对',JSON.stringify(identity,null,2),'',...evidence.segments.map(row=>'['+row.start+'–'+row.end+'] '+row.text),'','原生诊断与时间来源（提示不代表准确率）',JSON.stringify({quality_diagnostics:evidence.quality_diagnostics??null,native_alignment_windows:evidence.native_alignment_windows??null,timing_adjustments:evidence.timing_adjustments??null,overlap_decisions:evidence.overlap_decisions??null},null,2)];
        const url=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/plain;charset=utf-8'})),a=node('a');a.href=url;a.download='crowd-transcript-'+state.job_id+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }),button(visual?'导出画面文字 SRT':subtitle?'导出字幕 SRT':'导出完整转写 SRT',()=>{
        if(!valid())return;
        const url=URL.createObjectURL(new Blob([transcriptSrt(evidence.segments)],{type:'text/plain;charset=utf-8'})),a=node('a');a.href=url;a.download='crowd-transcript-'+state.job_id+'.srt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }),...(state.kind==='asr'?[button('整理专名与重叠重复',()=>openOptimization(state,valid)),button('核对转写质量与保存修订',()=>openQuality(state,valid))]:[node('p',visual?'来源：本机 Apple Vision 识别视频画面；采样覆盖不等于全部对白完整。':'来源：平台字幕。时间轴来自字幕轨；全文语义与漏字尚未人工校对。')]));
    if(state.video_ocr_candidate===true){const region=node('select'),label=node('label','画面文字位置');region.append(new Option('下方字幕区','bottom'),new Option('上方文案区','top'),new Option('全画面（可能包含招牌、水印）','full'));label.append(region);exportPanel.append(label,button('用现有视频提取画面文字（非听写）',()=>{if(valid())guarded(()=>openVideoOCR(state.run_id,state.job_id,false,region.value));}));}
    if(visual)exportPanel.append(button('导出画面文字阅读稿 TXT（去重复）',()=>{if(!valid())return;const rows=visualLineInventory(evidence.segments);const text=['画面文字阅读稿 · 非听写 · 未人工校对','完全相同的逐行文字聚合；不是出现顺序。原时间轴、每次出现和识别原值保留在JSON/SRT。','',...rows.map(row=>'['+row.first_start+'–'+row.last_end+'秒；'+row.segment_count+'段] '+row.text)].join('\n');const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'})),a=node('a');a.href=url;a.download='crowd-visual-reading-'+state.job_id+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}));
    renderTranscriptCloud(state,valid);

  }
  function renderTranscriptCloud(state,valid){
    const message=node('p'),panel=node('div');let received=false,busy=false,uncertain=false;
    const confirm=value=>{const r=value?.receipt;if(value?.status!=='received'||r?.status!=='received'||r.artifact_kind!=='transcript_report'||r.local_job_id!==state.job_id||r.asset_sha256!==state.asset_sha256||r.segment_count!==state.result[0].evidence.segments.length||r.semantic_review!=='not_reviewed'||r.reward_eligible!==false||!/^[a-f0-9]{64}$/.test(r.text_sha256||'')||!/^[a-f0-9]{64}$/.test(r.report_sha256||''))throw Error('transcript_receipt_mismatch');received=true;uncertain=false;message.textContent='云端已保存完整文字稿 · '+r.segment_count+'段 · 回执 '+String(r.artifact_id).slice(0,8)+' · 仍未人工校对';};
    const save=button('保存完整文字稿到云端',async()=>{if(!valid()||busy)return;busy=true;save.disabled=true;get.disabled=true;message.textContent='仅上传完整文字稿与来源信息，不上传音轨，不调用远程模型…';try{const value=await call('transcript_cloud_save',{job_id:state.job_id});if(!valid())return;confirm(value);}catch(error){if(valid()){uncertain=error.message==='cloud_outcome_unknown';message.textContent=uncertain?'云保存结果未知，请查询回执，勿重复保存。':'文字稿云保存失败：'+error.message;}}finally{busy=false;if(valid()){save.disabled=received||uncertain;get.disabled=!received;}}});
    const get=button('取回云端完整文字稿 JSON',async()=>{if(!valid()||busy)return;busy=true;save.disabled=true;get.disabled=true;try{const value=await call('transcript_cloud_get',{job_id:state.job_id});if(!valid())return;confirm(value);if(value.report?.job_id!==state.job_id||value.report.asset_sha256!==state.asset_sha256||value.report.segment_count!==state.result[0].evidence.segments.length)throw Error('transcript_receipt_mismatch');download('crowd-cloud-transcript-'+state.job_id+'.json',value);}catch(error){if(valid())message.textContent='云端文字稿回取失败：'+error.message;}finally{busy=false;if(valid()){save.disabled=received||uncertain;get.disabled=!received;}}});
    const check=button('查询文字稿云回执',async()=>{if(!valid()||busy)return;busy=true;check.disabled=true;try{const value=await call('transcript_cloud_status',{job_id:state.job_id});if(!valid())return;if(value.status==='received')confirm(value);else message.textContent=uncertain?'尚无回执；保留未知状态，不重复保存。':'云端尚未保存文字稿。';}catch(error){if(valid())message.textContent='云回执查询失败：'+error.message;}finally{busy=false;if(valid()){check.disabled=false;save.disabled=received||uncertain;get.disabled=!received;}}});
    get.disabled=true;save.disabled=true;panel.append(message,save,get,check);exportPanel.append(panel);
    call('transcript_cloud_status',{job_id:state.job_id}).then(value=>{if(!valid()||busy||received||uncertain)return;if(value.status==='received')confirm(value);else message.textContent='可直接保存完整文字稿；无需先做远程模型分析。';save.disabled=received;get.disabled=!received;}).catch(error=>{if(valid()&&!busy&&!received&&!uncertain){message.textContent='云端文字稿状态未确认：'+error.message;save.disabled=true;}});
  }
  async function openOptimization(state,valid){
    if(!valid())return;const panel=node('section'),message=node('p','正在检查来源拼写与真实重叠片段…');panel.append(message);exportPanel.append(panel);let busy=false;
    try{const plan=await call('optimization_preview',{job_id:state.job_id});if(!valid())return;
      const edits=plan.edits||[],removed=edits.filter(row=>row.remove_overlap_with!==undefined).length;
      message.textContent='可整理 '+(edits.length-removed)+' 处文字、移除 '+removed+' 处重叠重复。保留原稿；疑似幻觉仍需核对，不代表全文已校对。';
      for(const edit of edits)panel.append(node('p',edit.remove_overlap_with!==undefined?'重叠片段 '+(edit.segment_index+1)+'：保留完整句，移除重复前缀。':'片段 '+(edit.segment_index+1)+'：'+edit.text));
      const save=button('生成优化版本，保留原稿',async()=>{if(!valid()||busy||!edits.length)return;busy=true;save.disabled=true;
        try{const next=await call('optimization_apply',{job_id:state.job_id,expected_result_sha256:plan.result_sha256,expected_plan_sha256:plan.plan_sha256});if(!valid())return;render(next);await history(generation);}
        catch(error){if(valid())message.textContent='未生成新版本：'+error.message;}
        finally{busy=false;if(valid())save.disabled=!edits.length;}
      });save.disabled=!edits.length;panel.append(save);
    }catch(error){if(valid())message.textContent='整理检查失败：'+error.message;}
  }
  async function openQuality(state,valid){
    if(!valid())return;
    const panel=node('div'),message=node('p');panel.append(message);exportPanel.append(panel);
    message.textContent='读取原生诊断与全文时间段…';let busy=false;
    try{
      const value=await call('quality_lookup',{job_id:state.job_id});if(!valid())return;
      if(value.job_id!==state.job_id||value.asset_sha256!==state.asset_sha256||value.platform!==state.platform||value.content_id!==state.content_id||!Array.isArray(value.segments)||!value.segments.length)throw Error('transcript_quality_identity_mismatch');
      const q=value.quality;message.textContent='全文 '+value.segments.length+' 段；低置信候选 '+(q.flag_counts.low_logprob||0)+'；连续重复候选 '+(q.flag_counts.repeated_adjacent_text||0)+'；无文字区间 '+q.untranscribed_intervals_total+'。无文字不代表漏词或静音；无人工参考，准确率未知。';
      const candidates=node('details');candidates.append(node('summary','待听音的原窗口候选与无文字区间'));
      for(const row of (q.candidates||[]).slice(0,20))candidates.append(node('p','原窗口 '+row.start+'–'+row.end+' 秒：'+row.text+'（原窗口诊断，不是修订句子的评分）'),button('试听原窗口 '+row.start+'–'+row.end+' 秒',()=>{if(valid())listen(state,row);}));
      for(const row of (q.untranscribed_intervals||[]).slice(0,10))candidates.append(button('试听无文字区间 '+row.start+'–'+row.end+' 秒',()=>{if(valid())listen(state,row);}));
      for(const hint of (q.text_pattern_hints||[])){candidates.append(node('p',hint.kind==='credit_style_output'?'发现署名式输出疑点；模型置信值不能证明内容真实，请核对原音。':'发现大量同句重复；可能是真实对白或歌词，也可能是模型重复，请核对原音。'));for(const index of hint.segment_indices.slice(0,3)){const row=value.segments[index];if(row)candidates.append(button('试听文字疑点 '+row.start+'–'+row.end+' 秒',()=>{if(valid())listen(state,row);}));}}
      panel.append(candidates);
      const selector=node('select'),editor=node('textarea'),label=node('label','选择时间段并听音校对'),editLabel=node('label','修订文字（另存新版本，原转写保留）'),ack=node('input');ack.type='checkbox';editor.rows=5;editor.maxLength=2000;
      for(const row of value.segments)selector.append(new Option((row.segment_index+1)+' · '+row.start+'–'+row.end+' 秒 · '+row.text.slice(0,60),String(row.segment_index)));
      selector.value='0';const selected=()=>value.segments.find(row=>String(row.segment_index)===selector.value);
      const update=()=>{editor.value=selected()?.text||'';};selector.onchange=update;update();label.append(selector);editLabel.append(editor);const acknowledgment=node('label','我确认另存修订版本；未将其标记为全文已校对。');acknowledgment.append(ack);
      const save=button('保存为新转写版本',async()=>{
        if(!valid()||busy)return;const row=selected();if(!row||!ack.checked||!editor.value.trim()||editor.value===row.text){message.textContent='请听音修改文字并勾选另存确认。';return;}
        busy=true;save.disabled=true;message.textContent='正在保存新转写版本…';
        try{const revised=await call('transcript_revision',{job_id:state.job_id,expected_result_sha256:value.result_sha256,edits:[{segment_index:row.segment_index,expected_text_sha256:row.text_sha256,text:editor.value}],reviewer_kind:'human_manual',acknowledge_new_version:true});if(!valid())return;render(revised);await history(generation);}
        catch(error){if(valid())message.textContent='未确认新版本：'+error.message;}
        finally{busy=false;if(valid())save.disabled=false;}
      });
      panel.append(label,button('试听所选时间段',()=>{if(valid()&&selected())listen(state,selected());}),editLabel,acknowledgment,save);
    }catch(error){if(valid())message.textContent='质量信息读取失败：'+error.message;}
  }
  async function listen(state,row){
    const ticket=++playbackGeneration,viewTicket=generation,jobTicket=jobGeneration;player.pause?.();playbackMessage.textContent='正在核验本任务的原素材快照…';
    try{
      const response=await fetch('/api/media-processing',{method:'POST',headers:{'Content-Type':'application/json','X-Crowd-CSRF':token},body:JSON.stringify({action:'playback',payload:{job_id:state.job_id,asset_sha256:state.asset_sha256}})});
      if(!response.ok)throw Error((await response.json()).error||'media_playback_failed');
      const blob=await response.blob();
      if(ticket!==playbackGeneration||viewTicket!==generation||jobTicket!==jobGeneration||!dialog.open)return;
      if(response.headers.get('X-Content-SHA256')!==state.asset_sha256)throw Error('media_playback_identity_mismatch');
      if(playbackUrl)URL.revokeObjectURL(playbackUrl);playbackUrl=URL.createObjectURL(blob);player.src=playbackUrl;
      player.onloadedmetadata=()=>{if(ticket!==playbackGeneration||viewTicket!==generation||jobTicket!==jobGeneration||!dialog.open)return;if(!Number.isFinite(player.duration)||row.end>player.duration||row.start>=player.duration){playbackMessage.textContent='片段时间超出原素材可播时长，未自动改写时间轴。';return;}player.currentTime=row.start;player.ontimeupdate=()=>{if(player.currentTime>=row.end)player.pause();};playbackMessage.textContent='原素材 '+row.start+'–'+row.end+' 秒；请听音核对，未标记已校对。';player.play().catch(()=>{if(ticket===playbackGeneration&&viewTicket===generation&&jobTicket===jobGeneration&&dialog.open)playbackMessage.textContent+=' 请点击播放器播放。';});};
    }catch(error){if(ticket===playbackGeneration&&viewTicket===generation&&jobTicket===jobGeneration&&dialog.open)playbackMessage.textContent=error.message==='media_playback_snapshot_missing'?'旧任务未保留原素材快照，暂不可试听；转写仍保留。':'试听未能完成：'+error.message;}
  }
  function renderPlayback(state,evidence){
    clearPlayback();if(state.state!=='completed'||state.kind!=='asr')return;
    const item=evidence.find(value=>value.asset_sha256===state.asset_sha256);if(!item)return;
    const rows=item.quality_diagnostics?.time_basis==='original_audio_seconds'?item.quality_diagnostics.segments:item.timeline==='absolute_seconds'?item.segments:[];
    if(!Array.isArray(rows)||!rows.length)return;playbackPanel.hidden=false;
    for(const [index,row]of rows.entries())if(row&&typeof row.start==='number'&&typeof row.end==='number'&&Number.isFinite(row.start)&&Number.isFinite(row.end)&&0<=row.start&&row.start<row.end&&row.end<=7200)playbackPanel.append(button('试听片段 '+(index+1)+' · '+row.start+'–'+row.end+' 秒',()=>listen(state,row)));
  }
  function repeatedTextIndices(rows,requireChunk=false){
    const flagged=new Set();let streak=[],previous=null;
    for(let index=0;index<rows.length;index++){
      const row=rows[index];if(!row||typeof row!=='object'){streak=[];previous=null;continue;}const chunk=row.chunk_index??null;
      const valid=typeof row.text==='string'&&Number.isFinite(row.start)&&Number.isFinite(row.end)&&0<=row.start&&row.start<=row.end&&(!requireChunk&&chunk===null||Number.isInteger(chunk)&&chunk>=0);
      const normal=valid?row.text.normalize('NFKC').toLowerCase().replace(/[\p{P}\s]/gu,''):'';
      if(Array.from(normal).length<2||Array.from(normal).length>200){streak=[];previous=null;continue;}
      if(previous&&chunk===previous.chunk&&normal===previous.normal&&previous.start<=row.start&&row.start<=previous.end+1&&row.end-rows[streak[0]].start<=15)streak.push(index);else streak=[index];
      previous={chunk,normal,start:row.start,end:row.end};
      if(streak.length>=3)for(const item of streak)flagged.add(item);
    }
    return flagged;
  }
  function qualityText(evidence){
    if(evidence.declared_subtitle_provenance||evidence.subtitle_provenance)return '平台声明字幕轨，非本机语音模型生成；原轨可能不完整或存在错字，语义完整性未知。';
    const rows=evidence.segments||[],credit=rows.length<=3&&rows.reduce((n,row)=>n+Array.from(row.text||'').length,0)<=160&&rows.some(row=>/字幕(?:志愿者|制作|提供|校对)|(?:字幕|翻译)由/.test(row.text||''));
    const prefix=credit?'发现署名式输出疑点；可能是真实内容或模型生成，置信值不能证明准确。请核对原音。\n':'';
    const quality=evidence.quality_diagnostics;
    if(!quality||quality.schema_version!==1||!['available','partial'].includes(quality.status)||!Array.isArray(quality.segments)||!quality.segments.length)return prefix+'模型诊断：未记录（unknown）。旧结果或本次处理缺少原生诊断，仍需听音核对。';
    const labels={low_logprob:'平均对数概率偏低',high_compression:'压缩比偏高，建议检查重复',possible_no_speech:'可能没有语音，需听音核对',repeated_adjacent_text:'同窗口连续重复候选，可能是真实重复，需听音核对'};
    const metric=value=>typeof value==='number'&&Number.isFinite(value)?String(value):'未记录';
    const lines=['模型诊断仅供复核，不代表准确率。以下是原始窗口片段，可能包含已去重的文字；正文保留。'];
    if(quality.status==='partial')lines.push('部分片段或数值未记录（unknown）。');
    const repeated=repeatedTextIndices(quality.segments,quality.time_basis!=='local_file_seconds');
    if(repeated.size)lines.push('连续重复是文字规则提示，可能是真实重复；没有删除内容或修正词句。');
    for(const [index,row] of quality.segments.slice(0,20).entries()){
      if(!row||typeof row!=='object'){lines.push('本条诊断未记录（unknown）。');continue;}
      lines.push('['+row.start+'–'+row.end+'] '+(Number.isInteger(row.chunk_index)?'窗口 '+row.chunk_index+' · ':'')+'片段 '+row.segment_index+'：'+row.text+'\n  avg_logprob='+metric(row.avg_logprob)+'；compression_ratio='+metric(row.compression_ratio)+'；no_speech_prob='+metric(row.no_speech_prob)+'\n  '+([...new Set([...(Array.isArray(row.flags)?row.flags:[]),...(repeated.has(index)?['repeated_adjacent_text']:[])])].map(flag=>labels[flag]).filter(Boolean).join('；')||'没有触发复核提示，仍不代表识别正确。'));
    }
    if(quality.segments.length>20)lines.push('仅显示前 20 条；其余 '+(quality.segments.length-20)+' 条保留在处理结果中。');
    return prefix+lines.join('\n');
  }
  $('media_process_close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{generation++;clearTimeout(timer);timer=null;clearPlayback();});
  async function poll(id,ticket,jobTicket=jobGeneration){const state=await call('status',{job_id:id});if(ticket!==generation||jobTicket!==jobGeneration||!dialog.open)return;render(state);if(!['completed','failed','cancelled','interrupted_unknown'].includes(state.state))timer=setTimeout(()=>guarded(()=>poll(id,ticket,jobTicket)),1500);}
  function render(state){job=state;$('media_speech_bypass').hidden=!(state.kind==='asr'&&state.speech_check===true&&state.state==='failed'&&state.reason==='vad_no_speech_detected'&&state.speech_precheck?.has_speech===false);$('video_ocr_retry').hidden=!(state.kind==='video_ocr'&&['failed','cancelled'].includes(state.state));$('media_process_state').textContent=({queued:'等待处理',running:'正在本机处理',completed:'处理已保存，待人工核对',failed:'处理失败，原文件保留',cancelled:'已取消',interrupted_unknown:'处理结果待核对'})[state.state]||state.state;if(state.total_chunks)$('media_process_state').textContent+=' · 已处理 '+(state.completed_chunks||0)+' / '+state.total_chunks+' 段';if(state.expected_frames)$('media_process_state').textContent+=' · 已采样 '+(state.processed_frames||0)+' / '+state.expected_frames+' 帧';if(state.reason)$('media_process_state').textContent+='：'+(state.reason==='vad_no_speech_detected'?'完整音轨未检测到讲话候选，原音频已保留；检测可能漏掉歌词或短句，可选择继续听写。':state.reason);$('media_process_resume').hidden=!(['failed','cancelled'].includes(state.state)&&state.checkpoint_available&&state.reason!=='vad_no_speech_detected');$('media_process_cancel').disabled=['completed','failed','cancelled','interrupted_unknown'].includes(state.state);$('media_process_result').hidden=!state.result;if(state.result)$('media_process_result').textContent=state.result.map(item=>item.evidence?.segments?.length?item.evidence.segments.map(segment=>'['+segment.start+'–'+segment.end+'] '+segment.text).join('\n'):item.evidence?.raw_text||item.text||'本段未识别到文字').join('\n\n');const evidence=(state.result||[]).map(item=>item.evidence).filter(item=>item&&(item.segments||['faster_whisper_local','faster_whisper_local_segmented','apple_speech_ondevice'].includes(item.processor)));qualityOutput.hidden=!evidence.length;qualityOutput.textContent=state.kind==='video_ocr'?'画面文字识别，非语音模型转写。短字幕、字幕区域外文字可能遗漏；尚未人工校对。':evidence.map(qualityText).join('\n\n');if(state.kind!=='video_ocr')renderPlayback(state,evidence);renderExports(state);}
  async function history(ticket){const saved=await call('list',{run_id:selection.run_id});if(ticket!==generation||!dialog.open)return;$('media_process_jobs').replaceChildren();for(const observation of saved.subtitle_observations||[])$('media_process_jobs').append(node('p',observation.status==='not_video'?'此内容明确为图文，无视频字幕。':observation.status==='track_candidate'?'已发现声明字幕轨；仅通过原件与正文核验的轨才显示为可用。':'本次原响应未发现可用字幕轨；不代表平台不支持字幕。'));for(const item of saved.jobs||[]){const row=node('p'),created=typeof item.created_at==='number'&&Number.isFinite(item.created_at)&&item.created_at>0&&Number.isFinite(new Date(item.created_at*1000).getTime())?new Date(item.created_at*1000).toLocaleString('zh-CN',{hour12:false}):'未记录';row.append(node('span',item.content_id+' · '+item.kind+' · '+item.state+' · 创建 '+created+' · 任务 '+String(item.job_id||'未记录').slice(0,8)+' '),button('查看此任务',()=>guarded(async()=>{clearTimeout(timer);clearPlayback();const jobTicket=++jobGeneration;const state=await call('status',{job_id:item.job_id});if(ticket!==generation||jobTicket!==jobGeneration||!dialog.open)return;render(state);await poll(item.job_id,ticket,jobTicket);})));$('media_process_jobs').append(row);}if(!(saved.jobs||[]).length)$('media_process_jobs').append(node('p','暂无已保存任务。'));}
  function contentRows(file){const rows=(resultData.records||[]).filter(row=>['content','dynamic'].includes(row.kind));if(file.platform!=='zhihu'&&!String(file.path).startsWith('output/zhihu/'))return rows;const same=rows.filter(row=>row.platform==='zhihu'&&row.content_id===file.content_id);return ['answer','article','zvideo'].includes(file.source_content_type)&&same.length===1&&same[0].content_type===file.source_content_type?same:[];}
  async function previewInput(){
    const ticket=++previewGeneration,view=generation,cid=$('media_content').value,kind=$('media_kind').value;inputPlan=null;
    $('media_process_start').disabled=!$('media_content').options.length||$('media_kind').selectedOptions[0]?.disabled;
    $('media_video_region_label').hidden=kind!=='video_ocr';$('media_process_start').disabled=!$('media_content').options.length||$('media_kind').selectedOptions[0]?.disabled;if(kind==='video_ocr')$('media_process_hint').textContent='直接识别已登记视频的画面文字，不先转写声音，不复制或重新下载视频；结果可能含贴字、招牌和误字，非听写。';$('media_asr_engine_label').hidden=kind!=='asr';$('media_speech_check_label').hidden=kind!=='asr'||$('media_speech_check').disabled;if(!nativeSelectionFile||kind!=='asr')return;
    $('media_process_start').disabled=true;$('media_process_hint').textContent='正在核对已登记视频、音轨与本地处理范围…';
    try{const value=await call('preview',{...selection,content_id:cid,kind,...(kind==='asr'&&$('media_asr_engine').value==='mlx'?{asr_engine:$('media_asr_engine').value}:{})});
      if(ticket!==previewGeneration||view!==generation||!dialog.open||cid!==$('media_content').value||kind!==$('media_kind').value)return;
      const large=value.processing_profile==='registered_native_mp4_asr_64mib_7200s',standard=value.processing_profile==='standard_25mib_3600s';if(value.native_video_verified!==true||(!large&&!standard)||value.asset_sha256!==nativeSelectionFile.sha256||value.input_bytes!==nativeSelectionFile.bytes||value.max_input_bytes!==(large?64:25)*1048576||value.max_audio_seconds!==(large?7200:3600))throw Error('media_processing_preview_mismatch');
      inputPlan=value;$('media_process_hint').textContent='已核对登记视频与音轨。ASR最多'+(large?'120分钟、64MiB':'60分钟、25MiB')+'；本地分段处理，不重新访问来源。';$('media_process_start').disabled=$('media_kind').selectedOptions[0]?.disabled;
    }catch(error){if(ticket===previewGeneration&&view===generation&&dialog.open)$('media_process_hint').textContent='本地视频转写尚不可开始：'+error.message;}
  }
  async function open(file){generation++;jobGeneration++;clearTimeout(timer);clearPlayback();selection={run_id:idOf(selectedRun),path:file.path};nativeSelectionFile=file.source_kind==='mediacrawler_api'&&/\.mp4$/i.test(file.path||'')?file:null;inputPlan=null;previewGeneration++;job=null;qualityOutput.hidden=true;qualityOutput.textContent='';$('media_process_resume').disabled=false;$('media_process_resume').hidden=true;$('media_process_cancel').disabled=true;$('media_process_result').hidden=true;$('media_process_state').textContent='';$('media_content').replaceChildren();for(const row of contentRows(file))$('media_content').append(new Option(row.title||row.content_id,row.content_id));if(file.content_id&&[...$('media_content').options].some(option=>option.value===file.content_id))$('media_content').value=file.content_id;dialog.showModal();const identityMissing=(file.platform==='zhihu'||String(file.path).startsWith('output/zhihu/'))&&!$('media_content').options.length;if(identityMissing)$('media_process_state').textContent='知乎素材缺少唯一类型身份，暂不可处理；仍可下载。';const ticket=generation;let caps;try{caps=await call('capabilities');}catch(error){if(ticket===generation&&dialog.open)$('media_process_state').textContent=error.message;return;}if(ticket!==generation||!dialog.open)return;$('media_asr_engine').value=(caps.asr_engines||[]).includes('mlx')?'mlx':'cpu';$('media_speech_check').disabled=!caps.speech_check;$('media_speech_check').checked=!!caps.speech_check;for(const option of $('media_asr_engine').options)option.disabled=!(caps.asr_engines||['cpu']).includes(option.value);for(const option of $('media_kind').options)option.disabled=!caps[option.value]||(option.value==='video_ocr'&&!nativeSelectionFile);const ext=String(file.path).split('.').pop().toLowerCase();$('media_kind').value=nativeSelectionFile?'asr':['jpg','jpeg','png','webp'].includes(ext)?'ocr':['vtt','srt','txt'].includes(ext)?'transcript':'asr';$('media_asr_engine_label').hidden=$('media_kind').value!=='asr';$('media_process_hint').textContent=caps.asr?'本地 '+(caps.asr_model_name||'语音')+' 模型已配置，结果可按时间核对。最长 '+Math.floor((['m4a','mp3','aac'].includes(ext)?caps.limits?.long_audio_seconds||7200:caps.limits?.max_audio_seconds||3600)/60)+' 分钟、文件'+(['m4a','mp3','aac'].includes(ext)?64:25)+'MiB；分段处理，可从断点继续。':'本机尚未配置语音模型。图片和已有字幕可用；音视频转写需先配置本地模型。';$('media_process_start').disabled=!$('media_content').options.length||$('media_kind').selectedOptions[0]?.disabled;await previewInput();try{await history(ticket);}catch(error){if(ticket===generation&&dialog.open)$('media_process_state').textContent='已保存任务读取失败：'+error.message;}}
  async function openSaved(runId,jobId){
    const ticket=++generation,jobTicket=++jobGeneration;clearTimeout(timer);clearPlayback();selection={run_id:runId};$('media_video_region_label').hidden=true;$('media_asr_engine_label').hidden=true;$('media_speech_check_label').hidden=true;nativeSelectionFile=null;inputPlan=null;previewGeneration++;job=null;
    $('media_process_start').disabled=true;$('media_process_resume').hidden=true;$('media_process_cancel').disabled=true;
    $('media_process_result').hidden=true;$('media_process_result').textContent='';qualityOutput.hidden=true;qualityOutput.textContent='';exportPanel.hidden=true;exportPanel.replaceChildren();$('media_process_jobs').replaceChildren();$('media_process_state').textContent='正在读取已保存文字稿…';
    $('media_process_hint').textContent='查看本任务已保存文字稿；来源字幕的语义与漏字仍待校对。';dialog.showModal();
    const state=await call('status',{job_id:jobId});if(ticket!==generation||jobTicket!==jobGeneration||!dialog.open)return;
    if(state.run_id!==runId)throw Error('transcript_source_binding_denied');$('media_process_hint').textContent=state.kind==='video_ocr'?'已保存的画面文字稿；不是语音转写，短字幕和区域外文字可能遗漏，尚未人工校对。':state.kind==='subtitle'?'查看本任务已保存字幕；语义与漏字仍待校对。':'查看本任务已保存语音转写；尚未人工校对。';render(state);await history(ticket);if(['queued','running'].includes(state.state))await poll(jobId,ticket,jobTicket);
  }
  async function openVideoOCR(runId,sourceJobId,retry=false,textRegion='bottom'){const ticket=++generation,jobTicket=++jobGeneration,view=selectedRun;const state=await call('video_ocr_start',{run_id:runId,source_job_id:sourceJobId,...(retry?{retry:true}:{}),...(textRegion!=='bottom'?{text_region:textRegion}:{})});if(ticket!==generation||jobTicket!==jobGeneration||view!==selectedRun)return;await openSaved(runId,state.job_id);}
  async function retryVideoOCR(saved){if(saved.kind!=='video_ocr'||!['failed','cancelled'].includes(saved.state))throw Error('video_ocr_retry_not_allowed');const region=[['bottom',.67,.82],['top',.12,.32],['full',0,1]].find(row=>row[1]===saved.crop_top&&row[2]===saved.crop_bottom)?.[0];if(!region)throw Error('video_ocr_region_requires_selection');await openVideoOCR(saved.run_id,saved.video_source_job_id,true,region);}
  $('video_ocr_retry').onclick=()=>guarded(async()=>{const saved=job;if(!saved||saved.kind!=='video_ocr'||!['failed','cancelled'].includes(saved.state))return;$('video_ocr_retry').disabled=true;try{await retryVideoOCR(saved);}finally{$('video_ocr_retry').disabled=false;}});
  $('media_speech_bypass').onclick=()=>guarded(async()=>{const prior=job,ticket=generation,jobTicket=++jobGeneration;if(!prior||prior.reason!=='vad_no_speech_detected')return;$('media_speech_bypass').disabled=true;try{const state=await call('speech_check_bypass',{job_id:prior.job_id});if(ticket!==generation||jobTicket!==jobGeneration||!dialog.open)return;render(state);await poll(state.job_id,ticket,jobTicket);}finally{$('media_speech_bypass').disabled=false;}});
  $('media_kind').onchange=previewInput;$('media_content').onchange=previewInput;$('media_asr_engine').onchange=previewInput;
  $('media_process_start').onclick=()=>guarded(async()=>{if(nativeSelectionFile&&$('media_kind').value==='asr'&&!inputPlan)return;const ticket=generation,jobTicket=++jobGeneration;clearTimeout(timer);clearPlayback();$('media_process_start').disabled=true;try{const state=await call('start',{...selection,content_id:$('media_content').value,kind:$('media_kind').value,...($('media_kind').value==='asr'&&!$('media_speech_check').disabled?{speech_check:$('media_speech_check').checked}:{}),...($('media_kind').value==='video_ocr'?{text_region:$('media_video_region').value}:{}),...($('media_kind').value==='asr'&&$('media_asr_engine').value==='mlx'?{asr_engine:$('media_asr_engine').value}:{})});if(ticket!==generation||jobTicket!==jobGeneration||!dialog.open)return;render(state);await poll(state.job_id,ticket,jobTicket);}catch(error){if(ticket===generation&&jobTicket===jobGeneration&&dialog.open)$('media_process_state').textContent=error.message;}finally{if(ticket===generation&&jobTicket===jobGeneration)$('media_process_start').disabled=false;}});
  $('media_process_cancel').onclick=()=>guarded(async()=>{if(!job)return;const ticket=generation,jobTicket=jobGeneration;const state=await call('cancel',{job_id:job.job_id});if(ticket===generation&&jobTicket===jobGeneration&&dialog.open)render(state);});
  $('media_process_resume').onclick=()=>guarded(async()=>{if(!job)return;const ticket=generation,jobTicket=++jobGeneration;clearTimeout(timer);clearPlayback();$('media_process_resume').disabled=true;try{const state=await call('resume',{job_id:job.job_id});if(ticket!==generation||jobTicket!==jobGeneration||!dialog.open)return;render(state);await poll(state.job_id,ticket,jobTicket);}finally{if(ticket===generation&&jobTicket===jobGeneration)$('media_process_resume').disabled=false;}});
  const videoDialog=node('dialog');videoDialog.id='complete_video_dialog';videoDialog.setAttribute('aria-labelledby','complete_video_title');
  videoDialog.innerHTML=`<div class="dialog-head"><h2 id="complete_video_title">取得完整视频</h2><button id="complete_video_close">关闭</button></div><div class="dialog-body"><p class="hint">根据本轮保存的原平台视频引用，单独下载并在本机转码。输入最多256MiB，输出最多64MiB，最多4次HTTP请求，15分钟截止。输出是完整时长的转码副本，画质可能降低。完成后可保存到私有云端，云文件上限50MiB；保存与取回均校验文件字节。</p><p id="complete_video_state" role="status"></p><div class="actions"><button id="complete_video_start" disabled>下载并转码完整视频</button><button id="complete_video_cancel" disabled>取消此处理任务</button><button id="complete_video_download" hidden>下载完整视频 MP4</button><button id="complete_video_cloud_save" hidden disabled>保存到云端</button><button id="complete_video_cloud_download" hidden disabled>从云端下载 MP4</button></div><p id="complete_video_cloud_state" role="status"></p></div>`;
  document.body.append(videoDialog);let videoGeneration=0,videoTimer=null,videoSelection=null,videoJob=null,videoCloudKey=null,videoCloudBusy=false,videoCloudReceived=false;
  const videoCurrent=ticket=>ticket===videoGeneration&&videoDialog.open;
  const videoGuard=(fn,ticket=videoGeneration)=>guarded(async()=>{try{return await fn();}catch(error){if(videoCurrent(ticket))$('complete_video_state').textContent='操作未完成：'+error.message;}});
  function videoRender(state){videoJob=state;const names={queued:'等待处理',running:'正在处理',completed:'完整视频已保存',failed:'处理失败，已有文件保留',cancelled:'已取消',interrupted_unknown:'处理结果待核对'};const phases={downloading_video:'下载原完整流',checking_source_video:'校验原视频全长',transcoding_video:'本机转码',checking_complete_output:'校验输出全长'};$('complete_video_state').textContent=(names[state.state]||'状态待核对')+(phases[state.video_phase]?' · '+phases[state.video_phase]:'')+(state.downloaded_bytes?' · 已下载 '+(state.downloaded_bytes/1048576).toFixed(1)+'MiB':'')+(state.reason?' · '+state.reason:'');$('complete_video_cancel').disabled=['completed','failed','cancelled','interrupted_unknown'].includes(state.state);$('complete_video_download').hidden=state.state!=='completed';$('complete_video_cloud_save').hidden=state.state!=='completed';if(state.state==='completed'){$('complete_video_state').textContent+=' · '+state.result?.[0]?.evidence?.duration_seconds+' 秒 · 已通过全长解码，不代表已人工检查画面。';const key=state.job_id+':'+state.asset_sha256;if(key!==videoCloudKey){videoCloudKey=key;videoCloudReceived=false;$('complete_video_cloud_save').disabled=true;$('complete_video_cloud_state').textContent='读取云保存回执…';refreshVideoCloud(state,videoGeneration);}}else{$('complete_video_cloud_download').hidden=true;$('complete_video_cloud_state').textContent='';}}
  const videoCloudCurrent=(state,ticket)=>videoCurrent(ticket)&&videoJob?.job_id===state.job_id&&videoJob?.asset_sha256===state.asset_sha256;
  function videoCloudRender(value,state){
    if(value.state==='received'){
      const r=value.receipt,m=r?.manifest;
      if(r?.artifact_kind!=='video_object'||r.status!=='received'||r.verification!=='server_storage_bytes_sha256'||m?.local_job_id!==state.job_id||m.asset_sha256!==state.asset_sha256||!Number.isInteger(m.asset_bytes)||m.asset_bytes<=0||m.asset_bytes>50*1048576)throw Error('media_cloud_receipt_mismatch');
      videoCloudReceived=true;$('complete_video_cloud_state').textContent='云端已保存 · 文件字节校验通过 · 回执 '+String(r.artifact_id).slice(0,8);
    }else if(['not_saved','outcome_unknown'].includes(value.state)){
      videoCloudReceived=false;$('complete_video_cloud_state').textContent=value.state==='outcome_unknown'?'云保存结果待核对。点击核对已有结果，不自动重复上传。':'尚未保存到云端。';
    }else throw Error('media_cloud_state_invalid');
    $('complete_video_cloud_save').textContent=value.state==='outcome_unknown'?'核对云保存结果':'保存到云端';
    $('complete_video_cloud_save').disabled=videoCloudBusy||videoCloudReceived;$('complete_video_cloud_download').hidden=!videoCloudReceived;$('complete_video_cloud_download').disabled=videoCloudBusy;
  }
  async function refreshVideoCloud(state,ticket){try{const value=await call('video_cloud_status',{job_id:state.job_id});if(videoCloudCurrent(state,ticket))videoCloudRender(value,state);}catch(error){if(videoCloudCurrent(state,ticket))$('complete_video_cloud_state').textContent='云回执读取失败：'+error.message;}}
  async function videoPoll(id,ticket){return videoGuard(async()=>{const state=await call('status',{job_id:id});if(!videoCurrent(ticket))return;videoRender(state);if(!['completed','failed','cancelled','interrupted_unknown'].includes(state.state))videoTimer=setTimeout(()=>videoPoll(id,ticket),1500);},ticket);}
  async function openVideo(row){
    const ticket=++videoGeneration;clearTimeout(videoTimer);videoJob=null;videoCloudKey=null;videoCloudBusy=false;videoCloudReceived=false;$('complete_video_cloud_state').textContent='';$('complete_video_cloud_save').hidden=true;$('complete_video_cloud_download').hidden=true;videoSelection={run_id:idOf(selectedRun),content_id:row.content_id};
    $('complete_video_state').textContent='核对本轮视频引用…';$('complete_video_start').disabled=true;$('complete_video_cancel').disabled=true;$('complete_video_download').hidden=true;videoDialog.showModal();
    try{
      const ref=await call('video_preview',videoSelection);if(!videoCurrent(ticket))return;
      videoSelection={...videoSelection,reference_sha256:ref.reference_sha256};
      const saved=await call('list',{run_id:videoSelection.run_id});if(!videoCurrent(ticket))return;
      if(!Array.isArray(saved.jobs))throw Error('complete_video_saved_tasks_unavailable');
      const matches=saved.jobs.filter(state=>state.kind==='complete_video'&&state.run_id===videoSelection.run_id&&state.content_id===videoSelection.content_id&&state.source_reference_sha256===videoSelection.reference_sha256);
      if(matches.length>1)throw Error('complete_video_saved_task_ambiguous');
      if(matches.length===1){videoRender(matches[0]);if(['queued','running'].includes(matches[0].state))await videoPoll(matches[0].job_id,ticket);return;}
      $('complete_video_state').textContent='引用已核对。点击下方按钮才会下载完整视频。';$('complete_video_start').disabled=false;
    }catch(error){if(videoCurrent(ticket))$('complete_video_state').textContent='无法处理：'+error.message;}
  }
  $('complete_video_close').onclick=()=>videoDialog.close();videoDialog.addEventListener('close',()=>{videoGeneration++;clearTimeout(videoTimer);});
  $('complete_video_start').onclick=()=>videoGuard(async()=>{const ticket=videoGeneration;if(!videoSelection?.reference_sha256)return;$('complete_video_start').disabled=true;try{const state=await call('video_start',{...videoSelection,allow_download:true});if(!videoCurrent(ticket))return;videoRender(state);await videoPoll(state.job_id,ticket);}catch(error){if(videoCurrent(ticket))$('complete_video_state').textContent='处理未能启动：'+error.message;}});
  $('complete_video_cancel').onclick=()=>videoGuard(async()=>{if(!videoJob)return;const ticket=videoGeneration,state=await call('cancel',{job_id:videoJob.job_id});if(videoCurrent(ticket))videoRender(state);});
  $('complete_video_download').onclick=()=>videoGuard(async()=>{const state=videoJob,ticket=videoGeneration;if(!state||state.state!=='completed')return;const response=await fetch('/api/media-processing',{method:'POST',headers:{'Content-Type':'application/json','X-Crowd-CSRF':token},body:JSON.stringify({action:'video_file',payload:{job_id:state.job_id,asset_sha256:state.asset_sha256}})});if(!response.ok)throw Error((await response.json()).error||'complete_video_download_failed');const blob=await response.blob();if(!videoCurrent(ticket)||videoJob!==state)return;if(response.headers.get('X-Content-SHA256')!==state.asset_sha256)throw Error('complete_video_identity_mismatch');const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download='crowd-video-'+state.job_id+'.mp4';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  $('complete_video_cloud_save').onclick=async()=>{
    const state=videoJob,ticket=videoGeneration;if(!state||state.state!=='completed'||videoCloudBusy||videoCloudReceived||!videoCurrent(ticket))return;
    videoCloudBusy=true;$('complete_video_cloud_save').disabled=true;$('complete_video_cloud_download').disabled=true;$('complete_video_cloud_state').textContent='正在保存并校验云端文件…';
    try{const value=await call('video_cloud_save',{job_id:state.job_id});if(videoCloudCurrent(state,ticket))videoCloudRender({state:'received',receipt:value.receipt},state);}
    catch(error){if(videoCloudCurrent(state,ticket))$('complete_video_cloud_state').textContent='云保存未确认：'+error.message;}
    finally{if(videoCloudCurrent(state,ticket)){videoCloudBusy=false;$('complete_video_cloud_save').disabled=videoCloudReceived;$('complete_video_cloud_download').disabled=false;}}
  };
  $('complete_video_cloud_download').onclick=async()=>{
    const state=videoJob,ticket=videoGeneration;if(!state||state.state!=='completed'||videoCloudBusy||!videoCloudReceived||!videoCurrent(ticket))return;
    videoCloudBusy=true;$('complete_video_cloud_download').disabled=true;
    try{const response=await fetch('/api/media-processing',{method:'POST',headers:{'Content-Type':'application/json','X-Crowd-CSRF':token},body:JSON.stringify({action:'video_cloud_file',payload:{job_id:state.job_id,asset_sha256:state.asset_sha256}})});if(!response.ok)throw Error((await response.json()).error||'media_cloud_download_failed');const blob=await response.blob();if(!videoCloudCurrent(state,ticket))return;if(response.headers.get('X-Content-SHA256')!==state.asset_sha256||blob.size!==state.result?.[0]?.evidence?.bytes)throw Error('media_cloud_download_mismatch');const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download='crowd-cloud-video-'+state.job_id+'.mp4';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('complete_video_cloud_state').textContent='云端文件已取回并校验通过。';}
    catch(error){if(videoCloudCurrent(state,ticket))$('complete_video_cloud_state').textContent='云端取回未完成：'+error.message;}
    finally{if(videoCloudCurrent(state,ticket)){videoCloudBusy=false;$('complete_video_cloud_download').disabled=false;}}
  };
  const nativeDialog=node('dialog');nativeDialog.setAttribute('aria-label','已采视频云保存');
  const nativeMessage=node('p'),nativeSave=button('保存已采视频到云端',()=>nativeSaveVideo()),nativeDownload=button('下载云端已采视频',()=>nativeDownloadVideo());
  nativeDialog.append(node('h2','已采视频云保存'),node('p','保存本轮已有的 MP4，不重新访问平台。私有云限50MiB，保存与回取均核验字节；已有文件不等于平台完整视频。'),nativeMessage,nativeSave,nativeDownload,button('关闭已采视频云保存',()=>nativeDialog.close()));document.body.append(nativeDialog);
  let nativeSelection=null,nativeGeneration=0,nativeBusy=false,nativeReceived=false;
  const nativeCurrent=ticket=>nativeDialog.open&&ticket===nativeGeneration&&nativeSelection?.run_id===idOf(selectedRun);
  nativeDialog.addEventListener('close',()=>{nativeGeneration++;});
  function nativeRender(value){
    if(value.state==='received'){
      const r=value.receipt,m=r?.manifest;
      if(r?.artifact_kind!=='video_object'||r.status!=='received'||r.verification!=='server_storage_bytes_sha256'||m?.manifest_version!==2||m.representation!=='native_collected'||m.completeness!=='saved_asset_not_full_length_verified'||m.local_run_id!==nativeSelection.run_id||m.platform!==nativeSelection.platform||m.content_id!==nativeSelection.content_id||m.asset_sha256!==nativeSelection.asset_sha256||m.asset_bytes!==nativeSelection.bytes||nativeSelection.entity_ref&&m.entity_ref!==nativeSelection.entity_ref)throw Error('media_native_receipt_mismatch');
      nativeReceived=true;nativeMessage.textContent='云端已保存 · 文件字节校验通过 · 回执 '+String(r.artifact_id).slice(0,8)+'；未验平台完整时长。';
    }else if(['not_saved','outcome_unknown'].includes(value.state)){nativeReceived=false;nativeMessage.textContent=value.state==='outcome_unknown'?'云保存结果待核对，不自动重复上传。':'尚未保存到云端。';}else throw Error('media_native_state_invalid');
    nativeSave.textContent=value.state==='outcome_unknown'?'核对已采视频保存结果':'保存已采视频到云端';nativeSave.disabled=nativeBusy||nativeReceived;nativeDownload.hidden=!nativeReceived;nativeDownload.disabled=nativeBusy;
  }
  const nativePayload=()=>Object.fromEntries(['run_id','content_id','asset_sha256','entity_ref'].filter(k=>nativeSelection[k]!==undefined).map(k=>[k,nativeSelection[k]]));
  async function cloudVideo(file){
    const ticket=++nativeGeneration;nativeBusy=false;nativeReceived=false;nativeSelection={run_id:idOf(selectedRun),content_id:file.content_id,platform:file.platform,asset_sha256:file.sha256,bytes:file.bytes,...(file.entity_ref?{entity_ref:file.entity_ref}:{})};
    nativeMessage.textContent='核对原任务、视频与云回执…';nativeSave.disabled=true;nativeDownload.hidden=true;nativeDialog.showModal();
    if(file.source_kind!=='mediacrawler_api'||!/\.mp4$/i.test(file.path||'')||!/^[a-f0-9]{64}$/.test(file.sha256)||!Number.isInteger(file.bytes)||file.bytes<=0||file.bytes>50*1048576){nativeMessage.textContent='不是可保存的已采 MP4，或超过50MiB云上限。';return;}
    if(file.platform==='zhihu'){const rows=contentRows(file);if(rows.length!==1){nativeMessage.textContent='知乎视频缺少唯一类型身份，未上传。';return;}nativeSelection.entity_ref='zhihu:content:'+file.content_id+':'+file.source_content_type;}
    try{const value=await call('native_video_cloud_status',nativePayload());if(nativeCurrent(ticket))nativeRender(value);}catch(error){if(nativeCurrent(ticket))nativeMessage.textContent='暂不可保存：'+error.message;}
  }
  async function nativeSaveVideo(){
    const ticket=nativeGeneration;if(!nativeCurrent(ticket)||nativeBusy||nativeReceived)return;
    nativeBusy=true;nativeSave.disabled=true;nativeMessage.textContent='正在保存并核验云端文件…';
    try{const value=await call('native_video_cloud_save',nativePayload());if(nativeCurrent(ticket))nativeRender({state:'received',receipt:value.receipt});}catch(error){if(nativeCurrent(ticket))nativeMessage.textContent='云保存未确认：'+error.message;}finally{if(nativeCurrent(ticket)){nativeBusy=false;nativeSave.disabled=nativeReceived;nativeDownload.disabled=!nativeReceived;}}
  }
  async function nativeDownloadVideo(){
    const ticket=nativeGeneration;if(!nativeCurrent(ticket)||nativeBusy||!nativeReceived)return;const expected={...nativeSelection};nativeBusy=true;nativeDownload.disabled=true;
    try{const response=await fetch('/api/media-processing',{method:'POST',headers:{'Content-Type':'application/json','X-Crowd-CSRF':token},body:JSON.stringify({action:'native_video_cloud_file',payload:nativePayload()})});if(!response.ok)throw Error((await response.json()).error||'media_native_download_failed');const blob=await response.blob();if(!nativeCurrent(ticket))return;if(response.headers.get('X-Content-SHA256')!==expected.asset_sha256||blob.size!==expected.bytes)throw Error('media_native_download_mismatch');const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download='crowd-native-video-'+expected.content_id+'-'+expected.asset_sha256.slice(0,8)+'.mp4';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);nativeMessage.textContent='云端已采视频取回且字节校验通过；未验平台完整时长。';}catch(error){if(nativeCurrent(ticket))nativeMessage.textContent='回取未确认：'+error.message;}finally{if(nativeCurrent(ticket)){nativeBusy=false;nativeDownload.disabled=false;}}
  }
  return {open,openSaved,openVideoOCR,retryVideoOCR,openVideo,cloudVideo};
})();
