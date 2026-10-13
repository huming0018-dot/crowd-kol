'use strict';
(() => {
  const status=node('p');status.className='hint';status.setAttribute('role','status');
  $('connection').after(status);let pending=false;
  const health=node('p');health.className='hint';health.setAttribute('role','status');status.after(health);
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
  const labels={idle:'等待云端任务',claiming:'正在领取云端任务',authorized:'已获云端分配',
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
  refreshHealth();setInterval(refreshHealth,5000);
  refreshParticipants();setInterval(refreshParticipants,30000);
})();
