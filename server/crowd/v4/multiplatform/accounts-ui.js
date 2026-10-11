'use strict';
const accountView = (() => {
  const call=(action,payload={})=>api('/api/accounts',{action,payload});
  const dialog=node('dialog');dialog.id='accounts_dialog';dialog.setAttribute('aria-labelledby','accounts_title');
  dialog.innerHTML='<div class="dialog-head"><h2 id="accounts_title">平台登录</h2><button id="accounts_close">关闭</button></div><div class="dialog-body"><p>登录失效会暂停采集。用原账号重新登录并通过核验后，系统继续原任务的剩余范围；切换账号需另建任务。</p><p id="accounts_error" role="status"></p><div id="accounts_list"></div></div>';
  document.body.append(dialog);
  const openButton=button('平台登录',()=>guarded(open));$('open_settings').before(openButton);
  $('accounts_close').onclick=()=>dialog.close();
  const labels={check_failed:'登录核验失败，请重试',checking:'正在核验登录',logged_out:'已登出，采集暂停',waiting_login:'请在弹出的浏览器本人登录',resumed:'登录已恢复，可继续原任务',account_changed:'账号已更换，原任务保持暂停',identity_unverified:'登录可用，需确认是否原账号',unverified:'尚未核验登录',authenticated:'登录已核验'};
  let generation=0,timer=null,sequence=0;
  dialog.addEventListener('close',()=>{generation++;clearTimeout(timer);});
  async function operate(action,payload,ticket){try{await call(action,payload);}catch(error){if(ticket===generation&&dialog.open)$('accounts_error').textContent=error.message;return;}if(ticket===generation&&dialog.open)await refresh(ticket);}
  async function refresh(ticket){
    clearTimeout(timer);const current=++sequence;
    let result;try{result=await call('list');}catch(error){if(ticket===generation&&current===sequence&&dialog.open){$('accounts_error').textContent=error.message;timer=setTimeout(()=>guarded(()=>refresh(ticket)),3000);}return;}
    if(ticket!==generation||current!==sequence||!dialog.open)return;
    $('accounts_error').textContent='';$('accounts_list').replaceChildren();
    for(const session of result.sessions){
      const row=node('article');row.className='task';row.append(node('h3',platformNames[session.platform]||session.platform),node('p',labels[session.state]||session.state));
      const actions=node('div');actions.className='actions';
      actions.append(button('打开原会话登录',()=>guarded(async()=>{await operate('open_login',{session_id:session.session_id,platform:session.platform},ticket);})));
      if(session.state==='identity_unverified')actions.append(button('确认仍是原账号',()=>guarded(async()=>{await operate('confirm_same_account',{session_id:session.session_id,expected_generation:session.generation,confirm_same_account:true},ticket);})));
      if(session.state==='waiting_login'||session.state==='checking')actions.append(button('取消登录',()=>guarded(async()=>{await operate('cancel_login',{session_id:session.session_id},ticket);})));
      if(session.state==='account_changed')row.append(node('p','请创建独立会话或新任务；原账号的剩余额度和结果不会转给新账号。'));
      row.append(actions);$('accounts_list').append(row);
    }
    if(!result.sessions.length)$('accounts_list').append(node('p','还没有平台会话。首次建任务时会打开登录页。'));
    timer=setTimeout(()=>guarded(()=>refresh(ticket)),3000);
  }
  async function open(){generation++;clearTimeout(timer);$('accounts_error').textContent='';dialog.showModal();await refresh(generation);}
  return {open};
})();
