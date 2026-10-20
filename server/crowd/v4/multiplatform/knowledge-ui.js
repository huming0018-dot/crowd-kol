'use strict';
// Uses existing host api/node/button helpers and its Owner Origin/CSRF boundary.
const knowledgeView = (() => {
  const call = (action, payload = {}) => api('/api/knowledge', {action, payload});
  const dialog = node('dialog'), body = node('div'), close = button('关闭', () => dialog.close());
  dialog.setAttribute('aria-label', '知识提案审核'); body.className = 'dialog-body';
  const publicationBody = node('div'), feedbackBody = node('section'), gapsBody=node('section');
  dialog.append(close, feedbackBody, gapsBody, body, publicationBody); document.body.append(dialog);
  const draftsBody=node('section');dialog.append(draftsBody);
  let generation = 0, busy = false, current = null, draftReason = '';
  const storageKey = 'crowd:knowledge:pending-intent';
  dialog.addEventListener('close', () => { generation++; current = null; });
  const isCurrent = ticket => ticket === generation && dialog.open;
  function remembered() { try { return localStorage.getItem(storageKey); } catch { return null; } }
  function remember(id) { try { localStorage.setItem(storageKey, id); } catch { /* Server intent remains durable. */ } }
  function details(label, value) { const d = node('details'); d.append(node('summary', label), node('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2))); return d; }
  async function check(id, ticket) {
    try { const result = await call('status', {intent_id:id}); if (isCurrent(ticket)) { body.append(node('p', result.message)); if (result.state === 'accepted') await publication(ticket); } }
    catch { if (isCurrent(ticket)) body.append(node('p', '原决定状态暂时无法读取，请稍后核对；不会自动重发。')); }
  }
  function render(value, ticket) {
    current = value; body.replaceChildren(node('h2', '查看知识改动'), node('p', value.notice));
    const labels = {address:'地址核验',current_status:'营业核验'};
    body.append(node('p', '本次影响：'+Object.entries(value.added_unknowns).map(([key,count]) => (labels[key] || key)+'新增'+count+'项待确认').join('；')+'。其他内容是否保持请查看下方证据。'));
    body.append(node('p', '采用仅记录批准。发布生效、结果版本切换另行处理。'));
    body.append(node('p', '本次预览有效5分钟；超时请刷新提案，审核理由保留。'));
    for (const id of value.unresolved_decisions || []) body.append(button('核对原审核决定', () => check(id, ticket)));
    for (const file of value.files) if (file.changed) body.append(details(file.name+' 改动', file.diff));
    body.append(details('来源与证据', {gap:value.observed_gap,evidence:value.evidence_refs,quotes:value.quotes_preserved,sources:value.source_versions_preserved}));
    body.append(details('版本与审核边界', {proposal_id:value.proposal_id,candidate_hash:value.candidate_hash,role:value.role_state,principal:value.principal_kind,human_uid:value.human_uid}));
    const label = node('label', '审核理由'), reason = node('textarea'); reason.value = draftReason; reason.addEventListener('input', () => { draftReason = reason.value; }); reason.maxLength = 2000; reason.required = true; label.append(reason); body.append(label);
    const note = node('p'); note.setAttribute('role', 'status'); body.append(note); const buttons = [];
    async function decide(decision) {
      if (busy || !isCurrent(ticket)) return;
      if (!reason.value.trim()) { note.textContent = '请填写本次决定的理由。'; reason.focus(); return; }
      draftReason = reason.value; busy = true; buttons.forEach(b => b.disabled = true);
      const intent = crypto.randomUUID(); remember(intent);
      const payload = {decision,reason:reason.value.trim(),expected_candidate_hash:value.candidate_hash,preview_token:value.preview_token,intent_id:intent};
      note.textContent = '正在记录决定…';
      try { const result = await call('decide', payload); if (isCurrent(ticket)) { busy = false; note.textContent = result.message; if (result.state === 'not_submitted') body.append(button('刷新提案（保留理由）', () => show())); await publication(ticket); } }
      catch { if (isCurrent(ticket)) { note.textContent = '决定结果待核对，请保留原记录；不会自动再次提交。'; body.append(button('核对原决定', () => check(intent, ticket))); } }
      finally { busy = false; /* A new decision requires reopening a fresh preview. */ }
    }
    for (const [key, text] of [['approved','采用'],['request_changes','退回修改'],['rejected','不采用']]) {
      const b = button(text, () => decide(key)); b.disabled = !value.decision_available || !value.actions?.[key]?.enabled; buttons.push(b); body.append(b);
    }
  }
  const publicationKey = 'crowd:knowledge:publication-intent';
  function publicationIntent() { try { return localStorage.getItem(publicationKey); } catch { return null; } }
  async function publicationStatus(id, ticket) {
    try {
      const result = await call('publication_status', {intent_id:id});
      if (isCurrent(ticket)) { publicationBody.append(node('p', result.message)); await publication(ticket); }
    } catch { if (isCurrent(ticket)) publicationBody.append(node('p', '发布结果待核对；请保留原请求，不要换请求重试。')); }
  }
  async function publication(ticket) {
    if (!isCurrent(ticket)) return;
    publicationBody.replaceChildren(node('h2', '知识包发布与版本选择'));
    const last = publicationIntent();
    if (last) publicationBody.append(button('核对上次发布操作', () => publicationStatus(last, ticket)));
    try {
      const value = await call('publication_preview');
      if (!isCurrent(ticket)) return;
      publicationBody.append(node('p', value.message));
      publicationBody.append(node('p', value.accepted ? '原提案已有已记录的批准；发布仍需单独点击。' : '尚无可核的已批准原决定，不能发布或切换新版。'));
      if (value.rollback_notice) publicationBody.append(node('p', value.rollback_notice));
      if (value.unresolved_write) publicationBody.append(node('p', '存在结果待核对的发布操作，新发布或版本切换已阻止；不会自动重试。'));
      publicationBody.append(details('知识版本记录', {release:value.candidate_release,current:value.current_knowledge_pin,rollback:value.rollback_release}));
      const note = node('p'); note.setAttribute('role', 'status'); publicationBody.append(note);
      const controls = [];
      async function write(action) {
        if (busy || !isCurrent(ticket) || !value.actions[action]) return;
        busy = true; controls.forEach(b => b.disabled = true);
        const intent = crypto.randomUUID();
        try { localStorage.setItem(publicationKey, intent); } catch { /* Durable server journal remains authoritative. */ }
        note.textContent = '正在记录本次明确操作…';
        try {
          const result = await call('publication_'+action, {intent_id:intent});
          if (isCurrent(ticket)) { busy = false; note.textContent = result.message; await publication(ticket); }
        } catch {
          if (isCurrent(ticket)) { note.textContent = '结果待核对；不会自动再发，也不能换请求绕过未知结果。'; publicationBody.append(button('核对原发布操作', () => publicationStatus(intent, ticket))); }
        } finally { busy = false; }
      }
      for (const [action, text] of [['release','发布已批准知识包'],['pin','切换knowledge pin（消费者不变）'],['rollback','回到原已发布knowledge pin']]) {
        const b = button(text, () => write(action)); b.disabled = !value.actions[action] || busy; controls.push(b); publicationBody.append(b);
      }
    } catch { if (isCurrent(ticket)) publicationBody.append(node('p', '发布前置尚未接通或记录待核对；原决定、现有结果保持。')); }
  }
  const gapTypes={'regression-miss':'回归未覆盖','taxonomy-gap':'分类待补','rubric-gap':'评分规则待补'};
  let gapsGeneration=0;
  async function gapList(ticket,after=null){
    const request=++gapsGeneration,valid=()=>isCurrent(ticket)&&request===gapsGeneration;
    gapsBody.replaceChildren(node('h2','待处理知识缺口'),node('p','正在核对缺口回执…'));
    try{
      const value=await call('material_feedback_gap_list',{after});
      if(!valid())return;
      if(value.state!=='material_feedback_gaps'||!Array.isArray(value.items)||value.items.length>20)throw Error('invalid_gap_list');
      gapsBody.replaceChildren(node('h2','待处理知识缺口'),node('p','转入缺口不等于生成或批准知识改动。此处保留原反馈与素材血缘。'),button('刷新知识缺口',()=>gapList(ticket)));
      if(!value.items.length)gapsBody.append(node('p','本页暂无已转入的知识缺口。'));
      for(const row of value.items){
        const article=node('article'),note=node('p');
        article.append(node('h3',row.state==='outcome_unknown'?'缺口入库结果待核对':row.title||'待处理知识缺口'));
        if(row.state==='pending_gap')article.append(node('p',gapTypes[row.gap_type]||row.gap_type),node('p',row.description||''));
        article.append(details('原反馈、缺口与素材回执',row));
        article.append(button('核对原缺口',async()=>{try{const result=await call('material_feedback_gap_status',{feedback_intent:row.feedback_intent});if(valid())note.textContent='原缺口状态：'+result.state+'；未审核、发布。';}catch{if(valid())note.textContent='原缺口暂时无法核对；不重新提交。';}}),note);gapsBody.append(article);
      }
      if(value.next_cursor)gapsBody.append(button('下一页知识缺口',()=>gapList(ticket,value.next_cursor)));
    }catch{if(valid())gapsBody.replaceChildren(node('h2','待处理知识缺口'),node('p','知识缺口暂时无法核验；不会当作空列表。'),button('重读知识缺口',()=>gapList(ticket)));}
  }
  async function feedbackGap(parent,row,ticket){
    const panel=node('section'),version=feedbackGeneration;parent.append(panel);const valid=()=>isCurrent(ticket)&&version===feedbackGeneration;
    panel.replaceChildren(node('p','正在核对原反馈与可转入范围…'));
    try{
      const value=await call('material_feedback_gap_preview',{feedback_intent:row.intent_id});
      if(!valid())return;
      if(value.state!=='gap_preview'||value.feedback_intent!==row.intent_id||value.kind!=='want_to_know'||!/^[a-f0-9]{64}$/.test(value.feedback_sha256)||JSON.stringify([...(value.allowed_gap_types||[])].sort())!==JSON.stringify(Object.keys(gapTypes).sort()))throw Error('invalid_gap_preview');
      const note=node('p');note.setAttribute('role','status');
      async function check(){try{const result=await call('material_feedback_gap_status',{feedback_intent:row.intent_id});if(valid()){note.textContent='原缺口状态：'+result.state+'；未审核、发布。';if(result.state==='pending_gap')await gapList(ticket);}}catch{if(valid())note.textContent='原缺口暂时无法核对；不会重新提交。';}}
      panel.replaceChildren(node('h4','转入待处理知识缺口'),node('p','请选择缺口类型并确认标题与说明；只保存待处理问题，不调用模型、不审核或发布。'));
      if(value.existing){panel.append(node('p','已有原缺口记录：'+value.existing.state),button('核对原缺口',check),note);return;}
      const type=node('select'),title=node('input'),description=node('textarea'),consent=node('input');
      type.setAttribute('aria-label','知识缺口类型');title.setAttribute('aria-label','知识缺口标题');description.setAttribute('aria-label','知识缺口说明');
      const empty=node('option','请选择缺口类型');empty.value='';type.append(empty);
      for(const [key,label]of Object.entries(gapTypes)){const option=node('option',label);option.value=key;type.append(option);}
      title.value=value.reason.replace(/\s+/g,' ').slice(0,120);title.maxLength=200;description.value=value.reason;description.maxLength=2000;consent.type='checkbox';
      const permission=node('label','确认仅在原私有空间建立待处理缺口');permission.prepend(consent);let busy=false,settled=false;
      const submit=button('提交知识缺口',async()=>{
        if(busy||settled||!valid())return;
        if(!Object.hasOwn(gapTypes,type.value)||!title.value.trim()||!description.value.trim()||!consent.checked){note.textContent='请选择类型、填写标题与说明，并确认私有保存。';return;}
        busy=true;submit.disabled=true;note.textContent='正在保存知识缺口…';
        try{
          const result=await call('material_feedback_gap_submit',{feedback_intent:row.intent_id,expected_feedback_sha256:value.feedback_sha256,gap_type:type.value,title:title.value.trim(),description:description.value.trim(),consent_private:true});
          settled=true;if(!valid())return;
          if(result.state==='not_submitted'){note.textContent='本次缺口未提交，原反馈保持；请刷新反馈列表后核对输入。';return;}
          note.textContent=result.state==='pending_gap'?'已进入待处理知识缺口；尚未生成或批准知识改动。':'结果待核对；保留原反馈编号，不重复提交。';
          panel.append(button('核对原缺口',check));await gapList(ticket);
        }catch{settled=true;if(valid()){note.textContent='结果待核对；请核对原缺口，不重复提交。';panel.append(button('核对原缺口',check));}}
        finally{busy=false;}
      });
      panel.append(type,title,description,permission,submit,note);
    }catch{if(valid())panel.replaceChildren(node('p','原反馈暂时无法核验或不适用于知识缺口；没有自动转入。'));}
  }

  let feedbackGeneration = 0;
  async function feedbackInbox(ticket,after=null) {
    const request=++feedbackGeneration,valid=()=>isCurrent(ticket)&&request===feedbackGeneration;
    feedbackBody.replaceChildren(node('h2','素材反馈待处理'),node('p','正在核对已保存反馈…'));
    try {
      const value=await call('material_feedback_inbox',{after});
      if(!valid())return;
      if(value.state!=='material_feedback_inbox'||!Array.isArray(value.items)||value.items.length>20)throw Error('invalid_feedback_inbox');
      feedbackBody.replaceChildren(node('h2','素材反馈待处理'),node('p','反馈已保存不等于已审核或更新知识。这里只读取本授权空间中、本机提交的素材反馈。'));
      feedbackBody.append(button('刷新反馈列表',()=>feedbackInbox(ticket)));
      if(!value.items.length)feedbackBody.append(node('p','本页暂无素材反馈；已有提案与结果保留。'));
      const kinds={preference:'偏好',ignore:'不感兴趣',want_to_know:'进一步了解',experienced:'已体验反馈'};
      for(const row of value.items){
        const article=node('article'),note=node('p');
        article.append(node('h3',row.state==='outcome_unknown'?'提交结果待核对':(kinds[row.kind]||'素材反馈')+' · 已入库，未审核'));
        if(row.state!=='outcome_unknown'){
          article.append(node('p',row.reason||''));
          if(row.quote)article.append(node('blockquote',row.quote));
          if(/^pro-[a-f0-9]{64}$/.test(row.pro_key)&&/^[a-f0-9]{64}$/.test(row.job_id)){
            const link=node('a','查看提交时的原素材版本');link.href='/materials/pro/'+row.pro_key+'/versions/'+row.job_id;article.append(link);
          }
          article.append(details('原素材、版本与回执',{project:row.source_project,job_id:row.job_id,request:row.request,record_hash:row.record_hash,pack:row.pack_ref,feedback_id:row.feedback_id,principal:row.principal_kind,human_uid:row.human_uid}));
        } else article.append(node('p','保留原编号，仅核对结果；不会重发反馈或创建知识决定。'));
        article.append(node('p','反馈编号：'+row.intent_id),button('核对原反馈',async()=>{
          try{const result=await call('material_feedback_status',{intent_id:row.intent_id});if(valid())note.textContent='原反馈状态：'+result.state+'；未审核、发布。';}
          catch{if(valid())note.textContent='原反馈暂时无法核对；不自动重发。';}
        }),note);
        if(row.state==='pending_feedback'&&row.kind==='want_to_know'){let opened=false;article.append(button('转为知识缺口',()=>{if(opened||!isCurrent(ticket))return;opened=true;return feedbackGap(article,row,ticket);}));}
        feedbackBody.append(article);
      }
      if(value.next_cursor)feedbackBody.append(button('下一页反馈',()=>feedbackInbox(ticket,value.next_cursor)));
    } catch {if(valid())feedbackBody.replaceChildren(node('h2','素材反馈待处理'),node('p','反馈列表暂时无法核验；不会把错误显示为没有反馈。'),button('重读反馈列表',()=>feedbackInbox(ticket)));}
  }
  async function drafts(ticket) {
    draftsBody.replaceChildren(node('h2','知识草案与验证结果'),node('p','正在核对草案证据…'));
    try {
      const value=await call('draft_preview');
      if(!isCurrent(ticket))return;
      if(value.state!=='knowledge_draft_preview'||!Array.isArray(value.items)||value.items.length>20||value.live_database_changed!==false||value.decision_available!==false)throw Error('invalid_draft_preview');
      draftsBody.replaceChildren(node('h2','知识草案与验证结果'));
      if(!value.items.length)draftsBody.append(node('p','当前没有接入的知识草案。'));
      for(const row of value.items){
        if(row.published!==false||row.reviewed!==false||row.pin_changed!==false||row.knowledge_live_submission!==false)throw Error('invalid_draft_state');
        const article=node('article');
        article.append(node('h3',row.title),node('p','只读草案 · 未审核、未发布，现有结果与评分保持。'));
        article.append(node('p','当前处理版本 '+row.original_processing_pack.version+'；生成上下文 '+row.proposal_base_ref.version+'；草案目标 '+row.draft_target_ref.version+'。'));
        article.append(node('p','基于原4条素材的影响对照；隔离运行通过不等于正式重算或发布。'));
        article.append(details('同输入对照与来源', {impact:row.same_input_impact,source:row.source,gap:row.original_gap_context}));
        article.append(details('草案内容',row.objects),details('六文件改动',row.diff));
        article.append(details('生成与发布边界',{generation:row.generation,limits:row.limits,next:row.publication_gap}));
        draftsBody.append(article);
      }
    }catch{if(isCurrent(ticket))draftsBody.replaceChildren(node('h2','知识草案与验证结果'),node('p','草案证据暂时无法核验；不显示为没有草案，也不自动审核或发布。'));}
  }
  async function show() {
    const ticket = ++generation; current = null; body.replaceChildren(node('p', '正在读取知识提案…'));
    if (!dialog.open) dialog.showModal();
    publication(ticket);feedbackInbox(ticket);gapList(ticket);drafts(ticket);
    const last = remembered(); if (last) body.append(button('核对上次决定', () => check(last, ticket)));
    try { const value = await call('preview'); if (isCurrent(ticket)) { render(value, ticket); if (last) body.append(button('核对上次决定', () => check(last, ticket))); } }
    catch { if (isCurrent(ticket)) { body.replaceChildren(node('p', '提案暂时无法读取或权限尚未接通；当前结果与原决定保留。')); if (last) body.append(button('核对上次决定', () => check(last, ticket))); } }
  }
  return {show};
})();
