'use strict';
// Read-only fleet projection. Dispatch and receipts keep their existing contracts.
(() => {
  const panel=node('details'),heading=node('summary','云端任务与终端 · 正在读取'),body=node('div');
  panel.append(heading,body);$('runs').after(panel);
  const timeline=node('details'),timelineHeading=node('summary','采集步骤'),timelineBody=node('div');
  timeline.append(timelineHeading,timelineBody);panel.after(timeline);
  const local=node('details'),localHeading=node('summary','本机执行阶段'),localBody=node('div');
  local.append(localHeading,localBody);timeline.after(local);
  const platforms={xhs:'小红书',dy:'抖音',ks:'快手',bili:'B站',wb:'微博',zhihu:'知乎',tieba:'贴吧'};
  const states={delivery_pending:'等待回传，尚未完成',open:'等待分配',leased:'已领取，等待终端进度',complete:'本轮已完成',exhausted:'本轮已结束，未达目标',closed:'任务已关闭',running:'采集中',queued:'等待分配',active:'可分配',waiting:'待处理',completed:'本轮已结束',stopped:'已停止',paused:'已暂停',failed:'待处理',partial:'已有部分结果',unknown:'结果待核对',interrupted_unknown:'执行已中断，结果待核对',login_required:'等待原账号登录'};
  const login={ready:'登录可用',authenticated:'登录可用',resumed:'原账号已恢复',needs_login:'需本人重新登录',login_required:'需本人重新登录',verification:'需本人完成验证',unknown:'登录尚未核验'};
  const steps={deferring_delivery:'保存原回传清单并释放采集槽',claim:'领取任务',claiming:'领取任务',authorized:'任务已分配',session:'核验登录与执行会话',telemetry_gap:'步骤记录存在缺口',session_check:'核验登录',login_check:'核验登录',navigate:'打开采集页',navigation:'打开采集页',list:'读取列表',detail:'读取正文',comments:'读取评论',source_step:'来源步骤',comments_page:'读取评论页',comment_page:'读取评论页',media:'处理媒体',subtitle:'取得字幕',outbox:'保存待回传',upload:'上传结果',receipt:'核对回执',stop:'停止采集',ota:'自动更新',recovery:'恢复版本',idle:'等待任务',dispatching:'启动采集',running:'采集中',importing:'导入结果',delivering:'回传结果',finishing:'确认云端回执',waiting_login:'等待原账号登录',login_resumed:'原账号核验通过，等待重新领取',completed:'本轮云端交付已确认',paused:'本轮来源执行已停止',local_stop_unknown:'停止结果待核对',reconciling_no_dispatch:'核对未启动任务',state_unreadable:'无法读取执行状态'};
  const statuses={started:'开始',running:'进行中',completed:'已完成',succeeded:'已完成',success:'已完成',failed:'失败',error:'异常',waiting:'等待',paused:'已暂停',stopped:'已停止',pending:'待处理',received:'已确认',skipped:'跳过'};
  const reasons={pro_bili_wbi_unavailable:"B站签名参数暂不可用，采集已停止；不代表账号登出，请查看本机诊断。",pro_native_credentials_unavailable:"暂时无法复用原浏览器登录资料，采集已停止；不代表账号登出，请查看本机诊断。",pro_content_access_denied:"该内容访问被拒绝，采集已停止；不代表账号登出，请本人检查原页面。",pro_cookiebridge_unavailable:'原浏览器登录桥暂不可用；请恢复原浏览器扩展连接，当前不能判断平台是否登出。',pro_login_verification_failed:'连接或身份核验失败，采集已暂停；不代表账号登出，请查看诊断。',pro_self_check_unsupported:'该采集引擎暂不支持此平台登录核验，原采集方式保留。',login_required:'需本人重新登录',captcha:'需本人完成验证码',rate_limit:'平台限流，已暂停',source_outcome_unknown:'来源结果待核对',cloud_outcome_unknown:'云端回执待核对',telemetry_gap:'步骤记录存在缺口',user_stopped:'本人已停止',test_completed:'本轮已完成',no_task:'等待可用任务',task_full:'当前任务已分配完',session_rest:'等待下一轮',daily_quota:'本日额度已用完',action_gap:'等待下次来源访问',global_pause:'系统暂停，等待恢复'};
  const count=value=>Number.isSafeInteger(value)&&value>=0?String(value):'未统计';
  const short=value=>typeof value==='string'&&/^[a-zA-Z0-9:_-]{1,100}$/.test(value)?value.slice(-8):'未登记';
  const when=value=>{const date=new Date(typeof value==='number'?value*1000:value);return value&&Number.isFinite(date.getTime())?date.toLocaleString():'尚无记录';};
  const call=(action,payload={})=>api('/api/cloud',{action,payload});
  let pending=false,eventPending=false,localPending=false,cursor=0,rows=[],machineRows=[],machineError=null,checkedAt=null,allowedInstallations=null,lastHasMore=false;
  const sequences=new Map(),gaps=new Set();
  const problem=value=>['failed','waiting','unknown','interrupted_unknown','login_required','partial'].includes(value);
  function unavailable(value){return value.reason==='not_connected'?'尚未连接云端':value.reason==='upgrade_or_access_required'?'云端版本或访问权限待核对，尚未接通':'云端接口待升级，任务与步骤状态尚未接通';}
  async function refresh(){
    if(pending||document.hidden)return;pending=true;
    try{
      const [value,dispatches]=await Promise.all([call('unified_status',{limit:100}),call('unified_dispatches').catch(()=>null)]);
      if(!value.available){heading.textContent='云端任务与终端 · '+unavailable(value);body.replaceChildren();return;}
      if(value.schema!=='crowd-unified-status-v1'||!Array.isArray(value.tasks)||!Array.isArray(value.nodes))throw Error('invalid_projection');
      const tasks=value.tasks,nodes=value.nodes,issues=nodes.filter(row=>row.stale||['needs_login','login_required','verification'].includes(row.login_state));
      allowedInstallations=new Set(nodes.filter(row=>row.diagnostics_enabled===true&&typeof row.installation_id==='string').map(row=>row.installation_id));
      rows=rows.filter(row=>allowedInstallations.has(row.installation_id));
      for(const id of sequences.keys())if(!allowedInstallations.has(id)){sequences.delete(id);gaps.delete(id);}
      renderEvents(lastHasMore);
      heading.textContent='云端任务 '+tasks.length+' 个 · 终端 '+nodes.length+' 个 · '+issues.length+' 个终端需处理';
      body.replaceChildren(node('p','更新时间：'+when(value.checked_at)+'。此列表展示最近最多 100 个任务和终端；已收数量以云端回执为准。'));
      const dispatchList=node('section');dispatchList.append(node('h3','统一派发'));
      if(dispatches?.available===true&&dispatches.schema==='crowd-unified-dispatch-list-v1'&&Array.isArray(dispatches.dispatches)){
        for(const dispatch of dispatches.dispatches.slice(0,20)){
          const row=node('p');row.textContent='派发 '+short(dispatch.dispatch_id)+' · '+when(dispatch.created_at)+' · '+(dispatch.created===true?'已保存；执行结果见下方任务':'派发状态待核对');
          for(const route of dispatch.routes||[])row.append(node('small',' · '+(platforms[route.platform]||'平台待核对')+'：'+(route.execution_kind==='participant_extension'?'参与者终端':'采集机器')+' · '+(states[route.state]||'状态待核对')+' · 内容配置 '+count(route.item_quota)));
          dispatchList.append(row);
        }
        if(!dispatches.dispatches.length)dispatchList.append(node('p','尚无统一派发记录；旧任务继续保留。'));
      }else dispatchList.append(node('p','统一派发记录暂不可用；旧任务状态继续显示。'));
      body.append(dispatchList);
      const taskList=node('div');taskList.append(node('h3','任务'));
      for(const task of tasks){
        const item=node('p'),title=typeof task.title==='string'?task.title.slice(0,120):'';item.textContent=(task.execution_kind==='participant_extension'?'参与者':'机器')+'任务 '+short(task.logical_task_id)+(title?' · '+title:'')+' · '+(task.platforms||[]).map(p=>platforms[p]||'待识别平台').join(' / ')+' · '+(states[task.state]||'状态待核对')+' · 正文已收 '+count(task.received)+' · 评论 '+count(task.comments);
        if(problem(task.state))item.className='error';taskList.append(item);
      }
      if(!tasks.length)taskList.append(node('p','当前没有云端任务。'));
      body.append(taskList,node('h3','终端'));
      for(const row of nodes){
        const item=node('p'),version=typeof row.version==='string'&&/^\d+(?:\.\d+){1,3}$/.test(row.version)?row.version:'未知';
        const updated=when(row.updated_at),age=Date.parse(value.checked_at)-Date.parse(row.updated_at),fresh=row.stale===false&&updated!=='尚无记录'&&Number.isFinite(age)&&age>=-60000&&age<=180000;
        item.textContent=short(row.installation_id||row.node_id)+' · '+(row.stale===true?'离线待核对':fresh?'最近有上报':'上报状态待核验')+' · '+(row.enabled===false?'采集已关闭':'采集启用状态见任务')+' · '+(login[row.login_state]||'登录尚未核验')+' · 版本 '+version+' · 上报 '+updated;
        if(row.stale||['needs_login','login_required','verification'].includes(row.login_state))item.className='error';
        if(row.diagnostics_enabled===false)item.textContent+=' · 未开启诊断';
        body.append(item);
      }
      if(!nodes.length)body.append(node('p','还没有终端登记，不能视为两设备验收通过。'));
      body.append(node('p','参与者步骤只覆盖已升级且开启诊断的终端；机器控制阶段与Pro已保存分页同步云端；其他引擎逐页覆盖仍待核验。本机记录另行显示。'));
    }catch(_error){heading.textContent='云端任务与终端 · 查询失败，状态待核对';body.replaceChildren(node('p','无法读取最新状态；不会据此判定终端正常或重新发送任务。'));}
    finally{pending=false;}
  }
  function renderEvents(more){
    timelineBody.replaceChildren(node('p','云端更新时间：'+when(checkedAt)+' · 参与者保留最近7天；机器面板显示最近60条，云端保留范围另行核验。'+(more?'正在继续读取后续记录；当前尚未追平。':'')));
    if(gaps.size)timelineBody.append(node('p','有 '+gaps.size+' 个终端的步骤序号曾有跳跃或更早记录未保留，需核对补传完整性。'));
    for(const row of rows.slice(-60).reverse()){
      const item=node('p');item.textContent=when(row.occurred_at||row.received_at)+' · 终端 '+short(row.installation_id)+' · 任务 '+short(row.logical_task_id)+' · '+(steps[row.step]||'未识别步骤')+'：'+(statuses[row.status]||'状态待核对');
      if(row.error_code)item.textContent+=' · '+(reasons[row.error_code]||'异常代码待核对');
      if(Number.isFinite(row.duration_ms)&&row.duration_ms>=0)item.textContent+=' · '+(row.duration_ms/1000).toFixed(2)+' 秒';
      timelineBody.append(item);
    }
    for(const row of machineRows.slice(-60).reverse()){
      const event=row.event||{},item=node('p');item.textContent=when(row.received_at)+' · 机器 '+short(row.worker_id)+' · 任务 '+short(row.task_id)+' · run '+short(row.run_id)+' / epoch '+count(row.lease_epoch)+' · '+(steps[event.phase]||'状态待核对')+(event.outcome?' · '+(states[event.outcome]||'结果待核对'):'');
      const runReasons={"pro_signer_wrapper_changed":"签名服务版本校验不一致，采集尚未启动","pro_signer_source_changed":"签名服务源码校验不一致","pro_cookiebridge_unavailable":"原浏览器登录桥暂不可用，并非确认登出","pro_login_verification_failed":"官方身份核验未通过，请查看账号诊断","pro_self_check_unsupported":"此引擎暂不支持该平台身份核验","pro_account_changed":"账号身份已改变，等待原账号确认","pro_weibo_reply_target_invalid":"微博回复归属未能完整核实","wb_embedded_replies_incomplete":"微博子回复尚未完整保存","phase_observation_failed":"本地运行状态读取失败","run_completed":"来源执行已完成","run_stopped":"来源执行已停止","run_failure_unclassified":"来源执行失败，详细原因待本机诊断","run_outcome_unknown":"来源执行结果未知，不能重复派发","login_required":"平台要求本人登录","pro_content_access_denied":"该内容访问被拒绝，采集已停止；不代表账号登出，请本人检查原页面。","pro_native_credentials_unavailable":"未能复用原浏览器凭据，不能据此判定登出","pro_bili_wbi_unavailable":"B站签名参数未能通过核验","native_provider_profile_mode_unverified":"原浏览器凭据读取方式尚未核实，已停止读取","native_provider_credentials_unavailable":"未取得可用登录资料，不能据此判定登出","native_provider_profile_busy":"原浏览器资料正在使用，未读取凭据","native_provider_busy":"原浏览器凭据连接正在使用","native_provider_browser_unavailable":"原浏览器凭据连接暂不可用","native_provider_unavailable":"原浏览器凭据核验未完成，原因待本机检查","pro_existing_cdp_credentials_unavailable":"现有浏览器连接未取得可用凭据，不能据此判定登出","native_provider_profile_invalid":"原浏览器资料位置未通过核验","native_provider_session_invalid":"原账号会话绑定未通过核验","native_provider_profile_missing":"未找到已绑定的原浏览器资料","native_provider_mc_missing":"原凭据读取依赖未就绪","native_provider_lock_invalid":"原浏览器凭据锁未通过核验","native_provider_cookie_scope_invalid":"登录凭据的平台范围未通过核验","native_provider_cookie_shape_invalid":"登录资料格式未通过核验","native_provider_persistence_unavailable":"原浏览器资料持久化状态未确认","native_provider_retry_forbidden":"本次凭据读取结果未知，禁止自动重试","native_provider_exit_observer_unavailable":"本机凭据子进程退出核验不可用","native_provider_ownership_lost":"凭据读取进程归属待核对","native_provider_cleanup_unknown":"凭据读取清理结果未知，禁止重复启动"};
      if(typeof event.error_code==='string'&&Object.hasOwn(runReasons,event.error_code)){item.append(node('small',' · '+runReasons[event.error_code]));if(Number.isSafeInteger(event.exit_code)&&event.exit_code>=-128&&event.exit_code<=255)item.append(node('small',' · 退出码 '+event.exit_code));}
      if(event.source_stage){const stages={request_started:'请求已开始',response_received:'收到来源响应',request_failed:'来源请求失败',page_received:'收到评论页，尚未确认保存',content_saved:'正文已保存并回读核对',page_partially_saved:'本页已保存选中部分',page_saved:'评论页已保存并回读核对',store_failed:'本地保存失败',monitor_failed:'监控记录失败'};if(stages[event.source_stage])item.append(node('small',' · '+stages[event.source_stage]));}
      for(const [key,label] of [['source_sequence','来源步骤序号'],['api_attempts','HTTP尝试'],['http_status','HTTP状态'],['page_index','分页序号'],['saved_pages','已保存分页'],['saved_rows','分页记录观测数'],['acknowledged','云回执'],['pending','待回传']])if(Number.isSafeInteger(event[key]))item.append(node('small',' · '+label+' '+count(event[key])));
      const sourceScopes={request:'来源请求',content:'正文',root:'根评论页',reply:'回复页'};
      if(typeof event.scope==='string'&&Object.hasOwn(sourceScopes,event.scope)){item.append(node('small',' · '+sourceScopes[event.scope]));if(['root','reply'].includes(event.scope))item.append(node('small',' · 检查点'+(event.checkpoint_committed===true?'已提交':'未确认提交')));}
      timelineBody.append(item);
    }
    if(machineError)timelineBody.append(node('p','机器步骤查询失败；显示记录可能过期，不据此重发任务。'));
    if(!rows.length&&!machineRows.length)timelineBody.append(node('p','尚未收到步骤记录；只有健康心跳不代表完成采集。'));
  }
  async function refreshEvents(){
    if(eventPending||document.hidden)return;eventPending=true;
    try{
      const value=await call('node_events',{after_id:cursor,limit:200});
      if(!value.available){timelineHeading.textContent='采集步骤 · '+unavailable(value);timelineBody.replaceChildren();return;}
      if(value.schema!=='crowd-node-events-v1'||!Array.isArray(value.events)||!Number.isSafeInteger(value.cursor)||value.cursor<cursor)throw Error('invalid_events');
      if(Array.isArray(value.machine_events))machineRows=value.machine_events.filter(row=>Number.isSafeInteger(row.id)&&typeof row.run_id==='string'&&row.event&&typeof row.event==='object').slice(-200);
      machineError=value.machine_events_error||null;
      let latest=cursor;
      for(const row of value.events){
        if(!Number.isSafeInteger(row.id)||row.id<=latest||!Number.isSafeInteger(row.node_seq)||row.node_seq<1||typeof row.installation_id!=='string')throw Error('invalid_events');
        latest=row.id;
      }
      if(value.cursor!==latest)throw Error('invalid_cursor');
      const visible=value.events.filter(row=>allowedInstallations===null||allowedInstallations.has(row.installation_id));
      for(const row of visible){const prior=sequences.get(row.installation_id)||0;if(row.node_seq>prior+1)gaps.add(row.installation_id);sequences.set(row.installation_id,Math.max(prior,row.node_seq));}
      rows=[...rows,...visible].slice(-200);cursor=value.cursor;checkedAt=value.checked_at;lastHasMore=value.has_more===true;
      timelineHeading.textContent='采集步骤 · 已读取至 '+cursor+' · '+(value.has_more?'仍有后续记录':'已读取本次返回记录');renderEvents(value.has_more);
    }catch(_error){timelineHeading.textContent='采集步骤 · 查询失败，已显示记录可能过期';}
    finally{eventPending=false;}
  }
  async function refreshLocal(){
    if(localPending||document.hidden)return;localPending=true;
    try{
      const value=await call('workflow_events');local.hidden=value.coverage==='not_connected';if(local.hidden)return;
      localHeading.textContent='本机执行阶段 · '+(value.monitor_error?'记录不可用，需处理':count(value.event_count)+' 条保留记录');
      localBody.replaceChildren(node('p','仅记录本机控制器阶段变化，保存在此设备；不包含每个来源请求，尚未同步到云端。'));
      if(value.truncated)localBody.append(node('p','更早阶段已超出保留窗口；当前记录不是完整历史。'));
      for(const row of value.events||[])localBody.append(node('p',when(row.at)+' · '+(platforms[row.platform]||'调度')+' · 任务 '+short(row.task_id)+' · '+(steps[row.phase]||'状态待核对')));
      if(!(value.events||[]).length)localBody.append(node('p','尚无本机阶段记录。'));
    }catch(_error){localHeading.textContent='本机执行阶段 · 查询失败，需处理';}
    finally{localPending=false;}
  }
  refresh();refreshEvents();refreshLocal();
  setInterval(refresh,5000);setInterval(refreshEvents,5000);setInterval(refreshLocal,5000);
})();
