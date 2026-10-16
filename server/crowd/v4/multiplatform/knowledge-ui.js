'use strict';
// Uses existing host api/node/button helpers and its Owner Origin/CSRF boundary.
const knowledgeView = (() => {
  const call = (action, payload = {}) => api('/api/knowledge', {action, payload});
  const dialog = node('dialog'), body = node('div'), close = button('关闭', () => dialog.close());
  dialog.setAttribute('aria-label', '知识提案审核'); body.className = 'dialog-body';
  dialog.append(close, body); document.body.append(dialog);
  let generation = 0, busy = false, current = null;
  const storageKey = 'crowd:knowledge:pending-intent';
  dialog.addEventListener('close', () => { generation++; current = null; });
  const isCurrent = ticket => ticket === generation && dialog.open;
  function remembered() { try { return localStorage.getItem(storageKey); } catch { return null; } }
  function remember(id) { try { localStorage.setItem(storageKey, id); } catch { /* Server intent remains durable. */ } }
  function details(label, value) { const d = node('details'); d.append(node('summary', label), node('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2))); return d; }
  async function check(id, ticket) {
    try { const result = await call('status', {intent_id:id}); if (isCurrent(ticket)) body.append(node('p', result.message)); }
    catch { if (isCurrent(ticket)) body.append(node('p', '原决定状态暂时无法读取，请稍后核对；不会自动重发。')); }
  }
  function render(value, ticket) {
    current = value; body.replaceChildren(node('h2', '查看知识改动'), node('p', value.notice));
    const labels = {address:'地址核验',current_status:'营业核验'};
    body.append(node('p', '本次影响：'+Object.entries(value.added_unknowns).map(([key,count]) => (labels[key] || key)+'新增'+count+'项待确认').join('；')+'。其他内容是否保持请查看下方证据。'));
    body.append(node('p', '采用仅记录批准。发布生效、结果版本切换另行处理。'));
    for (const file of value.files) if (file.changed) body.append(details(file.name+' 改动', file.diff));
    body.append(details('来源与证据', {gap:value.observed_gap,evidence:value.evidence_refs,quotes:value.quotes_preserved,sources:value.source_versions_preserved}));
    body.append(details('版本与审核边界', {proposal_id:value.proposal_id,candidate_hash:value.candidate_hash,role:value.role_state,principal:value.principal_kind,human_uid:value.human_uid}));
    const label = node('label', '审核理由'), reason = node('textarea'); reason.maxLength = 2000; reason.required = true; label.append(reason); body.append(label);
    const note = node('p'); note.setAttribute('role', 'status'); body.append(note); const buttons = [];
    async function decide(decision) {
      if (busy || !isCurrent(ticket)) return;
      if (!reason.value.trim()) { note.textContent = '请填写本次决定的理由。'; reason.focus(); return; }
      busy = true; buttons.forEach(b => b.disabled = true);
      const intent = crypto.randomUUID(); remember(intent);
      const payload = {decision,reason:reason.value.trim(),expected_candidate_hash:value.candidate_hash,preview_token:value.preview_token,intent_id:intent};
      note.textContent = '正在记录决定…';
      try { const result = await call('decide', payload); if (isCurrent(ticket)) note.textContent = result.message; }
      catch { if (isCurrent(ticket)) { note.textContent = '决定结果待核对，请保留原记录；不会自动再次提交。'; body.append(button('核对原决定', () => check(intent, ticket))); } }
      finally { busy = false; /* A new decision requires reopening a fresh preview. */ }
    }
    for (const [key, text] of [['approved','采用'],['request_changes','退回修改'],['rejected','不采用']]) {
      const b = button(text, () => decide(key)); b.disabled = !value.decision_available || !value.actions?.[key]?.enabled; buttons.push(b); body.append(b);
    }
  }
  async function show() {
    const ticket = ++generation; current = null; body.replaceChildren(node('p', '正在读取知识提案…'));
    if (!dialog.open) dialog.showModal();
    const last = remembered(); if (last) body.append(button('核对上次决定', () => check(last, ticket)));
    try { const value = await call('preview'); if (isCurrent(ticket)) { render(value, ticket); if (last) body.append(button('核对上次决定', () => check(last, ticket))); } }
    catch { if (isCurrent(ticket)) { body.replaceChildren(node('p', '提案暂时无法读取或权限尚未接通；当前结果与原决定保留。')); if (last) body.append(button('核对上次决定', () => check(last, ticket))); } }
  }
  return {show};
})();
