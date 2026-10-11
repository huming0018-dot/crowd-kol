'use strict';
(() => {
  const status=node('p');status.className='hint';status.setAttribute('role','status');
  $('connection').after(status);let pending=false;
  const labels={idle:'等待云端任务',claiming:'正在领取云端任务',authorized:'已获云端分配',
    dispatching:'正在启动采集',running:'正在采集',importing:'正在保存采集结果',
    delivering:'正在回传云端',finishing:'正在确认云端回执',waiting_login:'等待原账号登录恢复',
    local_stop_unknown:'采集停止结果待核对'};
  async function refresh(){if(pending||document.hidden)return;pending=true;
    try{const value=await api('/api/cloud',{action:'status',payload:{}});
      $('storage_hint').textContent=value.storage_scope==='cloud'?'云端任务同步回执；历史资料保存在本机，与众包奖励分开。':'结果保存在本机，与众包奖励分开。';
      status.textContent=value.storage_scope==='cloud'?((value.outbox?.acknowledged||0)>0?'云端任务与回执已接通 · ':'云端任务已配置 · ')+(labels[value.phase]||value.phase)+' · 已确认回执 '+(value.outbox?.acknowledged||0)+' / 待回传 '+(value.outbox?.pending||0):'当前保存于本机；尚未连接云端任务。';
      if(value.waiting_login_count)status.textContent+=' · '+value.waiting_login_count+' 个平台等待登录';if(value.last_error)status.textContent+=' · 需要处理：'+value.last_error;
    }catch(error){status.textContent='云端连接待核对：'+error.message;}finally{pending=false;}}
  refresh();setInterval(refresh,5000);
})();
