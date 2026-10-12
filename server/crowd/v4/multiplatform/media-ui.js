'use strict';
const mediaView = (() => {
  const call=(action,payload={})=>api('/api/media-processing',{action,payload});
  const dialog=node('dialog');dialog.id='media_process_dialog';dialog.setAttribute('aria-labelledby','media_process_title');
  dialog.innerHTML=`<div class="dialog-head"><h2 id="media_process_title">本地媒体处理</h2><button type="button" id="media_process_close">关闭</button></div><div class="dialog-body"><p class="hint">仅处理本轮已经下载的文件。不会重新下载或上传素材；关联内容由你选择。</p><label>这份文件属于哪条内容？<select id="media_content"></select></label><label>处理方式<select id="media_kind"><option value="ocr">图片文字 OCR</option><option value="asr">音视频本地转写</option><option value="transcript">导入已有字幕</option></select></label><p id="media_process_hint" class="hint"></p><p id="media_process_state" role="status"></p><div class="actions"><button id="media_process_start" class="primary">处理已下载文件</button><button id="media_process_cancel" disabled>取消处理</button><button id="media_process_resume" hidden>从断点继续</button></div><details><summary>本轮已保存的处理任务与断点</summary><div id="media_process_jobs"></div></details><pre id="media_process_result" hidden></pre></div>`;
  document.body.append(dialog);let selection=null,job=null,generation=0,timer=null,jobGeneration=0;
  const qualityOutput=node('pre');qualityOutput.id='media_process_quality';qualityOutput.hidden=true;dialog.append(qualityOutput);
  const exportPanel=node('div');exportPanel.id='media_process_exports';exportPanel.hidden=true;dialog.append(exportPanel);
  const playbackPanel=node('details'),player=node('video'),playbackMessage=node('p');player.controls=true;player.preload='metadata';
  playbackPanel.append(node('summary','按时间试听原素材 · 不代表已校对'),player,playbackMessage);playbackPanel.hidden=true;dialog.append(playbackPanel);
  let playbackUrl=null,playbackGeneration=0;
  function clearPlayback(){exportPanel.hidden=true;exportPanel.replaceChildren();playbackGeneration++;player.pause?.();player.removeAttribute?.('src');player.load?.();if(playbackUrl)URL.revokeObjectURL(playbackUrl);playbackUrl=null;player.onloadedmetadata=null;player.ontimeupdate=null;playbackPanel.hidden=true;playbackMessage.textContent='';while(playbackPanel.children.length>3)playbackPanel.lastChild.remove();}
  function renderExports(state){
    if(state.state!=='completed'||state.kind!=='asr'||!Array.isArray(state.result)||state.result.length!==1)return;
    const item=state.result[0],evidence=item?.evidence,hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
    if(!evidence||evidence.asset_sha256!==state.asset_sha256||!hash(state.asset_sha256)||!hash(state.input_hash)||item.platform!==state.platform||item.content_id!==state.content_id||!Array.isArray(evidence.segments)||!evidence.segments.length)return;
    const viewTicket=generation,jobTicket=jobGeneration;
    const identity=Object.fromEntries(['job_id','run_id','platform','content_id','entity_ref','asset_sha256','input_hash','result_sha256','model_manifest_sha256','processor_files','created_at'].filter(key=>state[key]!==undefined).map(key=>[key,state[key]]));
    const payload={schema_version:1,job:identity,semantic_review:'not_reviewed',full_segments:true,result:state.result};
    const valid=()=>dialog.open&&viewTicket===generation&&jobTicket===jobGeneration&&job===state;
    exportPanel.hidden=false;
    exportPanel.append(node('p','导出全部时间段；不受正文预览截断限制。包含原任务身份与诊断，仍待听音校对。'),
      button('导出完整转写 JSON',()=>{if(valid())download('crowd-transcript-'+state.job_id+'.json',payload);}),
      button('导出完整转写 TXT',()=>{
        if(!valid())return;
        const lines=['完整转写 · 未人工校对',JSON.stringify(identity,null,2),'',...evidence.segments.map(row=>'['+row.start+'–'+row.end+'] '+row.text),'','原生诊断与时间来源（提示不代表准确率）',JSON.stringify({quality_diagnostics:evidence.quality_diagnostics??null,native_alignment_windows:evidence.native_alignment_windows??null,timing_adjustments:evidence.timing_adjustments??null,overlap_decisions:evidence.overlap_decisions??null},null,2)];
        const url=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/plain;charset=utf-8'})),a=node('a');a.href=url;a.download='crowd-transcript-'+state.job_id+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }));
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
    const quality=evidence.quality_diagnostics;
    if(!quality||quality.schema_version!==1||!['available','partial'].includes(quality.status)||!Array.isArray(quality.segments)||!quality.segments.length)return '模型诊断：未记录（unknown）。旧结果或本次处理缺少原生诊断，仍需听音核对。';
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
    return lines.join('\n');
  }
  $('media_process_close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{generation++;clearTimeout(timer);timer=null;clearPlayback();});
  async function poll(id,ticket,jobTicket=jobGeneration){const state=await call('status',{job_id:id});if(ticket!==generation||jobTicket!==jobGeneration||!dialog.open)return;render(state);if(!['completed','failed','cancelled','interrupted_unknown'].includes(state.state))timer=setTimeout(()=>guarded(()=>poll(id,ticket,jobTicket)),1500);}
  function render(state){job=state;$('media_process_state').textContent=({queued:'等待处理',running:'正在本机处理',completed:'处理已保存，待人工核对',failed:'处理失败，原文件保留',cancelled:'已取消',interrupted_unknown:'处理结果待核对'})[state.state]||state.state;if(state.total_chunks)$('media_process_state').textContent+=' · 已处理 '+(state.completed_chunks||0)+' / '+state.total_chunks+' 段';if(state.reason)$('media_process_state').textContent+='：'+state.reason;$('media_process_resume').hidden=!(['failed','cancelled'].includes(state.state)&&state.checkpoint_available);$('media_process_cancel').disabled=['completed','failed','cancelled','interrupted_unknown'].includes(state.state);$('media_process_result').hidden=!state.result;if(state.result)$('media_process_result').textContent=state.result.map(item=>item.evidence?.segments?.length?item.evidence.segments.map(segment=>'['+segment.start+'–'+segment.end+'] '+segment.text).join('\n'):item.evidence?.raw_text||item.text||'本段未识别到文字').join('\n\n');const evidence=(state.result||[]).map(item=>item.evidence).filter(item=>item&&(item.segments||['faster_whisper_local','faster_whisper_local_segmented','apple_speech_ondevice'].includes(item.processor)));qualityOutput.hidden=!evidence.length;qualityOutput.textContent=evidence.map(qualityText).join('\n\n');renderPlayback(state,evidence);renderExports(state);}
  async function history(ticket){const saved=await call('list',{run_id:selection.run_id});if(ticket!==generation||!dialog.open)return;$('media_process_jobs').replaceChildren();for(const item of saved.jobs||[]){const row=node('p'),created=typeof item.created_at==='number'&&Number.isFinite(item.created_at)&&item.created_at>0&&Number.isFinite(new Date(item.created_at*1000).getTime())?new Date(item.created_at*1000).toLocaleString('zh-CN',{hour12:false}):'未记录';row.append(node('span',item.content_id+' · '+item.kind+' · '+item.state+' · 创建 '+created+' · 任务 '+String(item.job_id||'未记录').slice(0,8)+' '),button('查看此任务',()=>guarded(async()=>{clearTimeout(timer);clearPlayback();const jobTicket=++jobGeneration;const state=await call('status',{job_id:item.job_id});if(ticket!==generation||jobTicket!==jobGeneration||!dialog.open)return;render(state);await poll(item.job_id,ticket,jobTicket);})));$('media_process_jobs').append(row);}if(!(saved.jobs||[]).length)$('media_process_jobs').append(node('p','暂无已保存任务。'));}
  function contentRows(file){const rows=(resultData.records||[]).filter(row=>['content','dynamic'].includes(row.kind));if(file.platform!=='zhihu'&&!String(file.path).startsWith('output/zhihu/'))return rows;const same=rows.filter(row=>row.platform==='zhihu'&&row.content_id===file.content_id);return ['answer','article','zvideo'].includes(file.source_content_type)&&same.length===1&&same[0].content_type===file.source_content_type?same:[];}
  async function open(file){generation++;jobGeneration++;clearTimeout(timer);clearPlayback();selection={run_id:idOf(selectedRun),path:file.path};job=null;qualityOutput.hidden=true;qualityOutput.textContent='';$('media_process_resume').disabled=false;$('media_process_resume').hidden=true;$('media_process_cancel').disabled=true;$('media_process_result').hidden=true;$('media_process_state').textContent='';$('media_content').replaceChildren();for(const row of contentRows(file))$('media_content').append(new Option(row.title||row.content_id,row.content_id));dialog.showModal();const identityMissing=(file.platform==='zhihu'||String(file.path).startsWith('output/zhihu/'))&&!$('media_content').options.length;if(identityMissing)$('media_process_state').textContent='知乎素材缺少唯一类型身份，暂不可处理；仍可下载。';const ticket=generation;let caps;try{caps=await call('capabilities');}catch(error){if(ticket===generation&&dialog.open)$('media_process_state').textContent=error.message;return;}if(ticket!==generation||!dialog.open)return;for(const option of $('media_kind').options)option.disabled=!caps[option.value];const ext=String(file.path).split('.').pop().toLowerCase();$('media_kind').value=['jpg','jpeg','png','webp'].includes(ext)?'ocr':['vtt','srt','txt'].includes(ext)?'transcript':'asr';$('media_process_hint').textContent=caps.asr?'本地 '+(caps.asr_model_name||'语音')+' 模型已配置，结果可按时间核对。最长 '+Math.floor((['m4a','mp3','aac'].includes(ext)?caps.limits?.long_audio_seconds||7200:caps.limits?.max_audio_seconds||3600)/60)+' 分钟、文件'+(['m4a','mp3','aac'].includes(ext)?64:25)+'MiB；分段处理，可从断点继续。':'本机尚未配置语音模型。图片和已有字幕可用；音视频转写需先配置本地模型。';$('media_process_start').disabled=!$('media_content').options.length||$('media_kind').selectedOptions[0]?.disabled;try{await history(ticket);}catch(error){if(ticket===generation&&dialog.open)$('media_process_state').textContent='已保存任务读取失败：'+error.message;}}
  $('media_kind').onchange=()=>{$('media_process_start').disabled=!$('media_content').options.length||$('media_kind').selectedOptions[0]?.disabled;};
  $('media_process_start').onclick=()=>guarded(async()=>{const ticket=generation,jobTicket=++jobGeneration;clearTimeout(timer);clearPlayback();$('media_process_start').disabled=true;try{const state=await call('start',{...selection,content_id:$('media_content').value,kind:$('media_kind').value});if(ticket!==generation||jobTicket!==jobGeneration||!dialog.open)return;render(state);await poll(state.job_id,ticket,jobTicket);}catch(error){if(ticket===generation&&jobTicket===jobGeneration&&dialog.open)$('media_process_state').textContent=error.message;}finally{if(ticket===generation&&jobTicket===jobGeneration)$('media_process_start').disabled=false;}});
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
  return {open,openVideo};
})();
