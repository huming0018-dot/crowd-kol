'use strict';
// Uses existing host api/node/button helpers and its Owner Origin/CSRF boundary.
const knowledgeView = (() => {
  const call = (action, payload = {}) => api('/api/knowledge', {action, payload});
  const dialog = node('dialog'), body = node('div'), close = button('关闭', () => dialog.close());
  dialog.setAttribute('aria-label', '知识提案审核'); body.className = 'dialog-body';
  const publicationBody = node('div'), feedbackBody = node('section');
  dialog.append(close, feedbackBody, body, publicationBody); document.body.append(dialog);
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
        }),note);feedbackBody.append(article);
      }
      if(value.next_cursor)feedbackBody.append(button('下一页反馈',()=>feedbackInbox(ticket,value.next_cursor)));
    } catch {if(valid())feedbackBody.replaceChildren(node('h2','素材反馈待处理'),node('p','反馈列表暂时无法核验；不会把错误显示为没有反馈。'),button('重读反馈列表',()=>feedbackInbox(ticket)));}
  }
  async function show() {
    const ticket = ++generation; current = null; body.replaceChildren(node('p', '正在读取知识提案…'));
    if (!dialog.open) dialog.showModal();
    publication(ticket);feedbackInbox(ticket);
    const last = remembered(); if (last) body.append(button('核对上次决定', () => check(last, ticket)));
    try { const value = await call('preview'); if (isCurrent(ticket)) { render(value, ticket); if (last) body.append(button('核对上次决定', () => check(last, ticket))); } }
    catch { if (isCurrent(ticket)) { body.replaceChildren(node('p', '提案暂时无法读取或权限尚未接通；当前结果与原决定保留。')); if (last) body.append(button('核对上次决定', () => check(last, ticket))); } }
  }
  return {show};
})();
