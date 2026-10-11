'use strict';
// The saved input snapshot supplies citations even if imported results later change.
const analysisView = (() => {
  let current = null, generation = 0, timer = null;
  const states = {not_started:'尚未分析',queued:'等待分析',running:'正在分析',completed:'分析完成',failed:'分析未完成',cancelled:'已取消分析',interrupted_unknown:'分析中断，等待核对'};
  const errors = {analysis_provider_missing:'本机未找到可用的 Codex CLI。采集结果仍可查看。',analysis_busy:'已有分析正在运行，请等待或取消它。',analysis_timeout:'分析超过时限，已停止；原始采集结果保留。',analysis_provider_failed:'Codex 分析失败，请检查其登录、网络或额度；不会自动重试。',analysis_interrupted_check_before_retry:'工作台曾中断，尚不能确认模型请求是否完成。请先核对，系统不会自动重复调用。',analysis_comment_limit_exceeded:'这篇内容超过单次200条评论的分析范围，请先分批处理。',analysis_text_limit_exceeded:'这份正文和评论超过单次50000字范围，请先分批处理。',truncated_content_text:'正文已截断，暂不对残缺正文生成完整分析。'};
  const request = (action,payload) => api('/api/analysis',{action,payload});
  Object.assign(errors,{ambiguous_analysis_entity:'相同数字 ID 对应多种内容，请选择具体类型再分析。',analysis_entity_not_found:'所选内容类型在这份结果中不存在，请刷新结果。',invalid_results_entity_ref:'所选内容身份不匹配，不能分析其他平台或内容。',analysis_environment_denied:'当前运行环境限制了 Codex 分析。已有正文和评论仍可查看。',analysis_login_required:'Codex 需要重新登录；登录后再分析，不影响平台采集结果。',analysis_quota_exceeded:'Codex 额度或调用频率已达到限制。请等待额度恢复后再分析。',analysis_network_unavailable:'暂时无法连接 Codex 模型服务。请检查网络后再分析。',analysis_provider_incompatible:'当前 Codex 版本不支持这份分析接口，请更新客户端后再试。',analysis_transfer_authorization_required:'发送前需要明确授权本次材料范围。',analysis_snapshot_changed:'已保存材料发生变化，请刷新范围后再分析。'});
  function stopPolling(){clearTimeout(timer);timer=null;}
  function target(){return {run_id:idOf(selectedRun),platform:current.platform,content_id:current.content_id,...(current.entity_ref?{entity_ref:current.entity_ref}:{}),...(current.derivedRefs?.length?{derived_refs:current.derivedRefs}:{})};}
  function section(label, rows, render){const d=node('details');d.open=true;d.append(node('summary',label));for(const row of rows)d.append(render(row));return d;}
  function paragraph(snapshot,index){return snapshot.paragraphs.find(row=>row.paragraph===index)?.text;}
  function citation(snapshot,index){const row=snapshot.paragraphs.find(row=>row.paragraph===index),d=node('details');d.append(node('summary','依据 · '+(row?.source_ref||snapshot.content.source_ref)+' · '+(row?.kind?row.kind.toUpperCase()+' 候选 '+(row.start==null?'图像文字':row.start+'–'+row.end+'秒'):(index===0?'标题':'段落 '+index))),node('p',paragraph(snapshot,index)||'未取得原文'));return d;}
  function derivedPicker(panel,job){
    if(!Array.isArray(job.derived_options)||!job.derived_options.length){if(job.derived_excluded)panel.append(node('p','部分派生任务缺少可证明的实体或文件归属，未列入分析。'));return;}
    panel.append(node('h3','可选已保存的 ASR / OCR'),node('p','勾选后会加入本次发送范围。候选文字尚未人工核对，ASR和OCR分别引用，不代表识别正确。'));
    for(const item of job.derived_options){
      const label=node('label'),check=node('input');check.type='checkbox';check.checked=!!current?.derivedRefs?.some(ref=>ref.job_id===item.job_id);
      check.disabled=['running','queued'].includes(job.state);
      check.onchange=async()=>{const ref={job_id:item.job_id,result_sha256:item.result_sha256,asset_sha256:item.asset_sha256};let refs=(current.derivedRefs||[]).filter(value=>value.job_id!==item.job_id);if(check.checked)refs.push(ref);if(refs.length>5){check.checked=false;panel.append(node('p','一次最多选择5份派生任务。'));return;}current.derivedRefs=refs;current.snapshot_hash=null;stopPolling();const ticket=++generation;try{await poll(await request('lookup',target()),ticket);}catch(error){if(ticket===generation)render({state:'failed',error:error.message});}};
      label.append(check,node('span',item.kind.toUpperCase()+' · '+item.job_id.slice(0,8)+' · '+item.segments.length+' 段 · 尚未核对'));panel.append(label);
      const detail=node('details');detail.append(node('summary','查看候选文字与引用'),node('pre',item.segments.map(row=>(row.start==null?'': '['+row.start+'–'+row.end+'秒] ')+row.text).join('\n')),node('small','asset '+item.asset_sha256+' · result '+item.result_sha256+' · processor '+item.processor+' · model '+(item.model_manifest_sha256||'未记录')));panel.append(detail);
    }
  }
  function render(job){
    if(job.snapshot_hash&&current)current.snapshot_hash=job.snapshot_hash;
    const panel=$('analysis_panel');panel.hidden=false;panel.replaceChildren(node('h3',current?.kind==='dynamic'?'动态文字分析':'正文与评论分析'),node('p',states[job.state]||job.state));
    panel.append(node('p','正文与评论会发送给已登录的 Codex 模型服务进行分析；报告为模型判断，统计由程序计算。'));
    panel.lastChild.className='hint';
    derivedPicker(panel,job);
    if(job.error)panel.append(node('p',errors[job.error]||('分析失败：'+job.error)));
    if(['queued','running'].includes(job.state)){
      if(Number.isInteger(job.total_batches))panel.append(node('p',`全文分批分析：${job.completed_batches||0} / ${job.total_batches} 批。每批保留原时间引用。`));
      const cancel=button('取消分析',async()=>{cancel.disabled=true;stopPolling();const ticket=++generation;try{await poll(await request('cancel',{job_id:job.job_id}),ticket);}finally{cancel.disabled=false;}});
      panel.append(cancel);return;
    }
    if(job.state!=='completed'){
      if(job.input_summary){
        if(job.input_summary.analysis_batches)panel.append(node('p',`全部所选转写将分 ${job.input_summary.analysis_batches} 批分析；不会重新下载或转写。失败不自动重试。`));
        const coverage=job.input_summary.coverage||{},count=value=>Number.isSafeInteger(value)&&value>=0?value:'未提供';
        panel.append(node('p',`本次范围：这篇已保存的文字与 ${job.input_summary.comments} 条评论；排除 ${count(coverage.excluded_comments)} 条无效记录。`),node('p',`一级评论 ${count(coverage.roots)} / 回复 ${count(coverage.replies)} / 父关系未知 ${count(coverage.unknown_parent)}`));
      }
      const excluded=job.input_summary?.coverage?.excluded_reasons||{};
      if(excluded.unconfirmed_content_type||excluded.different_content_type)panel.append(node('p',`已排除 ${excluded.unconfirmed_content_type||0} 条类型归属不明及 ${excluded.different_content_type||0} 条其他类型评论，不混入所选正文。`));
      if(current?.kind==='dynamic')panel.append(node('p','只分析已保存的动态文字；当前不支持动态评论，不混入同数字 ID 的视频评论。'));
      const start=button('发送所选文字并分析',()=>startAnalysis(),'primary');
      start.disabled=job.state==='interrupted_unknown'||!current?.snapshot_hash;panel.append(start);return;
    }
    const result=job.result,snapshot=result.input_snapshot,analysis=result.content_analysis,statistics=result.comment_statistics;
    if(result.full_analysis_coverage){
      const receiptText=node('p','完整分析可保存到云端，不会重新采集或调用模型。');
      const publish=button('保存完整分析到云端',async()=>{
        publish.disabled=true;receiptText.textContent='正在保存完整分析…';
        try{const saved=await request('publish',{job_id:job.job_id});receiptText.textContent='云端已确认分析 · '+saved.receipt.artifact_id+' · '+saved.receipt.report_sha256;}
        catch(error){receiptText.textContent='分析尚未确认保存：'+error.message;}
        finally{publish.disabled=false;}
      });panel.append(publish,receiptText);
    }
    if(result.full_analysis_coverage)panel.append(node('p',`已分析全部 ${result.full_analysis_coverage.selected_segments} 个所选转写段，${result.full_analysis_coverage.batches_completed} 批；音频识别准确性仍待校对。`));
    panel.append(node('p',snapshot.derived_inputs?.length?'素材范围：原文字、评论及明确勾选的ASR/OCR候选，均需核对':snapshot.content.scope==='title_only'?'素材范围：仅标题':snapshot.content.kind==='dynamic'?'素材范围：原动态文字；不含视频、画面、音轨或动态评论':'素材范围：原正文或视频简介；不含画面、音轨分析'),node('p',analysis.summary));
    panel.append(section('内容结构',analysis.segments,row=>{const d=node('div');d.append(node('strong',row.role),node('p',row.observation),citation(snapshot,row.paragraph));return d;}));
    panel.append(section('原文声称 · 尚未核实',analysis.claims,row=>{const d=node('div');d.append(node('p',row.claim),citation(snapshot,row.paragraph));return d;}));
    panel.append(section('可借鉴的方法',analysis.reusable_methods,row=>{const d=node('div');d.append(node('p',row.method),citation(snapshot,row.paragraph));return d;}));
    panel.append(node('h3','评论样本'));
    panel.append(node('p',`唯一评论 ${statistics.unique_comments} 条 · 已标 ${statistics.labeled} 条 · 待标 ${statistics.pending} 条 · 排除 ${statistics.coverage.excluded_comments} 条 · 重复 ${statistics.coverage.duplicates} 条`));
    panel.append(node('p',`原记录声明根评论 ${statistics.coverage.roots} 条 · 回复 ${statistics.coverage.replies} 条 · 父节点未知 ${statistics.coverage.unknown_parent} 条。比例分母为 ${statistics.denominator} 条已标评论，不代表全体读者。`));
    const table=node('table'),heading=node('tr');['情绪','数量','样本内比例'].forEach(x=>heading.append(node('th',x)));table.append(heading);
    const sentiments={positive:'正面',negative:'负面',neutral:'中性',mixed:'混合',unknown:'已审但不确定'};
    for(const [key,value]of Object.entries(statistics.counts.sentiment)){const tr=node('tr');[sentiments[key]||key,value,statistics.proportions.sentiment[key]==null?'无分母':statistics.proportions.sentiment[key]+'%'].forEach(x=>tr.append(node('td',x)));table.append(tr);}panel.append(table);
    for(const [key,label]of Object.entries({intent:'表达意图',aspects:'关注主题'})){
      panel.append(section(label+' · 可多选',Object.entries(statistics.counts[key]),([tag,count])=>node('p',`${tag}：${count} 条`)));
    }
    const originals=new Map(snapshot.comments.map(c=>[c.comment_id,c]));
    panel.append(section('逐条判断与原评论',result.comment_labels,row=>{const d=node('div'),original=originals.get(row.comment_id);d.append(node('p',original?.text||''),node('p',(sentiments[row.sentiment]||row.sentiment)+' · '+row.rationale),node('small',row.source_ref+' · '+row.comment_id));return d;}));
    panel.append(section('限制与缺口',analysis.limitations,line=>node('p',line)),node('p','正文、评论的真实性和模型标签仍需核对。评论情绪对象可能是信息、食物或其他评论者，不能当成餐厅评分。'));
    panel.append(button('下载分析与引用 JSON',()=>download('crowd-analysis-'+job.job_id+'.json',job),'primary'));
    panel.append(node('p','输入版本 '+job.snapshot_hash+' · '+job.provider_version));panel.lastChild.className='hint';
  }
  async function poll(job,ticket){
    if(ticket!==generation)return;render(job);
    if(['queued','running'].includes(job.state))timer=setTimeout(()=>guarded(async()=>{const next=await request('status',{job_id:job.job_id});await poll(next,ticket);}),1500);
  }
  async function startAnalysis(){stopPolling();const ticket=++generation;const panel=$('analysis_panel');panel.replaceChildren(node('p','正在提交分析…'));try{const job=await request('start',{...target(),snapshot_hash:current.snapshot_hash,allow_model_transfer:true});await poll(job,ticket);}catch(error){if(ticket===generation){if(error.message==='analysis_snapshot_changed'){await poll(await request('lookup',target()),ticket);if(ticket===generation)panel.prepend(node('p','采集结果已更新。请核对刷新后的材料范围，再决定是否发送。'));return;}render({state:'failed',error:error.message});}throw error;}}
  async function open(row){
    stopPolling();const ticket=++generation;current={platform:row.platform,content_id:row.content_id,kind:row.kind};
    current.entity_ref=row.entity_ref||(row.platform==='zhihu'&&['answer','article','zvideo'].includes(row.content_type)?'zhihu:content:'+row.content_id+':'+row.content_type:row.kind==='dynamic'?'bilibili:dynamic:'+row.content_id:null);
    const panel=$('analysis_panel');panel.hidden=false;panel.replaceChildren(node('p','正在读取已有分析…'));panel.scrollIntoView({behavior:'smooth',block:'start'});
    try{await poll(await request('lookup',target()),ticket);}catch(error){if(ticket===generation)render({state:'failed',error:error.message});throw error;}
  }
  function reset(){stopPolling();generation++;current=null;$('analysis_panel').hidden=true;$('analysis_panel').replaceChildren();}
  return {open,reset};
})();
