'use strict';
(() => {
  const status=node('p');status.className='hint';status.setAttribute('role','status');
  $('runs').before(status);let pending=false;
  const health=node('p');health.className='hint';health.setAttribute('role','status');status.after(health);
  const delivery=node('details'),deliveryTitle=node('summary','待回传处理'),deliveryBody=node('div'),deliveryNotice=node('p');
  delivery.hidden=true;deliveryNotice.setAttribute('role','status');delivery.append(deliveryTitle,deliveryNotice,deliveryBody);$('runs').before(delivery);
  const deliveryRefresh=node('button','刷新回传状态');deliveryRefresh.type='button';deliveryRefresh.onclick=()=>refreshDelivery();delivery.append(deliveryRefresh);
  let deliveryPending=false,deliveryAction=false;
  const deliveryReasons={delivery_pending:'等待后台核对并回传原记录',quarantined_delivery:'这些记录已保留，修复原因后可按原编号重试',source_outcome_unknown:'来源执行结果尚未确认，当前不能恢复回传',invalid_capture_retry:'原记录选择已失效，请刷新后重试',delivery_retry_denied:'原任务状态或执行权限已变化，请核对任务后再恢复',delivery_resume_denied:'原任务暂不能恢复回传，请核对任务状态',cloud_controller_busy:'后台正在处理，请稍后刷新',invalid_capture:'记录格式不符合云端要求，需维护者修复后重试',invalid_capture_record:'记录字段未通过云端检查，需维护者修复后重试',invalid_machine_provenance:'记录来源校验未通过，需维护者核对',capture_hash_conflict:'原记录与云端记录不一致，需维护者核对',capture_size_limit:'记录超过接收大小，需要维护者处理',sensitive_capture:'记录未通过数据检查，需要维护者处理',invalid_local_capture:'本机保存的记录损坏，需要维护者核对',delivery_attempt_limit:'多次回传未确认，已保留原记录等待处理',cloud_outcome_unknown:'上次操作结果待核对，先刷新状态；不要重复提交',invalid_cloud_ack:'云端回执不完整，原记录继续保留',cloud_read_unavailable:'云端状态暂不可读，请稍后刷新',cloud_delivery_lease_unavailable:'暂不能核验原任务权限，请稍后刷新',cloud_delivery_lease_denied:'原任务权限已变化，需要核对后再回传',worker_revoked:'这台终端的授权已失效，请联系Owner恢复',principal_denied:'没有该任务的操作权限，请核对Owner连接',owner_authorization_required:'需要有效的Owner连接才能处理回传',task_scope_denied:'此记录不属于当前Owner任务',task_not_found:'原云端任务不可用，需要维护者核对',task_paused:'原任务已暂停，请先在任务列表继续',task_stopped:'原任务已停止，不能直接恢复回传',delivery_state_conflict:'记录状态已变化，请刷新后处理',capture_not_quarantined:'记录已在处理或已确认，请刷新状态',delivery_not_deferred:'原任务尚未进入回传恢复状态，请稍后刷新',delivery_recovery_busy:'后台正在处理，请稍后刷新',controller_busy:'后台正在处理，请稍后刷新',delivery_binding_mismatch:'记录与原任务绑定不符，需要维护者核对',delivery_retry_run_mismatch:'只能恢复同一个原任务的记录，请刷新后按任务处理',delivery_resume_required:'需先恢复原任务的回传权限',cloud_upgrade_required:'后台需要升级后才能恢复回传',cloud_configuration_required:'尚未连接云端Owner',delivery_recovery_unavailable:'回传恢复暂不可用，请刷新状态或联系维护者'};
  const deliveryReason=value=>Object.prototype.hasOwnProperty.call(deliveryReasons,value)?deliveryReasons[value]:'回传状态需要核对，请刷新或联系维护者';
  const number=value=>Number.isSafeInteger(value)&&value>=0?value:0;
  const platformNames={xhs:'小红书',xiaohongshu:'小红书',bili:'B站',bilibili:'B站',dy:'抖音',douyin:'抖音',ks:'快手',kuaishou:'快手',wb:'微博',weibo:'微博',zhihu:'知乎',tieba:'贴吧'};
  const captureIds=group=>Array.isArray(group.quarantined_capture_ids)&&group.quarantined_capture_ids.length<=2000&&group.quarantined_capture_ids.every(id=>typeof id==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id))&&new Set(group.quarantined_capture_ids).size===group.quarantined_capture_ids.length?group.quarantined_capture_ids:[];
  async function retryDelivery(group,button){
    if(deliveryAction||group.retry_allowed!==true)return;
    const ids=captureIds(group);if(!ids.length)return;
    deliveryAction=true;button.disabled=true;deliveryNotice.textContent='正在核对原任务和回执…';
    try{
      const value=await api('/api/cloud',{action:'retry_delivery',payload:{capture_ids:ids}});
      if(value.schema!=='crowd-delivery-retry-v1'||value.accepted!==true||value.state!=='queued'||!Array.isArray(value.requeued_capture_ids)||!value.requeued_capture_ids.every(id=>ids.includes(id))||new Set(value.requeued_capture_ids).size!==value.requeued_capture_ids.length)throw Error('cloud_outcome_unknown');
      deliveryNotice.textContent='原记录已重新排队，等待云端回执。';
    }catch(error){deliveryNotice.textContent=deliveryReason(error.message);}
    finally{deliveryAction=false;await refreshDelivery();}
  }
  async function refreshDelivery(){
    if(deliveryPending||deliveryAction||document.hidden)return;deliveryPending=true;
    try{
      const value=await api('/api/cloud',{action:'delivery_status',payload:{}});
      if(value.storage_scope==='local'){delivery.hidden=true;deliveryBody.replaceChildren();return;}
      delivery.hidden=false;deliveryBody.replaceChildren();
      if(value.available!==true){deliveryTitle.textContent='回传恢复入口待升级';deliveryBody.append(node('p','后台尚未提供恢复接口；原待回传记录保持。'));return;}
      if(value.schema!=='crowd-delivery-status-v1'||!Array.isArray(value.groups))throw Error('cloud_read_unavailable');
      const groups=value.groups.filter(group=>group&&typeof group==='object'),pendingCount=groups.reduce((sum,group)=>sum+number(group.pending),0),quarantined=groups.reduce((sum,group)=>sum+number(group.quarantined),0);
      deliveryTitle.textContent='待回传 '+pendingCount+' 条 · 需处理 '+quarantined+' 条';
      if(quarantined)delivery.open=true;
      if(!groups.length){deliveryBody.append(node('p','当前没有需要处理的回传记录。'));return;}
      deliveryBody.append(node('p','重试只回传已保存的原记录；后台先核对回执，并保留原记录和提交编号。'));
      for(const group of groups){
        const item=node('div');item.className='record';
        item.append(node('strong',(Object.prototype.hasOwnProperty.call(platformNames,group.platform)?platformNames[group.platform]:'采集任务')+' · '+(group.title?String(group.title).slice(0,120):'任务 '+String(group.task_id||'').slice(-8))));
        item.append(node('p','待回传 '+number(group.pending)+' 条 · 已确认 '+number(group.acknowledged)+' 条 · 需处理 '+number(group.quarantined)+' 条'));
        if(number(group.deferred))item.append(node('p',number(group.deferred)+' 条等待自动重试'+(typeof group.next_retry_at==='number'&&Number.isFinite(group.next_retry_at)?'，最早 '+new Date(group.next_retry_at*1000).toLocaleString():'')));
        const reasons=[...new Set([group.reason,...(Array.isArray(group.errors)?group.errors:[])].filter(Boolean))];
        for(const reason of reasons)item.append(node('p',deliveryReason(reason)));
        const ids=captureIds(group);
        if(number(group.quarantined)){
          const retry=node('button',ids.length?'重试这 '+ids.length+' 条回传':'暂不能重试');retry.type='button';retry.disabled=group.retry_allowed!==true||!ids.length;
          retry.onclick=()=>retryDelivery(group,retry);item.append(retry);
          if(retry.disabled&&!reasons.length)item.append(node('p','后台正在核对原任务，暂不能重试；请稍后刷新。'));
        }
        deliveryBody.append(item);
      }
    }catch(_error){delivery.hidden=false;deliveryTitle.textContent='待回传状态暂不可读';deliveryBody.replaceChildren();deliveryBody.append(node('p','暂不能确认回传状态，请稍后刷新；原记录继续保留。'));}
    finally{deliveryPending=false;}
  }
  const history=node('details'),historyTitle=node('summary','运行异常记录（最近 7 天）'),historyBody=node('div');
  history.append(historyTitle,historyBody);health.after(history);let healthPending=false;
  const participants=node('details'),participantsTitle=node('summary','参与者监控'),participantsBody=node('div');
  participants.append(participantsTitle,participantsBody);history.after(participants);let participantsPending=false;
  const otaLabels={unknown:'更新状态未知',ready:'更新已就绪',applied:'更新已应用',current:'版本已核对',checking:'正在检查更新',pending_reload:'等待重载',helper_unavailable:'更新助手不可用',error:'更新异常',rolled_back:'已回滚'};
  const normalReasons=new Set(['test_completed','user_stopped','daily_quota','session_rest','action_budget','action_gap','known_note','note_busy','test_quota','test_no_task','no_task']);
  const reasonLabels={test_completed:'本轮采集已完成',user_stopped:'本人已停止采集',daily_quota:'本日采集额度已用完',session_rest:'等待下一轮采集',action_budget:'本轮访问额度已用完',action_gap:'等待下一次来源访问',known_note:'内容已采集',note_busy:'内容正在由其他任务采集',test_quota:'本轮测试额度已用完',test_no_task:'等待可用测试任务',no_task:'等待可用任务',rate_limit:'平台限流，采集已暂停',captcha:'需要本人完成验证码',login_required:'需要重新登录',test_partial:'本轮仅取得部分内容',test_comments_partial:'评论仅取得部分内容'};
  const reasonLabel=value=>reasonLabels[value]||value;
  const sourceIssue=value=>Boolean(value&&!normalReasons.has(value));
  const participantIssue=row=>sourceIssue(row.error)||sourceIssue(row.kol_error)||row.ota_poll_error||row.ota_poll_query_error||['error','helper_unavailable'].includes(row.update_state);
  async function refreshParticipants(){if(participantsPending||document.hidden)return;participantsPending=true;
    try{const value=await api('/api/cloud',{action:'participant_health',payload:{}});participants.hidden=value.storage_scope!=='cloud';if(participants.hidden)return;
      const rows=value.participants||[],issues=rows.filter(row=>row.diagnostics_enabled&&(row.stale||participantIssue(row)));
      participantsTitle.textContent='参与者监控 · '+rows.length+' 人 · '+issues.length+' 人待处理';participantsBody.replaceChildren();
      participantsBody.append(node('p','云端诊断更新时间：'+(value.checked_at?new Date(value.checked_at).toLocaleString():'尚无记录')+'。超过 '+(value.stale_after_seconds||180)+' 秒未上报显示离线待核对；不证明采集已停止。'));
      for(const row of rows){const item=node('p'),id=String(row.user_id||'').slice(0,8);
        item.textContent=id+' · '+(!row.diagnostics_enabled?'监控未开启':(row.stale?'离线待核对':'最近有上报')+' · 版本 '+(row.version||'未知')+' · '+(row.enabled?'采集已启用':'采集已关闭')+' · 待回传 '+(row.queued??'未知')+' · '+(otaLabels[row.update_state]||'更新状态未知'));
        if(row.diagnostics_enabled){const reasons=[row.error,row.kol_error].filter(Boolean),errors=[...reasons.filter(sourceIssue),row.ota_poll_error,row.ota_poll_query_error].filter(Boolean),normal=reasons.filter(value=>!sourceIssue(value));if(normal.length)item.textContent+=' · 状态：'+normal.map(reasonLabel).join(' / ');if(errors.length)item.textContent+=' · 需要处理：'+errors.map(reasonLabel).join(' / ');}participantsBody.append(item);}
      if(!rows.length)participantsBody.append(node('p','还没有参与者诊断上报。不能将未上报设备判为验收通过。'));
      const events=(value.events||[]).filter(participantIssue).slice(0,30);if(events.length){participantsBody.append(node('h4','最近参与者异常'));
        for(const row of events)participantsBody.append(node('p',new Date(row.at).toLocaleString()+' · '+String(row.user_id||'').slice(0,8)+' · '+[row.error,row.kol_error,row.ota_poll_error,row.ota_poll_query_error,otaLabels[row.update_state]].filter(Boolean).map(reasonLabel).join(' / ')));}
    }catch(_error){participants.hidden=false;participantsTitle.textContent='参与者监控 · 查询失败，需处理';participantsBody.replaceChildren();participantsBody.append(node('p','云端诊断不可用；本机监控继续，不能据此判断其他设备正常。'));}finally{participantsPending=false;}}
  const errorLabels={scheduler_dead:'调度线程已停止',scheduler_stale:'调度长时间没有推进',cloud_lock_unavailable:'无法读取任务锁',cloud_scheduler_failed:'调度异常',cloud_worker_failed:'采集执行器异常',cloud_stop_persistence_failed:'停止状态未能保存',postprocessing_enqueue_failed:'文字稿处理未能入队',postprocessing_tick_failed:'文字稿处理待重试',health_observation_failed:'无法读取调度健康',health_history_unavailable:'运行历史无法保存或读取'};
  const timeLabel=value=>typeof value==='number'?new Date(value*1000).toLocaleString():'尚无记录';
  const abnormal=value=>value&&(value.health_error||value.postprocessing_error||value.last_error||value.stale||(value.scheduler_started&&!value.scheduler_alive&&!value.scheduler_closed));
  async function refreshHealth(){if(healthPending||document.hidden)return;healthPending=true;
    try{const value=await api('/api/health',{action:'status',payload:{}}),current=value.current;
      if(value.storage_scope!=='cloud'){health.textContent='本机模式；云端调度监控未启用。';history.hidden=true;return;}history.hidden=false;
      const monitorStale=typeof value.observed_at!=='number'||Date.now()/1000-value.observed_at>15;
      const problem=value.monitor_error||(!value.monitor_alive||monitorStale?'health_observation_failed':null)||current?.health_error;
      health.textContent=(problem?'需要处理：'+(errorLabels[problem]||problem):current?.scheduler_closed?'调度已关闭':current?.scheduler_started&&current.scheduler_alive?'调度运行中':'调度尚未启动')+' · 最近调度 '+timeLabel(current?.last_tick_at)+' · 最近成功 '+timeLabel(current?.last_success_at)+' · 待回传 '+(current?.pending||0);
      if(current?.postprocessing_error)health.textContent+=' · '+(errorLabels[current.postprocessing_error]||current.postprocessing_error);
      const events=value.incidents||(value.events||[]).filter(abnormal);historyTitle.textContent='运行异常记录（最近 7 天，最多保存 '+value.max_events+' 次状态变化） · '+(value.incident_count??events.length)+' 次，显示最近 '+events.length+' 次';historyBody.replaceChildren();
      for(const event of events){const row=node('p');row.textContent=timeLabel(event.at)+' · '+(errorLabels[event.health_error||event.postprocessing_error||event.last_error]||event.health_error||event.postprocessing_error||event.last_error||'调度健康异常')+' · 状态 '+(labels[event.phase]||event.phase)+' · 待回传 '+event.pending;historyBody.append(row);}
      if(!events.length)historyBody.append(node('p','当前保留的状态变化中没有异常；不代表未监控时段无故障。'));
    }catch(_error){health.textContent='需要处理：运行监控暂不可用。';}finally{healthPending=false;}}
  const labels={deferring_delivery:'正在保存待回传清单',idle:'等待云端任务',claiming:'正在领取云端任务',authorized:'已获云端分配',
    dispatching:'正在启动采集',running:'正在采集',importing:'正在保存采集结果',
    delivering:'正在回传云端',finishing:'正在确认云端回执',waiting_login:'等待原账号登录恢复',
    local_stop_unknown:'采集停止结果待核对'};
  async function refresh(){if(pending||document.hidden)return;pending=true;
    try{const value=await api('/api/cloud',{action:'status',payload:{}});
      $('storage_hint').textContent=value.storage_scope==='cloud'?'云端任务同步回执；历史资料保存在本机，与众包奖励分开。':'结果保存在本机，与众包奖励分开。';
      status.textContent=value.storage_scope==='cloud'?((value.outbox?.acknowledged||0)>0?'云端任务与回执已接通 · ':'云端任务已配置 · ')+(labels[value.phase]||value.phase)+' · 已确认回执 '+(value.outbox?.acknowledged||0)+' / 待回传 '+(value.outbox?.pending||0):'当前保存于本机；尚未连接云端任务。';
      if(value.waiting_login_count)status.textContent+=' · '+value.waiting_login_count+' 个平台等待登录';if(value.last_error)status.textContent+=' · 需要处理：'+value.last_error;
      if(value.health_error)status.textContent='需要处理：'+(errorLabels[value.health_error]||value.health_error)+' · 当前任务状态 '+(labels[value.phase]||value.phase);
    }catch(error){status.textContent='云端连接待核对：'+error.message;}finally{pending=false;}}
  refresh();setInterval(refresh,5000);
  refreshDelivery();setInterval(refreshDelivery,5000);
  refreshHealth();setInterval(refreshHealth,5000);
  refreshParticipants();setInterval(refreshParticipants,30000);
})();
