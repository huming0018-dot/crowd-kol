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
  const labels={check_failed:'连接或身份核验失败，不代表账号登出',checking:'正在核验登录',logged_out:'已登出，采集暂停',waiting_login:'请在弹出的浏览器本人登录',resumed:'登录已恢复，可继续原任务',account_changed:'账号已更换，原任务保持暂停',identity_unverified:'登录可用，需确认是否原账号',unverified:'尚未核验登录',authenticated:'登录已核验'};
  const loginErrors={login_browser_timeout:'登录页或二维码等待超时，请打开原会话重试。',login_browser_closed:'登录窗口已关闭，请重新打开。',login_dependency_missing:'登录执行器缺少依赖，请检查设置。',login_flow_ended_before_verification:'登录流程结束，但尚未通过账号核验。',login_executor_failed:'登录执行器未完成核验，请重试；原任务仍保留。'};
  function proDiagnostic(value){
    if(!value||value.method!=='pro_official_self')return null;
    const phases={checking:'后台官方核验进行中',failed:'本次后台官方核验未通过',authenticated:'本次官方账号核验已通过'};
    const phase=phases[value.phase]||'本次后台核验状态未知';
    const integer=(x,min,max)=>Number.isInteger(x)&&x>=min&&x<=max;
    const request=(key,label)=>{
      const count=value[key+'_requests'];if(!integer(count,0,1))return label+'：请求次数未知';
      if(count===0)return label+'：尚未请求';
      const http=value[key+'_http_status'];let text=label+'：请求1次'+(integer(http,100,599)?'，HTTP '+http:'，响应状态未知');
      const code=value[key+'_business_code'];
      const bridge={0:'登录桥请求成功',1:'登录桥请求失败',2:'登录桥处理异常',3:'登录桥参数无效',4:'登录桥缺少参数',100:'原浏览器扩展未连接',101:'未取得本平台登录凭据',102:'登录凭据请求超时',103:'未找到原账号'};
      const official={0:'官方核验请求成功','-101':'官方提示未登录','-400':'官方请求不适用','-403':'官方拒绝访问','-412':'官方频率或访问限制'};
      const reasons=key==='bridge'?bridge:official;
      if(Number.isInteger(code)&&Object.hasOwn(reasons,String(code)))text+='，'+reasons[code]+'（'+code+'）';
      return text;
    };
    return phase+'；'+request('bridge','登录桥')+'；'+request('official_self','平台官方核验')+'。';
  }
  let generation=0,timer=null,sequence=0;
  dialog.addEventListener('close',()=>{generation++;clearTimeout(timer);browserDialog.close();});
  async function chooseBrowser(session,ticket,restartConnection=false,refreshTargets=false){
    const selection=++browserSequence;let choosing=false;
    const current=()=>ticket===generation&&selection===browserSequence&&browserDialog.open;
    browserDialog.replaceChildren(node('h2','使用已登录浏览器'),node('p','选择原账号所在的平台页面。系统随后核验账号，原浏览器和页面保留。'));
    const feedback=node('p');feedback.setAttribute('role','status');browserDialog.append(feedback,button('取消',()=>browserDialog.close()));browserDialog.showModal();
    let choices;try{choices=await call('browser_candidates',{session_id:session.session_id,port:9222,...(restartConnection?{restart_connection:true}:{}),...(refreshTargets?{refresh_targets:true}:{})});}
    catch(error){if(current())feedback.textContent=error.message==='browser_connection_pending'?'浏览器连接等待确认。请查看 Chrome 的“允许远程调试”提示；无需重新登录平台。':'原浏览器暂不可连接，请检查本机浏览器连接；不会自动改动浏览器。';return;}
    if(!current())return;
    if(choices.browser_connection_state==='pending'){
      feedback.textContent='浏览器连接正在等待原 Chrome 确认。请在原提示点“允许”，再继续；无需重新登录平台。';
      browserDialog.append(button('我已允许，继续核验',()=>guarded(()=>chooseBrowser(session,ticket))));return;
    }
    if(choices.browser_connection_state==='expired'){
      feedback.textContent='浏览器连接确认超时，原账号和页面仍保留。尚未核验登录，系统不会自动重连。';
      browserDialog.append(button('重新连接原浏览器',()=>guarded(()=>chooseBrowser(session,ticket,true))));return;
    }
    if(!choices.targets.length){feedback.textContent='没有识别到普通网页。请在原浏览器打开账号所在的平台页面，再刷新页面列表。';browserDialog.append(button('刷新页面列表',()=>guarded(()=>chooseBrowser(session,ticket,false,true))));return;}
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
      const unavailable=session.platform==='ks'&&session.login_verification_available===false&&session.login_diagnostic?.graphql_errors==='present';
      const row=node('article');row.className='task';row.append(node('h3',platformNames[session.platform]||session.platform),node('p',unavailable?'登录核验接口失败，登录状态尚未确认；已登录者无需重复扫码。':labels[session.state]||session.state));
      if(unavailable){const diagnostic={schema_validation:'当前核验请求与平台接口不兼容，不能据此认定账号登出。',authentication_required:'接口提示需要登录；原会话与任务保留。',rate_or_permission:'接口返回频率或权限限制，保持暂停。',unknown:'接口错误原因尚未定位，保留原会话与任务。'};row.append(node('p',diagnostic[session.login_diagnostic.graphql_error_kind]||diagnostic.unknown));}
      if(session.login_error_code)row.append(node('p',loginErrors[session.login_error_code]||'登录核验尚未完成。'));
      const diagnostic=proDiagnostic(session.login_diagnostic);if(diagnostic)row.append(node('p',diagnostic));
      const recovery=session.login_recovery;
      if(recovery?.kind==='cloud_pro')row.append(node('p','此账号属于原云端等待任务。复用当前原浏览器在后台核验；不会另开登录窗口，也不会自动继续已暂停任务。'));
      if(recovery?.kind==='blocked')row.append(node('p','原任务恢复上下文暂不可核对，请查看原任务；不会切换到其他登录方式。'));
      if(session.browser_connection)row.append(node('p','复用本人选择的已登录浏览器'));
      if(session.browser_connection_error)row.append(node('p','原浏览器连接暂不可用；任务仍保留，请恢复原窗口或重新选择。'));
      if(session.login_wait_reason==='verification_paused'&&session.login_in_progress===true)row.append(node('p','核验已暂停，原登录窗口保留。完成登录后点下方按钮继续核验。'));
      const actions=node('div');actions.className='actions';
      if(recovery?.kind==='cloud_pro'){
        const recover=button('复用原账号后台核验',()=>guarded(async()=>{
          recover.disabled=true;
          try{
            const result=await call('recover_cloud_login',{task_id:recovery.task_id,child_id:recovery.child_id});
            if(ticket!==generation||!dialog.open)return;
            await refresh(ticket);
            if(ticket===generation&&dialog.open)$('accounts_error').textContent=result.owner_continue_required?'正在后台核验；通过后请在原任务点继续，只使用剩余额度。':'正在后台核验；通过后按原任务的运行意图接续，只使用剩余额度。';
          }catch(error){if(ticket===generation&&dialog.open)$('accounts_error').textContent=error.message;}
          finally{recover.disabled=false;}
        }));recover.disabled=session.login_in_progress===true;actions.append(recover);
      }else if(recovery?.kind!=='blocked'){
        const openLogin=button('打开原会话登录',()=>guarded(async()=>{await operate('open_login',{session_id:session.session_id,platform:session.platform},ticket);}));
        openLogin.disabled=session.login_in_progress===true;actions.append(openLogin);
        const reuse=button('使用已登录浏览器',()=>guarded(()=>chooseBrowser(session,ticket)));reuse.disabled=session.login_in_progress===true;actions.append(reuse);
      }
      if(session.browser_connection&&!recovery){const original=button('使用持久会话并核验',()=>guarded(async()=>{
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
