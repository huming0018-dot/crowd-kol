'use strict';
const accountView = (() => {
  const call=(action,payload={})=>api('/api/accounts',{action,payload});
  const dialog=node('dialog');dialog.id='accounts_dialog';dialog.setAttribute('aria-labelledby','accounts_title');
  dialog.innerHTML='<div class="dialog-head"><h2 id="accounts_title">平台登录</h2><button id="accounts_close">关闭</button></div><div class="dialog-body"><p>登录失效会暂停采集。用原账号重新登录并通过核验后，系统继续原任务的剩余范围；切换账号需另建任务。</p><p id="accounts_error" role="status"></p><div id="accounts_list"></div></div>';
  document.body.append(dialog);
  const browserDialog=node('dialog');browserDialog.id='accounts_browser_dialog';browserDialog.setAttribute('aria-label','使用已登录浏览器');
  document.body.append(browserDialog);
  let browserSequence=0;browserDialog.addEventListener('close',()=>{browserSequence++;});
  const openButton=button('平台登录',()=>guarded(open));$('open_settings').before(openButton);
  $('accounts_close').onclick=()=>dialog.close();
  const labels={check_failed:'登录核验失败，请重试',checking:'正在核验登录',logged_out:'已登出，采集暂停',waiting_login:'请在弹出的浏览器本人登录',resumed:'登录已恢复，可继续原任务',account_changed:'账号已更换，原任务保持暂停',identity_unverified:'登录可用，需确认是否原账号',unverified:'尚未核验登录',authenticated:'登录已核验'};
  const loginErrors={login_browser_timeout:'登录页或二维码等待超时，请打开原会话重试。',login_browser_closed:'登录窗口已关闭，请重新打开。',login_dependency_missing:'登录执行器缺少依赖，请检查设置。',login_flow_ended_before_verification:'登录流程结束，但尚未通过账号核验。',login_executor_failed:'登录执行器未完成核验，请重试；原任务仍保留。'};
  let generation=0,timer=null,sequence=0;
  dialog.addEventListener('close',()=>{generation++;clearTimeout(timer);browserDialog.close();});
  async function chooseBrowser(session,ticket){
    const selection=++browserSequence;let choosing=false;
    const current=()=>ticket===generation&&selection===browserSequence&&browserDialog.open;
    browserDialog.replaceChildren(node('h2','使用已登录浏览器'),node('p','选择原账号所在的平台页面。系统随后核验账号，原浏览器和页面保留。'));
    const feedback=node('p');feedback.setAttribute('role','status');browserDialog.append(feedback,button('取消',()=>browserDialog.close()));browserDialog.showModal();
    let choices;try{choices=await call('browser_candidates',{session_id:session.session_id,port:9222});}
    catch(error){if(current())feedback.textContent='原浏览器暂不可连接，请检查本机浏览器连接；不会自动改动浏览器。';return;}
    if(!current())return;
    if(!choices.targets.length){feedback.textContent='没有识别到普通网页。请在原浏览器打开任意正常网页，再重新选择。';return;}
    for(const target of choices.targets){
      const selected=button((target.selection_kind==='context_anchor'?'已打开的浏览器页面':(platformNames[session.platform]||session.platform)+'页面')+' '+target.page_number,()=>guarded(async()=>{
        if(!current()||choosing)return;choosing=true;
        selected.disabled=true;
        try{
          const bound=await call('create_browser_session',{platform:session.platform,port:choices.port,target_id:target.target_id,browser_fingerprint:choices.browser_fingerprint});
          if(!current())return;
          await call('open_login',{session_id:bound.session_id,platform:session.platform});
          if(current()){browserDialog.close();await refresh(ticket);}
        }catch(error){if(current()){feedback.textContent=error.message;selected.disabled=false;choosing=false;}}
      }));browserDialog.append(selected);
    }
  }
  async function operate(action,payload,ticket){try{await call(action,payload);}catch(error){if(ticket===generation&&dialog.open)$('accounts_error').textContent=error.message;return;}if(ticket===generation&&dialog.open)await refresh(ticket);}
  async function refresh(ticket){
    clearTimeout(timer);const current=++sequence;
    let result;try{result=await call('list');}catch(error){if(ticket===generation&&current===sequence&&dialog.open){$('accounts_error').textContent=error.message;timer=setTimeout(()=>guarded(()=>refresh(ticket)),3000);}return;}
    if(ticket!==generation||current!==sequence||!dialog.open)return;
    $('accounts_error').textContent='';$('accounts_list').replaceChildren();
    for(const session of result.sessions){
      const row=node('article');row.className='task';row.append(node('h3',platformNames[session.platform]||session.platform),node('p',labels[session.state]||session.state));
      if(session.login_error_code)row.append(node('p',loginErrors[session.login_error_code]||'登录核验尚未完成。'));
      if(session.browser_connection)row.append(node('p','复用本人选择的已登录浏览器'));
      if(session.browser_connection_error)row.append(node('p','原浏览器连接暂不可用；任务仍保留，请恢复原窗口或重新选择。'));
      if(session.login_wait_reason==='verification_paused'&&session.login_in_progress===true)row.append(node('p','核验已暂停，原登录窗口保留。完成登录后点下方按钮继续核验。'));
      const actions=node('div');actions.className='actions';
      const openLogin=button('打开原会话登录',()=>guarded(async()=>{await operate('open_login',{session_id:session.session_id,platform:session.platform},ticket);}));
      openLogin.disabled=session.login_in_progress===true;actions.append(openLogin);
      const reuse=button('使用已登录浏览器',()=>guarded(()=>chooseBrowser(session,ticket)));reuse.disabled=session.login_in_progress===true;actions.append(reuse);
      if(session.browser_connection){const original=button('使用持久会话并核验',()=>guarded(async()=>{
        await call('use_persistent_browser',{session_id:session.session_id,expected_generation:session.generation});
        if(ticket!==generation||!dialog.open)return;
        await operate('open_login',{session_id:session.session_id,platform:session.platform},ticket);
      }));original.disabled=session.login_in_progress===true;actions.append(original);}
      if(session.login_wait_reason==='verification_paused'&&session.login_in_progress===true)actions.append(button('我已登录，继续核验',()=>guarded(async()=>{await operate('resume_verification',{session_id:session.session_id},ticket);})));
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
