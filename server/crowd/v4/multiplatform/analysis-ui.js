'use strict';
// The saved input snapshot supplies citations even if imported results later change.
const analysisView = (() => {
  let current = null, generation = 0, timer = null;
  const states = {not_started:'尚未分析',queued:'等待分析',running:'正在分析',completed:'分析完成',failed:'分析未完成',cancelled:'已取消分析',interrupted_unknown:'分析中断，等待核对'};
  const errors = {analysis_provider_missing:'本机未找到可用的 Codex CLI。采集结果仍可查看。',analysis_busy:'已有分析正在运行，请等待或取消它。',analysis_timeout:'分析超过时限，已停止；原始采集结果保留。',analysis_provider_failed:'Codex 分析失败，请检查其登录、网络或额度；不会自动重试。',analysis_interrupted_check_before_retry:'工作台曾中断，尚不能确认模型请求是否完成。请先核对，系统不会自动重复调用。',analysis_comment_limit_exceeded:'这篇内容超过单次200条评论的分析范围，请先分批处理。',analysis_text_limit_exceeded:'这份正文和评论超过单次50000字范围，请先分批处理。',truncated_content_text:'正文已截断，暂不对残缺正文生成完整分析。'};
  const request = (action,payload) => api('/api/analysis',{action,payload});
  Object.assign(errors,{analysis_environment_denied:'当前运行环境限制了 Codex 分析。已有正文和评论仍可查看。',analysis_login_required:'Codex 需要重新登录；登录后再分析，不影响平台采集结果。',analysis_quota_exceeded:'Codex 额度或调用频率已达到限制。请等待额度恢复后再分析。',analysis_network_unavailable:'暂时无法连接 Codex 模型服务。请检查网络后再分析。',analysis_provider_incompatible:'当前 Codex 版本不支持这份分析接口，请更新客户端后再试。',analysis_transfer_authorization_required:'发送前需要明确授权本次材料范围。',analysis_snapshot_changed:'已保存材料发生变化，请刷新范围后再分析。'});
  function stopPolling(){clearTimeout(timer);timer=null;}
  function target(){return {run_id:idOf(selectedRun),platform:current.platform,content_id:current.content_id};}
  function section(label, rows, render){const d=node('details');d.open=true;d.append(node('summary',label));for(const row of rows)d.append(render(row));return d;}
  function paragraph(snapshot,index){return snapshot.paragraphs.find(row=>row.paragraph===index)?.text;}
  function citation(snapshot,index){const d=node('details');d.append(node('summary','原文依据 · '+snapshot.content.source_ref+' · '+(index===0?'标题':'段落 '+index)),node('p',paragraph(snapshot,index)||'未取得原文'));return d;}
  function render(job){
    if(job.snapshot_hash&&current)current.snapshot_hash=job.snapshot_hash;
    const panel=$('analysis_panel');panel.hidden=false;panel.replaceChildren(node('h3','正文与评论分析'),node('p',states[job.state]||job.state));
    panel.append(node('p','正文与评论会发送给已登录的 Codex 模型服务进行分析；报告为模型判断，统计由程序计算。'));
    panel.lastChild.className='hint';
    if(job.error)panel.append(node('p',errors[job.error]||('分析失败：'+job.error)));
    if(['queued','running'].includes(job.state)){
      const cancel=button('取消分析',async()=>{cancel.disabled=true;stopPolling();const ticket=++generation;try{await poll(await request('cancel',{job_id:job.job_id}),ticket);}finally{cancel.disabled=false;}});
      panel.append(cancel);return;
    }
    if(job.state!=='completed'){
      if(job.input_summary)panel.append(node('p',`本次范围：这篇已保存的文字与 ${job.input_summary.comments} 条评论；排除 ${job.input_summary.coverage.excluded_comments} 条无效记录。`));
      const start=button('发送所选文字并分析',()=>startAnalysis(),'primary');
      start.disabled=job.state==='interrupted_unknown'||!current?.snapshot_hash;panel.append(start);return;
    }
    const result=job.result,snapshot=result.input_snapshot,analysis=result.content_analysis,statistics=result.comment_statistics;
    panel.append(node('p',snapshot.content.scope==='title_only'?'素材范围：仅标题':'素材范围：原正文或视频简介；不含画面、音轨分析'),node('p',analysis.summary));
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
    stopPolling();const ticket=++generation;current={platform:row.platform,content_id:row.content_id};
    const panel=$('analysis_panel');panel.hidden=false;panel.replaceChildren(node('p','正在读取已有分析…'));panel.scrollIntoView({behavior:'smooth',block:'start'});
    try{await poll(await request('lookup',target()),ticket);}catch(error){if(ticket===generation)render({state:'failed',error:error.message});throw error;}
  }
  function reset(){stopPolling();generation++;current=null;$('analysis_panel').hidden=true;$('analysis_panel').replaceChildren();}
  return {open,reset};
})();
